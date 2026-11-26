"""What people in a Dynamic mode scene say and think (game/living/scene_talk.py):
conversation, thoughts and lines heard on the approach, all built from the
facts the director recorded as it staged the scene."""

from ..living import scene_talk as st
from .. import mental_state
from .test_dynamic_mode import _Thing, _build, _culprit_gang, _trader, _world


def _live(w, scene, role, n=1, **props):
    """Make the party staged for *role* into live actors."""
    j = w.board.journeys[scene["journeys"][role]]
    things = [_Thing(3000.0 + i * 10, 0.0, display_name=f"{role}{i}", dialogue={}, **props)
              for i in range(n)]
    w.world.live[j.id] = {"things": things}
    w.director.spawned(j, things)
    return j, things


def _answers(tree, prompt):
    start = tree["nodes"][tree["start"]]
    reply = next(r for r in start["responses"] if r["text"] == prompt)
    return tree["nodes"][reply["goto"]]


def test_a_waylaid_traveller_says_who_robbed_them_and_where_they_came_from():
    w = _world()
    trader = _trader(w.board)
    _build(w)
    scene = w.director._stage_waylaid(12.0)
    gang = w.board.journeys[scene["journeys"]["attacker"]]
    _j, (lead,) = _live(w, scene, "victim")
    node = _answers(lead.properties["dialogue"], "What happened here?")
    gang_lead = gang.leader()["display"]
    assert node["text"].startswith(gang_lead) and "Kettlewick" in node["text"]   # bound for
    assert trader.dest == "kettle"
    where = w.board.place_name(gang.home)
    if where:
        assert where in w.director.scenes[scene["id"]]["talk"]["camp"]
    # Their own conversation is still all there.
    assert any(r["text"] == "What happened here?" for r in
               lead.properties["dialogue"]["nodes"][lead.properties["dialogue"]["start"]]["responses"])


def test_brigands_taunt_their_victim_by_name_and_the_victim_pleads():
    talk = {"victim": "Odo Fenn", "victim_first": "Odo", "dest": "Kettlewick"}
    assert "Hand it over, Odo!" in st.ambient("waylaid", "attacker", talk)
    assert "We're only bound for Kettlewick!" in st.ambient("waylaid", "victim", talk)
    assert "My purse... my life..." in st.thoughts("waylaid", "victim", talk)["flee"]
    assert "Easy pickings." in st.thoughts("waylaid", "attacker", talk)["calm"]


def test_a_line_needing_a_fact_the_scene_lacks_is_never_said():
    lines = st.ambient("waylaid", "victim", {})            # no destination known
    assert lines and not any("{" in l or "bound for" in l for l in lines)
    assert all("{" not in l for l in st.thoughts("avenger", "avenger", {"culprit": "Rook"})["calm"])


def test_a_captive_tells_where_they_were_taken_and_by_whom():
    talk = {"captive": "Mabel", "home": "Low Farm", "cult": "Brother Vael", "camp": "Old Camp",
            "count": 3}
    found = st.topic("cult_rite", "victim", talk)
    assert found["prompt"] == "What happened to you?"
    text = found["nodes"]["scene"]["text"]
    assert "outside Low Farm" in text and "Brother Vael and 2 others" in text
    assert "Old Camp" in found["nodes"]["scene_who"]["text"]
    assert "I should be home in Low Farm." in st.thoughts("cult_rite", "victim", talk)["calm"]
    assert "Please... my family are in Low Farm!" in st.ambient("cult_rite", "victim", talk)
    assert any("ember" in l for l in st.ambient("cult_rite", "attacker", talk))   # chanting


