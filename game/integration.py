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

import os

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
    _patch_window_title()
    _patch_map_loading()
    _patch_play_menu()


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
            _build_session_menu(MainWindow)
        except Exception as exc:
            _log(f"Session menu build failed: {exc}")
        try:
            _add_tools_menu_entries(MainWindow)
        except Exception as exc:
            _log(f"MiniWind Tools-menu entries failed: {exc}")
        # MiniWind's world comes from its settlement tools, not Fio's
        # procedural map generator: it is not offered (Tools and Terrain menus
        # share the one action).
        action = getattr(MainWindow, "procedural_action", None)
        if action is not None:
            action.setVisible(False)
            action.setEnabled(False)

    Ui_MainWindow.create_menu_bar = create_menu_bar

    # MiniWind always plays overhead (host.PLAY_CAMERA), so Fio's
    # First Person / Overhead play-camera dropdown has nothing to choose.
    _orig_create_status_bar = Ui_MainWindow.create_status_bar

    def create_status_bar(self, MainWindow):
        _orig_create_status_bar(self, MainWindow)
        try:
            _hide_camera_dropdown(MainWindow)
        except Exception as exc:
            _log(f"camera dropdown removal failed: {exc}")

    Ui_MainWindow.create_status_bar = create_status_bar
    Ui_MainWindow._miniwind_patched = True


#: settings.ini switch (Settings > Editor > Maps > "Allow Fio maps") that lets
#: the editor open plain Fio maps. Off by default: MiniWind ships game maps only.
ALLOW_FIO_MAPS = ("Editor", "allow_fio_maps")

#: What makes a map a MiniWind map: its game-settings entity.
_GAME_MAP_MARKER = b'"miniwindsettings"'


def is_game_map(path) -> bool:
    """True when the map file at *path* carries MiniWind's settings entity."""
    try:
        with open(path, "rb") as f:
            return _GAME_MAP_MARKER in f.read()
    except OSError:
        return True      # unreadable: let the editor report the real error


def fio_maps_allowed(config) -> bool:
    try:
        return config.getboolean(*ALLOW_FIO_MAPS, fallback=False)
    except Exception:
        return False


def _patch_map_loading():
    """Refuse plain Fio maps unless Settings allows them.

    Wraps ``MainWindow.load_level_file``, the one path every map open takes
    (File > Open, recent files, the maps browser, a level change in play).
    """
    try:
        from editor.main_window import MainWindow
    except Exception as exc:
        _log(f"map-loading gate skipped ({exc})")
        return
    if getattr(MainWindow, "_miniwind_maps_gated", False):
        return
    _orig_load = MainWindow.load_level_file

    def load_level_file(self, filePath):
        if not fio_maps_allowed(getattr(self, "config", None)) and not is_game_map(filePath):
            name = os.path.basename(str(filePath))
            message = (f"{name} is a plain Fio map. Turn on Settings > Editor > "
                       f"Allow Fio maps to open it.")
            _log(message)
            toast = getattr(self, "show_toast", None)
            if toast is not None:
                toast(message, is_error=True)
            return False
        return _orig_load(self, filePath)

    MainWindow.load_level_file = load_level_file
    MainWindow._miniwind_maps_gated = True


#: The editor window's product name.
WINDOW_TITLE = "MiniWind"


def _patch_window_title():
    """Title the editor window "MiniWind <map> <*>" where Fio says "Fio - <map> <*>"."""
    try:
        from editor.main_window import MainWindow
    except Exception as exc:
        _log(f"window-title patch skipped ({exc})")
        return
    if getattr(MainWindow, "_miniwind_title_patched", False):
        return
    _orig_set_title = MainWindow.setWindowTitle

    def setWindowTitle(self, title):
        _orig_set_title(self, _product_title(title))

    MainWindow.setWindowTitle = setWindowTitle
    MainWindow._miniwind_title_patched = True


