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
            _build_miniwind_menu(MainWindow)
        except Exception as exc:
            _log(f"MiniWind menu build failed: {exc}")
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


def _build_miniwind_menu(MainWindow):
    from PyQt5.QtWidgets import QMenu, QMessageBox
    from plugins.manager import get_manager

    mgr = get_manager()
    entries = mgr.builtin_menu_entries()

    menubar = MainWindow.menuBar()

    # Insert MiniWind immediately before Help (else append).
    help_action = None
    for action in menubar.actions():
        if action.text().replace("&", "") == "Help":
            help_action = action
            break

    menu = QMenu("MiniWind", menubar)
    if help_action:
        menubar.insertMenu(help_action, menu)
    else:
        menubar.addMenu(menu)

    hdr = menu.addAction("Add RPG entity (at origin):")
    hdr.setEnabled(False)
    for _game, label, cls in entries:
        act = menu.addAction(f"   {label}")
        act.triggered.connect(
            lambda _checked=False, c=cls, l=label: _place_entity(MainWindow, c, l))
    menu.addSeparator()

    about = menu.addAction("About MiniWind…")
    about.triggered.connect(
        lambda _checked=False: QMessageBox.information(
            MainWindow, "MiniWind RPG",
            "MiniWind — a small living fantasy RPG built into this Fio branch.\n\n"
            "Place Creatures/NPCs and a Game Settings marker from this menu or "
            "the editor palette (MiniWind category), then press Play to enter "
            "the world. Game content lives in editable data files under "
            "game/data/."))


def _place_entity(MainWindow, cls, label):
    """Create a MiniWind entity at the origin and select it, running its
    creation wizard first if one is registered (same behaviour as right-click)."""
    try:
        probe = cls(pos=[0, 40, 0])
        ttype = probe.properties.get("type") if hasattr(probe, "properties") else None
        # A map may hold at most one Game Settings marker — if one already
        # exists, select it and abort rather than adding a duplicate.
        try:
            from plugins.integration import _singleton_blocked
            if _singleton_blocked(MainWindow, MainWindow.state, ttype):
                return
        except Exception:
            pass
        wiz = None
        try:
            from plugins.manager import get_manager
            wiz = get_manager().entity_wizard_for(ttype) if ttype else None
        except Exception:
            wiz = None
        if wiz is not None:
            authored = wiz(MainWindow)
            if authored is None:
                return   # cancelled
            thing = cls(pos=[0, 40, 0], properties=dict(authored))
        else:
            thing = probe
        if hasattr(MainWindow, "save_state"):
            MainWindow.save_state()
        MainWindow.state.things.append(thing)
        if hasattr(MainWindow, "set_selected_object"):
            MainWindow.set_selected_object(thing)
        if hasattr(MainWindow, "update_views"):
            MainWindow.update_views()
        if hasattr(MainWindow, "show_toast"):
            MainWindow.show_toast(f"Added {label} — drag it into place")
    except Exception as exc:
        _log(f"placement failed: {exc}")
