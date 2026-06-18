# 永続化アーキテクチャ設計ドキュメント (SOT-670)

本ドキュメントは、Cloud Run本番環境におけるデータの永続化と、ステートレスな実行環境への対応のための設計指針を記述する。

## 1. 現状アーキテクチャ

現在の実装は、シングルサーバーでの動作を前提としたローカル完結型の構成となっている。

- **メタデータ管理**: FastAPI + SQLAlchemy + SQLite固定 (`sqlite:///./data/app.db`)
- **原本ファイル**: `backend/data/uploads` にUUIDファイル名（例: `550e8400e29b41d4a716446655440000.png`）でローカル保存
- **OCRテキスト**: `attachments` テーブルの `ocr_text` カラム (TEXT型) に保存
- **データモデル**:
  - `nursery_info`: 保育園資料のメタデータ（タイトル、種類、日付、重要度、タグ等）
  - `attachments`: 原本ファイル情報とOCR結果。`nursery_info.id` に紐づく1:N関係
- **課題**: Cloud Runはステートレスであり、インスタンスの再起動やスケーリングに伴い、ローカルに保存されたSQLiteファイルおよび原本画像が消失する。

## 2. 目標アーキテクチャ（保存先責務分担）

本番環境 (Production) では、マネージドサービスを活用して永続性を確保する。

| データ種別 | 保存先 (Production) | 保存先 (Local) | 備考 |
| :--- | :--- | :--- | :--- |
| メタデータ | **Firestore** | SQLite | サーバーレスでスケーラブルなNoSQL |
| 原本ファイル | **Cloud Storage (GCS)** | ローカルディスク | 堅牢なオブジェクトストレージ |
| OCRテキスト | Firestore (+ GCS) | SQLite | 短文はドキュメント内、極端に長い場合はGCS |
| ベクトル | Vertex AI Vector Search | (未実装) | 将来的な拡張（RAG用）。現状未実装。 |

### OCRテキストの保存方針
- 原則として Firestore の `attachments` ドキュメント内に文字列として保存する。
- Firestore のドキュメントサイズ上限 (1MB) に近づくような極端に長いテキスト（例: 大量のPDF資料）の場合は、GCSに `.txt` ファイルとして保存し、FirestoreにはそのURIを記録する方針とする。
- 初期実装では、一般的な保育園の配布物サイズを考慮し、Firestoreへの直接保存を優先する。

## 3. Firestoreコレクション設計

### `nursery_info` コレクション
- **ドキュメントID**: UUID または Firestore自動採番
- **フィールド**:
  - `title` (string)
  - `info_type` (string)
  - `content` (string)
  - `date` (string (YYYY-MM-DD) / null)
  - `event_date` (string (YYYY-MM-DD) / null)
  - `due_date` (string (YYYY-MM-DD) / null)
  - `items` (string/null)
  - `status` (string): "未対応", "完了" 等
  - `priority` (string): "低", "普通", "高"
  - `tags` (array<string>)
  - `memo` (string/null)
  - `created_at` (timestamp)
  - `updated_at` (timestamp)

**実装上の注意点:**
- **日付形式**: Firestore上では検索の容易さと既存実装（SQLAlchemy/Pydantic）との整合性のため、日付を `YYYY-MM-DD` 形式の文字列で保存する。
- **タグの変換**: API/スキーマ層では後方互換性のためカンマ区切りの文字列 (`tags: Optional[str]`) を維持する。Repository層において、Firestore保存時は `array<string>` へ変換し、取得時は `string` へ復元する責務を負う。これにより、Firestoreの `array-contains` クエリを利用可能にする。

### `attachments` コレクション
- `nursery_info` のサブコレクション、あるいは独立したコレクションとして設計（クエリ要件に基づき決定）。
- **フィールド**:
  - `info_id` (string): 親ドキュメントへの参照
  - `original_filename` (string)
  - `mime_type` (string)
  - `file_size` (number)
  - `storage_backend` (string): "local" or "gcs"
  - `object_key` (string): 保存先でのキー（例: `550e8400e29b41d4a716446655440000.png` または `uploads/uuid.png`）
  - `ocr_text` (string/null)
  - `created_at` (timestamp)

**実装上の注意点:**
- **ストレージキー**: バックエンドの実装に依存しないよう `object_key` を使用する。`local` ストレージの場合は現状の `stored_filename`（ハイフンなしUUID + 拡張子）が、`gcs` の場合はオブジェクトパスが格納される。

