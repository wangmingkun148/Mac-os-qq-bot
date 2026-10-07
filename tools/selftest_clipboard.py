"""Developer self-test for winapp.clipboard: image + text round trips. The clipboard is saved first and restored last.

    .venv\\Scripts\\python.exe -X utf8 tools\\selftest_clipboard.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from winapp import clipboard  # noqa: E402


def main():
    saved = clipboard.save()
    print("saved formats:", [fmt for fmt, _ in saved][:8], "... total", len(saved))
    ok = True
    try:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.png"
            image = Image.new("RGB", (64, 48), (200, 30, 30))
            image.putpixel((3, 4), (10, 200, 10))
            image.save(source)
            sequence = clipboard.sequence_number()
            assert clipboard.set_image(source), "set_image failed"
            assert clipboard.sequence_number() != sequence, "sequence did not change"
            print("formats after set_image:", clipboard.formats())
            back = clipboard.read_image()
            assert back is not None, "read_image returned None"
            back = back.convert("RGB")
            print("round trip size:", back.size, "pixel:", back.getpixel((3, 4)), "corner:", back.getpixel((0, 0)))
            ok = back.size == (64, 48) and back.getpixel((3, 4)) == (10, 200, 10) and back.getpixel((0, 0)) == (200, 30, 30)
            clipboard.set_text("日本語 text ✓")
            print("text round trip:", clipboard.read_text())
            ok = ok and clipboard.read_text() == "日本語 text ✓"
    finally:
        clipboard.restore(saved)
    print("restored formats:", clipboard.formats()[:8])
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
