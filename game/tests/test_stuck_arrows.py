"""
Arrows stuck in barrels (game/stuck_arrows.py), in a real Play session.

An arrow -- a projectile loosed with its ammunition in its metadata -- that
meets a barrel stops in it, kept in the barrel's model space so it moves and
turns with the barrel; it is heard (thunk.mp3) where it strikes. E by the
barrel pulls the arrows into the pack; E anywhere else does nothing. A barrel
that explodes destroys its arrows.

Run:  QT_QPA_PLATFORM=offscreen python -m pytest game/tests/test_stuck_arrows.py -q
"""

from __future__ import annotations

import math
import time
import weakref
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

from editor.things import PlayerStart                                # noqa: E402
from engine.prop_entity import Prop                                  # noqa: E402
from game import fio, stuck_arrows                                        # noqa: E402
from game.stuck_arrows import ARROW_THUNK_SOUND, KEY, StuckArrows    # noqa: E402
from tests.helpers.worlds import level_data, make_thing, room        # noqa: E402
from game.tests.test_multiplayer_integration import coop_game        # noqa: E402,F401

pytestmark = [pytest.mark.qt, pytest.mark.integration]

TICK = 1.0 / 60.0
#: The oak barrel's half-width (its model is 45.6 across, 65.2 tall).
RADIUS = 22.8214
#: The height arrows fly at in these tests: the middle of the barrel.
HEIGHT = 32.0


class _Game:
    """What StuckArrows asks of the game session."""

    def __init__(self, logic):
        # LogicThread is owned by the editor window. The projectile/use hooks
        # installed below live on that thread, so this test adapter must not
        # create a strong LogicThread -> callback -> adapter -> LogicThread
        # reference path that can keep the editor QObject graph alive.
        self.logic = weakref.proxy(logic)
        self.sounds = []
        self.notes = []
        self.interact_prompt = ""
        self.game = SimpleNamespace(character=SimpleNamespace(inventory=[], is_dead=False))
        self.stuck_arrows = StuckArrows(self)

    def play_sound_at(self, name, pos, volume=1.0, radius=900.0):
        self.sounds.append((name, tuple(float(v) for v in pos)))
        return True

    def notify(self, text, seconds=3.0):
        self.notes.append(text)

    def pack_has_room(self, item_id, qty=1, freed=0):
        return True

    def nearest_arrest_guard(self, *_a):
        return None

    nearest_talkable = nearest_notice_board = nearest_container = nearest_corpse = \
        nearest_arrest_guard


@pytest.fixture
def clock(monkeypatch):
    import engine.entity_table as et
    now = [et._CLOCK_ORIGIN + 1000.0]
    monkeypatch.setattr(time, "perf_counter", lambda: now[0])
    return now


@pytest.fixture(autouse=True)
def _uninstall_stuck_arrow_hooks_before_session_close(fio_session):
    """Detach hooks from the exact LogicThread before its editor is closed."""
    fio_session._stuck_arrows_cleanup = []
    yield
    for arrows, owner, logic in reversed(fio_session._stuck_arrows_cleanup):
        # Keep the actual LogicThread, rather than recovering it through the
        # game's weak proxy during teardown. Tests may explicitly uninstall
        # StuckArrows (which clears arrows.session) before this fixture runs.
        fio.clear_projectile_catcher(logic, arrows)
        runtime = fio.prop_runtime(logic)
        if (runtime is not None
                and getattr(runtime, "use_claim", None) is arrows._use_claim):
            runtime.use_claim = None
        arrows.uninstall()
        owner.logic = None
        owner.stuck_arrows = None
        arrows.session = None
    fio_session._stuck_arrows_cleanup = []


def _barrel(name, x, z, **props):
    return make_thing(Prop, name, (x, 0.0, z), model_path="Oak_Barrel.obj", **props)


def _step(session, ticks=1):
    for _ in range(ticks):
        session.clock[0] += TICK
        session.step(1)


def _play(fio_session, clock, things):
    level = level_data(brushes=room(size=1600.0),
                       things=[make_thing(PlayerStart, "spawn", (100.0, 40.0, 100.0))]
                       + list(things))
    session = fio_session(level).start_play()
    session.clock = clock
    _step(session, 2)
    game = _Game(session.logic)
    game.stuck_arrows.install()
    # The hook closes over this test game and its LogicThread. Uninstall it
    # before fio_session closes the editor, so the session/window can collect.
    # Retain the exact LogicThread for deterministic teardown even if a
    # test explicitly uninstalls the game hook before fixture cleanup.
    fio_session._stuck_arrows_cleanup.append(
        (game.stuck_arrows, game, session.logic))
    return session, game


def _named(session, name):
    return next(t for t in session.state.things if t.properties.get("name") == name)


