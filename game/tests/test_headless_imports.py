"""Pure game APIs stay importable on the dependency-light runtime."""

from pathlib import Path
import subprocess
import sys

import pytest


def test_pure_game_modules_do_not_load_the_desktop_host():
    result = subprocess.run([sys.executable, "-c", """
import importlib.abc
import sys

class NoDesktop(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('PyQt5', 'OpenGL', 'PIL'):
            raise AssertionError('pure game import reached ' + fullname)

sys.meta_path.insert(0, NoDesktop())
from game.rpg import items
from game import navigation
from game.multiplayer import compatibility
assert 'game.host' not in sys.modules
import game
assert game.combat_loadout._item_style_resolver is not None
"""], cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.qt
def test_desktop_host_is_loaded_once_even_when_requested_concurrently():
    result = subprocess.run([sys.executable, "-c", """
from concurrent.futures import ThreadPoolExecutor
import sys
import game

assert 'game.host' not in sys.modules
with ThreadPoolExecutor(max_workers=4) as workers:
    hosts = list(workers.map(lambda _: game.GAME, range(16)))
assert all(host is hosts[0] for host in hosts)
assert isinstance(hosts[0], game.MiniwindGame)
assert 'game.host' in sys.modules
"""], cwd=Path(__file__).resolve().parents[2],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
