# Findy DevOps AI Agent Hackathon 提出用 説明文（コピペ用）

> 本ファイルは提出フォームへの記入用テキストです。記載内容はすべて本リポジトリの実装
> （README / `backend/app/` / `infra/terraform/` / `.github/workflows/`）に基づく事実で、捏造はありません。
> ライブURL・デモ動画URLは記入済みです（下記「デモ / 動作確認」を参照）。

---

## 概要（100文字以内）

> 保育園のおたよりを撮るだけで、AIエージェントがOCR・構造化・公式手順の自律調査・締切逆算の準備タスク生成まで自動実行する、共働き家庭向けの先回りアシスタント。

（81文字）

---

## システム構成

```
[保護者/スマートフォンのブラウザ]
   │  SPA配信（HTML/JS/CSS）
   ▼
[Cloud Run: frontend（nginx / React 19 + TypeScript SPA）]
   │  fetch + HMAC署名セッションcookie（TanStack Query）
   │  写真・PDF
   ▼
[Cloud Run: upload-api（軽量アップロード受付）] ──GCS保存──▶ [Cloud Storage]
   │ 202即応答 → backend worker 呼出（非同期）
   ▼
[Cloud Run: backend（FastAPI / 重処理）]
   ├─ /api/auth   … Firebase Identity Toolkit REST + HMAC署名cookie
   ├─ /api/info   … 登録 / ハイブリッド検索 / RAG Q&A / 能動リマインド
   ├─ worker      … 非同期 process_ocr（OCR→構造化→エージェント）
   ├─ submission_agent … 提出書類先回りエージェント
   └─ rag/        … chunk→embed→インプロセスVectorStore→LLM回答（出典付き）
        │
        ▼  Google Cloud
   ┌──────────────────────────────────────────────────────────┐
   │ Vertex AI(Gemini) / Cloud Vision AI(OCR) / Google Search   │
   │ grounding / Firestore / Cloud Storage / Secret Manager /   │
   │ Cloud Scheduler / Cloud Monitoring(5xx・p99アラート)        │
   └──────────────────────────────────────────────────────────┘
```

- **フロントエンド**: React 19 + TypeScript の SPA（Vite / Tailwind CSS / TanStack Query / React Router 7）。
  Vite で静的ビルド（`dist/`）し、**nginx を載せた専用 Cloud Run サービス（`frontend`）で配信**します
  （`frontend/Dockerfile` + `nginx.conf`）。ブラウザからは TanStack Query 経由で backend / upload-api の
  API を呼び出し、認証は HMAC 署名セッション cookie、CORS は Cloud Storage / API 側で frontend URL を許可します。
- **アプリ実行基盤**: **Cloud Run による 3 サービス構成**（配信の `frontend`（nginx）+ 重処理の `backend` +
  アップロード即受領の軽量 `upload-api`）。特に AI 重処理を担う `backend` とアップロード受付の `upload-api` を
  分離し、アップロード体験をブロックしない実運用志向の非同期取り込みを実現しています。
- **AI処理**: Vertex AI 上の Gemini（`google-genai` SDK）で構造化抽出・RAG回答・提出書類調査、
  Cloud Vision AI で画像OCR、Google Search grounding で公式手順の自律調査。
- **データ**: 本番は Firestore（メタデータ）+ Cloud Storage（添付）、ローカルは SQLite。
- **IaC / CI-CD**: Terraform で GCP をコード管理、GitHub Actions（Workload Identity Federation, キーレス）で
  Cloud Run へ自動デプロイ、Cloud Monitoring でエラー率・レイテンシを監視。

---

## フロントエンド（画面と使い勝手）

おたよりナビのフロントエンドは **React 19 + TypeScript の SPA**（Vite / Tailwind CSS / TanStack Query /
React Router 7）で、保護者がスマートフォンで片手操作することを前提としたモバイルファースト UI です。
ログインは HMAC 署名セッション cookie を用い、全画面が保護ルート（`ProtectedRoute`）配下に置かれます。
**日本語 / 英語の言語切替**と **JST 統一の日付表示**に対応します（`frontend/src/`）。

主な画面（`frontend/src/pages/`, ルーティングは `frontend/src/App.tsx`）:

