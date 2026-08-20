"""Re-encode api/fixtures/ to the form the readers already receive.

`prep.prepare()` downscales to MAX_EDGE and encodes JPEG_QUALITY before the
vision reader is handed `prepared.jpeg`, so storing that output is very nearly a
no-op for the primary reader: measured over the 25 fixtures, PSNR 51-75 dB and a
mean pixel difference under 0.15/255, with no fixture crossing SHARP_FLOOR. It
takes the set from 30.7 MB to 3.6 MB.

The OCR fallback reads `prepared.image` rather than the JPEG, so its readings do
shift. That is accepted: a degraded fallback produces more human review, not
less, and OCR only runs when the vision reader is unreachable.

Run by hand when fixtures change, from api/:

    uv run python scripts/compress_fixtures.py

Output is committed. Rename the .png entries in build_fixtures.py and
fixtures-manifest.csv, then re-run build_fixtures.py so applications.csv and
expectations.json regenerate against the new names.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from readers.prep import prepare

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def main() -> None:
    before = after = 0
    for src in sorted(FIXTURES_DIR.iterdir()):
        if src.suffix.lower() not in SUFFIXES:
            continue
        jpeg = prepare(src).jpeg
        dest = src.with_suffix(".jpg")
        before += src.stat().st_size
        after += len(jpeg)
        if src != dest:
            src.unlink()
        dest.write_bytes(jpeg)
        print(f"{src.name} -> {dest.name}")
    print(f"\n{before / 1048576:.1f} MB -> {after / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
