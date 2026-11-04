"""Level-load GC policy restores collection and releases frozen worlds."""

import gc
import subprocess
import sys

import pytest

from engine import gc_control


@pytest.mark.parametrize("enabled", [True, False])
def test_nested_failed_loads_restore_the_callers_gc_state(enabled):
    previous = gc.isenabled()
    (gc.enable if enabled else gc.disable)()
    try:
        with pytest.raises(RuntimeError, match="load failed"):
            with gc_control.level_load():
                assert not gc.isenabled()
                with gc_control.level_load():
                    assert not gc.isenabled()
                assert not gc.isenabled()
                raise RuntimeError("load failed")
        assert gc.isenabled() is enabled
        assert gc_control._settings["depth"] == 0
    finally:
        (gc.enable if previous else gc.disable)()


def test_disabling_freeze_releases_cycles_from_the_loaded_world():
    # gc.freeze affects the entire interpreter, so exercise it in isolation.
    result = subprocess.run([sys.executable, "-c", """
import gc
import weakref
from engine import gc_control

class World:
    pass

world = World()
world.cycle = world
ref = weakref.ref(world)
gc_control.set_freeze(True)
with gc_control.level_load():
    pass
del world
gc.collect()
assert ref() is not None, 'the loaded world was not frozen'
gc_control.set_freeze(False)
gc.collect()
assert ref() is None, 'disabling freeze left the old world permanently alive'
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
