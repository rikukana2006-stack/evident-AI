# Evident AI / Fukkei Match

Evident AI の最初のモジュール **Fukkei Match** は、納品書と請求書をアップロードし、mock OCRで構造化データを抽出し、明細単位で差異を確認するMVPです。

現在の実装では、簡易起動用にSQLiteを標準DBとして使います。PostgreSQLを使う構成にも切り替えられるよう、手順を分けて記載しています。

## Repository Structure

```text
evident-ai/
+-- frontend/
+-- backend/
+-- database/
+-- docs/
+-- TODO.md
+-- README.md
```

## Tech Stack

- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: FastAPI, Python, SQLAlchemy
- Database: SQLite by default, PostgreSQL optional
- File storage: local storage for MVP
- OCR: mock OCR service
- Upload formats: PDF, image, Excel, CSV

## Windows Prerequisites

PowerShellで作業する想定です。

### 1. Node.jsをインストール

1. https://nodejs.org/ からWindows向けLTS版をダウンロードします。
2. インストーラーを既定設定で実行します。
3. 新しいPowerShellで確認します。

```powershell
node --version
npm --version
```

### 2. Pythonをインストール

1. https://www.python.org/downloads/windows/ からPython 3.12以上をダウンロードします。
2. インストール時に **Add python.exe to PATH** にチェックを入れます。
3. 新しいPowerShellで確認します。

```powershell
python --version
pip --version
```

### 3. PostgreSQLをインストールする場合

簡易起動では不要です。PostgreSQLで確認したい場合のみ実施してください。

1. https://www.postgresql.org/download/windows/ からWindows installerをダウンロードします。
2. 既定ポート `5432` でインストールします。
3. `postgres` ユーザーのパスワードを控えます。
4. 確認します。

```powershell
psql --version
```

## `.env`作成

リポジトリルートで実行します。

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env.local
```

### 簡易起動: SQLiteを使う場合

`backend\.env` は既定のままで動きます。

```text
EVIDENT_DATABASE_URL=sqlite:///./data/evident_ai.db
EVIDENT_ALLOWED_ORIGINS=["http://localhost:3002"]
EVIDENT_STORAGE_DIR=storage
```

SQLite DBはFastAPI起動時に `backend/data/evident_ai.db` として自動作成されます。

### PostgreSQLを使う場合

PostgreSQL用のDBとユーザーを作成します。例:

```powershell
createdb -U postgres evident_ai
```

必要に応じてPostgreSQLユーザーを作成し、`backend\.env` を変更します。

```text
EVIDENT_DATABASE_URL=postgresql+psycopg://evident_ai:evident_ai@localhost:5432/evident_ai
EVIDENT_ALLOWED_ORIGINS=["http://localhost:3002"]
EVIDENT_STORAGE_DIR=storage
```

PostgreSQLを使う場合はPythonドライバも追加で入れます。

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pip install "psycopg[binary]"
```

## Backend 起動方法

新しいPowerShellを開き、リポジトリルートから実行します。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

確認URL:

```text
http://localhost:8000/health
```

## Backend テスト

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest
```

## Frontend 起動方法

別のPowerShellを開き、リポジトリルートから実行します。

```powershell
cd frontend
npm install
npm run dev
```

画面確認URL:

```text
http://localhost:3002
```

## Demo Flow

1. Login画面で任意のメールアドレスとパスワードを入力します。
2. DashboardからDocument Uploadへ進みます。
3. 納品書と請求書のファイルを選択してアップロードします。
   - 対応形式: PDF, PNG, JPG, JPEG, WEBP, TIFF, Excel (`.xlsx`, `.xls`), CSV
4. OCR Reviewでmock OCRを実行し、JSONを確認します。
5. Matching Resultで突合を実行し、差異を確認します。
6. Approve、Hold、Reject、CSV exportを確認します。

## CSV / Excel Import Format

CSV and `.xlsx` files can be converted into OCR review JSON when they include a
header row with these columns. Japanese aliases such as `品名`, `数量`, `単価`,
`金額`, `税率` are also supported.

```csv
item_name,quantity,unit_price,amount,tax_rate
明治おいしい牛乳,20,100,2000,8
パン,30,80,2400,8
```

PDF and image files currently use mock OCR. They are accepted by the upload flow
so the real AI OCR service can be connected behind the same API later.

## GitHubへPushするコマンド

GitHubで空のリポジトリを作成してから、リポジトリルートで実行します。

```powershell
git status
git add .
git commit -m "Initial Evident AI Fukkei Match MVP"
git branch -M main
git remote add origin https://github.com/<your-account>/<your-repo>.git
git push -u origin main
```

すでにremoteがある場合:

```powershell
git remote -v
git remote set-url origin https://github.com/<your-account>/<your-repo>.git
git push -u origin main
```

## Push前チェック

```powershell
git status --ignored --short
```

以下はGitに含めない想定です。

- `backend/.venv/`
- `backend/data/`
- `backend/storage/`
- `frontend/node_modules/`
- `frontend/.next/`
- `.env`
- `.env.local`
