"""The LogicThread hooks a built-in game layer installs.

None of them names a game concept, and with none installed the engine behaves
as Fio ships it. MiniWind installs all of them from its session:

* ``player_fire_handler(logic, mode)`` owns what the fire buttons do
  (``"primary"`` / ``"secondary"``); a handled shot skips Fio's weapon path;
* ``_player_damage_filter(damage, kind)`` mitigates damage before health drops;
* ``ThreadedGameState.set_aim(direction, yaw)`` publishes pointer aim, and the
  play tick turns the player to the published yaw;
* a projectile may carry ``max_dist``, ``owner_is_player``, ``on_hit(target)``
  and ``on_impact(proj, pos, target)``.

Behaviour is driven on a real LogicThread; the fire-handler unit tests use a
minimal stand-in for what ``_handle_shooting`` reads.
"""

import glm
import pytest

pytest.importorskip("PyQt5", reason="drives the real editor state and logic thread")

from editor.editor_state import EditorState               # noqa: E402
from editor.things import Monster, PlayerStart            # noqa: E402
from engine.logic_thread import LogicThread               # noqa: E402
from engine.player import Player                          # noqa: E402
from engine.threaded_game_state import ThreadedGameState  # noqa: E402
from tests.helpers.worlds import box_brush, make_thing    # noqa: E402

pytestmark = [pytest.mark.qt, pytest.mark.integration]

TICK = 1.0 / 60.0


# ---------------------------------------------------------------------------
# Fire buttons
# ---------------------------------------------------------------------------

class _Shooter:
    """Just what _handle_shooting reads before it reaches the weapon path."""
    _handle_shooting = LogicThread._handle_shooting

    def __init__(self, handler=None, weapon=None):
        self.player = object()
        self.player_fire_handler = handler
        self.active_weapon = weapon
        self.events = []

    def _plugin_emit(self, name, **payload):
        self.events.append((name, payload))


def test_primary_and_secondary_fire_reach_the_handler():
    calls = []
    logic = _Shooter(handler=lambda lt, mode: calls.append((lt, mode)) or True)
    logic._handle_shooting()
    logic._handle_shooting(secondary=True)
    assert calls == [(logic, "primary"), (logic, "secondary")]
    assert [p["mode"] for n, p in logic.events if n == "player_shoot"] == ["primary", "secondary"]


def test_a_handled_shot_never_falls_through_to_the_weapon():
    logic = _Shooter(handler=lambda lt, mode: True, weapon="gun1")
    logic.game_state = None            # the weapon path would touch this
    logic._handle_shooting()           # must return before reaching it


def test_secondary_fire_without_a_handler_does_nothing():
    logic = _Shooter(handler=None, weapon="gun1")
    logic._handle_shooting(secondary=True)
    assert logic.events == []


def test_a_failing_handler_is_logged_and_counts_as_handled():
    def boom(lt, mode):
        raise RuntimeError("bow string snapped")
    logic = _Shooter(handler=boom, weapon="gun1")
    logic.game_state = None
    logic._handle_shooting()
    assert logic.events and logic.events[0][0] == "player_shoot"


def test_the_game_state_queues_secondary_shots_like_primary_ones():
    gs = ThreadedGameState()
    assert gs.consume_secondary_shot() is False
    gs.queue_secondary_shot()
    gs.queue_shot()
    assert gs.consume_secondary_shot() is True
    assert gs.consume_secondary_shot() is False
    assert gs.consume_shot() is True


# ---------------------------------------------------------------------------
# On a real logic thread
# ---------------------------------------------------------------------------

@pytest.fixture
def playing():
    state = EditorState()
    state.brushes = [box_brush("floor", (0, -16, 0), (4096, 32, 4096)),
                     box_brush("wall", (0, 64, 800), (512, 256, 32))]
    target = make_thing(Monster, "target", (600, 0, 0), health=100, team="beasts")
    state.things = [make_thing(PlayerStart, "spawn", (0, 64, 0)), target]
    logic = LogicThread(ThreadedGameState(), state)
    logic.player = Player(0.0, 0.0)
    logic.player.pos.y = 40.0
    logic.set_play_mode(True)
    logic._stop_monster_ai()
    logic.target = target
    yield logic
    logic.set_play_mode(False)
    logic.stop()