def _product_title(title) -> str:
    text = str(title)
    if text == "Fio":
        return WINDOW_TITLE
    if text.startswith("Fio - "):
        return f"{WINDOW_TITLE} {text[len('Fio - '):]}"
    return text


def _hide_camera_dropdown(MainWindow):
    """Take Fio's play-camera dropdown, its "Camera:" label and the spacing in
    front of them out of the status bar.

    Hidden, not deleted: the window keeps its ``camera_mode_combobox``
    attribute, so nothing that reads it can trip over a deleted widget.
    """
    from PyQt5.QtWidgets import QLabel, QLayout

    combo = getattr(MainWindow, "camera_mode_combobox", None)
    if combo is None:
        return
    layout = next((lay for lay in MainWindow.findChildren(QLayout)
                   if lay.indexOf(combo) >= 0), None)
    if layout is None:
        combo.hide()
        return
    index = layout.indexOf(combo)
    label = layout.itemAt(index - 1).widget() if index >= 1 else None
    if isinstance(label, QLabel) and label.text().strip() == "Camera:":
        label.hide()
        spacer = layout.itemAt(index - 2) if index >= 2 else None
        if spacer is not None and spacer.spacerItem() is not None:
            layout.removeItem(spacer)
    combo.hide()


def _add_tools_menu_entries(MainWindow):
    """Add MiniWind's quest editor, spell editor, world simulation and dice test tools."""
    tools = getattr(MainWindow, "tools_menu", None)
    if tools is None:
        return

    if not getattr(tools, "_miniwind_quest_editor_added", False):
        tools.addSeparator()
        quest_action = tools.addAction("Quest Editor…")
        quest_action.setToolTip("Open the MiniWind Quest Editor (it has its own button to "
                                "launch the guided Quest Wizard)")
        quest_action.triggered.connect(lambda _checked=False: _open_quest_editor(MainWindow))
        MainWindow.quest_editor_action = quest_action
        tools._miniwind_quest_editor_added = True

    if not getattr(tools, "_miniwind_spell_editor_added", False):
        spell_action = tools.addAction("Spell Editor…")
        spell_action.setToolTip("Edit MiniWind spell definitions — name, element, projectile "
                                "colour, damage, cost and speed.")
        spell_action.triggered.connect(lambda _checked=False: _open_spell_editor(MainWindow))
        tools._miniwind_spell_editor_added = True

    if not getattr(tools, "_miniwind_world_sim_added", False):
        world_action = tools.addAction("World Simulation…")
        world_action.setToolTip(
            "Watch the living world: every actor's current intent and the "
            "reason for it, the causal history of what has happened, and a "
            "Simulate Event tool for injecting an action and seeing the "
            "simulation respond.")
        world_action.setShortcut("Ctrl+Shift+W")
        world_action.triggered.connect(
            lambda _checked=False: _open_world_sim(MainWindow))
        tools._miniwind_world_sim_added = True

    if not getattr(tools, "_miniwind_dice_test_added", False):
        dice_action = tools.addAction("Dice Roll Test…")
        dice_action.setToolTip("Roll a tabletop dice expression and print the result in "
                               "the Debug Console.")
        dice_action.triggered.connect(lambda _checked=False: _open_dice_test(MainWindow))
        tools._miniwind_dice_test_added = True



def _open_quest_editor(MainWindow):
    """Open the Quest Editor on the map's Game Settings entity.

    Quests are stored on that entity (see game/quest_editor.py), so this finds
    it and hands it to the same dialog its Quests property tab opens -- the
    editor itself, not the guided wizard, which the editor launches from its
    own 'New Quest (Wizard)' button.
    """
    from PyQt5.QtWidgets import QMessageBox
    from .entities import GameSettings
    from . import quest_editor
    state = getattr(MainWindow, "state", None)
    settings_things = [t for t in getattr(state, "things", []) or []
                       if isinstance(t, GameSettings)]
    if not settings_things:
        QMessageBox.information(
            MainWindow, "Quest Editor",
            "This map has no Game Settings entity yet — place one from the "
            "MiniWind palette first (quests are authored and stored on it).")
        return
    quest_editor.open_quest_editor(settings_things[0], parent=MainWindow)


