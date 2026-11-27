"""The process-wide plugin manager must not own a closed engine session."""

import gc
import weakref

from plugins.manager import PluginManager


class _LogicTarget:
    pass


class _RetainingGame:
    name = "retaining-test-game"

    def connect(self, host):
        # Real built-in games keep their PluginHost between editor sessions.
        self.host = host


def test_retained_plugin_host_does_not_keep_logic_target_alive():
    manager = PluginManager()
    game = _RetainingGame()
    manager._builtin_games.append(game)

    target = _LogicTarget()
    target_ref = weakref.ref(target)
    manager.bind_host(target)

    # Both the manager and a built-in game retain their host objects. Neither
    # may keep the target (and therefore its editor window) alive.
    del target
    gc.collect()

    assert target_ref() is None
    assert manager._host_target() is None
    assert game.host.logic is None
    assert game.host.get("anything", "missing") == "missing"
