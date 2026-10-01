"""
What the pause menu's options do (:mod:`game.ui.pause_menu`).

The menu is presentation only. This object performs its options against the
editor window that hosts play mode, on machinery the editor already has: the
console's ``save`` / ``load`` (:mod:`engine.savegame`) for the three slots,
``load_level_file()`` for a fresh start, the kiosk exit for the way back to the
editor, and :mod:`game.music` for the music switch.

A Fio save holds the *world* (entities, the player, doors, monsters). Who the
player is (the character, inventory, quests, clock and everything the
villagers remember) lives in MiniWind's key/value store instead, so every slot
also carries a copy of that store under the ``"miniwind"`` key, and loading a
slot puts it back before the session that reads it starts.
"""

from __future__ import annotations

import json
import os

from .pause_menu import SLOT_COUNT, slot_name

#: Key a pause-menu save keeps MiniWind's store under.
SAVE_KEY = "miniwind"

#: The store MiniWind keeps its progress in unless a map names another.
DEFAULT_STORE = "miniwind"


def _global_store():
    from plugins.manager import get_manager
    return get_manager().global_store


def read_slot_header(path):
    """``{'map', 'saved_at', 'summary'}`` for the save at *path*, or None.

    Only the fields the menu captions a slot with are read, so a save from an
    incompatible version still lists rather than breaking the menu.
    """
    if not os.path.exists(path):
        return None
    info = {'map': '', 'saved_at': '', 'summary': ''}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        info['map'] = data.get('map', '')
        info['saved_at'] = data.get('saved_at', '')
        info['summary'] = _summary(data.get(SAVE_KEY))
    except Exception:
        pass
    return info


def _summary(block):
    """"Name, level N" for the character in a save's MiniWind block, or ''."""
    try:
        values = (block or {}).get('values', {})
        character = json.loads(values.get('_character', ''))
        name = str(character.get('name', '')).strip()
        level = character.get('level')
        if name and level:
            return f"{name}, level {int(level)}"
        return name
    except Exception:
        return ''


