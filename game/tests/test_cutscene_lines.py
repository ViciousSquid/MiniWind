"""A cutscene's SAY / THINK keyframes and its battles' combat tick, on the
game side (Fio's ``cutscene.line`` and ``cutscene.tick``)."""
from .test_corpse_loot import _Thing, _Logic
from .test_sim import _FakeGlobals


def _session():
    from ..runtime import MiniwindSession
    logic = _Logic([])
    logic.player = _Thing("You", (0.0, 0.0, 0.0), is_player=True)
    s = MiniwindSession(logic, cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    return s


def test_a_cutscene_line_shows_however_far_the_player_is():
    from ..runtime import BARK_RADIUS
    s = _session()
    far = _Thing("Herald", (BARK_RADIUS * 5, 0.0, 0.0), type="npc")
    s.bark(far, "ignored: too far from the player")
    assert s.live_barks() == []
    s.cutscene_line("say", far, "Hear me, people of the Vale!", 4.0)
    s.cutscene_line("think", far, "Will they listen?", 2.0)
    (said,), (thought,) = s.live_barks(), s.live_thoughts()
    assert said[:2] == (far, "Hear me, people of the Vale!") and 3.5 < said[2] <= 4.0
    assert thought[:2] == (far, "Will they listen?") and 1.5 < thought[2] <= 2.0


def test_a_cutscene_line_comes_before_anyone_elses_chatter():
    s = _session()
    chatter = [_Thing(f"Villager {i}", (10.0 * i, 0.0, 0.0), type="npc") for i in range(10)]
    for v in chatter:
        s.bark(v, "Fine weather.")
    hero = _Thing("Hero", (5.0, 0.0, 0.0), type="npc")
    s.cutscene_line("say", hero, "To arms!")
    assert s.live_barks()[0][0] is hero


def test_a_shouted_cutscene_line_wakes_no_one():
    s = _session()
    heard = []
    s.make_noise = lambda *a: heard.append(a)
    s.cutscene_line("say", _Thing("Captain", (0.0, 0.0, 0.0), type="npc"), "Charge!")
    assert not heard


def test_the_cutscene_tick_runs_combat_not_the_world(monkeypatch):
    s = _session()
    ran = []
    monkeypatch.setattr(s.archery, "update", lambda dt: ran.append("archery"))
    monkeypatch.setattr(s.burning, "update", lambda dt: ran.append("burning"))
    monkeypatch.setattr(s.gore, "update", lambda: ran.append("gore"))
    hour = s.clock.hour
    s.cutscene_tick(0.5)
    assert {"archery", "burning", "gore"} <= set(ran)
    assert s.clock.hour == hour                       # the world's clock is held


def test_played_cutscenes_are_remembered_with_the_save():
    s = _session()
    assert s.played_cutscenes() == set()
    s.remember_cutscene("intro-cam")
    s.remember_cutscene("battle-cam")
    s.remember_cutscene("intro-cam")
    assert s.played_cutscenes() == {"intro-cam", "battle-cam"}
    # Kept in the save's store, which travels with level changes and saves.
    import json
    assert json.loads(s.store.get("cutscenes_played")) == ["battle-cam", "intro-cam"]
