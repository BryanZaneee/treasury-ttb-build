"""Upload validation (PRD §8).

This path had no coverage at all until reviewers could upload their own labels:
every test posted `files={}`, so the write-to-disk branch never ran.
"""

import io

import pytest
from PIL import Image

import uploads


def _image(fmt: str = "PNG", size: tuple[int, int] = (40, 60), colour: str = "red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_the_three_allowed_formats_are_sniffed(fmt: str) -> None:
    assert uploads.sniff(_image(fmt)) == fmt.lower()


def test_a_text_file_renamed_to_png_is_refused() -> None:
    """The declared type and the extension are claims; the bytes are evidence."""
    with pytest.raises(uploads.UploadError, match="unsupported image format"):
        uploads.sniff(b"this is not an image, whatever it is called")


def test_a_gif_is_refused() -> None:
    with pytest.raises(uploads.UploadError, match="unsupported image format"):
        uploads.sniff(b"GIF89a" + b"\x00" * 32)


def test_a_riff_container_that_is_not_webp_is_refused() -> None:
    with pytest.raises(uploads.UploadError):
        uploads.sniff(b"RIFF\x00\x00\x00\x00WAVEfmt ")


def test_an_oversized_upload_is_refused(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    with pytest.raises(uploads.UploadError, match="maximum"):
        uploads.store(b"\x89PNG\r\n\x1a\n" + b"\x00" * uploads.MAX_BYTES, tmp_path)


def test_an_empty_upload_is_refused(tmp_path: object) -> None:
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    with pytest.raises(uploads.UploadError, match="empty"):
        uploads.store(b"", tmp_path)


def test_storage_is_content_addressed(tmp_path: object) -> None:
    """Two different labels that happen to share a name must both survive, and
    the same label twice must be one file."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    red = uploads.store(_image(colour="red"), tmp_path)
    blue = uploads.store(_image(colour="blue"), tmp_path)
    again = uploads.store(_image(colour="red"), tmp_path)

    assert red != blue, "different bytes get different keys"
    assert red == again, "identical bytes dedupe to one key"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted({red, blue})
    assert red.endswith(".png")


def test_stored_bytes_are_re_encoded(tmp_path: object) -> None:
    """Whatever was appended to the container does not survive a decode and a
    re-encode, which is the point of doing it."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    smuggled = b"<?php system($_GET[0]); ?>"
    key = uploads.store(_image() + smuggled, tmp_path)
    assert smuggled not in (tmp_path / key).read_bytes()


def test_safe_basename_strips_both_separators() -> None:
    assert uploads.safe_basename("../../etc/passwd") == "passwd"
    assert uploads.safe_basename(r"..\..\windows\evil.png") == "evil.png"
    assert uploads.safe_basename("plain.png") == "plain.png"
