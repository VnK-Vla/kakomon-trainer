# Kakomon Trainer

資格試験の過去問をRaspberry Pi上で管理し、ブラウザから演習するためのWebアプリです。

## GitHubに置くもの

このリポジトリには、アプリのコードと手順書だけを置きます。

- `server.py`
- `static/app.js`
- `static/app.css`
- `static/index.html`
- `tools/`
- `scripts/`
- `README.md`
- `kakomon-trainer.service.example`
- Tailscaleやバックアップの説明文書

## GitHubに置かないもの

著作権、利用者履歴、認証情報に関わるため、次のデータはGitHubに置きません。

- SSH鍵
- `work/`
- `data/questions.db`
- ユーザー履歴やメモを含むDB
- 過去問PDF
- PDFから抜き出した画像
- `static/media/`
- `static/source-pdfs/`
- `imports/`
- `*.tar.gz` などの転送用ファイル

これらはRaspberry Pi、PC、外付けストレージ、Google Driveなどで管理します。

## 推奨構成

```text
GitHub
  アプリのコード
  画面デザイン
  取り込みスクリプト
  設定ファイルの見本
  手順書

Raspberry Pi
  本番DB
  問題画像
  ユーザー履歴
  ユーザーメモ

PC / Google Drive
  元PDF
  DBバックアップ
  画像バックアップ
  SSH鍵
```

## 起動

```sh
python server.py --host 127.0.0.1 --port 8081
```

ブラウザで次を開きます。

```text
http://127.0.0.1:8081
```

Raspberry PiでTailscale Serveを使う場合も、アプリ本体は `127.0.0.1:8081` だけで待ち受ける構成にします。

## データ保存先

標準では次にSQLite DBを作ります。

```text
data/questions.db
```

保存先を変える場合は `KAKOMON_DATA_DIR` を指定します。

```sh
KAKOMON_DATA_DIR=/home/keita/kakomon-trainer/data python server.py --host 127.0.0.1 --port 8081
```

## Raspberry Piでの運用

systemd user serviceの見本は次のファイルです。

```text
kakomon-trainer.service.example
```

実運用では `KAKOMON_ADMIN_USERS` を自分のTailscaleログインメールに変更してください。

```text
KAKOMON_ADMIN_USERS=your-email@example.com
```

## バックアップ

Google Driveバックアップの手順は次を参照してください。

```text
docs/google-drive-backup.md
```
