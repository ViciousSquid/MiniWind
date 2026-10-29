"""The rumour layer: broadcasting what people already believe, as narration."""

from __future__ import annotations

import copy
import json
import random
from types import SimpleNamespace

from ..living import journeys, roads
from ..living.world import LivingWorld
from ..sim import knowledge, rumours
from ..sim.director import Director, actor_key
from ..sim.events import WorldEvent
from .test_storyteller import Store


def fact(kind="theft", actor="player", actor_name="Rufus", target="bram", target_name="Bram",
         certainty=1.0, source="witnessed", day=3, pos=(2000, 0, 0), e=7, **extra):
    ev = WorldEvent(kind, actor=actor, actor_name=actor_name, target=target, target_name=target_name,
                    pos=pos, day=day, hour=10, data=dict(item="a purse"))
    ev.id = e
    f = knowledge.fact_from_event(ev, certainty, source)
    f.update(extra)
    return f


def place_of(x, z):
    return "the ford" if x > 1000 else "Ashby"


def test_a_rumour_names_the_place_the_day_and_hedges_by_certainty():
    seen = rumours.line(fact(), place_of, today=4)
    assert "you stole a purse from Bram near the ford, yesterday" in seen
    assert seen.startswith(("I saw it myself", "I was there")) and seen.endswith(".")
    doubtful = rumours.line(fact(source="told", certainty=0.35), place_of, today=10)
    assert doubtful.startswith(("They say, though", "Only a rumour")) and "a while back" in doubtful


def test_an_unidentified_culprit_stays_someone_and_others_are_named():
    line = rumours.line(fact(kind="death", actor="kael", actor_name="Kael", identified=False), place_of, 3)
    assert "Bram was killed by someone" in line and "Kael" not in line
    told_to_bram = rumours.line(fact(kind="attack", actor="kael", actor_name="Kael"), listener="bram")
    assert "Kael attacked you" in told_to_bram


def test_a_faction_raid_account_explains_why_the_party_was_there():
    grievance = fact(kind="death", target="mara", target_name="Mara", e=3)
    clash = fact(kind="attack", actor="road_kael", actor_name="Kael", target="road_hal",
                 target_name="Hal", e=9,
                 cause=dict(faction="bandits", home="camp", fact=grievance))
    line = rumours.line(clash, place_of, 3, place_name=lambda k: "Blacktooth Camp")
    assert "Those were bandits out of Blacktooth Camp over how Mara was killed by you" in line


def test_only_notable_believed_facts_are_volunteered_in_a_stable_order():
    facts = [fact(e=1, kind="trade"), fact(e=2, certainty=0.2, source="told"),
             fact(e=3, kind="theft", day=1), fact(e=4, kind="death"), fact(e=5, kind="theft", day=2)]
    assert [f["e"] for f in rumours.pick(facts, 5)] == [4, 5, 3]
    assert [f["e"] for f in rumours.pick(facts, 5, skip=[4])] == [5, 3]
    assert rumours.pick(list(reversed(facts)), 2) == rumours.pick(facts, 2)


def test_departures_and_notices_read_like_neighbours_and_the_watch():
    order = rumours.departure("", "Kettlewick", faction="bandits", target="you",
                              reason_fact=fact(kind="death", target_name="Mara"))
    assert order == "Bandits set out from here for Kettlewick, after you, over how Mara was killed by you."
    trip = rumours.departure("Hester", "Ashby", "vendetta", "Bram")
    assert trip == "Hester left for Ashby — swore to find whoever killed Bram."
    posted = rumours.notice(fact(), place_of, 4)
    assert posted.startswith("BY ORDER OF THE WATCH: You stole a purse from Bram near the ford")


# ---------------------------------------------------------------- the world
def world(**session):
    places = {"a": dict(name="Ashby", x=0, z=0, kind="town"),
              "b": dict(name="the ford", x=2000, z=0, kind="inn"),
              "c": dict(name="Kettlewick", x=-2000, z=0, kind="town")}
    net = roads.RoadNetwork.build([], [(k, p["x"], p["z"]) for k, p in places.items()])
    store = Store()
    sess = SimpleNamespace(store=store, clock=SimpleNamespace(day=4, hour=9), **session)
    living = LivingWorld(sess)
    living.board = journeys.JourneyBoard(net, places, 1, rng=random.Random(3))
    living.places = places
    return living, store


