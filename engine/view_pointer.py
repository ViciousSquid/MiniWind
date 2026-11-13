"""Who owns the mouse in Play: the camera (mouse look), a game's pointer
claim, or a floating window that needs the cursor.

A game layer may claim the mouse during play (``QtGameView.game_pointer``,
duck-typed ``wants_pointer()``, ``pointer_move(ev)``, ``pointer_press(ev)``):
while it wants the pointer (an on-screen menu with things to click) the cursor
is shown and the mouse goes to it instead of the camera and the fire buttons.
Some floating windows need a free cursor for their controls too. Held by the
view as ``view.pointer``; its state stays on the view (``_game_pointer_shown``).
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from .view_pause import play_menu_open

#: Floating windows whose controls need a free cursor (the inventory strip
#: and ordinary overlays do not release the captured mouse).
CURSOR_WINDOWS = ('screen:statistics', 'screen:character', 'screen:spells',
                  'screen:trade', 'debug:tools', 'debug:pathfinding')


def _something_else_owns_the_mouse(view) -> bool:
    return (not getattr(view, 'play_mode', False)
            or getattr(view, 'console_overlay_active', False)
            or getattr(view, '_actor_pick', None) is not None
            or getattr(view, 'pause_menu', None) is not None
            or play_menu_open(view))


def game_pointer_open(view) -> bool:
    """Whether the game's pointer claim holds now (``QtGameView.game_pointer``).

    Never while something else owns the mouse: a pause menu, the console,
    an actor pick.
    """
    pointer = getattr(view, 'game_pointer', None)
    if pointer is None or _something_else_owns_the_mouse(view):
        return False
    try:
        return bool(pointer.wants_pointer())
    except Exception:
        return False


def window_wants_cursor(view) -> bool:
    """Whether a gameplay window needs a free mouse cursor (see CURSOR_WINDOWS)."""
    manager = getattr(view, 'floating_windows', None)
    if manager is None or _something_else_owns_the_mouse(view):
        return False
    return any(getattr(w, 'active', False) and getattr(w, 'wants_cursor', False)
               and getattr(w, 'key', None) in CURSOR_WINDOWS
               for w in manager.windows)


class ViewPointer:
    def __init__(self, view):
        self.view = view

    def game_pointer_open(self) -> bool:
        return game_pointer_open(self.view)

    def window_wants_cursor(self) -> bool:
        return window_wants_cursor(self.view)

    def sync(self):
        """Show the cursor while the game wants the pointer (or a floating
        window does), recapture it after."""
        view = self.view
        want = game_pointer_open(view) or window_wants_cursor(view)
        if want == view._game_pointer_shown:
            return
        view._game_pointer_shown = want
        if want:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            QApplication.setOverrideCursor(Qt.ArrowCursor)
        elif (view.play_mode and not view.console_overlay_active
              and view._actor_pick is None and view.pause_menu is None
              and not play_menu_open(view)):
            view._capture_play_cursor()

    def reset(self):
        """Leaving Play: nobody holds the pointer."""
        self.view._game_pointer_shown = False

    # -- the game's party: a pad player's screen, clicked with the mouse --------

    def _party(self):
        logic = self.view.logic_thread
        return getattr(getattr(logic, "game_session", None), "coop", None)

    def party_press(self, event) -> bool:
        """A click on a party member's open screen or conversation, when that
        member plays with a pad: it goes to the game's pointer as a press in
        their world. True when it was taken."""
        view = self.view
        party = self._party()
        if (not view.play_mode or party is None or view.pause_menu is not None
                or play_menu_open(view) or view.console_overlay_active):
            return False
        ui = party.ui_session
        if ui is None or (ui.open_screen is None and ui.dialogue is None):
            return False
        owner = party.players.get(ui.player_id)
        if (owner is None or owner.profile["device"] == "keyboard"
                or event.button() not in (Qt.LeftButton, Qt.RightButton)):
            return False
        view.game_pointer.party_world_press(event, party)
        return True

    def party_release(self, event):
        """A mouse button released in a party session: the game hears which hand."""
        party = self._party()
        if (self.view.play_mode and party is not None
                and event.button() in (Qt.LeftButton, Qt.RightButton)):
            party.mouse_hand("primary" if event.button() == Qt.LeftButton
                             else "secondary", False)

    def splitscreen_allowed(self) -> bool:
        """A party plays in one shared view: no split screen. A game may also
        turn split screen off altogether (``allows_splitscreen = False`` on
        its built-in game object)."""
        if self._party() is not None:
            return False
        try:
            from plugins.manager import get_manager
            games = list(getattr(get_manager(), "_builtin_games", ()) or ())
        except Exception:
            games = []
        return all(getattr(game, "allows_splitscreen", True) for game in games)
