# Label Verification Service — PRD & Build Plan

**v1.2 — 20 Aug 2026.** Reconciled with the delivered build. One configured vision provider
rather than two, with local OCR as its fallback rather than an always-on second reader;
extraction on request rather than on upload; job progress by polling rather than server-sent
events; a paid-call cap rather than a dollar estimate; `invalid` added to the verdict enum;
Caddy and systemd rather than Docker Compose. Where a decision reversed something in v1.1, the
reason is stated in place and the trade recorded in the README.

**v1.1 — 19 Aug 2026.** System of record moved from CSV to SQLite with a derived CSV mirror.
API surface reduced from 19 endpoints to 10. Authentication replaced with shared-token access
and spend controls. Performance targets reconciled with the 5-second stakeholder requirement.
Batch pairing, prompt-injection posture, and AI governance specified.

AI-assisted TTB-style COLA label verification. A reviewer files an application, a vision
model reads the label specimen, the two are adjudicated field by field, and every
determination is written to an auditable system of record.

- **Stack:** React 19 + TypeScript (Vite) · Python 3.12 + FastAPI · SQLite system of record with CSV mirror · Caddy and systemd on a Tailscale-connected VPS
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
| S1 | Check one label: upload a specimen, type the application fields, verify. | Record created, the label is read on submit, verdict returned and reported with a way into the record. |
| S2 | Prefill the single-label form from a named sample (matching, casing difference, missing warning, title-case warning, reworded warning, ABV mismatch, unit mismatch, illegible field). | Every sample selectable and reproduces its documented verdict. |
| S3 | Batch upload: application CSV + folder of label images, paired on `filename`. | Staged preview reports all five pairing buckets (§5.5); commit files every non-ambiguous row. |
| S4 | Load the bundled sample batch in one click. | The 25 fixture applications stage, images resolved — bar the three rows deliberately left in the other pairing states (§5.5). |
| S5 | Inbox filtered by needs attention / awaiting AI / review / fail / closed, with search over ID, applicant, brand, filename. | Filter counts match the store; search is case- and punctuation-insensitive. |
| S6 | Open an unverified application, fill missing fields, press Verify. | Row shows busy state, resolves to pass/review/fail without page reload; field results stream as they resolve. |
| S7 | Verify every pending record in one action. | Progress per record; one failure does not abort the rest; job summary reports the verdict mix. |
| S8 | Accept a flagged record after explicit confirmation naming each disagreeing field. | Confirmation lists offending fields; acceptance stores reviewer name, timestamp, override flag. |
| S9 | Return a record to the applicant with an editable reason. | Reason persists and appears in the export; the record is not reopenable (§12). |
| S10 | Minimise the detail panel and return to it later on this device. | Collapsed/expanded state and open record survive reload. |
| S11 | Export the store as CSV; import a CSV back; download a blank template. | Round-trip lossless: seed → export → wipe → import → export is byte-identical. |
| S12 | Reset the store to the bundled example set. | Reset requires the admin token, is confirmed in the UI, snapshots the prior store, restores the example set. |
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
fail; else any review → review; else match), plus `invalid`, which is not a field verdict at
all. No verdict yet = *awaiting AI*. Decision ∈ `null | accepted | returned`; a match verdict
may auto-set `accepted` by `Automatic` only when auto-approve is enabled **and** the record
passes the full eligibility test of §5.3.

- **match** — normalised values identical, or numerically equivalent within tolerance.
- **review** — same content, different presentation: capitalisation, punctuation, unit
  expression, an optional accompanying statement, a value on the label omitted from the
  application, or a cosmetic warning defect (title-case header, non-bold header). Also
  assigned when an otherwise-matching field was read from a degraded capture with low
  reader confidence.
- **fail** — different content; a required value absent from the label; a reworded or missing
  government warning; or a field the extractor returned as `ILLEGIBLE`.
- **invalid** — the specimen is not an alcohol beverage label at all. Added after v1.1: such a
  record cannot be adjudicated field by field, and `fail` would tell the reviewer the
  applicant's label is wrong when the finding is that the wrong file was filed. No field rows
  are written and the roll-up is bypassed. Only the vision reader can raise it, and the prompt
  is deliberately reluctant — a hard-to-read label must still be adjudicated.

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