def npc(name="Bram", pos=(0, 0, 0), **props):
    return SimpleNamespace(properties=dict(name=name, id=f"{name.lower()}_uuid", type="npc", **props),
                           pos=list(pos))


def tree():
    return {"start": "hi", "nodes": {"hi": {"text": "Hello.", "responses": [{"text": "Bye.", "goto": "END"}]}}}


def test_heard_any_news_offers_what_the_resident_believes_without_changing_anything():
    living, store = world()
    teller = npc()
    knowledge.learn(store, actor_key(teller), fact(kind="death", actor="kael", actor_name="Kael",
                                                  target="mara", target_name="Mara", identified=False))
    before, rng = copy.deepcopy(store.d), living.board.rng.getstate()
    out = living.prepare_tree(tree(), teller)
    assert {"text": "Heard any news?", "goto": "_town_news"} in out["nodes"]["hi"]["responses"]
    assert "Mara was killed by someone near the ford, yesterday" in out["nodes"]["_town_news"]["text"]
    assert store.d == before and living.board.rng.getstate() == rng


def test_a_resident_who_knows_nothing_and_a_quiet_town_offer_no_news():
    living, _store = world()
    assert living.prepare_tree(tree(), npc()) == tree()


def test_town_news_and_rumours_share_the_answer():
    living, store = world()
    teller = npc()
    knowledge.learn(store, actor_key(teller), fact())
    living.board.say("Brigands robbed a caravan near Ashby.", 90, "a", "robbery")
    text = living.prepare_tree(tree(), teller)["nodes"]["_town_news"]["text"]
    assert "stole a purse" in text and "Brigands robbed a caravan" in text


def test_neighbours_tell_of_a_faction_order_that_actually_set_out():
    living, _store = world()
    b = living.board
    j = b.plan("faction_raid", 90, origin="a", dest="c", members=[b._member("guard")])
    j.cause = dict(faction="the watch", home="a", target="player", fact=fact(kind="death", target_name="Mara"))
    assert living.departures("a") == [
        "The Watch set out from here for Kettlewick, after you, over how Mara was killed by you."]
    assert living.departures("c") == []
    j.state = "rest"                       # arrived: no longer setting out
    assert living.departures("a") == []


def test_neighbours_tell_of_a_justified_trip_only_while_the_storyteller_sent_it():
    rows = {"hester": dict(kind="vendetta", victim="Bram", destination="c")}
    story = SimpleNamespace(enabled=True, justified_view=lambda key: rows.get(key))
    living, _store = world(storyteller=story)
    b = living.board
    member = dict(b._member("merchant"), display="Hester", resident="hester")
    j = b.plan("market", 90, origin="a", dest="c", members=[member])
    j.resident = "hester"
    assert living.departures("a") == ["Hester left for Kettlewick — swore to find whoever killed Bram."]
    rows["hester"]["destination"] = "b"
    assert living.departures("a") == []


def test_the_watch_posts_only_reported_unsettled_crimes_known_in_town():
    reported, unreported, elsewhere = npc("Bram"), npc("Mara"), npc("Kael", pos=(-2000, 0, 0))
    cast = [reported, unreported, elsewhere]
    living, store = world(_things_of_type=lambda kind: cast if kind == "npc" else ())
    knowledge.learn(store, actor_key(reported), fact(e=1, reported=True))
    knowledge.learn(store, actor_key(unreported), fact(e=2))
    knowledge.learn(store, actor_key(elsewhere), fact(e=3, reported=True))
    posts = living.notices("a")
    assert len(posts) == 1 and "stole a purse" in posts[0]
    store.set("crime.1.settled", "1")
    assert living.notices("a") == []


