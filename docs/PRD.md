# Label Verification Service — PRD & Build Plan

**v1.1 — 19 Aug 2026.** System of record moved from CSV to SQLite with a derived CSV mirror.
Reader layer generalised to two interchangeable vision providers plus always-on local OCR.
API surface reduced from 19 endpoints to 10. Authentication replaced with shared-token access
and spend controls. Performance targets reconciled with the 5-second stakeholder requirement.
Batch pairing, prompt-injection posture, and AI governance specified.

AI-assisted TTB-style COLA label verification. A reviewer files an application, a vision
model reads the label specimen, the two are adjudicated field by field, and every
determination is written to an auditable system of record.

- **Stack:** React 19 + TypeScript (Vite) · Python 3.12 + FastAPI · SQLite system of record with CSV mirror · Docker Compose on a Tailscale-connected VPS
- **Design source:** `Label Verification.dc.html` — high-fidelity, approved. Its colors, type and copy are normative.
- **Target:** single-tenant internal tool, 1–10 concurrent reviewers, 2 vCPU / 4 GB VPS, reached at `bryanzane.com/ttb-build`
- **Timeline:** milestones M0–M7; production cutover at M6, hardening at M7

---

## 1. Problem and objective

Label review is manual double-entry: an agent reads the label, reads the application, and
compares seven fields by eye. Slow, inconsistent between agents, and formatting noise
(title case, unit expression, an optional statement) is indistinguishable from substantive
error until a human has already spent the attention.

The service separates those classes automatically. A vision model extracts the same seven
fields from the specimen; a deterministic rules engine compares them to the application and
assigns each field **match**, **review** (same content, different presentation) or **fail**
(different content, missing required value, illegible). Field verdicts roll up to a record
verdict. Clean matches can close themselves; everything else lands in a review inbox with the
disagreement pre-explained in language an agent can paste into a determination.

### Success measures
- ≥ 60% of clean captures eligible for auto-close with no human touch (11 of 25 fixtures are clean references).
- Zero false auto-closes across the fixture set — no defect fixture may reach *match*, for any reader.
- Median time to a determination on a review-state record under 45 s.
- Verification p95 under 5 s from the reviewer pressing Verify (§8).
- A batch of 25 applications + images verifies end to end in under 3 min; 300 in under 10.

### Out of scope for v1
Multi-tenancy, applicant-facing portal, TTB system integration/e-filing, artwork editing,
PDF specimens, e-signature, user accounts and role hierarchies (replaced by shared-token
access, §8).

---

## 2. Users and user stories

**Compliance reviewer** (primary) works the inbox, files single applications, runs batches,
issues determinations. **Compliance lead** (secondary) exports the store, resets fixtures for
training, audits closed records — the operations gated behind the admin token.

| ID | Story | Acceptance |
| --- | --- | --- |
| S1 | Check one label: upload a specimen, type the application fields, verify. | Record created, extraction starts on upload, verdict returned, detail view opens on the field comparison. |
| S2 | Prefill the single-label form from a named sample (matching, casing difference, missing warning, title-case warning, reworded warning, ABV mismatch, unit mismatch, illegible field). | Every sample selectable and reproduces its documented verdict. |
| S3 | Batch upload: application CSV + folder of label images, paired on `filename`. | Staged preview reports all five pairing buckets (§5.5); commit files every non-ambiguous row. |
| S4 | Load the bundled sample batch in one click. | 24 fixture applications stage with images resolved. |
| S5 | Inbox filtered by needs attention / awaiting AI / review / fail / closed, with search over ID, applicant, brand, filename. | Filter counts match the store; search is case- and punctuation-insensitive. |
| S6 | Open an unverified application, fill missing fields, press Verify. | Row shows busy state, resolves to pass/review/fail without page reload; field results stream as they resolve. |
| S7 | Verify every pending record in one action. | Progress per record; one failure does not abort the rest; job summary reports estimated spend. |
| S8 | Accept a flagged record after explicit confirmation naming each disagreeing field. | Confirmation lists offending fields; acceptance stores reviewer name, timestamp, override flag. |
| S9 | Return a record to the applicant with an editable reason. | Reason persists and appears in the export; the record is not reopenable (§12). |
| S10 | Minimise the detail panel and return to it later on this device. | Collapsed/expanded state and open record survive reload. |
| S11 | Export the store as CSV; import a CSV back; download a blank template. | Round-trip lossless: seed → export → wipe → import → export is byte-identical. |
| S12 | Reset the store to the bundled example set. | Reset requires the admin token, is confirmed in the UI, snapshots the prior store, restores 24 fixtures. |
| S13 | Read the store as a normal web page — never raw CSV. | CSV appears only as a file download; every on-screen view is rendered UI. |

---

## 3. Domain model

### 3.1 Verified fields

| Key | Label | Required | Normalisation before compare |
| --- | --- | --- | --- |
| `brand` | Brand name | Yes | Case-fold, collapse whitespace, strip punctuation and diacritics |
| `classType` | Class / type | Yes | Case-fold, collapse whitespace, drop trailing parenthetical designations |
| `abv` | Alcohol content | Yes | Parse percent by volume to float; proof statement informational only |
| `net` | Net contents | Yes | Convert mL / cl / L / FL OZ to millilitres; tolerance ±1 mL |
| `producer` | Bottler / producer | Conditional | Case-fold; state abbreviation ≡ full name |
| `origin` | Country of origin | Imports only | Case-fold; "Product of X" ≡ "X" |
| `warning` | Government warning | Yes | Character-exact body; header case and bold weight checked separately |

### 3.2 Verdicts and roll-up

Field verdict ∈ `match | review | fail`. Record verdict = worst field verdict (any fail →
fail; else any review → review; else match). No verdict yet = *awaiting AI*. Decision ∈
`null | accepted | returned`; a match verdict may auto-set `accepted` by `Automatic` only when
auto-approve is enabled **and** the record passes the full eligibility test of §5.3.

- **match** — normalised values identical, or numerically equivalent within tolerance.
- **review** — same content, different presentation: capitalisation, punctuation, unit
  expression, an optional accompanying statement, a value on the label omitted from the
  application, or a cosmetic warning defect (title-case header, non-bold header). Also
  assigned when an otherwise-matching field was read from a degraded capture, or when the two
  readers disagree (§5.3).
