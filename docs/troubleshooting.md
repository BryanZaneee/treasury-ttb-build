# Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| **"Could not reach the API"** | The API is not up on :8000. Start it, or point the dev proxy elsewhere with `DEV_API_URL`. |
| Inbox is **empty** on a fresh clone | `data/` is gitignored: `cd api && uv run python seed.py`. |
| Every record says **"Awaiting AI verification"** | Working as intended — nothing is read until you ask. |
| Amber strip: **"not using the vision reader"** | `READER_PROVIDER` is `fake`/`ocr`, or the reader could not be built. Check `OPENAI_API_KEY` and `GET /api/health`. |
| A **"Read by local OCR"** chip | The vision reader was unreachable and the service degraded rather than failing. |
| **"daily paid-call cap reached"** | Not a fault. `DAILY_VISION_CALL_CAP` is spent until UTC midnight. |
| Asked for an **administrator token** | Expected when `VITE_ADMIN_TOKEN` is empty. Enter `ADMIN_TOKEN` from the host's `.env`. |
| **401 downloading a restorable backup** | It is admin-gated. The plain **Export records as CSV** is not. |
| `npm install` fails on peer dependencies | Use `--legacy-peer-deps`, as CI does. |
| A deep link 404s in production | `PUBLIC_BASE_PATH` disagrees between build and proxy; rebuild the frontend. |

**First thing to check, always:** `curl -s localhost:8000/api/health | jq`. Settings are parsed
once at import, so an edited `.env` changes nothing until the API restarts.

**Getting back to a known state:** **Records → Load the example set** restores the thirteen,
**Remove all records** empties the store, and both snapshot into `data/snapshots/` first.

## Knobs the README does not list

`.env.example` carries all of them with comments; these are the ones that matter when
something is misbehaving.

| Variable | When you reach for it |
| --- | --- |
| `READER_MODEL` / `READER_EFFORT` | Changing the vision model. Both are part of the extraction cache key, so a change invalidates cached readings rather than serving stale ones. |
| `READER_BASE_URL` | Pointing at any other OpenAI-compatible endpoint. Empty uses the OpenAI default. |
| `READER_TIMEOUT_S` | Vision calls timing out and degrading to OCR more often than they should. Default 25. |
| `READER_CONCURRENCY` | Batch runs too slow, or the provider rate-limiting. Default 10 (PRD §8). |
| `DAILY_VISION_CALL_CAP` | Paid calls per UTC day. `0` disables the cap. Default 300. |
| `AUTO_APPROVE_MATCHES` / `QA_SAMPLE_RATE` | Whether clean matches close themselves, and the fraction sent to a human anyway. Off and 0.05 by default (PRD §5.3). |
| `DEV_API_URL` | Where `npm run dev` proxies `/api`. Defaults to `http://127.0.0.1:8000`. |
| `LIVE_READER` | Runs the three live-reader injection tests, which cost money and are skipped in CI. |
| `BACKUP_DEST` / `BACKUP_RECIPIENT` | Read by `deploy/backup.sh` on the app host only; it refuses to run without both. |