Plus columns that exist only in the database: `override`, `reader_provider`, `reader_model`,
`prompt_version`, `prep_ms`, `reader_ms`, `rules_ms`, and `reading_json`. The timing columns
make per-record latency comparable in production, not just in the bench (§5.4).
`reading_json` holds the reading behind the current verdict, so correcting an application
re-adjudicates against the label already read rather than paying to read it again
(`migrations/005`). `override` is exported; the rest are not.

v1.1 also specified `supersedes_id`, for PRD §12's refile-links-back. It was never written or
read, and was dropped in `migrations/006`.

The CSV columns absent here — `field_results`, `field_notes` and `field_values` — are packed
at export time from the second table.

**field_results** — one row per verified field per record. Replaces v1.0's packed
`key:verdict|key:verdict` cell, which was a serialization format nested inside a
serialization format.

```
record_id, field_key, app_value, label_value, verdict, note, confidence
```

Unique on (`record_id`, `field_key`). v1.1 also specified `reader_value`, `ocr_value` and
`agreed`, to retain what each reader independently saw and gate auto-close on their agreement.
With one reader plus a fallback (§5.3) there is no second reading to store: `ocr_value` and
`agreed` were never written, and `reader_value` only ever duplicated `label_value`. All three
were dropped in `migrations/006`. `confidence` stays — it is what drives the degraded-capture
downgrade of §3.2.

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

The mirror carries the v1.0 column set, with `field_results` re-packed into the
`key:verdict|key:verdict` form and notes in a parallel `field_notes` column, plus two columns
v1.1 did not have — 26 in all:

```
id, received, applicant, beverage, filename, specimen, quality,
app_brand, app_class_type, app_alcohol_content, app_net_contents,
app_producer, app_origin, app_warning_declared,
verified, result, field_results, field_notes, field_values, elapsed_ms, engine,
decision, override, decided_by, decided_at, note
```

`field_values` carries the observed values as JSON in one cell. Without it the mirror exports
verdicts and notes but not the values they were reached from, so a store restored from an
export renders every field as "not recorded" — a determination with its evidence deleted. JSON
rather than two more packed columns, because observed label values routinely contain both the
`|` and the `:` that `field_notes` separates on.

`override` is here because accepting a record that did not pass is the one determination a
reviewer makes against the engine, and an export that drops the flag destroys the only
evidence that the waiver was deliberate — which is what S8 exists to produce.

**Two further exports**, both API routes rather than files on disk, since the mirror is written
by a background timer and serving the file would race it:

- `GET /api/export/backup.csv` — the full 26-column mirror above. This is what
  `POST /api/store/import` reads back, and the file a restore starts from.
- `GET /api/export/records.csv` — what a reviewer takes away: 18 columns, the same store
  without its machine-facing half. No packed JSON, no timings, no engine string, and an
  `issues` column naming the fields that disagreed in words. Its application columns use the
  batch-intake header names, so a downloaded export can be re-uploaded on Check a batch
  without being translated first. It drops columns, so it is *not* a restore artifact.

### 4.3 CSV interchange

`csv_io.py` holds exactly two functions, both unit-tested independently of the database:

- `to_csv(rows) -> bytes` — fixed column order, RFC 4180 quoting, fixed null representation,
  deterministic output. Cells beginning `= + - @` are prefixed with an apostrophe against
  spreadsheet formula injection.
- `from_csv(bytes) -> rows` — tolerates CRLF, a BOM, and reordered columns; preserves `id` so
  merge-import is idempotent; rejects a file missing `app_brand` with a field-level error the
  UI can display, and recognises a batch-intake CSV well enough to say so by name.

Round-trip test: seed → export → wipe → import → export → assert identical bytes. Satisfies
S11 regardless of storage.

