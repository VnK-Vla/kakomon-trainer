# Google Drive backup

This Raspberry Pi backs up `/home/keita/kakomon-trainer` to Google Drive with rclone.

## Schedule

- Daily backup: every day at 03:17 JST
- Full backup: every Sunday at 03:47 JST

The crontab block is managed by:

```sh
/home/keita/kakomon-trainer/scripts/install_google_drive_backup_cron.sh
```

## Destination

```text
gdrive:kakomon-trainer-backup
```

Backups are split into:

- `daily/`: database, imports, code, tools, manifest
- `full/`: daily contents plus `static/media` and `static/source-pdfs`

## Retention

- Daily: 30 archives
- Full: 8 archives

These values can be changed with:

```sh
KAKOMON_BACKUP_DAILY_KEEP=30
KAKOMON_BACKUP_FULL_KEEP=8
```

## Manual Backup

Daily:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily
```

Full:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py full
```

Local archive only:

```sh
/usr/bin/python3 /home/keita/kakomon-trainer/scripts/backup_to_google_drive.py daily --no-upload
```

## Logs

```sh
tail -n 100 /home/keita/kakomon-trainer/logs/google-drive-backup.log
```

## Restore Outline

1. Download the archive from Google Drive.
2. Extract it into a temporary directory.
3. Stop the app if it is running.
4. Copy `kakomon-trainer/data/questions.db` back to `/home/keita/kakomon-trainer/data/questions.db`.
5. If needed, copy `imports/`, `static/media/`, and `static/source-pdfs/`.
6. Start the app again.

Example:

```sh
mkdir -p /tmp/kakomon-restore
tar -xzf kakomon-daily-YYYYMMDD-HHMMSS.tar.gz -C /tmp/kakomon-restore
cp /tmp/kakomon-restore/kakomon-trainer/data/questions.db /home/keita/kakomon-trainer/data/questions.db
```

The `manifest.json` inside each archive records question counts, user counts, and source data sizes.
