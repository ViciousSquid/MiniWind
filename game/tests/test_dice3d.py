"""Real dice: true solids that tumble out of step and settle on the face they
rolled; a hit's damage die rolls beside its d20."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

pytestmark = pytest.mark.qt

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
    b = ((400.0 + 180 * 0.95, 400.0), _box("Roll to hit"), _layout())   # margins touch
    groups = hud._stack_roll_boxes([a, b], 1200, 800)
    assert len(groups) == 2


def _rect(entry):
    x, y, _sp, _box, layout, _pointer = entry
    return x, y, layout["w"], layout["h"]


def test_a_box_never_hides_the_words_of_another():
    """A quarter across and fully level covers the start of a roller's name
    (seen at Smugglers' Cove): it stacks instead, and nothing overlaps."""
    from ..ui import hud
    entries = [((600.0, 500.0 - 121 * k), _box("Roll to hit"), _layout(280, 120)) for k in range(4)]
    entries.append(((600.0 - 280 * 0.75, 500.0), _box("Roll to hit"), _layout(280, 120)))
    rects = [_rect(e) for g in hud._stack_roll_boxes(entries, 1280, 720) for e in g]
    for i, (x, y, w, h) in enumerate(rects):
        for (x2, y2, w2, h2) in rects[i + 1:]:
            across = min(x + w, x2 + w2) - max(x, x2)
            down = min(y + h, y2 + h2) - max(y, y2)
            assert across <= w * hud.ROLL_BOX_OVERLAP_OK or down <= h * hud.ROLL_BOX_OVERLAP_OK


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
    def name(pair):
        return tuple(c.name() for c in pair)

    def grey(colour):
        rgb = (colour.red(), colour.green(), colour.blue())
        return max(rgb) - min(rgb) <= 6

    shades = [dice3d.pick_shade(seed) for seed in range(400)]
    mine = {name(f) for s in shades for f in dice3d.finishes(2, True, s)}
    theirs = {name(f) for s in shades for f in dice3d.finishes(2, False, s)}
    assert mine == {name(p) for p in dice3d.PLAYER_COLOURS}          # every finish turns up
    assert theirs == {name(p) for p in dice3d.GREYSCALE}
    assert name((dice3d.D20_BODY, dice3d.D20_INK)) in mine           # red, on any die
    assert not (mine & theirs)
    assert not any(grey(body) and grey(ink) for body, ink in dice3d.PLAYER_COLOURS)
    assert all(grey(body) and grey(ink) for body, ink in dice3d.GREYSCALE)
    black, white_ink = dice3d.GREYSCALE[0]
    assert black.lightness() < 30 and white_ink.lightness() > 230    # black dice, white numbers


@pytest.mark.parametrize("player", [True, False])
def test_never_two_dice_of_a_roll_the_same_colour(player):
    for seed in range(500):
        bodies = [body.name() for body, _ in dice3d.finishes(2, player, dice3d.pick_shade(seed))]
        assert bodies[0] != bodies[1]


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
        s._reveals = []                       # only this attempt's results are pending
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


# ------------------------------------------------------------------ co-op
def _coop_screen():
    """Two clients' players: Ash plays on this machine, Bryn on another."""
    def avatar(pid, name):
        return SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={
            "name": name, "display_name": name, "is_player": True,
            "player_id": pid, "multiplayer_player": True})

    def roll(actor, pid, side="you", against=None):
        return {"result": {"label": "Attack", "total": 12, "target": 10, "success": True,
                           "components": [{"notation": "1d20", "roll_details": [12]}]},
                "elapsed": 0.0, "actor": actor, "side": side, "against": against,
                "kind": "party", "player_id": pid, "seed": 5}

    ash, bryn = avatar("a", "Ash"), avatar("b", "Bryn")
    wolf = SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={"name": "Wolf"})
    mine, theirs = roll(ash, "a"), roll(bryn, "b")
    at_bryn = roll(wolf, "b", side="foe", against=("YOU", "you"))
    sa = SimpleNamespace(live_roll_boxes=lambda: [mine])
    sb = SimpleNamespace(live_roll_boxes=lambda: [theirs, at_bryn])
    a = SimpleNamespace(player_id="a", session=sa, profile={"name": "Ash"})
    b = SimpleNamespace(player_id="b", session=sb, profile={"name": "Bryn"})
    sa.coop = SimpleNamespace(players={"a": a, "b": b}, local_players=[a])
    return sa, mine, theirs, at_bryn