def _loose(session, start, vel, ammo="steel_arrow"):
    meta = {stuck_arrows.AMMO_KEY: ammo} if ammo else None
    return session.logic.combat_runtime.spawn_projectile(
        list(start), list(vel), lifetime=3.0, damage=5.0, max_dist=4000.0, metadata=meta)


def _fly(session, ticks=40):
    store = session.logic.combat_runtime._monster_projectiles
    for _ in range(ticks):
        _step(session)
        if not len(store):
            return


def _near(a, b, tol=0.5):
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def _shot_barrel(fio_session, clock, **props):
    """A barrel at (300, 0, 300) with one steel arrow loosed into it from the
    south, flying north (+z) at the barrel's middle."""
    session, game = _play(fio_session, clock, [_barrel("barrel", 300.0, 300.0, **props)])
    barrel = _named(session, "barrel")
    _loose(session, (300.0, HEIGHT, 0.0), (0.0, 0.0, 1600.0))
    _fly(session)
    return session, game, barrel


def test_an_arrow_that_hits_a_barrel_sticks_in_it(fio_session, clock):
    session, game, barrel = _shot_barrel(fio_session, clock)

    arrows = barrel.properties[KEY]
    assert len(arrows) == 1
    assert arrows[0]["item"] == "steel_arrow"
    # In the barrel's own frame: its south face, where it struck, pointing
    # the way it flew.
    assert _near(arrows[0]["at"], (0.0, HEIGHT, -RADIUS))
    assert _near(arrows[0]["dir"], (0.0, 0.0, 1.0), 1e-3)
    # It stopped: nothing flies on behind the barrel.
    assert len(session.logic.combat_runtime._monster_projectiles) == 0


def test_sticking_is_heard_where_it_struck(fio_session, clock):
    _session, game, _barrel_ = _shot_barrel(fio_session, clock)
    assert len(game.sounds) == 1
    name, pos = game.sounds[0]
    assert name == ARROW_THUNK_SOUND == "thunk.mp3"
    assert _near(pos, (300.0, HEIGHT, 300.0 - RADIUS))


def test_the_stuck_arrow_is_drawn_poking_out(fio_session, clock):
    _session, game, _barrel_ = _shot_barrel(fio_session, clock)
    game.stuck_arrows.update()
    (centre, heading, squash, sprite), = game.stuck_arrows.drawn
    # Behind its buried tip, along its flight; level, so drawn full length.
    assert centre[2] < 300.0 - RADIUS and _near(centre[:1], (300.0,))
    assert heading == pytest.approx(0.0, abs=1e-6)
    assert squash == pytest.approx(1.0)
    assert sprite.endswith("steel_arrow.png")


def test_the_arrow_moves_and_turns_with_the_barrel(fio_session, clock):
    _session, game, barrel = _shot_barrel(fio_session, clock)
    stuck = game.stuck_arrows

    # Pushed and turned a quarter about its upright axis.
    barrel.pos = [100.0, 0.0, -100.0]
    barrel.properties["rotation"] = [0.0, 90.0, 0.0]
    stuck.update()
    (tip, d, item), = stuck.world_arrows(barrel)
    assert _near(tip, (100.0 - RADIUS, HEIGHT, -100.0))
    assert _near(d, (1.0, 0.0, 0.0), 1e-3)
    assert item == "steel_arrow"
    assert len(stuck.drawn) == 1

    # Toppled onto its side: the arrow now points at the ground.
    barrel.properties["rotation"] = [90.0, 0.0, 0.0]
    stuck.update()
    (tip, d, _item), = stuck.world_arrows(barrel)
    assert _near(tip, (100.0, RADIUS, -100.0 + HEIGHT))
    assert _near(d, (0.0, -1.0, 0.0), 1e-3)
    # Seen from above, end on: drawn short.
    (_c, _h, squash, _s), = stuck.drawn
    assert squash < 0.5


def test_e_by_the_barrel_pulls_the_arrow_into_the_pack(fio_session, clock):
    from game.host import MiniwindGame
    from plugins.api import TickContext
    _session, game, barrel = _shot_barrel(fio_session, clock)
    game.stuck_arrows.update()
    logic = SimpleNamespace(
        interaction_runtime=SimpleNamespace(current_hud_message=""),
        player_runtime=SimpleNamespace(player=SimpleNamespace(pos=(300.0, 40.0, 220.0))))
    host = MiniwindGame()

    host._handle_interaction(logic, TickContext(logic=logic), game, set())
    assert "Pull the arrow from the barrel" in game.interact_prompt
    assert barrel.properties.get(KEY)            # only shown, not taken yet

    host._handle_interaction(logic, TickContext(logic=logic), game, {"e"})
    pack = game.game.character.inventory
    assert [(s["id"], s.get("qty", 1)) for s in pack] == [("steel_arrow", 1)]
    assert KEY not in barrel.properties
    assert game.notes and game.notes[-1].startswith("Picked up")
    assert game.stuck_arrows.drawn == ()
    assert game.stuck_arrows.nearest((300.0, 40.0, 220.0)) is None