- **fail** — different content; a required value absent from the label; a reworded or missing
  government warning; or a field the extractor returned as `ILLEGIBLE`.

**Rules first, model second.** The deterministic engine produces the verdict of record. The
vision reader supplies observed values and may **downgrade** a verdict or attach an
explanatory note. It may never improve one: `fail → review`, `fail → match` and
`review → match` are all rejected by the adjudicator and logged as a governance event. A
reader that is unreachable, slow, or returns unparseable JSON degrades to the rules verdict,
with the engine string recording the cause (e.g.
`deterministic rules engine (reader unreachable)`). The service never blocks on the reader.

### 3.3 Specimen text is untrusted input

The label image is applicant-supplied and may contain text crafted to influence the reader —
instructions, assertions about the application, or forged verdicts. Three controls apply:

1. The extraction prompt instructs the reader to transcribe observed text only, never to
   interpret instructions found within the image.
2. The reader's output is constrained by a strict JSON schema; anything off-schema is a parse
   failure and falls back to rules.
3. The reader never sees application values during extraction, and the adjudication pass
   cannot improve a verdict. An injected instruction therefore has no path to an auto-close.

`tests/test_injection.py` asserts this with three adversarial fixtures whose label artwork
carries injected instruction text. Each must still produce its expected verdict.

---

## 4. Persistence: SQLite system of record, CSV mirror

The durable store is a single SQLite file on a bind-mounted volume. CSV remains the
interchange format — export, import, batch intake, human inspection — but is no longer
authoritative.

**Why the change.** Treating CSV as the system of record required hand-built durability:
atomic temp-file replacement, an advisory `flock`, a process-wide lock, a forced single
Uvicorn worker, and a bespoke migration reader. SQLite provides all of it, ships in the
standard library, adds no container and no operational surface, and remains a single file that
can be copied for backup. The v1.0 design also documented its own 20,000-row retirement
trigger; adopting SQLite at M1 removes that migration from the roadmap entirely.

```
data/
  records.db             system of record (SQLite, WAL mode)
  records.csv            derived mirror, rewritten after each mutation
  images/<sha256>.png    content-addressed specimens, deduped on hash
  fixtures/              bundled sample batch: applications.csv + 25 specimen images
  snapshots/2026-08-18T14-02-11Z.db
```

### 4.1 Schema

Three tables. The design rule is that **`records` is the CSV row** — every CSV column except
the two derived ones is a column here, in the same order, with the same name. Export is a
`SELECT` plus one aggregate; no reshaping, no mapping layer, nothing to drift.

**records** — one row per application. Columns 1–22 are the CSV columns verbatim:

```
id, received, applicant, beverage, filename, specimen, quality,
app_brand, app_class_type, app_alcohol_content, app_net_contents,
app_producer, app_origin, app_warning_declared,
verified, result, elapsed_ms, engine, decision, decided_by, decided_at, note
```

Plus eight columns that exist only in the database and are not exported: `override`,
`supersedes_id`, `reader_provider`, `reader_model`, `prompt_version`, `prep_ms`, `reader_ms`,
`rules_ms`. The timing columns are what make per-record latency comparable across readers in
production, not just in the bench (§5.4).

The two CSV columns absent here — `field_results` and `field_notes` — are packed at export
time from the second table.

**field_results** — one row per verified field per record. Replaces v1.0's packed
`key:verdict|key:verdict` cell, which was a serialization format nested inside a
serialization format.

```
record_id, field_key, app_value, label_value, verdict, note,
reader_value, ocr_value, agreed, confidence
```

Unique on (`record_id`, `field_key`). `reader_value` and `ocr_value` retain what each reader
independently saw, and `agreed` is the auto-close gate of §5.3 — keeping both is what makes
the three-way comparison possible after the fact rather than only at bench time.

**audit** — append-only event log: `seq`, `ts`, `record_id`, `event`, `payload_json`. Every
determination, override, import, and reset writes one row. This is what satisfies §12's
requirement that superseded verdicts be retained: re-verification and re-decision append
rather than overwrite, and `records` simply holds the current state.

No hash chaining. It was in an earlier draft and has been cut: with no user identity in the
system, a tamper-evident chain proves only that the file was not edited out of band, which is
a marginal property bought with a verification script, a chain-integrity test, and an
explanation in the README. Append-only history is the part that earns its keep.

### 4.2 CSV mirror

After every mutation, a debounced writer (at most once per second, and always within two
seconds of the last write) regenerates `data/records.csv` from the database. The mirror is
**derived and never read back** — a stale or partial mirror is a cosmetic defect, not data
loss, which is precisely why no locking is required around it.

The mirror carries the v1.0 column set verbatim so exported files remain interchangeable with
the approved prototype, with `field_results` re-packed into the `key:verdict|key:verdict` form
and notes emitted in a parallel `field_notes` column:

```
id, received, applicant, beverage, filename, specimen, quality,
app_brand, app_class_type, app_alcohol_content, app_net_contents,
app_producer, app_origin, app_warning_declared,
verified, result, field_results, field_notes, elapsed_ms, engine,
decision, decided_by, decided_at, note
```

### 4.3 CSV interchange

`csv_io.py` holds exactly two functions, both unit-tested independently of the database:

- `to_csv(rows) -> bytes` — fixed column order, RFC 4180 quoting, fixed null representation,
  deterministic output. Cells beginning `= + - @` are prefixed with an apostrophe against
  spreadsheet formula injection.
- `from_csv(bytes) -> rows` — tolerates CRLF, a BOM, and reordered columns; preserves `id` so
  merge-import is idempotent; rejects a file missing `app_brand` with a field-level error the
  UI can display.

Round-trip test: seed → export → wipe → import → export → assert identical bytes. Satisfies
S11 regardless of storage.

**Batch intake CSV** accepts the shorter applicant header:
`filename, brand_name, class_type, alcohol_content, net_contents, producer, country_of_origin, government_warning, applicant`.

### 4.4 Snapshots and migrations

Snapshots are file copies (`sqlite3 .backup`) written before every import and reset. Schema
changes are versioned SQL in `migrations/`, applied at boot inside a transaction, with the
applied version recorded in a `schema_version` table.

---

## 5. Backend (Python)

