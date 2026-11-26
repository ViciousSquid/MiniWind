"""Cult Rite: a real resident captive, real cultists and a persistent death consequence."""

from ...sim import story_text
from .base import BaseScenario


class CultRiteScenario(BaseScenario):
    kind = "cult_rite"
    display_name = "Cult Rite"
    scene_name = "a cult rite with a captive"
    hints = ("A low chanting drifts through the dark.", "Torchlight flickers off the road ahead.")
    THOUGHTS = {
        "victim": {"calm": ("Someone, please...", "I don't want to die here.",
                            "I should be home in {home}.")},
        "attacker": {"calm": ("The night is hungry.", "Soon. The rite is nearly ready.",
                              "One more for the dark.")},
    }
    AMBIENT = {
        "victim": ("Help! Somebody!", "Please... my family are in {home}!",
                   "Let me go -- I've done nothing!"),
        "attacker": ("By ash and by ember, the old dark wakes.", "Bind them tighter.",
                     "Another for the altar.", "Sing, brothers. The night is listening."),
    }

    def thank_line(self, scene):
        return "You came for me... I thought I was done for. Thank you."

    def topic(self, role, talk, want=""):
        if role != "victim":
            return None
        from .. import scene_talk as st
        t = st._known(talk)
        back = {"text": "I see.", "goto": "@start"}
        text = (f"They took me on the road outside {t['home']}." if t.get("home")
                else "They took me off the road.")
        count = int(t.get("count", 0) or 0)
        if t.get("cult"):
            text += (f" {t['cult']} and {count - 1} others." if count > 1 else f" {t['cult']}.")
        text += " They said I was chosen."
        who = (f"{t['cult']} leads them." if t.get("cult") else "I never heard a name.")
        if t.get("camp"):
            who += f" They spoke of {t['camp']}."
        nodes = {
            "scene_who": {"text": who, "responses": [back]},
            "scene_home": {"text": (f"Thank you. I'll go straight back to {t['home']}."
                                      if t.get("home") else "Thank you. I'll go home."),
                           "responses": [{"text": "Go.", "goto": "END"}]},
            "scene": {"text": text, "responses": [
                {"text": "Who did this?", "goto": "scene_who"},
                {"text": "Get home. I'll deal with them.", "goto": "scene_home"}, back]},
        }
        return {"prompt": "What happened to you?", "nodes": nodes, "first": "scene"}

    def sacrifice(self, ctx, scene, captive, t):
        """The rite was finished: the captive is lost, and word goes round."""
        board = ctx.board
        for m in captive.members:
            m["alive"] = False
            m["health"] = 0
        name = captive.members[0]["display"] if captive.members else "a traveller"
        place = ctx._place_at(scene["x"], scene["z"])
        nid = board.say(f"{name} was taken by cultists and never came home; they were found "
                        f"by the road near {board.place_name(place)}.", t, place, "death")
        captive.news.append(nid)
        scene["resolved"] = True
        ctx._narrate(f"Outcome: nobody came for {name} within {ctx.rite_hours:g} game hours, so the rite "
                      f"was finished and {name} is lost. News spread from "
                      f"{board.place_name(place)}, and {name}'s family were told -- a real grievance "
                      "that may send one of them out for revenge.", scene=scene["id"])
        self.tell_kin(ctx, captive, scene)

    def stage(self, ctx, t):
        """A cult holds a real townsperson at a rite by the road."""
        spot = ctx._road_ahead(hostile=True)
        if spot is None:
            return ctx._no("no road the player is on has a free spot out of sight ahead")
        x, z = spot[7], spot[8]
        pool = [r for r in ctx.board.resident_pool if ctx._can_take(r["id"])]
        if not pool:
            return ctx._no("no townsperson out of sight and free to be taken captive")
        home = ctx._place_at(x, z)
        hx, hz = ctx.board.places[home]["x"], ctx.board.places[home]["z"]
        pool.sort(key=lambda r: math.hypot(ctx.board.places.get(r["home"], {}).get("x", hx) - hx,
                                           ctx.board.places.get(r["home"], {}).get("z", hz) - hz))
        r = pool[0]
        thing = ctx.world.resident_thing(r["id"])
        if thing is None:
            return ctx._no("the chosen captive is not in the scene")
        cult, borrowed = ctx._gang((x, z), t, "cultists")
        if cult is None:
            return ctx._no("no cult on the roads and no camp to send one from")
        sid = ctx._new_id()
        member = ctx._resident_member(thing, r["id"])
        captive = ctx._new_journey("captive", [member], [(x, z), (x + 1.0, z + 1.0)],
                                    r["home"], t, home=r["home"])
        ctx._take_resident(captive, r["id"])
        ctx._hold(captive, x, z, sid, "victim", t, hours=ctx.rite_hours,
                   greeting="Please -- cut me loose before they come back!", wander=8.0)
        ctx._hold(cult, x + 70.0, z + 40.0, sid, "attacker", t, hours=ctx.rite_hours,
                   borrowed=borrowed, wander=140.0)
        ctx._keep_apart(captive, cult)
        name = member["display"]
        return ctx._record(
            sid, "cult_rite", {"victim": captive.id, "attacker": cult.id}, x, z, t, reward=True,
            talk={"captive": name, "home": ctx.board.place_name(r["home"]),
                  "cult": ctx._lead(cult), "camp": ctx._camp(cult),
                  "count": len(cult.alive())},
            decision=(f"The storyteller decided that {ctx._lead(cult)}'s cult would hold a rite by "
                      f"the road with {name} of {ctx.board.place_name(r['home'])} as their captive, "
                      f"because it is night and {name} was the nearest townsperson nobody could see."),
            result=(f"Spawned {ctx._lead(cult)}'s cult ({ctx._from(cult, borrowed)}) and {name} "
                    f"({ctx._from(captive, False)}), held captive, {ctx._where(x, z)}. If nobody "
                    f"breaks up the rite within {ctx.rite_hours:g} game hours, {name} is lost and their "
                    "family hear of it."))

    def stage_expired(self, ctx, journey, scene, role, t):
        """Finish the rite only when the cult and captive still survive off-screen."""
        if scene is None or scene.get("resolved"):
            return None
        cult = ctx.board.journeys.get(scene["journeys"].get("attacker", ""))
        captive = ctx.board.journeys.get(scene["journeys"].get("victim", ""))
        if cult is None or not cult.alive() or captive is None or not captive.alive() or captive.live:
            return None
        self.sacrifice(ctx, scene, captive, t)
        captive.state = "done"
        return False if role == "victim" else None

    def tell_kin(self, ctx, captive, scene):
        """Kin of the lost hear of it (a real death fact, told them), so their
        own grievance -- and perhaps an avenger -- follows from it."""
        s = ctx.session
        director = getattr(s, "director", None)
        store = getattr(s, "store", None)
        if director is None or store is None or not captive.members:
            return
        from ...sim import appraisal, knowledge
        from ...sim.director import actor_key
        m = captive.members[0]
        rid = m.get("resident") or m.get("name")
        cult = ctx.board.journeys.get(scene["journeys"].get("attacker", ""))
        lead = cult.leader() if cult is not None else None
        try:
            event = director.emit("death", actor=(lead or {}).get("name", "cultists"), target=rid,
                                  pos=(scene["x"], 0.0, scene["z"]), observers=(),
                                  actor_faction="cultists", target_faction="villagers")
        except Exception:
            return
        for kin_id, thing in list(ctx.world._residents.items()):
            if kin_id == rid or thing.properties.get("dead"):
                continue
            tie = appraisal.relationship_to(thing.properties, actor_key(rid), m.get("display", ""))
            if tie not in appraisal.WARM_TIES:
                continue
            fact = knowledge.fact_from_event(event, 0.9, knowledge.SOURCE_HEARD, told_by="news")
            knowledge.learn(store, actor_key(thing), fact)
            director.invalidate(thing)

    # -- watching scenes play out ----------------------------------------------
