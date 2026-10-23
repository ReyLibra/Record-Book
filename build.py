"""Build "Record Book.exe" (a single Windows executable) with PyInstaller.

    python build.py

The exe is written next to this file, so it uses the same record_book.db, image cache and
crash.log as running from source. Build files go in build/ (safe to delete).
Needs:  pip install pyinstaller
"""

import re
import sys
from pathlib import Path

from app_info import APP_NAME, VERSION

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
ICON = BUILD / "record_book.ico"
VERSION_FILE = BUILD / "version_info.txt"


def make_icon():
    """The app's book icon (the one in the window title bar) as a Windows .ico."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(["build", "-platform", "offscreen"])
    from widgets import ACCENT, shape_icon

    icon = shape_icon("book", ACCENT, 256)
    # .ico with several sizes, so Explorer and the taskbar get a sharp one
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pngs = []
    for size in sizes:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        icon.pixmap(size, size).toImage().save(buf, "PNG")
        pngs.append(bytes(data))
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + len(sizes).to_bytes(2, "little")
    entries, offset = b"", 6 + 16 * len(sizes)
    for size, png in zip(sizes, pngs):
        dim = 0 if size == 256 else size  # 0 means 256 in the .ico format
        entries += bytes([dim, dim, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
        entries += len(png).to_bytes(4, "little") + offset.to_bytes(4, "little")
        offset += len(png)
    ICON.write_bytes(header + entries + b"".join(pngs))
    del app


def make_version_file():
    """Windows file properties (Details tab): name, version, description."""
    # Windows wants four numbers: the leading "1.2.0" of a version like "1.2.0(Unreleased)"
    numbers = re.match(r"[\d.]+", VERSION).group(0).strip(".").split(".")
    parts = [int(p) for p in numbers] + [0] * (4 - len(numbers))
    nums = ", ".join(str(p) for p in parts[:4])
    VERSION_FILE.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '{APP_NAME} - Genshin Impact character, build and DPS log'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{APP_NAME}'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


def main():
    BUILD.mkdir(exist_ok=True)
    make_icon()
    make_version_file()
    import PyInstaller.__main__

    PyInstaller.__main__.run([
        str(HERE / "record_book.py"),
        "--name", APP_NAME,
        "--onefile",
        "--windowed",  # no console window
        "--icon", str(ICON),
        "--version-file", str(VERSION_FILE),
        "--distpath", str(HERE),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--paths", str(HERE),
        "--exclude-module", "tkinter",
        "--noconfirm",
        "--clean",
    ])
    exe = HERE / f"{APP_NAME}.exe"
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1_048_576:.0f} MB), version {VERSION}")


if __name__ == "__main__":
    sys.exit(main())
