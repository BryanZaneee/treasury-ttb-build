"""Assemble the demo batch folder for docs/demo.md.

Copies the images the demo CSV refers to out of api/fixtures/ and manufactures
the two cases you cannot get from a clean fixture set: a second image that
normalises to the same name as another (ambiguous), and an image no CSV row
claims (unused). Output is gitignored — the fixtures are already in the repo
and a second copy of them is not worth carrying.

    uv run python scripts/make_demo_batch.py

Then in the UI: Batch upload → the CSV at docs/demo/batch-demo.csv, and every
image in demo-batch/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "api" / "fixtures"
OUT = ROOT / "demo-batch"
CSV = ROOT / "docs" / "demo" / "batch-demo.csv"

# Straight copies: the CSV names these exactly, so they pair on the first pass.
EXACT = [
    "old-tom-pass.jpg",
    "harbor-mist-nowarning.jpg",
    "cedar-ridge-titlecase.jpg",
    "stones-throw-caps.jpg",
    "vinos-del-sol-abv.jpg",
]

# The CSV says saltmarsh-glare.png; the real file is .jpg. One candidate, wrong
# extension, so it pairs but is flagged for a look before commit.
FUZZY = ("saltmarsh-glare.jpg", "saltmarsh-glare.jpg")

# Two files normalising to "ember-line-heavyblur" against a CSV row that matches
# neither exactly. Nothing guesses between them; the commit blocks until a human
# picks one. Deliberately the smallest fixture, since this one is duplicated.
AMBIGUOUS = [("ember-line-heavyblur.jpg", "ember-line-heavyblur.jpg"),
             ("ember-line-heavyblur.jpg", "ember_line_heavyblur.jpg")]

# Claimed by no row: the preview reports it rather than filing it silently.
UNUSED = ("blue-heron-blur.jpg", "blue-heron-blur.jpg")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    pairs = [(n, n) for n in EXACT] + [FUZZY, *AMBIGUOUS, UNUSED]
    for src_name, dest_name in pairs:
        src = FIXTURES / src_name
        if not src.exists():
            raise SystemExit(f"missing fixture {src} - run compress_fixtures.py first")
        shutil.copy2(src, OUT / dest_name)

    shutil.copy2(CSV, OUT / "batch-demo.csv")

    print(f"{OUT}:")
    for path in sorted(OUT.iterdir()):
        print(f"  {path.name:<32} {path.stat().st_size // 1024:>5} KB")
    print(
        "\nUpload batch-demo.csv plus every image here. Expect: 5 matched, "
        "1 matched on a different extension, 1 ambiguous (blocks commit), "
        "1 missing its image, 1 unused image."
    )


if __name__ == "__main__":
    main()
