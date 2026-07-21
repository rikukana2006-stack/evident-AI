# TODO

## 実帳票サンプルから判明した次課題

- 水野産業の横向きスキャンPDFに対応するため、OCR前のページ回転補正を追加する。
- ヘルシーフードのような複数ページ納品書は、ページごとの明細を集計してから請求書と突合する。
- サトウ教材のように商品コードと商品名が同じ列に近い帳票では、商品コードを保持しつつ商品名正規化を強化する。
- OCRで商品名が一部崩れても、数量・単価・金額が一致する場合は同一候補として扱う。
- 取引先プロファイルは、初回から完全な個別テンプレートを作るのではなく、実データで崩れた点だけルール化する。

## 確認済み

- GitHub remote設定と `main` ブランチのpush
- frontend起動確認: `http://localhost:3002`
- backend起動確認: `http://127.0.0.1:8000/health`
- API経由のE2E確認
  - document upload
  - mock OCR
  - CSV OCR JSON conversion
  - XLSX OCR JSON conversion
  - OCR review save
  - matching run
  - hold / approve / reject
  - CSV export
- backend unit tests
  - matching logic
  - CSV OCR JSON conversion
  - XLSX OCR JSON conversion
  - upload to matching API flow
- 期待される突合結果
  - 牛乳: `name_check_required`、数量差異、金額差異
  - パン: 単価差異、金額差異
- アップロード許可形式
  - PDF
  - 画像: PNG, JPG, JPEG, WEBP, TIFF
  - Excel: XLSX, XLS
  - CSV

## 現在未確認の点

- in-app browser上でのクリック操作による画面E2E確認
- PostgreSQL接続での実起動確認
- Windows実機で、READMEのクリーンインストール手順を最初から最後まで通す確認
- PDF/画像/Excel/CSVの実ファイルを使った画面アップロード確認
- `.xls` の本解析

## 今後確認が必要な点

- mock OCRを実AI OCRに差し替えるためのサービス境界とエラー処理
- PDF/画像OCRの本実装
- `.xls` バイナリExcel解析の本実装
- ファイルサイズ上限、保存期間の仕様
- 認証をmock loginから本実装へ移行する設計
- PostgreSQL利用時のマイグレーション管理
- CSV exportの項目名、文字コード、Excel互換性
- 明細名の類似判定しきい値の業務レビュー
- テスト追加: 主要画面操作
