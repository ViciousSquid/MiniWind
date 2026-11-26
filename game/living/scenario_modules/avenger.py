"""Avenger: a resident pursues the actual person responsible for their grievance."""

import copy
import math
from .. import journeys as jn, scene_talk
from ...sim import story_text
from .base import BaseScenario


class AvengerScenario(BaseScenario):
    kind = "avenger"
    display_name = "Avenger"
    scene_name = "a townsperson out for revenge"
    hints = ("Someone waits by the road ahead, blade in hand.",)
    THOUGHTS = {
        "avenger": {
            "calm": ("{culprit} will pay for {whom_first}.", "For {whom_first}.", "Steady. Wait for them."),
            "combat": ("This is for {whom_first}!",),
        },
    }
    AMBIENT = {
        "avenger": ("For {whom_first}.", "Steady... steady.", "{culprit}. I'll find you."),
    }

    def topic(self, role, talk, want=""):
        if role != "avenger":
            return None
        from .. import scene_talk as st
        t = st._known(talk)
        if not t.get("culprit"):
            return None
        back = {"text": "I see.", "goto": "@start"}
        text = f"{t['culprit']} {t.get('what', 'wronged')} {t.get('whom', 'me')}{st._near(t.get('place', ''))}."
        how = st._HOW_KNOWN.get(t.get("source", ""))
        if how:
            text += " " + how
        if t.get("where"):
            text += f" {t['where']}."
        nodes = {
            "scene_alone": {"text": "Because nobody else will. Somebody has to answer for it.",
                            "responses": [back]},
            "scene": {"text": text, "responses": [
                {"text": "Why go alone?", "goto": "scene_alone"}, back]},
        }
        return {"prompt": f"Tell me about {t['culprit']}.", "nodes": nodes, "first": "scene"}

    def grievances(self, ctx):
        """Townsfolk who hold a real grievance against an outlaw:
        ``[(thing, rid, fact, tie)]``, freshest first."""
        s = ctx.session
        from ...sim import appraisal, knowledge
        from ...sim.director import actor_key
        store = getattr(s, "store", None)
        if store is None:
            return []
        day = int(getattr(s.clock, "day", 0) or 0)
        out = []
        for rid, thing in list(ctx.world._residents.items()):
            p = thing.properties
            if p.get("dead") or str(p.get("type", "npc")) != "npc" \
                    or p.get("faction") not in ("villagers", None, ""):
                continue
            key = actor_key(thing)
            try:
                facts = knowledge.facts_view(store, key)
            except Exception:
                continue
            for f in facts:
                if f.get("kind") not in ("death", "attack", "theft"):
                    continue
                if f.get("actor_faction") not in ctx.outlaw_factions:
                    continue
                if float(f.get("certainty", 0)) < 0.5 or day - int(f.get("day", 0) or 0) > ctx.grievance_days:
                    continue
                victim = f.get("target", "")
                tie = "" if victim == key else appraisal.relationship_to(
                    p, victim, f.get("target_name", ""))
                if victim != key and tie not in appraisal.WARM_TIES:
                    continue
                out.append((thing, rid, f, tie))
        out.sort(key=lambda row: (-int(row[2].get("day", 0) or 0), -float(row[2].get("hour", 0) or 0)))
        return out

    def culprit_member(self, ctx, fact):
        """``(party, member)``: the culprit themselves, riding with a party on
        the roads (off screen, unstaged), or None."""
        from ...sim.director import actor_key
        culprit = fact.get("actor", "")
        if not culprit:
            return None
        for j in ctx.board.journeys.values():
            if j.live or j.stage is not None or j.state == "done" or not j.alive():
                continue
            for m in j.alive():
                if culprit in (actor_key(m.get("id") or ""), actor_key(m.get("name") or "")):
                    return j, m
        return None

    def culprit_actor(self, ctx, fact):
        """The culprit as an actor somewhere in the world (a brigand at their
        camp, a beast at its lair), alive, or None."""
        find = getattr(ctx.session, "_sim_actor_by_key", None)
        culprit = fact.get("actor", "")
        if find is None or not culprit:
            return None
        try:
            thing = find(culprit)
        except Exception:
            return None
        if thing is None or getattr(thing, "pos", None) is None \
                or (getattr(thing, "properties", None) or {}).get("dead"):
            return None
        return thing

    def avenger_quest(self, ctx, sid, member, target_name, target_display, culprit, what, whom,
                       purse, here=True, place=""):
        """The quest an avenger offers: kill the culprit, for what they have."""
        if not target_name:
            return None
        qid = f"dyn_avenge_{sid}"
        where = "just up the road" if here else f"at {place}"
        pay = (f"Help me end it and what I have is yours -- {purse} gold." if purse else
               "I've no gold to give, only my thanks.")
        quest = {"id": qid, "name": f"{member['display']}'s Score",
                 "giver": member["name"],
                 "offer": f"{culprit} {what} {whom}. {target_display} is {where}. {pay}",
                 "xp": 50, "rewards": {"gold": int(purse)} if purse else {},
                 "stages": [
                     {"index": 0, "journal": f"Help {member['display']} deal with "
                                             f"{target_display}, {where}.",
                      "objective": f"Kill {target_display}",
                      "condition": {"kind": "kill", "target": target_name, "count": 1},
                      "waypoint": target_name},
                     {"index": 10, "journal": f"{target_display} is dead. "
                                              f"{member['display']} has their score settled.",
                      "finishes": True}]}
        ctx.world._register(quest)
        return qid

    def stage(self, ctx, t):
        """A townsperson out to settle a real score -- with the real culprit.

        The avenger only ever goes after whoever did it: the culprit riding
        with a party on the roads (that party is staged up the road), or the
        culprit as an actor elsewhere in the world (the avenger sets out for
        where they are). A culprit who is nowhere to be found sends nobody: no
        stand-in gang is ever put in their place, and the log says why."""
        from ...sim.director import actor_key
        done = {sc.get("fact_e") for sc in ctx.scenes.values()}
        unfound = []
        for thing, rid, fact, tie in self.grievances(ctx):
            if fact.get("e") in done or not ctx._can_take(rid):
                continue
            culprit = fact.get("actor_name") or "an outlaw"
            holder = thing.properties.get("display_name") or thing.properties.get("name") or rid
            riding = self.culprit_member(ctx, fact)
            actor = None if riding else self.culprit_actor(ctx, fact)
            if riding is None and actor is None:
                unfound.append(f"{holder}'s grievance is against {culprit}, who is neither on the "
                               "roads nor anywhere to be found -- no stand-in was sent")
                continue
            spot = ctx._road_ahead(hostile=True)
            if spot is None:
                return ctx._no("no road the player is on has a free spot out of sight ahead")
            x, z = spot[7], spot[8]
            if riding is not None:
                gang, target = riding
                route, dest = ctx._away_from_player(spot, ctx.quarry_gap)
                gx, gz = route[0]
                quarry_place = None
            else:
                gang, target = None, None
                quarry_place = ctx._place_at(actor.pos[0], actor.pos[2])
                start_place = ctx._place_at(x, z)
                if start_place == quarry_place:   # already the nearest place: straight there
                    q = ctx.board.places[quarry_place]
                    path = [(q["x"], q["z"])]
                else:
                    path = ctx.board._route(start_place, quarry_place)
                if not path:
                    unfound.append(f"{culprit} is at {ctx.board.place_name(quarry_place)}, but no "
                                   f"road leads there from where {holder} would set out")
                    continue
                route, dest = [(x, z)] + [tuple(p) for p in path], quarry_place
            sid = ctx._new_id()
            member = ctx._resident_member(thing, rid)
            member["armed"] = True
            name = member["display"]
            what = {"death": "killed", "attack": "attacked", "theft": "robbed"}[fact["kind"]]
            whom = (f"my {tie} {fact.get('target_name', '')}".strip() if tie else "me")
            where = ("They're camped up the road" if gang is not None else
                     f"They're at {ctx.board.place_name(quarry_place)}")
            greeting = f"{culprit} {what} {whom}. {where} -- I'm going after them, with or without you."
            j = ctx._new_journey("avenger", [member], [(x, z), (x + 1.0, z + 1.0)], dest, t,
                                  home=ctx.board.nearest_place(thing.pos[0], thing.pos[2], jn.HOMES))
            ctx._take_resident(j, rid)
            ctx._hold(j, x, z, sid, "avenger", t, hours=ctx.hold_hours * 0.5, greeting=greeting,
                       wander=50.0)
            j.stage["onward"] = [list(p) for p in route]
            j.stage["onward_dest"] = dest
            journeys = {"avenger": j.id}
            if gang is not None:
                gx, gz = route[0]
                ctx._hold(gang, gx, gz, sid, "attacker", t, borrowed=True, wander=110.0)
                ctx._keep_apart(j, gang)
                journeys["attacker"] = gang.id
            # The quest: kill the culprit, by name.
            target_name = (target or {}).get("name") or (actor.properties.get("name") if actor else "")
            target_display = (target or {}).get("display") or culprit
            purse = sum(int(st.get("qty", 0)) for st in member["inventory"]
                        if str(st.get("id")) == "gold")
            quest = self.avenger_quest(ctx, sid, member, target_name, target_display, culprit, what,
                                        whom, purse, here=gang is not None,
                                        place=ctx.board.place_name(quarry_place) if quarry_place else "")
            quest_name = f"'{name}'s Score'" if quest else "none"
            if gang is not None:
                found = (f"put {target_display}'s own band ({ctx._from(gang, True)}) "
                         f"{ctx.quarry_gap:,.0f} units beyond -- the party the culprit rides with")
            else:
                found = (f"{culprit} is not on the roads but is at "
                         f"{ctx.board.place_name(quarry_place)}, so {name} sets out for there")
            return ctx._record(
                sid, "avenger", journeys, x, z, t,
                fact_e=fact.get("e"), quest=quest, quest_reward=purse, reward=False,
                talk={"avenger": name, "culprit": culprit, "what": what, "whom": whom,
                      "whom_first": (fact.get("target_name") or "").split(" ")[0] if tie else "",
                      "place": ctx._place_of(fact), "source": fact.get("source", ""),
                      "where": where},
                culprit={"actor": fact.get("actor", ""), "name": culprit,
                         "faction": fact.get("actor_faction", "")},
                decision=story_text.grievance(name, fact, actor_key(thing), thing.properties,
                                              ctx._place_of(fact)),
                result=(f"Spawned {name} ({ctx._from(j, False)}), armed, on the road "
                        f"{ctx._where(x, z)}, and {found}. {name} offers {story_text.PLAYER} a "
                        f"quest ({quest_name}) to kill {target_display}, for what they have "
                        f"({purse} gold); if nobody comes within {ctx.hold_hours * 0.5:g} game hours "
                        "they go alone."))
        if unfound:
            return ctx._no("; ".join(unfound))
        return ctx._no("no townsperson holds a fresh, certain grievance against outlaws "
                        "(and is out of sight, free to leave)")


    def spawned(self, ctx, scene, journey, things):
        """Offer the optional kill-the-culprit quest when the avenger materialises."""
        qid = scene.get("quest")
        if not qid or (journey.stage or {}).get("role") != "avenger" or not things:
            return
        from ...rpg import quests as rpg_quests
        quest = rpg_quests.get(qid)
        if quest is None:
            return
        giver = things[0]
        tree = copy.deepcopy(giver.properties.get("dialogue"))
        tree, _ = rpg_quests.offer_dialogue_branch(
            tree, qid, quest.name, quest.desc if getattr(quest, "desc", "") else "")
        giver.properties["dialogue"] = tree

    def watch(self, ctx, scene, px, pz, t):
        journeys = scene.get("journeys") or {}
        if "avenger" in journeys and "attacker" not in journeys:
            # The avenger is following a culprit elsewhere in the world, not
            # protecting a staged victim. Keep it out of the generic rescue path.
            return True
        return False

    def thank_line(self, scene):
        return "It's done. I couldn't have -- thank you."

    def reward(self, ctx, scene, journey, lead, purse):
        if scene.get("quest") and scene.get("quest_reward"):
            quests = getattr(getattr(ctx.session, "game", None), "quests", None)
            if quests is not None and quests.is_complete(scene["quest"]):
                ctx._pay(journey, lead, min(purse, int(scene["quest_reward"])))
                scene["quest_reward"] = 0
        return 0

    def learned_intervention(self, name):
        return f"they helped {name} settle the score"

    def stage_expired(self, ctx, journey, scene, role, t):
        """An unmet avenger continues toward the known culprit on their own."""
        stage = journey.stage or {}
        if role != "avenger" or not stage.get("onward"):
            return None
        lead = journey.leader()
        ctx._narrate(
            f"Outcome: {lead['display'] if lead else 'The avenger'} waited "
            f"{ctx.hold_hours * 0.5:g} game hours, but {story_text.PLAYER} never came; they "
            "have gone after the gang alone, and the board's dice will settle it.",
            journey=journey.id)
        route = [tuple(p) for p in stage["onward"]]
        ctx._walking(journey, route, stage.get("onward_dest") or journey.dest,
                     scene["id"] if scene else "", "avenger", t)
        journey.stage.pop("greeting", None)
        journey.fought = []
        return True
