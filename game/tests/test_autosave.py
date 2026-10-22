"""
Autosaves (game/autosave.py): every five minutes of play and on discovering a
new place, held back while the player is in danger or on a menu; and the
death screen's way back to the last one (game/ui/death_screen.py).

Run:  python -m pytest game/tests/test_autosave.py -q
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from .. import autosave
from ..autosave import Autosaver


def _session():
    c = NS(health=100.0, is_dead=False)
    return NS(game=NS(character=c), needs_char_creation=False,
              open_screen=None, dialogue=None)


def _saver():
    now = [1000.0]
    s = _session()
    return s, Autosaver(s, clock=lambda: now[0]), now


def test_a_save_falls_due_every_five_minutes_of_play():
    s, saver, now = _saver()
    for _ in range(299):
        saver.tick(1.0)
    assert saver.pending is None
    saver.tick(1.0)
    assert saver.pending == "timer" and saver.ready()
    assert saver.take() == "timer"
    assert saver.pending is None and saver.elapsed == 0.0


def test_discovering_a_place_saves_unless_one_was_just_made():
    s, saver, now = _saver()
    saver.discovered("Greywood")
    assert saver.pending == "discovered Greywood" and saver.ready()
    saver.take()
    now[0] += 10.0
    saver.discovered("Old Mill")
    assert saver.pending is None                     # moments after the last
    now[0] += autosave.MIN_GAP
    saver.discovered("Old Mill")
    assert saver.pending == "discovered Old Mill"


def test_a_timed_save_waits_out_danger_and_menus():
    s, saver, now = _saver()
    saver.tick(1.0)
    s.game.character.health = 60.0                   # hit
    saver.tick(autosave.INTERVAL)
    assert saver.pending == "timer" and not saver.ready()
    now[0] += autosave.SAFE_AFTER_HURT
    assert saver.ready()
    s.open_screen = "trade"
    assert not saver.ready()
    s.open_screen = None
    s.dialogue = object()
    assert not saver.ready()


def test_the_dead_are_never_saved():
    s, saver, now = _saver()
    saver.discovered("Greywood")
    s.game.character.is_dead = True
    assert not saver.ready()
    saver.tick(autosave.INTERVAL * 2)
    assert saver.elapsed == 0.0                      # death stops the clock


def test_the_death_screen_restores_the_autosave_on_a_click(qt_app, monkeypatch, tmp_path):
    import json
    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import death_screen

    restored = []

    class _Actions:
        window = NS(console_handler=NS(
            _resolve_save_path=lambda n: str(tmp_path / f"{n}.fiosave")))

        def autosave_info(self):
            return {"summary": "Aldric, level 3", "map": "", "saved_at": ""}

        def restore_autosave(self):
            restored.append(True)

    (tmp_path / "autosave.fiosave").write_text(json.dumps({}))
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda _ms, fn: fn()))
    view = NS(play_menu=NS(actions=_Actions()))
    img = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    death_screen.draw(p, view, 800, 600)
    p.end()
    assert death_screen.has_button()
    centre = death_screen.button("restore").center()
    assert not death_screen.press(view, 5, 5)
    assert death_screen.press(view, centre.x(), centre.y())
    assert restored == [True]


def _dead_view(tmp_path, autosave=True):
    """A stand-in view for the death screen: a dead player, the pause menu's
    actions and (with *autosave*) an autosave on disk."""
    import json
    calls = []

    class _Actions:
        window = NS(console_handler=NS(
            _resolve_save_path=lambda n: str(tmp_path / f"{n}.fiosave")))

        def autosave_info(self):
            return {"summary": "Aldric, level 3", "map": "", "saved_at": ""}

        def restore_autosave(self):
            calls.append("restore")

        def pause_menu_new_game(self):
            calls.append("new")

        def pause_menu_quit(self):
            calls.append("quit")

    class _Menu:
        actions = _Actions()

        def open_load(self):
            calls.append("load")

    if autosave:
        (tmp_path / "autosave.fiosave").write_text(json.dumps({}))
    session = NS(game=NS(character=NS(is_dead=True)), death_message=lambda: None)
    view = NS(play_menu=_Menu(), logic_thread=NS(_miniwind=session),
              update=lambda: None)
    return view, calls


def _paint_death_screen(view):
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import death_screen
    img = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    death_screen.draw(p, view, 800, 600)
    p.end()


def test_dying_offers_load_and_a_new_game_not_the_editor(qt_app, monkeypatch, tmp_path):
    from PyQt5.QtCore import QTimer
    from ..ui import death_screen
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda _ms, fn: fn()))
    view, calls = _dead_view(tmp_path, autosave=False)
    _paint_death_screen(view)
    # No autosave yet: still a way back, through a saved game or a new one.
    assert [k for k, _ in death_screen._buttons] == ["load", "new", "quit"]
    for key in ("load", "new"):
        centre = death_screen.button(key).center()
        assert death_screen.press(view, centre.x(), centre.y())
    assert calls == ["load", "new"]


def test_the_death_menu_answers_the_keyboard_and_swallows_escape(qt_app, monkeypatch, tmp_path):
    from PyQt5.QtCore import QEvent, QTimer, Qt
    from PyQt5.QtGui import QKeyEvent
    from ..ui import death_screen
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda _ms, fn: fn()))
    view, calls = _dead_view(tmp_path)
    _paint_death_screen(view)
    assert [k for k, _ in death_screen._buttons] == ["restore", "load", "new", "quit"]
    menu = death_screen.DeathMenu(view)
    key = lambda code: QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier)
    # Escape is taken (so the view never leaves Play for the editor) and does nothing.
    assert menu.handle_key(key(Qt.Key_Escape)) and calls == []
    death_screen._selected = 0
    assert menu.handle_key(key(Qt.Key_Down))
    assert menu.handle_key(key(Qt.Key_Down))
    assert menu.handle_key(key(Qt.Key_Return))
    assert calls == ["new"]
    assert not menu.handle_key(key(Qt.Key_F12))     # the view's own keys pass
    # A living player's keys are none of its business.
    view.logic_thread._miniwind.game.character.is_dead = False
    assert not menu.handle_key(key(Qt.Key_Escape))


# ------------------------------------------------------------ cause of death

def test_the_cause_of_death_names_the_weapon_and_the_killer():
    import random
    from .. import death_causes as dc
    T = lambda **p: NS(properties=p)
    rng = random.Random(1)
    guard = T(npc_role="guard", display_name="Kestrel the Guard", type="npc",
              _active_weapon="iron_dagger")
    line = dc.describe(guard, "attack", "physical", rng=rng)
    assert line.endswith("by Kestrel the Guard")
    assert line[:-len(" by Kestrel the Guard")] in dc.WEAPON_VERBS["dagger"]
    wolf = T(npc_role="wolf", display_name="Wolf", type="creature")
    assert dc.describe(wolf, "attack", rng=rng).endswith("by a wolf")
    assert dc.name_of(T(npc_role="villager", display_name="Mara", type="npc")) == "Mara, a villager"
    assert dc.name_of(T(npc_role="bandit_chief", display_name="Greenskin Warboss")) == \
        "the Greenskin Warboss"
    assert dc.name_of(T(npc_role="monster", name="Creature_19")) == "a fiend"
    archer = T(npc_role="guard_archer", display_name="Town Archer", type="npc")
    line = dc.describe(archer, "projectile", rng=rng)
    assert line.split(" by ")[0] in dc.PROJECTILE_VERBS["bow"] and line.endswith("a town archer")
    dragon = T(display_name="Dragon")
    assert dc.describe(dragon, "breath", "fire", rng=rng).split(" by ")[0] in dc.FIRE_VERBS
    assert dc.describe(None, "trigger", rng=rng, trap_name="Spike Pit").endswith(
        ("a spike pit", "a spike pit, fatally"))
    assert dc.describe(None, None, rng=rng) in dc.GENERIC_VERBS


def test_no_phrasing_says_by_twice():
    from .. import death_causes as dc
    pools = [v for d in (dc.WEAPON_VERBS, dc.PROJECTILE_VERBS, dc.CREATURE_VERBS)
             for lst in d.values() for v in lst]
    pools += (dc.BITE_VERBS + dc.FIRE_VERBS + dc.FROST_VERBS + dc.SHOCK_VERBS
              + dc.POISON_VERBS + dc.GENERIC_VERBS)
    assert len(set(pools)) >= 150
    assert not [v for v in pools if " by " in f" {v} "]


def test_the_session_remembers_who_dealt_the_killing_blow():
    """Through the real damage path: the engine records the attacker, the
    game's damage filter keeps it, and the dead player's line names them."""
    import random
    from .fio_logic import FioLogic
    from ..runtime import MiniwindSession

    class _Logic(FioLogic):
        def __init__(self):
            self.things = []
            self.player = NS(pos=[0.0, 0.0, 0.0], properties={"is_player": True})

    s = MiniwindSession(_Logic(), cfg={})
    s.rng = random.Random(2)
    s.needs_char_creation = False
    guard = NS(pos=[0.0, 0.0, 0.0], properties={
        "npc_role": "guard", "display_name": "Kestrel the Guard", "type": "npc",
        "_active_weapon": "iron_shortsword"})
    from .. import fio
    fio.player_runtime(s.logic).last_damage = (guard, "attack", "physical")
    s._blocking = False
    c = s.game.character
    c.health = 1.0
    for _ in range(50):
        if c.is_dead:
            break
        s._mitigate_incoming(999.0)
    assert c.is_dead
    line = s.death_message()
    assert line.endswith("by Kestrel the Guard")
    assert s.death_message() == line                  # chosen once per death
