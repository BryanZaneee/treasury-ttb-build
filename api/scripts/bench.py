"""Measure a reader against the 25 fixtures (PRD §5.4).

Reports the two things that decide a production default: whether the reader
reaches the documented verdict for each fixture, and whether verification comes
in under §8's five-second p95. That p95 is measured from the Verify press,
because that is where §8 sets the threshold - and since this service reads only
when a reviewer asks (see CLAUDE.md's deviations), the model call is inside it
rather than overlapping data entry.

The extraction cache is bypassed, as §5.4 requires: a cached run measures
SQLite, not the reader.

Run by hand. `--out` writes the table alone and overwrites; the production
rationale and its head-to-head table live in the README:

    uv run python scripts/bench.py --reader fake
    uv run python scripts/bench.py --reader ocr --out /tmp/ocr.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import adjudicate
from config import settings
from models import Application
from readers import get_reader
from readers.fake import expectations
from readers.prep import prepare

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _application(expected: dict[str, Any]) -> Application:
    app = expected["app"]
    return Application(
        brand=app["brand"],
        class_type=app["classType"],
        abv=app["abv"],
        net=app["net"],
        producer=app.get("producer"),
        origin=app.get("origin"),
        warning=app.get("warning", False),
    )


def run(
    reader_name: str, model: str | None = None, effort: str | None = None
) -> list[dict[str, Any]]:
    reader = get_reader(reader_name, model, effort)
    rows: list[dict[str, Any]] = []
    for specimen, expected in sorted(expectations().items()):
        path = FIXTURES_DIR / specimen
        # Cold: the whole point is to time the reader, not the prep cache.
        prepare.cache_clear()

        started = time.perf_counter_ns()
        prep_started = time.perf_counter_ns()
        prepare(path)
        prep_ms = round((time.perf_counter_ns() - prep_started) / 1_000_000)

        try:
            reading = reader.read(specimen, path)
        except Exception as exc:  # noqa: BLE001 - a failed read is a result
            rows.append({"specimen": specimen, "error": str(exc)[:120]})
            continue
        read_done = time.perf_counter_ns()

        results, verdict = adjudicate.adjudicate(specimen, _application(expected), reading)
        finished = time.perf_counter_ns()

        # `usage` is the vision reader's last-call token count (readers/vision.py);
        # the fake and OCR readers have no such attribute and still have to bench.
        usage = getattr(reader, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0)
        out_tok = getattr(usage, "output_tokens", 0)
        reader_ms = max(0, round((read_done - started) / 1_000_000) - prep_ms)

        got = {r.field_key: r.verdict for r in results}
        want = expected["field_verdicts"]
        rows.append(
            {
                "specimen": specimen,
                "verdict": verdict,
                "expected": expected["verdict"],
                "verdict_ok": verdict == expected["verdict"],
                "fields_ok": sum(1 for k, v in want.items() if got.get(k) == v),
                "fields_total": len(want),
                "quality": reading.quality,
                "quality_ok": reading.quality == expected["quality"],
                "prep_ms": prep_ms,
                "reader_ms": reader_ms,
                "rules_ms": round((finished - read_done) / 1_000_000),
                "total_ms": round((finished - started) / 1_000_000),
                "in_tok": in_tok,
                "out_tok": out_tok,
                # Output tokens per second of reader wall-clock. On a reasoning
                # model this is a throughput proxy, not a decode rate: reasoning
                # tokens are billed as output but are not all in completion_tokens.
                "tok_s": round(out_tok / (reader_ms / 1000), 1) if reader_ms and out_tok else 0.0,
            }
        )
    return rows


def report(reader_name: str, rows: list[dict[str, Any]], model: str | None = None) -> str:
    ok = [r for r in rows if not r.get("error")]
    totals = sorted(r["total_ms"] for r in ok)

    def p(q: float) -> int:
        return totals[min(len(totals) - 1, int(len(totals) * q))] if totals else 0

    verdict_hits = sum(1 for r in ok if r["verdict_ok"])
    field_hits = sum(r["fields_ok"] for r in ok)
    field_total = sum(r["fields_total"] for r in ok)
    p95 = p(0.95)

    def med(key: str) -> float:
        vals = [r[key] for r in ok if r.get(key)]
        return round(statistics.median(vals), 1) if vals else 0.0

    lines = [
        f"# Reader benchmark — `{reader_name}`" + (f" / `{model}`" if model else ""),
        "",
        f"{len(rows)} fixtures. Extraction cache bypassed (PRD §5.4); prep cache cleared per",
        "fixture. Timings are measured from the Verify press, which is where §8 sets the",
        "five-second threshold.",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Verdict accuracy | {verdict_hits}/{len(ok)} |",
        f"| Field accuracy | {field_hits}/{field_total} |",
        f"| Quality calls correct | {sum(1 for r in ok if r['quality_ok'])}/{len(ok)} |",
        f"| p50 total | {p(0.5)} ms |",
        f"| **p95 total** | **{p95} ms** |",
        f"| max total | {totals[-1] if totals else 0} ms |",
        f"| median reader | {round(statistics.median([r['reader_ms'] for r in ok])) if ok else 0} ms |",
        f"| median prep | {round(statistics.median([r['prep_ms'] for r in ok])) if ok else 0} ms |",
        f"| median input tokens | {med('in_tok')} |",
        f"| median output tokens | {med('out_tok')} |",
        f"| median output tok/s | {med('tok_s')} |",
        f"| Errors | {len(rows) - len(ok)} |",
        "",
        # A run where every read errored has no timings at all. Reporting that
        # as "MET (0 ms)" reads as a pass, which is the opposite of the truth.
        (
            f"**§8 five-second p95: {'MET' if p95 < 5000 else 'NOT MET'}** ({p95} ms)."
            if ok
            else "**§8 five-second p95: NO DATA** - every read failed."
        ),
        "",
        (
            "| Fixture | Verdict | Expected | Fields | Quality | prep | reader | rules | total "
            "| in tok | out tok | tok/s |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(
                f"| `{r['specimen']}` | error | — | — | — | — | — | — | — | — | — | {r['error']} |"
            )
            continue
        mark = "" if r["verdict_ok"] else " ⚠"
        lines.append(
            f"| `{r['specimen']}` | {r['verdict']}{mark} | {r['expected']} | "
            f"{r['fields_ok']}/{r['fields_total']} | {r['quality']} | "
            f"{r['prep_ms']} | {r['reader_ms']} | {r['rules_ms']} | {r['total_ms']} | "
            f"{r['in_tok']} | {r['out_tok']} | {r['tok_s']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader", default="fake", help="fake | ocr | openai")
    parser.add_argument("--model", help="override READER_MODEL, e.g. gpt-5.6-luna")
    parser.add_argument("--effort", help="override READER_EFFORT, e.g. minimal")
    parser.add_argument("--out", type=Path, help="write the report here as well as stdout")
    parser.add_argument("--json", type=Path, help="write the raw rows for later comparison")
    args = parser.parse_args()

    rows = run(args.reader, args.model, args.effort)
    text = report(args.reader, rows, args.model or settings.reader_model)
    print(text)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}", file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