FastAPI on Uvicorn, Python 3.12, Pydantic v2, `uv` for dependencies, Ruff + mypy strict,
pytest. WAL-mode SQLite permits concurrent readers, so the single-worker constraint from v1.0
is lifted; two workers are the default.

One package per concern, and a package only where there is more than one file. Single-module
packages have been flattened; `readers/` stays a package because it holds four interchangeable
implementations plus the protocol. Module names are nouns matching the concept they own, and
each appears exactly once.

```
api/
  main.py             app factory, CORS, static mounts, health
  config.py           env parsing, per-provider effort clamp, spend accounting
  models.py           Pydantic: Application, LabelReading, FieldResult, Record
  db.py               connection, schema, migrations, snapshot, reset, audit append
  csv_io.py           to_csv / from_csv / mirror writer — the only CSV code
  adjudicate.py       normalisation, per-field comparison, roll-up, notes
  batching.py         filename pairing, staged-preview construction
  jobs.py             bounded worker pool, per-record status, SSE progress
  seed.py             build the 24-record example store from fixtures/
  readers/
    __init__.py       Reader protocol, registry, get_reader(config)
    vision.py         OpenAI-compatible client — serves both OpenAI and Gemini
    ocr.py            local Tesseract reader
    fake.py           replays fixture readings — used in CI
    prompts.py        extraction prompts, versioned
  routers/
    records.py  batches.py  jobs.py  store.py
migrations/
  001_initial.sql  002_….sql
tests/                one test module per api module it covers
  test_adjudicate.py  one case per fixture defect, verdict asserted
  test_readers.py     schema conformance, retry, degradation, effort clamp
  test_injection.py   adversarial specimen fixtures
  test_db.py          round-trip, migration, concurrent write
  test_csv_io.py      byte-identical round trip, formula-injection prefixing
  test_batching.py    filename pairing across all five buckets
  test_api.py         contract tests against the OpenAPI schema
scripts/
  bench.py            three-way reader bake-off (§5.4)
```

### 5.1 API surface

Ten endpoints. Static assets — specimen images, the CSV mirror, the blank template, and the
named-sample catalogue — are served directly by Caddy from the data volume rather than through
the application.

| Endpoint | Behaviour |
| --- | --- |
| `GET /api/records` | Filter (`attention\|pending\|review\|fail\|closed`), query, cursor page; returns rows plus filter counts. |
| `POST /api/records` | Create one application: multipart (image + JSON), or `specimen_key` for a bundled fixture image. Extraction begins immediately (§5.2). |
| `GET /api/records/{id}` | Full record: application, reading, field results, notes, engine, timings, decision history. |
| `PATCH /api/records/{id}` | Edit application fields, or issue a decision. Editing invalidates any prior verdict. **The override rule is enforced here**: `decision: accepted` on a non-`match` verdict is rejected unless `override: true`, and the check has its own unit test — it must not be lost inside a generic field-merge loop. |
| `POST /api/records/{id}/verify` | Run adjudication. Idempotent per (record, image hash, prompt version, provider, model, effort) via cache. |
| `POST /api/batches/stage` | Multipart CSV + images. Parses, pairs images by filename (§5.5), returns a staged preview with per-row errors. Nothing is written. |
| `POST /api/jobs` | `{scope: "pending" \| "batch", batch_id?, verify_now?}`. Commits a staged batch and/or enqueues verification. Returns a job id. |
| `GET /api/jobs/{id}/events` | Server-sent events: `progress`, `record`, `done`, `error`. |
| `POST /api/fixtures` | `{mode: "stage" \| "reset"}`. Stage the sample batch, or snapshot and reseed the 24-record example store. Admin token required for `reset`. |
| `POST /api/store/import` | Replace or merge by `id`, after snapshotting. Admin token required. |
| `GET /api/health` | Store readable, images writable, reader reachable, prompt version, provider, model, spend today. |

Served by Caddy, not the API: `/ttb-build/images/{hash}`, `/ttb-build/export/records.csv`,
`/ttb-build/export/template.csv`, `/ttb-build/specimens.json`.

### 5.2 Reader layer

**Providers.** Two vision models are supported and interchangeable by configuration. Both are
reached through a single `AsyncOpenAI` client, since Gemini exposes an OpenAI-compatible
endpoint — only the API key, base URL, and model string differ.

| | OpenAI | Google |
| --- | --- | --- |
| Model string | `gpt-5.6-luna` | `gemini-3.7-flash` |
| Base URL | default | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Image input | `image_url` with `data:image/jpeg;base64,…` | identical |
| Effort parameter | `reasoning_effort`: `none`, `low`, `medium` (default), `high`, `xhigh`, `max` | `reasoning_effort` maps to `thinking_level`: `low`, `medium`, `high` |
| Structured output | supported | supported |
| Context / output | 1,050,000 / 128,000 | 1,048,576 / 65,536 |
| Published price | $0.20/M in, $0.02/M cached in, $1.20/M out | see current Gemini pricing page |

**Two provider-specific constraints, enforced in the adapter:**

1. **Effort clamp.** Gemini 3.7 Flash rejects `minimal` with an error, and reasoning cannot be
   disabled on Gemini 3 models. The adapter clamps configured effort to a per-provider floor:
   `low` for Gemini, `none` for OpenAI. Asserted in `test_readers.py`.
2. **Service tier.** Gemini matches OpenAI's `service_tier` parameter in name and logic,
   defaulting to `standard`. It is exposed as configuration so priority inference can be
   measured against the latency target rather than assumed.

**Configuration.**

```
READER_PROVIDER=openai|gemini|ocr|fake
READER_MODEL=gpt-5.6-luna
READER_BASE_URL=                    # empty = OpenAI default
READER_API_KEY=
READER_EFFORT=low                   # clamped per provider
READER_SERVICE_TIER=standard        # standard | flex | priority
READER_TIMEOUT_S=25
READER_CONCURRENCY=10
DAILY_SPEND_CAP_USD=50
```

**Image preparation.** Pillow applies EXIF rotation, downscales the longest edge to 1024 px,
encodes JPEG q85, and computes a perceptual sharpness score used as the capture-quality prior.
Where the sharpness prior is low or the warning region is small, a second pass runs on a
bottom crop of the label, since warning text is the smallest type on most specimens and the
field most sensitive to resolution. The 1024 px default is validated against the fixture set
by `scripts/bench.py` before it is fixed; if per-field accuracy drops, the value moves back to
1600 and the latency budget absorbs it.