def test_in_coop_you_are_whoever_plays_on_this_machine(qt_app):
    from ..ui import hud
    screen, mine, theirs, at_bryn = _coop_screen()
    boxes = hud._screen_roll_boxes(screen)
    assert {id(b) for b in boxes} == {id(mine), id(theirs), id(at_bryn)}   # the party's rolls too
    assert hud._box_side(mine) == "you"                    # yours: in colour, YOU
    assert hud._box_side(theirs) == "ally"                 # a party member's: greyscale
    assert hud._box_against(at_bryn) == ("BRYN", "ally")   # not "vs YOU" on your screen
    mine_layout = hud._roll_box_layout(mine, 1200)
    their_layout = hud._roll_box_layout(theirs, 1200)
    assert mine_layout["side"] == "you" and mine_layout["parts"][0][0] == "YOU"
    assert their_layout["side"] == "ally" and their_layout["parts"][0][0] == "BRYN"


def test_alone_your_rolls_are_still_yours(qt_app):
    from ..ui import hud
    box = {"side": "you", "actor": SimpleNamespace(pos=[0, 0, 0], properties={}), "player_id": None}
    solo = SimpleNamespace(live_roll_boxes=lambda: [box])
    assert hud._screen_roll_boxes(solo) == [box] and hud._box_side(box) == "you"


