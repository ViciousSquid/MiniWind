"""Slow Time: the world at half speed for 5 s (+1 s a level past 5), tinted
icy blue -- all but its caster, who keeps their own speed (twice the world's),
wears an icy fisheye bubble and gives off a flickering blue light."""
from types import SimpleNamespace

import pytest

from .test_corpse_loot import _Thing, _Logic
from .test_sim import _FakeGlobals


def _session():
    from ..runtime import MiniwindSession
    logic = _Logic([])
    logic.player = _Thing("You", (0.0, 0.0, 0.0), is_player=True)
    logic.time_scale = 1.0
    s = MiniwindSession(logic, cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    return s


@pytest.fixture
def clock(monkeypatch):
    """Real time, stepped by the test."""
    import time
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    return now


def _player(s):
    from .. import fio
    return fio.player(s.logic)


def _rate(s, thing):
    from .. import fio
    return fio.actor_time_rate(s.logic, thing)


def test_slow_time_lasts_five_seconds_and_a_second_a_level_past_five():
    from ..runtime import slow_time_seconds
    assert [slow_time_seconds(n) for n in range(1, 11)] == [
        5.0, 5.0, 5.0, 5.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]


def test_it_is_a_spell_the_game_knows():
    import game.rpg.magic as magic
    spell = magic.get("slow_time")
    assert spell is not None and spell.delivery == magic.SELF
    assert [e["kind"] for e in spell.effects] == ["slow_time"]


def test_the_world_runs_at_half_speed_then_as_before(clock):
    s = _session()
    s.logic.time_scale = 1.5                     # the debug tools' speed
    assert s.slow_time(7) == pytest.approx(7.0)
    assert s.logic.time_scale == pytest.approx(0.75)
    clock[0] += 0.2
    assert 0.0 < s.slow_time_tint() < 1.0        # fading in
    clock[0] += 3.0
    assert s.slow_time_tint() == pytest.approx(1.0)
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(0.75)
    clock[0] += 4.0                              # 7.2 s since the cast
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(1.5) and s.slow_time_tint() == 0.0


def test_the_caster_is_not_slowed(clock):
    """The world's clock runs at half speed, the caster's at twice the
    world's: their normal speed in real time."""
    s = _session()
    s.slow_time(1)
    assert s.slow_time_caster() is _player(s)
    assert _rate(s, _player(s)) == pytest.approx(2.0)
    npc = _Thing("Guard", (100.0, 0.0, 0.0), type="npc")
    assert _rate(s, npc) == 1.0
    clock[0] += 5.1
    s._update_slow_time()
    assert _rate(s, _player(s)) == 1.0 and s.slow_time_caster() is None


def test_the_casters_own_timers_run_at_its_speed_in_the_tick(clock):
    """Cooldowns, swings and the bow draw are the caster's: a slowed world's
    tick takes twice its delta off them."""
    s = _session()
    s._cast_cooldown = s._attack_cooldown = 1.0
    s._attack_anim_time = 0.2
    s.tick(0.05)
    plain = 1.0 - s._cast_cooldown
    s._cast_cooldown = s._attack_cooldown = 1.0
    s._attack_anim_time = 0.2
    s.slow_time(1)
    s.tick(0.05)
    assert 1.0 - s._cast_cooldown == pytest.approx(2.0 * plain)
    assert 1.0 - s._attack_cooldown == pytest.approx(2.0 * plain)
    assert s._attack_anim_time == pytest.approx(max(0.0, 0.2 - 2.0 * 0.05))


def test_an_npc_caster_is_the_one_not_slowed(clock):
    s = _session()
    mage = _Thing("Necromancer", (50.0, 56.0, 0.0), type="npc", creature_level=8,
                  sprite_height=112)
    assert s.slow_time(8, caster=mage) == pytest.approx(8.0)
    assert s.logic.time_scale == pytest.approx(0.5)
    assert _rate(s, mage) == pytest.approx(2.0) and _rate(s, _player(s)) == 1.0
    assert s.slow_time_caster() is mage


def test_npc_magic_casts_it_for_the_caster(clock):
    """Through the NPC spell path: the caster's creature level sets how long,
    and the caster is the one left at its own speed."""
    from .. import npc_magic
    s = _session()
    mage = _Thing("Necromancer", (50.0, 56.0, 0.0), type="npc", creature_level=7,
                  spells=["slow_time"], magicka=500, max_magicka=500)
    s.npc_magic._fizzles = lambda thing, spell: False
    s.npc_magic.cast_spell(mage, "slow_time")
    assert s.slow_time_left() == pytest.approx(7.0)
    assert s.slow_time_caster() is mage and _rate(s, mage) == pytest.approx(2.0)
    assert npc_magic is not None


def test_a_second_caster_takes_it_over(clock):
    """One Slow Time at a time: recast it lasts the longer, and the newer
    caster is the one not slowed (and wears the bubble and the light)."""
    s = _session()
    s.slow_time(1)                               # the player: 5 s
    clock[0] += 1.0
    mage = _Thing("Necromancer", (300.0, 56.0, 0.0), type="npc")
    s.slow_time(10, caster=mage)                 # 10 s from now
    assert s.slow_time_left() == pytest.approx(10.0)
    assert _rate(s, mage) == pytest.approx(2.0) and _rate(s, _player(s)) == 1.0
    assert s.logic.time_scale == pytest.approx(0.5)      # not slowed twice
    s._update_slow_time()
    assert s.slow_time_light().pos[0] == pytest.approx(300.0)
    assert s.slow_time_lenses()[0][0] == pytest.approx(300.0)


def test_it_ends_when_its_caster_falls(clock):
    s = _session()
    mage = _Thing("Necromancer", (50.0, 56.0, 0.0), type="npc")
    s.slow_time(1, caster=mage)
    mage.properties["dead"] = True
    s._update_slow_time()
    assert s.slow_time_left() == 0.0 and s.logic.time_scale == 1.0
    assert _rate(s, mage) == 1.0 and s.slow_time_light() is None


def test_nothing_else_lets_it_lapse(clock):
    """Anything that puts the world's speed back meanwhile is overruled on the
    next tick; a speed the debug tools pick becomes the one it slows."""
    s = _session()
    s.slow_time(1)
    s.logic.time_scale = 1.0                     # put back behind its back
    clock[0] += 0.25
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(0.5)
    assert s.slow_time_left() == pytest.approx(4.75)
    s.logic.time_scale = 2.0                     # the debug tools: 2x
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(1.0)
    clock[0] += 5.0
    s._update_slow_time()
    assert s.logic.time_scale == pytest.approx(2.0)


# -- the quick bar: the real cast path ------------------------------------------
def _bar_session():
    from .test_spell_quickbar import _session as quickbar_session
    s = quickbar_session()
    s.logic.time_scale = 1.0
    c = s.game.character
    c.known_spells.append("slow_time")
    c.magicka = c.max_magicka = 300
    s.set_strip_slot(3, "spell:slow_time")
    return s


def test_cast_from_the_quick_bar_it_lasts_its_full_time(clock, monkeypatch):
    """Regression: cast with its number key (select_strip_slot ->
    cast_from_strip -> do_cast), Slow Time must still be running a quarter
    of a second later -- and through every tick the game runs, the playing
    tick, a paused world's and a cutscene's -- until its seconds are up."""
    import game.rpg.magic as rpg_magic
    from .test_spell_quickbar import _press
    monkeypatch.setattr(rpg_magic, "cast_check", lambda *a, **k: (True, {}))
    s = _bar_session()
    before = s.game.character.magicka
    _press(s, "4")
    assert s.game.character.magicka < before
    assert "Time slows…" in [n.get("text") for n in s.notifications]
    for step, tick in enumerate((s.tick, s.tick_ui, s.cutscene_tick) * 5):
        clock[0] += 0.05
        tick(0.05 * s.logic.time_scale)
        assert s.slow_time_left() > 0.0, (step, tick)
    assert s.slow_time_left() == pytest.approx(5.0 - 0.75)
    assert s.slow_time_tint() == pytest.approx(1.0)
    assert s.logic.time_scale == pytest.approx(0.5)
    assert _rate(s, _player(s)) == pytest.approx(2.0)
    assert s.slow_time_light() is not None and s.slow_time_lenses()
    clock[0] += 4.3
    s.tick(0.05)
    assert s.slow_time_left() == 0.0 and s.logic.time_scale == 1.0
    assert s.slow_time_light() is None and not s.slow_time_lenses()


def test_a_fizzled_cast_from_the_bar_says_so_and_slows_nothing(clock, monkeypatch):
    import game.rpg.magic as rpg_magic
    from .test_spell_quickbar import _press
    monkeypatch.setattr(rpg_magic, "cast_check",
                        lambda *a, **k: (False, {"roll_result": 4, "target": 15}))
    s = _bar_session()
    _press(s, "4")
    notes = [n.get("text") for n in s.notifications]
    assert any("fizzles" in str(n) for n in notes) and "Time slows…" not in notes
    assert s.slow_time_left() == 0.0 and s.logic.time_scale == 1.0


# -- the light -------------------------------------------------------------------
def test_the_caster_gives_off_a_flickering_icy_light_that_follows_them(clock):
    from .. import fio
    from ..runtime import (SLOW_TIME_COLOUR, SLOW_TIME_LIGHT_INTENSITY,
                           SLOW_TIME_LIGHT_RADIUS, SLOW_TIME_FLICKER_FLOOR)
    s = _session()
    assert s.slow_time_light() is None
    s.slow_time(1)
    light = s.slow_time_light()
    assert light is not None and light in fio.things(s.logic)
    p = light.properties
    assert tuple(p["colour"]) == SLOW_TIME_COLOUR and not p["casts_shadows"]
    assert p["radius"] == pytest.approx(SLOW_TIME_LIGHT_RADIUS, rel=0.07)
    clock[0] += 0.5                               # past the fade-in
    seen = []
    for _ in range(40):
        clock[0] += 0.013
        s._update_slow_time()
        seen.append(p["intensity"])
    peak = SLOW_TIME_LIGHT_INTENSITY
    assert min(seen) >= peak * SLOW_TIME_FLICKER_FLOOR - 1e-6   # never out
    assert max(seen) <= peak + 1e-6
    assert max(seen) - min(seen) > 0.15 * peak                 # it flickers
    steps = [abs(b - a) for a, b in zip(seen, seen[1:])]
    assert len({round(d, 3) for d in steps}) > 10              # irregularly
    player = _player(s)
    player.pos = [400.0, 0.0, -250.0]
    s._update_slow_time()
    assert (light.pos[0], light.pos[2]) == pytest.approx((400.0, -250.0))
    clock[0] += 5.0
    s._update_slow_time()
    assert s.slow_time_light() is None and light not in fio.things(s.logic)


def test_the_light_fades_in_and_out_with_the_spell(clock):
    s = _session()
    s.slow_time(1)
    p = s.slow_time_light().properties
    assert p["intensity"] == pytest.approx(0.0)
    clock[0] += 0.1
    s._update_slow_time()
    rising = p["intensity"]
    clock[0] += 1.0
    s._update_slow_time()
    assert 0.0 < rising < p["intensity"]
    clock[0] += 3.8                               # 0.1 s left
    s._update_slow_time()
    assert p["intensity"] < rising * 1.5


def test_the_flicker_jitters_between_six_and_twelve_hertz_and_never_goes_out():
    import numpy as np
    from ..runtime import slow_time_flicker, SLOW_TIME_FLICKER_FLOOR
    t = np.arange(0.0, 8.0, 1.0 / 400.0)
    k = np.array([slow_time_flicker(x) for x in t])
    assert k.min() >= SLOW_TIME_FLICKER_FLOOR and k.max() <= 1.0
    power = np.abs(np.fft.rfft(k - k.mean())) ** 2
    freqs = np.fft.rfftfreq(len(k), 1.0 / 400.0)
    band = power[(freqs >= 5.5) & (freqs <= 12.5)].sum()
    assert band > 0.8 * power.sum()


# -- the bubble ------------------------------------------------------------------
def test_the_bubble_is_round_the_caster_while_it_lasts(clock):
    from ..runtime import (SLOW_TIME_BUBBLE_SCALE, SLOW_TIME_CASTER_HEIGHT,
                           SLOW_TIME_BUBBLE_LENS, SLOW_TIME_BUBBLE_FILL)
    s = _session()
    assert s.slow_time_lenses() == []
    s.slow_time(1)
    assert s.slow_time_lenses() == []             # the very first instant: nothing yet
    clock[0] += 1.0
    (x, y, z, strength, radius, rim, colour, shimmer, fill), = s.slow_time_lenses()
    assert (x, z) == (0.0, 0.0) and y == pytest.approx(SLOW_TIME_CASTER_HEIGHT / 2)
    assert radius == pytest.approx(SLOW_TIME_CASTER_HEIGHT * SLOW_TIME_BUBBLE_SCALE, rel=0.11)
    assert strength == pytest.approx(SLOW_TIME_BUBBLE_LENS, rel=0.06)
    assert SLOW_TIME_BUBBLE_LENS >= 0.55                  # a strong fisheye
    assert fill == pytest.approx(SLOW_TIME_BUBBLE_FILL)
    assert colour[2] > colour[1] > colour[0]      # icy blue
    clock[0] += 3.9                               # fading out
    faded = s.slow_time_lenses()[0]
    assert faded[8] < fill and faded[3] < strength * 0.95
    clock[0] += 0.2
    s._update_slow_time()
    assert s.slow_time_lenses() == []


def test_the_bubble_gently_pulses_larger_and_smaller(clock):
    from ..runtime import (SLOW_TIME_BUBBLE_SCALE, SLOW_TIME_CASTER_HEIGHT,
                           SLOW_TIME_BUBBLE_PULSE, SLOW_TIME_BUBBLE_PULSE_HZ)
    s = _session()
    s.slow_time(10)                               # long enough to watch it
    clock[0] += 1.0                               # fully in
    radii = []
    period = 1.0 / SLOW_TIME_BUBBLE_PULSE_HZ
    for k in range(24):
        radii.append(s.slow_time_lenses()[0][4])
        clock[0] += period / 24
    base = SLOW_TIME_CASTER_HEIGHT * SLOW_TIME_BUBBLE_SCALE
    assert max(radii) == pytest.approx(base * (1 + SLOW_TIME_BUBBLE_PULSE), rel=0.02)
    assert min(radii) == pytest.approx(base * (1 - SLOW_TIME_BUBBLE_PULSE), rel=0.02)
    assert 1.5 <= period <= 3.0                   # gentle: a breath, not a flicker


def test_the_bubble_projects_to_a_tinted_lens_on_screen():
    import glm
    from ..ui import magic_gl
    proj = glm.perspective(glm.radians(60.0), 16 / 9, 1.0, 5000.0)
    view = glm.lookAt(glm.vec3(0, 900, 1), glm.vec3(0, 0, 0), glm.vec3(0, 1, 0))
    lens = (0.0, 56.0, 0.0, 0.6, 168.0, 0.94, (0.47, 0.75, 1.0), 0.35, 0.55)
    (cx, cy, r, s, progress, colour, shimmer, fill), = magic_gl.project_lenses(
        proj, view, [lens], 1280, 720)
    assert (cx, cy) == pytest.approx((0.5, 0.5), abs=0.01)
    assert 0.05 < r < 0.5 and fill == pytest.approx(0.55)
    # An impact's lens (eight values) still projects, with no fill.
    impact = magic_gl.project_lenses(proj, view, [lens[:8]], 1280, 720)[0]
    assert impact[7] == 0.0


def test_the_host_draws_the_bubble_only_while_it_lasts(clock, monkeypatch):
    """The GL pass is asked for nothing at all when no Slow Time runs."""
    import game.host as host
    from ..ui import magic_gl
    drawn = []
    monkeypatch.setattr(magic_gl, "draw_lenses", lambda p, v, lenses: drawn.append(list(lenses)))
    monkeypatch.setattr(magic_gl, "draw_sprites", lambda *a, **k: 0)
    s = _session()
    s.magic_fx = None
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    game._host = SimpleNamespace(logic=SimpleNamespace(_miniwind=s))
    ev = {"play_mode": True, "projection": None, "view": None}
    game._on_post_scene(ev)
    assert drawn == []
    s.slow_time(1)
    clock[0] += 1.0
    game._on_post_scene(ev)
    assert len(drawn) == 1 and len(drawn[0]) == 1 and drawn[0][0][8] > 0.0
    clock[0] += 5.0
    s._update_slow_time()
    game._on_post_scene(ev)
    assert len(drawn) == 1


# -- the end of it ---------------------------------------------------------------
def test_leaving_the_map_ends_it(clock):
    from .. import fio
    s = _session()
    s.slow_time(1)
    light = s.slow_time_light()
    s.uninstall()
    assert s.logic.time_scale == 1.0 and s.slow_time_left() == 0.0
    assert fio.actor_time_rates(s.logic) == {}
    assert light not in fio.things(s.logic)


def test_a_save_made_while_it_lasts_loads_at_the_worlds_own_speed(clock):
    """Nothing of it rides the save: a session made from it starts unslowed."""
    s = _session()
    s.slow_time(1)
    s.persist(force=True)
    assert not any("slow" in str(k).lower() for k in s.store.all())
    s.uninstall()
    t = _session()
    assert t.slow_time_left() == 0.0 and t.slow_time_lenses() == []
    assert t.logic.time_scale == 1.0


def test_the_screen_takes_an_icy_tint(qt_app):
    from PyQt5.QtGui import QImage, QPainter, QColor
    from ..ui import hud
    s = _session()
    s.slow_time(1)
    s._slow_time_from -= 1.0                     # past the fade-in
    img = QImage(64, 64, QImage.Format_ARGB32)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    hud.draw_slow_time(p, s, 64, 64)
    p.end()
    c = img.pixelColor(10, 10)
    assert c.blue() > c.red() > 0


def test_casting_slow_time_plays_its_sound(monkeypatch):
    from .. import runtime
    s = _session()
    played = []
    monkeypatch.setattr(type(s), "play_ui_sound", lambda self, name, volume=1.0: played.append(name) or True)
    s.slow_time(1)
    assert played == [runtime.SLOW_TIME_SOUND] and runtime.SLOW_TIME_SOUND == "slowtime.wav"


@pytest.mark.gl
def test_the_bubble_bends_and_tints_the_frame_in_gl():
    """The real lens pass over a striped frame: inside the bubble the stripes
    are magnified and tinted icy blue, a bright rim rings it, and outside it
    the frame is untouched."""
    import numpy as np
    import OpenGL.GL as gl
    import glm
    from tests.helpers import gl as glh
    from ..ui import magic_gl
    size = 160
    with glh.GLTestContext(size, size) as ctx:
        ctx.bind()
        # Vertical grey stripes, 8 px wide.
        gl.glEnable(gl.GL_SCISSOR_TEST)
        for x in range(0, size, 8):
            v = 0.8 if (x // 8) % 2 else 0.2
            gl.glScissor(x, 0, 8, size)
            gl.glClearColor(v, v, v, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        before = ctx.read_pixels().astype(int)
        ctx.bind()
        proj = glm.ortho(-200.0, 200.0, -200.0, 200.0, 1.0, 2000.0)
        view = glm.lookAt(glm.vec3(0, 0, 500), glm.vec3(0, 0, 0), glm.vec3(0, 1, 0))
        lens = (0.0, 0.0, 0.0, 0.32, 100.0, 0.94, (0.47, 0.75, 1.0), 0.0, 0.55)
        assert magic_gl.draw_lenses(proj, view, [lens]) == 1
        after = ctx.read_pixels().astype(int)
        magic_gl._S.ok = None                      # the context goes; so do its programs
        magic_gl._S.tex_size = (0, 0)
        magic_gl._S.fbo = magic_gl._S.tex = 0
    mid = size // 2
    r_px = 100.0 / 400.0 * size                     # the bubble's radius on screen
    # Outside: as it was.
    assert np.abs(after[5, 5] - before[5, 5]).max() <= 2
    assert np.abs(after[mid, 2] - before[mid, 2]).max() <= 2
    # Inside: bluer than the grey it was.
    inside = after[mid - 8:mid + 8, mid - 8:mid + 8].reshape(-1, 3)
    assert (inside[:, 2] - inside[:, 0]).mean() > 10
    # Magnified: fewer stripe edges across the middle than before.
    def edges(row):
        light = row.mean(axis=1) > 128
        return int((light[1:] != light[:-1]).sum())
    span = slice(int(mid - r_px * 0.5), int(mid + r_px * 0.5))
    assert edges(after[mid, span]) < edges(before[mid, span])
    # A bright icy rim at the edge.
    rim = after[mid, int(mid + r_px * 0.965) - 1:int(mid + r_px * 0.965) + 2]
    assert rim[:, 2].max() > 200
