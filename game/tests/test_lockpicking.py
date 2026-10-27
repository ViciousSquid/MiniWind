"""Lock progress, real resource losses and the Knock-only jam exception."""
import json
from types import SimpleNamespace

import pytest

from ..rpg.lockpicking import LOCKS, LockpickAttempt, shear_chance
from ..rpg import inventory as inv, items, magic, skills
from .test_corpse_loot import _Thing, _Logic
from .test_sim import _FakeGlobals


def _locked(**props):
    return _Thing("Old lockbox", (40, 0, 0), type="container", locked=True,
                  inventory=[items.make("gold", 30)], **props)


def _picking(chest=None, skill=25, picks=3):
    chest = chest or _locked()
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic([chest]), cfg={}, globals_store=_FakeGlobals())
    s.game.dice = None
    s.needs_char_creation = False
    s.game.character.skills[skills.SECURITY] = skill
    s.game.character.inventory = [items.make("lockpick", picks)] if picks else []
    s.open_container(chest)
    return s, chest


def _set_pin(a):
    a.set_tension(True)
    for _ in range(100):
        a.angle = a.target
        event = a.tick(.02)
        if event:
            return event
    pytest.fail("A tracked pin never latched")


@pytest.mark.parametrize("difficulty", LOCKS)
@pytest.mark.parametrize("skill", [0, 15, 100])
def test_any_lock_can_be_opened_by_control_without_a_random_success_roll(difficulty, skill):
    a = LockpickAttempt(difficulty, skill, "test")
    for pin in range(a.lock.pins):
        assert _set_pin(a) == ("unlocked" if pin == a.lock.pins - 1 else "pin_set")
        assert a.pins_set == pin + 1
        assert not a.tension
    assert a.complete


def test_binding_requires_tracking_on_a_master_lock_at_low_skill():
    a = LockpickAttempt("master", 0, "hard")
    a.angle = a.target
    a.set_tension(True)
    for _ in range(100):
        a.tick(.02)
    assert a.pins_set == 0
    assert 0 < a.turn < 1
    assert not a.aligned
    expert = LockpickAttempt("master", 100, "hard")
    assert expert.tolerance > a.tolerance * 3
    assert shear_chance(15) == 0
    assert shear_chance(0) == .25


def test_release_recovers_strain_and_never_resets_pins_or_partial_turn():
    a = LockpickAttempt(seed="stable")
    _set_pin(a)
    a.angle = a.target
    a.set_tension(True)
    a.tick(.1)
    partial = a.turn
    a.angle = 80 if a.target < 0 else -80
    for _ in range(25):
        assert a.tick(.1) is None
    assert a.strain > 0
    a.set_tension(False)
    for _ in range(30):
        a.tick(.1)
    assert a.strain == 0
    assert a.pins_set == 1 and a.turn == partial
    restored = LockpickAttempt(seed="stable", saved=json.loads(json.dumps(a.snapshot())))
    assert restored.pins_set == 1 and restored.turn == partial
    assert restored.targets == a.targets
    assert not restored.tension


def test_breaks_only_after_sustained_overload_and_never_from_a_stalled_frame():
    a = LockpickAttempt(seed="break")
    a.angle = 80 if a.target < 0 else -80
    a.set_tension(True)
    assert a.tick(120) is None
    assert a.strain == 0
    for _ in range(100):
        event = a.tick(.1)
        if event:
            break
    assert event == "pick_broke"
    assert not a.tension
    assert a.feedback_time > 0
    assert a.tick(.1) is None


def test_mouse_resistance_is_stronger_when_binding_and_freely_releases():
    a = LockpickAttempt(seed="mouse")
    a.angle = -70
    a.set_tension(False)
    a.move(10, mouse=True)
    free = a.angle + 70
    a.angle = -70 if a.target > 0 else 70
    before = a.angle
    a.set_tension(True)
    a.move(10, mouse=True)
    assert 0 < a.angle - before < free
    a.set_tension(False)
    before = a.angle
    a.move(-10, mouse=True)
    assert a.angle == before - 10


@pytest.mark.parametrize("saved", [None, [], {"signature": "wrong"}, {"angle": "bad"}])
def test_unrelated_or_bad_saved_progress_does_not_poison_a_lock(saved):
    a = LockpickAttempt(seed="save", saved=saved)
    assert a.pins_set == 0 and a.angle == 0


def test_locked_inventory_is_inaccessible_until_the_minigame_is_won():
    s, chest = _picking()
    assert s.open_screen == "lockpicking"
    assert s.container_inventory() == []
    assert not s.take_from_container(0)
    before_xp = dict(s.game.character._skill_xp)
    for _ in range(500):
        a = s.lockpick_attempt
        if a is None:
            break
        a.angle = a.target
        a.set_tension(True)
        s.tick_lockpicking(.05)
    assert not chest.properties["locked"]
    assert s.open_screen == "container"
    assert "lockpick_state" not in chest.properties
    assert s.game.character._skill_xp != before_xp
    assert s.take_from_container(0)
    xp = dict(s.game.character._skill_xp)
    s.close_container()
    s.open_container(chest)
    assert s.game.character._skill_xp == xp


