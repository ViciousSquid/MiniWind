"""A corpse: its head gone grey with the heads folder's cross on it, the cross
fading after a few seconds (game/corpse_sprites.py). Alive is colour, dead is
greyscale; a gibbed body has no corpse at all."""

from types import SimpleNamespace

import pytest
from PIL import Image

from .. import corpse_sprites as cs

ROOT = cs._root()
HEAD = "assets/sprites/heads/head01.png"
CHICKEN = "assets/sprites/heads/chicken.png"


def _open(rel):
    return Image.open(f"{ROOT}/{rel}").convert("RGBA")


def _is_grey(px):
    r, g, b, a = px
    return a == 0 or (abs(r - g) <= 1 and abs(g - b) <= 1)


def test_the_cross_is_the_heads_folders_never_fios_monster_one():
    assert cs.CROSS == "assets/sprites/heads/dead.png"
    assert _open(cs.CROSS).size == (128, 128)


def test_dead_is_the_head_gone_grey_with_the_cross_in_its_own_colours():
    out = cs.corpse_sprite(HEAD, 0)
    assert out.startswith(cs.CACHE_DIR + "/")
    corpse, head, cross = _open(out), _open(HEAD), _open(cs.CROSS)
    assert corpse.size == head.size
    w, h = head.size
    for x in range(0, w, 7):
        for y in range(0, h, 7):
            c, hd, cr = corpse.getpixel((x, y)), head.getpixel((x, y)), cross.getpixel((x, y))
            if cr[3] == 0:
                assert _is_grey(c)                     # the head: grey
                assert c[3] == round(hd[3] * cs.DEAD_OPACITY)   # its shape, at 90%
            elif cr[3] == 255:
                assert c[:3] == cr[:3]                 # the cross: its own colours


def test_once_the_cross_has_faded_it_is_the_grey_head_alone():
    out = cs.corpse_sprite(HEAD, cs.FADE_STEPS)
    corpse, head = _open(out), _open(HEAD)
    expected = head.getchannel("A").point(lambda v: int(round(v * cs.DEAD_OPACITY)))
    assert corpse.getchannel("A").tobytes() == expected.tobytes()
    assert cs.DEAD_OPACITY == 0.9
    assert all(_is_grey(corpse.getpixel((x, y))) for x in range(0, 128, 5) for y in range(0, 128, 5))


def test_a_chicken_gets_the_same_cross_as_a_crab_and_its_head_stays_its_size():
    from ..rpg import heads
    crab_px, chicken_px = heads.size_for({}, "crab01"), heads.size_for({}, "chicken")
    assert (crab_px, chicken_px) == (64, 50) and cs.MIN_CROSS_PX == crab_px
    crab = _open(cs.corpse_sprite("assets/sprites/heads/crab01.png", 0, crab_px))
    chick = _open(cs.corpse_sprite(CHICKEN, 0, chicken_px))
    assert crab.size == (128, 128)                       # the crab: its cross is its head
    canvas = round(128 * cs.MIN_CROSS_PX / chicken_px)
    assert chick.size == (canvas, canvas)               # the chicken: a larger canvas
    # Drawn at their dead sizes, the two crosses are the same size...
    assert cs.dead_size(crab_px) == cs.dead_size(chicken_px) == 64
    # ...and the chicken's head, in the middle of its canvas, is still 50 px.
    head_on_screen = 128 * cs.dead_size(chicken_px) / canvas
    assert head_on_screen == pytest.approx(chicken_px, abs=0.5)
    head = _open(CHICKEN)
    off = (canvas - 128) // 2
    opaque = [(x, y) for x in range(0, 128, 8) for y in range(0, 128, 8)
              if head.getpixel((x, y))[3] == 255 and _open(cs.CROSS).resize(
                  (canvas, canvas)).getpixel((x + off, y + off))[3] == 0]
    assert opaque and all(_is_grey(chick.getpixel((x + off, y + off))) for x, y in opaque)


def test_a_small_corpse_is_drawn_at_the_crabs_size_and_back_to_its_own_if_revived():
    now = [0.0]
    fader = cs.CorpseFader(clock=lambda: now[0])
    hen = SimpleNamespace(properties={"custom_idle": CHICKEN, "dead": True,
                                      "sprite_width": 50, "sprite_height": 50})
    fader.update([hen])
    p = hen.properties
    assert (p["sprite_width"], p["sprite_height"], p["_alive_size"]) == (64, 64, 50)
    assert p["custom_dead"] == cs.corpse_sprite(CHICKEN, 0, 50)
    p["dead"] = False
    assert cs.restore_size(p) and (p["sprite_width"], p["sprite_height"]) == (50, 50)
    big = SimpleNamespace(properties={"custom_idle": HEAD, "dead": True, "sprite_width": 128})
    fader.update([big])
    assert big.properties["sprite_width"] == 128 and "_alive_size" not in big.properties