**Extraction begins on upload, not on Verify.** The reader never sees application values, so
extraction has no dependency on the form and starts the moment the specimen lands. By the time
the reviewer presses Verify, the reading is cached and adjudication is a rules-engine call.
This is what makes the 5-second target achievable rather than a hope about model latency.

**Guards.** Two retries with backoff on transport or schema failure; a 25-second per-image
budget; results cached by `sha256(image) + prompt_version + provider + model + effort` — the
provider and model components prevent a stale reading being served after a configuration
change; a strict JSON schema with one object per field carrying `value`, `confidence`, and a
literal `ILLEGIBLE` sentinel, plus the warning composite (present, body verbatim, header case,
header bold) and a capture-quality classification drawn from the fixture vocabulary (`normal`,
`blurry`, `heavyBlur`, `glare`, `pixelated`, `angled`, `dark`, `damaged`, `cropped`).

### 5.3 Dual reader and auto-close eligibility

Local OCR (Tesseract) runs on **every** specimen, always, at roughly 200 ms and no marginal
cost. It serves three purposes:

1. **Independent second reader.** Agreement between OCR and the vision model on a normalised
   field value is the auto-close gate. This is a materially stronger signal than a low-tier
   model's self-reported confidence, which is poorly calibrated.
2. **Fallback reader.** When the vision provider is unreachable — the firewall scenario raised
   in the IT interview — OCR supplies observed values and the engine string names it.
3. **Illegibility prior.** OCR confidence feeds the capture-quality assessment alongside the
   sharpness score.

**Auto-close eligibility.** A record may auto-close only if all of the following hold: every
field verdict is `match`; the vision reader and OCR agree on every field after normalisation;
capture quality is `normal`; and no field was read by a single reader alone. Anything else
routes to the review inbox. An OCR-only reading never auto-closes.

OCR is not a batch-size fallback. Reader selection never varies with queue depth — two records
must not receive different verdict quality for reasons unrelated to their content, which would
be indefensible on audit.

**Runtime timings.** Every verification records `prep_ms`, `reader_ms`, `rules_ms`, and
`elapsed_ms` on the record, measured with `time.perf_counter_ns()` and rounded to whole
milliseconds at the boundary. Because OCR runs on every specimen alongside the vision reader,
production accumulates paired timings continuously — the comparison does not stop when the
bench script finishes.

Provider selection is a measurement, not an assertion. The measurement is specified in §5.4.

### 5.4 Three-way reader benchmark

`scripts/bench.py` runs the full fixture set through all three readers and produces the
evidence for choosing one. It is the artifact that turns "we picked Luna" into "we measured
Luna, Gemini, and OCR, and here is the table."

```
python scripts/bench.py --readers openai,gemini,ocr --runs 3 --concurrency 1
```

**Method.** Every reader sees the identical prepared image, so differences are attributable to
the reader and not to preprocessing. The extraction cache is bypassed. Each fixture runs
`--runs` times (default 3) and the median is reported, since a single sample on a network call
is noise. `--concurrency 1` is the default for latency measurement — concurrent runs measure
throughput, not latency, and the two are reported separately. Ground truth is
`fixtures/expectations.json`.

**Timing instrumentation.** Four stages, `perf_counter_ns()` at each boundary, reported in ms:

| Stage | Measures |
| --- | --- |
| `prep_ms` | EXIF rotation, downscale, JPEG encode, sharpness score |
| `reader_ms` | Request dispatch to parsed response — the only stage that differs between readers |
| `rules_ms` | Normalisation, comparison, roll-up, note generation |
| `total_ms` | Upload accepted to verdict written |

`reader_ms` is additionally split into `ttfb_ms` and `transfer_ms` for the two API readers,
because a provider that is slow to start and a provider that is slow to stream are different
problems with different fixes.

**Outputs.** Two files, both committed:

- `data/benchmark.csv` — one row per (fixture, reader, run): `fixture_id, reader, run,
  prep_ms, ttfb_ms, reader_ms, rules_ms, total_ms, verdict, expected_verdict, fields_correct,
  fields_total, illegible_detected, input_tokens, output_tokens, cost_usd, error`. Raw, so any
  claim in the summary can be recomputed.
- `docs/benchmark.md` — the rendered summary, reproduced in the README.

**Summary tables.** Four, in this order:

*Speed* — per reader: p50, p95, and max `total_ms`; median `reader_ms`; median `ttfb_ms`;
timeout and error counts. The p95 column is checked directly against the 5-second requirement
in §8.

*Accuracy* — per reader: per-field correctness against ground truth for all seven fields as a
matrix (reader × field), overall field accuracy, record-verdict accuracy, **false auto-close
count** (a defect fixture reaching `match` — this must be zero for any reader to be eligible),
false-rejection count, and illegible-detection precision and recall.

*Agreement* — the pairwise matrix across all three readers: openai↔gemini, openai↔ocr,
gemini↔ocr, per field. This is the table that justifies the §5.3 auto-close gate. Low OCR
agreement on `brand` and high agreement on `warning` is the expected shape — stylised brand
type defeats OCR while the warning statement is plain high-contrast sans-serif — and if the
measured matrix contradicts that, the gate design is revisited rather than the measurement
explained away.

*Cost* — per reader: median input and output tokens, cost per label, cost per 100 labels,
extrapolated cost for a 300-label peak-season batch.

**Exit criteria.** M3 does not close until `docs/benchmark.md` exists, every reader shows zero
false auto-closes, and at least one configuration meets the p95 target of §8. The chosen
production default is named in the README with a one-paragraph rationale citing the table.
`tests/test_readers.py` runs the same harness against the `fake` reader with two fixtures, so
the benchmark code path is covered in CI without network access or spend.

### 5.5 Batch filename pairing

Applications are paired to specimens on the CSV `filename` column against uploaded image
basenames, in three passes:

1. **Exact** basename match.
2. **Normalised** — case-fold, drop extension, collapse `[\s_-]+` to a single `-`, strip a
   leading `./`. Pairs `Old_Tom_750.JPG` with `old-tom-750.jpg`.