- **掲示板 / ホーム（`/` `DashboardPage`）** — 今日・明日・今週・来週の予定と、緊急度別の能動リマインドを
  1 画面に集約。各リマインド項目はタップで対象データ詳細へ遷移します。
- **登録（`/create/auto` `AutoRegisterPage`）** — おたよりの写真を撮影・選択すると OCR で自動読み取りし、
  やること・持ち物・締め切りを仮登録。内容を確認してから本登録します。
- **やること（`/tasks` `TasksPage`）** — 提出物・持ち物・締め切りを一覧表示。ステータス（未確認 / 未対応 /
  対応済）の変更、手動追加、締切逆算で自動生成された準備タスクの日付順表示に対応します。
- **カレンダー（`/schedule` `SchedulePage`）** — 行事・締め切りを日付ごとに確認。日付選択とステータス絞り込み。
- **質問（`/info?tab=ask` `InfoHubPage`）** — 登録済みおたよりへの自然言語 Q&A（RAG）。回答には根拠となる
  おたよりが出典表示されます。ハイブリッド検索・一覧タブも同じ情報ハブに統合しています。
- **データ詳細（`/data/:id` `DataDetailPage`）** — 個別おたより / タスクの詳細表示、お気に入り登録。
- **設定（`/settings` `SettingsPage`）** — 言語・タイムゾーン・市町村・お子さまの登録、全データ削除。
- **使い方（`/howto` `HowToPage`）** — スクリーンショット付きの操作ガイド（`frontend/public/howto/*.png`）。

品質保証は **Playwright による e2e 19 テスト**と **ESLint** で担保し、各画面のキャプチャは README / 本ドキュメントに
掲載しています。バックエンドの重い AI 処理（OCR・構造化・自律調査・締切逆算）はすべて非同期で走るため、UI は
アップロード直後に応答を返し、処理結果はリマインド / やること画面へ反映されます。

---

## 開発素材（使用しているAPI・ツール）

**Google Cloud**
- Cloud Run（×3: frontend(nginx) / backend / upload-api）— アプリ実行プロダクト（必須要件①）
- Vertex AI（Gemini）— 構造化抽出・RAG回答・提出書類調査（必須要件②）
- Cloud Vision AI — 画像おたよりのOCR
- Google Search grounding（Vertex AI Gemini の機能）— 公式手順の自律調査
- Firestore / Cloud Storage / Secret Manager / Cloud Scheduler / Cloud Monitoring
- Artifact Registry / Cloud Build — コンテナのビルド・格納

**認証 / バックエンド**
- Firebase Identity Toolkit REST（サーバサイド照合）+ HMAC署名セッションcookie
- FastAPI（Python 3.12）/ SQLAlchemy / `google-genai` SDK / `google-cloud-vision`
- OCRフォールバック: pytesseract / pypdf / pdf2image / Pillow

**フロントエンド**
- React 19 / TypeScript / Vite / Tailwind CSS / TanStack Query / React Router 7
- 配信: nginx（`frontend/nginx.conf`）を載せた専用 Cloud Run サービスで静的 SPA を配信

**IaC / CI-CD / テスト**
- Terraform（`infra/terraform/`）/ GitHub Actions（Workload Identity Federation）
- pytest（backend）/ Playwright（frontend e2e）/ ESLint

---

## タグ（4個）

`#AIエージェント`　`#RAG`　`#VertexAI-Gemini`　`#CloudRun`

---

## 作品の特徴や技術的こだわり

### 1. AIエージェントが価値の中核（単なるチャットではない）

中核は**提出書類先回りエージェント**（`backend/app/submission_agent.py`）。保護者が毎回行っていた
「読む → 調べる → 逆算する」という多段の判断を、エージェントが自律的に実行します。

1. **抽出判断** — OCRテキストから「提出が必要な書類」をLLMで判定（暴走防止に上限つき）。
2. **自律調査** — 各書類について **Google Search grounding** で公式手順・発行元・所要期間を調べる
   （利用不可時はLLMの既知知識へ graceful fallback し、例外を伝播させない設計）。
