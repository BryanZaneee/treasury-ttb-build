"""Image preparation, shared by every reader (PRD §5.2).

Every reader sees the *identical* prepared image, so differences in the bake-off
are attributable to the reader and not to preprocessing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

# PRD §5.2: validated against the fixture set by scripts/bench.py before it is
# fixed. If per-field accuracy drops, this moves back to 1600 and the latency
# budget absorbs it.
MAX_EDGE = 1024
JPEG_QUALITY = 85

# Edge-energy below this reads as a soft capture. Calibrated by measuring all 25
# fixtures: the three blurred ones score 12.4/21.4/32.7 and the lowest clean one
# scores 37.7, so 35 separates them with no false positive.
#
# It is worth being precise about what this does and does not buy. Sharpness is a
# *blur* detector, not a capture-quality classifier: measured across the fixture
# set, glare (44-62), pixelation (48-54), angle (45-48), dark (36), damage (51)
# and cropping (41) all sit inside the clean range of 37.7-61.6 and are simply
# invisible to it. Those treatments need the vision reader's own quality call.
# ponytail: blur-only prior, and the margin here is 2.7 points - recalibrate
# against the fixture set if the prep pipeline or MAX_EDGE ever changes.
SHARP_FLOOR = 35.0


@dataclass(frozen=True)
class Prepared:
    image: Image.Image
    jpeg: bytes
    sharpness: float
    width: int
    height: int

    @property
    def is_sharp(self) -> bool:
        return self.sharpness >= SHARP_FLOOR


# Preparation is deterministic per file, and stored specimens are
# content-addressed, so the same path never means two different images. Caching
# it lets the caller time this stage on its own (PRD §5.4 per-stage timings)
# without the reader paying for a second pass.
# ponytail: bounded LRU holding decoded images; drop maxsize if memory ever
# matters more than the repeat verify.
@lru_cache(maxsize=32)
def prepare(path: Path) -> Prepared:
    """EXIF-rotate, downscale the longest edge, encode JPEG, score sharpness."""
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)

    # Variance of edge energy - a cheap, dependency-free focus proxy. A blurred
    # or pixelated capture has far less edge energy than a crisp one.
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).stddev[0]

    return Prepared(
        image=image,
        jpeg=buffer.getvalue(),
        sharpness=sharpness,
        width=image.width,
        height=image.height,
    )
