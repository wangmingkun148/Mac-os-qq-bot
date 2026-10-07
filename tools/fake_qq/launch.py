"""Open the mock QQ in an Edge app window and keep serving until Ctrl+C:   launch.py"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import FakeQQ  # noqa: E402

EDGE = next((str(p) for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
                              Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe") if p.is_file()), "")
fake = FakeQQ()
profile = tempfile.mkdtemp(prefix="qqbot-fake-edge-")
subprocess.Popen([EDGE, f"--app={fake.url}", f"--user-data-dir={profile}", "--inprivate", "--no-first-run", "--window-size=1000,700",
                  "--window-position=60,60", "--disable-sync", "--disable-extensions", "--disable-features=msImplicitSignin,msEdgeOnRamp"])
print(fake.url, flush=True)
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
