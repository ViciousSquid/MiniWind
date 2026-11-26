"""Waylaid Traveller: the real traveller, the real gang and their robbery."""

from .. import scene_talk
from ...sim import story_text
from .base import BaseScenario


class WaylaidScenario(BaseScenario):
    kind = "waylaid"
    display_name = "Waylaid Traveller"
    scene_name = "a traveller waylaid"
    hints = ("Shouts carry from the road ahead.", "Someone is crying for help up the road.")
    THOUGHTS = {
        "victim": {
            "calm": ("Keep still. Don't look at them.", "Not here... not now.",
                     "We should have stayed in {origin}."),
            "flee": ("My purse... my life...", "Someone, please!", "Run! Just run!"),
            "combat": ("Not without a fight!",),
        },
        "attacker": {
            "calm": ("Easy pickings.", "Fat purse on that one.", "{victim_first} won't miss it.")
        },
    }
    AMBIENT = {
        "victim": ("Please, we've nothing worth killing for!", "Take it -- just let us go!",
                   "We're only bound for {dest}!", "Help! Somebody, help!"),
        "attacker": ("Hand it over, {victim_first}!", "Your purse or your life!",
                     "Nobody's coming to help you.", "Empty the packs. All of it."),
    }

    def topic(self, role, talk, want=""):
        if role != "victim":
            return None
        from .. import scene_talk as st
        t = st._known(talk)
        nodes = {}
        back = {"text": "I see.", "goto": "@start"}
        camp = t.get("camp")
        text = (f"{t.get('gang', 'Brigands')} and their lot came at us on the road"
                f"{st._near(t.get('here', ''))}. They wanted everything we carry.")
        if t.get("dest"):
            text += f" We were only bound for {t['dest']}."
        replies = [back]
        if camp:
            nodes["scene_from"] = {"text": f"From the {camp} way. That's where they'll run back to.",
                                   "responses": [back]}
            replies = [{"text": "Where did they come from?", "goto": "scene_from"}, back]
        nodes["scene"] = {"text": text, "responses": replies}
        return {"prompt": "What happened here?", "nodes": nodes, "first": "scene"}

    def stage(self, ctx, t):
        """A real traveller on the roads, set upon by a real gang ahead."""
        spot = ctx._road_ahead(hostile=True)
        if spot is None:
            return ctx._no("no road the player is on has a free spot out of sight ahead")
        x, z = spot[7], spot[8]
        victim = ctx._borrow(ctx.peaceful_kinds, (x, z))
        if victim is None:
            return ctx._no("no peaceful traveller off screen within reach to be waylaid")
        gang, borrowed = ctx._gang((x, z), t)
        if gang is None:
            return ctx._no("no gang on the roads and no camp to send one from")
        sid = ctx._new_id()
        ctx._hold(victim, x, z, sid, "victim", t, borrowed=True, wander=40.0)
        ux, uz = ctx._side_offset(spot, 130.0)
        ctx._hold(gang, x + ux, z + uz, sid, "attacker", t, borrowed=borrowed, wander=60.0)
        ctx._keep_apart(victim, gang)
        v, g = ctx._lead(victim), ctx._lead(gang)
        return ctx._record(
            sid, "waylaid", {"victim": victim.id, "attacker": gang.id}, x, z, t, reward=True,
            talk={"victim": v, "victim_first": scene_talk._first(v), "gang": g,
                  "camp": ctx._camp(gang), "here": ctx.board.place_name(ctx._place_at(x, z)),
                  "origin": ctx.board.place_name(victim.origin),
                  "dest": ctx.board.place_name(victim.dest)},
            decision=(f"The storyteller decided that {g}'s brigands would set upon {v} "
                      f"({victim.kind}, {ctx._from(victim, True)}) because they were the nearest "
                      "peaceful travellers off screen and a gang was within reach."),
            result=(f"Moved {v}'s party and {g}'s gang ({ctx._from(gang, borrowed)}) onto the road "
                    f"{ctx._where(x, z)}, side by side, so the fight starts as they come into reach "
                    f"-- with or without {story_text.PLAYER}."))