def test_the_staged_cult_rite_gives_the_captive_their_story(monkeypatch):
    w = _world(hour=23.0)
    farmer = _Thing(-4000, 0, name="mabel", display_name="Mabel", npc_role="farmer",
                    faction="villagers", type="npc")
    w.world._residents["mabel"] = farmer
    w.board.resident_pool = [{"id": "mabel", "home": "farm", "role": "farmer",
                              "name": "mabel", "display": "Mabel"}]
    scene = w.director._stage_cult_rite(23.0)
    _j, (captive,) = _live(w, scene, "victim")
    node = _answers(captive.properties["dialogue"], "What happened to you?")
    assert "outside Low Farm" in node["text"]
    _j, cultists = _live(w, scene, "attacker", n=2)
    assert all(c.properties["_scene_thoughts"]["calm"] for c in cultists)
    assert "dialogue" not in cultists[0].properties or not any(
        r.get("text") == "What happened to you?"
        for r in (cultists[0].properties["dialogue"].get("nodes", {}).get("greet", {})
                  .get("responses", [])))


def test_an_avenger_names_the_culprit_the_deed_and_how_they_know():
    from ..sim import knowledge
    from ..sim.director import actor_key
    w = _world()
    w.session.clock.day = 2
    edda = _Thing(-4000, 0, name="edda", display_name="Edda", npc_role="farmer",
                  faction="villagers", type="npc", relationships={"Aldo": "brother"})
    w.world._residents["edda"] = edda
    knowledge.learn(w.store, actor_key(edda), {
        "e": 41, "kind": "death", "actor": "black_rook", "actor_name": "Black Rook",
        "actor_faction": "bandits", "target": "aldo", "target_name": "Aldo",
        "day": 2, "hour": 3.0, "certainty": 0.9, "identified": True, "source": "witnessed"})
    _culprit_gang(w.board)
    scene = w.director._stage_avenger(12.0)
    _j, (avenger,) = _live(w, scene, "avenger")
    node = _answers(avenger.properties["dialogue"], "Tell me about Black Rook.")
    assert node["text"].startswith("Black Rook killed my brother Aldo")
    assert "I saw it with my own eyes." in node["text"]
    assert "camped up the road" in node["text"]
    assert "Black Rook will pay for Aldo." in avenger.properties["_scene_thoughts"]["calm"]


def test_someone_come_for_repayment_names_what_was_taken():
    deed = st.deed("theft", "a loaf of bread", "me", "Ashby")
    found = st.topic("reckoning", "seeker", {"deed": deed}, "restitution")
    assert found["nodes"]["scene"]["text"] == (
        "You took a loaf of bread from me near Ashby. I want it back -- or its worth, in gold.")
    thanks = st.topic("gratitude", "seeker", {"deed": st.deed("heal", victim="my sister Ann")},
                      "gratitude")
    assert thanks["nodes"]["scene"]["text"] == "You healed my sister Ann. I've not forgotten it."
    assert st.topic("reckoning", "seeker", {"deed": deed}, "vendetta") is None   # no talking


def test_a_scene_thought_replaces_a_quiet_one_but_never_an_urgent_reason():
    minds = {"calm": ("Someone, please...",), "flee": ("Run! Just run!",)}
    held = {"display_name": "Mabel", "sched_state": "IDLE", "_scene_thoughts": minds}
    assert mental_state.thought(held) == ("scene:calm", "Someone, please...")
    held["_flee"] = True
    assert mental_state.thought(held) == ("scene:flee", "Run! Just run!")
    alert = {"display_name": "Mabel", "sched_state": "ALERT", "_scene_thoughts": minds}
    assert mental_state.thought(alert)[0] == "alert"               # its own reason stands
    assert "scene" in mental_state.URGENT_THOUGHTS                 # said at once, when first seen
    assert mental_state.thought({"display_name": "X", "sched_state": "IDLE"})[0] != "scene:calm"