def _open_spell_editor(MainWindow):
    try:
        from . import editor_ui
        saved = editor_ui.open_spell_editor(MainWindow)
        if saved and hasattr(MainWindow, "show_toast"):
            MainWindow.show_toast("Spells saved to game/data/spells.json")
    except Exception as exc:
        _log(f"Spell Editor failed to open: {exc}")

def _open_world_sim(MainWindow):
    """Open the World Simulation window (actors · history · simulate event)."""
    try:
        from . import sim_editor
        sim_editor.open_world_window(MainWindow)
    except Exception as exc:
        _log(f"World Simulation window failed to open: {exc}")


def _open_dice_test(MainWindow):
    """Open the dice test dialog and route each roll through the Debug Console."""
    from PyQt5.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

    dialog = QDialog(MainWindow)
    dialog.setWindowTitle("Dice Roll Test")
    dialog.setMinimumWidth(360)
    layout = QVBoxLayout(dialog)

    layout.addWidget(QLabel("Dice notation (for example: 1d20+2d6+3):"))
    notation_edit = QLineEdit("1d20")
    notation_edit.selectAll()
    layout.addWidget(notation_edit)

    options = QHBoxLayout()
    animate_check = QCheckBox("Animate")
    animate_check.setChecked(True)
    animate_check.setToolTip("Show the shake / roll / fade presentation in the game HUD.")
    options.addWidget(animate_check)
    options.addStretch()
    layout.addLayout(options)

    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    roll_button = QPushButton("Roll")
    buttons.addButton(roll_button, QDialogButtonBox.AcceptRole)
    buttons.rejected.connect(dialog.reject)
    roll_button.clicked.connect(lambda: _run_dice_test(MainWindow, notation_edit, animate_check))
    notation_edit.returnPressed.connect(roll_button.click)
    layout.addWidget(buttons)

    MainWindow._dice_test_dialog = dialog
    dialog.finished.connect(lambda _result: setattr(MainWindow, "_dice_test_dialog", None))
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def _run_dice_test(MainWindow, notation_edit, animate_check):
    """Submit one dice test to the normal console command dispatcher."""
    notation = notation_edit.text().strip() or "1d20"
    command = f"diceroll {notation}"
    if animate_check.isChecked():
        command += " --animate"
    _run_console_command(MainWindow, command)
    try:
        tab = MainWindow.properties_tab_widget
        console = MainWindow.debug_console
        index = tab.indexOf(console)
        if index >= 0:
            tab.setCurrentIndex(index)
    except Exception:
        pass


def _build_session_menu(MainWindow):
    """Top-level **Session** menu — save, load and reset a playthrough.

    RPG entities are still placed from the editor palette (MiniWind category)
    and the right-click "Add MiniWind Entity" submenu."""
    from PyQt5.QtWidgets import QMenu

    menubar = MainWindow.menuBar()

    # Don't add a second copy if the menu bar is rebuilt (accept the old name).
    for action in menubar.actions():
        if action.text().replace("&", "") in ("Session", "Sessions"):
            return

    # Insert Session immediately before Help (else append).
    help_action = None
    for action in menubar.actions():
        if action.text().replace("&", "") == "Help":
            help_action = action
            break

    menu = QMenu("Session", menubar)
    if help_action:
        menubar.insertMenu(help_action, menu)
    else:
        menubar.addMenu(menu)

    save = menu.addAction("Save Game…")
    save.setToolTip("Save the current playthrough to a slot (Play mode only).")
    save.triggered.connect(lambda _checked=False: _save_game(MainWindow))

    load = menu.addAction("Load Game…")
    load.setToolTip("Load a saved playthrough.")
    load.triggered.connect(lambda _checked=False: _load_game(MainWindow))

    menu.addSeparator()
    reset = menu.addAction("Reset All Progress…")
    reset.setToolTip("Erase the saved MiniWind character, inventory, quests and "
                     "world state so the next Play starts a fresh game.")
    reset.triggered.connect(lambda _checked=False: _reset_all_progress(MainWindow))


