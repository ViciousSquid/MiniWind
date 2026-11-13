"""Real dice: true solids that tumble out of step and settle on the face they
rolled; a hit's damage die rolls beside its d20."""

from __future__ import annotations

import random

import pytest

pytest.importorskip("PyQt5")

from ..diceroll import DiceRoller, roll_check
from ..rpg import combat, items
from ..ui import dice3d


@pytest.mark.parametrize("sides, faces, corners", [(4, 4, 3), (6, 6, 4), (8, 8, 3),
                                                   (10, 10, 4), (12, 12, 5), (20, 20, 3)])
def test_every_die_is_its_true_solid(sides, faces, corners):
    verts, built = dice3d.solid(sides)
    assert len(built) == faces
    assert all(len(idx) == corners for idx, _n in built)


@pytest.mark.parametrize("sides", [4, 6, 8, 10, 12, 20])
def test_a_settled_die_turns_the_face_it_rolled_to_the_player(sides):
    _verts, faces = dice3d.solid(sides)
    for value in range(1, sides + 1):
        rotation, dx, dy, settled = dice3d.pose(sides, value, dice3d.motion(value), 99.0)
        assert settled and dx == 0.0 and dy == 0.0
        toward = [dice3d._apply(rotation, n)[2] for _idx, n in faces]
        assert max(range(len(faces)), key=toward.__getitem__) == value - 1


def test_two_dice_thrown_together_tumble_out_of_step():
    a, b = dice3d.motion(1), dice3d.motion(2)
    assert (a["duration"], a["axis"], a["turns"]) != (b["duration"], b["axis"], b["turns"])
    ra = dice3d.pose(20, 7, a, 0.3)[0]
    rb = dice3d.pose(20, 7, b, 0.3)[0]
    assert ra != rb
    assert not dice3d.pose(20, 7, a, 0.3)[3]         # still tumbling


def test_a_die_draws_on_a_painter(qt_app):
    from PyQt5.QtGui import QImage, QPainter
    img = QImage(120, 120, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    rotation = dice3d.pose(20, 17, dice3d.motion(3), 9.0)[0]
    dice3d.draw_die(p, 20, 17, 60, 60, 100, rotation)
    p.end()
    assert (img.pixel(60, 60) >> 24) & 0xFF > 0


# ------------------------------------------------------------- damage dice
@pytest.mark.parametrize("base", [2.0, 5.0, 8.0, 12.0, 20.0])
def test_a_damage_die_averages_the_weapons_damage(base):
    sides, flat = combat.damage_die(base)
    assert sides in combat.DAMAGE_DICE
    assert (sides + 1) / 2.0 + flat == pytest.approx(base)


def test_an_item_can_name_its_own_damage_die():
    class Weapon(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)
    assert combat.damage_die(10.0, Weapon(damage_die="d6"))[0] == 6


def test_a_hit_rolls_its_damage_die_beside_the_d20():
    from ..rpg.character import Character
    seen = []
    roller = DiceRoller(rng=random.Random(4))
    roller.add_roll_listener(lambda result, source, ctx: seen.append((source, ctx)))
    c = Character()
    res = None
    for _ in range(20):                       # until one lands
        res = combat.player_attack(c, {"name": "hen", "health": 50}, dice=roller)
        if res["hit"]:
            break
    assert res["hit"]
    sources = [s for s, _ctx in seen]
    hit_at = len(sources) - 1 - sources[::-1].index("combat.hit")
    assert sources[hit_at + 1] == "combat.damage"
    assert seen[hit_at + 1][1]["damage_die"]
    assert res["damage_die"] == combat.damage_die(2.0)[0] and 1 <= res["damage_face"]


def test_the_damage_die_joins_the_hit_in_the_dice_panel(qt_app, monkeypatch):
    from .test_cast_controls import _Logic
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(), cfg={})
    monkeypatch.setattr(s, "_visualise_dice_rolls_enabled", lambda: True)
    s.dice_animation = None
    d = s.game.dice
    hit = roll_check(d, 0.7, "Roll to hit Bandit", source="combat.hit")
    damage = d.request_roll("1d8", source="combat.damage",
                            context={"label": "Damage (Mace: d8)", "damage_die": True})
    assert s.dice_animation["result"] is hit or s.dice_animation["result"] == hit
    assert s.dice_animation["companion"] == damage
    assert damage not in s.dice_animation.get("followups", [])


# --------------------------------------------------------------- roll boxes
def _layout(w=180, h=120):
    return {"w": w, "h": h}


def _box(label):
    return {"result": {"label": label}}


def test_close_roll_boxes_stack_with_the_attacker_on_top():
    from ..ui import hud
    attack = ((500.0, 400.0), _box("Roll to hit"), _layout())
    save = ((520.0, 400.0), _box("Hunter: shield saving throw"), _layout())
    # Saved first, attacked second: the stack still puts the attack on top.
    (group,) = hud._stack_roll_boxes([save, attack], 1200, 800)
    assert [g[3]["result"]["label"] for g in group] == ["Roll to hit",
                                                         "Hunter: shield saving throw"]
    top, bottom = group
    assert bottom[1] - (top[1] + 120) == hud.ROLL_BOX_STACK_GAP      # locked together
    assert not top[5] and bottom[5]                  # only the bottom box points down


