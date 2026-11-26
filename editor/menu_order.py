"""Menu order: the Debug menu reads alphabetically.

Kept apart from ``editor/ui.py`` (which pulls in the whole engine) so the game
layer can sort the menu again after adding its own entries
(``game/integration.py``).
"""

from __future__ import annotations

import re


def menu_sort_key(action) -> str:
    """An action's name for sorting: without its "&", a trailing "…" or
    "...", or a shortcut hint in brackets ("Position (Ctrl+P)")."""
    text = action.text().replace("&", "")
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    return text.rstrip(".…").strip().casefold()


def sort_menu_alphabetically(menu) -> None:
    """Put *menu*'s entries in alphabetical order; its separators go, as
    they no longer mark groups."""
    actions = [a for a in menu.actions() if not a.isSeparator()]
    for a in menu.actions():
        menu.removeAction(a)
    for a in sorted(actions, key=menu_sort_key):
        menu.addAction(a)
