"""Write assets/hangulflow.ico from the same icon the app draws at runtime.

A Windows .ico can hold several sizes; Qt's writer stores only one, so this
packs PNG-compressed images for every size into one file (the ICO format
allows PNG entries since Windows Vista).

Run:  .venv\\Scripts\\python.exe tools\\make_icon.py
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from hangulflow import paths  # noqa: E402
from hangulflow.ui import theme  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(icon, size: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icon.pixmap(QSize(size, size)).toImage().save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - needed for fonts and pixmaps
    theme.load_bundled_fonts(paths.fonts_dir())
    icon = theme.app_icon(theme.detect_fonts().korean)
    images = [(size, png_bytes(icon, size)) for size in SIZES]

    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)

    target = ROOT / "assets" / "hangulflow.ico"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(header + entries + blobs)
    print(f"wrote {target} ({len(images)} sizes, {target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