def test_e_away_from_the_barrel_does_nothing(fio_session, clock):
    from game.host import MiniwindGame
    from plugins.api import TickContext
    _session, game, barrel = _shot_barrel(fio_session, clock)
    logic = SimpleNamespace(
        interaction_runtime=SimpleNamespace(current_hud_message=""),
        player_runtime=SimpleNamespace(player=SimpleNamespace(pos=(300.0, 40.0, -200.0))))

    MiniwindGame()._handle_interaction(logic, TickContext(logic=logic), game, {"e"})

    assert game.interact_prompt == ""
    assert game.game.character.inventory == []
    assert len(barrel.properties[KEY]) == 1


def test_one_press_pulls_every_arrow_as_the_ammo_it_was(fio_session, clock):
    session, game = _play(fio_session, clock, [_barrel("barrel", 300.0, 300.0)])
    barrel = _named(session, "barrel")
    _loose(session, (300.0, HEIGHT, 0.0), (0.0, 0.0, 1600.0), ammo="steel_arrow")
    _loose(session, (290.0, HEIGHT - 10.0, 0.0), (0.0, 0.0, 1600.0), ammo="iron_bolt")
    _loose(session, (450.0, HEIGHT, 300.0), (-1600.0, 0.0, 0.0), ammo="no_such_ammo")
    _fly(session)
    assert len(barrel.properties[KEY]) == 3

    assert game.stuck_arrows.pull(barrel) == 3
    ids = sorted(s["id"] for s in game.game.character.inventory)
    assert ids == ["iron_arrow", "iron_bolt", "steel_arrow"]    # unknown: plain arrows
    assert KEY not in barrel.properties


def test_the_e_press_is_claimed_from_picking_the_barrel_up(fio_session, clock):
    session, game, _barrel_ = _shot_barrel(fio_session, clock, carry_enabled=True)
    runtime = session.logic.prop_runtime
    assert runtime.use_claim == game.stuck_arrows.claims_use
    player = session.logic.player_runtime.player
    player.pos.x, player.pos.z = 300.0, 220.0
    assert game.stuck_arrows.claims_use()
    player.pos.x, player.pos.z = -300.0, -300.0
    assert not game.stuck_arrows.claims_use()
    game.stuck_arrows.uninstall()
    assert runtime.use_claim is None
    assert session.logic.combat_runtime.projectile_catcher is None


def test_a_projectile_that_is_not_an_arrow_flies_on(fio_session, clock):
    session, game = _play(fio_session, clock, [_barrel("barrel", 300.0, 300.0)])
    barrel = _named(session, "barrel")
    _loose(session, (300.0, HEIGHT, 0.0), (0.0, 0.0, 1600.0), ammo=None)
    _fly(session, ticks=20)
    assert KEY not in barrel.properties
    assert game.sounds == []


def test_an_arrow_sticks_in_an_explosive_barrel_and_dies_with_it(fio_session, clock):
    session, game, barrel = _shot_barrel(
        fio_session, clock, explosive=True, explosive_health=1000)
    explosions = session.logic.explosion_runtime
    assert explosions.damage_taken.get(id(barrel), 0.0) > 0.0     # it was struck
    assert len(barrel.properties[KEY]) == 1
    game.stuck_arrows.update()
    assert len(game.stuck_arrows.drawn) == 1

    explosions.explode_prop(barrel)
    game.stuck_arrows.update()
    # Destroyed in the blast: nothing drawn, nothing to pull.
    assert KEY not in barrel.properties
    assert game.stuck_arrows.drawn == ()
    assert game.stuck_arrows.nearest((300.0, 40.0, 220.0)) is None


def test_stuck_arrows_survive_a_save_and_load(fio_session, clock):
    """They are a public property of the barrel: a save keeps them, and
    loading it puts them back -- found again, drawn and pullable."""
    from engine import savegame
    session, game, barrel = _shot_barrel(fio_session, clock)
    logic = session.logic
    snapshot = savegame.build_snapshot(logic, map_name="stuck_arrows.json")

    assert game.stuck_arrows.pull(barrel) == 1          # taken after the save
    game.stuck_arrows.update()
    assert game.stuck_arrows.drawn == ()

    savegame.restore_auto(logic, snapshot, current_map_name="stuck_arrows.json")
    barrel = _named(session, "barrel")
    game.stuck_arrows.update()
    assert [a["item"] for a in barrel.properties[KEY]] == ["steel_arrow"]
    assert len(game.stuck_arrows.drawn) == 1
    assert game.stuck_arrows.nearest((300.0, 40.0, 220.0)) is barrel


