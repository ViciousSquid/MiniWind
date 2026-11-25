"""A cast spell's icon over its caster's head: 0.3 s in, 1.5 s held, 0.25 s
out -- the player's casts and NPCs'; floating words sit above it."""
import pytest

from .. import runtime
from ..runtime import cast_icon_alpha
from .test_necromancy import _necromancer, _session, _body


@pytest.mark.parametrize("age, alpha", [(0.0, 0.0), (0.15, 0.5), (0.3, 1.0), (1.0, 1.0),
                                        (1.8, 1.0), (1.925, 0.5)])
def test_the_timeline(age, alpha):
    assert cast_icon_alpha(age) == pytest.approx(alpha)


def test_it_is_over_after_two_and_a_bit_seconds():
    total = runtime.CAST_ICON_FADE_IN + runtime.CAST_ICON_HOLD + runtime.CAST_ICON_FADE_OUT
    assert total == pytest.approx(2.05)
    assert cast_icon_alpha(total + 0.01) is None


def test_a_cast_shows_its_icon_until_it_has_faded():
    necro = _necromancer()
    s = _session(necro)
    s.show_cast(necro, "firebolt")
    import time
    t0 = s.cast_icons[id(necro)][2]
    assert s.live_cast_icons(t0 + 0.15) == [(necro, "firebolt", pytest.approx(0.5))]
    assert s.live_cast_icons(t0 + 1.0)[0][2] == pytest.approx(1.0)
    assert s.live_cast_icons(t0 + 3.0) == []
    assert id(necro) not in s.cast_icons


def test_an_npc_cast_that_works_shows_its_icon_and_a_fizzle_does_not(monkeypatch):
    import game.npc_magic as npc_magic
    necro = _necromancer(_aggro_target=1, spells=[{"id": "slow_time"}, {"id": "firebolt"}])
    s = _session(necro)
    monkeypatch.setattr(npc_magic.NpcMagic, "_fizzles", lambda self, t, sp: True)
    s.npc_magic.cast_spell(necro, "slow_time")
    assert not s.__dict__.get("cast_icons")
    monkeypatch.setattr(npc_magic.NpcMagic, "_fizzles", lambda self, t, sp: False)
    s.npc_magic.cast_spell(necro, "slow_time")
    assert s.cast_icons[id(necro)][1] == "slow_time"


def test_the_players_cast_shows_its_icon_over_the_player():
    s = _session()
    from game.rpg import magic
    player = s.player_actor
    assert player is not None
    s._magic_cast_fx(magic.get("firebolt"))
    assert s.cast_icons[id(player)][1] == "firebolt"


def test_a_dead_casters_icon_goes():
    necro = _necromancer()
    s = _session(necro)
    s.show_cast(necro, "firebolt")
    necro.properties["dead"] = True
    assert s.live_cast_icons() == []


def test_floating_words_rise_above_the_icon():
    from game.ui import hud
    necro = _necromancer()
    s = _session(necro)
    assert hud._cast_icon_lift(s) == {}
    s.show_cast(necro, "firebolt")
    import time
    s.cast_icons[id(necro)] = (necro, "firebolt", time.monotonic() - 0.5)
    assert hud._cast_icon_lift(s) == {id(necro): hud.CAST_ICON_SIZE / 2 + hud.CAST_ICON_GAP}


def test_the_icon_glows_on_top_of_the_caster(qt_app):
    """Emissive: the spell's colour lights the pixels round the icon, which
    is centred on the caster's head."""
    import glm
    from PyQt5.QtGui import QImage, QPainter, QColor
    from game.ui import hud
    necro = _necromancer()
    s = _session(necro)
    s.show_cast(necro, "firebolt")
    t0 = s.cast_icons[id(necro)][2]

    class _View:
        projection_matrix = glm.perspective(glm.radians(60.0), 1.0, 1.0, 5000.0)
        view_matrix = glm.lookAt(glm.vec3(0, 900, 1), glm.vec3(0, 0, 0), glm.vec3(0, 1, 0))
    img = QImage(400, 400, QImage.Format_ARGB32)
    img.fill(QColor(30, 30, 30))
    p = QPainter(img)
    hud.draw_cast_icons(p, s, _View, 400, 400, now=t0 + 1.0)
    p.end()
    sp = hud._head_screen(glm, _View.projection_matrix, _View.view_matrix, necro, 400, 400)
    cx, cy = int(sp[0]), int(sp[1])
    halo = img.pixelColor(cx + int(hud.CAST_ICON_SIZE * 0.6), cy)   # just outside the icon
    assert halo.red() > 60 and halo.red() > halo.blue()            # firebolt's warm light
    assert img.pixelColor(cx + 150, cy) == QColor(30, 30, 30)        # nothing far off