def _run_console_command(MainWindow, cmd):
    """Run a debug-console command (reuses save/load/… command handling)."""
    try:
        from editor.debug_console import DebugConsole
        dc = DebugConsole.get_instance()
        dc.command_input.setText(cmd)
        dc._on_command_entered()
        return True
    except Exception as exc:
        _log(f"session command '{cmd}' failed: {exc}")
        return False


def _in_play(MainWindow):
    view = getattr(MainWindow, "view_3d", None)
    return bool(view is not None and getattr(view, "play_mode", False))


def _save_game(MainWindow):
    from PyQt5.QtWidgets import QInputDialog, QMessageBox
    if not _in_play(MainWindow):
        QMessageBox.information(
            MainWindow, "Save Game",
            "Enter Play mode first — there is nothing to save in the editor.")
        return
    name, ok = QInputDialog.getText(MainWindow, "Save Game", "Save slot name:",
                                    text="save1")
    if ok and name.strip():
        _run_console_command(MainWindow, f"save {name.strip()}")


def _load_game(MainWindow):
    import os
    from PyQt5.QtWidgets import QFileDialog
    root = getattr(MainWindow, "root_dir", None) or os.getcwd()
    saves = os.path.join(root, "saves")
    path, _f = QFileDialog.getOpenFileName(MainWindow, "Load Game", saves,
                                           "MiniWind saves (*.fiosave)")
    if path:
        name = os.path.splitext(os.path.basename(path))[0]
        _run_console_command(MainWindow, f"load {name}")


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
        from editor.things import LogicState
        regs.append(LogicState._persistent_registry)
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



def _patch_play_menu():
    """Give the 3D view MiniWind's pause menu, and the music its settings.

    Fio's view keeps a ``play_menu`` slot that Escape raises during play (see
    ``QtGameView.open_play_menu``); MiniWind fills it with
    :class:`game.ui.pause_menu.PauseMenu` as each view is built, and points
    the soundtrack at the editor's settings so the music switch persists.
    """
    try:
        from engine.qt_game_view import QtGameView
    except Exception as exc:
        _log(f"pause menu skipped ({exc})")
        return
    if getattr(QtGameView, "_miniwind_play_menu", False):
        return
    _orig_init = QtGameView.__init__

    def __init__(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        try:
            install_play_menu(self)
        except Exception as exc:
            _log(f"pause menu not installed ({exc})")

    QtGameView.__init__ = __init__
    QtGameView._miniwind_play_menu = True


def install_play_menu(view):
    """Install the pause menu on *view* and configure the music from its editor."""
    from .ui.pause_actions import PauseActions
    from .ui.pause_menu import PauseMenu
    from . import music
    view.play_menu = PauseMenu(view, PauseActions(view))
    # Character creation, trading and conversations take the mouse.
    from .ui.hits import GamePointer
    view.game_pointer = GamePointer(view)
    _use_game_fonts_for_loading()
    editor = getattr(view, "editor", None)
    config = getattr(editor, "config", None)
    if config is not None:
        music.PLAYER.configure(config, getattr(editor, "save_config", None))


def _use_game_fonts_for_loading():
    """Set the loading bar in MiniWind's faces where they are installed:
    Enchanted Land for the title, MedievalSharp for the bar's text."""
    try:
        from PyQt5.QtGui import QFont
        from editor import loading_overlay
        from .ui import fonts
    except Exception:
        return
    title = fonts.menu_family()
    text = fonts.dialogue_family()
    loading_overlay.set_fonts(
        title=QFont(title, 22) if title != fonts.FALLBACK_FAMILY else None,
        bar=QFont(text, 12) if text != fonts.DIALOGUE_FALLBACK else None)