def test_slightly_overlapping_boxes_stay_over_their_rollers():
    from ..ui import hud
    a = ((400.0, 400.0), _box("Roll to hit"), _layout())
    b = ((400.0 + 180 * 0.8, 400.0), _box("Roll to hit"), _layout())    # 20% overlap
    groups = hud._stack_roll_boxes([a, b], 1200, 800)
    assert len(groups) == 2


def test_with_stacking_off_close_boxes_stay_apart():
    from ..ui import hud
    a = ((500.0, 400.0), _box("Roll to hit"), _layout())
    b = ((510.0, 400.0), _box("Roll to hit"), _layout())
    assert len(hud._stack_roll_boxes([a, b], 1200, 800, stack=False)) == 2
    assert len(hud._stack_roll_boxes([a, b], 1200, 800, stack=True)) == 1


def test_stack_dialogs_is_a_game_setting_on_by_default():
    from ..integration import GAME_SETTINGS
    entry = next(e for e in GAME_SETTINGS if e[0] == "stack_dialogs")
    assert entry[1] == "Stack dialogs" and entry[3] is True


def test_only_the_players_dice_are_in_colour():
    mine20, theirs20 = dice3d.colours(20, True), dice3d.colours(20, False)
    assert mine20[0] == dice3d.D20_BODY
    for sides in (20, 8):
        body, ink = dice3d.colours(sides, False)
        for colour in (body, ink):
            assert colour.red() == colour.green() == colour.blue() or \
                max(colour.red(), colour.green(), colour.blue()) - \
                min(colour.red(), colour.green(), colour.blue()) <= 6   # greyscale


