"""Reckoning: evidence-based confrontation, restitution and repayment."""

from .. import journeys as jn, scene_talk
from ...sim import story_text
from .base import BaseScenario


class MeetingScenario(BaseScenario):
    def justified_holders(self, ctx, kinds):
        """Townsfolk with a real, evidenced intent toward the player:
        ``[(thing, rid, kind, fact)]`` (storyteller.justification)."""
        s = ctx.session
        director = getattr(s, "director", None)
        store = getattr(s, "store", None)
        if director is None or store is None:
            return []
        from ...sim import knowledge
        from ...sim.director import actor_key
        from ...sim.storyteller import justification
        out = []
        for rid, thing in list(ctx.world._residents.items()):
            p = thing.properties
            if p.get("dead") or str(p.get("type", "npc")) != "npc":
                continue
            key = actor_key(thing)
            cached = director.cached_intents(key)
            if not cached:
                continue
            known = None
            for intent in cached:
                if known is None:
                    known = {f.get("e"): f for f in knowledge.facts_view(store, key)}
                fact = known.get(intent.event_id)
                kind = justification(p, key, intent, fact)
                if kind in kinds:
                    out.append((thing, rid, kind, fact))
                    break
        return out

    def meet(self, ctx, t, kinds, scene_kind, hostile):
        from ...sim.director import actor_key
        done = {sc.get("fact_e") for sc in ctx.scenes.values()}
        import game.chatter as chatter
        for thing, rid, kind, fact in self.justified_holders(ctx, kinds):
            if fact.get("e") in done or not ctx._can_take(rid):
                continue
            spot = ctx._road_ahead(hostile=hostile)
            if spot is None:
                return ctx._no("no road the player is on has a free spot out of sight ahead")
            route, dest = ctx._toward_player(spot)
            sid = ctx._new_id()
            member = ctx._resident_member(thing, rid)
            victim = fact.get("target_name", "") if fact.get("target") != rid else ""
            if kind in ("vendetta", "reckoning"):
                member["armed"] = True
                member["grudge"] = True
                # What they shout as the fight opens (world._grudge_opening).
                member["grudge_kind"] = kind
                member["grudge_victim"] = victim
            line = chatter.justified_line(kind, victim, member["display"]) or ""
            j = ctx._new_journey("avenger", [member], route, dest, t,
                                  home=ctx.board.nearest_place(thing.pos[0], thing.pos[2], jn.HOMES))
            ctx._take_resident(j, rid)
            ctx._walking(j, route, dest, sid, "seeker", t, greeting=line)
            name = member["display"]
            errand = {"vendetta": "to find the player and settle it",
                      "reckoning": "to find the player and settle it",
                      "restitution": "to find the player and demand repayment",
                      "gratitude": "to find the player and thank them"}[kind]
            armed = ", armed," if member.get("armed") else ""
            tie_name = story_text.whom(fact, actor_key(thing), thing.properties)
            spoken = "me" if tie_name == "them" else tie_name.replace("their ", "my ", 1)
            return ctx._record(
                sid, scene_kind, {"seeker": j.id}, spot[7], spot[8], t,
                fact_e=fact.get("e"), justified=kind, gift=kind == "gratitude", reward=False,
                talk={"seeker": name, "victim_first": scene_talk._first(victim) if victim else "",
                      "deed": scene_talk.deed(fact.get("kind", ""),
                                              story_text.item_name(str(fact.get("item", "") or "")),
                                              spoken, ctx._place_of(fact)),
                      "owed": scene_talk.owed(fact.get("kind", ""), str(fact.get("item", "") or ""))
                      if kind == "restitution" else 0,
                      "scene": sid, "event": fact.get("e", 0)},
                decision=story_text.justified(kind, name, fact, actor_key(thing), thing.properties,
                                              ctx._place_of(fact)),
                result=(f"Spawned {name}{armed} ({ctx._from(j, False)}) on the road "
                        f"{ctx._where(spot[7], spot[8])}, and sent them {errand}, walking "
                        f"toward {story_text.PLAYER}."))
        return ctx._no("nobody holds a cached, evidenced intent of this kind toward the player "
                        f"({', '.join(kinds)}) and is free to leave")


class ReckoningScenario(MeetingScenario):
    kind = "reckoning"
    THOUGHTS = {
        "seeker": {
            "vendetta": {"calm": ("{victim_first} deserved better.", "Today it ends.")},
            "reckoning": {"calm": ("Not this time.", "I won't be beaten twice.")},
            "restitution": {"calm": ("I want what's mine.", "They'll pay, one way or another.")},
        },
    }
    display_name = "Reckoning"
    scene_name = "someone settling a score with you"
    hints = ("Someone is walking the road toward you with purpose.",)

    def stage(self, ctx, t):
        return self.meet(ctx, t, ("vendetta", "reckoning", "restitution"), "reckoning", True)

    def repaid(self, ctx, npc, scene_id, event, gold) -> None:
        """The player paid *gold* to someone come for repayment: the theft is
        settled (they want nothing more for it), the gold is theirs, and the
        scene is over."""
        s = ctx.session
        if event:
            s.store.set(f"crime.{int(event)}.settled", "1")
        try:
            from ...rpg import inventory as rpg_inventory
            from ...rpg import items as rpg_items
            coins = rpg_items.make("gold", int(gold)) or rpg_inventory.make_item(
                "gold", "Gold", qty=int(gold))
            rpg_inventory.add_item(rpg_inventory.get_inventory(npc), coins)
        except Exception:
            pass
        scene = ctx.scenes.get(scene_id or "")
        name = npc.properties.get("display_name") or npc.properties.get("name") or "They"
        if scene is not None and not scene.get("resolved"):
            scene["resolved"] = True
            ctx._narrate(f"Outcome: {name} was repaid {gold} gold by {story_text.PLAYER} -- "
                          "the theft is settled.", scene=scene["id"])

    def topic(self, role, talk, want=""):
        if role != "seeker" or want != "restitution":
            return None
        from .. import scene_talk as st
        t = st._known(talk)
        if not t.get("deed"):
            return None
        nodes = {}
        back = {"text": "I see.", "goto": "@start"}
        text = f"You {t['deed']}. I want it back -- or its worth, in gold."
        owed = int(t.get("owed", 0) or 0)
        if owed <= 0:
            return {"prompt": "What do you want?", "nodes": {
                "scene": {"text": text, "responses": [back]}}, "first": "scene"}
        nodes["scene_paid"] = {"text": "That squares it. We're done, you and I.",
                               "responses": [{"text": "Farewell.", "goto": "END"}]}
        nodes["scene_short"] = {"text": "Then find it. I'll not wait forever.",
                                "responses": [back]}
        nodes["scene_refuse"] = {"text": "Then we'll settle it some other way.",
                                 "responses": [{"text": "...", "goto": "END"}]}
        nodes["scene"] = {"text": f"{text} {owed} gold squares it.", "responses": [
            {"text": f"Here: {owed} gold.", "goto": "END",
             "condition": {"has_item": "gold", "qty": owed},
             "actions": [{"op": "scene_repay", "scene": t.get("scene", ""),
                          "event": t.get("event", 0), "gold": owed}]},
            {"text": f"I haven't got {owed} gold.", "goto": "scene_short",
             "condition": {"lacks_item": "gold", "qty": owed}},
            {"text": "I'm not paying you.", "goto": "scene_refuse"}]}
        return {"prompt": "What do you want?", "nodes": nodes, "first": "scene"}
