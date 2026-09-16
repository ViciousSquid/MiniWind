"""Console commands registered through the plugin API (API 1.4.0).

``editor.console_commands`` asks the plugin manager for any command its own
table does not answer. A game layer (MiniWind's diceroll / quest / sim)
registers through ``EditorAPI.register_console_command``.
"""

import types

from plugins.api import ConsoleContext, EditorAPI
from plugins.manager import PluginManager


def _manager_with(owner=None):
    mgr = PluginManager()
    api = EditorAPI(mgr, owner)
    return mgr, api


def test_a_registered_command_is_dispatched_with_its_context():
    mgr, api = _manager_with()
    seen = []

    def handler(ctx, args):
        seen.append((ctx, args))
        return "rolled " + args

    api.register_console_command("Dice", handler, "roll dice")
    logic, window = object(), object()
    handled, reply = mgr.dispatch_console_command(
        "dice", "2d6", logic, play_mode=True, main_window=window)

    assert handled is True and reply == "rolled 2d6"
    ctx, args = seen[0]
    assert isinstance(ctx, ConsoleContext)
    assert (ctx.logic_thread, ctx.play_mode, ctx.main_window) == (logic, True, window)
    assert mgr.has_console_command("DICE")
    assert ("dice", "roll dice") in mgr.console_commands()


def test_an_unknown_command_is_not_handled():
    mgr, _ = _manager_with()
    assert mgr.dispatch_console_command("nope", "", None) == (False, None)
    assert not mgr.has_console_command("nope")


def test_a_failing_handler_is_still_handled():
    mgr, api = _manager_with()

    def boom(ctx, args):
        raise RuntimeError("bad roll")

    api.register_console_command("boom", boom)
    assert mgr.dispatch_console_command("boom", "", None) == (True, None)


def test_a_builtin_game_owners_commands_are_always_active():
    game = types.SimpleNamespace(name="game", is_builtin_game=True)
    mgr, api = _manager_with(game)
    api.register_console_command("quest", lambda ctx, args: "ok")
    assert mgr.has_console_command("quest")


def test_miniwind_registers_its_commands():
    mgr, api = _manager_with()
    from game import console
    console.register(api)
    names = {name for name, _ in mgr.console_commands()}
    assert {"diceroll", "dice", "quest", "quests", "sim"} <= names
