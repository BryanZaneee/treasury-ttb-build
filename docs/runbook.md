# Operator runbook

For whoever is on the hook for this service, whether or not they built it. Every
procedure here is meant to be followed literally, top to bottom, without reading the
source first.

**What this service is.** A reviewer files a label application, a vision model reads the
label image, and a deterministic rules engine compares the two field by field. Verdicts
land in a SQLite store with an append-only audit log. Serving at
`bryanzane.com/ttb-build`.

**Where things live on the app host.**

| Path | What |
| --- | --- |
| `/var/www/ttb-build` | the checkout; `deploy.sh` pulls into it |
| `/var/www/ttb-build/.env` | all configuration, both apps, one file |
| `/var/www/ttb-build/data` | SQLite store, uploaded images, snapshots. **The only irreplaceable thing here.** |
| `/etc/systemd/system/ttb-build.service` | the API |
| `/etc/systemd/system/ttb-build-backup.timer` | nightly off-box backup |
| `/var/backups/ttb-build` | local staging for the last 30 days of backups |

---

## Is it healthy?

```bash
curl -s http://127.0.0.1:8020/api/health | jq
```

`store_readable`, `images_writable` and `reader_reachable` should all be `true`. The
endpoint deliberately reports unhealthy for *any* storage failure, not only anticipated
ones, so a `false` is always worth acting on.

`reader_reachable: false` means the configured reader could not even be constructed —
almost always a missing or wrong `READER_API_KEY`. No network call is made to check it.

`counters` accumulate since the process started: `verifications`, `verdict_*`,
`cache_hits`, `cache_misses`, `reader_errors`, `spend_cap_reached`, `rate_limited`.

Logs are one JSON object per line:

```bash
journalctl -u ttb-build -f | jq -r '[.ts, .event, .request_id, (.detail // "")] | @tsv'
```

Applicant names and reviewer notes are never logged. If you need to trace one request end
to end, grab its `request_id` — it is on every line the request produced and is returned
to the client in the `x-request-id` header.

---

## Deploy

```bash
/var/www/ttb-build/deploy/deploy.sh
```

Pulls, rebuilds both sides, restarts the API, then polls `/api/health` for 20 seconds. If
it does not come up it resets to the previous commit, reinstalls and restarts — you do not
have to roll back by hand. A failed deploy exits non-zero and says what it rolled back to.

Migrations apply automatically at boot and are tracked in `schema_version`, so there is no
separate migration step.

---

## "The AI verification isn't working"

Work down this list; the first three cost nothing to check.

1. **Which reader actually ran?** Open any recent record. If it says *"read by local
   OCR"*, the vision reader failed and the service degraded rather than erroring — this
   is by design. The determination view warns the reviewer, and an OCR-only record never
   auto-closes.
2. **Is it the spend cap?** If the engine string says *"daily spend cap reached"*, nothing
   is broken. `DAILY_VISION_CALL_CAP` paid calls have been made since UTC midnight and it
   will resume on its own. Raise the cap in `.env` and `systemctl restart ttb-build` only
   if the extra spend is intended.
3. **Is the key right?** `curl -s .../api/health | jq .reader_reachable`. `false` means
   the key is missing or malformed.
4. **Is the provider up?** `reader_errors` climbing in `counters`, with `journalctl`
   showing the cause per request.

Reviewers are never blocked by any of this: verification always completes with a
rules-based verdict, and the record says which reader produced it.

## "It's slow"

Verification runs the model call inside the Verify press — this service deliberately does
not read labels on upload, so nothing is precomputed. Expect roughly the model's own
latency. `docs/benchmark.md` has the measured figures.

A repeat verification of an unchanged image is served from the extraction cache and is
near-instant. `cache_hits` versus `cache_misses` in `counters` tells you whether that is
working.

For batches, `READER_CONCURRENCY` (default 10) sets how many labels are read at once.
Raising it makes batches faster until the provider starts rate-limiting; the daily call
cap still applies on top.

---

## Restore from backup

**Rehearse this before you need it.** M7 is not met until someone who did not build the
service has done it successfully.