def test_ambient_beats_come_from_the_scene_now_and_then_near_the_player(monkeypatch):
    import time
    w = _world()
    _trader(w.board)
    _build(w)
    scene = w.director._stage_waylaid(12.0)
    _live(w, scene, "victim")
    _live(w, scene, "attacker", n=2)
    thoughts = []
    w.session.think = lambda thing, text, *a: thoughts.append(text)
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    w.director._ambient(scene, 2900.0, 0.0)
    assert len(w.barks) + len(thoughts) == 1
    w.director._ambient(scene, 2900.0, 0.0)                     # too soon: nothing
    assert len(w.barks) + len(thoughts) == 1
    clock[0] += 12.0
    w.director._ambient(scene, 2900.0, 0.0)
    assert len(w.barks) + len(thoughts) == 2
    clock[0] += 12.0
    w.director._ambient(scene, -5000.0, 0.0)                    # far off: nothing heard
    assert len(w.barks) + len(thoughts) == 2
    talk = scene["talk"]
    allowed = set(st.ambient("waylaid", "victim", talk) + st.ambient("waylaid", "attacker", talk))
    allowed |= set(sum(st.thoughts("waylaid", "victim", talk).values(), []))
    allowed |= set(sum(st.thoughts("waylaid", "attacker", talk).values(), []))
    assert set(w.barks + thoughts) <= allowed


def test_repayment_can_be_paid_in_the_conversation_and_settles_the_theft():
    from ..rpg import items as rpg_items
    loaf = next((i for i in ("bread", "loaf", "apple") if rpg_items.get(i)), None)
    owed = st.owed("theft", loaf or "")
    assert owed >= st.LEAST_OWED and st.owed("lockpick") == st.LOCKPICK_OWED
    assert st.owed("death") == 0
    talk = {"deed": "took a loaf of bread from me", "owed": owed, "scene": "dyn3", "event": 17}
    found = st.topic("reckoning", "seeker", talk, "restitution")
    pay, short, refuse = found["nodes"]["scene"]["responses"]
    assert pay["text"] == f"Here: {owed} gold." and pay["condition"] == {"has_item": "gold", "qty": owed}
    assert pay["actions"] == [{"op": "scene_repay", "scene": "dyn3", "event": 17, "gold": owed}]
    assert short["condition"] == {"lacks_item": "gold", "qty": owed}
    assert refuse["goto"] == "scene_refuse"


def test_paying_settles_the_theft_gives_them_the_gold_and_ends_the_scene():
    from ..sim import crime
    from ..rpg import inventory as rpg_inventory
    w = _world()
    w.director.scenes["dyn3"] = {"id": "dyn3", "kind": "reckoning", "journeys": {},
                                 "resolved": False, "x": 0.0, "z": 0.0, "hinted": True}
    seeker = _Thing(0, 0, display_name="Hal", inventory=[])
    assert not crime.settled(w.store, 17)
    w.director.repaid(seeker, "dyn3", 17, 12)
    assert crime.settled(w.store, 17)
    assert rpg_inventory.quantity(rpg_inventory.get_inventory(seeker), "gold") == 12
    assert w.director.scenes["dyn3"]["resolved"]
    assert any("repaid 12 gold" in d for d in w.said)


def test_the_player_pays_from_their_purse_and_only_with_enough(monkeypatch):
    from types import SimpleNamespace
    from .. import runtime
    from .test_cast_controls import _Logic
    s = runtime.MiniwindSession(_Logic(), cfg={})
    paid = []
    s.living = SimpleNamespace(scenarios=SimpleNamespace(
        repaid=lambda npc, sid, e, gold: paid.append((sid, e, gold))))
    npc = _Thing(0, 0, display_name="Hal")
    s.game.character.gold = 8
    assert not s._dialogue_has("gold", 12, {})
    s._dialogue_action(npc, {"op": "scene_repay", "scene": "dyn3", "event": 17, "gold": 12})
    assert s.game.character.gold == 8 and not paid               # not enough: nothing
    s.game.character.gold = 20
    assert s._dialogue_has("gold", 12, {})
    s._dialogue_action(npc, {"op": "scene_repay", "scene": "dyn3", "event": 17, "gold": 12})
    assert s.game.character.gold == 8 and paid == [("dyn3", 17, 12)]


