# Full Migration Handoff

この文書は、`kakomon-trainer` を完全に引き継ぐときに、GitHub に置くものと、GitHub に置かない非公開データを分けるための資料です。

## 結論

完全移行は、1つのフォルダや1つのGitHubリポジトリだけでは完結しません。

次の3層で管理します。

```text
1. GitHub / 公開してよいコード資料
   アプリ本体、画面、取り込みスクリプト、運用手順書

2. 非公開ランタイムデータ
   DB、画像、PDF、バックアップアーカイブ

3. 認証・接続情報
   SSH鍵、Tailscaleログイン、rclone/Google Drive認証、Cloudflare設定
```

## GitHub に置くもの

GitHub に置くのは、コードと秘密を含まない説明書だけです。

```text
server.py
static/index.html
static/app.js
static/app.css
tools/
scripts/
docs/
README.md
kakomon-trainer.service.example
.gitignore
.gitattributes
start.sh
start.ps1
```

## GitHub に置かないもの

次のものは、著作権、利用者履歴、認証情報に関係するため GitHub に置きません。

```text
data/questions.db
static/media/
static/source-pdfs/
imports/
backups/
backup-staging/
logs/
work/
private-handoff/
runtime-handoff/
SSH鍵
rclone認証情報
Tailscaleログイン情報
Google Drive認証トークン
Cloudflare Access設定
実際のsystemd serviceファイル
*.db
*.pdf
*.tar.gz
*.pem
*.key
```

## 完全移行に必要なもの

完全移行には、GitHubのコードだけでなく、非公開データと認証の引き継ぎが必要です。

```text
コード:
  GitHub またはコード移行パッケージ

本番データ:
  /home/keita/kakomon-trainer/data/questions.db
  /home/keita/kakomon-trainer/static/media/
  /home/keita/kakomon-trainer/static/source-pdfs/

バックアップ:
  Google Drive: gdrive:kakomon-trainer-backup
  Pi local: /home/keita/kakomon-trainer/backup-staging/

接続:
  Tailscale
  SSH
  rclone / Google Drive
```

## 非公開資料の置き場所

Pi 上には、GitHub に入れない非公開の引き継ぎ資料を置けます。

```text
/home/keita/kakomon-trainer/private-handoff/
```

このフォルダは `.gitignore` で除外します。

ここには、DBや画像そのものではなく、次のような非公開運用メモを置きます。

```text
PRIVATE_RUNTIME_HANDOFF.md
runtime-inventory.json
restore-checklist.md
```

## 復元の考え方

新しい Pi に完全移行する場合:

1. GitHub またはコード移行パッケージからコードを配置する
2. Python と rclone を用意する
3. Tailscale にログインする
4. rclone で Google Drive に再認証する
5. Google Drive の full バックアップを取得する
6. `data/questions.db` を戻す
7. `static/media/` と `static/source-pdfs/` を戻す
8. systemd service を配置する
9. アプリを `127.0.0.1:8081` で起動する
10. Tailscale Serve を `127.0.0.1:8081` に向ける
11. ブラウザから問題、画像、履歴、解答表示を確認する

同じ Pi を使い続ける場合:

- Tailscale の再設定は通常不要です。
- rclone の再認証も通常不要です。
- Codex は `/home/keita/kakomon-trainer` を作業フォルダにします。

## 参照文書

```text
docs/project-context.md
docs/pi-codex-handoff.md
docs/remote-access-backup-handoff.md
docs/google-drive-backup.md
```