**Batch intake CSV** accepts the shorter applicant header:
`filename, brand_name, class_type, alcohol_content, net_contents, producer, country_of_origin, government_warning, applicant`.
It also accepts the mirror's own names for those seven fields: refusing a file this service
wrote, over a column name, is not a defensible error.

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
  config.py           env parsing, reader API key selection
  models.py           Pydantic: Application, LabelReading, FieldResult, Record
  db.py               connection, schema, migrations, snapshot, reset, audit append
  csv_io.py           to_csv / from_csv / mirror writer — the only CSV code
  adjudicate.py       normalisation, per-field comparison, roll-up, notes
  batching.py         filename pairing, staged-preview construction
  logs.py             structured JSON logging, redaction, service counters
  uploads.py          image sniffing, re-encoding, content-addressed storage
  seed.py             build the example store from fixtures/
  readers/
    __init__.py       Reader protocol, registry, get_reader(config)
    vision.py         OpenAI-compatible client, and the daily paid-call cap
    prep.py           shared image preparation, cached per file
    ocr.py            local Tesseract reader
    fake.py           replays fixture readings — used in CI
    prompts.py        extraction prompts, versioned
  routers/
    records.py  batches.py  jobs.py  store.py  specimens.py
migrations/
  001_initial.sql … 006_drop_unused_columns.sql
tests/                one test module per api module it covers
  test_adjudicate.py  one case per fixture defect, verdict asserted
  test_readers.py     schema conformance, retry, degradation, effort clamp
  test_injection.py   adversarial specimen fixtures
  test_db.py          round-trip, migration, concurrent write
  test_csv_io.py      byte-identical round trip, formula-injection prefixing
  test_batching.py    filename pairing across all five buckets
  test_api.py         contract and behaviour tests for the documented routes
  test_uploads.py     format sniffing, re-encoding, size and name safety
scripts/
  bench.py            reader bake-off against the fixture set (§5.4)
