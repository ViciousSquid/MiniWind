"""Draw the keyboard-key icons the game's hints show (assets/ui/keys).

    python game/tools/make_key_icons.py            # I and P
    python game/tools/make_key_icons.py I P E      # any letters

A flat keycap: a rounded slate square, its lower and right sides a darker
bevel, a raised face inside with a darker rim, and the letter in bold
near-white in the face's upper left. Writes ``key_<letter>.png`` (lower
case) at 256x256, drawn at 1024 and scaled down smoothly. Original art,
pure Qt; deterministic.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets" / "ui" / "keys"
SIZE = 256
WORK = 1024                      # drawn at this size, then scaled to SIZE

#: The palette (slate blue-grey, near-white letter).
CAP = "#56717d"                  # the cap's top and left
BEVEL = "#455a64"                # its lower and right sides
RIM = "#4b626d"                  # the face's rim
FACE = "#56707c"                 # the face
LETTER = "#eceff1"


def draw_key(letter: str):
    """The key for *letter* as a QImage (SIZE x SIZE, transparent outside)."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPolygonF

    s = WORK / 512.0             # the design is laid out on a 512 grid
    img = QImage(WORK, WORK, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)

    outer = QRectF(32 * s, 32 * s, 448 * s, 448 * s)
    cap = QPainterPath()
    cap.addRoundedRect(outer, 64 * s, 64 * s)
    p.setBrush(QColor(CAP))
    p.drawPath(cap)

    # The bevel: below and right of the face, cut on the diagonals from the
    # face's corners to the cap's corners -- clipped to the cap's outline.
    face = QRectF(96 * s, 80 * s, 312 * s, 312 * s)
    bevel = QPolygonF([
        QPointF(outer.left(), outer.bottom()),          # bottom-left corner
        QPointF(face.left(), face.bottom()),
        QPointF(face.right(), face.bottom()),
        QPointF(face.right(), face.top()),
        QPointF(outer.right(), outer.top()),            # top-right corner
        QPointF(outer.right(), outer.bottom()),
    ])
    path = QPainterPath()
    path.addPolygon(bevel)
    p.setBrush(QColor(BEVEL))
    p.drawPath(cap.intersected(path))

    # The face: a darker rim, the face inside it.
    rim = QPainterPath()
    rim.addRoundedRect(face, 14 * s, 14 * s)
    p.setBrush(QColor(RIM))
    p.drawPath(rim)
    inner = face.adjusted(16 * s, 16 * s, -8 * s, -8 * s)
    p.setBrush(QColor(FACE))
    p.drawRect(inner)

    # The letter: bold, its cap height filling the upper-left box.
    box = QRectF(inner.left() + 26 * s, inner.top() + 22 * s, 0, 164 * s)
    font = QFont("DejaVu Sans", 100)
    font.setBold(True)
    font.setWeight(QFont.Black)
    glyph = QPainterPath()
    glyph.addText(0, 0, font, letter.upper())
    bounds = glyph.boundingRect()
    scale = box.height() / max(1.0, bounds.height())
    p.save()
    p.translate(box.left() - bounds.left() * scale, box.top() - bounds.top() * scale)
    p.scale(scale, scale)
    p.setBrush(QColor(LETTER))
    p.drawPath(glyph)
    p.restore()
    p.end()
    return img.scaled(SIZE, SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def main(letters):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])   # fonts need an app
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for letter in letters:
        path = OUT_DIR / f"key_{letter.lower()}.png"
        if not draw_key(letter).save(str(path), "PNG"):
            raise OSError(f"could not write {path}")
        print(path.relative_to(ROOT))
    del app


if __name__ == "__main__":
    main(sys.argv[1:] or ["I", "P"])
