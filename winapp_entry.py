"""PyInstaller entry point (``python -m winapp`` does the same from source)."""
import sys

from winapp.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
