# Kakomon Trainer

Raspberry Pi上で動かす、資格試験の過去問演習用Webアプリです。

## 保存場所の方針

GitHubにはコードと手順書だけを置きます。問題データ、画像、履歴、メモ、SSH鍵は置きません。

- GitHub: アプリコード、画面、取り込みスクリプト、設定例、手順書
- Raspberry Pi: 本番DB、問題画像、ユーザー履歴、ユーザーメモ
- PC/外部ストレージ: 元PDF、DBバックアップ、画像バックアップ、SSH鍵

## ローカル起動

```sh
python server.py --host 127.0.0.1 --port 8081
```

ブラウザで開きます。

```text
http://127.0.0.1:8081
```

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

systemd user serviceの例は次のファイルです。

```text
kakomon-trainer.service.example
```

実運用では `KAKOMON_ADMIN_USERS` を自分のTailscaleログインメールに変更してください。

```text
KAKOMON_ADMIN_USERS=your-email@example.com
```

Tailscale Serveで公開する場合、アプリ本体は `127.0.0.1:8081` のみに待ち受けさせます。

```sh
python server.py --host 127.0.0.1 --port 8081
```

`0.0.0.0:8081` で直接公開しないでください。

## GitHubに入れないもの

`.gitignore` で以下を除外しています。

- `data/`
- `static/media/`
- `import_pdfs/`
- `backups/`
- `*.db`
- `*.pdf`
- `*.tar.gz`
- SSH鍵や秘密情報
- 実運用の `kakomon-trainer.service`

## 機能

- 試験種別の切り替え
- 分野別・年度別演習
- 問題番号ジャンプ
- 前後の問題への移動
- ユーザー別の解答履歴
- ユーザー別の問題メモ
- 自己評価: 〇、△、×
- 管理者だけが使えるユーザー管理・問題修正

## 取り込みスクリプト

PDFや解答Markdownの取り込み補助スクリプトは `tools/` にあります。

```text
tools/
```

元PDFや生成画像はGitHubには入れず、Raspberry Piまたはバックアップ用ストレージで管理してください。
