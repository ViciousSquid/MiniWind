"""Every cast is heard: spellcast.mp3 for any spell that works, sizzle.mp3 for
one that fizzles, resurrection.mp3 for a resurrection; a discovery plays
discover.mp3; "Block" stands over the player's head while blocking."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .. import runtime
from ..rpg import equipment as eq
from .test_cast_controls import _Logic, _Thing


def _session(monkeypatch, *present):
    s = runtime.MiniwindSession(_Logic(), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    queued = []
    s.logic.game_state = SimpleNamespace(queue_sound=queued.append)
    monkeypatch.setattr(runtime, "sound_available", lambda name: name in present)
    c = s.game.character
    c.can_use_magic = lambda: True
    c.magicka = c.max_magicka = 500
    s._spawn_player_spell_projectile = lambda spell, aim=None: None
    s._acquire_target = lambda reach, aim_dot=None: None
    return s, queued


def _files(queued):
    return [q["file"] for q in queued]


@pytest.mark.parametrize("spell", ["flare", "heal_minor", "sp_calm"])   # projectile, self, target
def test_every_spell_that_works_plays_spellcast_once(monkeypatch, spell):
    s, queued = _session(monkeypatch, "spellcast.mp3", "sizzle.mp3")
    c = s.game.character
    c.known_spells = [spell]
    eq.equip_spell(c, spell, "main")
    s.game.cast_active_spell = lambda: SimpleNamespace(cast=True, reason="", roll=None)
    assert s.do_cast(aim="facing", hand="main")
    assert _files(queued) == ["spellcast.mp3"]
    assert queued[0]["position"] == s._player_pos() and not queued[0].get("global")


def test_knock_plays_spellcast(monkeypatch):
    s, queued = _session(monkeypatch, "spellcast.mp3")
    c = s.game.character
    c.known_spells = ["knock"]
    eq.equip_spell(c, "knock", "main")
    chest = _Thing("Chest", locked=True)
    s.nearest_knock_target = lambda: chest
    s.game.cast_active_spell = lambda: SimpleNamespace(cast=True, reason="", roll=None)
    assert s.do_cast(aim="facing", hand="main")
    assert _files(queued) == ["spellcast.mp3"]


def test_a_fizzle_plays_sizzle_and_not_spellcast(monkeypatch):
    s, queued = _session(monkeypatch, "spellcast.mp3", "sizzle.mp3")
    c = s.game.character
    c.known_spells = ["flare"]
    eq.equip_spell(c, "flare", "main")
    s.game.cast_active_spell = lambda: SimpleNamespace(cast=False, reason="fizzle", roll=None)
    assert not s.do_cast(aim="facing", hand="main")
    assert _files(queued) == ["sizzle.mp3"]
    assert queued[0]["position"] == s._player_pos()          # from the caster: the player
    assert not queued[0].get("global")


def test_a_casters_cast_and_fizzle_are_heard_where_it_stands(monkeypatch):
    s, queued = _session(monkeypatch, "spellcast.mp3", "sizzle.mp3")
    caster = _Thing("Cultist", (120.0, 0.0, 40.0))
    s.cast_sound(caster)
    s.fizzled(caster)
    assert _files(queued) == ["spellcast.mp3", "sizzle.mp3"]
    assert all(q["position"] == [120.0, 0.0, 40.0] and not q.get("global") for q in queued)


def test_npc_magic_reports_a_working_cast():
    from ..npc_magic import NpcMagic
    heard = []
    magic = NpcMagic.__new__(NpcMagic)
    magic.session = SimpleNamespace(cast_sound=heard.append)
    thing = object()
    magic._cast_sound(thing)
    assert heard == [thing]


def test_resurrection_plays_its_own_sound_not_spellcast(monkeypatch):
    s, queued = _session(monkeypatch, "spellcast.mp3", "resurrection.mp3")
    body = _Thing("Fallen", (60.0, 0.0, 0.0), type="npc", dead=True, health=0, max_health=40)
    s._nearest_dead_actor = lambda reach, aim=None: body
    s._revive_actor = lambda target: True
    s._restore_living_kit = lambda p: None
    s._bind_raised = lambda p: None
    spell = runtime.rpg_magic.get("resurrection")
    s._do_resurrect(spell, aim="facing")
    assert _files(queued) == ["resurrection.mp3"]


def test_resurrection_is_silent_until_its_sound_is_added(monkeypatch):
    s, queued = _session(monkeypatch, "spellcast.mp3")
    body = _Thing("Fallen", (60.0, 0.0, 0.0), type="npc", dead=True)
    s._nearest_dead_actor = lambda reach, aim=None: body
    s._revive_actor = lambda target: True
    s._restore_living_kit = lambda p: None
    s._bind_raised = lambda p: None
    s._do_resurrect(runtime.rpg_magic.get("resurrection"), aim="facing")
    assert queued == []                                     # never spellcast instead


# --------------------------------------------------------------- discovery
def test_discovering_a_place_plays_discover(monkeypatch):
    s, queued = _session(monkeypatch, "discover.mp3")
    town = _Thing("town", (0.0, 0.0, 50.0), type="marker", marker_kind="location",
                  place_name="Ashby", discover_radius=200.0)
    s.logic.things.append(town)
    s._type_index_token = None
    s.autosave = SimpleNamespace(discovered=lambda name: None)
    s._tick_locations()
    assert _files(queued) == ["discover.mp3"]
    s._tick_locations()
    assert _files(queued) == ["discover.mp3"]               # once only


# ------------------------------------------------------------------ block
@pytest.mark.qt
def test_block_stands_over_the_players_head_while_held(qt_app, monkeypatch):
    import glm
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import hud
    s, _queued = _session(monkeypatch)
    drawn = []
    monkeypatch.setattr(hud, "_world_to_screen", lambda *a: (200.0, 120.0))
    view = SimpleNamespace(projection_matrix=glm.mat4(1), view_matrix=glm.mat4(1))
    image = QImage(400, 300, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    real = painter.drawText

    def spy(*args):
        drawn.append(args[-1])
        return real(*args)
    painter.drawText = spy
    try:
        hud.draw_player_block(painter, s, view, 400, 300)
        assert drawn == []                                  # not blocking
        s.toggle_block(True)
        hud.draw_player_block(painter, s, view, 400, 300)
    finally:
        painter.end()
    assert hud.BLOCK_TEXT in drawn
