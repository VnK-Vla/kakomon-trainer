# Remote Access and Backup Handoff

この文書は、Tailscale と Google Drive バックアップを引き継ぐための運用メモです。

`kakomon-trainer` のコードは GitHub で管理できますが、接続設定やバックアップ認証は GitHub に入れません。

## 現在の確認結果

確認日: 2026-06-20

Tailscale:

```text
hostname: <tailscale-hostname>
Tailscale IP: <tailscale-ip>
Serve URL: https://<tailscale-hostname>.<tailnet-domain>
Serve target: http://127.0.0.1:8081
scope: tailnet only
```

Google Drive:

```text
rclone: /usr/bin/rclone
rclone remote: gdrive:
backup destination: gdrive:kakomon-trainer-backup
daily backup: confirmed
full backup: confirmed manually on 2026-06-20
latest confirmed full archive: recorded in private-handoff/runtime-inventory.json
```

Cron:

```text
17 3 * * * daily backup
47 3 * * 0 full backup
```

## 何を引き継ぐか

引き継ぐべきものは3種類に分けます。

### 1. GitHub に入れてよいもの

```text
docs/remote-access-backup-handoff.md
docs/google-drive-backup.md
docs/tailscale-*.template.md
scripts/backup_to_google_drive.py
scripts/install_google_drive_backup_cron.sh
kakomon-trainer.service.example
```

### 2. Pi 上に残すもの

```text
/home/keita/kakomon-trainer/data/questions.db
/home/keita/kakomon-trainer/static/media/
/home/keita/kakomon-trainer/static/source-pdfs/
/home/keita/kakomon-trainer/backup-staging/
/home/keita/kakomon-trainer/logs/
```

### 3. GitHub に入れず、別管理するもの

```text
SSH 鍵
rclone の認証トークン
Tailscale のログイン状態
Cloudflare Access の設定
.env
実際の systemd service ファイル
```

## Tailscale の引き継ぎ

同じ Raspberry Pi を使い続ける場合は、通常 Tailscale の再設定は不要です。

確認:

```sh
tailscale status --self
tailscale serve status
```

期待される Serve 設定:

```text
https://<tailscale-hostname>.<tailnet-domain>
|-- / proxy http://127.0.0.1:8081
```

アプリ本体は次で待ち受けます。

```text
http://127.0.0.1:8081
```

Tailscale は、そのローカルアプリを tailnet 内へ中継します。

## Tailscale の再設定が必要な場合

次の場合は再設定が必要になることがあります。

- 新しい Raspberry Pi に移す
- SD カードや OS を入れ直す
- `tailscale logout` を実行した
- Tailscale 管理画面で端末登録を削除した
- tailnet やログインアカウントを変えた
- `tailscale serve reset` で公開設定を消した

再設定時の考え方:

1. Pi で Tailscale にログインする
2. `tailscale status --self` で端末が見えることを確認する
3. アプリが `127.0.0.1:8081` で動いていることを確認する
4. Tailscale Serve を `127.0.0.1:8081` に向ける
5. `tailscale serve status` で設定を確認する

実際の再ログインや Serve 設定には認証が関係するため、GitHub にはトークンやログイン情報を残しません。

## Google Drive バックアップの引き継ぎ

Google Drive バックアップは `rclone` を使います。

確認:

```sh
rclone listremotes
rclone lsd gdrive:kakomon-trainer-backup
rclone lsf gdrive:kakomon-trainer-backup/daily --files-only
tail -n 100 /home/keita/kakomon-trainer/logs/google-drive-backup.log
```

バックアップ先:

```text
gdrive:kakomon-trainer-backup
```

保存先の意味:

```text
daily/
  DB、imports、コード、tools、manifest

full/
  daily の内容に加えて static/media と static/source-pdfs
```

`full/` は毎週日曜に自動作成されます。

実際に確認済みの full バックアップ名、サイズ、sha256 は非公開資料に記録します。

```text
/home/keita/kakomon-trainer/private-handoff/runtime-inventory.json
```

## Cron の確認と再登録

確認:

```sh
crontab -l
```

期待されるブロック:

```text
# kakomon-trainer Google Drive backup BEGIN
17 3 * * * KAKOMON_BACKUP_REMOTE=gdrive:kakomon-trainer-backup /usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily >> /home/keita/kakomon-trainer/logs/google-drive-backup.log 2>&1
47 3 * * 0 KAKOMON_BACKUP_REMOTE=gdrive:kakomon-trainer-backup /usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py full >> /home/keita/kakomon-trainer/logs/google-drive-backup.log 2>&1
# kakomon-trainer Google Drive backup END
```

再登録:

```sh
/home/keita/kakomon-trainer/scripts/install_google_drive_backup_cron.sh
```

## 手動バックアップ

Daily:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily
```

Full:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py full
```

ローカルアーカイブだけ作る:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily --no-upload
```

## 新しい Pi に移す場合

新しい Pi に完全移行する場合は、コードだけでは足りません。

必要なもの:

```text
GitHub またはコード移行パッケージ
Google Drive のバックアップアーカイブ
Tailscale の再ログイン
rclone の再認証
新しい SSH 鍵の登録
systemd service の設定
```

復元の流れ:

1. 新しい Pi にコードを配置する
2. Python と rclone を用意する
3. Tailscale にログインする
4. rclone で Google Drive に接続する
5. Google Drive からバックアップを取得する
6. `data/questions.db` を戻す
7. 必要に応じて `static/media/` と `static/source-pdfs/` を戻す
8. アプリを起動する
9. Tailscale Serve を設定する
10. ブラウザから動作確認する

## 認証情報の扱い

rclone の認証ファイルや Tailscale のログイン状態は、便利ですが秘密情報に近いものです。

GitHub には置きません。

新しい Pi に移す場合は、古い認証ファイルを無造作にコピーするより、原則として再ログイン・再認証します。

どうしても認証情報をバックアップする場合は、GitHub ではなく、暗号化した安全な保管場所に置きます。
