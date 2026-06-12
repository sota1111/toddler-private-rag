# 保育園情報アシスタント MVP (Toddler Private RAG)

保育園から提供される膨大な情報（お手紙、掲示、行事予定など）を管理し、必要な情報を素早く確認するためのアシスタントツールです。

## 機能
- **ダッシュボード**: 明日の持ち物、今週の行事、未対応の提出物をクイックビュー
- **情報一覧**: キーワードや種別、ステータスによる検索・フィルタリング
- **情報登録**: 新しい情報の登録（OCR/RAG連携のベースとなる入力機能）

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

このアプリは JWT 認証を使用しています。

### 環境変数の設定

`.env.example` をコピーして `.env` を作成し、以下の変数を設定してください：

```env
AUTH_USERNAME=your_username
AUTH_PASSWORD=your_password
AUTH_SECRET_KEY=your_secret_key_at_least_32_chars
```

### ログイン

アプリにアクセスすると自動的にログイン画面へリダイレクトされます。
設定した `AUTH_USERNAME` / `AUTH_PASSWORD` でログインしてください。

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

現在 SQLite/VectorDB をローカルで使用しています。Cloud Run はステートレスなため、本番環境では以下を検討してください:

- ドキュメントDB: **Firestore** への移行
- VectorDB: **Vertex AI Vector Search** または Cloud Run 内の永続ストレージ
- アップロードファイル: **Cloud Storage** への保存

### プライバシー・セキュリティ

- 保育園資料・個人メモは外部に送信しないこと
- 外部 LLM API を使用する場合はデータ送信範囲を確認すること
- 実データなしでもデプロイ準備状態を確認できます（空の状態でも起動可能）

### 環境変数

| 変数名 | 説明 |
|--------|------|
| AUTH_USERNAME | 認証ユーザー名 |
| AUTH_PASSWORD | 認証パスワード（Secret Manager 推奨） |
| AUTH_SECRET_KEY | JWT署名キー（Secret Manager 推奨） |
| OPENAI_API_KEY / GEMINI_API_KEY | LLM API キー（Secret Manager 推奨） |

### 注意事項

- 実際の `.env` ファイルは Git 管理対象外 (`.gitignore` 設定済み)
- 個人情報・保育園資料は `.env` で管理するパスに保存し、コードに直書きしないこと
