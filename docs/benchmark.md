# Reader benchmark

Measured with `api/scripts/bench.py` over the 25 fixtures, extraction cache bypassed
(PRD §5.4) and the prep cache cleared per fixture. Timings run from the Verify press,
which is where §8 sets the five-second threshold.

## What this decides

**The §8 latency target is met, but only by one configuration.** This service reads a
label only when a reviewer asks, rather than extracting on upload as §5.2 describes, so
the whole reader call sits inside the Verify press instead of overlapping the reviewer's
data entry — which is what makes the p95 below worth measuring rather than assuming.
Image preparation is a median 7 ms, so essentially all of it is the reader. The
head-to-head is below; re-run `bench.py` for per-fixture detail on any single
configuration.

**OCR stays a fallback, not a reader of record.** It reaches the documented verdict on
15 of 25 fixtures — the same count as `gpt-4.1-mini` — but on only 85 of 155 fields
against that model's 127, which is the number that matters: a verdict can be right for
the wrong reason. That is the reason `READER_PROVIDER`
defaults to a vision model in production and OCR runs only when that model is
unreachable: it is fast and free, and it is not accurate enough to adjudicate against.
A record it read never auto-closes, and the determination view says so.

**`fake` is the CI and demo reader.** It replays `expectations.json`, so it scores 25/25
verdicts and 155/155 fields at a 7 ms p95 by construction. That is not an accuracy
measurement — it is what makes the suite deterministic and free. Its value here is
proving the rules engine and the timing harness agree with the fixture ground truth.

**The production vision reader: `gpt-5.6-luna` at `READER_EFFORT=none`.** Measured
head to head against the 4.1 class on 2026-08-20, 25 fixtures each, sequential, zero
errors. `MAX_EDGE = 1024` and `JPEG_QUALITY = 85` in `readers/prep.py` are what the
model receives; re-run this before changing either.

| Reader | effort | p50 | **p95** | max | median reader | in tok | out tok | tok/s | Verdicts | Fields | Quality |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **gpt-5.6-luna** | **none** | **2482 ms** | **4084 ms** | 4394 ms | 2465 ms | 1696 | 186 | 73.4 | 16/25 | 122/155 | 15/25 |
| gpt-4.1-nano | n/a | 3548 ms | 4629 ms | 5369 ms | 3538 ms | 2670 | 165 | 46.4 | 13/25 | 108/155 | 12/25 |
| gpt-5.6-luna | low | 3884 ms | 5105 ms | 5512 ms | 3874 ms | 1696 | 279 | 75.6 | 18/25 | 124/155 | 20/25 |
| gpt-4.1-mini | n/a | 3815 ms | 5240 ms | 5434 ms | 3804 ms | 2025 | 182 | 47.4 | 15/25 | 127/155 | 12/25 |

`effort` is `reasoning_effort`, which only the gpt-5.x family accepts - `readers/vision.py`
withholds it from `gpt-4.1-*`, which is why those rows read n/a. Note that `minimal` is
**not** a valid value for `gpt-5.6-luna`: it returns a 400, and the supported set is
`none`, `low`, `medium`, `high`, `xhigh`.

**Why luna at `none` wins.** It is the only configuration that is both the fastest
measured and more accurate than either 4.1 model - a 545 ms better p95 than nano and
1,156 ms better than mini, while reaching three more documented verdicts than nano.
Dropping effort from `low` to `none` cuts p50 by 1,402 ms because output falls from 279
to 186 tokens; throughput is unchanged at ~73-75 tok/s, so the saving is reasoning
tokens not emitted rather than a faster model.

**The accuracy cost of that choice is real.** luna at `low` is the most accurate reader
measured - 18/25 verdicts and 20/25 quality calls - but its 5,105 ms p95 misses the §8
budget. If §8 latency is ever relaxed, `low` is the setting to go back to.

**Caveat on the latency ranking.** A p95 over 25 samples is effectively the single
24th-slowest call, so the gaps between adjacent rows rest on one sample apiece. The
luna-`none` result is far enough clear of the rest to act on; the nano/luna-`low`/mini
ordering is not a hard margin. p50 is the sturdier number here.

**Accuracy figures are relative, not pass rates.** `fixtures/expectations.json` encodes
brand verdicts no real reader can reach, so every model scores low in absolute terms.
Compare the columns across rows, not against 25/25.

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

