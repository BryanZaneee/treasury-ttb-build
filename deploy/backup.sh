#!/usr/bin/env bash
# Nightly off-box backup of the record store (PRD §8).
#
# Snapshots written by the app are file copies on the same disk as the database,
# which does not survive losing the box. This takes a consistent copy, encrypts
# it, ships it off the host, and prunes both ends to 30 days.
#
# Run by the systemd timer:  /var/www/ttb-build/deploy/backup.sh
set -euo pipefail

APP=/var/www/ttb-build
DATA="${DATA_DIR:-$APP/data}"
STAGING=/var/backups/ttb-build
RETENTION_DAYS=30

# Where the encrypted copy goes and who can read it. Both must be set in the
# unit's environment; failing loudly beats writing an unencrypted backup or
# quietly keeping it on the same disk.
: "${BACKUP_DEST:?set BACKUP_DEST, e.g. user@host:/srv/backups/ttb-build}"
: "${BACKUP_RECIPIENT:?set BACKUP_RECIPIENT to the age public key to encrypt to}"

STAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
mkdir -p "$STAGING"
ARCHIVE="$STAGING/ttb-build-$STAMP.tar.gz"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# sqlite3 .backup rather than cp: the app is running and WAL means a plain copy
# can catch a torn write.
sqlite3 "$DATA/records.db" ".backup '$WORK/records.db'"
cp -a "$DATA/images" "$WORK/images"

tar -czf "$ARCHIVE" -C "$WORK" records.db images
age -r "$BACKUP_RECIPIENT" -o "$ARCHIVE.age" "$ARCHIVE"
rm -f "$ARCHIVE"

echo "==> $(du -h "$ARCHIVE.age" | cut -f1) encrypted, shipping to $BACKUP_DEST"
rsync -a --timeout=120 "$ARCHIVE.age" "$BACKUP_DEST/"

# Local staging first, then the far end. Keeping the last copy on the box is
# deliberate: a restore during an outage should not depend on the network.
find "$STAGING" -name '*.age' -mtime "+$RETENTION_DAYS" -delete
DEST_HOST="${BACKUP_DEST%%:*}"
DEST_PATH="${BACKUP_DEST#*:}"
ssh "$DEST_HOST" "find '$DEST_PATH' -name '*.age' -mtime +$RETENTION_DAYS -delete"

echo "==> backup complete: $(basename "$ARCHIVE.age")"
