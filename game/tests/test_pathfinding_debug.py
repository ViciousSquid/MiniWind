"""The pathfinding tool is usable both interactively and from future scripts."""

import json
from types import SimpleNamespace

import pytest

from .. import console, pathfinding_debug as debug
from ..navigation import Navigator
from .test_navigation import Clock, enclosed


def session():
    actor = SimpleNamespace(pos=(24, 0, 24), properties={"display_name": "Town Guard",
                                                     "_dest": (1000, 0, 1000)})
    clock = Clock()
    nav = Navigator(enclosed, clock)
    world = SimpleNamespace(nav=nav, _live_actors=lambda: [actor],
                            _player_pos=lambda: (0, 0, 0))
    return world, actor, clock


def command(world, text, monkeypatch):
    logs = []
    monkeypatch.setattr(console, "debug_log", lambda category, text: logs.append((category, text)))
    ctx = console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=world), play_mode=True)
    console.cmd_paths(ctx, text)
    return logs


def test_explicit_on_off_are_idempotent_and_no_argument_toggles(monkeypatch):
    world, _, _ = session()
    for _ in range(2):
        command(world, "on", monkeypatch)
        assert world.show_paths
    for _ in range(2):
        command(world, "off", monkeypatch)
        assert not world.show_paths
    command(world, "", monkeypatch)
    assert world.show_paths


def test_export_contains_decisions_costs_and_actor_identity_without_planning(tmp_path, monkeypatch):
    world, actor, clock = session()
    command(world, "on", monkeypatch)
    world.nav.steer(id(actor), actor.pos, actor.properties["_dest"])
    clock.now = .25
    world.nav.steer(id(actor), actor.pos, actor.properties["_dest"])
    path = tmp_path / "path report.json"
    logs = command(world, f'export "{path}"', monkeypatch)
    assert logs[-1][0] == "Info"
    captured = json.loads(path.read_text())
    assert captured["schema_version"] == 1
    row = captured["actors"][0]
    assert row["name"] == "Town Guard"
    assert row["decision"] == "retry_wait"
    assert row["searches"] == 1 and row["failed_searches"] == 1
    assert row["searches_per_second"] == 4.0  # average over this .25-second observation
    assert row["expanded_nodes"] > 0 and row["search_ms"] >= 0
    assert row["last_search"]["outcome"] == "unreachable"
    assert debug.report(world)["summary"]["searches"] == 1


def test_filters_work_by_actor_name_id_state_and_radius(monkeypatch):
    world, actor, _ = session()
    command(world, "on", monkeypatch)
    world.nav.steer(id(actor), actor.pos, actor.properties["_dest"])
    command(world, 'actor "Town Guard"', monkeypatch)
    assert len(debug.actor_records(world)) == 1
    command(world, f"actor {id(actor)}", monkeypatch)
    assert len(debug.actor_records(world)) == 1
    command(world, "state route", monkeypatch)
    assert debug.actor_records(world) == []
    command(world, "state failed", monkeypatch)
    assert len(debug.actor_records(world)) == 1
    command(world, "radius 10", monkeypatch)
    assert debug.actor_records(world) == []
    command(world, "radius 3200", monkeypatch)
    command(world, "actor nobody", monkeypatch)
    assert debug.actor_records(world) == []
    command(world, "actor all", monkeypatch)
    assert len(debug.actor_records(world)) == 1


def test_debug_reads_bigworld_tiers_and_never_revives_dormant_actors(monkeypatch):
    from engine.spatial import SIM_TIER_KEY, TIER_DISTANT, TIER_DORMANT
    world, actor, _ = session()
    command(world, "on", monkeypatch)
    world.nav.steer_actor(actor, actor.pos, actor.properties["_dest"])
    actor.properties[SIM_TIER_KEY] = TIER_DISTANT
    command(world, "tier distant", monkeypatch)
    row = debug.actor_records(world)[0]
    assert row["tier"] == "DISTANT"
    assert row["decision"] == "bigworld_coarse" and not row["live_navigation"]
    assert row["points"] == ()  # no stale live route after a tier transition
    command(world, "tier near", monkeypatch)
    assert debug.actor_records(world) == []
    command(world, "tier all", monkeypatch)
    actor.properties[SIM_TIER_KEY] = TIER_DORMANT
    assert debug.actor_records(world) == []
    assert world.nav.search_stats()[id(actor)]["searches"] == 1


@pytest.mark.parametrize("text", ["radius nan", "radius -1", "state unknown", "on extra", 'actor "'])
def test_invalid_commands_preserve_configuration_and_report_errors(text, monkeypatch):
    world, _, _ = session()
    before = debug.settings(world)
    assert command(world, text, monkeypatch)[-1][0] == "Error"
    assert debug.settings(world) == before


def test_report_reset_and_disabled_instrumentation(monkeypatch):
    world, actor, _ = session()
    command(world, "on", monkeypatch)
    world.nav.steer(id(actor), actor.pos, actor.properties["_dest"])
    assert command(world, "report", monkeypatch)[-1][0] == "Info"
    command(world, "reset", monkeypatch)
    assert world.nav.search_stats() == {}
    command(world, "off", monkeypatch)
    assert debug.report(world)["actors"] == []


@pytest.mark.qt
def test_panel_controls_and_overlay_render_without_requesting_routes(qt_app):
    import glm
    from PyQt5.QtGui import QImage, QPainter
    from engine.floating_windows import WindowManager
    from engine.qt_game_view import _window_wants_cursor
    from ..ui.path_debug import draw, open_panel

    world, actor, _ = session()
    debug.configure(world, enabled=True)
    world.nav.steer(id(actor), actor.pos, actor.properties["_dest"])
    manager = WindowManager()
    view = SimpleNamespace(logic_thread=SimpleNamespace(_miniwind=world),
                           window_manager=manager, floating_windows=manager, play_mode=True,
                           update=lambda: None, projection_matrix=glm.mat4(1), view_matrix=glm.mat4(1))
    panel = open_panel(view)
    assert open_panel(view) is panel
    assert _window_wants_cursor(view)
    image = QImage(1280, 720, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        panel.draw(painter)
        draw(painter, world, view, 1280, 720)
    finally:
        painter.end()
    assert len(panel._buttons) == 17
    # Click the Paths on button, then the Failed state filter.
    centre = panel._buttons[0][0].center()
    panel.handle_body_click(centre.x(), centre.y())
    assert not world.show_paths
    panel._buttons[4][1]()
    assert debug.settings(world).state == "failed"
    assert world.nav.search_stats() == {}
