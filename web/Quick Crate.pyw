"""Windows launcher for the Quick Crate web version.

Double-click this file to start Quick Crate without a console window (Python from python.org runs .pyw
files with pythonw). If it's already running, this just opens the window again. The server stops by
itself about 10 seconds after you close the window. Its log is in %LOCALAPPDATA%\\Quick Crate\\server.log.
"""
import os, runpy, sys
from pathlib import Path

log_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Quick Crate"
log_dir.mkdir(parents=True, exist_ok=True)
log = open(log_dir / "server.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log  # pythonw has no console to print to

here = Path(__file__).resolve().parent
sys.argv = [str(here / "server.py")] + sys.argv[1:]
runpy.run_path(str(here / "server.py"), run_name="__main__")
