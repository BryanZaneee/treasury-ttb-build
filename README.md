# Label Verification Service

AI-assisted TTB-style COLA label verification. A reviewer files an application, a reader
extracts the same seven fields from the label image, and a **deterministic rules engine**
adjudicates the two field by field into `match` / `review` / `fail`. Every determination is
written to an auditable system of record.

**Live:** <https://bryanzane.com/ttb-build> · **Spec:** [`docs/PRD.md`](docs/PRD.md)

**All data in this deployment is synthetic.** The 25 label images are generated, the brands
are fictional, and no real applicant information exists anywhere in the system.

---

## Setup

| Need | Version | Notes |
| --- | --- | --- |
| Python | 3.12 or newer | required by `api/pyproject.toml` |
| [uv](https://docs.astral.sh/uv/) | current | the only Python package manager used here |
| Node | 22 | the version CI builds against |
| Tesseract | optional | only for `READER_PROVIDER=ocr`: `brew install tesseract` |

Two processes, two terminals: the API on **:8000** and the frontend on **:5173**.

### 1. Get the code and configure

```bash
git clone https://github.com/BryanZaneee/treasury-ttb-build.git
cd treasury-ttb-build
cp .env.example .env
```

`.env` lives at the **repo root**, not inside `api/` or `web/` — both sides read the one copy.
Set `ACCESS_TOKEN`, `ADMIN_TOKEN` and their `VITE_` copies to any non-empty string for local
use. For the real vision reader set `OPENAI_API_KEY` (or `READER_API_KEY`); to run with no key
and no spend, set `READER_PROVIDER=fake`.

### 2. Start the API

```bash
cd api
uv sync
uv run python seed.py                        # prints "seeded 13 records"
uv run uvicorn main:app --reload --port 8000
```

The seed step is required on a fresh clone: `data/` is gitignored, so the SQLite store does not
exist until you create it.

### 3. Start the frontend

In a second terminal:

```bash
cd web
npm install --legacy-peer-deps
npm run dev
```

### 4. Use it

Open <http://localhost:5173>. The inbox opens on the **13-record example set**, deliberately
part-worked so every filter has something in it: three awaiting verification, three matched,
three in review, four failed, three already decided.

Press **Run AI verification on all** to work the unverified ones, or open any record and verify
it alone. All 25 fixtures stage as a batch from **Batch upload → Load bundled sample batch**;
`docs/demo/batch-demo.csv` plus `uv run python scripts/make_demo_batch.py` builds a batch that
lands in all five filename-pairing buckets. Adversarial labels live in `api/fixtures/injection/`.

> **Running with no spend:** set `READER_PROVIDER=fake`. The fake reader replays
> `api/fixtures/expectations.json`, so every fixture reaches its documented verdict instantly,
> offline and free. This is the reader CI uses, and what keeps the suite deterministic.

### 5. Run the checks

```bash
cd api && uv run ruff check . && uv run mypy . && uv run pytest -q     # 205 tests, 3 skipped
cd web && npm run lint && npm run test && npm run build                # 16 tests
cd web && npx playwright test                                          # 16 specs
```

No API key needed — every suite runs against the fixture replayer. CI runs all three on every
push, plus `pip-audit` and `npm audit` as advisory steps. The three skipped tests are the
live-reader injection cases; they need `LIVE_READER` and cost money.

Something not coming up? See [docs/troubleshooting.md](docs/troubleshooting.md).

### Configuration

Only these are needed to run. `.env.example` is commented in full and is the reference
for the rest — reader model, timeouts, concurrency, spend cap, backup target.

| Variable | Purpose |
| --- | --- |
| `READER_PROVIDER` | `fake`, `ocr` or `openai`. Which reader verification uses. |
| `OPENAI_API_KEY` | Key for the vision reader. Only needed for `openai`. |
| `ACCESS_TOKEN` / `ADMIN_TOKEN` | Shared bearer tokens. There are no user accounts (PRD §8). |
| `VITE_ACCESS_TOKEN` / `VITE_ADMIN_TOKEN` | The browser's copies. See the warning below. |
| `DATA_DIR` | Where the SQLite store, images and snapshots live. |
| `PUBLIC_BASE_PATH` | Subpath the app is served under in production. Empty locally. |

Anything prefixed `VITE_` is compiled into the browser bundle and is therefore public (PRD §8).
**Never give the reader API key a `VITE_` prefix**, and leave `VITE_ADMIN_TOKEN` empty in
production — the app then asks a reviewer for the admin token and keeps it for that tab only.

---

## Features

- **Check one label** — file an image plus the seven application fields, get a verdict back.
- **Named-sample prefill** — twelve documented labels, each noting what it demonstrates.
- **Batch upload** — application CSV plus an image folder, paired on filename across all five
  buckets; commit is blocked while a row is ambiguous.
- **Filtered inbox with search** — needs attention, awaiting AI, review, fail, closed; searched
  over ID, applicant, brand and filename, case- and punctuation-insensitively.
- **Verify in place, or everything pending at once** — per-record progress, one failure does
  not abort the rest.
- **Accept a flagged record** behind a confirmation naming every disagreeing field; stores the
  reviewer, timestamp and an override flag.
- **Return to applicant** with an editable reason that persists into the export.
- **CSV export, import and a blank template** — a reviewer-facing export, a full restorable
  backup, and a round trip that is byte-identical.
- **Reset to the example set** — admin-gated, snapshotting the current store first.
- **The rules engine owns the verdict.** The reader never sees the application and has no
  verdict field, so PRD §3.2 holds by construction.
- **Verification degrades rather than blocking.** An unreachable vision reader falls back to
  local OCR and the record carries a *Read by local OCR* chip.
- **Nothing is read until asked**, repeat reads are cached, and `DAILY_VISION_CALL_CAP` caps
  spend for the day.
- **Every determination is auditable** — decisions, overrides, imports and resets append to a
  log that is never rewritten.

---

## Approach

Label review today is manual double-entry: an agent reads the label, reads the application, and
compares seven fields by eye. It is slow, inconsistent between agents, and formatting noise
(title case, a unit written differently, an optional statement) is indistinguishable from
substantive error until a human has already spent the attention on it.

Thirteen user stories with one testable acceptance line each (PRD §2) came first, then
[`docs/PRD.md`](docs/PRD.md) fixing the domain model, persistence schema, API surface, routes
and design tokens, fixture set and an M0–M7 roadmap with per-milestone exit criteria. Behaviour
is not invented at the keyboard: if the PRD settles a question, the code follows and the comment
cites the section. The rules engine had to be green against all 25 fixture expectations before
any reader code existed — that ordering is why the reader is swappable.

Six things went the other way, and the PRD was revised to v1.2 to match the build:

| Departure | Why |
| --- | --- |
| **A label is read only when a reviewer asks**, not on upload | Extraction costs money per call; a filing nobody verifies must never pay for one. |
| **One vision provider**, not two side by side | The abstraction it needed was a per-provider table with one row in it. |
| **OCR is the fallback**, not an always-on second reader | Measured at 85 of 155 fields against the vision reader's 122 — enough to fall back to, not to gate auto-close on. |
| **A fourth verdict, `invalid`** | An image that is not a label cannot be adjudicated field by field, and `fail` would blame the applicant's label. |
| **Job progress is polled**, not streamed over SSE | One endpoint fewer for a queue this size. |
| **No Docker** | The host already runs Caddy and several services under systemd. |

**One rule holds the design together: rules own the verdict.** A reader reports what is printed
on the label. It never sees the application and cannot express a verdict at all — the response
schema is closed. That is what makes the reader safe to treat as configuration, and why a label
printing *"ignore all previous instructions"* is simply transcribed and then fails the
comparison like any other mismatch (PRD §3.3). A reviewer *can* overrule a verdict, but never
silently: the override names every disagreeing field and lands in an append-only audit log.

### The readers

| Reader | Speed | Cost | What it is |
| --- | --- | --- | --- |
| `openai` | p50 2.5 s, p95 4.1 s | metered | `gpt-5.6-luna` vision at `effort=none`. Production. |
| `ocr` | p95 0.8 s | none | Local Tesseract, two page-segmentation passes. The fallback. |
| `fake` | instant | none | Replays the fixture ground truth. The CI reader (PRD §5.4). |

Those figures are measured, not estimated: `scripts/bench.py` over four configurations and all
25 fixtures picked `gpt-5.6-luna` at `effort=none` as the only one clearing the five-second p95
target while beating both `gpt-4.1` models on accuracy. Full table in PRD §5.4. Re-run it before
changing the model, `MAX_EDGE` or `JPEG_QUALITY`.

### Layout

```
api/            FastAPI, flat modules — db, adjudicate, csv_io, batching, models
  routers/      records, batches, jobs, store — all mounted under /api
  readers/      vision, ocr, fake, image prep, versioned prompts
  migrations/   numbered SQL, applied at boot, tracked in schema_version
  fixtures/     25 label images, applications.csv, expectations.json, injection/
  tests/        one module per api module; conftest.py isolates DATA_DIR
web/src/        React 19 — routes/, components/, lib/ (copy, search, job, dialog)
web/e2e/        Playwright suite and the axe-core accessibility audit
deploy/         Caddyfile, systemd units, deploy.sh, backup.sh
docs/           PRD.md, fixture manifest, troubleshooting.md
data/           SQLite store, images, snapshots, CSV mirror. Gitignored.
```

---

## Tools used

VS Code, with Claude Code and Codex as the AI pair for implementation. Both were driven from the
PRD rather than ad-hoc prompts, so generated code always had a written spec to be checked
against. Three things made that safe: the semantics were fixed in writing first, the 25 fixtures
gave a pass/fail oracle rather than an opinion, and CI ran on every push.

| Layer | Choice |
| --- | --- |
| Frontend | React 19, TypeScript strict, Vite, React Router, TanStack Query |
| Backend | Python 3.12, FastAPI, Pydantic |
| Store | SQLite via the stdlib `sqlite3` module, WAL mode, no ORM, derived CSV mirror |
| Reader | `gpt-5.6-luna` vision, with local Tesseract OCR always available as the fallback |
| Tests | pytest, Vitest, Playwright with axe-core for the accessibility audit |
| Deploy | Caddy and systemd on a VPS. No Docker. |

---

## Assumptions

1. **Egress is restricted.** No vision provider is a hard dependency — local OCR plus the rules
   engine produce a complete verdict with the reader switched off entirely.
2. **This is a standalone prototype.** No COLA integration, no e-filing, no shared authorisation
   boundary.
3. **Synthetic data only.** Generated images, fictional brands, no real trade dress, no PII.
4. **Provider choice is configuration, not architecture.** Swapping vision models is an
   environment change, not a refactor.
5. **Model pricing and rate limits are current as of the build date**, re-verified against
   provider documentation before any production cutover.
6. **There are no user accounts yet.** `web/src/lib/session.ts` is a mock session read by both
   the masthead and every determination, so replacing it is a single change.

---

## Deployment

The service runs on a VPS behind Caddy under a `/ttb-build` subpath. `deploy/deploy.sh` pulls,
rebuilds both sides, restarts the systemd unit and rolls back if the health endpoint does not
come up. Migrations apply at boot and are tracked in `schema_version`, so there is no separate
migration step to forget. `deploy/backup.sh` takes a nightly encrypted copy off the box on a
systemd timer, pruning both ends to 30 days.

---

## Known limitations and next steps

Two PRD §10 M7 exit criteria are still open, and neither blocks use: a **load pass at ten
concurrent reviewers** (the contention story is reasoned about rather than observed) and a
**restore rehearsal** by someone who did not build the system.

Real limitations, left alone deliberately rather than half-fixed:

| Limitation | What it costs |
| --- | --- |
| A batch commit is not atomic across claim and insert | A mid-commit failure leaves rows neither staged nor filed |
| Resetting the store while a job runs does not join the verification pool | Verifications in flight are silently discarded |
| Two reviewers deciding one record both pass the "already closed" check | The second decision wins; both append to the audit log |
| An imported CSV is not validated against the verdict and decision enums | An out-of-enum value imports cleanly, then breaks the record list |
| Job polling has no cancellation | Wasted requests, and a toast on a page already left |
| A new HTTP client is built per verification | Lost connection reuse across a batch — latency, not correctness |
| The per-IP rate limiter keeps a counter per address for the process lifetime | Memory grows with distinct clients |
| The warning is judged on the image filed (PRD §12 leaves back labels open) | A warning on the other side fails, possibly falsely |

Out of scope for v1 by decision (PRD §1): multi-tenancy · applicant-facing portal · TTB
integration and e-filing · artwork editing · PDF uploads · e-signature · user accounts with a
role hierarchy. The last unlocks the others; shared-token access stands in for it (PRD §8).