```bash
# 1. Stop the API so nothing writes while you swap the store.
systemctl stop ttb-build

# 2. Take the backup you want. Newest local copy:
ls -t /var/backups/ttb-build/*.age | head

# 3. Decrypt and unpack into a scratch directory first — never straight over data/.
mkdir -p /tmp/restore && cd /tmp/restore
age -d -i /path/to/age-identity /var/backups/ttb-build/ttb-build-<STAMP>.tar.gz.age \
  > restore.tar.gz
tar -xzf restore.tar.gz

# 4. Check it is what you think before committing to it.
sqlite3 records.db 'SELECT COUNT(*) FROM records;'
sqlite3 records.db 'SELECT result, COUNT(*) FROM records GROUP BY result;'
ls images | wc -l

# 5. Keep the current store aside rather than deleting it.
mv /var/www/ttb-build/data /var/www/ttb-build/data.before-restore

# 6. Put the restored copy in place. You are in /tmp/restore, where step 3
#    unpacked records.db and images/.
mkdir -p /var/www/ttb-build/data/snapshots
cp records.db /var/www/ttb-build/data/records.db
cp -a images /var/www/ttb-build/data/images
chown -R www-data:www-data /var/www/ttb-build/data

# 7. Start, and confirm.
systemctl start ttb-build
curl -s http://127.0.0.1:8020/api/health | jq
```

Once you have confirmed record counts and spot-checked a determination in the browser,
remove `data.before-restore`. Not before.

**The app's own snapshots** (`data/snapshots/*.db`) are taken automatically before every
import and reset and pruned to 30 days. They are on the same disk as the database, so they
cover "someone imported the wrong CSV", not "the box is gone". The off-box backup covers
the second case.

### Restoring records without touching the box

For "we need last week's records back", not "the disk is gone", there is a CSV path that
needs no shell. In the app: **Export → Download a restorable backup**, then **Restore from a
backup** to read one back. Both are admin-token gated, and the restore snapshots first.

The file matters. `/export/backup.csv` is the full mirror (PRD §4.2) and is what
`POST /api/store/import` reads. `/export/records.csv` — the **Export records as CSV** button —
is the reviewer's take-away and drops columns, so it will be rejected as an import.

```bash
# The same thing without the browser.
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
  http://127.0.0.1:8020/api/export/backup.csv > backup.csv

curl -X POST http://127.0.0.1:8020/api/store/import \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F 'csv_file=@backup.csv' -F 'mode=replace'
```

`mode=merge` upserts by `id`, so re-importing an export is idempotent. `mode=replace` wipes
first, which is what makes export → wipe → import → export byte-identical (S11).

---

## Resetting to the demo fixtures

Destructive: it replaces every record with the 13-record example set — part-worked on purpose,
so every inbox filter has something in it. All 25 fixtures stage as a batch instead, from
**Batch upload → Load the sample batch**. It snapshots first.
Needs the admin token, and the UI confirms behind the reviewer's own name.

```bash
curl -X POST http://127.0.0.1:8020/api/fixtures \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' -d '{"mode": "reset"}'
```

---

## Configuration worth knowing

Everything is in `/var/www/ttb-build/.env`. **Restart the API after any change** —
settings are read once at import, so an edited file changes nothing until you do.

| Setting | Why you would touch it |
| --- | --- |
| `READER_PROVIDER` | `openai` in production. `fake` replays fixtures for a zero-cost demo. `ocr` is local-only and much less accurate. |
| `DAILY_VISION_CALL_CAP` | Paid calls per UTC day. `0` disables the backstop. |
| `READER_CONCURRENCY` | Labels read at once during a batch. |
| `AUTO_APPROVE_MATCHES` | Off by default. On, a clean match closes itself — see below. |
| `QA_SAMPLE_RATE` | Fraction of otherwise auto-closeable records sent to a human anyway. |
| `ACCESS_TOKEN` / `ADMIN_TOKEN` | Shared bearer tokens; there are no user accounts. |

**Before turning on `AUTO_APPROVE_MATCHES`:** records will start closing without a human.
It only fires when every field matches, capture quality is normal, and the vision reader
(not the OCR fallback) produced the reading. Every auto-close writes an audit row. Leave
`QA_SAMPLE_RATE` non-zero so a sample keeps reaching a person.

---

## Two things that are working as intended

- **A failed record can be accepted.** A reviewer may override any verdict; the UI names
  the disagreeing fields first, and the reviewer's name, the timestamp and the override
  flag go into the audit log. The verdict itself is never rewritten — the record stays
  `fail` with `decision=accepted`.
- **The model can never improve a verdict.** The reader is never shown the application
  values and cannot express a verdict at all. Text printed on a label instructing the
  reader to approve it is transcribed as label text and then fails the comparison like any
  other mismatch.
