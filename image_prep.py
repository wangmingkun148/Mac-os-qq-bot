"""Shrink big images before they are uploaded to a model."""
from __future__ import annotations
import os
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:             # Pillow is only needed for resizing; without it images are sent as they are
    Image = ImageOps = None


def image_size(path):
    """(width, height) in pixels, or None when the file cannot be read as an image."""
    if Image is None:
        return None
    try:
        with Image.open(path) as picture:
            return picture.size
    except (OSError, ValueError):
        return None


def save_jpeg(source, target, max_edge, quality=85):
    """Write ``source`` to ``target`` as a JPEG whose longer side is at most ``max_edge`` pixels (None = keep size).
    Returns True on success."""
    if Image is None:
        return False
    try:
        with Image.open(source) as picture:
            picture = ImageOps.exif_transpose(picture)
            if max_edge:
                picture.thumbnail((int(max_edge), int(max_edge)), Image.LANCZOS)
            if picture.mode in ("RGBA", "LA", "P"):
                picture = picture.convert("RGBA")
                background = Image.new("RGB", picture.size, (255, 255, 255))
                background.paste(picture, mask=picture.getchannel("A"))
                picture = background
            elif picture.mode != "RGB":
                picture = picture.convert("RGB")
            picture.save(target, "JPEG", quality=quality)
        return Path(target).is_file() and Path(target).stat().st_size > 0
    except (OSError, ValueError):
        return False


def shrink_image(path, max_edge=2048):
    """Scale the file at ``path`` in place so its longer side is at most ``max_edge`` pixels (JPEG, quality 85).
    Smaller images and any failure leave the file untouched. Returns True when it was resized."""
    if not max_edge or max_edge <= 0 or not Path(path).is_file():
        return False
    size = image_size(path)
    if size is None or max(size) <= max_edge:
        return False
    target = Path(str(path) + ".small.jpg")
    try:
        if not save_jpeg(path, target, max_edge):
            return False
        os.replace(target, path)
        return True
    except OSError:
        return False
    finally:
        Path(target).unlink(missing_ok=True)
