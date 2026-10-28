"""
Blood and screen shake: wounds spray and splash, the dead lie in pools, gibs
throw chunks, and the player's killing blows and criticals jolt the screen.

Run:  python -m pytest game/tests/test_blood.py -q
"""

from __future__ import annotations

import configparser

import numpy as np

import pytest

from .. import gore_fx, runtime
from .test_ember_tome import _FakePlayer, _FakeThing, _session


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _gore():
    clock = _Clock()
    return gore_fx.GoreFX(clock=clock), clock


def test_a_wound_sprays_blood_that_lands_and_stays():
    g, clock = _gore()
    g.wound([0, 0, 0], damage=20, max_health=30, away=(1, 0))
    assert g.particles and g.splats                 # the spray and the splash
    clock.t += 3.0
    g.update()
    assert not g.particles                          # everything has landed...
    assert len(g.splats) > 5                        # ...as blood on the ground
    clock.t += gore_fx.SPLAT_LIFE + 1
    g.update()
    assert not g.splats                             # and in time it dries away


def test_harder_blows_and_crits_bleed_more():
    light, _c = _gore()
    heavy, _c = _gore()
    light.wound([0, 0, 0], 2, 100)
    heavy.wound([0, 0, 0], 60, 100, crit=True)
    assert len(heavy.particles) > len(light.particles)


def test_a_kill_opens_a_spreading_pool_and_a_gib_throws_chunks():
    g, clock = _gore()
    g.kill([0, 0, 0], 40)
    pool = g.splats[-1]
    assert pool["kind"] == "pool"
    early = g.splat_size(pool)
    clock.t += gore_fx.POOL_SPREAD
    assert g.splat_size(pool) > early
    g.gib([0, 0, 0], 120)
    assert any(p["kind"] == "chunk" for p in g.particles)


def test_blood_is_capped():
    g, _c = _gore()
    for _ in range(400):
        g.wound([0, 0, 0], 50, 30, crit=True)
    assert len(g.particles) <= gore_fx.MAX_PARTICLES
    assert len(g.splats) <= gore_fx.MAX_SPLATS


def test_the_players_blood_and_the_red_flash_fade():
    g, clock = _gore()
    g.hurt(0.5)
    g.flash_red(0.5)
    assert g.screen and g.flash_level() > 0
    clock.t += gore_fx.SCREEN_BLOOD_SECONDS + 0.1
    g.update()
    assert not g.screen and g.flash_level() == 0


def test_the_camera_shakes_and_settles():
    from engine.logic_camera import LogicCamera
    cam = LogicCamera(host=None)
    cam.camera_mode = "Overhead"
    cam.shake(0.02, 0.3)
    assert cam.shake_level() > 0
    later = cam._shake[1] + 0.31
    assert cam.shake_level(later) == 0.0 and cam.shake_offset(later) == (0.0, 0.0)
    cam.shake(0.001, 0.3)                           # a weaker one does not cut it short
    assert cam._shake[0] == 0.02


@pytest.fixture
def config():
    config = configparser.ConfigParser()
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    yield config
    runtime.set_editor_config(previous)


def _bandit(**props):
    base = {"type": "npc", "name": "Brigand", "npc_role": "bandit", "health": 0,
            "max_health": 40}
    base.update(props)
    return _FakeThing([120.0, 56.0, 0.0], base)


def _shook(s, monkeypatch):
    shakes = []
    monkeypatch.setattr(s, "shake", lambda strength, seconds=0.3: shakes.append(strength))
    return shakes


def test_killing_blows_and_crits_shake_the_screen_and_plain_hits_do_not(config, monkeypatch):
    s = _session([], _FakePlayer([0, 0, 0]))
    shakes = _shook(s, monkeypatch)
    s._gore_hit(_bandit(health=20), 5)
    assert shakes == []
    s._gore_hit(_bandit(health=10), 15, crit=True)
    s._gore_hit(_bandit(), 30, killed=True)
    s._gore_hit(_bandit(gibbed=True), 90, killed=True)
    assert shakes == [runtime.CRIT_SHAKE[0], runtime.KILL_SHAKE[0], runtime.GIB_SHAKE[0]]
    assert s.gore.particles and s.gore.splats
    # A creature's blow on another bleeds, but only the player's own shake.
    shakes.clear()
    s.gore_npc_hit(_bandit(health=10), 30, attacker=_bandit())
    assert shakes == []


