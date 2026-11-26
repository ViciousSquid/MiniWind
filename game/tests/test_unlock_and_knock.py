"""The console's ``unlock`` and the Knock spell open a lock the same way
(game/unlocking.py): unlock at once if locked, leave an open one alone. Knock
is readied with a hand cursor, picks a container within 64 units, and works
twice a day, saying so over the caster's head."""

from types import SimpleNamespace

import pytest

from .. import console, unlocking
from ..rpg import magic
from .test_lockpicking import _knock, _locked, _picking


def test_unlock_opens_a_locked_or_jammed_container_and_leaves_an_open_one():
    s, chest = _picking()
    s.close_lockpicking()
    assert unlocking.unlock(s, chest)
    assert not chest.properties["locked"] and "lockpick_state" not in chest.properties
    assert s.roll_log[-1]["text"] == "Unlocked!" and s.roll_log[-1]["prominent"]
    count = len(s.roll_log)
    assert not unlocking.unlock(s, chest)                    # already open: nothing
    assert len(s.roll_log) == count
    chest.properties["lock_jammed"] = True
    assert unlocking.unlock(s, chest) and not chest.properties["lock_jammed"]


def test_unlock_puts_away_the_lockpicking_on_that_container():
    s, chest = _picking()
    assert s.open_screen == "lockpicking"
    assert unlocking.unlock(s, chest)
    assert s.open_screen != "lockpicking"


def test_the_console_command_pauses_and_picks_a_container_and_unlocks_it(monkeypatch):
    s, chest = _picking()
    s.close_lockpicking()
    armed = {}

    class _Window:
        view_3d = SimpleNamespace()
        toasts = []

        def begin_actor_pick(self, on_pick=None, find=None, verb=None):
            armed.update(on_pick=on_pick, find=find, verb=verb)
            return True

        def show_toast(self, text):
            self.toasts.append(text)

    queued = []
    import game.ui.hits as hits
    monkeypatch.setattr(hits, "queue", queued.append)
    monkeypatch.setattr(unlocking, "container_at", lambda session, view, x, y: chest)
    from .. import runtime
    monkeypatch.setattr(runtime, "_current_session", s)
    window = _Window()
    console.cmd_unlock(console.ConsoleContext(None, True, window), "")
    assert armed["verb"] == "Unlock" and window.toasts
    assert armed["find"](10, 10) is chest                   # the highlight
    armed["on_pick"](chest)                                 # the click
    queued[0](s)
    assert not chest.properties["locked"]
    assert "unlock" in {n for names, _h, _d in console.COMMANDS for n in names}


def test_the_console_command_is_play_mode_only():
    window = SimpleNamespace(begin_actor_pick=lambda *a, **k: pytest.fail("armed"))
    console.cmd_unlock(console.ConsoleContext(None, False, window), "")


def _ready(s, monkeypatch):
    s.close_lockpicking()
    _knock(s)
    monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (True, {}))
    floats = []
    s.float_text = lambda thing, text, seconds=1.6, after=0.0: floats.append(text)
    return floats


def _click(s, chest):
    s._cast_cooldown = 0.0
    assert s.do_cast(aim="facing", hand="main")              # readied
    assert s.spell_aiming and s.knock_aiming
    return s.cast_at(None, container=chest)


def test_knock_is_readied_first_with_a_hand_cursor_not_a_bolt(monkeypatch):
    s, chest = _picking()
    _ready(s, monkeypatch)
    assert s.do_cast(aim="facing", hand="main")
    assert s.knock_aiming and chest.properties["locked"]
    import game.ui.hits as hits
    pointer = hits.GamePointer(SimpleNamespace(logic_thread=SimpleNamespace(_miniwind=s)))
    assert pointer.cursor_shape() == "hand" and pointer.wants_pointer()
    s.cancel_spell_aim()
    assert pointer.cursor_shape() == "arrow" and not s.knock_aiming


def test_knock_too_far_away_floats_and_keeps_the_hand_up(monkeypatch):
    s, chest = _picking()
    floats = _ready(s, monkeypatch)
    chest.pos = [unlocking.KNOCK_REACH + 10.0, 0.0, 0.0]
    assert not _click(s, chest)
    assert floats == [unlocking.TOO_FAR] and chest.properties["locked"]
    assert s.knock_aiming                                    # walk closer, click again
    assert s.knock_uses_today() == 0


def test_knock_works_twice_a_day_and_says_so(monkeypatch):
    s, chest = _picking()
    floats = _ready(s, monkeypatch)
    other = _locked()
    s.logic.things.append(other)
    assert _click(s, chest) and not chest.properties["locked"]
    assert floats[-1] == "Can only be used once more"
    assert _click(s, other) and not other.properties["locked"]
    assert floats[-1] == "Can't be used again today"
    chest.properties["locked"] = True
    s._cast_cooldown = 0.0
    assert not s.do_cast(aim="facing", hand="main")          # worked out for the day
    assert floats[-1] == "Can't be used again today" and not s.knock_aiming
    s._resurrect_day = lambda: 99                            # a new day
    assert _click(s, chest)


def test_knock_on_an_open_container_costs_nothing(monkeypatch):
    s, chest = _picking()
    _ready(s, monkeypatch)
    chest.properties["locked"] = False
    magicka = s.game.character.magicka
    assert not _click(s, chest)
    assert s.game.character.magicka == magicka and s.knock_uses_today() == 0


@pytest.mark.qt
def test_the_engine_pick_takes_a_finder_and_a_verb():
    from engine.view_picking import ViewPicking
    found = object()
    view = SimpleNamespace(play_mode=True, logic_thread=None, console_overlay_active=True,
                           update=lambda: None, _actor_pick=None, actor_pick_hover=None)
    picking = ViewPicking(view)
    got = []
    assert picking.begin_actor_pick(got.append, find=lambda x, y: found, verb="Unlock")
    picking._update_actor_pick_hover(1, 2)
    assert view.actor_pick_hover is found
    view._capture_play_cursor = lambda: None
    assert picking._click_actor_pick(1, 2) and got == [found]