3. **Extension-agnostic** — same stem, any allowed extension.

Staging returns five buckets, and ambiguity is always an error rather than a guess:

| Bucket | Meaning |
| --- | --- |
| `matched` | Exactly one image via pass 1 or 2. |
| `matched_fuzzy` | Paired via pass 3; flagged in the preview for visual confirmation before commit. |
| `missing_image` | No image. Row files and is editable, but is not verifiable. |
| `ambiguous` | Two or more images normalise to the same stem. Row errors; all candidate filenames are shown. |
| `unused_images` | Uploaded images no CSV row claims. Listed in the preview summary so nothing vanishes silently. |

Commit is blocked while any row is `ambiguous`. `missing_image` rows do not block: they file,
per acceptance test 9.

---

## 6. Frontend (React + TypeScript)

Vite + React 19 + TS strict, React Router, TanStack Query for server state, Zod for response
parsing, and an API client generated from the FastAPI OpenAPI schema (`openapi-typescript`) so
types cannot drift. Styling: CSS modules with the token set below — no component framework; the
prototype's markup translates directly. Vitest + Testing Library for units, Playwright for the
flows in §11. The app is served under `PUBLIC_BASE_PATH` (§9), which threads into Vite `base`
and the Router `basename`.

### 6.1 Screens (from the approved prototype)

| Route | Contents |
| --- | --- |
| `/inbox` | Review inbox. Notification strip ("n applications need your attention"), five filter tabs with live counts, search, verify-all, queue table with pill status, per-row expand showing the field comparison, per-row Verify / Open. Empty and error states per filter. |
| `/check` | Check one label. Left: specimen dropzone with preview and quality badge, or named-sample picker — extraction starts on drop. Right: the seven application fields. Verify runs adjudication and routes to the detail view. |
| `/batch` | Check a batch. CSV dropzone, image multi-drop, template download, load-sample-batch, staged table showing all five pairing buckets with row errors, verify-now toggle, commit with per-record progress and estimated spend. |
| `/records/:id` | Determination view. Specimen viewer (zoom, quality treatment noted) beside the three-column comparison — application says / label shows / result — one row per field with the agent-ready note and both readers' values, then engine, per-stage timings and the decision bar (Accept, Return, minimise). Minimised state and open record persist in `localStorage`. |
| `/store` | Record store, rendered as a normal table — never raw CSV. Export (the served mirror), import, blank template, reset-to-example with confirmation, snapshot list. |

### 6.2 Design tokens (normative, from the prototype)

| Token | Value | Use |
| --- | --- | --- |
| `--navy` | `#10283d` | Masthead, table headers, primary buttons |
| `--gold` | `#b8912f` | 3px masthead rule, section rules, review dot |
| `--desk` | `#eef1f5` | App background |
| `--ink` / `--ink-2` | `#10151c` / `#3c4855` | Body text, secondary text |
| `--rule` | `#d5dde5` | Hairlines, card borders |
| pill / match | `#e3f2e6` · `#1e5c2e` · `#b7dcc0` | bg · fg · border (dot `#2f7a45`) |
| pill / review | `#fdf0d5` · `#6b4a05` · `#e6cf90` | bg · fg · border (dot `#b8912f`) |
| pill / fail | `#fbe6e4` · `#8a1f16` · `#e8b6ae` | bg · fg · border (dot `#b7362a`) |
| pill / pending | `#e9eef4` · `#3c4855` · `#cdd5df` | bg · fg · border (dot `#8b95a1`) |
| type | Public Sans / IBM Plex Mono / Cormorant Garamond | UI · IDs, values, metadata · label specimen display |
| radius / hit | 2–3px · min 44px | Squared government-form feel; touch targets |

---

## 7. Fixtures and specimen generation

The test set is 25 synthetic specimens across eight label looks and nine capture treatments —
11 clean, 2 mild blur, 1 heavy blur, 3 glare, 3 pixelated, 2 off-axis, 1 dark, 1 damaged,
1 cropped — with the intended defect declared per row, plus three adversarial specimens
carrying injected instruction text (§3.3). Generation instructions and the full manifest are in
`label-image-generation-prompt.md`; brands are fictional, no real trade dress.

Each fixture carries an expectation record in `fixtures/expectations.json`: application values
as filed, values truly on the label, fields deliberately made illegible, and the expected
record verdict. `test_adjudicate.py` asserts every one, and the same file is ground truth for
the benchmark (§5.4) — this is how "zero false auto-closes" is enforced in CI and in the reader
bake-off alike. The named single-label samples in the UI (matching, casing difference, missing
warning, title-case warning, reworded warning, ABV mismatch, unit mismatch, glare on net
contents, pixelated brand) are the same fixtures, published as `specimens.json` on the data
volume.

---

## 8. Non-functional requirements

**Performance.** Verification p95 **under 5 seconds measured from the reviewer pressing
Verify** — the threshold the Compliance Division identified as the point at which the previous
scanning pilot was abandoned. This is met by extracting on upload (§5.2), so the model call
overlaps the reviewer's data entry rather than following it. Reader wall-clock time is tracked
separately as an internal metric and surfaced on the determination view. Field results stream
to the UI as they resolve. Inbox first paint under 1.5 s on a cold cache. Store operations
under 300 ms.

**Batch throughput.** A 25-application batch completes in under 3 minutes. A 300-application
batch — the peak-season volume described by the Compliance Division — completes in under 10
minutes at `READER_CONCURRENCY=10`. Concurrency is bounded, not unbounded: 300 simultaneous
requests would exceed provider rate limits, exhaust memory during image preparation, and
destroy per-record progress reporting. Note that OpenAI Tier 1 limits are 500 RPM and 500,000
TPM; the account tier is verified before any 300-record run, and the ceiling is documented in
the runbook. Each job reports estimated spend in its summary.

**Access.** No user accounts, no signup, no session management. Mutating endpoints require a
shared bearer token (`ACCESS_TOKEN`) supplied in the README; `POST /api/store/import` and
`POST /api/fixtures {mode: reset}` additionally require `ADMIN_TOKEN`. This is one middleware
and no user model, and it prevents an unauthenticated visitor from spending the model budget.
Because there is no identity, `decided_by` is captured as a free-text reviewer name on the
determination; the timestamp and override flag — the audit-relevant fields — are recorded
regardless.

