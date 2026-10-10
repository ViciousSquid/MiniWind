"""The logic-thread hooks a built-in game layer installs.

None of them names a game concept, and with none installed the engine behaves
as Fio ships it. MiniWind installs all of them from its session:

* ``LogicThread.player_fire_handler(logic, mode)`` owns what the fire buttons
  do (``"primary"`` / ``"secondary"``); a handled shot skips Fio's weapon path
  (``LogicCombat._handle_shooting``);
* ``LogicThread._player_damage_filter(damage, kind)`` mitigates damage before
  health drops (``LogicTriggers._apply_player_damage``);
* ``ThreadedGameState.set_aim(direction, yaw)`` publishes pointer aim, and the
  play tick turns the player to the published yaw (``LogicPlayer``);
* ``LogicCombat.spawn_projectile`` launches a projectile with its own range,
  owner, ``on_hit(target)`` and ``on_impact(pos, target)``;
* ``LogicCamera.set_camera_focus`` holds the overhead camera on a point.

Behaviour is driven on a real LogicThread in Play.
"""

import glm
import pytest

pytest.importorskip("PyQt5", reason="drives the real editor state and logic thread")

from editor.editor_state import EditorState               # noqa: E402
from editor.things import Monster, PlayerStart            # noqa: E402
from engine.logic_combat import PLAYER_PROJECTILE_OWNER   # noqa: E402
from engine.logic_thread import LogicThread               # noqa: E402
from engine.player import Player                          # noqa: E402
from engine.threaded_game_state import ThreadedGameState  # noqa: E402
from tests.helpers.worlds import box_brush, make_thing    # noqa: E402

pytestmark = [pytest.mark.qt, pytest.mark.integration]

TICK = 1.0 / 60.0


@pytest.fixture
def playing():
    state = EditorState()
    state.brushes = [box_brush("floor", (0, -16, 0), (4096, 32, 4096)),
                     box_brush("wall", (0, 64, 800), (512, 256, 32))]
    target = make_thing(Monster, "target", (600, 0, 0), health=100, team="beasts")
    state.things = [make_thing(PlayerStart, "spawn", (0, 64, 0)), target]
    logic = LogicThread(ThreadedGameState(), state)
    logic.player_runtime.player = Player(0.0, 0.0)
    logic.player_runtime.player.pos.y = 40.0
    logic.session_runtime.apply_play_mode(True)
    # The AI thread is not under test here; keep the tick single-threaded.
    logic.session_runtime.stop_monster_ai()
    logic.target = target
    yield logic
    logic.session_runtime.apply_play_mode(False)
    logic.stop()


def _ticks(logic, n):
    for _ in range(n):
        logic._tick_play_mode(TICK)


def _store(logic):
    return logic.combat_runtime._monster_projectiles


def _emitted(logic):
    events = []
    logic._plugin_emit = lambda name, **payload: events.append((name, payload))
    return events


# ---------------------------------------------------------------------------
# Fire buttons
# ---------------------------------------------------------------------------

def test_primary_and_secondary_fire_reach_the_handler(playing):
    calls = []
    events = _emitted(playing)
    playing.player_fire_handler = lambda lt, mode: calls.append((lt, mode)) or True
    playing.combat_runtime._handle_shooting()
    playing.combat_runtime._handle_shooting(secondary=True)
    assert calls == [(playing, "primary"), (playing, "secondary")]
    assert [p["mode"] for n, p in events if n == "player_shoot"] == ["primary", "secondary"]


def test_a_handled_shot_never_falls_through_to_the_weapon(playing):
    combat = playing.combat_runtime
    combat.give_weapon(combat.items.resolve("gun1"))
    ammo = combat.player_ammo
    playing.player_fire_handler = lambda lt, mode: True
    combat._handle_shooting()
    assert combat.player_ammo == ammo
    assert not combat.muzzle_flash_active


def test_secondary_fire_without_a_handler_does_nothing(playing):
    combat = playing.combat_runtime
    combat.give_weapon(combat.items.resolve("gun1"))
    events = _emitted(playing)
    combat._handle_shooting(secondary=True)
    assert events == []
    assert not combat.muzzle_flash_active


def test_a_failing_handler_is_logged_and_counts_as_handled(playing):
    def boom(lt, mode):
        raise RuntimeError("bow string snapped")
    combat = playing.combat_runtime
    combat.give_weapon(combat.items.resolve("gun1"))
    events = _emitted(playing)
    playing.player_fire_handler = boom
    combat._handle_shooting()
    assert events and events[0][0] == "player_shoot"
    assert not combat.muzzle_flash_active


def test_the_game_state_queues_secondary_shots_like_primary_ones():
    gs = ThreadedGameState()
    assert gs.consume_secondary_shot() is False
    gs.queue_secondary_shot()
    gs.queue_shot()
    assert gs.consume_secondary_shot() is True
    assert gs.consume_secondary_shot() is False
    assert gs.consume_shot() is True


def test_both_fire_buttons_reach_the_handler_on_the_tick(playing):
    modes = []
    playing.player_fire_handler = lambda lt, mode: modes.append(mode) or True
    playing.game_state.queue_shot()
    playing.game_state.queue_secondary_shot()
    _ticks(playing, 1)
    assert modes == ["primary", "secondary"]


def test_fire_pressed_over_a_paused_world_is_dropped(playing):
    modes = []
    playing.player_fire_handler = lambda lt, mode: modes.append(mode) or True
    playing.session_runtime.set_world_paused("menu", True)
    playing.game_state.queue_secondary_shot()
    _ticks(playing, 1)
    playing.session_runtime.set_world_paused("menu", False)
    _ticks(playing, 1)
    assert modes == []


