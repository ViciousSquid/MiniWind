"""
A town's notice board as the top-down camera sees it:
``assets/sprites/miniwind/topdown/notice_board.png``.

A plank board on two posts with a peaked rain cap, three notes pinned to it
(one with a red wax seal), drawn with the heads' dark outline and lit from the
top left on a soft shadow, like the containers (game/tools/make_container_art.py).
The board's face is towards the bottom of the image.

Run from the repo root::

    python -m game.tools.make_notice_board_art
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join("assets", "sprites", "miniwind", "topdown", "notice_board.png")
SIZE = 256
SS = 4                                     # drawn this much larger, then reduced
OUTLINE = (38, 24, 14, 255)
WOOD = (122, 84, 50, 255)
WOOD_HI = (160, 116, 72, 255)
WOOD_LO = (88, 58, 34, 255)
CAP = (96, 62, 38, 255)
PAPER = (232, 220, 186, 255)
PAPER_LO = (200, 186, 150, 255)
INK = (70, 56, 44, 255)
WAX = (168, 40, 34, 255)


def _px(v):
    return int(round(v * SIZE * SS))


def _box(d, x0, y0, x1, y1, fill, width=0.012):
    d.rectangle([_px(x0), _px(y0), _px(x1), _px(y1)], fill=fill,
                outline=OUTLINE, width=max(1, _px(width)))


def draw() -> Image.Image:
    big = Image.new("RGBA", (SIZE * SS, SIZE * SS), (0, 0, 0, 0))
    shadow = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [_px(0.16), _px(0.30), _px(0.90), _px(0.86)], radius=_px(0.05), fill=(0, 0, 0, 90))
    big.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(_px(0.03))))
    d = ImageDraw.Draw(big)
    # Two posts, seen from above as their tops and a little of their faces.
    for x in (0.20, 0.74):
        _box(d, x, 0.62, x + 0.06, 0.84, WOOD_LO)
    # The board: three planks.
    for i, y in enumerate((0.30, 0.42, 0.54)):
        _box(d, 0.14, y, 0.86, y + 0.12, WOOD_HI if i == 0 else WOOD)
        d.line([_px(0.16), _px(y + 0.03), _px(0.84), _px(y + 0.03)],
               fill=WOOD_LO, width=_px(0.004))
    # The peaked rain cap over its top edge.
    d.polygon([(_px(0.10), _px(0.31)), (_px(0.50), _px(0.18)), (_px(0.90), _px(0.31)),
               (_px(0.90), _px(0.34)), (_px(0.10), _px(0.34))], fill=CAP, outline=OUTLINE)
    d.line([_px(0.50), _px(0.19), _px(0.50), _px(0.33)], fill=WOOD_LO, width=_px(0.006))
    # Three notes, slightly askew, with lines of writing and pins.
    notes = [(0.20, 0.37, 0.42, 0.60, -4), (0.46, 0.35, 0.66, 0.55, 3),
             (0.60, 0.48, 0.81, 0.66, -2)]
    for x0, y0, x1, y1, tilt in notes:
        note = Image.new("RGBA", (_px(x1 - x0) + 8, _px(y1 - y0) + 8), (0, 0, 0, 0))
        nd = ImageDraw.Draw(note)
        nd.rectangle([4, 4, note.width - 4, note.height - 4], fill=PAPER,
                     outline=PAPER_LO, width=_px(0.006))
        for k in range(4):
            yy = int(note.height * (0.28 + k * 0.16))
            nd.line([int(note.width * 0.18), yy, int(note.width * (0.82 - 0.1 * (k % 2))), yy],
                    fill=INK, width=_px(0.006))
        note = note.rotate(tilt, resample=Image.BICUBIC, expand=True)
        big.alpha_composite(note, (_px(x0) - 4, _px(y0) - 4))
        d.ellipse([_px((x0 + x1) / 2) - _px(0.012), _px(y0) - _px(0.006),
                   _px((x0 + x1) / 2) + _px(0.012), _px(y0) + _px(0.018)], fill=(60, 60, 66, 255))
    d.ellipse([_px(0.66), _px(0.40), _px(0.72), _px(0.46)], fill=WAX, outline=OUTLINE)
    return big.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    draw().save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
