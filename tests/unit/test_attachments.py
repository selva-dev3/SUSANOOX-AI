from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from susanoox.models.attachments import MAX_IMAGE_BYTES, load_image_file, read_clipboard_image
from susanoox.utils.errors import AttachmentError


def make_png(path: Path) -> None:
    Image.new("RGB", (2, 2), color="magenta").save(path, format="PNG")


def test_load_image_file_validates_and_preserves_supported_image(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    make_png(image_path)

    attachment = load_image_file(image_path)

    assert attachment.filename == "screen.png"
    assert attachment.media_type == "image/png"
    assert attachment.data == image_path.read_bytes()


def test_load_image_file_rejects_invalid_content(tmp_path: Path) -> None:
    image_path = tmp_path / "fake.png"
    image_path.write_text("not an image")

    with pytest.raises(AttachmentError, match="not a valid"):
        load_image_file(image_path)


def test_load_image_file_rejects_oversized_content(tmp_path: Path) -> None:
    image_path = tmp_path / "large.png"
    image_path.write_bytes(b"0" * (MAX_IMAGE_BYTES + 1))

    with pytest.raises(AttachmentError, match="10 MB"):
        load_image_file(image_path)


def test_file_read_is_bounded_even_if_file_grows(tmp_path: Path) -> None:
    path = tmp_path / "growing.png"
    path.touch()
    requested_sizes: list[int] = []

    class GrowingFile(BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size == MAX_IMAGE_BYTES + 1
            requested_sizes.append(size)
            return b"x" * size

    with patch.object(Path, "open", return_value=GrowingFile()):
        with pytest.raises(AttachmentError, match="10 MB"):
            load_image_file(path)
    assert requested_sizes == [MAX_IMAGE_BYTES + 1]


def test_read_clipboard_image_encodes_pixels_as_png(monkeypatch: pytest.MonkeyPatch) -> None:
    image = Image.new("RGB", (2, 2), color="magenta")
    monkeypatch.setattr("susanoox.models.attachments.ImageGrab.grabclipboard", lambda: image)

    attachment = read_clipboard_image()

    assert attachment.filename == "clipboard.png"
    assert attachment.media_type == "image/png"
    assert attachment.data.startswith(b"\x89PNG")


def test_read_clipboard_image_has_actionable_empty_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("susanoox.models.attachments.ImageGrab.grabclipboard", lambda: None)

    with pytest.raises(AttachmentError, match="file path"):
        read_clipboard_image()


def test_clipboard_encoding_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    image = Image.new("RGB", (2, 2))
    monkeypatch.setattr("susanoox.models.attachments.ImageGrab.grabclipboard", lambda: image)

    def fail_save(*args: object, **kwargs: object) -> None:
        raise OSError("sensitive decoder details")

    monkeypatch.setattr(image, "save", fail_save)
    with pytest.raises(AttachmentError, match="file path") as error:
        read_clipboard_image()
    assert "sensitive" not in str(error.value)
