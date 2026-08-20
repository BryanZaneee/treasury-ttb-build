# Label Verification Service

AI-assisted TTB-style COLA label verification. A reviewer files an application, a reader
extracts the same seven fields from the label specimen, and a **deterministic rules engine**
adjudicates the two field by field into `match` / `review` / `fail`. Every determination is
written to an auditable system of record.

The authoritative spec is [`design_handoff_label_verification/PRD.md`](design_handoff_label_verification/PRD.md).
Its §6.2 carries the approved design tokens — colours, type and copy are normative.

**All data in this deployment is synthetic.** The 25 label specimens are generated, the brands
are fictional, and no real applicant information exists anywhere in the system.

---

## Setup

### Prerequisites

| Need | Version | Notes |
| --- | --- | --- |
| Python | 3.12 or newer | required by `api/pyproject.toml` |
| [uv](https://docs.astral.sh/uv/) | current | the only Python package manager used here |
| Node | 22 | the version CI builds against |
| Tesseract | optional | only needed for `READER_PROVIDER=ocr`: `brew install tesseract` |

### 1. Configure

```bash
cp .env.example .env
```

Open `.env` and set `ACCESS_TOKEN`, `ADMIN_TOKEN`, and their `VITE_` copies to any non-empty
string for local use. If you want the real vision reader, also set `READER_API_KEY`; otherwise
set `READER_PROVIDER=fake` and skip the key entirely.

`.env` lives at the **repo root**, not inside `api/` or `web/`. Both sides read it: `api/config.py`
walks up to it and `web/vite.config.ts` sets `envDir: '..'`. There is only ever one copy.

### 2. Start the API

```bash
cd api
uv sync
uv run python seed.py                        # prints "seeded 25 records"
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

Open <http://localhost:5173>. The inbox opens with 25 unverified applications. Press
**Run AI verification on all** to work the whole queue, or open any record and verify it on its
own.

> **Running the demo with no spend:** set `READER_PROVIDER=fake` in `.env`. The fake reader
> replays `api/fixtures/expectations.json`, so every fixture reaches its documented verdict
> instantly, offline, and at zero cost. This is also the reader CI uses.

### Configuration reference

| Variable | Purpose |
| --- | --- |
| `READER_PROVIDER` | `fake`, `ocr` or `openai`. Which reader verification uses. |
| `READER_MODEL` | Vision model. `gpt-4.1-mini` in production. |
| `READER_API_KEY` | Key for the vision reader. `OPENAI_API_KEY` overrides it for that one provider. |
| `READER_TIMEOUT_S` | Per-call timeout before the service degrades to local OCR. |
| `DAILY_VISION_CALL_CAP` | Paid vision calls allowed per UTC day. Once breached, records finish with rules-only verdicts rather than failing. `0` disables it. |
| `ACCESS_TOKEN` / `ADMIN_TOKEN` | Shared bearer tokens. There are no user accounts (PRD §8). |
| `VITE_ACCESS_TOKEN` / `VITE_ADMIN_TOKEN` | The same two tokens, exposed to the browser bundle for local dev. |
| `AUTO_APPROVE_MATCHES` | Whether clean matches close themselves. Defaults to off (PRD §5.3). |
| `QA_SAMPLE_RATE` | Fraction of auto-close-eligible records sent to a human anyway. Default 0.05. |
| `DATA_DIR` | Where the SQLite store, images and snapshots live. |
| `PUBLIC_BASE_PATH` | Subpath the app is served under in production. Empty locally. |

**Never give the reader API key a `VITE_` prefix.** Anything prefixed `VITE_` is compiled into
the browser bundle and is therefore public (PRD §8).

---

## Approach

### Start from the stakeholders, not the stack

Label review today is manual double-entry: an agent reads the label, reads the application, and
compares seven fields by eye. It is slow, it is inconsistent between agents, and formatting noise
(title case, a unit written differently, an optional statement) is indistinguishable from
substantive error until a human has already spent the attention on it.

Two roles came out of that. The **compliance reviewer** works the inbox, files single
applications, runs batches and issues determinations. The **compliance lead** exports the store,
resets fixtures for training and audits closed records, which is what sits behind the admin
token.

### Turn the wants into user stories with acceptance criteria

Thirteen stories, S1 through S13, each with a single testable acceptance line. The full table is
PRD §2. Three examples of the shape:

- **S3, batch upload.** Application CSV plus a folder of label images, paired on filename.
  *Acceptance:* the staged preview reports all five pairing buckets, and commit files every
  non-ambiguous row.
- **S8, accepting a flagged record.** *Acceptance:* the confirmation names each disagreeing
  field; cancel changes nothing; confirm stores the reviewer name, the timestamp and an override
  flag.
- **S11, CSV interchange.** *Acceptance:* seed, export, wipe, import, export produces
  byte-identical output.

Writing acceptance criteria first is what made the work verifiable. Each one maps to a test.

### Draw the scope line before writing code

Ruled out for v1, deliberately: multi-tenancy, an applicant-facing portal, TTB system
integration and e-filing, artwork editing, PDF specimens, e-signature, and user accounts with a
role hierarchy. Accounts were replaced by shared-token access (PRD §8) because a single-tenant
internal tool for 1 to 10 reviewers does not need an identity system, and building one would
have consumed the time the rules engine needed.

### Write the PRD, then treat it as the source of truth

`design_handoff_label_verification/PRD.md` fixes the domain model, the persistence schema, the
API surface, the routes and design tokens, the fixture set, the non-functional requirements, and
an M0 to M7 roadmap where every milestone carries its own exit criteria. Behaviour is not
invented at the keyboard: if the PRD settles a question, the code follows it and the comment
cites the section.

### Execute in milestone order and let the gates hold

The rules engine had to be green against all 25 fixture expectations before any reader code was
written. That ordering is why the reader is swappable: the verdict semantics were already
pinned down and testable without a model in the loop. The 20 acceptance tests in PRD §11 map
onto the pytest suite in `api/tests/`.

### One rule holds the whole design together

**Rules own the verdict.** A reader supplies observed values, and it may *downgrade* a verdict
or attach a note, but it may never improve one (PRD §3.2). `fail` to `review`, `fail` to `match`
and `review` to `match` are rejected and logged. That single constraint is what prevents a model
from talking a bad label into an approval, and it is what makes the reader safe to treat as
configuration.

---

## Tools used

**Development.** VS Code as the editor, with Claude Code and Codex as the AI pair for
implementation. Both were driven from the PRD rather than from ad-hoc prompts, so generated code
always had a written spec to be checked against, and a fixture set that told us immediately
whether it was right. The three things that made the AI-assisted workflow safe here were the
same three that make any of it safe: the semantics were fixed in writing first, the 25 fixtures
gave a pass or fail oracle rather than an opinion, and CI (ruff, mypy in strict mode, pytest,
vitest, production build) ran on every push.

**Runtime stack.**

| Layer | Choice |
| --- | --- |
| Frontend | React 19, TypeScript strict, Vite, React Router, TanStack Query |
| Backend | Python 3.12, FastAPI, Pydantic |
| Store | SQLite via the stdlib `sqlite3` module, WAL mode, no ORM, derived CSV mirror |
| Reader | `gpt-4.1-mini` vision, with local Tesseract OCR always available as the fallback |
| Deploy | Caddy and systemd on a VPS. No Docker. |

---

## Assumptions

1. **Egress is restricted.** The IT interview described a firewall that broke a previous
   vendor's ML endpoints, so no vision provider is a hard dependency. Local OCR plus the rules
   engine produce a complete verdict with the reader switched off entirely, and the engine
   string always names what actually read the label.
2. **This is a standalone prototype.** No COLA integration, no e-filing, and no authorisation
   boundary shared with an existing system.
3. **Synthetic data only.** All 25 specimens are generated, the brands are fictional, no real
   trade dress is reproduced, and no applicant PII exists in the deployment.
4. **Provider choice is a configuration, not an architecture.** Swapping vision models is an
   environment change, not a refactor.
5. **Model pricing and rate limits are current as of the build date** and are re-verified
   against provider documentation before any production cutover.
6. **There are no user accounts yet.** Determinations are attributed to the signed-in reviewer,
   and `web/src/lib/session.ts` is a mock session standing in until real authentication exists.
   It is one definition, read by both the masthead and every determination, so replacing it is a
   single change.

---

## How it works

### The readers

| Reader | Speed | Cost | What it is |
| --- | --- | --- | --- |
| `openai` | 2 to 4 seconds | metered | `gpt-4.1-mini` vision. The production reader. |
| `ocr` | about 600 ms | none | Local Tesseract, two page-segmentation passes. No network. Also the automatic fallback. |
| `fake` | instant | none | Replays the fixture ground truth. The CI reader (PRD §5.4). |

The reader never sees the application values, so nothing written on a label can steer the
adjudication (PRD §3.3).

When the vision reader is unavailable, verification falls back to local OCR rather than failing:
the service never blocks on a reader. Because OCR reads blurred, angled and low-contrast
captures markedly less reliably, the reviewer is told rather than left to guess. A toast is
raised on the determination, the record carries a *Read by local OCR* chip, and the engine
string names what actually read the label.

### Repository map

| Path | What is in it |
| --- | --- |
| `api/` | Flat modules, no package prefix: `db.py`, `adjudicate.py`, `csv_io.py`, `batching.py`, `uploads.py`, `models.py` |
| `api/routers/` | The HTTP surface: records, batches, jobs, store, specimens, all mounted under `/api` |
| `api/readers/` | Reader implementations plus image prep and versioned prompts |
| `api/fixtures/` | The 25 specimens, `applications.csv` and `expectations.json` |
| `web/src/routes/` | Inbox, CheckLabel, CheckBatch, RecordDetail, Export |
| `data/` | Runtime store: SQLite database, uploaded images, snapshots, CSV mirror. Gitignored. |
| `deploy/` | Caddyfile, systemd unit and the deploy script for the VPS |
| `design_handoff_label_verification/` | The normative PRD and the fixture manifest |

---

## Quality gates

These are exactly what CI runs on every push:

```bash
cd api && uv run ruff check . && uv run mypy . && uv run pytest -q
cd web && npm run lint && npm run test && npm run build
```

The behavioural coverage lives on the Python side: `test_adjudicate` for the rules engine,
`test_api` for the route contracts, `test_batching` for filename pairing, `test_csv_io` for the
round trip, `test_db` for the store, `test_readers` for reader behaviour and fallback, and
`test_uploads` for specimen validation. The web side is a smoke test plus a type-checked
production build, so the frontend is covered by types and by the API contract rather than by a
large component suite.

Run a single test with `uv run pytest tests/test_db.py::test_round_trip -q` or
`npx vitest run -t 'name of test'`.

---

## Deployment

The service runs on a VPS behind Caddy, served under a `/ttb-build` subpath.
`deploy/deploy.sh` pulls the new commit, rebuilds both sides, restarts the systemd unit and
rolls back to the previous commit if the health endpoint does not come up. `PUBLIC_BASE_PATH` is
defined once in the root `.env` and threads from there into the Vite `base`, the Router
`basename` and the front-host proxy path, so the subpath is never written down twice.
