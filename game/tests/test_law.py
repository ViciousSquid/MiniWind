"""The watch is local, fallible, and reached by an actual walking witness."""

from types import SimpleNamespace

import pytest

from ..runtime import MiniwindSession
from ..sim import appraisal, crime, knowledge
from ..sim.director import actor_key
from ..sim.law import Writs, SEARCH_HOURS, SEARCH_RADIUS
from .test_sim import _FakeGlobals, _FakeLogic, _Store, _Thing, _player
from .test_npc_movement import _AI


def _scene(*extra):
    witness = _Thing("Wick", (120, 0, 0), type="npc", faction="villagers",
                     courage=0.5, sight_range=700)
    guard = _Thing("Kestrel", (2500, 0, 0), type="npc", npc_role="guard",
                   faction="guards", combatant=True, aggression="defensive")
    player = _player()
    logic = _FakeLogic([witness, guard, *extra], player)
    session = MiniwindSession(logic, cfg={"region_name": "Millbrook", "start_hour": 12},
                              globals_store=_FakeGlobals())
    session.game.character.gold = 5000
    session._refresh_actor_cache()
    return session, witness, guard


def _theft(session):
    return session.emit_event("theft", target="farmer", value=30)


def _reported(session, witness, guard):
    ev = _theft(session)
    witness.pos = [guard.pos[0] - 100, 0, guard.pos[2]]
    session.director.resolve_reports(session._sim_actors())
    return ev


def test_witness_message_is_immediate_once_per_crime_and_no_bounty_yet():
    session, witness, guard = _scene()
    other = _Thing("Mara", (150, 0, 0), type="npc")
    session.logic.things.append(other)
    _theft(session)
    texts = [n["text"] for n in session.notifications]
    assert texts.count("Someone witnessed your crime.") == 1
    assert session.game.character.bounty == 0
    session.director.resolve_reports(session._sim_actors())
    assert session.game.character.bounty == 0


def test_unseen_and_lawful_events_do_not_show_witness_message():
    session, witness, guard = _scene()
    witness.pos = [5000, 0, 5000]
    _theft(session)
    session.emit_event("attack", crime=False)
    assert not any("witnessed your crime" in n["text"] for n in session.notifications)


def test_hearing_cannot_identify_the_culprit_or_create_a_bounty():
    session, witness, guard = _scene()
    witness.properties["sight_range"] = 0
    session.emit_event("attack", target="farmer")
    marker = session.witness_markers()[0]
    assert not marker["identified"]
    witness.pos = [2400, 0, 0]
    session.director.resolve_reports(session._sim_actors())
    assert session.game.character.bounty == 0
    intent = session.director.top_intent(guard)
    assert intent.reaction == appraisal.INVESTIGATE
    session._apply_sim_intent(guard)
    assert guard.properties["_dest"] == [0, 0, 0]


def test_maps_follow_the_actual_witness_and_remove_it_on_report_or_death():
    from ..ui.worldmap import map_features
    session, witness, guard = _scene()
    _theft(session)
    session._apply_sim_intent(witness)
    marker = session.witness_markers()[0]
    assert marker["identified"] and marker["reporting"]
    witness.pos = [300, 0, 90]
    assert map_features(session)["witnesses"][0]["z"] == 90
    witness.properties["dead"] = True
    assert not session.witness_markers()
    witness.properties["dead"] = False
    witness.pos = [2400, 0, 0]
    session.director.resolve_reports(session._sim_actors())
    assert not session.witness_markers()
    assert session.law.bounty("Millbrook") == 55


def test_witness_retargets_the_nearest_living_guard_and_physically_routes_around_walls():
    farther = _Thing("Other watchman", (800, 0, 1000), type="npc", npc_role="guard")
    session, witness, guard = _scene(farther)
    guard.pos = [0, 0, 1400]
    farther.pos = [800, 0, 1400]
    witness.pos = [0, 0, 0]
    session.logic.player.pos = [0, 0, 0]
    session.logic.monster_ai = _AI([(-400, 400, 200, 260)])
    _theft(session)
    session._apply_sim_intent(witness)
    assert witness.properties["_dest"] == guard.pos
    guard.properties["dead"] = True
    session._apply_sim_intent(witness)
    assert witness.properties["_dest"] == farther.pos
    guard.properties["dead"] = False
    max_x = 0
    for _ in range(350):
        session._apply_sim_intent(witness)
        session._move(witness, 0.1)
        max_x = max(max_x, abs(witness.pos[0]))
        session.director.resolve_reports(session._sim_actors())
        if session.game.character.bounty:
            break
    assert max_x > 400, "the witness must go around the wall"
    assert session.law.bounty("Millbrook") == 55


