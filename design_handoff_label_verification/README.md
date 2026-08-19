# Handoff: Label Verification Service

## Overview

An AI-assisted label verification workbench for TTB-style COLA (Certificate of Label
Approval) review. A compliance reviewer files an application (brand name, class/type,
alcohol content, net contents, bottler/producer, country of origin, government warning), a
vision model reads the same fields off the label specimen image, and a deterministic rules
engine adjudicates the two field by field: **match**, **review** (same content, different
presentation) or **fail** (different content, missing required value, or illegible). Field
verdicts roll up to a record verdict; clean matches auto-close, everything else lands in a
review inbox. Every determination is persisted to a SQLite system of record with an
append-only audit log and a derived CSV mirror that the user can export, import, and reset —
but which is never displayed as raw CSV in the browser.

**Read `PRD.md` in this folder first.** It is the authoritative product requirements and
build plan: data model, verdict semantics, CSV schema, full API surface, screen list, design
tokens, non-functional requirements, VPS deployment topology, and an M0–M7 roadmap with exit
criteria. This README covers the design side of the handoff.

## About the design files

`Label Verification.dc.html` in this bundle is a **design reference created in HTML** — a
working prototype showing intended look, copy and behaviour. It is not production code to
copy. The task is to **recreate it in the target codebase** using that codebase's patterns.
Where no codebase exists, the PRD's chosen stack applies: **React 19 + TypeScript (Vite)
frontend, Python 3.12 + FastAPI backend, SQLite system of record with a CSV mirror, Docker
Compose behind Caddy on a Tailscale-connected VPS, served at `bryanzane.com/ttb-build`.**

The prototype keeps its records in `localStorage` as a CSV string and calls the model
client-side. Production moves both server-side: the record store, image storage, rules engine
and reader calls all live in the FastAPI service (PRD §4–5); the React app only talks to the
typed API. Two behaviours differ deliberately from the prototype and are specified in the PRD:
extraction starts on specimen upload rather than on Verify (§5.2), and auto-close is gated on
vision/OCR agreement and defaults to off (§5.3, §8).

## Fidelity

**High-fidelity.** Colours, typography, spacing, copy and interaction states in the
prototype are final and normative. Recreate the UI faithfully using the target codebase's
libraries. The design token table is in PRD §6.2; every hex value in it is taken directly
from the prototype source.

## Screens

Five views. Layout is a fixed 1280px-max content column centred on a `#eef1f5` desk, under a
`#10283d` masthead with a 3px `#b8912f` bottom rule. Cards are white, 1px `#d5dde5` borders,
2–3px radius — a squared, government-form feel, no soft shadows.

### 1. Review inbox (`/inbox`) — default view
- **Purpose:** the reviewer's home. See what needs attention, verify pending records, open
  records to adjudicate.
- **Layout:** notification strip → filter tab row → search + verify-all row → queue table.
- **Notification strip:** full-width card, `#fdf3dd` background, `#e6cf90` border, one line
  of 14px text ("*n* applications need your attention"), with the count in `IBM Plex Mono`
  600. Hidden when the attention count is zero.
- **Filter tabs:** five buttons — Needs attention / Awaiting AI / Needs review / Fail /
  Closed. Inactive: white, `#d5dde5` border, `#3c4855` 13px 600 text. Active: `#10283d` fill,
  white text. Each carries a live count in a mono badge; the attention badge is `#c2410c`
  fill / white text. Min-height 44px.
- **Queue table:** header row `#10283d` fill, white 10px uppercase 0.07em-tracked labels.
  Columns: Application ID (mono 12px) · Applicant · Brand · Specimen filename (mono) ·
  Received · Status pill · Actions. Rows separated by 1px `#d5dde5`; hover `#f5f7f9`.
