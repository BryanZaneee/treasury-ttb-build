"""Image preparation, shared by every reader (PRD §5.2), so a bake-off measures
the reader and not the preprocessing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

# PRD §5.2: validated against the fixtures by scripts/bench.py. If per-field
# accuracy drops, this goes back to 1600 and latency absorbs it.
MAX_EDGE = 1024
JPEG_QUALITY = 85

# Edge energy below this reads as soft: over the 25 fixtures the three blurred
# score 12.4/21.4/32.7 and the rest 35.7-62.5. Blur only; glare and angle sit in
# the clean range and need the vision reader's own call.
# ponytail: margins are 0.7 and 2.3, so recalibrate if prep or MAX_EDGE moves.
SHARP_FLOOR = 35.0


@dataclass(frozen=True)
class Prepared:
    image: Image.Image
    jpeg: bytes
    sharpness: float

    @property
    def is_sharp(self) -> bool:
        return self.sharpness >= SHARP_FLOOR


# Deterministic per file and specimens are content-addressed, so caching lets the
# caller time this stage alone (PRD §5.4) without the reader paying twice.
# ponytail: bounded LRU of decoded images; drop maxsize if memory matters more.
@lru_cache(maxsize=32)
def prepare(path: Path) -> Prepared:
    """EXIF-rotate, downscale the longest edge, encode JPEG, score sharpness."""
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)

    # Edge-energy variance: a cheap, dependency-free focus proxy.
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).stddev[0]

    return Prepared(
        image=image,
        jpeg=buffer.getvalue(),
        sharpness=sharpness,
    )
