# Kakomon Trainer Project Context

この文書は、別のプロジェクトや別のチャットに作業を移しても、全体像が分かるようにするための引き継ぎメモです。

## 目的

Kakomon Trainer は、専門医試験の過去問を Raspberry Pi 上で管理し、ブラウザから演習するための軽量な Web アプリです。

現在の主な対象:

- 放射線診断専門医認定試験
- 核医学専門医試験
- 放射線治療専門医認定試験

## 基本方針

- Raspberry Pi 上の DB が本番データの正本です。
- GitHub にはアプリのコードと説明書だけを置きます。
- 問題 DB、PDF、抽出画像、ユーザー履歴、SSH 鍵は GitHub に置きません。
- DB を変更する前は、Pi 上でバックアップを作ります。
- 解答 markdown や PDF は取り込み後に一時ファイルから削除します。

## 主な配置

```text
GitHub / PC
  outputs/kakomon-trainer/
    server.py
    static/
    tools/
    scripts/
    docs/
    README.md

Raspberry Pi
  /home/keita/kakomon-trainer/
    server.py
    static/
    data/questions.db
    static/media/
    static/source-pdfs/
    backups/
    logs/

Google Drive
  kakomon-trainer-backup/
    daily/
    full/
```

## GitHub に入れてよいもの

- アプリ本体のコード
- 画面の HTML/CSS/JavaScript
- 取り込み用スクリプト
- バックアップ用スクリプト
- systemd 設定の見本
- Tailscale や運用の説明文書

## GitHub に入れないもの

- `data/questions.db`
- `static/media/`
- `static/source-pdfs/`
- `imports/`
- `work/`
- `backups/`
- SSH 鍵
- `.env`
- 過去問 PDF
- 解答 markdown
- 転送用の tar/zip ファイル

この境界は `.gitignore` でも管理しています。

## アプリ構成

サーバー:

- `server.py`
- Python 標準ライブラリの HTTP サーバー
- SQLite DB を使用
- `KAKOMON_DATA_DIR` で DB 保存先を変更できます

画面:

- `static/index.html`
- `static/app.js`
- `static/app.css`

主な機能:

- 試験タブの切り替え
- 分野別、年度別の演習
- 問題番号指定ジャンプ
- 前の問題、次の問題
- 複数選択問題への対応
- 判定後の自己評価: 〇、△、×
- 解答履歴と選択肢履歴
- ユーザー別履歴
- 管理者向けユーザー一覧
- 問題一覧のページ分割
- 演習画面からの分野修正
- 元 PDF 確認リンク
- iPhone 向けレイアウト

## DB

標準の保存先:

```text
data/questions.db
```

Pi 上の本番保存先:

```text
/home/keita/kakomon-trainer/data/questions.db
```

主なテーブル:

- `questions`: 問題、選択肢、解答、解説、画像、分野、年度
- `attempts`: 解答履歴、自己評価、選択肢履歴
- `users`: ユーザー管理
- `question_notes`: ユーザーごとの問題メモ

## 代表的な API

- `GET /api/session`
- `GET /api/questions`
- `POST /api/questions`
- `GET /api/stats`
- `GET /api/study-summary`
- `GET /api/attempts`
- `POST /api/attempts`
- `DELETE /api/attempts`
- `GET /api/users`
- `POST /api/users`
- `POST /api/notes/{question_id}`

## 本番起動

本番では Raspberry Pi 上で `127.0.0.1:8081` に待ち受けます。

systemd 設定の見本:

```text
kakomon-trainer.service.example
```

重要な環境変数:

```text
KAKOMON_DATA_DIR=/home/keita/kakomon-trainer/data
KAKOMON_ADMIN_USERS=your-email@example.com
```

`KAKOMON_ADMIN_USERS` には、管理者として扱う Tailscale ログインメールを設定します。

## 公開方法

基本は Tailscale 経由で接続します。

- アプリ自体は `127.0.0.1:8081` のみで待ち受けます。
- IP アドレス直打ちで外から開く構成にはしません。
- 限定公開する場合は、Tailscale または Cloudflare Access 側で認証をかけます。

招待者向けの説明はテンプレートを使います。

```text
docs/tailscale-invitee-guide.template.md
```

Tailscale と Google Drive の引き継ぎは次を参照します。

```text
docs/full-migration-handoff.md
docs/remote-access-backup-handoff.md
```

## バックアップ

Google Drive へのバックアップ設定:

```text
docs/google-drive-backup.md
```

手動バックアップ:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py full
```

DB を更新する前には、Pi 上の `backups/` に `questions.db` をコピーしてから作業します。

## 問題・解答の取り込み

PDF や解答 markdown は GitHub に入れません。

通常の流れ:

1. Pi の一時フォルダに取り込み用ファイルを置く
2. DB バックアップを作る
3. 取り込みスクリプトまたは一時スクリプトで `questions.db` を更新する
4. 件数と未登録数を確認する
5. 一時フォルダを削除する

取り込み後に確認すること:

- 該当年度の問題数が合っている
- `answer` が空の問題がない
- 複数選択の解答が `a,c` のように保存されている
- 解説が解答画面に表示される
- 画像問題の画像が表示される
- 元 PDF リンクが開ける

## 作業時の注意

- Pi 上の `/home/keita/kakomon-trainer` が本番に近い状態です。
- PC 側の `outputs/kakomon-trainer` はコード管理用です。
- 本番 DB、画像、PDF は PC 側にあっても GitHub には入れません。
- Windows の通常の `git push` が失敗することがあるため、GitHub 更新は接続済みの GitHub ツール経由が安全です。
- 既存のユーザー履歴を消さないように、DB 操作前は必ずバックアップを作ります。

## 新しいチャットや担当者に渡すとき

最初に共有するもの:

- この文書
- `README.md`
- `docs/google-drive-backup.md`
- `kakomon-trainer.service.example`

共有してはいけないもの:

- SSH 鍵
- DB 本体
- PDF
- 抽出画像
- ユーザー履歴
- Google Drive 認証トークン

必要な場合だけ、別経路で秘密情報や本番データの場所を伝えてください。