def test_no_stuck_arrows_costs_nothing(fio_session, clock, monkeypatch):
    session, game = _play(fio_session, clock, [_barrel("barrel", 300.0, 300.0)])
    stuck = game.stuck_arrows
    stuck.update()

    def _boom(_prop):
        raise AssertionError("no barrel frame is needed without stuck arrows")

    monkeypatch.setattr(session.logic.explosion_runtime, "model_frame", _boom)
    for _ in range(5):
        stuck.update()
    assert stuck.drawn == ()
    assert stuck.nearest((300.0, 40.0, 220.0)) is None


def test_the_thunk_is_quiet_while_the_sound_file_is_missing(monkeypatch, tmp_path):
    """The game's own positional sound path skips a sound that is not there
    -- no error -- and plays it once the file is in assets/sounds."""
    import game.runtime as runtime
    queued = []
    owner = SimpleNamespace(logic=SimpleNamespace(
        game_state=SimpleNamespace(queue_sound=queued.append)))
    monkeypatch.setattr(runtime, "SOUND_DIR", str(tmp_path))
    monkeypatch.setattr(runtime, "_ARCHIVED_SOUNDS", frozenset())
    play = runtime.MiniwindSession.play_sound_at

    assert play(owner, ARROW_THUNK_SOUND, (1.0, 2.0, 3.0)) is False
    assert queued == []

    (tmp_path / ARROW_THUNK_SOUND).write_bytes(b"RIFF")
    assert play(owner, ARROW_THUNK_SOUND, (1.0, 2.0, 3.0)) is True
    assert queued[0]["file"] == "thunk.mp3"
    assert queued[0]["position"] == [1.0, 2.0, 3.0]


def test_the_cylinder_geometry():
    frame = ((-10.0, 0.0, -10.0), (10.0, 50.0, 10.0), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0), None)
    # Straight through the middle: in at the near face, out at the far.
    t = stuck_arrows.ray_cylinder(frame, (0.0, 25.0, -100.0), (0.0, 0.0, 1.0), 500.0)
    assert t == pytest.approx((90.0, 110.0))
    # Past the corner of its box: a miss (it is round, not square).
    d = (1.0 / math.sqrt(2.0), 0.0, 1.0 / math.sqrt(2.0))
    assert stuck_arrows.ray_cylinder(frame, (-25.0, 25.0, -7.0), d, 500.0) is None
    # Over the top.
    assert stuck_arrows.ray_cylinder(frame, (0.0, 60.0, -100.0), (0.0, 0.0, 1.0), 500.0) is None


def test_the_dense_projectile_path_catches_arrows_too(fio_session, clock, monkeypatch):
    """A swarm of projectiles takes the engine's batched path: an arrow in it
    sticks just the same."""
    session, game = _play(fio_session, clock, [_barrel("barrel", 300.0, 300.0)])
    monkeypatch.setattr(session.logic.combat_runtime, "PROJECTILE_DENSE_THRESHOLD", 0)
    barrel = _named(session, "barrel")
    _loose(session, (300.0, HEIGHT, 0.0), (0.0, 0.0, 1600.0))
    _fly(session)
    (arrow,) = barrel.properties[KEY]
    assert _near(arrow["at"], (0.0, HEIGHT, -RADIUS))


def test_the_players_arrow_carries_its_ammo_and_the_session_catches_it(coop_game):
    """In a real game session: the barrels' catcher is installed, and the
    player's arrow says which ammunition it is."""
    from game.rpg import equipment
    coop = coop_game.logic.game_session.coop
    human = coop.local_players[0]
    assert coop.logic.combat_runtime.projectile_catcher is coop.root.stuck_arrows
    c = human.session.game.character
    equipment.equip(c, "short_bow")
    assert human.session.game.fire_arrow()
    human.session._spawn_player_arrow_projectile()
    store = coop.logic.combat_runtime._monster_projectiles
    assert store.metadata_of(len(store) - 1)[stuck_arrows.AMMO_KEY] == "iron_arrow"


def test_an_archers_shot_carries_its_ammo():
    """An NPC's crossbow bolt says what it is, so one pulled from a barrel is
    a bolt."""
    from game.tests.test_combat_tactics import _archery, _crossbowman
    session, combat = _archery(retreating=True)
    combat.shots.clear()
    assert session.archery.shot_hook(_crossbowman(), [400.0, 0, 0], None, 400.0 ** 2)
    assert combat.shots[-1]["metadata"] == {stuck_arrows.AMMO_KEY: "iron_bolt"}