def test_a_dead_witness_cannot_testify_even_if_left_in_the_actor_list():
    session, witness, guard = _scene()
    _theft(session)
    witness.pos = list(guard.pos)
    witness.properties["dead"] = True
    session.director.resolve_reports([witness, guard])
    assert session.law.total == 0


def test_a_robbed_victim_seeks_the_watch_and_can_wake_the_guard():
    session, witness, guard = _scene()
    guard.properties.update(sched_state="SLEEPING", asleep=True)
    session.emit_event("theft", target=witness, value=30)
    session._apply_sim_intent(witness)
    assert witness.properties["sched_state"] == "REPORT"
    assert witness.properties["_dest"] == guard.pos
    witness.pos = [2400, 0, 0]
    session.director.resolve_reports(session._sim_actors())
    assert not guard.properties["asleep"]
    assert session.law.total == 55


def test_witness_seeks_a_guardpost_when_no_guard_survives():
    post = _Thing("Watch post", (800, 0, 0), type="marker", marker_kind="guardpost")
    session, witness, guard = _scene(post)
    _theft(session)
    guard.properties["dead"] = True
    session._apply_sim_intent(witness)
    assert witness.properties["_dest"] == post.pos
    assert session.game.character.bounty == 0


def test_saved_search_rallies_guards_at_last_sighting_even_when_player_is_far():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    session._arrest_region = "Millbrook"
    session.law.sighted("Millbrook", [2400, 0, 0], session._law_now())
    session.logic.player.pos = [9000, 0, 0]
    session.law.search("Millbrook", session._player_pos(), session._law_now())
    session.law.persist()
    session.law = Writs(session.store)
    session._start_arrest_pursuit()
    assert guard in session._arrest_pursuers
    session._update_arrest_pursuit()
    assert session.law_status()["phase"] == "search"
    assert session.law_status()["centre"] == [2400, 0, 0]


def test_uninformed_guard_does_not_magically_know_a_writ():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    stranger = _Thing("Uninformed watch", (50, 0, 0), type="npc", npc_role="guard")
    session.logic.things.append(stranger)
    session._update_arrest()
    assert not session._arrest_state
    assert not session._guard_knows_writ(stranger, "Millbrook")
    fact = knowledge.facts(session.store, actor_key(guard))[0]
    knowledge.tell(session.store, actor_key(guard), actor_key(stranger), fact)
    session._update_arrest()
    assert session._arrest_guard is stranger


def test_escape_freezes_last_sighting_and_keeps_the_local_debt():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    session.logic.player.pos = [2400, 0, 0]
    session._update_arrest()
    session._start_arrest_pursuit()
    session._update_arrest_pursuit()
    sighting = list(session.law.record("Millbrook")["last_pos"])
    session.logic.player.pos = [5000, 0, 2000]
    session._update_arrest_pursuit()
    session._decide(guard)
    assert guard.properties["_dest"] == sighting
    assert guard.properties["sched_state"] == "SEARCH"
    session.clock.hour += SEARCH_HOURS + 0.01
    session._update_arrest()
    assert session._arrest_state == ""
    assert session.law_status()["phase"] == "writ"
    assert session.law.total == 55
    assert guard.properties["aggression"] == "defensive"


def test_reacquiring_sight_resets_search_and_invisibility_breaks_sight():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    session.logic.player.pos = [2400, 0, 0]
    session._update_arrest()
    session._start_arrest_pursuit()
    session._update_arrest_pursuit()
    session.logic.player.pos = [5000, 0, 0]
    session.clock.hour += 0.1
    session._update_arrest_pursuit()
    assert session.law_status()["remaining"] < 1
    session.logic.player.pos = [2400, 0, 0]
    session._update_arrest_pursuit()
    assert session.law_status()["phase"] == "pursuit"
    assert session.law_status()["remaining"] == 1
    session.game.character.effect_magnitude = lambda name: 1 if name == "invisibility" else 0
    assert not session._guard_sees_player(guard)


def test_boundary_ends_pursuit_without_erasing_either_regions_writ():
    border = _Thing("Bridgewatch", (5000, 0, 0), type="marker", marker_kind="location",
                    law_region="Bridgewatch", radius=800)
    session, witness, guard = _scene(border)
    _reported(session, witness, guard)
    session.law.charge("Bridgewatch", 99, 20, session._law_now())
    session.logic.player.pos = [2400, 0, 0]
    session._update_arrest()
    session._start_arrest_pursuit()
    session.logic.player.pos = [5000, 0, 0]
    session._update_arrest()
    assert not session._arrest_state
    assert session.law.bounty("Millbrook") == 55
    assert session.law.bounty("Bridgewatch") == 20