**Spend control.** Hard spend limits are configured on the OpenAI and Google API dashboards and
are the primary control. The service adds a secondary backstop, `DAILY_SPEND_CAP_USD` (default
50), accounted in the reader layer from per-request token usage. On breach, verification returns
rules-only verdicts with the engine string naming the cause, and `/api/health` reports the
condition. This is defence in depth rather than the sole guard: it degrades gracefully
mid-batch where a provider-side cap returns hard errors, and it keeps spend visible in the
application's own health output. Per-IP rate limits apply to upload and verify.

**Security.** Upload allowlist (PNG / JPEG / WebP, 12 MB maximum, magic-byte sniffed,
re-encoded before storage); images served from a path that cannot execute; CSV cells prefixed
against spreadsheet formula injection on export; reader API key server-side only, never in the
client bundle; dependencies pinned with hashes, `pip-audit` and `npm audit` gating CI, SBOM
generated at build. Structured logs redact applicant names and free-text notes — only record
identifiers, verdicts, and timings are logged. The deployment carries synthetic fixture data
only; no real applicant information is present, which is stated in the README.

**AI governance.** `AUTO_APPROVE_MATCHES` defaults to **off** and is admin-configurable only.
When enabled, auto-close requires the full eligibility test of §5.3, every auto-close writes an
audit row, and a configurable sample rate (`QA_SAMPLE_RATE`, default 0.05) routes a random
fraction of otherwise-eligible records to human review anyway. Automatic closure of a
compliance determination is a policy decision, and the system treats it as one.

**Accessibility.** Verdict is never conveyed by colour alone — every pill carries text;
contrast at least 4.5:1; full keyboard path through inbox → detail → decision; dialogs
focus-trapped and Escape-dismissible; live-region announcements on verification completion.

**Observability.** Structured JSON logs with a request id; one audit row per determination;
counters for verifications, verdict mix, reader errors, cache hits, spend; `/api/health` polled
by the host.

**Data protection.** Nightly snapshot of `records.db` and the image directory to encrypted
off-box storage, 30-day retention. Restore procedure documented and rehearsed once at M7.

---

## 9. Deployment

The application runs on a Tailscale-connected VPS with no public ingress of its own. The
existing public web host terminates TLS for `bryanzane.com` and reverse-proxies `/ttb-build`
across the tailnet to the application box. The app host therefore needs no open ports beyond
Tailscale, which removes an entire class of exposure — the API is unreachable from the public
internet except through the front Caddy.

**Public host Caddyfile** (added to the existing `bryanzane.com` block):

```
handle_path /ttb-build/* {
    reverse_proxy 100.88.216.70:8080
}
```

**App host** — Caddy plus API in Compose, started by a systemd unit so the stack survives
reboot. The app-host Caddy listens on the tailnet interface only, serves the built frontend,
proxies `/api` to the API container, and serves the data volume's static assets directly:

```
:8080 {
    root * /srv/labelverify/web
    handle /api/* { reverse_proxy api:8000 }
    handle /images/*   { root * /srv/labelverify/data; file_server }
    handle /export/*   { root * /srv/labelverify/data; file_server }
    handle { try_files {path} /index.html; file_server }
    encode gzip
}
```

`/export/records.csv` is the CSV mirror from §4.2, served straight off disk — which is how the
export endpoint was removed from the API surface without losing the capability.

```
/srv/labelverify/
  docker-compose.yml     caddy + api
  Caddyfile
  .env                   READER_*, ACCESS_TOKEN, ADMIN_TOKEN, DAILY_SPEND_CAP_USD,
                         AUTO_APPROVE_MATCHES, QA_SAMPLE_RATE, DATA_DIR=/data,
                         PUBLIC_BASE_PATH=/ttb-build
  web/                   built Vite bundle (immutable asset hashes)
  data/                  bind mount: records.db, records.csv, images/, snapshots/
  deploy.sh              pull, build, migrate-check, up -d, health gate, rollback
```

**Subpath configuration.** `PUBLIC_BASE_PATH` is read at build time and threaded into four
places that must agree: Vite `base`, React Router `basename`, the API client base URL, and the
front Caddy's `handle_path`. It is defined once and injected; it is not repeated across config
files.

**Host prep.** Non-root `deploy` user owning `/srv/labelverify`; root SSH login disabled; SSH
keys only; UFW denying all inbound except the Tailscale interface; `fail2ban`; unattended
security upgrades; 2 GB swap.

**CI (GitHub Actions).** Lint, mypy, pytest, vitest, Playwright, `pip-audit`, `npm audit`,
SBOM; build both images and push to the registry; SSH deploy on a tag over the tailnet.
`deploy.sh` gates on `/api/health` and rolls back to the previous tag on failure.

**Backups.** Nightly cron tars `data/` and encrypts it to off-box object storage; weekly
restore verification into a scratch directory.

**Staging** is the same Compose file on a second port with its own data volume, so fixture
resets never touch production.

---

## 10. Roadmap

| M | Milestone | Deliverables and exit criteria |
| --- | --- | --- |
| M0 | Skeleton and contracts | Monorepo (`api/`, `web/`, `fixtures/`), Pydantic models, generated TS types, token middleware, health endpoint, CI green. *Exit:* `docker compose up` serves an empty inbox from the real API under `/ttb-build`. |
| M1 | SQLite store, CSV mirror, fixtures | Three-table schema, migrations, snapshots, append-only audit, seed/reset, `csv_io` plus the debounced mirror, 25 specimens with `expectations.json`. *Exit:* byte-identical round trip and reset both pass; mirror regenerates within two seconds of a mutation. |
| M2 | Rules engine | Normalisation, per-field comparison, warning composite, roll-up, agent-ready notes, quality downgrade, verdict-improvement guard. *Exit:* all 25 fixture expectations green with the `fake` reader; no defect fixture reaches match. |
| M3 | Reader layer and bake-off | Image prep, versioned prompts, schema validation, retries, cache, both vision providers with the effort clamp, always-on OCR, dual-reader gate, injection fixtures, `scripts/bench.py`. *Exit:* `docs/benchmark.md` committed, zero false auto-closes for every reader, at least one configuration meeting the §8 p95 target, production default named with a rationale. |
| M4 | Reviewer UI | Inbox, single check with extract-on-upload, determination view with per-stage timings and both readers' values, decision dialogs with override warning, persisted minimise, toasts, store page. *Exit:* prototype parity signed off screen by screen. |
| M5 | Batch pipeline | Three-pass pairing with all five buckets, stage/commit, sample batch, job queue with SSE progress and spend reporting, verify-all, partial-failure recovery. *Exit:* 25-application batch inside the time budget with one row deliberately missing its image and one ambiguous pair blocking commit; 300-record run inside 10 minutes. |
| M6 | Deploy and cutover | Compose, tailnet-only app host, front-host `/ttb-build` proxy, systemd unit, shared-token access, spend caps verified on both dashboards, backups, staging, CI deploy with rollback. *Exit:* two reviewers work a real batch at `bryanzane.com/ttb-build` end to end. |
| M7 | Hardening | Playwright suite, accessibility audit, load pass at 10 concurrent reviewers, restore rehearsal, runbook and operator guide. *Exit:* runbook followed successfully by someone who did not build the system. |