# ------------------------------------------------------- session surfaces
class Session:
    """The parts of MiniwindSession the volunteering and board code touch."""

    def __init__(self, living, cast, player=(0, 0, 0)):
        self.living, self.cast, self.player = living, cast, list(player)
        self.dialogue = None
        self.barks = {}
        self.said = []
        self._chat_rng = SimpleNamespace(random=lambda: 0.0)
        living.session._things_of_type = self._things_of_type

    def _things_of_type(self, kind):
        return [t for t in self.cast if t.properties.get("type") == kind]

    def _player_pos(self):
        return self.player

    @staticmethod
    def _dist2d(a, b):
        return ((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

    def bark(self, thing, text, seconds=3.0):
        self.barks[id(thing)] = (thing, text, seconds)
        self.said.append((thing.properties["name"], text))


def test_the_nearest_idle_resident_volunteers_each_rumour_once():
    from ..runtime import MiniwindSession

    living, store = world()
    near, far = npc("Bram", pos=(100, 0, 0)), npc("Mara", pos=(900, 0, 0))
    for who in (near, far):
        knowledge.learn(store, actor_key(who), fact(e=1))
    knowledge.learn(store, actor_key(near), fact(e=2, kind="death"))
    session = Session(living, [near, far])
    before = copy.deepcopy(store.d)
    for _ in range(3):
        session.barks.clear()
        near.properties.pop("_rumour_until", None)
        MiniwindSession._update_volunteering(session)
    assert [who for who, _ in session.said] == ["Bram", "Bram"]
    assert "killed" in session.said[0][1] and "stole" in session.said[1][1]
    assert near.properties["_told_player"] == [2, 1]
    assert store.d == before


def test_nobody_volunteers_during_a_conversation_or_while_busy():
    from ..runtime import MiniwindSession

    living, store = world()
    near = npc("Bram", pos=(100, 0, 0))
    knowledge.learn(store, actor_key(near), fact())
    session = Session(living, [near])
    session.dialogue = object()
    MiniwindSession._update_volunteering(session)
    session.dialogue = None
    near.properties["sched_state"] = "FLEE"
    MiniwindSession._update_volunteering(session)
    assert session.said == []


def test_tavern_talk_is_likelier_at_an_inn():
    from ..runtime import MiniwindSession, VOLUNTEER_CHANCE, TAVERN_FACTOR

    for player, heard in (((0, 0, 0), False), ((2000, 0, 0), True)):
        living, store = world()
        regular = npc("Bram", pos=(player[0] + 50, 0, 0))
        knowledge.learn(store, actor_key(regular), fact())
        session = Session(living, [regular], player)
        roll = VOLUNTEER_CHANCE * (1 + TAVERN_FACTOR) / 2
        session._chat_rng = SimpleNamespace(random=lambda: roll)
        MiniwindSession._update_volunteering(session)
        assert bool(session.said) == heard


def test_a_notice_board_posts_the_writ_appeals_departures_and_news():
    from ..runtime import MiniwindSession

    living, store = world()
    board = SimpleNamespace(properties=dict(type="notice_board", name="Board"), pos=[10, 0, 0])
    resident = npc("Bram")
    session = Session(living, [board, resident])
    session.law = SimpleNamespace(bounty=lambda region: 120)
    session._law_region = lambda pos, thing: "ashby"
    session.game = SimpleNamespace(character=SimpleNamespace(name="Rufus"))
    knowledge.learn(store, actor_key(resident), fact(reported=True))
    living.board.say("Wolves took sheep at Ashby.", 90, "a", "raid")
    assert MiniwindSession.nearest_notice_board(session, [0, 0, 0]) is board
    assert MiniwindSession.nearest_notice_board(session, [500, 0, 0]) is None
    posts = MiniwindSession.notice_board_posts(session, board)
    assert posts[0].startswith("WANTED: Rufus") and "120 gold" in posts[0]
    assert any(p.startswith("BY ORDER OF THE WATCH") for p in posts)
    assert posts[-1] == "Wolves took sheep at Ashby."
    session.law = SimpleNamespace(bounty=lambda region: 0)
    living.board.news.clear(), living.board.heard.clear(), store.d.clear()
    session.notice_board_posts = lambda b: MiniwindSession.notice_board_posts(session, b)
    bare = MiniwindSession._notice_board_tree(session, board)
    assert bare["nodes"]["board"]["text"].startswith("The board is bare")