def test_guard_accepts_full_local_payment_and_keeps_other_debts_and_memories():
    session, witness, guard = _scene()
    ev = _reported(session, witness, guard)
    session.law.charge("Bridgewatch", 99, 300, session._law_now())
    session.game.character.bounty = session.law.total
    session.logic.player.pos = list(guard.pos)
    session.dialogue_npc = guard
    before = session.game.character.gold
    session._pay_bounty()
    assert session.game.character.gold == before - 55
    assert session.game.character.bounty == 300
    assert crime.settled(session.store, ev.id)
    assert knowledge.knows(session.store, actor_key(witness), ev.id) is not None
    assert session.director.top_intent(guard) is None


def test_guard_cannot_forgive_unpaid_balance_in_a_village_without_a_gaol():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    session.logic.player.pos = list(guard.pos)
    session.dialogue_npc = guard
    session.game.character.gold = 10
    session._pay_bounty()
    assert session.law.total == 55
    assert session.game.character.gold == 10
    assert not any(a.get("op") == "pay_bounty"
                   for r in session._arrest_tree(guard)["nodes"]["arrest"]["responses"]
                   for a in r.get("actions", []))


def test_gaol_serves_world_time_and_discharges_only_the_local_writ():
    prison = _Thing("Gaol", (2700, 0, 0), type="marker", marker_kind="prison")
    session, witness, guard = _scene(prison)
    _reported(session, witness, guard)
    session.law.charge("Bridgewatch", 99, 300, session._law_now())
    session._arrest_region = "Millbrook"
    before = session._law_now()
    session._complete_escort(prison.pos)
    assert session._law_now() > before
    assert session.game.character.bounty == 300


def test_delayed_report_retains_jurisdiction_after_event_history_is_evicted():
    session, witness, guard = _scene()
    ev = session.emit_event("theft", target="farmer", value=30, law_region="Bridgewatch")
    for _ in range(405):
        session.director.bus.make("talk")
    assert session.director.bus.get(ev.id) is None
    witness.pos = list(guard.pos)
    session.director.resolve_reports(session._sim_actors())
    assert session.law.bounty("Bridgewatch") == 55
    assert session.law.bounty("Millbrook") == 0


def test_grave_crimes_raise_only_local_watch_and_curfew_expires():
    session, witness, guard = _scene()
    guard.pos = [200, 0, 0]
    distant = _Thing("Distant watch", (9000, 0, 0), type="npc", npc_role="guard")
    near = _Thing("Gate watch", (1700, 0, 0), type="npc", npc_role="guard")
    session.logic.things.extend([distant, near])
    for _ in range(3):
        session.emit_event("death", target="farmer")
        session.director.resolve_reports(session._sim_actors())
    assert session._guard_knows_writ(near, "Millbrook")
    assert not session._guard_knows_writ(distant, "Millbrook")
    assert session.law_status()["curfew"]
    merchant = _Thing("Trader", type="npc", merchant=True)
    session._dialogue_action(merchant, {"op": "open_trade"})
    assert session.open_screen != "trade"
    session.clock.hour += 6.01
    assert not session.law_status()["curfew"]


def test_writs_and_search_progress_round_trip_and_old_bounties_migrate_once():
    store = _Store()
    law = Writs(store)
    law.migrate("Millbrook", 100)
    law.migrate("Millbrook", 100)
    law.charge("Bridgewatch", 99, 250, 30)
    law.sighted("Millbrook", [0, 0, 0], 30)
    law.search("Millbrook", [SEARCH_RADIUS + 1, 0, 0], 30.1)
    law.persist()
    loaded = Writs(store)
    assert loaded.total == 350
    assert loaded.record("Millbrook")["phase"] == "search"
    assert loaded.remaining("Millbrook") == pytest.approx(0.6)
    loaded.settle("Millbrook")
    assert Writs(store).total == 250


def test_hearing_through_a_wall_does_not_reveal_a_name():
    session, witness, guard = _scene()
    session.logic.session_runtime = SimpleNamespace(
        spatial_grid=SimpleNamespace(has_line_of_sight=lambda a, b: False))
    session.emit_event("attack", target="farmer")
    assert not session.witness_markers()[0]["identified"]
    assert not session._guard_sees_player(guard)


