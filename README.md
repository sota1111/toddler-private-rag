# 保育園情報アシスタント MVP (Toddler Private RAG)

保育園から提供される膨大な情報（お手紙、掲示、行事予定など）を管理し、必要な情報を素早く確認するためのアシスタントツールです。

## 機能
- **ダッシュボード**: 明日の持ち物、今週の行事、未対応の提出物をクイックビュー
- **情報一覧**: キーワードや種別、ステータスによる検索・フィルタリング
- **情報登録**: 新しい情報の登録（OCR/RAG連携のベースとなる入力機能）
- **RAG（ベクトル検索＋LLM回答生成）**: 埋め込みベースのベクトル検索で関連情報を取得し、LLMで質問に回答

## RAG（ベクトル検索＋LLM回答生成）

登録情報（タイトル・本文・添付のOCRテキスト）をチャンク化して埋め込み、コサイン類似度で
関連チャンクを検索し、その結果をコンテキストにLLMで回答を生成します。

### エンドポイント（要認証）
- `POST /api/info/ask` — `{"query": "...", "top_k": 4}` → `{"answer": "...", "sources": [...]}`
- `GET /api/info/search?q=...&top_k=4` — ベクトル検索のみ（出典チャンクを返す）

### Provider 設定（環境変数）
- `EMBEDDING_PROVIDER` / `LLM_PROVIDER`: `fake`（既定）| `gemini`
- 既定の `fake` は決定論的でAPIキー不要。オフラインで動作し、テストにも使用します。
- `gemini` を使う場合は `GEMINI_API_KEY`（または `GOOGLE_API_KEY`）を設定し、
  `google-generativeai` をインストールしてください（SDKは遅延インポートのため未導入でも起動は可能）。
- ベクトルストアはインプロセス（純Pythonのコサイン類似度）で追加インフラ不要、
  sqlite / firestore いずれのバックエンドでも動作します。

## 技術スタック
- **Frontend**: React (TypeScript), Vite, Tailwind CSS, TanStack Query
- **Backend**: FastAPI (Python), SQLite, SQLAlchemy

## セットアップ

### バックエンド
1. `backend` ディレクトリへ移動
   ```bash
   cd backend
   ```
2. 仮想環境の作成と有効化
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
3. 依存関係のインストール
   ```bash
   pip install -r requirements.txt
   ```
4. サーバーの起動
   ```bash
   uvicorn app.main:app --reload
   ```

### フロントエンド
1. `frontend` ディレクトリへ移動
   ```bash
   cd frontend
   ```
2. 依存関係のインストール
   ```bash
   npm install
   ```
3. 開発サーバーの起動
   ```bash
   npm run dev
   ```

## 開発環境
- バックエンド: http://localhost:8000
- フロントエンド: http://localhost:5173 (Vite 開発サーバー)
- API ドキュメント: http://localhost:8000/docs

## 認証設定
### GCP Secret Manager セットアップ

本番環境（Cloud Run）では機密情報を Secret Manager で管理します。初回デプロイ前に以下のコマンドでシークレットを作成してください。

```bash
# セッション署名シークレットの作成
echo -n "your-random-32+chars" | gcloud secrets create rag-auth-secret --data-file=- --project=YOUR_PROJECT_ID

# 許可メールアドレスの作成
echo -n "you@example.com,other@example.com" | gcloud secrets create rag-allowed-emails --data-file=- --project=YOUR_PROJECT_ID

# Cloud Run サービスアカウントへの権限付与
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

このアプリは **Firebase認証 + 署名付きセッションcookie** を使用しています。

### 環境変数の設定

`.env.example` をコピーして `.env` を作成し、必要な変数を設定してください。

主な環境変数:
- `APP_ENV`: `local` または `production`
- `AUTH_SECRET`: セッションcookie署名用
- `ALLOWED_USER_EMAILS`: ログインを許可するメールアドレス（カンマ区切り）
- `GOOGLE_CLOUD_PROJECT`: GCPプロジェクトID
- `VITE_FIREBASE_*`: フロントエンド用Firebase設定

### ログイン

アプリにアクセスすると自動的にログイン画面へリダイレクトされます。
Firebaseでログイン後、そのメールアドレスが `ALLOWED_USER_EMAILS` に含まれている場合のみアクセスが許可されます。

## GCP デプロイ準備

### 概要

このアプリは FastAPI (Backend) + React (Frontend) 構成のプライベート RAG システムであり、Cloud Run にデプロイできます。

**重要**: 保育園資料・個人メモなどのプライベートデータを扱うため、認証・Secret 管理を徹底してください。

### コンテナ化

```bash
# Backend
docker build -t toddler-private-rag-backend ./backend
docker run -p 8000:8000 --env-file .env toddler-private-rag-backend

# Frontend
docker build -t toddler-private-rag-frontend ./frontend
docker run -p 8080:8080 toddler-private-rag-frontend
```

### GCP 実行環境

- **Backend**: Cloud Run (ポート `8000`)
- **Frontend**: Cloud Run (ポート `8080`) または Firebase Hosting

### データ永続化について

現在 SQLite/VectorDB をローカルで使用しています。Cloud Run はステートレスなため、本番環境での永続化には以下の変数を使用します（移行で段階導入予定）:

| 変数名 | 説明 |
|--------|------|
| DATABASE_TYPE | メタデータ永続化先 (`sqlite` / `firestore`) |
| FIRESTORE_DATABASE | Firestore データベース名 |
| GCS_BUCKET_NAME | アップロードファイル保存先の Cloud Storage バケット名 |

現状のコードはローカル sqlite/ファイル既定で動作し、これらの変数は永続化層の導入後に有効化されます。

### プライバシー・セキュリティ

- 保育園資料・個人メモは外部に送信しないこと
- 外部 LLM API を使用する場合はデータ送信範囲を確認すること
- 実データなしでもデプロイ準備状態を確認できます（空の状態でも起動可能）
- **本番環境 (`APP_ENV=production`) では、起動時のサンプルデータの投入 (seed) は行われません。**

### 環境変数

| 変数名 | 説明 |
|--------|------|
| APP_ENV | 実行環境 `local` / `production`（productionでcookie secure有効・seed無効） |
| AUTH_SECRET | セッションcookie署名シークレット（Secret Manager管理） |
| ALLOWED_USER_EMAILS | ログイン許可メール（カンマ区切り, Secret Manager管理推奨） |
| GOOGLE_CLOUD_PROJECT | Firebase Admin / GCPプロジェクトID |
| VITE_FIREBASE_* | フロントエンド用Firebase設定 |
| CORS_ORIGINS | 許可するフロントエンドOrigin（カンマ区切り） |
| DATABASE_TYPE / FIRESTORE_DATABASE / GCS_BUCKET_NAME | 本番永続化設定（移行で導入予定） |
| OPENAI_API_KEY / GEMINI_API_KEY | LLM API キー（Secret Manager 推奨） |

### 注意事項

- 実際の `.env` ファイルは Git 管理対象外 (`.gitignore` 設定済み)
- 個人情報・保育園資料は `.env` で管理するパスに保存し、コードに直書きしないこと
