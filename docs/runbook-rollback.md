# Cloud Run ロールバック手順 (Runbook) — SOT-1400

不具合のあるデプロイを検知したときに、Cloud Run のトラフィックを直前の正常リビジョンへ戻す
手順をまとめる。`.github/workflows/deploy-cloudrun.yml` の `main` push デプロイで問題が出た
場合に使う。

## 対象サービス

| サービス | Cloud Run service name |
|---|---|
| バックエンド (AI worker) | `toddler-private-rag-backend` |
| フロントエンド (nginx SPA) | `toddler-private-rag-frontend` |
| アップロード API | `upload-api` |

共通の変数（自分の環境に合わせて置き換える）:

```bash
PROJECT=gen-lang-client-0243034020
REGION=asia-northeast1
SERVICE=toddler-private-rag-backend   # 戻したいサービス名
```

## 1. 異常の確認

- Cloud Monitoring のアラート（`Cloud Run 5xx error rate high` / `Cloud Run request latency high`,
  SOT-1400 で追加）が発火していないか確認する。
- ログ確認:

  ```bash
  gcloud run services logs read "$SERVICE" --region "$REGION" --project "$PROJECT" --limit 100
  ```

## 2. リビジョン一覧と直前の正常リビジョンの特定

```bash
gcloud run revisions list \
  --service "$SERVICE" \
  --region "$REGION" \
  --project "$PROJECT"
```

直近で 100% トラフィックを受けていた1つ前のリビジョン名（例: `toddler-private-rag-backend-00042-abc`）
を控える。現在のトラフィック割当は次で確認できる:

```bash
gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --format 'value(status.traffic)'
```

## 3. トラフィックを直前の正常リビジョンへ戻す（最速・推奨）

```bash
GOOD_REVISION=toddler-private-rag-backend-00042-abc   # 手順2で控えたもの
gcloud run services update-traffic "$SERVICE" \
  --to-revisions "${GOOD_REVISION}=100" \
  --region "$REGION" --project "$PROJECT"
```

イメージの再ビルドが不要なため、これが最短のロールバック手段。

## 4. （代替）既知の正常イメージタグで再デプロイ

リビジョンが残っていない場合は、直前の正常コミット SHA のイメージで再デプロイする。
イメージは `latest` と `<commit-sha>` の2タグで Artifact Registry に push されている。

```bash
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/toddler-private-rag/${SERVICE}"
PREV_SHA=<直前の正常コミットSHA>
gcloud run deploy "$SERVICE" \
  --image "${IMAGE}:${PREV_SHA}" \
  --region "$REGION" --project "$PROJECT" --platform managed
```

> 注意: `deploy-cloudrun.yml` の `--set-env-vars` / `--set-secrets` を含む完全なデプロイ設定は
> ワークフロー側が真実のソース。env / secret も巻き戻したい場合は、該当コミットの
> `deploy-cloudrun.yml` から再実行（`workflow_dispatch`）するのが確実。

## 5. 確認

- 手順1のアラートが解消したことを確認する。
- スモークチェック:
  - RAG 回答1件（質問→回答が返る）
  - 写真 OCR 1件（画像アップロード→抽出が返る）
- トラフィックが意図したリビジョンに 100% 向いていることを再確認:

  ```bash
  gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --format 'value(status.traffic)'
  ```

## 補足

- フロントエンド/upload-api も同じ手順（`SERVICE` を差し替え）で戻せる。
- インフラ定義（Terraform）側の変更を巻き戻す場合は `infra/terraform/README.md` を参照。
