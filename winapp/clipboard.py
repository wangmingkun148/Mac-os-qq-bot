"""Clipboard access (text, images, file lists) with save/restore, built on the Win32 API.

Everything here must run on one thread: the clipboard owner window is created lazily on the calling thread."""
from __future__ import annotations

import ctypes
import io
import struct
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

CF_TEXT, CF_BITMAP, CF_DIB, CF_UNICODETEXT, CF_HDROP, CF_DIBV5 = 1, 2, 8, 13, 15, 17
GMEM_MOVEABLE = 0x0002
HWND_MESSAGE = wintypes.HWND(-3)

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]

_owner = None
_png_format = None
STANDARD_NAMES = {CF_TEXT: "CF_TEXT", CF_BITMAP: "CF_BITMAP", CF_DIB: "CF_DIB", CF_UNICODETEXT: "CF_UNICODETEXT",
                  CF_HDROP: "CF_HDROP", CF_DIBV5: "CF_DIBV5", 7: "CF_OEMTEXT", 16: "CF_LOCALE"}


def _owner_window():
    global _owner
    if _owner is None:
        _owner = user32.CreateWindowExW(0, "STATIC", "qqbot-clipboard", 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
    return _owner


def png_format() -> int:
    global _png_format
    if _png_format is None:
        _png_format = user32.RegisterClipboardFormatW("PNG")
    return _png_format


def sequence_number() -> int:
    """Changes whenever the clipboard content changes (the Windows counterpart of NSPasteboard.changeCount)."""
    return user32.GetClipboardSequenceNumber()


class opened:
    """``with opened():`` holds the clipboard open, retrying while another program has it."""

    def __init__(self, attempts=25, delay=0.02):
        self.attempts, self.delay = attempts, delay

    def __enter__(self):
        for _ in range(self.attempts):
            if user32.OpenClipboard(_owner_window()):
                return self
            time.sleep(self.delay)
        raise OSError("clipboard is busy")

    def __exit__(self, *exc):
        user32.CloseClipboard()


def format_name(fmt: int) -> str:
    if fmt in STANDARD_NAMES:
        return STANDARD_NAMES[fmt]
    buffer = ctypes.create_unicode_buffer(128)
    if user32.GetClipboardFormatNameW(fmt, buffer, 128):
        return buffer.value
    return f"#{fmt}"


def formats() -> list[str]:
    """Names of the formats currently on the clipboard (diagnostics only)."""
    names = []
    try:
        with opened():
            fmt = 0
            while True:
                fmt = user32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                names.append(format_name(fmt))
    except OSError:
        pass
    return names


def _read_bytes(fmt: int) -> bytes | None:
    handle = user32.GetClipboardData(fmt)
    if not handle:
        return None
    size = kernel32.GlobalSize(handle)
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, size)
    finally:
        kernel32.GlobalUnlock(handle)


def _put_bytes(fmt: int, data: bytes, pad: int = 0) -> bool:
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data) + pad)
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    ctypes.memmove(pointer, data, len(data))
    if pad:
        ctypes.memset(pointer + len(data), 0, pad)
    kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(fmt, handle):
        kernel32.GlobalFree(handle)
        return False
    return True


def _dib_to_image(data: bytes) -> Image.Image:
    """A CF_DIB/CF_DIBV5 payload is a BMP file without its 14-byte file header."""
    header_size = struct.unpack_from("<I", data, 0)[0]
    bit_count = struct.unpack_from("<H", data, 14)[0]
    compression = struct.unpack_from("<I", data, 16)[0]
    colors_used = struct.unpack_from("<I", data, 32)[0]
    offset = 14 + header_size
    if compression == 3 and header_size == 40:          # BI_BITFIELDS: three colour masks follow the header
        offset += 12
    palette = (colors_used or (1 << bit_count if bit_count <= 8 else 0)) * 4
    offset += palette
    file_header = b"BM" + struct.pack("<IHHI", 14 + len(data), 0, 0, offset)
    return Image.open(io.BytesIO(file_header + data))


def read_image():
    """The picture on the clipboard as a PIL image, or None. Handles PNG, DIB/DIBV5 and copied image files."""
    with opened():
        available = set()
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            available.add(fmt)
        errors = []
        for fmt in (png_format(), CF_DIBV5, CF_DIB):
            if fmt in available:
                data = _read_bytes(fmt)
                if data:
                    try:
                        image = Image.open(io.BytesIO(data)) if fmt == png_format() else _dib_to_image(data)
                        image.load()
                        return image
                    except Exception as exc:         # try the next format
                        errors.append(f"{format_name(fmt)}: {exc}")
        if CF_HDROP in available:
            handle = user32.GetClipboardData(CF_HDROP)
            if handle:
                count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
                for index in range(count):
                    buffer = ctypes.create_unicode_buffer(1024)
                    shell32.DragQueryFileW(handle, index, buffer, 1024)
                    path = Path(buffer.value)
                    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
                        try:
                            with Image.open(path) as picture:
                                picture.load()
                                return picture.copy()
                        except Exception as exc:
                            errors.append(f"file: {exc}")
    return None


def set_image(path):
    """Replace the clipboard with the picture at ``path`` (PNG plus DIB, so any paste handler can use it)."""
    with Image.open(path) as picture:
        picture.load()
        rgb = picture.convert("RGB")
        png = io.BytesIO()
        picture.convert("RGBA" if "A" in picture.getbands() else "RGB").save(png, "PNG", optimize=False)
        bmp = io.BytesIO()
        rgb.save(bmp, "BMP")
    dib = bmp.getvalue()[14:]
    with opened():
        user32.EmptyClipboard()
        ok = _put_bytes(CF_DIB, dib)
        ok = _put_bytes(png_format(), png.getvalue()) and ok
    return ok


def set_text(text: str) -> bool:
    with opened():
        user32.EmptyClipboard()
        return _put_bytes(CF_UNICODETEXT, text.encode("utf-16-le"), pad=2)


def read_text() -> str | None:
    with opened():
        data = _read_bytes(CF_UNICODETEXT)
    if data is None:
        return None
    return data.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]


# formats that carry their data in a global memory block and can therefore be saved and put back
_SAVEABLE_STANDARD = {CF_TEXT, CF_UNICODETEXT, CF_DIB, CF_DIBV5, CF_HDROP, 7, 16}


def save() -> list[tuple[int, bytes]]:
    """Copy of the clipboard so a temporary use can be undone. Handle-based formats (bitmaps, metafiles) are
    skipped; Windows rebuilds CF_BITMAP from the saved DIB on demand."""
    items = []
    try:
        with opened():
            fmt = 0
            while True:
                fmt = user32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                if fmt in _SAVEABLE_STANDARD or fmt >= 0xC000:       # registered formats start at 0xC000
                    data = _read_bytes(fmt)
                    if data:
                        items.append((fmt, data))
    except OSError:
        pass
    return items


def restore(items: list[tuple[int, bytes]]):
    try:
        with opened():
            user32.EmptyClipboard()
            for fmt, data in items:
                _put_bytes(fmt, data)
    except OSError:
        pass