@pytest.mark.parametrize("age, alpha", [(0.0, 1.0), (2.9, 1.0), (3.0, 1.0),
                                        (3.5, 0.5), (4.0, 0.0), (9.0, 0.0)])
def test_the_cross_holds_three_seconds_then_fades(age, alpha):
    assert cs.cross_alpha(age) == pytest.approx(alpha)


def test_mark_gives_the_living_the_full_cross_and_a_loaded_corpse_none():
    alive = {"custom_idle": HEAD}
    assert cs.mark(alive) and alive["custom_dead"] == cs.corpse_sprite(HEAD, 0)
    corpse = {"custom_idle": HEAD, "dead": True}
    cs.mark(corpse)
    assert corpse["custom_dead"] == cs.corpse_sprite(HEAD, cs.FADE_STEPS)
    assert corpse["_cross_faded"]


def test_never_fios_corpse_even_when_the_image_cannot_be_made():
    p = {"custom_idle": "assets/sprites/heads/no_such_head.png"}
    cs.mark(p)
    assert p["custom_dead"] == "assets/sprites/heads/no_such_head.png"   # the plain look


def test_the_fader_steps_a_new_corpse_through_the_fade():
    now = [100.0]
    fader = cs.CorpseFader(clock=lambda: now[0])
    body = SimpleNamespace(properties={"custom_idle": HEAD, "dead": True})
    touched = []
    fader.update([body], touch=touched.append)
    assert body.properties["custom_dead"] == cs.corpse_sprite(HEAD, 0)
    now[0] += 2.0
    fader.update([body], touch=touched.append)
    assert body.properties["custom_dead"] == cs.corpse_sprite(HEAD, 0)   # still full
    now[0] += 1.5                                                        # 3.5 s: half
    fader.update([body], touch=touched.append)
    assert body.properties["custom_dead"] == cs.corpse_sprite(HEAD, cs.FADE_STEPS // 2)
    now[0] += 1.0
    fader.update([body], touch=touched.append)
    assert body.properties["custom_dead"] == cs.corpse_sprite(HEAD, cs.FADE_STEPS)
    assert body.properties["_cross_faded"] and touched
    count = len(touched)
    fader.update([body], touch=touched.append)
    assert len(touched) == count                                         # done with it


def test_a_gibbed_body_gets_no_cross_and_the_engine_draws_no_corpse():
    fader = cs.CorpseFader(clock=lambda: 0.0)
    gibbed = SimpleNamespace(properties={"custom_idle": HEAD, "dead": True, "gibbed": True})
    fader.update([gibbed])
    assert "custom_dead" not in gibbed.properties
    from engine.entity_table import _monster_sprite_candidates
    assert _monster_sprite_candidates({"dead": True, "gibbed": True, "custom_dead": "x.png"}) == ()
    whole = _monster_sprite_candidates({"dead": True, "custom_dead": cs.corpse_sprite(HEAD, 0)})
    assert whole[0][1].endswith("__0.png")                           # the grey head and cross


def test_revived_is_colour_again_and_the_next_death_has_a_cross():
    from engine.entity_table import _monster_sprite_candidates
    p = {"custom_idle": HEAD, "dead": True, "_cross_faded": True,
         "custom_dead": cs.corpse_sprite(HEAD, cs.FADE_STEPS)}
    p["dead"] = False                                                 # revived
    alive = _monster_sprite_candidates(p)
    assert alive[0][1] == "head01.png"                                # the colour head
    p.pop("_cross_faded")
    cs.mark(p)
    assert p["custom_dead"] == cs.corpse_sprite(HEAD, 0)              # a cross next time


def test_only_in_play_do_actors_get_a_corpse_image():
    from ..entities import NPC
    cs.ACTIVE = False
    try:
        editor_npc = NPC(pos=[0, 0, 0], properties={"name": "a", "head": "head01"})
        assert "custom_dead" not in editor_npc.properties            # maps stay clean
        cs.ACTIVE = True
        play_npc = NPC(pos=[0, 0, 0], properties={"name": "b", "head": "head01"})
        assert play_npc.properties["custom_dead"] == cs.corpse_sprite(HEAD, 0)
    finally:
        cs.ACTIVE = False


def test_the_players_corpse_is_grey_with_a_fading_cross_and_colour_when_alive(monkeypatch):
    import time
    from .test_bow_draw import _session
    s, _shots = _session()
    s.logic.player_head_sprite = HEAD
    assert s.overhead_player_corpse() is None                         # alive: colour
    s.game.character.health = 0
    assert s.game.character.is_dead
    clock = [50.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    grey, cross, alpha = s.overhead_player_corpse()
    assert grey == cs.corpse_sprite(HEAD, cs.FADE_STEPS) and cross == cs.CROSS and alpha == 1.0
    clock[0] += 3.5
    assert s.overhead_player_corpse()[2] == pytest.approx(0.5)
    clock[0] += 5.0
    assert s.overhead_player_corpse()[2] == 0.0
    s.game.character.health = 50                                      # revived
    assert s.overhead_player_corpse() is None
