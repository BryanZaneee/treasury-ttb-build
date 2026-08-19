# Label Verification Service

AI-assisted TTB-style COLA label verification. A reviewer files an application, a reader
extracts the same seven fields from the label specimen, and a **deterministic rules engine**
adjudicates the two field by field into `match` / `review` / `fail`. Every determination is
written to an auditable system of record.

The authoritative spec is `design_handoff_label_verification/PRD.md`. The approved visual
design is `Label Verification.dc.html` in the same folder; its colours, type and copy are
normative.

**All data in this deployment is synthetic.** The 25 label specimens are generated, the brands
are fictional, and no real applicant information exists anywhere in the system.

---

## Running it locally

Two processes. The API on :8000, the frontend on :5173 with a dev proxy to it.

```bash
# 1. Configure — copy the template and fill in the tokens you want to use.
cp .env.example .env          # first time only; .env is gitignored

# 2. API
cd api
uv sync
uv run python -c "import db, seed; db.init_db(); print(seed.seed_store())"   # 25 fixtures
uv run uvicorn main:app --port 8000

# 3. Frontend, in a second terminal
cd web
npm ci --legacy-peer-deps
npm run dev                   # http://localhost:5173
```

Open <http://localhost:5173>. The inbox starts with 25 unverified applications; press
**Run AI verification on all** to work the queue.

### Configuration

`.env` at the repo root is read by both the API (`api/config.py`) and Vite
(`vite.config.ts` sets `envDir: '..'`). The variables that matter for a local run:

| Variable | Purpose |
| --- | --- |
| `READER_PROVIDER` | `fake` \| `ocr` \| `openai` \| `gemini` — which reader verification uses |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | Per-provider keys. The reader bench races several providers at once, so one shared key cannot serve them all. |
| `ACCESS_TOKEN` / `ADMIN_TOKEN` | Shared bearer tokens. There are no user accounts (PRD §8). |
| `VITE_ACCESS_TOKEN` / `VITE_ADMIN_TOKEN` | The same tokens, exposed to the browser bundle for local dev. **Never give the reader API key a `VITE_` prefix** — that would ship it to the client. |

`READER_PROVIDER=fake` is the default and the right setting for a demo: it replays
`fixtures/expectations.json`, so every fixture produces its documented verdict instantly and
with no spend. `ocr` and the two vision providers read the actual image.

Local OCR needs Tesseract: `brew install tesseract`.

---

## The readers

| Reader | Speed | Cost | What it is |
| --- | --- | --- | --- |
| `fake` | ~0 ms | none | Replays the fixture ground truth. The CI reader (PRD §5.4). |
| `ocr` | ~600 ms | none | Local Tesseract, two page-segmentation passes. No network. |
| `openai` | ~2–4 s | metered | OpenAI vision via the Chat Completions API. |
| `gemini` | ~2–5 s | metered | Gemini via its OpenAI-compatible endpoint — same client, different base URL. |

Rules own the verdict. A reader supplies observed values and may **downgrade** a verdict or
attach a note; it may never improve one (PRD §3.2). When the configured reader is unreachable,
verification falls back to local OCR and the engine string names the cause — the service never
blocks on a reader.

### Reader bench

The **Reader bench** tab (first in the nav) races any combination of readers against one
specimen and reports per-stage timings, token counts, the verdict each produced, and how each
scored against the fixture ground truth. It is the interactive form of the PRD §5.4 bake-off.

It is a development affordance: it calls a paid provider on every run, and it — along with
`api/routers/dev.py` — should be removed before the M6 cutover.

---

## Quality gates

```bash
cd api  && uv run ruff check . && uv run mypy . && uv run pytest -q
cd web  && npx oxlint && npm run test && npm run build
```