def test_how_angry_they_are_decides_whether_a_roll_is_needed():
    assert st.temper(60) == "" and st.accept_chance("") == 1.0
    assert st.temper(20) == "resentful" and st.temper(5) == "infuriated"
    assert st.temper(70, furious=True) == "infuriated"
    assert st.accept_chance("infuriated") < st.accept_chance("resentful") < 1.0
    assert st.accept_chance("infuriated", 100) == st.ACCEPT_CHANCE["infuriated"] + 0.2


def _repay_session(disposition):
    from types import SimpleNamespace
    from .. import runtime
    from .test_cast_controls import _Logic
    s = runtime.MiniwindSession(_Logic(), cfg={})
    paid, engaged, barks = [], [], []
    s.living = SimpleNamespace(scenarios=SimpleNamespace(
        repaid=lambda npc, sid, e, gold: paid.append(gold)))
    s.bark = lambda thing, text, *a: barks.append(text)
    s._sim_engage = lambda npc, offender: engaged.append(npc) or True
    s.game.dice = None
    s.game.character.gold = 50
    return s, paid, engaged, barks


def test_an_infuriated_seeker_rolls_and_a_bad_roll_refuses_the_gold_and_starts_a_fight(monkeypatch):
    from .. import runtime
    s, paid, engaged, barks = _repay_session(3)
    monkeypatch.setattr(runtime.disp, "of", lambda c, p, store: 3)
    s.rng.random = lambda: 0.99                                  # a bad roll
    npc = _Thing(0, 0, display_name="Hal")
    s._scene_repay(npc, {"op": "scene_repay", "scene": "dyn3", "event": 17, "gold": 12})
    assert s.game.character.gold == 50 and not paid             # kept the gold
    assert engaged == [npc] and npc.properties["combatant"]     # and they attack
    assert barks[-1] in st.REFUSED


def test_a_good_roll_takes_the_gold_grudgingly_and_a_calm_one_needs_no_roll(monkeypatch):
    from .. import runtime
    s, paid, engaged, barks = _repay_session(3)
    monkeypatch.setattr(runtime.disp, "of", lambda c, p, store: 3)
    s.rng.random = lambda: 0.01
    s._scene_repay(_Thing(0, 0, display_name="Hal"),
                   {"op": "scene_repay", "scene": "dyn3", "event": 17, "gold": 12})
    assert paid == [12] and s.game.character.gold == 38 and not engaged
    assert barks[-1] in st.ACCEPTED_GRUDGINGLY
    monkeypatch.setattr(runtime.disp, "of", lambda c, p, store: 60)
    s.rng.random = lambda: 0.99                                  # would fail, but no roll
    s._scene_repay(_Thing(0, 0, display_name="Ann"),
                   {"op": "scene_repay", "scene": "dyn4", "event": 18, "gold": 5})
    assert paid == [12, 5] and barks[-1] in st.ACCEPTED


def test_after_a_refusal_a_d6_plus_luck_says_whether_you_keep_your_gold(monkeypatch):
    from .. import runtime
    from ..rpg import inventory as rpg_inventory
    s, paid, engaged, barks = _repay_session(3)
    monkeypatch.setattr(runtime.disp, "of", lambda c, p, store: 3)
    s.rng.random = lambda: 0.99                                  # refused
    s.game.character.attrs["luck"] = 40                          # no Luck bonus
    s.rng.randint = lambda a, b: 6                               # a good d6: kept
    hal = _Thing(0, 0, display_name="Hal", inventory=[])
    s._scene_repay(hal, {"op": "scene_repay", "scene": "dyn3", "event": 17, "gold": 12})
    assert s.game.character.gold == 50 and engaged == [hal]
    s.rng.randint = lambda a, b: 1                               # a bad d6: taken anyway
    ann = _Thing(0, 0, display_name="Ann", inventory=[])
    s._scene_repay(ann, {"op": "scene_repay", "scene": "dyn4", "event": 18, "gold": 12})
    assert s.game.character.gold == 38 and engaged == [hal, ann] and not paid
    assert rpg_inventory.quantity(rpg_inventory.get_inventory(ann), "gold") == 12
    assert barks[-1] in st.SNATCHED
