"""
MiniWind's display fonts.

Every ``.ttf`` / ``.otf`` in ``assets/fonts`` is registered with Qt the first
time a font is asked for, so a typeface dropped into that folder is available
by its family name.

* :func:`menu_family`: the pause menu's banner and options, **Enchanted
  Land** (Georgia if its file is missing).
* :func:`dialogue_font`: what NPCs and the player say in a conversation,
  **MedievalSharp** (SIL Open Font License, ``MedievalSharp-OFL.txt``;
  Georgia if its file is missing).
* :func:`game_family`: the readable MedievalSharp face for all game UI text,
  including older callers that still request Georgia or a sans face.
"""

from __future__ import annotations

import os

#: Resolve bundled fonts independently of the directory the game starts in.
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "fonts")

#: The pause menu's typeface, and the face used while it is not installed.
MENU_FAMILY = "Enchanted Land"
FALLBACK_FAMILY = "Georgia"

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
        from PyQt5.QtGui import QFontDatabase, QGuiApplication
        if QGuiApplication.instance() is None:
            return families          # too early: Qt cannot load fonts yet
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


#: ``(installed family set, {lowercase name: name})``: the lookup table for
#: :func:`_family`, rebuilt only when the installed set is a different one
#: (it is loaded once), not on each of the dozens of asks a HUD frame makes.
_by_lower = (None, {})


def _family(wanted, fallback):
    global _by_lower
    families = installed_families()
    if _by_lower[0] is not families:
        _by_lower = (families, {f.lower(): f for f in families})
    return _by_lower[1].get(wanted.lower(), fallback)


def menu_family() -> str:
    """The pause menu's font family: Enchanted Land if installed, else Georgia."""
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


def dialogue_font_px(pixels):
    """The conversation font at *pixels* tall, whatever the screen's DPI.

    For UI laid out in pixels (the character window): a point size grows
    with the display's DPI and scaling while the layout does not, so text
    sized in points overflows its boxes on a high-DPI screen."""
    f = dialogue_font(10)
    f.setPixelSize(max(1, int(pixels)))
    return f


def game_family(family: str) -> str:
    """Use the game's reading face, regardless of a legacy family request.

    Debug tools choose their fonts separately and never use this helper.
    """
    return dialogue_family()
