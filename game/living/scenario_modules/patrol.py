"""Watch Encounter: a patrol and brigands meet in a real fight."""

from .. import scene_talk
from ...sim import story_text
from .base import BaseScenario


class PatrolScenario(BaseScenario):
    kind = "patrol"
    display_name = "Watch Encounter"
    scene_name = "the watch fighting brigands"
    hints = ("Steel rings out on the road ahead.",)
    THOUGHTS = {
        "victim": {"calm": ("Brigands about. Stay sharp.",),
                   "combat": ("Hold the line!", "For the watch!")},
        "attacker": {"combat": ("Cut them down!",)},
    }
    AMBIENT = {
        "victim": ("In the name of the watch, lay down your arms!", "Form up! Form up!"),
        "attacker": ("Come on then, tin-hats!", "Not so brave without your walls!"),
    }

    def thank_line(self, scene):
        return "Good work, citizen. The watch won't forget it."

    def learned_intervention(self, name):
        return "they helped the watch beat the brigands"

    def topic(self, role, talk, want="")
        if role != "victim":
            return None
        from .. import scene_talk as st
        t = st._known(talk)
        text = f"{t.get('gang', 'Brigands')}'s gang, bold as you like, on the open road."
        if t.get("camp"):
            text += f" They came from {t['camp']}."
        return {"prompt": "What happened here?", "nodes": {
            "scene": {"text": text, "responses": [{"text": "I see.", "goto": "@start"}]}},
            "first": "scene"}

    def stage(self, ctx, t):
        spot = ctx._road_ahead(hostile=True)
        if spot is None:
            return ctx._no("no road the player is on has a free spot out of sight ahead")
        x, z = spot[7], spot[8]
        patrol = ctx._borrow(("patrol",), (x, z))
        if patrol is None:
            return ctx._no("no patrol of the watch off screen within reach")
        gang, borrowed = ctx._gang((x, z), t)
        if gang is None:
            return ctx._no("no gang on the roads and no camp to send one from")
        sid = ctx._new_id()
        ctx._hold(patrol, x, z, sid, "victim", t, borrowed=True, wander=60.0)
        ux, uz = ctx._side_offset(spot, 170.0)
        ctx._hold(gang, x + ux, z + uz, sid, "attacker", t, borrowed=borrowed, wander=60.0)
        ctx._keep_apart(patrol, gang)
        return ctx._record(
            sid, "patrol", {"victim": patrol.id, "attacker": gang.id}, x, z, t, reward=True,
            talk={"gang": ctx._lead(gang), "camp": ctx._camp(gang),
                  "captain": ctx._lead(patrol)},
            decision=(f"The storyteller decided that {ctx._lead(patrol)}'s patrol would run into "
                      f"{ctx._lead(gang)}'s brigands because both were on the roads nearby."),
            result=(f"Moved the patrol ({ctx._from(patrol, True)}) and the gang "
                    f"({ctx._from(gang, borrowed)}) onto the road {ctx._where(x, z)}, side by "
                    "side, so they fight as they come into reach."))

    # -- hooks from the living world -------------------------------------------
