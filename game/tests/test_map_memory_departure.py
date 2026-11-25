"""What happened in a map is remembered when the player leaves it, however soon."""
import json

from .test_corpse_loot import _Thing, _Logic
from .test_sim import _FakeGlobals


def _session(*things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(list(things)), cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    return s


def test_a_kill_made_just_before_leaving_is_remembered():
    """Deaths are noted every CHECK_SECONDS; the save made on leaving the map
    (walking into a cave mouth) notes one made since, so the victim does not
    stand up again when the player comes back out."""
    from ..map_memory import MapMemory, STORE_PREFIX
    bandit = _Thing("Bandit", (40, 0, 0), type="creature", id="bandit-1")
    s = _session(bandit)
    s.memory.load("overworld")
    s.memory.update(0.1)                      # not yet a poll's worth of time
    bandit.properties["dead"] = True          # struck down...
    s.memory.save()                           # ...and straight into the cave
    saved = json.loads(s.store.get(STORE_PREFIX + "overworld"))
    assert "bandit-1" in saved["dead"]

    fresh = _Thing("Bandit", (40, 0, 0), type="creature", id="bandit-1")
    s.logic.things = [fresh]
    back = MapMemory(s)
    back.load("overworld")
    back.apply()
    assert fresh.properties.get("dead")


def test_a_remembered_corpse_keeps_its_time_of_death():
    """Coming back to a map does not re-date the dead it laid down."""
    from ..map_memory import STORE_PREFIX
    wolf = _Thing("Wolf", (40, 0, 0), type="creature", id="wolf-1", dead=True)
    s = _session(wolf)
    s.memory.load("cave")
    s.memory.save()
    first = json.loads(s.store.get(STORE_PREFIX + "cave"))["dead"]["wolf-1"]["t"]
    s.clock.hour = (s.clock.hour + 5.0) % 24.0
    s.memory.save()
    assert json.loads(s.store.get(STORE_PREFIX + "cave"))["dead"]["wolf-1"]["t"] == first
