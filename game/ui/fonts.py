"""
MiniWind's display fonts.

Every ``.ttf`` / ``.otf`` in ``assets/fonts`` is registered with Qt the first
time a font is asked for, so a typeface dropped into that folder is available
by its family name.

* :func:`menu_family`: the pause menu's banner and options, **Enchanted
  Land** (Arial if its file is missing).
* :func:`dialogue_font`: what NPCs and the player say in a conversation,
  **MedievalSharp** (SIL Open Font License, ``MedievalSharp-OFL.txt``;
  Georgia if its file is missing).
"""

from __future__ import annotations

import os

#: Where the game's font files live, relative to the working directory.
FONT_DIR = os.path.join("assets", "fonts")

#: The pause menu's typeface, and the face used while it is not installed.
MENU_FAMILY = "Enchanted Land"
FALLBACK_FAMILY = "Arial"

#: The conversation typeface, and the face used while it is not installed.
DIALOGUE_FAMILY = "MedievalSharp"
DIALOGUE_FALLBACK = "Georgia"

_families = None


def installed_families():
    """Family names of the fonts in :data:`FONT_DIR` (registered on first call)."""
    global _families
    if _families is not None:
        return _families
    families = set()
    try:
        from PyQt5.QtGui import QFontDatabase
        names = sorted(os.listdir(FONT_DIR))
    except Exception:
        names = []
    for name in names:
        if not name.lower().endswith((".ttf", ".otf")):
            continue
        try:
            font_id = QFontDatabase.addApplicationFont(os.path.join(FONT_DIR, name))
        except Exception:
            continue
        if font_id >= 0:
            families.update(QFontDatabase.applicationFontFamilies(font_id))
    _families = families
    return families


def _family(wanted, fallback):
    families = {f.lower(): f for f in installed_families()}
    return families.get(wanted.lower(), fallback)


def menu_family() -> str:
    """The pause menu's font family: Enchanted Land if installed, else Arial."""
    return _family(MENU_FAMILY, FALLBACK_FAMILY)


def dialogue_family() -> str:
    """The conversation font family: MedievalSharp if installed, else Georgia."""
    return _family(DIALOGUE_FAMILY, DIALOGUE_FALLBACK)


def dialogue_font(size):
    """A conversation font of *size* points.

    MedievalSharp has a single, upright weight, so no bold or italic is
    asked of it (Qt would fake one).
    """
    from PyQt5.QtGui import QFont
    family = dialogue_family()
    return QFont(family, int(size))
