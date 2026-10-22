"""
The death screen: DIED, how ("Stabbed to death by Kestrel the Guard",
:mod:`game.death_causes`), and a menu of the ways back.

Dying ends this life, not the game. Under the cause the screen offers, top to
bottom:

* **Restore last autosave** -- when there is one (:mod:`game.autosave`), with
  how long ago it was made: the saved map, character and world
  (:meth:`game.ui.pause_actions.PauseActions.restore_autosave`).
* **Load game** -- the pause menu's LOAD GAME page of save slots, raised over
  the death screen (:meth:`game.ui.pause_menu.PauseMenu.open_load`); backing
  out of it returns here.
* **New game** -- character creation on a fresh start of the map
  (:meth:`~game.ui.pause_actions.PauseActions.pause_menu_new_game`).
* **Quit to desktop**.

The mouse picks one; so do Up/Down (or W/S) and Enter (or Space / E), through
:class:`DeathMenu`, which the view asks first about every key while the
player is dead. Escape does nothing here: dying never drops a player out to
the editor.

The game's tick does not run while the player is dead, so a choice is
carried out here on the UI thread (deferred out of the input handler), not
queued for the tick as the menus' clicks are.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QPen

from . import hits

#: ``(key, label)`` of every option the menu can show, top to bottom.
#: ``restore`` is left out when there is no autosave to restore.
OPTIONS = (
    ("restore", "Restore last autosave"),
    ("load", "Load game"),
    ("new", "New game"),
    ("quit", "Quit to desktop"),
)

#: ``[(key, QRect)]`` of the options as last drawn (view pixels).
_buttons = []
#: Index into :data:`_buttons` of the highlighted option.
_selected = 0
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
    return bool(_buttons)


def button(key):
    """The rectangle option *key* was last drawn in, or None."""
    for k, rect in _buttons:
        if k == key:
            return rect
    return None


def draw(painter, view, w, h) -> None:
    """Paint the death screen over the frame."""
    global _buttons, _selected
    from . import fonts, theme as T
    T.dim_screen(painter, w, h, alpha=200)
    painter.fillRect(0, 0, w, h, QColor(90, 0, 0, 70))
    info = _autosave_info(view)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    # DIED, large, in the game's medieval face, with a dark drop shadow.
    title = QRect(0, h // 2 - 250, w, 150)
    painter.setFont(fonts.dialogue_font_px(130))
    painter.setPen(QColor(40, 0, 0, 220))
    painter.drawText(title.translated(4, 4), int(Qt.AlignCenter), "DIED")
    painter.setPen(QColor(220, 50, 40))
    painter.drawText(title, int(Qt.AlignCenter), "DIED")
    # How: "Stabbed to death by Kestrel the Guard".
    session = getattr(getattr(view, "logic_thread", None), "_miniwind", None)
    cause = session.death_message() if session is not None else None
    if cause:
        line = QRect(0, title.bottom() - 6, w, 34)
        painter.setFont(fonts.dialogue_font_px(26))
        painter.setPen(QColor(30, 0, 0, 200))
        painter.drawText(line.translated(2, 2), int(Qt.AlignCenter), cause)
        painter.setPen(QColor(235, 205, 170))
        painter.drawText(line, int(Qt.AlignCenter), cause)

    # The menu: one button per way back, the autosave first when there is one.
    options = [(k, label) for k, label in OPTIONS if k != "restore" or info is not None]
    bw, bh, gap = 340, 50, 14
    y = title.bottom() + 52
    buttons = []
    for i, (key, label) in enumerate(options):
        r = QRect(w // 2 - bw // 2, y, bw, bh)
        if hits.hovered(r):
            _selected = i
        buttons.append((key, r))
        y = r.bottom() + gap
        if key == "restore":
            y += 22                   # room for the autosave's age under it
    _selected = max(0, min(_selected, len(buttons) - 1))
    for i, (key, r) in enumerate(buttons):
        hot = i == _selected
        painter.setBrush(QColor(96, 70, 34, 245) if hot else QColor(58, 46, 30, 240))
        painter.setPen(QPen(QColor(240, 200, 110), 2 if hot else 1.4))
        painter.drawRoundedRect(r, 8, 8)
        painter.setFont(fonts.dialogue_font_px(22))
        painter.setPen(QColor(255, 236, 190) if hot else QColor(225, 205, 165))
        painter.drawText(r, int(Qt.AlignCenter), dict(options)[key])
        if key == "restore":
            detail = f"Autosaved {_ago(info.get('age', 0))}"
            if info.get("summary"):
                detail += f"  ·  {info['summary']}"
            painter.setFont(fonts.dialogue_font_px(15))
            painter.setPen(QColor(220, 200, 170))
            painter.drawText(QRect(0, r.bottom() + 4, w, 22), int(Qt.AlignCenter), detail)
    _buttons = buttons
    painter.setFont(fonts.dialogue_font_px(14))
    painter.setPen(QColor(180, 160, 150))
    painter.drawText(QRect(0, y + 6, w, 20), int(Qt.AlignCenter),
                     "↑ ↓  choose    Enter  select")
    painter.restore()


def choose(view, key) -> bool:
    """Carry out option *key* ('restore', 'load', 'new' or 'quit')."""
    actions = _actions(view)
    from PyQt5.QtCore import QTimer
    if key == "load":
        menu = getattr(view, "play_menu", None)
        if menu is None or not hasattr(menu, "open_load"):
            return False
        menu.open_load()
        return True
    name = {"restore": "restore_autosave", "new": "pause_menu_new_game",
            "quit": "pause_menu_quit"}.get(key)
    fn = getattr(actions, name, None) if name else None
    if fn is None:
        return False
    QTimer.singleShot(0, fn)
    return True


def press(view, x, y) -> bool:
    """A click on the death screen: True if it took it."""
    global _selected
    point = QPoint(int(x), int(y))
    for i, (key, rect) in enumerate(_buttons):
        if rect.contains(point):
            _selected = i
            return choose(view, key)
    return False


class DeathMenu:
    """The death screen's keys, asked first by the view while the player is
    dead (``QtGameView.death_menu``)."""

    def __init__(self, view):
        self.view = view

    def _dead(self) -> bool:
        session = getattr(getattr(self.view, "logic_thread", None), "_miniwind", None)
        return bool(session is not None and session.game.character.is_dead)

    def handle_key(self, event) -> bool:
        """True when the key was the death menu's (it then did what it means)."""
        global _selected
        if not self._dead():
            return False
        key = event.key()
        if key == Qt.Key_Escape:
            return True               # nothing to back out of; never the editor
        if not _buttons:
            return False
        if key in (Qt.Key_Up, Qt.Key_W):
            _selected = (_selected - 1) % len(_buttons)
        elif key in (Qt.Key_Down, Qt.Key_S, Qt.Key_Tab):
            _selected = (_selected + 1) % len(_buttons)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_E):
            if not event.isAutoRepeat():
                choose(self.view, _buttons[max(0, min(_selected, len(_buttons) - 1))][0])
        else:
            return False
        self.view.update()
        return True