- **Status pill:** 11.5px 600 text with a 6px dot, 2px radius, 1px border. Four states with
  bg · fg · border · dot: match `#e3f2e6 · #1e5c2e · #b7dcc0 · #2f7a45` ("Match"); review
  `#fdf0d5 · #6b4a05 · #e6cf90 · #b8912f` ("Needs review"); fail `#fbe6e4 · #8a1f16 ·
  #e8b6ae · #b7362a` ("Fail"); pending `#e9eef4 · #3c4855 · #cdd5df · #8b95a1` ("Awaiting
  AI"). Never colour alone — the text always states the verdict.
- **Actions:** primary `Verify` (navy fill, white text) on unverified rows; `Open` (white,
  navy border/text) always. A busy row swaps in a 12px spinner (`@keyframes spin`, 0.7s
  linear) and disables both buttons.
- **Row expand:** clicking a row reveals the field comparison inline — the same three-column
  block as the detail view, in a `#f5f7f9` panel, animating in with `riseIn`
  (opacity 0→1, translateY 6px→0, 180ms ease-out).
- **Empty states:** per filter, centred 14px `#6c7885` text plus the action that would fill
  it (e.g. "No applications are awaiting AI review." + `Check one label`).

### 2. Check one label (`/check`)
- **Purpose:** file and verify a single application.
- **Layout:** two columns, 1fr / 1fr, 24px gap; stacks under 900px.
- **Left:** specimen dropzone — dashed `#cdd5df` 1.5px border, `#f5f7f9` fill, 15px 600
  prompt plus 12.5px `#6c7885` hint, min-height 240px; on drop it becomes the specimen
  preview with the filename in mono and a capture-quality badge (Clean capture, Out of focus,
  Glare, Pixelated, Off-axis, Dark, Damaged, Cropped). Below it, the named-sample picker: a
  select of documented fixtures (matching, casing difference, missing warning, title-case
  warning, reworded warning, ABV mismatch, unit mismatch, glare on net contents, pixelated
  brand) that prefills the form.
- **Right:** the seven application fields. Labels 11px uppercase 0.06em `#6c7885`; inputs
  full width, 1px `#cdd5df`, 2px radius, 10px 12px padding, 14px text, min-height 44px;
  focus adds a 2px `#14507d` outline. The government warning field is a checkbox line
  ("Application declares the health warning statement").
- **Footer:** `Verify label` primary button, right-aligned, with a busy label
  ("Reading specimen…") while running; on completion the app routes to the detail view.

### 3. Check a batch (`/batch`)
- **Purpose:** file many applications at once from a CSV plus a folder of images.
- **Layout:** two dropzones side by side (application CSV / label images), then a utility
  row (`Download blank template`, `Load sample batch`), then the staged table, then commit.
- **Dropzones:** same treatment as §2; each shows the selected filename or "No file
  selected" / "No images selected" in mono 12px.
- **Staged table:** ID · Applicant · Brand · Filename · Image matched (a small pill: matched
  `#e3f2e6`, missing `#fbe6e4`) · Row errors. Parse errors show above the table in a
  `#fbe6e4` / `#e8b6ae` band with the specific column named.
- **Commit row:** "Verify immediately after filing" toggle (default on) and a
  `File n applications` primary button; while running, a determinate progress line
  ("Verified 7 of 24") and per-row status updates.

### 4. Determination view (`/records/:id`)
- **Purpose:** adjudicate one record and issue the determination.
- **Layout:** header block (application ID in mono, applicant, beverage, received date,
  status pill) → two columns: specimen viewer (40%) and comparison table (60%) → engine
  metadata line → decision bar.
- **Specimen viewer:** the image on a `#10151c` mat, click to zoom; below it the filename,
  the capture treatment, and the extraction confidence in mono 11px.
- **Comparison table:** one row per field, three columns — **Application says** /
  **Label shows** / **Result**. Column headers 10px uppercase. Values 14px; a differing
  value is `#8a1f16` 600 on the label side. Each row's Result cell holds the pill plus the
  agent-ready note (13px `#3c4855`, one formal sentence). Row background tints by verdict
  header colour: match `#eef8f0`, review `#fdf3dd`, fail `#fdeeec`.
- **Government warning row** spans the full width beneath the field rows and shows the
  warning text as it appears on the label, in `Cormorant Garamond` at label scale, so the
  header case and weight defects are visible.
- **Engine line:** mono 11px `#6c7885` — engine name, elapsed ms, prompt version.
- **Decision bar:** `Accept determination` (navy fill), `Return to applicant` (white,
  `#8a1f16` border and text), and a `Minimise` control. Minimised state and the open record
  id persist in `localStorage` and are restored on reload.
- **Accept-with-override dialog:** triggered whenever the verdict is not match. Centred
  modal, 520px, white, 1px `#d5dde5`, 24px padding, backdrop `rgba(16,21,28,0.45)`. Title
  "The AI check found differences"; body lists each disagreeing field with its note; buttons
  `Cancel` (white) and `Accept anyway` (navy). Focus-trapped, Escape cancels. The server
  enforces the same rule — `accepted` on a non-match verdict requires `override: true`.
- **Return dialog:** same shell, with an editable reason textarea prefilled with the standard
  return language.

### 5. Record store (`/store`)
- **Purpose:** read, export, import and reset the system of record — as a normal web page.
- **Layout:** action row (`Export CSV`, `Import CSV`, `Download blank template`,
  `Reset to example data`) then the full record table with the same pill vocabulary, plus
  decision, decided by, decided at, and note columns.
- **Reset** opens a confirmation dialog stating that the current store is snapshotted first.
- CSV must never be rendered as text on screen; it exists only as a download.

## Interactions and behaviour

- Verification is async and per-record: the row/button enters a busy state, the record
  resolves in place, and a toast appears bottom-centre (`toastIn`, opacity + translateY 12px,
  200ms) for 3.6s: "Verification complete — needs review on `<filename>`".
- Verify-all iterates pending records sequentially with per-record progress; one failure does
  not abort the run.
- Auto-approve: when enabled, a match verdict that passes the full eligibility test (PRD §5.3)
  sets decision `accepted`, decided by `Automatic`. Defaults to **off**.
- Transitions: 120–180ms ease-out on hover/entry; hover on buttons is `filter:
  brightness(1.12)`; no bounce, no scale.
- Errors surface inline next to the control that caused them, never as a bare alert.
- Responsive: the two-column screens stack under 900px; the queue table scrolls horizontally
  under 720px with the ID column pinned.

## State

Server state (via the API): records, filter counts, staged batches, job progress, specimen
catalogue. Local UI state: active filter, search query, expanded row, open record id,
minimised panel, modal, toast, staged form values, auto-approve toggle. Persisted locally:
open record id and minimised state only — the record store itself is server-side.

## Assets

- Fonts (Google Fonts): **Public Sans** 400/500/600/700 (UI), **IBM Plex Mono** 400/500/600
  (IDs, values, metadata), **Cormorant Garamond** 600/700 (label specimen display).
- No icon library; the few glyphs used are text or CSS shapes. Do not add illustrative SVGs.
- Label specimen images are synthetic fixtures — 25 of them, generation instructions and
  manifest in `label-image-generation-prompt.md`.
- `TTB` mark in the masthead is a 34px bordered mono monogram, not a logo file. Replace with
  the real agency asset if one exists in the target codebase.

## Files in this bundle

| File | What it is |
| --- | --- |
| `PRD.md` | Product requirements and build plan — read first. PRD §13 is the specimen manifest appendix. |
| `PRD Label Verification.dc.html` | The same PRD (v1.1) as a formatted, printable document (project root); `PRD Label Verification v1.0.dc.html` is the superseded version |
| `Label Verification.dc.html` | The approved high-fidelity prototype (design reference) |
| `support.js` | Runtime the prototype needs to open in a browser |
| `label-image-generation-prompt.md` | The prompt + spec used to generate the 25 fixture specimens (art direction, capture treatments, verbatim warning text) |
| `fixtures-manifest.csv` | **Ground truth for the 25 specimen photos** — one row per image: `id, filename, brand, class_type, alcohol, net_contents, origin, look, treatment, intended_defect`. Build `api/fixtures/expectations.json` (PRD §7) directly from this file: `intended_defect` states in prose exactly what verdict each field must resolve to under the rules in PRD §3.2, and rows marked "none — clean reference" are the auto-close-eligible set (PRD §1, §5.3). |
| `fixtures/` | Drop the 25 actual specimen image files here, named exactly as `fixtures-manifest.csv` lists them, before running the seed script or the reader benchmark. Not included in this bundle — generate them from `label-image-generation-prompt.md` or supply your own photos matching the manifest rows. |
| `sample-application.csv` | Example batch-intake CSV header and row |

## How an agent should use this bundle to build the app

1. **Read `PRD.md` end to end first.** It is the spec — domain model (§3), persistence
   schema (§4), API surface (§5), frontend routes and tokens (§6), fixtures (§7 and the §13
   appendix), non-functional requirements (§8), deployment (§9), and the M0–M7 roadmap (§10)
   with exit criteria per milestone. Build in that milestone order; do not start the reader
   layer (M3) before the rules engine (M2) is green against every fixture expectation.
2. **Open `Label Verification.dc.html` in a browser** (it is self-contained with
   `support.js` alongside it) to see the approved look, copy, states and interactions. Treat
   its HTML/CSS as the literal source of truth for colors, spacing, type and copy — read the
   file's markup directly rather than eyeballing it, and carry values into the target
   codebase's own component/styling conventions (this README's own "About the design files"
   and "Fidelity" sections above explain what to keep literal vs. what to rebuild).