def test_cancel_and_reopen_keeps_pins_and_does_not_spend_a_pick():
    s, chest = _picking()
    _set_pin(s.lockpick_attempt)
    angle = s.lockpick_attempt.angle
    s.close_lockpicking()
    # Simulate a save/load: only ordinary public entity properties survive.
    restored = _Thing("Old lockbox", (40, 0, 0))
    restored.properties = json.loads(json.dumps(chest.properties))
    s.logic.things.append(restored)
    s.open_container(restored)
    assert s.lockpick_attempt.pins_set == 1
    assert s.lockpick_attempt.angle == angle
    assert inv.quantity(s.game.character.inventory, "lockpick") == 3


def _snap(s):
    a = s.lockpick_attempt
    a.angle = 80 if a.target < 0 else -80
    a.strain = .999
    a.binding_time = 1
    a.set_tension(True)
    s.tick_lockpicking(.1)


def test_snap_consumes_exactly_one_pick_and_preserves_pins():
    s, _ = _picking(skill=15)
    _set_pin(s.lockpick_attempt)
    _snap(s)
    assert inv.quantity(s.game.character.inventory, "lockpick") == 2
    assert s.lockpick_attempt.pins_set == 1
    assert not s.lockpick_attempt.tension
    s.tick_lockpicking(.1)
    assert inv.quantity(s.game.character.inventory, "lockpick") == 2


def test_last_pick_break_disables_tension_and_the_player_can_leave():
    s, _ = _picking(skill=15, picks=1)
    _snap(s)
    s.lockpick_action("tension_on")
    assert not s.lockpick_attempt.tension
    s.lockpick_action("cancel")
    assert s.open_screen is None


def test_low_skill_snap_can_shear_and_a_key_cannot_bypass_the_saved_jam(monkeypatch):
    s, chest = _picking(skill=0)
    monkeypatch.setattr(s.game.rng, "random", lambda: 0)
    _snap(s)
    assert chest.properties["lock_jammed"]
    assert s.open_screen is None
    chest.properties["lock_key"] = "old_key"
    inv.add_item(s.game.character.inventory, inv.make_item("old_key"))
    assert not s.open_container(chest)
    restored = _Thing("Old lockbox", (40, 0, 0))
    restored.properties = json.loads(json.dumps(chest.properties))
    assert not s.open_container(restored)
    # Even a direct inventory action cannot bypass the lock.
    s.container_thing = restored
    assert not s.take_from_container(0)
    assert not s.store_in_container(0)


def test_a_non_shearing_snap_does_not_jam_and_can_be_retried(monkeypatch):
    s, chest = _picking(skill=0)
    monkeypatch.setattr(s.game.rng, "random", lambda: .99)
    _snap(s)
    assert not chest.properties.get("lock_jammed")
    s.lockpick_action("tension_on")
    assert s.lockpick_attempt.tension


def test_matching_key_opens_a_normal_lock_without_consumption_or_security_xp():
    s, chest = _picking(picks=0)
    assert s.open_screen != "lockpicking"
    chest.properties["lock_key"] = "old_key"
    inv.add_item(s.game.character.inventory, inv.make_item("old_key"))
    xp = dict(s.game.character._skill_xp)
    assert s.open_container(chest)
    assert s.open_screen == "container"
    assert inv.has_item(s.game.character.inventory, "old_key")
    assert s.game.character._skill_xp == xp


def _knock(s):
    c = s.game.character
    c.class_id = "mage"
    c.known_spells = ["knock"]
    c.active_spell = "knock"
    c.magicka = 500
    c.max_magicka = 500
    c.skills[skills.DEFENSIVE] = 100
    return c


def test_knock_uses_the_spell_pipeline_to_clear_jams_without_stealing_the_contents(monkeypatch):
    s, chest = _picking()
    s.close_lockpicking()
    chest.properties["lock_jammed"] = True
    c = _knock(s)
    monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (True, {}))
    assert s.do_cast()
    assert c.magicka < 500
    assert not chest.properties["locked"] and not chest.properties["lock_jammed"]
    assert "lockpick_state" not in chest.properties
    assert len(chest.properties["inventory"]) == 1
    assert s.open_container(chest)


@pytest.mark.parametrize("reason", ["unknown", "magicka", "fizzle", "range"])
def test_unsuccessful_knock_never_clears_a_jam(reason, monkeypatch):
    s, chest = _picking()
    s.close_lockpicking()
    chest.properties["lock_jammed"] = True
    c = _knock(s)
    if reason == "unknown":
        c.known_spells = []
    elif reason == "magicka":
        c.magicka = 0
    elif reason == "range":
        chest.pos = [5000, 0, 0]
    else:
        monkeypatch.setattr(magic, "cast_check", lambda *a, **kw: (False, {}))
    assert not s.do_cast()
    assert chest.properties["lock_jammed"] and chest.properties["locked"]


