"""Package the approved PNG into a multi-resolution ICO without extra dependencies."""
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main():
    source = QImage(str(ROOT / "assets" / "nova.png"))
    if source.isNull() or source.width() != source.height():
        raise SystemExit("Expected a readable square assets/nova.png")
    frames = []
    for size in SIZES:
        frame = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not frame.save(buffer, "PNG"):
            raise RuntimeError("Could not encode icon frame")
        frames.append(bytes(data))
    offset = 6 + 16 * len(frames)
    entries = []
    for size, frame in zip(SIZES, frames):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256,
                                   0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    icon = struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries + frames)
    (ROOT / "assets" / "nova.ico").write_bytes(icon)
    print("Created assets/nova.ico:", ", ".join(map(str, SIZES)))


if __name__ == "__main__":
    main()
