# Pi Codex Handoff

この文書は、Raspberry Pi 上で Codex を動かし、この PC からリモート接続して `kakomon-trainer` を操作するための引き継ぎメモです。

## 最初に読むもの

Pi 上で作業を始めるときは、次の順で確認します。

1. `/home/keita/kakomon-trainer/README.md`
2. `/home/keita/kakomon-trainer/docs/project-context.md`
3. `/home/keita/kakomon-trainer/docs/pi-codex-handoff.md`
4. `/home/keita/kakomon-trainer/docs/full-migration-handoff.md`
5. `/home/keita/kakomon-trainer/docs/remote-access-backup-handoff.md`
6. `/home/keita/kakomon-trainer/docs/google-drive-backup.md`

## 本番フォルダ

Pi 上の本番フォルダ:

```text
/home/keita/kakomon-trainer
```

このフォルダには、コードだけでなく本番データもあります。

```text
/home/keita/kakomon-trainer/server.py
/home/keita/kakomon-trainer/static/
/home/keita/kakomon-trainer/data/questions.db
/home/keita/kakomon-trainer/static/media/
/home/keita/kakomon-trainer/static/source-pdfs/
/home/keita/kakomon-trainer/backups/
/home/keita/kakomon-trainer/logs/
```

GitHub に入れるのはコードと説明書だけです。DB、PDF、画像、履歴、鍵は GitHub に入れません。

## Codex に見せるべき範囲

Pi 上で Codex が実作業をする場合は、`/home/keita/kakomon-trainer` を作業フォルダにします。

```sh
cd /home/keita/kakomon-trainer
```

このフォルダを見れば、アプリ本体、DB、画像、バックアップの位置が分かります。

ただし、GitHub に反映してよいのは次のようなコードと文書だけです。

```text
server.py
static/app.js
static/app.css
static/index.html
tools/
scripts/
docs/
README.md
kakomon-trainer.service.example
```

## 絶対に GitHub に入れないもの

```text
data/questions.db
static/media/
static/source-pdfs/
imports/
backups/
logs/
work/
SSH 鍵
Google Drive 認証トークン
.env
*.db
*.pdf
*.tar.gz
```

## アプリの待ち受け

アプリ本体は Pi 上で `127.0.0.1:8081` に待ち受けます。

```sh
python3 /home/keita/kakomon-trainer/server.py --host 127.0.0.1 --port 8081
```

systemd の見本:

```text
/home/keita/kakomon-trainer/kakomon-trainer.service.example
```

実際の service ファイルには、管理者ユーザーなどの実設定が含まれる可能性があるため、GitHub には見本だけを置きます。

## Tailscale

同じ Raspberry Pi を使い続ける場合、通常は Tailscale の再設定は不要です。

詳しい引き継ぎは次を参照します。

```text
/home/keita/kakomon-trainer/docs/remote-access-backup-handoff.md
```

現在の想定:

```text
Tailscale hostname: <tailscale-hostname>
Tailscale Serve: https://<tailscale-hostname>.<tailnet-domain>
Proxy target: http://127.0.0.1:8081
Scope: tailnet only
```

Codex を Pi 上で使うこと自体は、Tailscale Serve の設定を変更しません。

Tailscale の再設定が必要になる主なケース:

- 新しい Raspberry Pi に移す
- SD カードや OS を入れ直す
- `tailscale logout` した
- Tailscale の端末登録を管理画面から削除した
- tailnet やアカウントを変更した
- `tailscale serve reset` などで Serve 設定を消した

確認コマンド:

```sh
tailscale status --self
tailscale serve status
```

期待される Serve 設定:

```text
https://<tailscale-hostname>.<tailnet-domain>
|-- / proxy http://127.0.0.1:8081
```

## PC からの接続

SSH 鍵はプロジェクト内に置きません。PC 側の安全な場所に置きます。

接続情報は環境に合わせて確認します。

```text
user: <pi-user>
ssh port: <ssh-port>
app dir: /home/keita/kakomon-trainer
```

LAN から接続する場合の例:

```sh
ssh -p <ssh-port> <pi-user>@<lan-ip>
```

Tailscale 経由で接続する場合は、Tailscale IP またはホスト名を使います。

## DB 更新前のルール

DB を変更する前に、必ず Pi 上でバックアップを作ります。

```sh
mkdir -p /home/keita/kakomon-trainer/backups/before-change-YYYYMMDD-HHMMSS
cp /home/keita/kakomon-trainer/data/questions.db \
  /home/keita/kakomon-trainer/backups/before-change-YYYYMMDD-HHMMSS/questions.db
```

更新後に確認すること:

- 問題数が減っていない
- 解答が空になっていない
- 画像が表示される
- 解答履歴が残っている
- Tailscale URL から開ける

## バックアップ

Google Drive バックアップの説明:

```text
/home/keita/kakomon-trainer/docs/remote-access-backup-handoff.md
/home/keita/kakomon-trainer/docs/google-drive-backup.md
```

手動バックアップ:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py full
```

完全復元に必要なもの:

```text
data/questions.db
static/media/
static/source-pdfs/
必要に応じて backups/
```

## 新しい環境へ完全移行するとき

新しい Pi に移す場合は、コードだけでは足りません。

必要なもの:

```text
GitHub またはコード移行パッケージ
Google Drive などにある DB・画像・PDF バックアップ
Tailscale の再ログイン
必要なら Cloudflare Access の再設定
新しい SSH 鍵の登録
systemd service の再配置
```

同じ Pi を使う場合は、Tailscale の再設定は通常不要です。
