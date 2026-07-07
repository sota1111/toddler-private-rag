# ProtoPedia 投稿用マークダウン — おたよりナビ

> 本ファイルは [ProtoPedia](https://protopedia.net/) 投稿フォーム記入用のテキストです。
> 「システム構成」と「ストーリー（①課題と背景 / ②想定ユーザー / ③プロダクトの特徴）」を、
> そのままコピーして貼り付けられる形でまとめています。
>
> 記述はすべて本リポジトリの実装（`README.md` / `backend/app/` / `backend/remediation_function/` /
> `infra/terraform/` / `.github/workflows/`）に基づく事実です。詳細な設計資料は
> [`docs/architecture.md`](./architecture.md)、作品ストーリーの原文は [`docs/story.md`](./story.md) を参照してください。
>
> - 🚀 ライブデモ: <https://toddler-private-rag-frontend-iqrm6wvhfq-an.a.run.app/tasks>
> - 🎥 紹介動画: <https://www.youtube.com/watch?v=yt0ke4QzjhE>

---

# システム構成

保育園のおたよりを「撮るだけ」で、AIエージェントが *OCR → 構造化 → 公式手順の自律調査 → 締切逆算のタスク生成*
を一気通貫で実行する、Google Cloud 上のフルサイクル運用アプリです。

## コンテナ構成（Cloud Run 3 + 1 サービス）

実行基盤は **Cloud Run による 3 + 1 サービス構成**です。AI 重処理を行う `backend` と、アップロード受付を行う
`upload-api` を分離することで、UI をブロックしない非同期取り込みを実現します。

| サービス | 役割 | 技術 |
| -- | -- | -- |
| `frontend` | SPA 配信 | React 19 + TypeScript / Vite / Tailwind / TanStack Query / React Router 7 / nginx |
| `upload-api` | アップロード即受領（GCS 保存 → backend worker 呼出 → 202 即応答） | 軽量 FastAPI |
| `backend` | OCR / 抽出 / エージェント / RAG / 認証 | FastAPI（Python 3.12）+ google-genai + Cloud Vision |
| `remediation`（既定OFF / opt-in） | 自律ロールバック判定 + 決定論的ポストモーテム | functions-framework（`backend/app` 非依存） |

> `remediation` は `var.enable_autonomous_rollback = false`（既定）では**一切作成されず**、アラートはメール通知のみ。
> 安全側デフォルトの opt-in サービスです。

## 中核: AIエージェントの自律ループ

中核は提出書類先回りエージェント（`backend/app/submission_agent.py`）で、保護者が毎回行っていた
「読む → 調べる → 逆算する」という多段の判断を自律的に実行します。単なる LLM ラッパーやチャットではなく、
*判断してタスクを生成し実行する*点に「AIエージェントである必然性」があります。

処理フロー:

1. **OCR** — Cloud Vision（fallback: pytesseract / pdf2image）
2. **構造化抽出** — Gemini（やること / 持ち物 / 締切 / 行事 / 注意事項の 5 カテゴリ）
3. **提出要否の LLM 判定**
   * 上限 10 件で暴走防止
4. **自律調査**
   * Google Search grounding
   * 発行元・手順・所要期間を調査
5. **逆算実行**
   * 締切 − 所要期間 = 準備開始日
   * 日付付きタスクを生成
6. **緊急度別リマインド**

> LLM / grounding 呼び出しは **never-throw 劣化** で握りつぶし、失敗時は空リスト / None を返して例外を伝播させず、
> アプリ全体は落ちない設計です。grounding が使えない場合も LLM 既知知識へ graceful fallback します。

### RAG サブシステム（出典付き回答の内部基盤）

`backend/app/rag/` は自前実装のハイブリッド検索（ベクトル + キーワード）+ LLM 回答生成です。
登録時に *chunking → embedding_cache → vector_store* でインプロセス索引を構築し、質問時は hybrid 検索で
関連チャンクを取得して Vertex AI Gemini が**出典（sources）付き**で回答します。空インデックス時は
**出典なし＋拒否応答**を返す設計です。

## Google Cloud 構成マッピング

GCP は名目ではなく、実行基盤・AI・監視・自動処置まで実配線しています。

| 役割 | 使用プロダクト |
| -- | -- |
| アプリ実行（3サービス構成） | **Cloud Run** ×3（frontend / backend / upload-api）＋ opt-in remediation |
| 構造化抽出・RAG回答・書類調査 | **Vertex AI (Gemini)**（`google-genai`, `GOOGLE_GENAI_USE_VERTEXAI`） |
| 画像おたよりの OCR | **Cloud Vision AI** |
| 公式手順の自律調査 | **Google Search grounding** |
| メタデータ / 添付 | **Firestore**（メタデータ）/ **Cloud Storage**（添付） |
| 秘匿 / 定期ジョブ / 監視 | **Secret Manager** / **Cloud Scheduler** / **Cloud Monitoring**（5xx / p99 / LLMエラー） |
| コンテナ / 非同期 | **Artifact Registry** / **Pub/Sub** |

- **IaC** — Terraform（17 ファイル）で GCP をコード管理（state は GCS リモートバックエンド）。
- **CI/CD** — GitHub Actions（4 ワークフロー）、**Workload Identity Federation（JSON キーレス）**、backend は
  **canary デプロイ + 自動ロールバック**（`/health` 失敗で旧リビジョン維持）。
- **サプライチェーン** — `pip-audit` / `npm audit`（ブロッキング）/ Trivy / SBOM（CycloneDX）/ Dependabot
  （`cooldown` で改ざんリリースの即時取り込みを抑止）。

> **設計判断も明示**しています。エージェント基盤は ADK / Agent Builder ではなく、処理が「OCR→抽出→grounding→逆算」
> という**確定的で短いパイプライン**であることから、軽量・低レイテンシ・依存最小を優先して Vertex AI 上の
> in-process 実装を採用。将来の多エージェント化時はこの境界を保ったまま ADK / Agent Engine へ移行できます。

---

# ストーリー

## ① 本作品で解決したい課題とその背景

### 一言でいうと

**「園からの1枚の紙を、締切に間に合う“行動”へ変えるまでの認知労働」** を、AIエージェントが丸ごと肩代わりします。

### 背景 — 情報は非構造・非デジタルで、大量に届く

保育園からの情報は「紙のおたより」「玄関の掲示」「行事予定表」など、**非構造・非デジタル**な形で毎日のように
届きます。提出物・持ち物・締切・行事・注意事項が各所に散らばり、保護者はそれを毎回自分で読み解かなければ
なりません。

さらに厄介なのは、**読むだけでは終わらない**ことです。たとえば「就労証明書を提出してください」という1行を
受け取った保護者は、頭の中で次の多段の作業を強いられます。

1. これは**自分が提出すべき書類**か？（判定）
2. どこに・どう申請すれば発行される？勤務先発行か、役所か？（**調査**）
3. 発行に**何日かかる**のか？（所要期間の見積り）
4. 締切に間に合わせるには、**いつ準備を始めればいいのか**？（**逆算**）

### なぜ放置できないのか — 認知負荷が「提出漏れ・締切超過」を生む

この「読む → 調べる → 逆算する」という一連の頭脳労働が、書類のたび・子どものたび・園のたびに積み重なります。
共働き・多忙な世帯ほど負荷が高く、**「気づいたら締切を過ぎていた」「発行が間に合わなかった」** という失敗が
構造的に起こります。既存のカレンダーアプリやメモアプリは「登録した予定を通知する」ことはできても、
**紙から予定を起こし、必要な準備期間を自分で調べて逆算する**ところは人間任せのままでした。

> **本作品が解こうとしているのは「情報整理」ではなく「先回り」です。** 締切を通知するのではなく、
> 締切に間に合うように**いつ動き出すべきか**をエージェントが自ら調べ・計算して提示します。

---

## ② 想定する利用ユーザー

### 主対象

- **共働き・多忙で、園からの情報を追いきれない保護者。** 紙の量が多く、読み解きと逆算に割く時間がない。
- **紙とデジタルが混在し、情報が一元化されていない家庭。** 掲示・おたより・予定表がバラバラで、
  「今週なにを持たせるか」「未提出はどれか」が一覧化できていない。

### ユーザーが置かれている状況（ジョブ）

| ユーザーの「したいこと」 | 従来 | 本作品 |
| -- | -- | -- |
| 届いた紙の中身を把握したい | 全部読む | **撮るだけ**で提出物/持ち物/締切/行事/注意事項に自動構造化 |
| 提出書類の出し方を知りたい | 自分で検索/園に問合せ | エージェントが **公式手順・発行元・所要期間を自律調査** |
| 締切に間に合わせたい | 頭の中で逆算 | **締切から逆算した準備開始日つきタスク**を自動生成 |
| 今日/今週なにをするか知りたい | メモ・記憶頼み | ダッシュボードで今日/明日の持ち物・今週/来週の行事・未対応を即確認 |
| 過去のおたよりを調べたい | 紙を探す | 自然文で質問 → **出典（根拠）付き**でRAG回答 |

### 「AIエージェントである必然性」がユーザー価値に直結する

このユーザーが本当に困っているのは「情報が多い」ことではなく、**情報を行動に変える途中の判断・調査・逆算が
重い**ことです。だからこそ、単なる検索窓やチャットボットではなく、**人間の多段作業を代行して自律的に
アウトプット（日付付き準備タスク）まで到達するエージェント**であることが、そのままユーザー価値になります。

---

## ③ プロダクトの特徴

### 特徴1 — 中核は「提出書類先回りエージェント」（単なるLLMラッパーではない）

本作品の中核は、チャット応答ではなく **提出書類先回りエージェント**（`backend/app/submission_agent.py`）です。
おたより1枚を起点に、エージェントが次の判断・調査・実行を**自律的に**行います。

```
おたより写真/PDF
  → OCR抽出（Cloud Vision AI / Gemini Vision, ocr.py）
  → 5カテゴリ構造化抽出（提出物/持ち物/締切/行事/注意事項, extraction.py）
  → 【エージェント】① 提出が必要な書類をLLMで判定（暴走防止に上限つき）
  → 【エージェント】② Google Search grounding で公式手順・発行元・所要期間を自律調査
  → 【エージェント】③ 締切から所要期間を後ろ向きに差し引き、準備開始日を逆算 → 日付付きタスク自動生成
  → 能動リマインド / ダッシュボード表示（reminders.py）
```

**実例（就労証明書）:** 「就労証明書を 2026/7/30 までに提出」という **1行** から、発行に約2週間かかる書類の
**準備開始日（7/9）まで逆算**して、4つの準備タスクを自動生成します。

| # | 自動生成された準備タスク | 生成された締切 |
| -- | -- | -- |
| 1/4 | テンプレート入手 | 2026-07-09 |
| 2/4 | 証明書発行（勤務先へ依頼） | 2026-07-12 |
| 3/4 | 誤り確認 | 2026-07-26 |
| 4/4 | 市町村に提出 | 2026-07-27 |

> この逆算ロジックは `backend/tests/test_submission_agent.py`（`test_build_drafts_per_step_backward_chain`）で
> 検証済みで、上記の日付は**テストで固定された生成結果と一致**します。「回帰テストで守られたエージェント」です。

### 特徴2 — 評価・監視・改善ループを持つ「運用できるAI」

AIエージェントの品質を **主観ではなく指標で守り、CIでゲート**しています。

- **エージェント性能評価ゲート**（`evaluation-gate`, `backend/tests/test_eval_ocr.py` / `test_eval_rag.py` /
  `test_eval_agent.py`, golden dataset は `backend/tests/eval/dataset.py`）を **独立した必須ステータスチェック**
  として分離。閾値（初期 0.8）を割ると CI が落ち、**CD（本番デプロイ）もブロック**されます。
  - **① Agent E2E Regression（エージェント本体の品質回帰）** — 「おたより文 → 公式手順の調査 → 締切逆算 →
    日付付き準備タスク生成」の**一気通貫パイプライン**（`test_eval_agent.py`）を、LLM 抽出と grounding の
    2境界だけ決定論的スタブし残りは実ロジックのまま golden で回帰計測。**単なる部品ユニットテストではなく、
    エージェントそのものの出力品質を名前付き必須チェックとしてゲート**しています。
  - **② タスク生成評価（「やること化」の品質）** — 期待「やること」のうち生成された割合＝**coverage** と、
    生成タスクが期待書類に対応する割合＝**precision（過検出ゼロ）** を下限ゲート
    （`MIN_TASK_COVERAGE` / `MIN_TASK_PRECISION`）。作品の主要価値である「紙 → やること」を評価対象に載せています。
  - **③ 締切逆算評価（実用性の定量化）** — 逆算された準備開始日の**一致率（許容誤差 0 日）** を下限ゲート
    （`MIN_DEADLINE_MATCH_RATE`）。README 実例「就労証明書 7/30 締切 → 準備開始 7/9」を **golden 固定値**として
    守り、体験価値（間に合う逆算）を数値で担保します。
  - **④ RAG 評価ゲート（根拠性・幻覚抑制）** — **top-source 正答率** / **keyword hit rate** /
    **groundedness**（回答語が取得ソース本文に追跡可能か＝幻覚検出）/ **refusal**（空インデックス時は出典なしで
    **拒否**し捏造しない）を下限ゲート（`MIN_TOP_SOURCE_ACCURACY` / `MIN_AVG_KEYWORD_HIT_RATE` /
    `MIN_GROUNDEDNESS`, `test_rag_refusal_on_empty_index`）。
  - **⑤ 不明点・曖昧情報への対応評価（安全なAI判断）** — 締切不明のとき**日付を捏造しない**／手続き名しか
    書かれていないとき**「推定（要確認）」導線**を必ず出す／一般的な文面で**過検出しない**、を `test_eval_agent.py`
    のケースで検証。分からないことを分からないと扱う挙動を回帰から守ります。
  - **OCR** — 日付・持ち物の coverage（recall）に加え **precision（誤検出ゼロ）** と **F1** を下限ゲート。
- **⑥ AI 品質ゲート一覧（審査員向けサマリ）** — 上記を CI の `evaluation-gate` ジョブ（`.github/workflows/ci.yml`,
  通常テストとは**別の必須ステータスチェック**）に集約。**いずれか 1 指標でも閾値割れ → CI 失敗 → 本番デプロイ停止**。

  | # | 評価ゲート | 主な指標 | 実装 |
  | -- | -- | -- | -- |
  | ① | Agent E2E Regression | 一気通貫パイプラインの回帰（名前付き必須チェック） | `test_eval_agent.py` |
  | ② | タスク生成 | coverage / precision（過検出ゼロ） | `test_eval_agent.py` |
  | ③ | 締切逆算 | 逆算日付の一致率（誤差 0 日, 7/30→7/9 golden） | `test_eval_agent.py` |
  | ④ | RAG | top-source 正答率 / keyword hit / groundedness / refusal | `test_eval_rag.py` |
  | ⑤ | 曖昧・不明情報への対応 | 締切捏造なし / 「推定（要確認）」導線 / 過検出なし | `test_eval_agent.py` |
  | ⑥ | OCR | coverage(recall) / precision / F1 | `test_eval_ocr.py` |

- **監視 → 障害対応ループ**（`infra/terraform/monitoring.tf` / `backend/remediation_function/`）—
  5xxエラー率 / p99レイテンシ / LLMエラーにアラート。検知 → 原因特定（**決定論的RCAで幻覚を持ち込まない**）→
  処置（**更新起因に限定した自律ロールバック、二段スイッチで既定OFF**）→ 回復確認 → 構造化ポストモーテム自動出力、
  という**改善ループ**を runbook と実装で整合させています。

> 「作って終わり」ではなく、**エージェント本体の品質回帰（タスク生成・締切逆算・RAG根拠性・曖昧対応）を
> 指標で止め、障害を検知・是正・記録できる**ところまで作り込んでいます。

### 特徴3 — Google Cloud を必然として使い切ったフルサイクル実装

GCP は名目ではなく、**エージェントの中核機能そのもの**に使われています。

| 役割 | 使用プロダクト |
| -- | -- |
| アプリ実行（3サービス構成） | **Cloud Run** ×3（frontend / backend / upload-api） |
| 構造化抽出・RAG回答・書類調査 | **Vertex AI (Gemini)** |
| 画像おたよりの OCR | **Cloud Vision AI** |
| 公式手順の自律調査 | **Google Search grounding** |
| メタデータ / 添付 / 秘匿 / 定期ジョブ / 監視 | Firestore / Cloud Storage / Secret Manager / Cloud Scheduler / Cloud Monitoring |

- **IaC** — Terraform（17 ファイル）で GCP をコード管理（state は GCS リモートバックエンド）。
- **CI/CD** — GitHub Actions（4 ワークフロー）、**Workload Identity Federation（JSONキーレス）**、backend は
  **canary デプロイ + 自動ロールバック**（`/health` 失敗で旧リビジョン維持）。
- **サプライチェーン** — `pip-audit` / `npm audit`（ブロッキング）/ Trivy / SBOM（CycloneDX）/ Dependabot
  （`cooldown` で改ざんリリースの即時取り込みを抑止）。

> **設計判断も明示**しています。エージェント基盤は ADK / Agent Builder ではなく、処理が「OCR→抽出→grounding→逆算」
> という**確定的で短いパイプライン**であることから、軽量・低レイテンシ・依存最小を優先して Vertex AI 上の
> in-process 実装を採用。将来の多エージェント化時はこの境界を保ったまま ADK / Agent Engine へ移行できます。

### 特徴4 — 迷わないユーザビリティ（撮るだけ / 出典付き / モバイルファースト）

- **撮るだけ登録** — 写真/PDF を上げると OCR→構造化で**下書きを自動生成**、確認して本登録（仮登録→finalize）。
- **今日やることが一目でわかる** — 今日/明日の持ち物・今週/来週の行事・未対応の提出物をダッシュボードに集約。
- **根拠付きで答える RAG Q&A** — 自然文の質問に、登録情報を**出典（sources）付き**で回答（`POST /api/info/ask`）。
- **モバイルファースト** — React 19 + TypeScript SPA、日本語/英語切替、JST統一の日付計算、Playwright e2e で担保。
- **プライバシー** — メール由来の owner 単位でデータ分離（`identity.py`）、アップロードはマジックバイト検証＋
  Pillow 再エンコードで EXIF/不正ペイロード除去（`upload_security.py`）。