def test_bones_do_not_bleed(config):
    s = _session([], _FakePlayer([0, 0, 0]))
    s._gore_hit(_bandit(npc_role="skeleton"), 30, killed=True)
    assert not s.gore.particles and not s.gore.splats


def test_gore_and_shake_can_be_turned_off(config, monkeypatch):
    config.read_dict({"GAME": {"gore": "False", "screen_shake": "False"}})
    s = _session([], _FakePlayer([0, 0, 0]))
    assert not s.gore_enabled() and not s.screen_shake_enabled()
    s._gore_hit(_bandit(), 30, killed=True)
    assert not s.gore.particles and not s.gore.splats


def test_a_heavy_blow_on_the_player_bleeds_onto_the_screen(config, monkeypatch):
    s = _session([], _FakePlayer([0, 0, 0]))
    shakes = _shook(s, monkeypatch)
    s._gore_player_hurt(s.game.character.max_health * 0.4)
    assert s.gore.screen and shakes


# ------------------------------------------------- stamped into the ground
def test_settled_blood_is_stamped_and_then_forgotten_here():
    g, clock = _gore()
    taken = []
    g.stamp = lambda s: taken.append(s["kind"]) or True
    g.wound([0, 0, 0], 20, 30)
    g.kill([0, 0, 0], 30)
    g.update()
    assert "splash" in taken and "pool" not in taken     # a pool waits to spread
    assert any(s["kind"] == "pool" for s in g.splats)
    clock.t += gore_fx.POOL_SPREAD + 3.0
    for _ in range(20):
        g.update()
    assert "pool" in taken and not g.splats


def test_stamping_is_spread_over_updates():
    g, _c = _gore()
    taken = []
    g.stamp = lambda s: taken.append(1) or True
    for i in range(30):
        g._splat((i * 10.0, 0, 0), 20)
    g.update()
    assert len(taken) == gore_fx.STAMPS_PER_UPDATE


def test_blood_that_cannot_be_stamped_stays_drawn():
    g, _c = _gore()
    g.stamp = lambda s: False
    g.wound([0, 0, 0], 20, 30)
    g.update()
    assert g.splats and all(s.get("stamp_tried") for s in g.splats[:1])


def _flat_terrain():
    from engine.terrain import BiomeConfig, Terrain
    t = Terrain(seed=7)
    t.biome = BiomeConfig(name="Flat", base_height=100.0, height_scale=0.0,
                          hills_intensity=0.0,
                          color_gradient=[(0.0, (0.5, 0.5, 0.5)), (1.0, (0.5, 0.5, 0.5))])
    t.enabled = True
    return t


@pytest.mark.qt
def test_blood_is_baked_into_the_terrain_itself(config, monkeypatch, qt_app):
    from .. import fio
    terrain = _flat_terrain()
    monkeypatch.setattr(fio, "terrain", lambda logic: terrain)
    monkeypatch.setattr(fio, "ground_height", lambda logic, x, z, below=None: 100.0)
    s = _session([], _FakePlayer([0, 0, 0]))
    splat = {"x": 10.0, "y": 100.0, "z": 10.0, "size": 60.0, "kind": "pool",
             "seed": 0.3, "rot": 0.5}
    assert s._stamp_blood(splat)
    paint = terrain.washable_texture_paint_maps[(0, 0)]
    stained = paint[paint[..., 3] > 128]
    assert len(stained) and np.all(stained[:, 0] > stained[:, 1] * 3)   # it is red
    # On a floor built over the terrain it is not stamped (the HUD draws it).
    monkeypatch.setattr(fio, "ground_height", lambda logic, x, z, below=None: 160.0)
    assert not s._stamp_blood(splat)


def test_stamp_images_are_read_once():
    from engine.terrain import Terrain
    from .. import runtime as rt
    path = rt._blood_stamp("splash", 0.1)
    assert path and path.endswith(".png")
    Terrain._RGBA_CACHE.pop(path, None)
    reads = []
    real = Terrain._read_texture_rgba
    try:
        Terrain._read_texture_rgba = staticmethod(lambda p: reads.append(p) or real(p))
        a = Terrain._load_texture_rgba(path)
        b = Terrain._load_texture_rgba(path)
    finally:
        Terrain._read_texture_rgba = staticmethod(real)
    assert a is b and len(reads) == 1
