"""MiniWind's console commands, dispatched through Fio's console surface.

Fio calls a plugin command as ``callback(args, main_window, logic,
play_mode)``; ``game.console`` adapts that to its ``handler(ctx, args)``
form. These drive the real dispatch path of a fresh plugin manager.
"""

from plugins.api import EditorAPI
from plugins.manager import PluginManager

from .. import console


class _Window:
    def __init__(self, pick_ok=True):
        self.picks = 0
        self.toasts = []
        self._ok = pick_ok

    def begin_actor_pick(self, on_pick=None):
        self.picks += 1
        return self._ok

    def show_toast(self, text):
        self.toasts.append(text)


def _manager():
    mgr = PluginManager()
    console.register(EditorAPI(mgr, None))
    return mgr


def test_every_command_and_alias_is_registered():
    names = set(_manager().console_commands())
    assert {"diceroll", "dice", "quest", "quests", "sim", "inspect", "mind", "storyteller"} <= names


def test_a_command_receives_fios_arguments_as_its_context(monkeypatch):
    seen = []
    monkeypatch.setattr(console, "COMMANDS",
                        ((("probe",), lambda ctx, args: seen.append((ctx, args)), ""),))
    mgr = _manager()
    logic, window = object(), object()
    handled, _ = mgr.dispatch_console_command("probe", "a b", logic,
                                              main_window=window, play_mode=True)
    assert handled
    ctx, args = seen[0]
    assert (ctx.logic_thread, ctx.main_window, ctx.play_mode, args) == (logic, window, True, "a b")


def test_dice_rolls_in_the_editor():
    handled, _ = _manager().dispatch_console_command("dice", "2d1+3", None)
    assert handled


def test_inspect_arms_fios_actor_pick_in_play_mode():
    window = _Window()
    for name in ("inspect", "mind"):
        handled, _ = _manager().dispatch_console_command(
            name, "", object(), main_window=window, play_mode=True)
        assert handled
    assert window.picks == 2
    assert window.toasts and "click an actor" in window.toasts[-1]


def test_inspect_does_nothing_outside_play_mode():
    window = _Window()
    _manager().dispatch_console_command("inspect", "", None, main_window=window,
                                        play_mode=False)
    assert window.picks == 0 and window.toasts == []


def test_inspect_reports_a_view_that_cannot_pick():
    window = _Window(pick_ok=False)
    _manager().dispatch_console_command("inspect", "", object(), main_window=window,
                                        play_mode=True)
    assert window.picks == 1 and window.toasts == []


def test_pause_toggles_a_world_freeze_without_a_menu():
    from .. import console

    class _Runtime:
        def __init__(self):
            self.owners = set()

        def world_pause_owners(self):
            return frozenset(self.owners)

        def set_world_paused(self, owner, paused=True):
            (self.owners.add if paused else self.owners.discard)(owner)

    class _Logic:
        session_runtime = _Runtime()

    ctx = console.ConsoleContext(logic_thread=_Logic(), play_mode=True, main_window=None)
    console.cmd_pause(ctx, "")
    assert console.CONSOLE_PAUSE in _Logic.session_runtime.owners
    console.cmd_pause(ctx, "")
    assert not _Logic.session_runtime.owners


def test_storyteller_dispatch_opens_the_live_view(monkeypatch):
    from types import SimpleNamespace
    from .. import ui

    opened = []
    panel = SimpleNamespace(open_storyteller=lambda view: opened.append(view) or object())
    monkeypatch.setattr(ui, "storyteller_window", panel, raising=False)
    view = object()
    logic = SimpleNamespace(_miniwind=SimpleNamespace(storyteller=object()))
    handled, _ = _manager().dispatch_console_command(
        "storyteller", "", logic, main_window=SimpleNamespace(view_3d=view), play_mode=True)
    assert handled
    assert opened == [view]


def test_storyteller_reports_missing_play_session_and_view(monkeypatch):
    from types import SimpleNamespace
    from .. import ui

    messages = []
    monkeypatch.setattr(console, "debug_log", lambda _category, message: messages.append(message))
    console.cmd_storyteller(console.ConsoleContext(), "")
    assert "Play Mode only" in messages[-1]
    console.cmd_storyteller(console.ConsoleContext(play_mode=True), "")
    assert "no active MiniWind storyteller" in messages[-1]
    monkeypatch.setattr(ui, "storyteller_window", SimpleNamespace(open_storyteller=lambda view: None), raising=False)
    logic = SimpleNamespace(_miniwind=SimpleNamespace(storyteller=object()))
    console.cmd_storyteller(console.ConsoleContext(logic_thread=logic, play_mode=True), "")
    assert "no game view" in messages[-1]