3. **Use `fixtures-manifest.csv` as the ground truth for tests.** For each row, derive the
   expected field-by-field and roll-up verdict from PRD §3.2's match/review/fail rules applied
   to the `intended_defect` column, and write it into `fixtures/expectations.json`. The rules
   engine (M2) must reproduce every one of these 25 verdicts, with zero defect rows reaching
   `match`, before any model/reader code is written.
4. **Place the 25 specimen images in `fixtures/`** (generate them with
   `label-image-generation-prompt.md` if they aren't already supplied alongside this bundle),
   matching filenames to the manifest exactly — the seed script, batch sample, and named
   single-label picker all key off these filenames.
5. Follow the roadmap in PRD §10 and validate against the 20 acceptance tests in PRD §11 —
   those are the definition of done, not the prototype's visual fidelity alone.

## Suggested build order

Follow the PRD roadmap: M0 skeleton and typed contracts → M1 SQLite store, CSV mirror and
fixtures → M2 rules engine (green against all 25 fixture expectations before any model work) →
M3 reader layer plus the three-way bake-off → M4 reviewer UI to prototype parity → M5 batch
pipeline → M6 VPS deploy and cutover → M7 hardening. The rules engine and its fixture suite
are the load-bearing part: if a defect fixture ever reaches *match*, stop and fix that before
building anything else on top.