---

## 11. Acceptance tests

1. Clean reference fixture, correct application → every field match, eligible for auto-close, closed count increments when auto-approve is on.
2. Casing-only difference → review, not fail; note names capitalisation explicitly.
3. Missing government warning → fail; warning row states the statement is absent.
4. Reworded warning → fail; title-case or non-bold header → review.
5. 75 cl on label vs 750 mL filed → review (equivalent volume, different unit expression).
6. 12.5% on label vs 13.5% filed → fail.
7. Glare over net contents, pixelated brand, heavy blur → that field fails as illegible while other fields still resolve.
8. Accept on a fail verdict → confirmation lists each disagreeing field; cancel changes nothing; confirm stores override flag and reviewer name.
9. Batch of 25 with one unmatched image → 24 verify, 1 files as image-missing, no row lost.
10. Export → import → export produces identical bytes; reset restores 24 fixtures after snapshotting.
11. Vision provider unreachable → verification still returns rules verdicts from OCR values and the engine string names the fallback; the record does not auto-close.
12. Reload mid-review → open record and minimised panel state restored.
13. A specimen carrying injected instruction text in its artwork produces its expected rules verdict; the injected content appears nowhere in the determination.
14. A staged batch containing two images that normalise to the same stem reports `ambiguous` and blocks commit until resolved.
15. Reader switched from `openai` to `gemini` between two verifications of the same specimen produces two distinct cache entries and two recorded `reader_model` values.
16. `READER_EFFORT=minimal` with `READER_PROVIDER=gemini` is clamped to `low` and the request succeeds.
17. Daily spend cap breached mid-batch: remaining records complete with rules-only verdicts and the engine string names the cause; no record is lost.
18. Re-verifying an already-decided record appends an `audit` event and leaves the prior determination readable; `records` reflects only the current state.
19. `scripts/bench.py --readers openai,gemini,ocr` completes on the full fixture set and writes both `data/benchmark.csv` and `docs/benchmark.md`; every reader reports zero false auto-closes.
20. Per-stage timings (`prep_ms`, `reader_ms`, `rules_ms`) are present and non-zero on every verified record, and sum to within 5 ms of `elapsed_ms`.

---

## 12. Risks, decisions and open questions

**Superseded verdicts are retained.** The `audit` table is append-only: re-verification and
re-decision append an event rather than overwriting, and `records` holds only the current
state. A compliance audit trail that discards prior determinations cannot answer the question
it exists to answer.

**A returned record is not reopenable.** The applicant files afresh. The original record
remains closed and linked to its successor by `supersedes_id`, so the history is traceable
without a mutable record.

**Still open:** whether the government warning may legitimately sit on a back label the
specimen does not include, and if so whether the reviewer attaches a second image. This is a
verdict-correctness question, not a nicety — until it is answered, a single-image specimen
missing the warning is treated as `fail`, which may generate false rejections for products
whose warning is genuinely on a back label.

| Risk | Mitigation |
| --- | --- |
| Reader hallucinates a value and a defect auto-closes | Rules own the verdict; the reader may never improve one; OCR agreement gates auto-close; fixture suite blocks release |
| Prompt injection via specimen artwork | Transcribe-only prompt, strict schema, no verdict improvement, adversarial fixtures in CI |
| Degraded captures produce confident wrong readings | Sharpness prior plus dual-reader agreement; `ILLEGIBLE` sentinel is a `fail`, never a guess |
| Reader latency or cost at batch scale | Extraction on upload, content-addressed cache, bounded concurrency, per-image budget, provider-side spend caps plus an in-service backstop, per-job spend reporting |
| Provider unavailable or blocked by egress policy | Two interchangeable providers plus local OCR; rules verdicts always return; engine string names the reader |
| Single VPS is a single point of failure | Stateless containers plus a bind-mounted volume; restore is one `deploy.sh` run against a fresh host |

---

## 13. Appendix: Specimen manifest (ground truth)

The 25 synthetic label photos referenced throughout §7 were produced and are shipped in this
handoff bundle as `fixtures-manifest.csv`, one row per specimen: `id, filename, brand,
class_type, alcohol, net_contents, origin, look, treatment, intended_defect`. This is the
ground truth the seed builder (`api/seed.py`) and the test suite (`test_adjudicate.py`) are
built from — `intended_defect` states, in prose, exactly what `fixtures/expectations.json`
must encode as the expected field-level and record-level verdict per §3.2's rules. Rows whose
`intended_defect` is "none — clean reference" are the ≥60% auto-close-eligible set from §1;
every other row is a deliberately injected defect and must **never** reach `match` on the
field it targets (the zero-false-auto-close bar in §1 and §5.4).

