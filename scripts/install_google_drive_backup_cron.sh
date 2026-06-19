#!/bin/sh
set -eu

APP_DIR="${KAKOMON_APP_DIR:-/home/keita/kakomon-trainer}"
REMOTE="${KAKOMON_BACKUP_REMOTE:-gdrive:kakomon-trainer-backup}"
LOG_FILE="$APP_DIR/logs/google-drive-backup.log"
PYTHON="${PYTHON:-/usr/bin/python3}"
SCRIPT="$APP_DIR/scripts/backup_to_google_drive.py"
MARK_BEGIN="# kakomon-trainer Google Drive backup BEGIN"
MARK_END="# kakomon-trainer Google Drive backup END"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$APP_DIR/backup-staging/crontab"

mkdir -p "$BACKUP_DIR" "$APP_DIR/logs"
crontab -l > "$BACKUP_DIR/crontab-before-$STAMP.txt" 2>/dev/null || true

tmp="$(mktemp)"
if crontab -l >/dev/null 2>&1; then
  crontab -l | awk -v begin="$MARK_BEGIN" -v end="$MARK_END" '
    $0 == begin {skip=1; next}
    $0 == end {skip=0; next}
    skip != 1 {print}
  ' > "$tmp"
else
  : > "$tmp"
fi

cat >> "$tmp" <<EOF
$MARK_BEGIN
17 3 * * * KAKOMON_BACKUP_REMOTE=$REMOTE $PYTHON $SCRIPT daily >> $LOG_FILE 2>&1
47 3 * * 0 KAKOMON_BACKUP_REMOTE=$REMOTE $PYTHON $SCRIPT full >> $LOG_FILE 2>&1
$MARK_END
EOF

crontab "$tmp"
rm -f "$tmp"
echo "installed cron entries for $REMOTE"
crontab -l | sed -n "/$MARK_BEGIN/,/$MARK_END/p"
