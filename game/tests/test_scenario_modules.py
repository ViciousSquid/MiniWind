"""Tests for the reusable world-scenario module boundary."""

from .test_dynamic_mode import _build, _trader, _world


def test_the_director_registers_each_existing_scenario_once():
    world = _world()
    assert set(world.director.modules) == {
        "waylaid", "avenger", "reckoning", "gratitude",
        "patrol", "ambush", "procession", "cult_rite",
    }
    assert all(module.kind == kind for kind, module in world.director.modules.items())


def test_a_scenario_can_be_invoked_without_dynamic_pacing():
    world = _world(mode="normal")
    _trader(world.board)
    _build(world)

    assert not world.director.enabled()
    scene = world.director.invoke("waylaid", 12.0)

    assert scene is not None
    assert scene["kind"] == "waylaid"
    assert scene["id"] in world.director.scenes
    assert set(scene["journeys"]) == {"victim", "attacker"}