| # | Filename | Brand | Class/Type | Alcohol | Net | Origin | Look | Treatment | Intended defect |
|---|---|---|---|---|---|---|---|---|---|
| 1 | old-tom-pass.jpg | OLD TOM DISTILLERY | Kentucky Straight Bourbon Whiskey | 45% Alc./Vol. (90 Proof) | 750 mL | — | classic | normal | none — clean reference |
| 2 | stones-throw-caps.jpg | STONE'S THROW | Kentucky Straight Bourbon Whiskey | 45% Alc./Vol. (90 Proof) | 750 mL | — | industrial | normal | brand rendered in full caps; warning verbatim |
| 3 | harbor-mist-nowarning.jpg | HARBOR MIST | India Pale Ale | 6.8% Alc./Vol. | 12 FL OZ | — | botanical | normal | government warning completely absent |
| 4 | cedar-ridge-titlecase.jpg | CEDAR RIDGE | Napa Valley Cabernet Sauvignon | 14.2% Alc./Vol. | 750 mL | — | crest | normal | warning header in Title Case, not ALL CAPS |
| 5 | lark-hollow-reworded.jpg | LARK HOLLOW | Small Batch Gin | 44% Alc./Vol. (88 Proof) | 750 mL | — | minimal | normal | warning replaced with non-compliant reworded text |
| 6 | vinos-del-sol-abv.jpg | VINOS DEL SOL | Rioja Tempranillo | 12.5% Alc./Vol. | 750 mL | Product of Spain | crest | normal | none — clean reference |
| 7 | iron-gate-blur.jpg | IRON GATE | Straight Rye Whiskey | 50% Alc./Vol. (100 Proof) | 750 mL | — | band | blurry | mild soft-focus, all text incl. warning still readable |
| 8 | saltmarsh-glare.jpg | SALTMARSH | Gose Style Ale | 4.5% Alc./Vol. | 16 FL OZ | — | script | glare | glare blows out net contents only |
| 9 | north-fen-pixel.jpg | NORTH FEN | Vodka | 40% Alc./Vol. (80 Proof) | 1 L | — | slate | pixelated | brand name illegible |
| 10 | brasserie-verte-origin.jpg | BRASSERIE VERTE | Belgian Style Tripel | 9.2% Alc./Vol. | 330 mL | — | crest | angled | no country-of-origin statement anywhere |
| 11 | quarry-house-units.jpg | QUARRY HOUSE | Willamette Valley Pinot Noir | 13.1% Alc./Vol. | 75 cl | — | minimal | normal | net contents in cl, not mL |
| 12 | golden-hour-nonbold.jpg | GOLDEN HOUR | Orange Liqueur | 24% Alc./Vol. (48 Proof) | 500 mL | — | script | normal | warning header not bold |
| 13 | ember-line-heavyblur.jpg | EMBER LINE | Single Malt Whiskey | 58.4% Alc./Vol. (116.8 Proof) | 700 mL | — | slate | heavyBlur | alcohol content and warning unreadable |
| 14 | stillwater-glare.jpg | STILLWATER LANDING | Finger Lakes Dry Riesling | 11.5% Alc./Vol. | 750 mL | — | botanical | glare | glare blows out alcohol content only |
| 15 | red-kite-pixel.jpg | RED KITE | American Pale Ale | 5.2% Alc./Vol. | 16 FL OZ | — | industrial | pixelated | class/type line illegible |
| 16 | casa-luz-origin.jpg | CASA LUZ | 100% de Agave Blanco Tequila | 40% Alc./Vol. (80 Proof) | 750 mL | Product of Mexico | band | normal | none — clean reference |
| 17 | fogbank-dark.jpg | FOGBANK | Baltic Porter | 8.1% Alc./Vol. | 500 mL | — | slate | dark | warning sinks into dark background |
| 18 | pilgrim-oak-damaged.jpg | PILGRIM OAK | Apple Brandy | 42% Alc./Vol. (84 Proof) | 375 mL | — | classic | damaged | tear/stain removes producer statement |
| 19 | tallgrass-cropped.jpg | TALLGRASS UNION | Saison | 6.4% Alc./Vol. | 750 mL | — | minimal | cropped | warning partly/wholly outside frame |
| 20 | maison-clair-angled.jpg | MAISON CLAIR | Cotes de Provence Rose | 12.8% Alc./Vol. | 750 mL | Product of France | crest | angled | net contents borderline legible at far edge |
| 21 | blue-heron-blur.jpg | BLUE HERON | Straight Rye Whiskey | 47% Alc./Vol. (94 Proof) | 750 mL | — | band | blurry | mild soft-focus, all text incl. warning still readable |
| 22 | copper-kettle-pass.jpg | COPPER KETTLE | Blended Scotch Whisky | 43% Alc./Vol. (86 Proof) | 1 L | Product of Scotland | classic | normal | none — clean reference |
| 23 | wildvine-glare.jpg | WILDVINE | Sonoma Coast Orange Wine | 13.4% Alc./Vol. | 750 mL | — | script | glare | glare blows out brand name only |
| 24 | south-shoal-pixel.jpg | SOUTH SHOAL | Flavored Malt Beverage | 5.0% Alc./Vol. | 12 FL OZ | — | minimal | pixelated | net contents illegible |
| 25 | abbey-row-pass.jpg | ABBEY ROW | Belgian Style Dubbel | 7.6% Alc./Vol. | 330 mL | — | botanical | normal | none — clean reference |

**Distribution:** treatments — angled 2, blurry 2, cropped 1, damaged 1, dark 1, glare 3,
heavyBlur 1, normal 11, pixelated 3. Looks — band 3, botanical 3, classic 3, crest 4,
industrial 2, minimal 4, script 3, slate 3. This matches the ≥60%-clean and zero-false-close
targets in §1 and the look/treatment rotation specified in `label-image-generation-prompt.md`.

The actual specimen photos (25 image files, filenames as above) are the deliverable of that
generation prompt and are supplied alongside this PRD in the handoff bundle's `fixtures/`
folder — copy them there before running `api/seed.py` or `scripts/bench.py`.

## 14. Assumptions

1. **Egress is restricted.** The IT interview described a firewall that broke the previous
   vendor's ML endpoints. No vision provider is a hard dependency: local OCR plus the rules
   engine produce a complete verdict with the reader disabled, and the engine string always
   names what read the label.
2. **Standalone prototype.** No integration with COLA, no e-filing, no authorisation boundary
   shared with existing systems.
3. **Synthetic data only.** All 25 specimens are generated; brands are fictional; no real trade
   dress is reproduced; no applicant PII exists in the deployment.
4. **Provider choice is a configuration, not an architecture.** Swapping vision models is an
   environment change. The production provider is selected from the measured bake-off, not
   asserted in advance.
5. **Model pricing and rate limits are current as of 19 Aug 2026** and are verified against
   provider documentation before the cutover at M6.
