"""Validation and storage for client-supplied images (PRD §8).

Until reviewers could upload their own labels the only images on the volume
were our own fixtures, so bytes went to disk unexamined at whatever name the
client asked for. Neither assumption survives a public upload form:

  - a name is a client-supplied string, so `label.jpg` from two people is one
    file, and `old-tom-pass.png` silently replaces a fixture
  - a content type is a claim, not evidence, so the format is sniffed from the
    magic bytes and the image is re-encoded before it is stored

Storage is content-addressed. The schema already separates where an image lives
(`specimen`) from what it was called (`filename`), so the same bytes uploaded
twice are one file and two different files can share a name.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps

# PRD §8: PNG / JPEG / WebP, 12 MB maximum.
MAX_BYTES = 12 * 1024 * 1024

# Sniffed from the leading bytes; the declared content type is not consulted.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"RIFF", "webp"),  # RIFF....WEBP - the WEBP tag is checked below
)

_EXTENSION = {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}


class UploadError(ValueError):
    """The upload cannot be stored. Surfaced to the client as a 422."""


def sniff(data: bytes) -> str:
    """The image format, from the bytes rather than the filename or the
    declared content type."""
    for signature, kind in _SIGNATURES:
        if not data.startswith(signature):
            continue
        if kind == "webp" and data[8:12] != b"WEBP":
            continue
        return kind
    raise UploadError(
        "unsupported image format - upload a PNG, JPEG or WebP file"
    )


def store(data: bytes, images_dir: Path) -> str:
    """Validate, re-encode and store one image. Returns the storage key.

    Re-encoding through Pillow is what makes the sniff worth doing: whatever
    was appended to, or hidden inside, the original container does not survive
    a decode and a re-encode.
    """
    if not data:
        raise UploadError("the uploaded file is empty")
    if len(data) > MAX_BYTES:
        raise UploadError(
            f"image is {len(data) // (1024 * 1024)} MB; the maximum is "
            f"{MAX_BYTES // (1024 * 1024)} MB"
        )

    kind = sniff(data)
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
    except Exception as exc:
        raise UploadError(f"the file is not a readable image ({type(exc).__name__})") from exc

    buffer = io.BytesIO()
    if kind == "png":
        image.save(buffer, format="PNG", optimize=True)
    elif kind == "webp":
        image.save(buffer, format="WEBP", quality=90)
    else:
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
    clean = buffer.getvalue()

    key = f"{hashlib.sha256(clean).hexdigest()}{_EXTENSION[kind]}"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / key).write_bytes(clean)
    return key


def safe_basename(name: str) -> str:
    """The filename with any directory component removed.

    Handles both separators: a Windows-style `..\\..\\x.png` survives a POSIX
    rsplit untouched, which is how the batch intake was letting it through.
    """
    return Path(name.replace("\\", "/")).name
