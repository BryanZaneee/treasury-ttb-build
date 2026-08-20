# Reader benchmark

Measured with `api/scripts/bench.py` over the 25 fixtures, extraction cache bypassed
(PRD §5.4) and the prep cache cleared per fixture. Timings run from the Verify press,
which is where §8 sets the five-second threshold.

## What this decides

**The §8 latency target holds.** This service reads a label only when a reviewer asks
for it, rather than extracting on upload as §5.2 describes — so the whole reader call
sits inside the Verify press instead of overlapping the reviewer's data entry. That
made the p95 worth measuring rather than assuming. Local OCR comes in at **773 ms
p95**, against a 5,000 ms budget. Image preparation is a median 7 ms, so essentially
all of it is the reader.

**OCR stays a fallback, not a reader of record.** It reaches the documented verdict on
15 of 25 fixtures and gets 85 of 155 fields right. That is the reason `READER_PROVIDER`
defaults to a vision model in production and OCR runs only when that model is
unreachable: it is fast and free, and it is not accurate enough to adjudicate against.
A record it read never auto-closes, and the determination view says so.

**`fake` is the CI and demo reader.** It replays `expectations.json`, so it scores 25/25
verdicts and 155/155 fields at a 7 ms p95 by construction. That is not an accuracy
measurement — it is what makes the suite deterministic and free. Its value here is
proving the rules engine and the timing harness agree with the fixture ground truth.

**Not measured: the production vision reader.** Running `--reader openai` costs real
money per call and needs a key, so those numbers are taken on demand rather than
committed. `MAX_EDGE = 1024` and `JPEG_QUALITY = 85` in `readers/prep.py` are what the
model receives; re-run this before changing either.

## Reproducing

```bash
cd api
uv run python scripts/bench.py --reader fake
uv run python scripts/bench.py --reader ocr
uv run python scripts/bench.py --reader openai --json /tmp/openai.json   # costs money
```

## Local OCR, 25 fixtures

| Measure | Value |
| --- | --- |
| Verdict accuracy | 15/25 |
| Field accuracy | 85/155 |
| Quality calls correct | 14/25 |
| p50 total | 537 ms |
| **p95 total** | **773 ms** |
| max total | 1383 ms |
| median reader | 530 ms |
| median prep | 7 ms |

**§8 five-second p95: MET** (773 ms).

| Fixture | Verdict | Expected | Fields | Quality | prep | reader | rules | total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `abbey-row-pass.jpg` | fail ⚠ | match | 3/6 | normal | 12 | 711 | 0 | 723 |
| `blue-heron-blur.jpg` | fail ⚠ | match | 3/6 | blurry | 7 | 481 | 0 | 488 |
| `brasserie-verte-origin.jpg` | fail | fail | 4/7 | normal | 7 | 458 | 0 | 465 |
| `casa-luz-origin.jpg` | fail ⚠ | match | 3/7 | normal | 9 | 522 | 0 | 531 |
| `cedar-ridge-titlecase.jpg` | fail ⚠ | review | 2/6 | normal | 7 | 589 | 0 | 596 |
| `copper-kettle-pass.jpg` | fail ⚠ | match | 4/7 | normal | 8 | 601 | 0 | 609 |
| `ember-line-heavyblur.jpg` | fail | fail | 2/6 | heavyBlur | 6 | 271 | 0 | 277 |
| `fogbank-dark.jpg` | fail | fail | 5/6 | normal | 7 | 598 | 0 | 605 |
| `golden-hour-nonbold.jpg` | fail ⚠ | review | 3/6 | normal | 8 | 489 | 0 | 497 |
| `harbor-mist-nowarning.jpg` | fail | fail | 4/6 | normal | 8 | 436 | 0 | 444 |
| `iron-gate-blur.jpg` | fail ⚠ | match | 4/6 | blurry | 8 | 553 | 0 | 561 |
| `lark-hollow-reworded.jpg` | fail | fail | 5/6 | normal | 7 | 385 | 0 | 392 |
| `maison-clair-angled.jpg` | fail ⚠ | review | 0/7 | normal | 7 | 449 | 0 | 456 |
| `north-fen-pixel.jpg` | fail | fail | 3/6 | normal | 8 | 729 | 0 | 737 |
| `old-tom-pass.jpg` | review ⚠ | match | 5/6 | normal | 7 | 561 | 0 | 568 |
| `pilgrim-oak-damaged.jpg` | fail | fail | 4/6 | normal | 8 | 540 | 0 | 548 |
| `quarry-house-units.jpg` | fail ⚠ | review | 4/6 | normal | 7 | 468 | 0 | 475 |
| `red-kite-pixel.jpg` | fail | fail | 2/6 | normal | 8 | 569 | 0 | 577 |
| `saltmarsh-glare.jpg` | fail | fail | 3/6 | normal | 8 | 585 | 0 | 593 |
| `south-shoal-pixel.jpg` | fail | fail | 3/6 | normal | 8 | 711 | 0 | 719 |
| `stillwater-glare.jpg` | fail | fail | 3/6 | normal | 7 | 551 | 0 | 558 |
| `stones-throw-caps.jpg` | review | review | 5/6 | normal | 8 | 583 | 0 | 591 |
| `tallgrass-cropped.jpg` | fail | fail | 3/6 | normal | 7 | 455 | 0 | 463 |
| `vinos-del-sol-abv.jpg` | fail | fail | 4/7 | normal | 8 | 621 | 0 | 629 |
| `wildvine-glare.jpg` | fail | fail | 4/6 | normal | 7 | 416 | 0 | 423 |

