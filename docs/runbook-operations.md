# 運用 Runbook（保守運用） — SOT-1466 / SOT-1475

おたよりナビ（AIエージェント）の日常運用手順をまとめる。ロールバックの詳細手順は
[`runbook-rollback.md`](./runbook-rollback.md) を参照。

## 対象システム

- バックエンド (AI worker): Cloud Run `toddler-private-rag-backend`
- フロントエンド (SPA): Cloud Run `toddler-private-rag-frontend`
- アップロード API: Cloud Run `upload-api`
- パイプライン: OCR(Cloud Vision) → 抽出 → RAG(埋め込み+ベクトル検索) → Search grounding → submission_agent

## 監視ダッシュボード / アラート

- **ダッシュボード**: Cloud Monitoring の「おたよりナビ 運用ダッシュボード (SOT-1475)」
  （`infra/terraform/dashboard.tf` の `google_monitoring_dashboard.ops`）。
  Cloud Run のリクエスト数 / 5xx率 / p99レイテンシ / インスタンス数と、LLM・OCR・grounding の
  log-based メトリクスを1画面に集約する。
- **アラート**（`monitoring.tf`）:
  - Cloud Run 5xx error rate high (SOT-1400)
  - Cloud Run request latency high (SOT-1400)
  - LLM error rate high (SOT-1472)
- 通知先メールは `var.alert_notification_email` を設定したときのみ有効。

### ダッシュボードの使い方

キャプチャ（レイアウトプレビュー）: [`docs/screenshots/SOT-1475-monitoring-dashboard.png`](./screenshots/SOT-1475-monitoring-dashboard.png)

#### 開き方