def _ticks(logic, n):
    for _ in range(n):
        logic._tick_play_mode(TICK)


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
    playing.set_world_paused("menu", True)
    playing.game_state.queue_secondary_shot()
    _ticks(playing, 1)
    playing.set_world_paused("menu", False)
    _ticks(playing, 1)
    assert modes == []


def test_the_damage_filter_mitigates_before_health_drops(playing):
    seen = []
    playing._player_damage_filter = lambda dmg, kind: seen.append((dmg, kind)) or dmg // 2
    start = playing.player_health
    playing._apply_player_damage(20, "fire")
    assert seen == [(20, "fire")]
    assert playing.player_health == start - 10


def test_the_default_damage_kind_is_physical(playing):
    seen = []
    playing._player_damage_filter = lambda dmg, kind: seen.append(kind) or dmg
    playing._apply_player_damage(5)
    assert seen == ["physical"]


def test_a_failing_damage_filter_leaves_the_damage_alone(playing):
    def boom(dmg, kind):
        raise RuntimeError("armour bug")
    playing._player_damage_filter = boom
    start = playing.player_health
    playing._apply_player_damage(7)
    assert playing.player_health == start - 7


def test_the_player_turns_to_the_published_aim(playing):
    playing.game_state.set_aim((1.0, 0.0, 0.0), yaw=1.25)
    _ticks(playing, 1)
    assert playing.player.angle == pytest.approx(1.25)
    playing.game_state.set_aim()                          # pointer aim off
    playing.player.angle = 0.5
    _ticks(playing, 1)
    assert playing.player.angle == pytest.approx(0.5)


def _projectile(logic, start, vel, **extra):
    proj = {"pos": list(start), "vel": list(vel), "owner_id": -1, "damage": 10,
            "lifetime": 10.0, "distance_travelled": 0.0}
    proj.update(extra)
    if not hasattr(logic, "_monster_projectiles"):
        logic._monster_projectiles = []
    logic._monster_projectiles.append(proj)
    return proj


def test_on_hit_resolves_the_damage_and_on_impact_reports_the_actor(playing):
    hits, impacts = [], []
    target = playing.target
    lift = playing.PROJECTILE_MONSTER_LIFT
    _projectile(playing, (450, target.pos[1] + lift, 0), (600, 0, 0),
                on_hit=hits.append,
                on_impact=lambda proj, pos, who: impacts.append((pos, who)))
    health = target.properties["health"]
    _ticks(playing, 30)
    assert hits == [target]
    assert impacts and impacts[0][1] is target
    assert isinstance(impacts[0][0], glm.vec3)
    assert target.properties["health"] == health, "on_hit owns the damage"


def test_on_impact_reports_a_wall(playing):
    impacts = []
    _projectile(playing, (0, 64, 600), (0, 0, 600),
                on_impact=lambda proj, pos, who: impacts.append(who))
    _ticks(playing, 40)
    assert impacts == [None]
    assert not playing._monster_projectiles


def test_a_projectile_stops_at_its_own_range(playing):
    impacts = []
    proj = _projectile(playing, (-2000, 64, 0), (-600, 0, 0), max_dist=120.0,
                       on_impact=lambda *a: impacts.append(a))
    _ticks(playing, 10)                      # 100 units: still in flight
    assert proj in playing._monster_projectiles
    _ticks(playing, 10)                      # 200 units: past its 120
    assert proj not in playing._monster_projectiles
    assert impacts == []                     # expiring is not an impact


def test_the_players_own_projectile_never_hits_the_player(playing):
    pp = playing.player.pos
    start = playing.player_health
    _projectile(playing, (pp.x - 10, pp.y, pp.z), (300, 0, 0), owner_is_player=True)
    _ticks(playing, 3)
    assert playing.player_health == start
    _projectile(playing, (pp.x - 10, pp.y, pp.z), (300, 0, 0))     # the control
    _ticks(playing, 3)
    assert playing.player_health < start


def test_projectile_records_are_published_for_the_renderer(playing):
    _projectile(playing, (-2000, 64, 0), (-60, 0, 0), kind="arrow", color=[1, 2, 3])
    _ticks(playing, 1)
    assert [r.get("kind") for r in playing._projectile_records] == ["arrow"]
    assert len(playing._projectile_positions) == 1
