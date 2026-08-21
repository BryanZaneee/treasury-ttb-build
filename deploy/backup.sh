#!/usr/bin/env bash
# Nightly off-box backup of the record store (PRD §8), run by the systemd timer.
# The app's own snapshots sit on the same disk as the database, which does not
# survive losing the box. This encrypts a consistent copy, ships it, and prunes
# both ends to 30 days.
set -euo pipefail

APP=/var/www/ttb-build
DATA="${DATA_DIR:-$APP/data}"
STAGING=/var/backups/ttb-build
RETENTION_DAYS=30

# Both must be set: failing loudly beats an unencrypted backup, or one that
# never leaves the disk it is protecting against losing.
: "${BACKUP_DEST:?set BACKUP_DEST, e.g. user@host:/srv/backups/ttb-build}"
: "${BACKUP_RECIPIENT:?set BACKUP_RECIPIENT to the age public key to encrypt to}"

STAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
mkdir -p "$STAGING"
ARCHIVE="$STAGING/ttb-build-$STAMP.tar.gz"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# sqlite3 .backup, not cp: the app is running and WAL can give a torn copy.
sqlite3 "$DATA/records.db" ".backup '$WORK/records.db'"
cp -a "$DATA/images" "$WORK/images"

tar -czf "$ARCHIVE" -C "$WORK" records.db images
age -r "$BACKUP_RECIPIENT" -o "$ARCHIVE.age" "$ARCHIVE"
rm -f "$ARCHIVE"

echo "==> $(du -h "$ARCHIVE.age" | cut -f1) encrypted, shipping to $BACKUP_DEST"
rsync -a --timeout=120 "$ARCHIVE.age" "$BACKUP_DEST/"

# The last copy stays on the box: a restore during an outage needs no network.
find "$STAGING" -name '*.age' -mtime "+$RETENTION_DAYS" -delete
DEST_HOST="${BACKUP_DEST%%:*}"
DEST_PATH="${BACKUP_DEST#*:}"
ssh "$DEST_HOST" "find '$DEST_PATH' -name '*.age' -mtime +$RETENTION_DAYS -delete"

echo "==> backup complete: $(basename "$ARCHIVE.age")"
