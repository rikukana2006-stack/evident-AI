# TODO

## 現在未確認の点

- PostgreSQL接続での実起動確認は未実施です。現在のMVPはSQLite起動を標準にしています。
- Windows実機で、READMEのクリーンインストール手順を最初から最後まで通す確認が必要です。
- GitHub remoteを実際に設定してのpushは未実施です。リポジトリURL決定後に実行してください。
- backendとfrontendを同時起動した状態で、アップロードからCSV exportまでのE2E確認が必要です。

## 今後確認が必要な点

- mock OCRを実AI OCRに差し替えるためのサービス境界とエラー処理
- アップロード可能なファイル形式、サイズ上限、保存期間の仕様
- 認証をmock loginから本実装へ移行する設計
- PostgreSQL利用時のマイグレーション管理
- CSV exportの項目名、文字コード、Excel互換性
- 明細名の類似判定しきい値の業務レビュー
- テスト追加: matching logic、API、主要画面操作