def test_both_maps_paint_witnesses_from_the_same_live_snapshot(qt_app, monkeypatch):
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import law_marks, theme, worldmap
    from ..ui.map_page import MapPage
    session, witness, guard = _scene()
    _theft(session)
    session._apply_sim_intent(witness)
    witness.pos = [800, 0, 300]
    expected = session.witness_markers()
    drawn = []
    original = law_marks.draw_witness

    def draw(painter, point, account, radius=7):
        drawn.append(account)
        original(painter, point, account, radius)

    monkeypatch.setattr(law_marks, "draw_witness", draw)
    image = QImage(1000, 700, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        worldmap.draw_minimap(painter, session, None, 1000, 700)
        assert drawn == expected
        drawn.clear()
        page = MapPage(SimpleNamespace(view=SimpleNamespace(update=lambda: None)))
        page.features = worldmap.map_features(session)
        page.centre = (0, 0)
        page.draw(painter, 1000, 700, theme.font, theme.font)
        assert drawn == expected
    finally:
        painter.end()


def test_ordinary_guard_dialogue_gains_payment_without_losing_authored_responses():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    tree = {"start": "greeting", "nodes": {"greeting": {
        "text": "What brings you here?", "responses": [{"text": "Any rumours?", "goto": "END"}]}}}
    result = session._law_payment_tree(guard, tree)
    responses = result["nodes"]["greeting"]["responses"]
    assert responses[0]["actions"] == [{"op": "pay_bounty"}]
    assert responses[1]["text"] == "Any rumours?"
    assert len(tree["nodes"]["greeting"]["responses"]) == 1


def test_attacked_guard_pursues_but_stands_down_after_escape_and_payment():
    session, witness, guard = _scene()
    guard.pos = [100, 0, 0]
    session._provoke(guard)
    assert session._sim_is_crime_against(guard), "provoking the watch does not legalise further attacks"
    session.director.resolve_reports(session._sim_actors())
    assert guard in session._arrest_pursuers
    session.logic.player.pos = [3000, 0, 3000]
    session._update_arrest_pursuit()
    session.clock.hour += SEARCH_HOURS + 0.01
    session._update_arrest()
    assert guard.properties["aggression"] == "defensive"
    assert not session._apply_sim_intent(guard)
    session.logic.player.pos = list(guard.pos)
    session.dialogue_npc = guard
    session._pay_bounty()
    assert session.law.total == 0
    assert not session._apply_sim_intent(guard)
    assert guard.properties["aggression"] == "defensive"


def test_session_save_load_preserves_a_search_and_its_local_charge():
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    session.logic.player.pos = [2400, 0, 0]
    session._update_arrest()
    session._start_arrest_pursuit()
    session.logic.player.pos = [6000, 0, 2000]
    session.clock.hour += 0.1
    session._update_arrest_pursuit()
    session.persist(force=True)
    loaded = MiniwindSession(session.logic, cfg={"region_name": "Millbrook"},
                             globals_store=session.store._g)
    loaded.restore()
    assert loaded.game.character.bounty == 55
    assert loaded.law_status()["phase"] == "search"
    assert loaded.law_status()["remaining"] == pytest.approx(0.6)
    assert guard in loaded._arrest_pursuers
    loaded._update_arrest()
    assert loaded.law_status()["centre"] == [2400, 0, 0]


def test_searchradius_command_hides_only_the_visual_and_remembers_the_choice():
    from .test_console import _manager
    session, witness, guard = _scene()
    _reported(session, witness, guard)
    session.law.sighted("Millbrook", [0, 0, 0], session._law_now())
    session.law.search("Millbrook", [3000, 0, 0], session._law_now())
    session.logic._miniwind = session
    manager = _manager()
    for argument, expected in (("0", False), ("nonsense", False), ("1", True), ("0", False)):
        handled, _ = manager.dispatch_console_command("searchradius", argument, session.logic,
                                                      play_mode=True)
        assert handled
        status = session.law_status()
        assert status["show_radius"] is expected
        assert status["phase"] == "search" and status["bounty"] == 55
    session.persist(force=True)
    loaded = MiniwindSession(session.logic, cfg={"region_name": "Millbrook"},
                             globals_store=session.store._g)
    assert not loaded.law_status()["show_radius"]


def test_search_label_orbits_while_the_faint_circle_stays_fixed(qt_app, monkeypatch):
    from PyQt5.QtCore import QPointF, QRect
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import law_marks
    status = {"phase": "search", "centre": [0, 0, 0], "radius": 1000, "show_radius": True}

    def render():
        image = QImage(400, 400, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            law_marks.draw_search(painter, status, lambda x, z: QPointF(200, 200), 0.1)
        finally:
            painter.end()
        return image

    monkeypatch.setattr(law_marks, "time", SimpleNamespace(monotonic=lambda: 0))
    first = render()
    monkeypatch.setattr(law_marks, "time", SimpleNamespace(monotonic=lambda: 15))
    quarter_turn = render()
    assert first != quarter_turn
    interior = QRect(102, 102, 196, 196)
    assert first.copy(interior) == quarter_turn.copy(interior)
    status["show_radius"] = False
    hidden = render()
    assert hidden.pixelColor(200, 200).alpha() == 0
