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
  （`infra/terraform/monitoring.tf` の `google_monitoring_dashboard.ops`）。
  リクエスト数 / 5xx率 / p99レイテンシ / インスタンス数 / LLM呼び出しのエラー・レイテンシを集約。
- **アラート**（`monitoring.tf`）:
  - Cloud Run 5xx error rate high (SOT-1400)
  - Cloud Run request latency high (SOT-1400)
  - LLM error rate high (SOT-1472)
- 通知先メールは `var.alert_notification_email` を設定したときのみ有効。

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
4. **恒久対応**: 原因を修正 → eval 回帰スイート緑を確認 → 再デプロイ。
5. **記録**: 事象・原因・対応を Linear に残し、再発防止（eval ケース追加等）を検討。

## モデル / プロンプト変更フロー

1. `ai_client.py` / プロンプトレジストリ（SOT-1474）で設定を変更し、バージョン/履歴を更新。
2. ローカルで eval 回帰スイートを実行し、精度指標（coverage/precision/F1/groundedness/refusal）が
   閾値を下回らないことを確認。
3. PR → CI（Evaluation regression gate 含む）緑 → merge。
4. デプロイ後、日次監視で回帰がないか観察（canary/段階リリースが望ましい）。