def test_roll_boxes_only_open_in_the_near_tier(qt_app):
    from engine.spatial import TIER_ACTIVE
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    wolf = _Thing("Wolf", (100.0, 0.0, 0.0), type="creature", npc_role="wolf")
    s = MiniwindSession(_Logic([wolf]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    roll = {"label": "Roll to hit", "roll_result": 7, "target": 9,
            "components": [{"notation": "1d20", "roll_details": [7]}]}
    wolf.properties["_sim_tier"] = TIER_ACTIVE
    assert s.show_roll_box(wolf, roll) is None
    wolf.properties["_sim_tier"] = 0
    wolf.properties["_bw_parked_hidden"] = False          # parked: never rolls
    assert s.show_roll_box(wolf, roll) is None
    del wolf.properties["_bw_parked_hidden"]
    assert s.show_roll_box(wolf, roll) is not None


def test_every_client_sees_the_same_dice(qt_app, monkeypatch):
    """The host rolls; a client shows that very roll -- the same numbers, the
    same throw, the same finishes -- for a player's own roll and a roll box
    over anyone near them, after a trip over the wire."""
    import json
    from .test_cast_controls import _Logic, _Thing
    from ..multiplayer import replication
    from ..runtime import MiniwindSession
    from ..ui import hud

    def session(wolf):
        s = MiniwindSession(_Logic([wolf]), cfg={})
        s._player_pos = lambda: [0.0, 0.0, 0.0]
        s.player_id = "b"
        return s

    wolf = _Thing("Wolf", (100.0, 0.0, 0.0), type="creature", npc_role="wolf", id="wolf_7")
    host = session(wolf)
    monkeypatch.setattr(host, "_visualise_dice_rolls_enabled", lambda: True)
    host._on_dice_roll({"label": "Attack", "total": 15, "target": 10, "success": True,
                        "components": [{"notation": "1d20", "roll_details": [15]}]},
                       "test", {"against_name": "Wolf"})
    assert host.dice_animation is not None and "seed" in host.dice_animation
    assert host.show_roll_box(wolf, {"label": "Roll to hit", "total": 4, "target": 12,
                                     "success": False,
                                     "components": [{"notation": "1d20", "roll_details": [4]}]})

    def seen(box):
        return [(v["sides"], v["value"], v["shade"], v["motion"])
                for v in hud._prepare_dice_animation(dict(box), box["result"])]

    host_box = next(iter(host.roll_boxes.values()))
    wire = json.loads(json.dumps(replication.rolls_out(host)))
    client_wolf = _Thing("Wolf", (100.0, 0.0, 0.0), type="creature", id="wolf_7")
    avatar = _Thing("Bryn", (0.0, 0.0, 0.0), type="npc", id="b")
    client = session(client_wolf)
    replication.rolls_in(client, wire, {"wolf_7": client_wolf, "b": avatar}, avatar, "b")

    assert client.dice_animation["actor"] is avatar
    assert client.dice_animation["result"]["components"][0]["roll_details"] == [15]
    assert seen(client.dice_animation) == seen(host.dice_animation)
    (client_box,) = client.roll_boxes.values()
    assert client_box["actor"] is client_wolf and client_box["result"]["total"] == 4
    assert seen(client_box) == seen(host_box)
    # Lean on the wire: the tumble is rebuilt from the seed, never sent.
    hud._prepare_dice_animation(host_box, host_box["result"])
    assert "dice_visuals" not in json.dumps(replication.rolls_out(host))
    # The next frame keeps what is already shown (its dice built once), and
    # only steps its clock to the host's.
    hud._prepare_dice_animation(client_box, client_box["result"])
    host_box["elapsed"] = 0.4
    replication.rolls_in(client, json.loads(json.dumps(replication.rolls_out(host))),
                         {"wolf_7": client_wolf, "b": avatar}, avatar, "b")
    assert next(iter(client.roll_boxes.values())) is client_box
    assert client_box["elapsed"] == 0.4 and "dice_visuals" in client_box


def test_mashing_attack_tells_the_last_roll_at_once_and_shows_the_new_one(qt_app, monkeypatch):
    """Attacking again before the last roll has landed never makes the player
    wait: that roll's results are told there and then (its damage, its HIT,
    the target's bar), and the new roll replaces it at once."""
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    from ..rpg import equipment as eq, inventory as inv
    from ..ui import target_panel as tp
    bandit = _Thing("Bandit", (0.0, 0.0, 60.0), type="npc", health=5000, max_health=5000,
                    npc_role="bandit")
    s = MiniwindSession(_Logic([bandit]), cfg={})
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    monkeypatch.setattr(s, "_visualise_dice_rolls_enabled", lambda: True)
    s.target_panel = tp.TargetTracker()
    c = s.game.character
    inv.add_item(c.inventory, items.make("iron_longsword"))
    eq.equip(c, "iron_longsword")
    floaters = []
    monkeypatch.setattr(s, "add_floater", lambda text, kind="dmg", y=0.0: floaters.append(text))
    for _ in range(40):
        s.dice_animation = None
        s._reveals = []
        first = s.game.attack_creature(bandit.properties)
        s._land_player_hit(bandit, first)
        if first["hit"]:
            break
    assert first["hit"] and s._reveals                  # its damage is waiting on its dice
    assert s.target_panel._held is not None
    shown = s.dice_animation
    s._tick_dice_animation(0.1)                         # a tenth of a second later: again
    second = s.game.attack_creature(bandit.properties)
    s._land_player_hit(bandit, second)
    assert floaters and floaters[0] == f"-{int(first['damage'])}"   # told at once
    assert s.dice_animation is not shown                 # the new roll, straight away
    assert s.dice_animation["elapsed"] < 0.1
    held = s.target_panel._held                         # the first blow's hold is gone
    if second["hit"]:
        assert held is not None and held[1] == second["health_before"]
    else:
        assert held is None


@pytest.mark.parametrize("side,kind,bg", [
    ("you", "party", "you"), ("ally", "party", "other"),
    ("foe", "party", "other"), ("foe", "npc", "other")])
def test_your_rolls_sit_on_black_everyone_elses_on_blue(qt_app, side, kind, bg):
    """The box behind your own roll is black; behind anyone else's -- an ally,
    a foe, a fight between NPCs -- blue-slate, whatever the roll's kind."""
    from PyQt5.QtGui import QImage, QPainter, QColor
    from ..ui import hud
    box = {"result": {"label": "Roll to hit", "roll_result": 14, "target": 8,
                      "success": True, "dice_notation": "1d20", "roll_details": [14],
                      "components": [{"notation": "1d20", "roll_details": [14]}]},
           "elapsed": 0.0, "duration": 6.0, "actor": None, "side": side,
           "kind": kind, "seed": 3}
    layout = hud._roll_box_layout(box, 1200)
    img = QImage(400, 300, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    hud._draw_roll_box(p, box, layout, 10, 10, (200, 290), 0)
    p.end()
    px = QColor(img.pixel(14, 10 + layout["h"] - 4))            # inside, clear of text
    want = QColor(*hud.ROLL_BOX_BG[bg][:3])
    alpha = hud.ROLL_BOX_BG[bg][3] / 255.0
    expect = [round(c * alpha + 255 * (1 - alpha)) for c in (want.red(), want.green(), want.blue())]
    assert abs(px.red() - expect[0]) <= 3 and abs(px.green() - expect[1]) <= 3 \
        and abs(px.blue() - expect[2]) <= 3, (px.getRgb(), expect)


def test_a_brawl_never_runs_under_the_shortcut_bar():
    """Six fighters in one knot: the stack shows what fits above the bar,
    the player's own roll always among them."""
    from ..ui import hud
    entries = [((640.0, 400.0 + 8 * k), _box("Roll to hit"), _layout(280, 120)) for k in range(5)]
    mine = ((650.0, 420.0), {"result": {"label": "Roll to hit"}, "side": "you"}, _layout(280, 120))
    entries.append(mine)
    groups = hud._stack_roll_boxes(entries, 1280, 720, floor=610)
    shown = [e for g in groups for e in g]
    assert all(y >= 4 and y + layout["h"] <= 610 for _x, y, _sp, _b, layout, _p in shown)
    assert len(shown) == 4                       # four 120 px boxes fit in 602 px
    assert any(b is mine[1] for _x, _y, _sp, b, _l, _p in shown)


def test_docked_rolls_are_one_column_of_one_width_on_the_right():
    from ..ui import hud
    entries = [((300.0 + 40 * k, 400.0), _box("Roll to hit"), _layout(180 + 30 * k, 120)) for k in range(3)]
    mine = ((640.0, 420.0), {"result": {"label": "Roll to hit"}, "side": "you"}, _layout(200, 120))
    groups = hud._stack_roll_boxes(entries + [mine], 1280, 720, floor=620, dock="right", dock_top=200)
    column = [e for g in groups for e in g if e[3] is not mine[1]]
    assert len(column) == 3
    assert {e[0] + e[4]["w"] for e in column} == {1280 - 12}      # flush right
    assert {e[4]["w"] for e in column} == {hud.ROLL_DOCK_W}       # one narrow width
    assert all(e[4]["h"] == 120 + hud.ROLL_DOCK_LINE_H for e in column)   # two-line title
    assert column[0][1] == 200 and all(not e[5] for e in column)  # no pointer tails
    (own,) = [e for g in groups for e in g if e[3] is mine[1]]
    assert abs(own[0] + 100 - 640) < 2                            # yours stays over you


def test_your_roll_stays_over_you_when_it_touched_anothers_before_docking():
    # Found in a co-op game: your box overlapped a party member's, the two
    # joined one cluster, and docking the other dropped yours entirely.
    from ..ui import hud
    theirs = ((560.0, 400.0), _box("Roll to hit"), _layout(190, 122))
    mine = ((540.0, 400.0), {"result": {"label": "Roll to hit"}, "side": "you"}, _layout(160, 122))
    groups = hud._stack_roll_boxes([mine, theirs], 1280, 720, floor=620, dock="right", dock_top=200)
    shown = [e[3] for g in groups for e in g]
    assert mine[1] in shown and theirs[1] in shown


def test_without_a_role_label_the_verdict_sits_right_under_the_dice(monkeypatch):
    from ..ui import hud
    roll = {"label": "Roll to hit", "roll_result": 12, "target": 10, "success": True,
            "dice_notation": "1d20", "roll_details": [12],
            "components": [{"notation": "1d20", "roll_details": [12]}]}
    lay = hud._roll_box_layout({"result": roll, "elapsed": 0.0, "seed": 3, "side": "you"}, 1280)
    assert lay["under"] == hud.ROLL_DICE_GAP < hud.ROLL_ROLE_LINE_H
    assert lay["h"] == hud.ROLL_BOX_TITLE_H + hud.ROLL_BOX_DIE + hud.ROLL_DICE_GAP + 22 + 10


def test_party_members_roll_in_their_own_colour():
    from PyQt5.QtGui import QColor
    from ..multiplayer import presentation
    from ..ui import hud

    def member(pid, boxes):
        session = SimpleNamespace(live_roll_boxes=lambda: boxes)
        return SimpleNamespace(player_id=pid, profile={"name": pid}, session=session)

    actor = lambda pid: SimpleNamespace(pos=(0, 0, 0), properties={"multiplayer_player": True, "player_id": pid})
    wolf = SimpleNamespace(pos=(0, 0, 0), properties={"name": "Wolf"})
    mine = {"actor": actor("p1"), "side": "you", "player_id": "p1"}
    theirs = {"actor": actor("p2"), "side": "ally", "player_id": "p2"}
    foe = {"actor": wolf, "side": "foe", "player_id": "p2"}
    p1, p2 = member("p1", [mine]), member("p2", [theirs, foe])
    coop = SimpleNamespace(players={"p1": p1, "p2": p2}, local_players=[p1])
    session = SimpleNamespace(coop=coop, live_roll_boxes=lambda: [])
    hud._screen_roll_boxes(session)
    blue, orange = (QColor(presentation.COLOURS[i]) for i in (0, 1))
    assert mine["_party_colour"] == (blue.red(), blue.green(), blue.blue())
    assert theirs["_party_colour"] == (orange.red(), orange.green(), orange.blue())
    assert foe["_party_colour"] is None            # a wolf is nobody's colour
    assert presentation.colour_for(coop, "nobody") is None


def test_party_cards_are_narrow():
    from ..multiplayer import presentation
    rects = presentation.party_rects(1280, 720, 4)
    assert all(r.width() == presentation.CARD_WIDTH <= 180 for r in rects)