1. **Cloud Console から**: [Monitoring → Dashboards](https://console.cloud.google.com/monitoring/dashboards)
   を開き、一覧から **「おたよりナビ 運用ダッシュボード (SOT-1475)」** を選択する。
   URL 直接指定なら
   `https://console.cloud.google.com/monitoring/dashboards?project=<PROJECT_ID>` で対象プロジェクトを開く。
2. **gcloud から**（存在確認 / 定義の確認）:
   ```bash
   gcloud monitoring dashboards list --project <PROJECT_ID> \
     --filter 'displayName:"おたよりナビ 運用ダッシュボード"'
   ```
3. 右上の期間セレクタ（既定 1 時間）で表示レンジを調整する。日次確認は 24 時間、
   インシデント時は 1〜6 時間程度に絞ると異常の立ち上がりを追いやすい。

#### タイルの見方（全8枚 / 2列 × 4行）

| タイル | 意味 | 見方の目安 |
| --- | --- | --- |
| **Cloud Run request rate** | サービス別のリクエスト数（rate, 秒あたり） | ベースラインを把握。急増＝負荷、急減＝到達不可の兆候 |
| **Cloud Run 5xx rate** | サービス別の 5xx 応答 rate | 常時ほぼ 0 が正常。継続的な立ち上がりはアラート（SOT-1400）と連動 |
| **Cloud Run p99 latency** | サービス別の p99 レイテンシ | 通常レンジを把握し、跳ね上がりを検知。SOT-1400 のレイテンシアラートと対応 |
| **Cloud Run instance count** | サービス別の稼働インスタンス数 | スケール挙動の確認。張り付き＝飽和、0 近辺＝コールドスタート要因 |
| **LLM request rate** (SOT-1472) | LLM 呼び出し回数（log-based metric） | パイプライン稼働量の代理指標。ログ未出力時は無データ |
| **LLM error rate** (SOT-1472) | LLM 呼び出しエラー rate（log-based metric） | 0 が正常。上昇はモデル/認証/クォータ異常。LLM error アラートと連動 |
| **Grounding degradation rate** (SOT-1470 D3) | Search grounding 劣化（フォールバック）rate | 上昇＝grounding 品質低下。回答根拠の劣化を早期検知 |
| **OCR empty-extraction rate** (SOT-1470 D3) | OCR 抽出が空になった rate | 上昇＝入力画像/PDF 品質 or OCR 経路の異常 |

> LLM / grounding / OCR タイルは `monitoring.tf` の log-based メトリクスを参照する。対象ログが
> まだ出ていない期間は「No data」表示になる（異常ではない）。

#### 作成・更新（Terraform）

ダッシュボード定義はコード管理（`infra/terraform/dashboard.tf`）。変更は必ず Terraform 経由で反映する。

```bash
cd infra/terraform
terraform plan  -target=google_monitoring_dashboard.ops
terraform apply -target=google_monitoring_dashboard.ops
```

#### 日常運用での使い方

- **日次**: 5xx rate / p99 latency / LLM error rate を確認し、アラート発火の裏取りに使う。
- **インシデント時**: request rate と instance count で影響範囲を、5xx / p99 で深刻度を、
  LLM / grounding / OCR タイルで「どの段階（OCR / RAG / LLM）」かの当たりを付ける
  （詳細は下記「インシデント対応」）。

## 定期運用サイクル

### 日次
- ダッシュボードでアラート発火・5xx率・p99レイテンシを確認。
- LLMエラー率 / grounding fallback の発生を確認（`monitoring.tf` の log-based metric）。
- 異常があれば「インシデント対応」へ。

### 週次
- eval 回帰スイート（`backend/tests/test_eval_ocr.py` / `test_eval_rag.py`）の結果を確認。
  CI の「Evaluation regression gate」ジョブが緑であることを確認（SOT-1471）。
- ユーザーフィードバック（採否 / 👍👎, SOT-1473）を集計し、誤り事例を eval データセットへ追加候補として記録。
- コスト（Vertex AI / Cloud Run）の推移を確認。

### 月次
- モデル / プロンプト設定（`ai_client.py`・プロンプトレジストリ SOT-1474）を見直し、必要なら更新。
  モデル更新時は eval 回帰スイートで精度が落ちないことを確認してから反映（canary 推奨）。
- コストレビュー、精度トレンドレビュー。
- データ保持 / プライバシ（`retention.py` / `privacy.py`）の監査。

## インシデント対応

1. **検知**: アラート or ダッシュボード異常。
2. **切り分け**: どのサービス / どの段階（OCR / RAG / LLM）かをログで特定。
   ```bash
   gcloud run services logs read <service> --region asia-northeast1 --project <project> --limit 100
   ```
3. **一次対応**: 直近デプロイ起因なら [`runbook-rollback.md`](./runbook-rollback.md) でロールバック。
   自律ロールバック（下記）が有効なら、このステップは自動で試行される。
4. **恒久対応**: 原因を修正 → eval 回帰スイート緑を確認 → 再デプロイ。
5. **記録**: 事象・原因・対応を Linear に残し、再発防止（eval ケース追加等）を検討。

### 自律ロールバック（P2, SOT-1480）

デプロイ時の canary ロールバック（`deploy-cloudrun.yml`, SOT-1469 B2）の「ランタイム版」。
Cloud Monitoring のアラート（5xx / レイテンシ / LLM エラー）が **webhook 通知チャネル** を発火し、
小さな remediation Cloud Run サービス（`backend/remediation_function/`）が受け取って、
**ガードレール付きで**直近デプロイ起因かを判定し、健全な前 revision へトラフィックを戻す。

- **アーキテクチャ**: alert → `remediation_webhook` 通知チャネル（`?token=` 認証）→ remediation
  サービス → Cloud Run Admin API v2 で `update-traffic`（前 revision へ 100%）。
- **ガードレール**（`remediation_function/remediation.py`）:
  - **token 認証**（設定なしなら全拒否＝fail-closed）
  - **dry-run**（既定 ON）: 判定とログのみ出力し、トラフィックは変更しない
  - **cooldown**: 同一サービスを `REMEDIATION_COOLDOWN_SECONDS`（既定 3600s）以内に再ロールバックしない
    （状態は Firestore `remediation_state` に保存）
  - **直近デプロイ判定**: 現行 revision が `REMEDIATION_DEPLOY_WINDOW_SECONDS`（既定 3600s）より
    古い場合はスキップ（デプロイ起因でない可能性が高いため人手に委ねる）
  - **監査ログ**: 全判定を `[remediation] action=... service=... reason=...` 形式で出力
- **既定は無効（opt-in）**: Terraform は `var.enable_autonomous_rollback = false` の間、何も作成せず
  アラートは email チャネルのみに通知する。

#### 有効化手順

1. `terraform.tfvars` に設定（機微値は gitignored）:
   ```hcl
   enable_autonomous_rollback = true
   remediation_token          = "<ランダムな長い文字列>"
   remediation_dry_run        = true   # まず dry-run で挙動を確認してから false に
   ```
2. `terraform apply`（remediation サービス・SA・IAM・webhook 通知チャネルを作成し、既存アラートに配線）。
3. CI で remediation イメージをビルド/デプロイするため、リポジトリ変数/シークレットを設定:
   - repo *variable* `REMEDIATION_ENABLED=true`（未設定ならデプロイ手順はスキップ＝既存パイプライン無影響）
   - repo *variable* `REMEDIATION_DRY_RUN`（任意, 既定 `true`）
   - secrets `CLOUD_RUN_SERVICE_REMEDIATION` / `CLOUD_RUN_REMEDIATION_SA` / `REMEDIATION_TOKEN`
4. dry-run のログ（`[remediation] action=dry_run ... would roll back ...`）で妥当性を確認したら、
   `remediation_dry_run = false` にして実ロールバックを有効化する。

#### 無効化 / 停止

- 即時停止は `remediation_dry_run = true`（apply）または repo variable `REMEDIATION_ENABLED=false`。
- 完全撤去は `enable_autonomous_rollback = false` で apply（webhook チャネルとサービスを削除）。

### 自動 原因分析・改善提案（RCA, SOT-1484）

remediation サービスは、ロールバック判定に加えて**インシデントの原因分析（RCA）と改善提案を
自動生成**する（`backend/remediation_function/postmortem.py`）。生成は **決定的（ルールベース）** で、
障害経路に生成 AI（幻覚リスク）を足さない設計を維持している。

- **入力**: アラートの policy / condition を signal（`5xx` / `latency` / `llm_error` /
  `grounding_degraded` / `unknown`）に分類し、ロールバック結果（`RemediationResult`）を取り込む。
- **出力**: signal ごとに **probable root causes**・**improvement proposals**・関連 runbook を
  対応付けた構造化ポストモーテムを、webhook レスポンス JSON の `postmortem` フィールドと
  `[postmortem] signal=... severity=... ...` 監査ログ行として出力する。
- **人手の判断は残す**: 生成物はあくまで一次分析。恒久対応・再発防止の意思決定と説明責任は人間が担う
  （上記「インシデント対応」5. の記録・再発防止と接続する）。
- `never raises`: 未分類のアラートも `unknown` signal で必ずポストモーテムを返す。

## モデル / プロンプト変更フロー

1. `ai_client.py` / プロンプトレジストリ（SOT-1474）で設定を変更し、バージョン/履歴を更新。
2. ローカルで eval 回帰スイートを実行し、精度指標（coverage/precision/F1/groundedness/refusal）が
   閾値を下回らないことを確認。
3. PR → CI（Evaluation regression gate 含む）緑 → merge。
4. デプロイ後、日次監視で回帰がないか観察（canary/段階リリースが望ましい）。
