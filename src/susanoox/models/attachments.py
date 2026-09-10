from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path
from typing import Final, Literal, cast

from PIL import Image, ImageGrab, UnidentifiedImageError

from susanoox.models.protocol import ImageAttachment
from susanoox.utils.errors import AttachmentError

MAX_IMAGE_BYTES: Final = 10 * 1024 * 1024
MAX_IMAGE_PIXELS: Final = 40_000_000
_MEDIA_TYPES: Final = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def load_image_file(path: Path) -> ImageAttachment:
    try:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise AttachmentError(f"Image file not found: {resolved}")
        with resolved.open("rb") as handle:
            data = handle.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentError("Image is larger than the 10 MB attachment limit.")
    except AttachmentError:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise AttachmentError("Unable to read the selected image file.") from error
    return _validate_image(data, filename=resolved.name)


def read_clipboard_image() -> ImageAttachment:
    """Translate failures throughout clipboard decoding and conversion."""
    try:
        return _read_clipboard_image()
    except AttachmentError:
        raise
    except (OSError, NotImplementedError, ValueError, Image.DecompressionBombError) as error:
        raise AttachmentError(
            "Could not read the clipboard image. Paste an image file path instead."
        ) from error


def _read_clipboard_image() -> ImageAttachment:
    clipboard = ImageGrab.grabclipboard()
    if isinstance(clipboard, list):
        image_path = next((Path(value) for value in clipboard if _looks_like_image(value)), None)
        if image_path is not None:
            return load_image_file(image_path)
    if isinstance(clipboard, Image.Image):
        if clipboard.width * clipboard.height > MAX_IMAGE_PIXELS:
            raise AttachmentError("Image dimensions exceed the safe processing limit.")
        output = BytesIO()
        clipboard.save(output, format="PNG", optimize=True)
        data = output.getvalue()
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentError("Clipboard image is larger than the 10 MB attachment limit.")
        return ImageAttachment(filename="clipboard.png", media_type="image/png", data=data)
    raise AttachmentError(
        "No image was found on the clipboard. Paste or drag an image file path instead."
    )


def _looks_like_image(value: str) -> bool:
    return Path(value).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _validate_image(data: bytes, *, filename: str) -> ImageAttachment:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise AttachmentError("Image dimensions exceed the safe processing limit.")
                image.verify()
    except AttachmentError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise AttachmentError("Image dimensions exceed the safe processing limit.") from error
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise AttachmentError("The selected file is not a valid supported image.") from error
    media_type = _MEDIA_TYPES.get(image_format or "")
    if media_type is None:
        raise AttachmentError("Supported image types are PNG, JPEG, GIF, and WebP.")
    return ImageAttachment(
        filename=filename,
        media_type=cast(
            Literal["image/png", "image/jpeg", "image/gif", "image/webp"],
            media_type,
        ),
        data=data,
    )
