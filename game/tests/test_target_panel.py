"""The target panel (bottom right), criticals for everyone, "Crit!", critical
kills, and the reaper never coming for a body blown apart."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

from ..ui import target_panel as tp


def foe(name="Bandit", health=55, pos=(100.0, 0.0, 0.0), **extra):
    props = {"name": name, "health": health, "max_health": health, "npc_role": "bandit"}
    props.update(extra)
    return SimpleNamespace(pos=list(pos), properties=props)


# ------------------------------------------------------------- who it shows
def test_it_fades_in_over_a_second():
    t = tp.TargetTracker()
    bandit = foe()
    t.note(bandit, by_player=True, now=0.0)
    assert t.view(now=0.5)["alpha"] == pytest.approx(0.5)
    assert t.view(now=1.2)["alpha"] == 1.0


def test_your_own_attack_always_takes_the_panel():
    t = tp.TargetTracker()
    bandit, wolf = foe("Bandit"), foe("Wolf")
    t.note(bandit, by_player=True, now=0.0)
    t.note(wolf, by_player=True, now=0.5)
    assert t.view(now=0.6)["thing"] is wolf


def test_an_attacker_takes_it_only_once_your_target_has_gone_quiet():
    t = tp.TargetTracker()
    bandit, wolf = foe("Bandit"), foe("Wolf")
    t.note(bandit, by_player=True, now=0.0)
    t.note(wolf, by_player=False, now=1.0)              # bandit still fresh
    assert t.view(now=1.1)["thing"] is bandit
    t.note(wolf, by_player=False, now=0.0 + tp.SWITCH_QUIET_SECONDS + 0.1)
    assert t.view(now=3.0)["thing"] is wolf


def test_a_swap_while_shown_is_quick_not_a_fresh_fade():
    t = tp.TargetTracker()
    t.note(foe("Bandit"), by_player=True, now=0.0)
    t.note(foe("Wolf"), by_player=True, now=2.0)
    assert t.view(now=2.0 + tp.SWAP_SECONDS)["alpha"] == 1.0


# ---------------------------------------------------------- how it goes away
def test_no_combat_for_six_seconds_fades_it_out():
    t = tp.TargetTracker()
    t.note(foe(), by_player=True, now=0.0)
    assert t.view(now=tp.IDLE_TIMEOUT - 0.1)["alpha"] == 1.0
    assert t.view(now=tp.IDLE_TIMEOUT + 0.5)["alpha"] == pytest.approx(0.5, abs=0.02)
    assert t.view(now=tp.IDLE_TIMEOUT + tp.FADE_OUT_SECONDS + 0.1) is None


def test_killed_shows_slain_for_a_moment_then_fades():
    t = tp.TargetTracker()
    bandit = foe()
    t.note(bandit, by_player=True, now=0.0)
    bandit.properties.update(health=0, dead=True)
    v = t.view(now=2.0)
    assert v["slain"] and v["alpha"] == 1.0
    assert t.view(now=2.0 + tp.SLAIN_HOLD + tp.FADE_OUT_SECONDS / 2)["alpha"] == \
        pytest.approx(0.5, abs=0.02)
    assert t.view(now=2.0 + tp.SLAIN_HOLD + tp.FADE_OUT_SECONDS + 0.1) is None


def test_running_away_fades_it_out():
    t = tp.TargetTracker()
    bandit = foe()
    t.note(bandit, by_player=True, now=0.0)
    bandit.pos[0] = tp.FLED_DISTANCE + 500
    t.view((0.0, 0.0, 0.0), now=2.0)
    assert t.view((0.0, 0.0, 0.0), now=2.0 + tp.FADE_OUT_SECONDS + 0.1) is None


def test_the_damage_sliver_holds_then_drains():
    t = tp.TargetTracker()
    bandit = foe(health=55)
    t.note(bandit, by_player=True, now=0.0)
    t.view(now=1.0)
    bandit.properties["health"] = 34
    assert t.view(now=1.05)["ghost"] == 55
    end = 1.05 + tp.DAMAGE_DRAIN_DELAY + tp.DAMAGE_DRAIN_SECONDS + 0.01
    assert t.view(now=end)["ghost"] == 34


# ------------------------------------------------------------ where it goes
@pytest.mark.parametrize("width", [1280, 1100, 960, 800, 700])
def test_it_never_overlaps_the_shortcut_bar(qt_app, width):
    from ..ui import inventory_strip
    rects = inventory_strip.layout(9, width, 720)
    r = inventory_strip._bar_rect(rects)
    bar = (r.x(), r.y(), r.width(), r.height())
    x, y, w, compact = tp.place(width, 720, bar)
    assert x + w <= bar[0] - 1 or x >= bar[0] + bar[2] + 1          # side by side
    assert y + tp.PANEL_HEIGHT > bar[1]                             # never above it
    assert x >= 0 and x + w <= width


def test_on_a_wide_screen_the_bar_does_not_move_for_it(qt_app):
    from ..ui import inventory_strip
    r = inventory_strip._bar_rect(inventory_strip.layout(9, 1280, 720))
    assert r.x() + r.width() / 2 == pytest.approx(640, abs=2)
    assert tp.place(1280, 720, (r.x(), r.y(), r.width(), r.height()))[2] == tp.PANEL_WIDTH


def test_with_the_bar_dragged_into_its_corner_it_goes_to_the_other_side():
    width = 1280
    bar = (width - 4 - 588, 720 - 93, 588, 72)
    x, y, w, compact = tp.place(width, 720, bar)
    assert x + w <= bar[0] and not compact


def test_odds_say_what_you_need_to_hit():
    from ..rpg.character import Character
    assert tp.odds_text(Character(), {"name": "hen", "creature_role": "hen"}).startswith("To hit: ")


# ------------------------------------------------------------- criticals
def test_npcs_roll_for_criticals_the_way_the_player_does():
    from ..rpg import armour_class as ac, combat
    from ..rpg.character import Character
    c = Character()
    c.attrs["luck"] = 70
    assert ac.crit_chance({"luck": 70}) == pytest.approx(combat.critical_chance(c))
    assert ac.crit_chance({}) == pytest.approx(0.11)


def test_a_critical_against_the_player_does_more_damage():
    from ..diceroll import DiceRoller
    from ..rpg import armour_class as ac, combat
    from ..rpg.character import Character

    class Always(random.Random):
        def randint(self, a, b):
            return b                                    # every d20 a 20

    hit = combat.resolve_incoming(Character(), 10.0, dice=DiceRoller(rng=Always(0)),
                                  attack_bonus=20, rng=Always(0))
    assert hit["crit"]


def test_crit_floats_over_whoever_lands_it_and_hushes_their_speech(qt_app):
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession, CRIT_TEXT
    wolf = _Thing("Wolf", (100.0, 0.0, 0.0), type="creature", npc_role="wolf")
    s = MiniwindSession(_Logic([wolf]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    s.attack_outcome(wolf, True, crit=True)
    assert s.floats[id(wolf)][1] == CRIT_TEXT and s.shows_crit(wolf)
    from ..ui import hud
    assert hud._has_roll_box(s, wolf)                   # its bubbles give way
    s.attack_outcome(wolf, False, crit=True)            # a miss is never a crit
    assert s.floats[id(wolf)][1] == "MISS"


def test_a_critical_kill_blows_the_body_apart():
    from ..diceroll import DiceRoller
    from ..rpg.dialogue import DictStore
    from ..rpg.game_state import GameState

    class Faces(random.Random):
        def __init__(self, *f):
            super().__init__(0)
            self.f = iter(f)

        def randint(self, a, b):
            return next(self.f)

    game = GameState.new_game(DictStore(), "T", "imperial", "warrior", rng=random.Random(0))
    target = {"name": "hen", "creature_role": "hen", "health": 3, "max_health": 30}
    game.dice = DiceRoller(rng=Faces(20, 1, 20))        # hits, rolls a 1 on damage, crits
    res = game.attack_creature(target)
    assert res["killed"] and res["crit"] and res["crit_kill"]
    assert target.get("gibbed")


def test_the_reaper_never_comes_for_a_body_blown_apart(qt_app):
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(), cfg={})
    s.rng = SimpleNamespace(random=lambda: 0.0, uniform=lambda a, b: a)   # always would
    body = _Thing("Bandit", (50.0, 0.0, 0.0), dead=True, gibbed=True)
    before = len(s._reapers)
    s._maybe_send_the_reaper(body)
    assert len(s._reapers) == before


def test_a_body_blown_apart_cannot_be_resurrected(qt_app):
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    body = _Thing("Bandit", (50.0, 0.0, 0.0), type="npc", dead=True, gibbed=True, health=0)
    s = MiniwindSession(_Logic([body]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    assert s._nearest_dead_actor(500.0) is None


def test_the_health_bar_waits_for_the_damage_die():
    """The blow has landed in the rules, but the bar (and SLAIN) show the
    health as it was until the dice have told it."""
    t = tp.TargetTracker()
    bandit = foe(health=55)
    t.note(bandit, by_player=True, now=0.0)
    bandit.properties.update(health=0, dead=True)
    t.hold(bandit, 55.0, 0.9, now=2.0)
    v = t.view(now=2.5)
    assert v["health"] == 55 and not v["slain"]           # dice still rolling
    v = t.view(now=3.0)
    assert v["health"] == 0 and v["slain"]                 # told
