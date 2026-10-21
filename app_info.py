"""Version and where Record Book keeps its files."""

import sys
from pathlib import Path

APP_NAME = "Record Book"
VERSION = "1.1.0"

# The database, caches and crash.log live next to the program: next to record_book.py when run
# from source, next to "Record Book.exe" when packaged (PyInstaller unpacks the code itself into a
# temporary folder that is wiped on exit, so __file__ can't be used there).
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