# ---------------------------------------------------------------------------
# Damage and aim
# ---------------------------------------------------------------------------

def test_the_damage_filter_mitigates_before_health_drops(playing):
    seen = []
    playing._player_damage_filter = lambda dmg, kind: seen.append((dmg, kind)) or dmg // 2
    start = playing.player_runtime.player_health
    playing.trigger_runtime._apply_player_damage(20, "fire")
    assert seen == [(20, "fire")]
    assert playing.player_runtime.player_health == start - 10


def test_the_default_damage_kind_is_physical(playing):
    seen = []
    playing._player_damage_filter = lambda dmg, kind: seen.append(kind) or dmg
    playing.trigger_runtime._apply_player_damage(5)
    assert seen == ["physical"]


def test_a_failing_damage_filter_leaves_the_damage_alone(playing):
    def boom(dmg, kind):
        raise RuntimeError("armour bug")
    playing._player_damage_filter = boom
    start = playing.player_runtime.player_health
    playing.trigger_runtime._apply_player_damage(7)
    assert playing.player_runtime.player_health == start - 7


def test_the_player_turns_to_the_published_aim(playing):
    player = playing.player_runtime.player
    playing.game_state.set_aim((1.0, 0.0, 0.0), yaw=1.25)
    _ticks(playing, 1)
    assert player.angle == pytest.approx(1.25)
    playing.game_state.set_aim()                          # pointer aim off
    player.angle = 0.5
    _ticks(playing, 1)
    assert player.angle == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Game projectiles
# ---------------------------------------------------------------------------

def _projectile(logic, start, vel, **kwargs):
    kwargs.setdefault("lifetime", 10.0)
    kwargs.setdefault("damage", 10)
    return logic.combat_runtime.spawn_projectile(start, vel, **kwargs)


def test_on_hit_resolves_the_damage_and_on_impact_reports_the_actor(playing):
    hits, impacts = [], []
    target = playing.target
    lift = playing.combat_runtime.PROJECTILE_MONSTER_LIFT
    _projectile(playing, (450, target.pos[1] + lift, 0), (600, 0, 0),
                on_hit=hits.append,
                on_impact=lambda pos, who: impacts.append((pos, who)))
    health = target.properties["health"]
    _ticks(playing, 30)
    assert hits == [target]
    assert impacts and impacts[0][1] is target
    assert isinstance(impacts[0][0], glm.vec3)
    assert target.properties["health"] == health, "on_hit owns the damage"
    assert not _store(playing).hooks, "a consumed projectile drops its callbacks"


def test_on_impact_reports_a_wall(playing):
    impacts = []
    _projectile(playing, (0, 64, 600), (0, 0, 600),
                on_impact=lambda pos, who: impacts.append(who))
    _ticks(playing, 40)
    assert impacts == [None]
    assert len(_store(playing)) == 0


def test_a_projectile_stops_at_its_own_range(playing):
    impacts = []
    _projectile(playing, (-2000, 64, 0), (-600, 0, 0), max_dist=120.0,
                on_impact=lambda *a: impacts.append(a))
    _ticks(playing, 10)                      # 100 units: still in flight
    assert len(_store(playing)) == 1
    _ticks(playing, 10)                      # 200 units: past its 120
    assert len(_store(playing)) == 0
    assert impacts == []                     # expiring is not an impact
    assert not _store(playing).hooks


def test_the_players_own_projectile_never_hits_the_player(playing):
    pp = playing.player_runtime.player.pos
    start = playing.player_runtime.player_health
    _projectile(playing, (pp.x - 10, pp.y, pp.z), (300, 0, 0))   # the player's
    _ticks(playing, 3)
    assert playing.player_runtime.player_health == start
    _projectile(playing, (pp.x - 10, pp.y, pp.z), (300, 0, 0),
                owner_id=id(playing.target))                     # the control
    _ticks(playing, 3)
    assert playing.player_runtime.player_health < start


def test_game_projectiles_are_published_for_the_renderer(playing):
    _projectile(playing, (-2000, 64, 0), (-60, 0, 0))
    _ticks(playing, 1)
    assert len(playing.combat_runtime.projectile_positions) == 1
    assert int(_store(playing).owner_id[0]) == PLAYER_PROJECTILE_OWNER


# ---------------------------------------------------------------------------
# Camera focus
# ---------------------------------------------------------------------------

def test_the_camera_glides_to_a_focus_and_back(playing, monkeypatch):
    camera = playing.camera
    clock = [100.0]
    monkeypatch.setattr("engine.logic_camera.time.perf_counter", lambda: clock[0])
    here = glm.vec3(0.0, 0.0, 0.0)
    camera.set_camera_focus((1000.0, 0.0, 0.0))
    assert camera.camera_focus == (1000.0, 0.0, 0.0)
    assert camera.focused_camera_centre(here).x == pytest.approx(0.0)
    clock[0] += camera.CAMERA_FOCUS_SECONDS
    assert camera.focused_camera_centre(here).x == pytest.approx(1000.0)
    camera.set_camera_focus(None)
    assert camera.camera_focus is None
    clock[0] += camera.CAMERA_FOCUS_SECONDS / 2
    assert 0.0 < camera.focused_camera_centre(here).x < 1000.0
    camera.set_camera_focus(None, glide=False)
    assert camera.focused_camera_centre(here).x == pytest.approx(0.0)


def test_every_session_starts_following_the_player(playing):
    playing.camera.set_camera_focus((50.0, 0.0, 50.0))
    playing.session_runtime.apply_play_mode(False)
    playing.session_runtime.apply_play_mode(True)
    playing.session_runtime.stop_monster_ai()
    assert playing.camera.camera_focus is None