def test_damage_and_leaving_reach_interrupt_without_losing_progress():
    s, _ = _picking()
    _set_pin(s.lockpick_attempt)
    s.game.character.health -= 1
    s.tick_lockpicking(.05)
    assert s.open_screen is None
    s, chest = _picking()
    chest.pos = [5000, 0, 0]
    s.tick_lockpicking(.05)
    assert s.open_screen is None


def test_a_patrol_arriving_later_sees_picking_and_reports_it_once():
    s, chest = _picking(_locked(owner="absent_owner"))
    s.tick_lockpicking(.1)
    assert s.open_screen == "lockpicking"
    guard = _Thing("Watchman", (50, 0, 0), type="npc", npc_role="guard", faction="guards", sight_range=500)
    s.logic.things.append(guard)
    s._type_index_token = None
    s.tick_lockpicking(.4)
    assert s.open_screen is None
    assert s.game.character.bounty == 25
    assert len(s.director.bus.recent(kind="lockpick")) == 1


@pytest.mark.parametrize("hidden_by", ["sleep", "wall", "distance", "ownership"])
def test_unseen_or_lawful_lockpicking_has_no_witness_bounty(hidden_by):
    chest = _locked(owner="player" if hidden_by == "ownership" else "absent_owner")
    s, _ = _picking(chest)
    guard = _Thing("Watchman", (50, 0, 0), type="npc", faction="guards", sight_range=500)
    s.logic.things.append(guard)
    s._type_index_token = None
    if hidden_by == "sleep":
        guard.properties["sched_state"] = "SLEEPING"
    elif hidden_by == "wall":
        s.logic.session_runtime = SimpleNamespace(spatial_grid=SimpleNamespace(has_line_of_sight=lambda *a: False))
    elif hidden_by == "distance":
        guard.pos = [5000, 0, 0]
    s.tick_lockpicking(.1)
    assert s.open_screen == "lockpicking"
    assert s.game.character.bounty == 0


@pytest.mark.parametrize("state", ["jammed", "unlocked", "partial"])
def test_map_departure_and_return_remember_the_lock_without_resetting_loot(state):
    from ..map_memory import MapMemory
    chest = _locked(id="persistent-lock")
    original = json.loads(json.dumps(chest.properties))
    s, _ = _picking(chest)
    s.memory.load("test-cave")
    if state == "jammed":
        chest.properties["lock_jammed"] = True
    elif state == "unlocked":
        chest.properties["locked"] = False
        s.close_lockpicking()
    else:
        _set_pin(s.lockpick_attempt)
        s.close_lockpicking()
    chest.properties["inventory"] = []
    s.memory.save()
    fresh = _Thing("Old lockbox", (40, 0, 0))
    fresh.properties = original
    s.logic.things = [fresh]
    memory = MapMemory(s)
    memory.load("test-cave")
    memory.apply()
    assert fresh.properties["inventory"] == []
    if state == "jammed":
        assert fresh.properties["lock_jammed"]
        assert not s.open_container(fresh)
    elif state == "unlocked":
        assert not fresh.properties["locked"]
    else:
        assert fresh.properties["lockpick_state"]["pins_set"] == 1


def test_mouse_fire_never_attacks_or_casts_while_picking(monkeypatch):
    s, _ = _picking()
    monkeypatch.setattr(s, "do_attack", lambda *a: pytest.fail("attack leaked"))
    monkeypatch.setattr(s, "do_cast", lambda *a: pytest.fail("cast leaked"))
    assert s.fire_player_weapon(s.logic, "primary")
    assert s.fire_player_weapon(s.logic, "secondary")


def test_starting_to_pick_lowers_a_charged_weapon_and_discards_queued_release(monkeypatch):
    s, chest = _picking()
    s.close_lockpicking()
    s.bow_charge = .9
    s._blocking = True
    s._bow_input.append("release")
    monkeypatch.setattr(s, "_loose_drawn_arrow", lambda *a: pytest.fail("arrow leaked"))
    assert s.open_container(chest)
    s._update_bow_draw(.1)
    assert s.bow_charge is None
    assert not s._bow_input
    assert not s._blocking


def test_a_lethal_hit_closes_the_lock_ui_before_engine_ticks_stop(monkeypatch):
    from .. import runtime
    s, chest = _picking()
    _set_pin(s.lockpick_attempt)
    monkeypatch.setattr(runtime.rpg_combat, "resolve_incoming",
                        lambda *a, **kw: {"final": 999, "armor_class": "none"})
    s._mitigate_incoming(999)
    assert s.game.character.is_dead
    assert s.open_screen is None
    assert chest.properties["lockpick_state"]["pins_set"] == 1