3. **逆算実行** — 提出期限から所要期間を後ろ向きに差し引いた**準備開始日**を計算し、
   日付付きの準備タスクを自動生成。以降は能動リマインドが緊急度別に通知。

> **実例**: 「就労証明書を 2026/7/30 までに提出」という1行のおたよりから、発行に約2週間かかる書類の
> 準備開始日（7/9）まで逆算して4つの準備タスク（テンプレート入手→勤務先へ発行依頼→誤り確認→市町村へ提出）を
> 自動生成します。この逆算ロジックは `backend/tests/test_submission_agent.py`
> （`test_build_drafts_per_step_backward_chain`）で検証済みで、生成される日付はテスト固定値と一致します。

### 2. 課題設定と提供価値の一貫性

保育園情報は「紙のおたより・玄関の掲示・行事予定表」など**非構造・非デジタル**で大量に届き、提出物・締切が
各所に散らばります。共働き世帯ではこの認知負荷が提出漏れ・締切超過を生みます。本作品は
**撮って登録するだけ**で抽出・調査・逆算を肩代わりし、今日/明日の持ち物・今週/来週の行事・未対応の提出物を
ダッシュボードで即確認できるようにします。ここに **AIエージェントである必然性**があります。

### 3. Google Cloud 必須要件の充足（審査用マッピング）

| 必須要件 | 使用プロダクト | 実装根拠 |
|---|---|---|
| アプリ実行プロダクト | **Cloud Run ×2** | `infra/terraform/cloud_run.tf` / `cloud_run_upload.tf` / `.github/workflows/deploy-cloudrun.yml` |
| AI技術 | **Vertex AI Gemini** | `backend/app/ai_client.py`（`GOOGLE_GENAI_USE_VERTEXAI`）/ `extraction.py` / `rag/providers.py` |
| AI技術 | **Cloud Vision AI** | `backend/app/ocr.py`（`google-cloud-vision`）|
| AI技術 | **Google Search grounding** | `backend/app/submission_agent.py` |

### 4. 技術選定の納得感（ADK/Agent Builder ではなく Vertex AI in-process）

本エージェントの処理は「OCR → 抽出 → Google Search grounding → 締切逆算」という**確定的で短いパイプライン**で、
多エージェントの動的オーケストレーションを必要としません。そのため**軽量・低レイテンシ・依存最小**を優先し、
Vertex AI 上の in-process 実装を採用（設計決定は `submission_agent.py` 冒頭に明記）。将来の多エージェント化時は
この境界を保ったまま ADK / Agent Engine へ移行できる構成です。

### 5. DevOps フルサイクル・実運用への配慮

- **IaC** — Terraform（`infra/terraform/`, 16ファイル）で Cloud Run ×2 / Firestore / Pub/Sub / Cloud Storage /
  Secret Manager / IAM / **Workload Identity Federation** / Artifact Registry / Cloud Scheduler / Cloud Monitoring /
  API有効化 をコード管理。
- **CI/CD** — GitHub Actions 2ワークフロー（`ci.yml`: pytest + ESLint + Playwright e2e / `deploy-cloudrun.yml`:
  Docker build → Artifact Registry → Cloud Run deploy）。認証は **Workload Identity Federation**（JSONキーレス）。
- **監視** — `monitoring.tf` で Cloud Run の **5xxエラー率**・**p99レイテンシ**にアラートポリシー＋メール通知。
  （実測SLO値ではなく、IaCで定義済みのアラートポリシーです。）
- **実績数値** — pytest **253件** / Playwright e2e **19テスト** / Terraform **16ファイル**（実際の収集数・ファイル数）。

### 6. ユーザビリティ・データ分離

日本語/英語切替、JST統一の日付計算、写真を上げるだけの自動登録ドラフト、出典付きRAG Q&A、お気に入り表示。
メールから導出した owner 単位で情報を分離し、他ユーザーのデータに触れない設計（`backend/app/identity.py`）。

---

## デモ / 動作確認

- 🔗 デモ（デプロイ済み Cloud Run URL）: <https://toddler-private-rag-frontend-iqrm6wvhfq-an.a.run.app/tasks>
- 🎥 デモ動画: <https://www.youtube.com/channel/UC8u73I1rt1L3b4L5ZVfo-Ng>
