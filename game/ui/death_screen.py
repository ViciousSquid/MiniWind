"""
The death screen: DIED, and the way back -- the last autosave.

Dying used to end the game. Now, when there is an autosave
(:mod:`game.autosave`), the screen offers it with how long ago it was made,
and one click puts the player back there: the saved map, character and
world (:meth:`game.ui.pause_actions.PauseActions.restore_autosave`). Escape
still leaves for the editor.

The game's tick does not run while the player is dead, so the click is
carried out here on the UI thread (deferred out of the input handler), not
queued for the tick as the menus' clicks are.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QPen

from . import hits

#: The restore button as last drawn (view pixels), or None.
_button = None
#: ``(path, mtime) -> info`` of the autosave last read, so the file (which can
#: be large) is read once, not every frame.
_info_cache = (None, None)


def _actions(view):
    return getattr(getattr(view, "play_menu", None), "actions", None)


def _autosave_info(view):
    """The autosave's header and age, read once per write of the file."""
    global _info_cache
    actions = _actions(view)
    console = getattr(getattr(actions, "window", None), "console_handler", None)
    if actions is None or console is None or not hasattr(actions, "autosave_info"):
        return None
    from ..autosave import AUTOSAVE_NAME
    path = console._resolve_save_path(AUTOSAVE_NAME)
    if not os.path.exists(path):
        return None
    key = (path, os.path.getmtime(path))
    if _info_cache[0] != key:
        _info_cache = (key, actions.autosave_info())
    info = dict(_info_cache[1] or {})
    import time
    info["age"] = max(0.0, time.time() - key[1])
    return info


def _ago(seconds) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return "moments ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    return f"{hours} hour{'s' if hours != 1 else ''} ago"


def has_button() -> bool:
    return _button is not None


def draw(painter, view, w, h) -> None:
    """Paint the death screen over the frame."""
    global _button
    from . import fonts, theme as T
    T.dim_screen(painter, w, h, alpha=200)
    painter.fillRect(0, 0, w, h, QColor(90, 0, 0, 70))
    info = _autosave_info(view)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    # DIED, large, in the game's medieval face, with a dark drop shadow.
    title = QRect(0, h // 2 - 190, w, 150)
    painter.setFont(fonts.dialogue_font_px(130))
    painter.setPen(QColor(40, 0, 0, 220))
    painter.drawText(title.translated(4, 4), int(Qt.AlignCenter), "DIED")
    painter.setPen(QColor(220, 50, 40))
    painter.drawText(title, int(Qt.AlignCenter), "DIED")
    if info is not None:
        r = QRect(w // 2 - 170, h // 2 - 20, 340, 54)
        hot = hits.hovered(r)
        painter.setBrush(QColor(96, 70, 34, 245) if hot else QColor(58, 46, 30, 240))
        painter.setPen(QPen(QColor(240, 200, 110), 2 if hot else 1.4))
        painter.drawRoundedRect(r, 8, 8)
        painter.setFont(fonts.dialogue_font_px(22))
        painter.setPen(QColor(255, 236, 190))
        painter.drawText(r, int(Qt.AlignCenter), "Restore last autosave")
        detail = f"Autosaved {_ago(info.get('age', 0))}"
        if info.get("summary"):
            detail += f"  ·  {info['summary']}"
        painter.setFont(fonts.dialogue_font_px(15))
        painter.setPen(QColor(220, 200, 170))
        painter.drawText(QRect(0, r.bottom() + 8, w, 22), int(Qt.AlignCenter), detail)
        _button = r
        hint_y = r.bottom() + 40
    else:
        _button = None
        painter.setFont(fonts.dialogue_font_px(17))
        painter.setPen(QColor(220, 200, 170))
        painter.drawText(QRect(0, h // 2 - 10, w, 24), int(Qt.AlignCenter),
                         "There is no autosave yet.")
        hint_y = h // 2 + 24
    painter.setFont(fonts.dialogue_font_px(14))
    painter.setPen(QColor(180, 160, 150))
    painter.drawText(QRect(0, hint_y, w, 20), int(Qt.AlignCenter),
                     "Esc — return to the editor")
    painter.restore()


def press(view, x, y) -> bool:
    """A click on the death screen: True if it took it."""
    if _button is None or not _button.contains(QPoint(int(x), int(y))):
        return False
    actions = _actions(view)
    if actions is None or not hasattr(actions, "restore_autosave"):
        return False
    from PyQt5.QtCore import QTimer
    QTimer.singleShot(0, actions.restore_autosave)
    return True