### Firestoreクエリ制約への対処
Firestoreは標準で `ilike` (部分一致) 検索をサポートしていない。
- **検索の代替方針**:
  - タグ検索: Firestoreの `array-contains` を使用。
  - 全文検索: 
    1. 小規模な間は、フロントエンド側でフィルタリング、または全件取得後のインメモリ検索。
    2. 将来的には Algolia / ElasticSearch / Vertex AI Search との連携を検討（現状未実装）。
    3. 暫定的に、主要な単語を `search_keywords` 配列として抽出して保存する手法を検討。

## 4. ローカル↔本番の切替方針（Environment駆動）

環境変数によってデータアクセス層（Repository層 / Storage層）の挙動を切り替える。

- **環境変数**:
  - `APP_ENV`: `local` (Default), `production`
  - `STORAGE_BACKEND`: `local`, `gcs`
  - `DATABASE_TYPE`: `sqlite`, `firestore`
  - `GCS_BUCKET_NAME`: GCSバケット名
  - `GOOGLE_CLOUD_PROJECT`: プロジェクトID

- **実装方針**:
  - Factory パターンまたは依存性注入 (DI) を用いて、`SqliteNurseryRepository` と `FirestoreNurseryRepository` を切り替える。
  - データ保存先の切替には `DATABASE_TYPE` を使用し、名称の揺れ（`DATA_BACKEND`等）を防ぐ。
  - ローカル開発時は `.env` なしで SQLite/Local ストレージが動作する後方互換性を維持する。

## 5. Cloud Run / Secret Manager / IAM

- **認証**:
  - ローカル開発: `GOOGLE_APPLICATION_CREDENTIALS` (Service Account Key JSON)
  - 本番: Cloud Run のデフォルトサービスアカウント (Identity-Based)
- **権限 (IAM)**:
  - `roles/datastore.user` (Firestore)
  - `roles/storage.objectAdmin` (GCS)
- **Secret Manager**:
  - Firebase設定、特定のAPIキー等の機密情報は Secret Manager から環境変数として注入する。
- **削除の同期**:
  - `nursery_info` または `attachments` を削除する際、対応する GCS 上のオブジェクトも確実に削除されるよう、Repository/Storage 層で整合性を確保する。
- **原本配信**:
  - セキュリティ保護のため、GCSバケットを公開せず、バックエンド (FastAPI) が **署名付きURL (Signed URL)** を発行してクライアントに返却する方針、またはバックエンドがプロキシとして配信する方針とする（パフォーマンスと有効期限の制御を考慮して決定）。

## 6. 個人情報(PII)保護方針

保育園の資料には子供の名前、住所、電話番号などの個人情報が含まれる。

- **PII Redaction (SOT-780)**:
  - OCRテキストの保存およびログ出力前に、メールアドレス、電話番号、マイナンバー、銀行口座番号などの特定パターンを自動的にマスクする。
  - 詳細は [データ保持およびプライバシー保護方針](./data-retention-policy.md) を参照。
- **データ保持ポリシー (SOT-780)**:
  - `ATTACHMENT_RETENTION_DAYS` によって、一定期間を過ぎた添付ファイルを自動または手動で削除する仕組みを提供する。
- **ログ出力の制限**:
  - ログに原本ファイル名、OCRテキスト、リクエストボディの `content` 等を直接出力しない。
  - ログにはドキュメントIDのみを含め、詳細な調査は Firestore 上で実施する。
- **暗号化**:
  - GCS、Firestore 共に Google Cloud 標準の保存時暗号化 (Encryption at rest) を利用。
- **SOT-673 での導入予定**: 構造化ログの導入時に、機密情報のマスキング方針を適用する予定である（現状未実装）。

## 7. 移行方針 / 段階導入

1.  **SOT-670 (本件)**: アーキテクチャ設計。
2.  **SOT-671 (Storage層)**: GCS対応の抽象化。ローカル保存とGCS保存を切り替え可能にする。
3.  **SOT-672 (Repository層)**: Firestore対応の抽象化。SQLAlchemyとFirestoreを抽象インターフェースで隠蔽する。
4.  **SOT-673 (Logging/Tracing)**: 本番向けの可観測性向上（導入予定）。

### 既存データの移行
- 開発初期段階のため、自動移行スクリプトの優先度は低。
- 必要に応じて、SQLite からエクスポートし Firestore にインポートするワンショットのスクリプトを作成する。

---
*本ドキュメントは、実装の進展に伴い随時更新される。*