def test_a_roll_box_sits_over_its_roller_and_hushes_its_speech(qt_app):
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    wolf = _Thing("Wolf", (100.0, 0.0, 0.0), type="creature", npc_role="wolf")
    s = MiniwindSession(_Logic([wolf]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    box = s.show_roll_box(wolf, {"label": "Roll to hit", "roll_result": 7, "target": 9,
                                 "success": False, "dice_notation": "1d20",
                                 "roll_details": [7], "components": [
                                     {"notation": "1d20", "roll_details": [7]}]},
                          kind="npc")
    assert box["actor"] is wolf and box["kind"] == "npc"
    assert s.has_roll_box(wolf) and box in s.live_roll_boxes()
    s._tick_dice_animation(box["duration"] + 0.1)
    assert not s.has_roll_box(wolf)


# ------------------------------------------- a roll box never shows a false result
def test_the_damage_line_is_the_damage_actually_dealt(qt_app, monkeypatch):
    """The box's damage line names the die's real face and the final damage --
    the very number that floats over the target -- never an earlier figure."""
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    from ..rpg import equipment as eq, inventory as inv
    bandit = _Thing("Bandit", (0.0, 0.0, 60.0), type="npc", health=500, max_health=500,
                    npc_role="bandit")
    s = MiniwindSession(_Logic([bandit]), cfg={})
    monkeypatch.setattr(s, "_visualise_dice_rolls_enabled", lambda: True)
    c = s.game.character
    inv.add_item(c.inventory, items.make("iron_longsword"))
    eq.equip(c, "iron_longsword")
    floaters = []
    monkeypatch.setattr(s, "add_floater", lambda text, kind="dmg", y=0.0: floaters.append(text))
    for _ in range(40):
        s.dice_animation = None
        res = s.game.attack_creature(bandit.properties)
        s._land_player_hit(bandit, res)
        if res["hit"]:
            break
    assert res["hit"]
    companion = s.dice_animation["companion"]
    face = companion["roll_result"]
    assert res["damage_face"] == face                   # the face shown is the face used
    assert companion["detail"].endswith(f"rolled {face} → {int(res['damage'])} damage")
    # The number over the target waits for the damage die, then matches.
    assert f"-{int(res['damage'])}" not in floaters
    import time
    later = time.monotonic() + 10.0
    monkeypatch.setattr(time, "monotonic", lambda: later)
    s._run_reveals()
    assert floaters[-1] == f"-{int(res['damage'])}"     # the same number over the target


@pytest.mark.parametrize("sides", [6, 12, 20])
def test_a_settled_die_shows_exactly_the_rolled_number(qt_app, sides):
    """Settled, the face turned to the player is the rolled one, and it is
    labelled with the rolled number."""
    for value in (1, sides // 2, sides):
        rotation, _dx, _dy, settled = dice3d.pose(sides, value, dice3d.motion(9), 99.0)
        assert settled
        _verts, faces = dice3d.solid(sides)
        toward = [dice3d._apply(rotation, n)[2] for _idx, n in faces]
        front = max(range(len(faces)), key=toward.__getitem__)
        assert front == value - 1 and dice3d.face_label(sides, front) == str(value)


def test_hit_or_miss_waits_for_its_die_to_land(qt_app, monkeypatch):
    """With a roll box on screen, HIT / MISS / Crit! over the attacker
    appears only when the to-hit die lands -- never ahead of the dice."""
    import time
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession, HIT_TEXT
    wolf = _Thing("Wolf", (100.0, 0.0, 0.0), type="creature", npc_role="wolf")
    s = MiniwindSession(_Logic([wolf]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    roll = {"label": "Roll to hit", "roll_result": 15, "target": 9, "success": True,
            "dice_notation": "1d20", "roll_details": [15],
            "components": [{"notation": "1d20", "roll_details": [15]}]}
    s.show_roll_box(wolf, roll, kind="npc")
    s.attack_outcome(wolf, True)
    wait = s._reveal_delay(wolf)
    assert wait > 0.5                                     # the die is still tumbling
    assert all(t is not wolf for t, *_ in s.live_floats())
    clock = time.monotonic() + wait + 0.05
    monkeypatch.setattr(time, "monotonic", lambda: clock)
    floated = {id(t): text for t, text, *_ in s.live_floats()}
    assert floated[id(wolf)] == HIT_TEXT


def test_the_box_tells_each_result_as_its_die_lands(qt_app):
    """The verdict line waits for the roll's own die; the damage line for
    the damage die as well."""
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import hud
    box = {"result": {"label": "Roll to hit", "roll_result": 14, "target": 8, "success": True,
                      "dice_notation": "1d20", "roll_details": [14],
                      "components": [{"notation": "1d20", "roll_details": [14]}]},
           "companion": {"dice_notation": "1d12", "roll_result": 9, "roll_details": [9],
                         "components": [{"notation": "1d12", "roll_details": [9]}],
                         "detail": "Iron Longsword d12+9.5: rolled 9 → 15 damage"},
           "elapsed": 0.0, "duration": 6.0, "actor": None, "side": "you", "kind": "party",
           "seed": 3}
    layout = hud._roll_box_layout(box, 1200)
    hit_die, dmg_die = layout["visuals"]
    told = []
    orig = hud.T.text_in
    hud.T.text_in = lambda painter, rect, text, *a, **k: told.append(text)
    try:
        def lines_at(t):
            told.clear()
            box["elapsed"] = t
            lay = hud._roll_box_layout(box, 1200)
            img = QImage(400, 300, QImage.Format_ARGB32)
            p = QPainter(img)
            hud._draw_roll_box(p, box, lay, 10, 10, (200, 290), 0)
            p.end()
            return [x for x in told if "need" in x or "damage" in x]
        assert lines_at(0.1) == []                                        # tumbling
        land = hit_die["motion"]["delay"] + hit_die["motion"]["duration"]
        dmg_land = dmg_die["motion"]["delay"] + dmg_die["motion"]["duration"]
        if dmg_land > land + 0.02:
            mid = (land + dmg_land) / 2
            assert lines_at(mid) == ["14 (need 8+) — HIT"]               # d20 down only
        assert lines_at(max(land, dmg_land) + 0.05) == [
            "14 (need 8+) — HIT", "Iron Longsword d12+9.5: rolled 9 → 15 damage"]
    finally:
        hud.T.text_in = orig


def test_damage_is_told_within_a_second_and_no_roll_lasts_past_1_2():
    """Every die lands quickly: the damage (last die down, plus the reveal
    beat) is told within 1.0 s of the blow. Some rolls rattle on after
    landing -- face up -- but none lasts longer than 1.2 s; and rolls vary."""
    from ..runtime import REVEAL_PAUSE
    told, longest, paces, rattled = 0.0, 0.0, set(), 0
    for seed in range(1, 3000):
        speed = dice3d.roll_speed(seed)
        paces.add(round(speed, 3))
        long_roll = dice3d.rattles(seed)
        rattled += long_roll
        a = dice3d.motion(seed * 31, speed=speed, rattle=long_roll)
        b = dice3d.motion(seed * 31 + 977, delay=dice3d.SECOND_DIE_DELAY, speed=speed,
                          rattle=long_roll)
        land = max(a["delay"] + a["duration"], b["delay"] + b["duration"])
        told = max(told, land + REVEAL_PAUSE)
        longest = max(longest, *(m["delay"] + m["duration"] + m["rattle"] for m in (a, b)))
    assert told <= dice3d.DAMAGE_TOLD_BY == 1.0
    assert longest <= dice3d.ROLL_MAX_SECONDS == 1.2
    assert 0.15 < rattled / 2999 < 0.35 and len(paces) > 100


def test_a_rattling_die_keeps_its_rolled_face_up():
    m = dice3d.motion(5, rattle=True)
    assert m["rattle"] > 0
    _verts, faces = dice3d.solid(20)
    for t in (0.01, m["rattle"] / 3, m["rattle"] * 0.8):
        rotation, _dx, _dy, settled = dice3d.pose(20, 13, m, m["duration"] + t)
        toward = [dice3d._apply(rotation, n)[2] for _idx, n in faces]
        assert settled and max(range(20), key=toward.__getitem__) == 12