class PauseActions:
    """The pause menu's options, performed on the editor window of *view*."""

    def __init__(self, view, music=None):
        self.view = view
        if music is None:
            from .. import music as _music
            music = _music.PLAYER
        self.music = music

    # ------------------------------------------------------------- plumbing
    @property
    def window(self):
        return getattr(self.view, 'editor', None)

    def _console(self):
        return getattr(self.window, 'console_handler', None)

    def _logic(self):
        return getattr(self.view, 'logic_thread', None)

    def _session(self):
        return getattr(self._logic(), '_miniwind', None)

    def _playing(self):
        return bool(getattr(self.view, 'play_mode', False))

    def _busy(self, title, stage=""):
        """The window's loading bar for a long action (a no-op without one)."""
        overlay = getattr(self.window, 'loading_overlay', None)
        if overlay is None:
            import contextlib
            return contextlib.nullcontext()
        return overlay.busy(title, stage)

    def _toast(self, message, error=False):
        toast = getattr(self.window, 'show_toast', None)
        if toast is not None:
            toast(message, is_error=error)

    def slot_path(self, slot):
        """Absolute path of save slot *slot* (1-based)."""
        return self._console()._resolve_save_path(slot_name(slot))

    # ---------------------------------------------------------------- slots
    def pause_menu_slot_info(self):
        """Header of each save slot (see :func:`read_slot_header`), None if empty."""
        return [read_slot_header(self.slot_path(slot))
                for slot in range(1, SLOT_COUNT + 1)]

    def pause_menu_save_slot(self, slot):
        """Write the live play session, and MiniWind's store, into *slot*."""
        session = self._session()
        if session is not None:
            # Flush the character and clock into the store first.
            session.persist(force=True)
        path = self.slot_path(slot)
        before = os.path.getmtime(path) if os.path.exists(path) else None
        self._console().cmd_save(slot_name(slot))
        if not os.path.exists(path) or os.path.getmtime(path) == before:
            self._toast(f"Could not save to slot {slot}.", error=True)
            return False
        store = getattr(getattr(session, 'store', None), '_name', DEFAULT_STORE)
        try:
            from engine.fileio import write_json_atomic
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            data[SAVE_KEY] = {'store': store,
                              'values': _global_store().all(store=store)}
            write_json_atomic(path, data)
        except Exception as exc:
            self._toast(f"Slot {slot}: the character was not saved ({exc}).",
                        error=True)
            return False
        self._toast(f"Saved to slot {slot}.")
        return True

    def pause_menu_load_slot(self, slot):
        """Restore *slot*: its map, then its character and world.

        The running session is stopped first (it writes itself into the store
        as it ends), the slot's store replaces that, and the console's load
        then reloads the save's map, starts play on it (the new session reads
        the character back from the store) and lays the saved world over it.
        """
        path = self.slot_path(slot)
        if not os.path.exists(path):
            self._toast(f"Slot {slot} is empty.", error=True)
            return False
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                block = json.load(fh).get(SAVE_KEY)
        except Exception as exc:
            self._toast(f"Slot {slot} cannot be read ({exc}).", error=True)
            return False
        with self._busy(f"Loading slot {slot}", "Stopping the game"):
            if isinstance(block, dict) and isinstance(block.get('values'), dict):
                if self._playing():
                    self.window._exit_play_mode()
                self._replace_store(str(block.get('store') or DEFAULT_STORE),
                                    block['values'])
            # Without a MiniWind block (a console save) the world alone is
            # restored, onto the running session as the console would.
            self._console().cmd_load(slot_name(slot))
        return True

    @staticmethod
    def _replace_store(store, values):
        globals_store = _global_store()
        for key in list(globals_store.keys(store=store)):
            globals_store.delete(key, store=store)
        for key, value in values.items():
            globals_store.set(key, value, store=store)

    # ------------------------------------------------------------- new game
    def pause_menu_new_game(self):
        """Start the map over with a new character.

        Play stops first, because a session writes itself into the store as
        it ends, which would bring the old character back. Then the progress
        is wiped, the map reloaded from disk and play started again.
        """
        window = self.window
        map_path = getattr(window, 'file_path', None)
        if not map_path:
            self._toast("No map loaded.", error=True)
            return False
        with self._busy("Starting a new game", "Stopping the game"):
            if self._playing():
                window._exit_play_mode()
            from .. import GAME
            GAME.reset_progress(window)
            if window.load_level_file(map_path) is False:
                return False
            if not self._playing():
                window.enter_play_mode()
        return True

    # ----------------------------------------------------------------- music
    def pause_menu_music_volume(self):
        """The music volume, 0..1 (0 is off)."""
        return float(self.music.effective_volume)

    def pause_menu_set_music_volume(self, volume):
        self.music.set_volume(volume)

    # ---------------------------------------------------------------- options
    def pause_menu_display_settings(self):
        """The launcher's display settings, on the editor window's own config.

        The same :class:`game.ui.launcher.DisplaySettings` the launcher uses,
        so the two can never disagree; saved through the window, whose own
        write of settings.ini then carries the change.
        """
        from .launcher import DisplaySettings
        window = self.window
        config = getattr(window, "config", None)
        if config is None:
            return DisplaySettings()
        return DisplaySettings(getattr(window, "config_path", "settings.ini"),
                               config=config,
                               save=getattr(window, "save_config", None))

    def pause_menu_apply_display(self):
        """Show a changed window mode / resolution now, in a kiosk game."""
        window = self.window
        if getattr(window, "is_kiosk_mode", False):
            apply = getattr(window, "apply_kiosk_display_mode", None)
            if apply is not None:
                apply()

    # --------------------------------------------------------------- leaving
    def pause_menu_to_editor(self):
        """Leave the game and hand the map back to the editor."""
        window = self.window
        if getattr(window, 'is_kiosk_mode', False):
            window.exit_kiosk_mode(confirm=False)
        else:
            window._exit_play_mode()

    def pause_menu_quit(self):
        """Quit to desktop."""
        from PyQt5.QtWidgets import QApplication
        self.window._exit_play_mode()
        QApplication.quit()