```

### 5.1 API surface

Nine endpoints. Specimen images are served directly by Caddy from the data volume in
production; the API mounts them locally where there is no Caddy.

| Endpoint | Behaviour |
| --- | --- |
| `GET /api/records` | Filter (`attention\|pending\|review\|fail\|closed`), query, cursor page; returns rows plus filter counts. |
| `POST /api/records` | Create one application: multipart (image + JSON), or `specimen_key` for a bundled fixture image. `verify_now` reads and adjudicates it in the same request (§5.2). |
| `GET /api/records/{id}` | Full record: application, reading, field results, notes, engine, timings, decision history. |
| `PATCH /api/records/{id}` | Edit application fields, or issue a decision. Editing invalidates any prior verdict. **The override rule is enforced here**: `decision: accepted` on a non-`match` verdict is rejected unless `override: true`, and the check has its own unit test — it must not be lost inside a generic field-merge loop. |
| `POST /api/records/{id}/verify` | Run adjudication. Idempotent per (record, image hash, prompt version, provider, model, effort) via cache. |
| `POST /api/batches/stage` | Multipart CSV + images. Parses, pairs images by filename (§5.5), returns a staged preview with per-row errors. Nothing is written. |
| `POST /api/jobs` | `{scope: "pending" \| "batch" \| "ids", batch_id?, record_ids?, rows?, verify_now?}`. Commits a staged batch and/or enqueues verification. Returns a job id. |
| `GET /api/jobs/{id}` | Job state, counters, verdict mix and per-record events. Polled; there is no event stream. |
| `POST /api/fixtures` | `{mode: "stage" \| "reset" \| "empty"}`. Stage the sample batch, or snapshot and reseed or clear the store. Admin token required for `reset` and `empty`. |
| `POST /api/store/import` | Replace or merge by `id`, after snapshotting. Admin token required. |
| `GET /api/health` | Store readable, images writable, reader reachable, prompt version, provider, model, paid calls today, service counters. |

Also on the API: `GET /api/batches/{id}` and its per-row image routes (§5.5),
`GET /api/specimens` for the bundled catalogue, and the three CSV exports of §4.2 —
`/api/export/records.csv` (reviewer), `/api/export/backup.csv` (full mirror),
`/api/export/template.csv` (blank intake header).

### 5.2 Reader layer

**Provider.** One vision model, reached through the OpenAI Chat Completions API. The adapter
is deliberately thin, so any OpenAI-compatible endpoint is a base-URL change rather than a
rewrite — which is how a second provider would be added back if one were ever needed. v1.1
specified two providers side by side; the second was dropped because a single-tenant tool does
not need provider redundancy badly enough to pay for a second bake-off, and the abstraction it
required was a per-provider table with one row in it.

| | OpenAI |
| --- | --- |
| Model string | `gpt-5.6-luna` |
| Base URL | default, overridable by `READER_BASE_URL` |
| Image input | `image_url` with `data:image/jpeg;base64,…` |
| Effort parameter | `reasoning_effort`: `none` (default), `low`, `medium`, `high`, `xhigh`, `max` |
| Structured output | `json_schema`, strict, closed with `additionalProperties: false` |
| Published price | $0.20/M in, $0.02/M cached in, $1.20/M out |

**Two constraints, enforced in the adapter:**

1. **Effort clamp.** Configured effort is raised to the provider floor (`none`), and an
   unrecognised value falls to it rather than being forwarded. Asserted in `test_readers.py`.
2. **Service tier.** The API does not accept the value `standard` this document names as the
   default; the valid values are `auto`, `default`, `fast`, `flex` and `priority`. The adapter
   maps `standard` onto `auto`. Found by calling the endpoint, and asserted in
   `test_readers.py`.

**Configuration.**

```
READER_PROVIDER=openai|ocr|fake
READER_MODEL=gpt-5.6-luna
READER_BASE_URL=                    # empty = OpenAI default
READER_API_KEY=                     # OPENAI_API_KEY takes precedence
READER_EFFORT=none                  # clamped to the provider floor
READER_SERVICE_TIER=standard        # mapped onto the API's `auto`
READER_TIMEOUT_S=25
READER_CONCURRENCY=10
DAILY_VISION_CALL_CAP=300           # paid calls per UTC day; 0 disables
```

**Image preparation.** Pillow applies EXIF rotation, downscales the longest edge to 1024 px,
encodes JPEG q85, and computes a perceptual sharpness score used as the capture-quality prior.
The 1024 px default is validated against the fixture set by `scripts/bench.py` before it is
fixed; if per-field accuracy drops, the value moves back to 1600 and the latency budget
absorbs it. The second bottom-crop pass v1.1 specified was not built: the single pass reaches
the documented warning verdict on every fixture, so it would be a second paid call for an
accuracy problem that has not appeared.

**Extraction runs when a reviewer asks, not on upload.** The reader never sees application
values, so extraction *could* start the moment the specimen lands — v1.1 specified exactly
that, to hide the model call behind the reviewer's data entry. It costs money per call, and a
filing nobody ever verifies must never pay for one, so the reader runs only on request:
`verify_now` on `POST /api/records`, the Verify action, or a job. The consequence is that
verification latency is now wholly model latency, which is why §8's target is measured in
§5.4 rather than assumed.

**Guards.** Two retries with backoff on transport or schema failure; a 25-second per-image
budget; results cached by `sha256(image) + prompt_version + provider + model + effort` — the
provider and model components prevent a stale reading being served after a configuration
change; a strict JSON schema with one object per field carrying `value`, `confidence`, and a
literal `ILLEGIBLE` sentinel, plus the warning composite (present, body verbatim, header case,
header bold) and a capture-quality classification drawn from the fixture vocabulary (`normal`,
`blurry`, `heavyBlur`, `glare`, `pixelated`, `angled`, `dark`, `damaged`, `cropped`).

### 5.3 OCR fallback and auto-close eligibility

Local OCR (Tesseract) is free, needs no network, and serves two purposes:

1. **Fallback reader.** When the vision provider is unreachable — the firewall scenario raised
   in the IT interview — OCR supplies observed values and the engine string names it, so the
   service degrades rather than blocking. A record read this way carries a *Read by local OCR*
   chip in the determination view.
2. **Illegibility prior.** The sharpness score computed during preparation drives the
   capture-quality call when OCR is what read the label.

v1.1 ran OCR on **every** specimen as an independent second reader, and made agreement between
it and the vision model the auto-close gate. That is not what was built. §5.4 measures OCR at
15 of 25 documented verdicts but only 85 of 155 fields, against the vision reader's 122 —
accurate enough to fall back to, not accurate enough to gate on, and a gate it
disagrees with on `brand` most of the time is one that routes everything to a human anyway. So
OCR runs only when the vision reader fails, and the agreement clause is dropped from the gate.

**Auto-close eligibility.** A record may auto-close only if all of the following hold:
`AUTO_APPROVE_MATCHES` is on, which it is not by default; every field verdict is `match`;
capture quality is `normal`; the reading did not come from the OCR fallback; and the record was
not drawn into review by `QA_SAMPLE_RATE`. Anything else routes to the review inbox.

OCR is not a batch-size fallback. Reader selection never varies with queue depth — two records
must not receive different verdict quality for reasons unrelated to their content, which would
be indefensible on audit.

**Runtime timings.** Every verification records `prep_ms`, `reader_ms`, `rules_ms`, and
`elapsed_ms` on the record, measured with `time.perf_counter_ns()` and rounded to whole
milliseconds at the boundary. Preparation runs inside the reader call and is subtracted out
rather than counted twice.

Provider selection is a measurement, not an assertion. The measurement is specified in §5.4.

### 5.4 Reader benchmark

`scripts/bench.py` runs the full fixture set through a named reader and produces the evidence
for choosing one. It is the artifact that turns "we picked Luna" into "we measured Luna against
the 4.1 class and against OCR, and here is the table."

```
uv run python scripts/bench.py --reader openai --model gpt-5.6-luna --effort none
```

**Method.** Every reader sees the identical prepared image, so differences are attributable to
the reader and not to preprocessing. The extraction cache is bypassed and the preparation cache
is cleared per fixture. Timings run from the Verify press, which is where §8 sets the
threshold — and since extraction now happens there rather than on upload, that is the whole
model call. Ground truth is `fixtures/expectations.json`.

One run per configuration, not the median of three v1.1 asked for: each run is 25 paid calls,
and the four configurations already separate by more than the run-to-run spread.

**Timing instrumentation.** Four stages, `perf_counter_ns()` at each boundary, reported in ms:

| Stage | Measures |
| --- | --- |
| `prep_ms` | EXIF rotation, downscale, JPEG encode, sharpness score |
| `reader_ms` | Request dispatch to parsed response — the only stage that differs between readers |
| `rules_ms` | Normalisation, comparison, roll-up, note generation |
| `total_ms` | Verify press to verdict written |

**Outputs.** The table is printed to stdout; `--out` writes it to a file and `--json` the raw
rows, so any claim can be recomputed. The head-to-head result and the rationale for the
production default are recorded in the README.

**Summary tables.** Per reader: p50, p95 and max `total_ms`; median `reader_ms` and `prep_ms`;
median input and output tokens and output tokens per second; verdict accuracy against ground
truth; per-field accuracy across all seven fields; capture-quality accuracy; and error count.
The p95 column is checked directly against the 5-second requirement in §8.

The three-way agreement matrix v1.1 specified is not produced: it existed to justify the
auto-close gate's reader-agreement clause, which §5.3 no longer has.

**Exit criteria.** M3 does not close until the bake-off has been run, no reader shows a defect
fixture reaching `match`, and at least one configuration meets the p95 target of §8. The chosen
production default is named in the README with a rationale citing the table.
`tests/test_readers.py` runs the same code path against the `fake` reader, so the benchmark is
covered in CI without network access or spend.

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
| `/batch` | Check a batch. CSV dropzone, image multi-drop, template download, load-sample-batch, staged table showing all five pairing buckets with row errors and per-row image picker, commit with per-record progress. |
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
scanning pilot was abandoned. Because extraction runs on request rather than on upload (§5.2),
that window is wholly model latency, so it is measured rather than assumed:
§5.4 records 4,084 ms p95 for the production configuration. Per-stage timings
are recorded on every record. Inbox first paint under 1.5 s on a cold cache. Store operations
under 300 ms.

**Batch throughput.** A 25-application batch completes in under 3 minutes. A 300-application
batch — the peak-season volume described by the Compliance Division — completes in under 10
minutes at `READER_CONCURRENCY=10`. Concurrency is bounded, not unbounded: 300 simultaneous
requests would exceed provider rate limits, exhaust memory during image preparation, and
destroy per-record progress reporting. Note that OpenAI Tier 1 limits are 500 RPM and 500,000
TPM; the account tier is verified before any 300-record run, and the ceiling is documented in
the runbook. Each job reports its verdict mix in its summary; a per-job spend estimate was
dropped, because an honest one needs a per-model price table and the enforced control is the
call cap below.

**Access.** No user accounts, no signup, no session management. Mutating endpoints require a
shared bearer token (`ACCESS_TOKEN`) supplied in the README; `POST /api/store/import` and
`POST /api/fixtures {mode: reset}` additionally require `ADMIN_TOKEN`. This is one middleware
and no user model, and it prevents an unauthenticated visitor from spending the model budget.
Because there is no identity, `decided_by` is captured as a free-text reviewer name on the
determination; the timestamp and override flag — the audit-relevant fields — are recorded
regardless.

**Spend control.** A hard spend limit on the provider dashboard is the primary control. The
service adds a secondary backstop, `DAILY_VISION_CALL_CAP` (default 300), accounted in the
reader layer. It counts paid calls rather than dollars: an honest dollar figure needs a
per-model price table that goes stale, and a call count cannot. On breach, verification returns
rules-only verdicts with the engine string naming the cause, and `/api/health` reports the
count against the cap. This is defence in depth rather than the sole guard: it degrades gracefully
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

**App host** — Caddy and the API directly under systemd, so both survive reboot. v1.1
specified Docker Compose; the target is a shared host already running Caddy and several other
services under systemd, so a container runtime would have added operational surface without
buying isolation this tool needs. The app-host Caddy listens on the tailnet interface only,
serves the built frontend, proxies `/api`, and serves the image directory directly:

```
:8080 {
    root * /var/www/ttb-build/web/dist
    handle /api/images/* { root * /var/www/ttb-build/data; file_server }
    handle /api/* { reverse_proxy 127.0.0.1:8020 }
    handle { try_files {path} /index.html; file_server }
    encode gzip
}
```

The CSV exports are API routes rather than files on disk (§4.2): the mirror is written by a
debounced background timer, so serving the file races that writer.

```
/var/www/ttb-build/
  api/                   FastAPI app, its .venv, migrations
  web/dist/              built Vite bundle (immutable asset hashes)
  data/                  records.db, records.csv, images/, snapshots/
  .env                   READER_*, ACCESS_TOKEN, ADMIN_TOKEN, DAILY_VISION_CALL_CAP,
                         AUTO_APPROVE_MATCHES, QA_SAMPLE_RATE, DATA_DIR,
                         PUBLIC_BASE_PATH=/ttb-build, BACKUP_DEST, BACKUP_RECIPIENT
  deploy/                Caddyfile, systemd units, deploy.sh, backup.sh
```

**Subpath configuration.** `PUBLIC_BASE_PATH` is read at build time and threaded into the
places that must agree: Vite `base`, React Router `basename` and the API client base URL all
derive from `import.meta.env.BASE_URL`, and the front Caddy's `handle_path` matches it. It is
defined once and injected; it is not repeated across config files.

**Host prep.** SSH keys only; the API bound to loopback and reached only through Caddy; UFW
denying all inbound except the Tailscale interface; unattended security upgrades.

**CI (GitHub Actions).** Three jobs: api (ruff, mypy, pytest, `pip-audit`), web (oxlint,
vitest, build, `npm audit`), and e2e (Playwright plus the axe audit against both servers,
uploading its report on failure). Both audits are advisory. `deploy/deploy.sh` is run on the
host, gates on `/api/health`, and resets to the previous commit if it does not come up.

**Backups.** `deploy/backup.sh` on a systemd timer takes a `sqlite3 .backup` copy with the
image directory, encrypts it with `age`, ships it off-box with rsync, and prunes both ends to
30 days. A rehearsed restore is outstanding — see §10 M7.

---

## 10. Roadmap

| M | Milestone | Deliverables and exit criteria |
| --- | --- | --- |
| M0 | Skeleton and contracts | Monorepo (`api/`, `web/`, `fixtures/`), Pydantic models, hand-written TS types, token middleware, health endpoint, CI green. *Exit:* both dev servers serve an empty inbox from the real API. |
| M1 | SQLite store, CSV mirror, fixtures | Three-table schema, migrations, snapshots, append-only audit, seed/reset, `csv_io` plus the debounced mirror, 25 specimens with `expectations.json`. *Exit:* byte-identical round trip and reset both pass; mirror regenerates within two seconds of a mutation. |
| M2 | Rules engine | Normalisation, per-field comparison, warning composite, roll-up, agent-ready notes, quality downgrade. *Exit:* all 25 fixture expectations green with the `fake` reader; no defect fixture reaches match. |
| M3 | Reader layer and bake-off | Image prep, versioned prompts, schema validation, retries, cache, the vision reader with its effort clamp, OCR fallback, injection fixtures, `scripts/bench.py`. *Exit:* the bake-off run and its table recorded in the README, no defect fixture reaching match for any reader, at least one configuration meeting the §8 p95 target, production default named with a rationale. |
| M4 | Reviewer UI | Inbox, single check, determination view, decision dialogs with override warning, persisted minimise, toasts, records page. *Exit:* prototype parity signed off screen by screen. |
| M5 | Batch pipeline | Pairing with all five buckets, stage/commit, sample batch, job queue with polled progress, verify-all, partial-failure recovery. *Exit:* 25-application batch inside the time budget with one row deliberately missing its image and one ambiguous pair blocking commit; 300-record run inside 10 minutes. |
| M6 | Deploy and cutover | Tailnet-only app host, front-host `/ttb-build` proxy, systemd units, shared-token access, spend cap verified on the dashboard, encrypted off-box backups, deploy script with health gate and rollback. *Exit:* two reviewers work a real batch at `bryanzane.com/ttb-build` end to end. **Done.** |
| M7 | Hardening | Playwright suite, accessibility audit, load pass at 10 concurrent reviewers, restore rehearsal, runbook and operator guide. *Exit:* runbook followed successfully by someone who did not build the system. **Partial:** the Playwright suite, the axe audit, the runbook and the backup timer are in; the load pass and a rehearsed restore are outstanding. |

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
10. Export → import → export produces identical bytes; reset restores the example set after snapshotting.
11. Vision provider unreachable → verification still returns rules verdicts from OCR values and the engine string names the fallback; the record does not auto-close.
12. Reload mid-review → open record and minimised panel state restored.
13. A specimen carrying injected instruction text in its artwork produces its expected rules verdict; the injected content appears nowhere in the determination.
14. A staged batch containing two images that normalise to the same stem reports `ambiguous` and blocks commit until resolved.
15. Model or effort changed between two verifications of the same specimen produces two distinct cache entries and two recorded `reader_model` values.
16. An unrecognised `READER_EFFORT` is clamped to the provider floor and the request succeeds.
17. Daily spend cap breached mid-batch: remaining records complete with rules-only verdicts and the engine string names the cause; no record is lost.
18. Re-verifying an already-decided record appends an `audit` event and leaves the prior determination readable; `records` reflects only the current state.
19. `scripts/bench.py --reader <name>` completes on the full fixture set and writes its summary; no reader lets a defect fixture reach `match`.
20. Per-stage timings (`prep_ms`, `reader_ms`, `rules_ms`) are present and non-zero on every verified record, and sum to within 5 ms of `elapsed_ms`.

---

## 12. Risks, decisions and open questions

**Superseded verdicts are retained.** The `audit` table is append-only: re-verification and
re-decision append an event rather than overwriting, and `records` holds only the current
state. A compliance audit trail that discards prior determinations cannot answer the question
it exists to answer.

**A returned record is not reopenable.** The applicant files afresh and the original stays
closed. v1.1 linked the two with a `supersedes_id` column; it was never written, and was
dropped in `migrations/006`. The `audit` table is what makes the history traceable, and a
refile link belongs with the refile flow whenever that is built.

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
| Reader latency or cost at batch scale | Read only on request, content-addressed cache, bounded concurrency, per-image budget, a provider-side spend cap plus an in-service paid-call backstop |
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
