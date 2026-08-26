"""
Editor-side integration for the built-in MiniWind game.

MiniWind is native to this branch, so its editor affordances are wired directly
rather than through the Plugins system:

* a top-level **MiniWind** menu (placement of RPG entities + New RPG Map), and
* placement of MiniWind entities via the editor's ordinary palette (they are
  registered under a "MiniWind" category by :meth:`MiniwindGame.register`).

Typed property widgets, custom property tabs (Inventory / Dialogue / Quests) and
the ``render.overlay`` HUD are already served by the *generic* engine extension
surface — the same one plugins use — because the built-in game registers its
schemas and I/O there. Nothing MiniWind-specific needs to live in
``plugins/integration.py``.

``apply()`` is idempotent and fully guarded: any patch that cannot be installed
(e.g. a headless/tool context with no PyQt) is skipped with a log line rather
than breaking startup.
"""

from __future__ import annotations

_applied = False


def _log(message: str):
    try:
        from editor.debug_console import debug_log
        debug_log("MiniWind", message)
    except Exception:
        print(f"[MiniWind] {message}")


def apply():
    """Install MiniWind's editor integration. Safe to call more than once."""
    global _applied
    if _applied:
        return
    _applied = True
    _register_wizards()
    _patch_editor_menu()


def _register_wizards():
    """Register creation wizards for entities that need configuring up front.

    These are consumed by the editor's generic placement path (right-click
    "Add MiniWind Entity", and the MiniWind menu), so an NPC/Monster is authored
    through a guided flow instead of a wall of raw properties.
    """
    try:
        from plugins.manager import get_manager
        from . import editor_wizards
        mgr = get_manager()
        mgr.register_entity_wizard("npc", editor_wizards.npc_wizard)
        mgr.register_entity_wizard("creature", editor_wizards.creature_wizard)
    except Exception as exc:
        _log(f"wizard registration skipped ({exc})")


# ---------------------------------------------------------------------------
# editor.ui.Ui_MainWindow — top-level "MiniWind" menu-bar entry
# ---------------------------------------------------------------------------

def _patch_editor_menu():
    try:
        from editor.ui import Ui_MainWindow
    except Exception as exc:
        _log(f"menu-bar patch skipped ({exc})")
        return

    if getattr(Ui_MainWindow, "_miniwind_patched", False):
        return

    _orig_create_menu_bar = Ui_MainWindow.create_menu_bar

    def create_menu_bar(self, MainWindow):
        _orig_create_menu_bar(self, MainWindow)
        try:
            _build_sessions_menu(MainWindow)
        except Exception as exc:
            _log(f"Sessions menu build failed: {exc}")
        try:
            _add_tools_menu_entries(MainWindow)
        except Exception as exc:
            _log(f"MiniWind Tools-menu entries failed: {exc}")

    Ui_MainWindow.create_menu_bar = create_menu_bar
    Ui_MainWindow._miniwind_patched = True


def _add_tools_menu_entries(MainWindow):
    """Add MiniWind's Spell Editor to the editor's existing Tools menu."""
    tools = getattr(MainWindow, "tools_menu", None)
    if tools is None:
        return
    if getattr(tools, "_miniwind_spell_editor_added", False):
        return
    tools.addSeparator()
    act = tools.addAction("Spell Editor…")
    act.setToolTip("Edit MiniWind spell definitions — name, element, projectile "
                   "colour, damage, cost and speed.")
    act.triggered.connect(lambda _checked=False: _open_spell_editor(MainWindow))
    tools._miniwind_spell_editor_added = True


def _open_spell_editor(MainWindow):
    try:
        from . import editor_ui
        saved = editor_ui.open_spell_editor(MainWindow)
        if saved and hasattr(MainWindow, "show_toast"):
            MainWindow.show_toast("Spells saved to game/data/spells.json")
    except Exception as exc:
        _log(f"Spell Editor failed to open: {exc}")


def _build_sessions_menu(MainWindow):
    """Top-level **Sessions** menu — manage a playthrough's saved progress.

    Replaces the old "MiniWind" menu; RPG entities are still placed from the
    editor palette (MiniWind category) and the right-click "Add MiniWind Entity"
    submenu."""
    from PyQt5.QtWidgets import QMenu

    menubar = MainWindow.menuBar()

    # Don't add a second copy if the menu bar is rebuilt.
    for action in menubar.actions():
        if action.text().replace("&", "") == "Sessions":
            return

    # Insert Sessions immediately before Help (else append).
    help_action = None
    for action in menubar.actions():
        if action.text().replace("&", "") == "Help":
            help_action = action
            break

    menu = QMenu("Sessions", menubar)
    if help_action:
        menubar.insertMenu(help_action, menu)
    else:
        menubar.addMenu(menu)

    reset = menu.addAction("Reset All Progress…")
    reset.setToolTip("Erase the saved MiniWind character, inventory, quests and "
                     "world state so the next Play starts a fresh game.")
    reset.triggered.connect(lambda _checked=False: _reset_all_progress(MainWindow))


def _reset_all_progress(MainWindow):
    """Confirm, then wipe all saved MiniWind progress for a fresh start."""
    from PyQt5.QtWidgets import QMessageBox

    reply = QMessageBox.question(
        MainWindow, "Reset All Progress",
        "This erases your MiniWind character, inventory, spells, quests and "
        "world progress. This cannot be undone.\n\nReset all progress?",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    if reply != QMessageBox.Yes:
        return

    _clear_miniwind_progress(MainWindow)

    if hasattr(MainWindow, "show_toast"):
        MainWindow.show_toast("MiniWind progress reset — next Play starts a new character")
    _log("All MiniWind progress reset.")


def _clear_miniwind_progress(MainWindow):
    """Clear the persistent MiniWind key/value store and reset a live session."""
    store_names = {"miniwind"}

    # A live play session may use a map-specified store name; reset it too.
    session = _active_session(MainWindow)
    if session is not None:
        try:
            store_names.add(session.store._name)
        except Exception:
            pass

    # 1. Clear the persistent registry (editor) and the player fallback.
    for reg in _progress_registries():
        for name in store_names:
            try:
                if name in reg:
                    reg[name].clear()
            except Exception:
                pass

    # 2. Reset a session that is currently being played.
    if session is not None and hasattr(session, "reset_progress"):
        try:
            session.reset_progress()
        except Exception as exc:
            _log(f"live session reset failed: {exc}")


def _progress_registries():
    """The dict-of-dicts KV registries MiniWind persists progress into."""
    regs = []
    try:
        from editor.things import LogicKeyValueStore
        regs.append(LogicKeyValueStore._persistent_registry)
    except Exception:
        pass
    try:
        from plugins.api import GlobalStore
        regs.append(GlobalStore._fallback)
    except Exception:
        pass
    return regs


def _active_session(MainWindow):
    """The live MiniWind session if a map is being played, else None."""
    view = getattr(MainWindow, "view_3d", None)
    lt = getattr(view, "logic_thread", None) if view is not None else None
    return getattr(lt, "_miniwind", None) if lt is not None else None

