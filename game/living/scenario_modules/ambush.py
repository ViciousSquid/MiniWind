"""Ambush: brigands wait along the road after dark."""

from ...sim import story_text
from .base import BaseScenario


class AmbushScenario(BaseScenario):
    kind = "ambush"
    display_name = "Ambush"
    scene_name = "an ambush"
    hints = ("The road ahead has gone very quiet.",)
    THOUGHTS = {
        "attacker": {"calm": ("Quiet now. Wait for it.", "Here they come...",
                              "Nobody move till they're close.")},
    }

    def watch(self, ctx, scene, px, pz, t):
        return self.watch_solo_attacker(ctx, scene)

    def stage(self, ctx, t):
        spot = ctx._road_ahead(hostile=True)
        if spot is None:
            return ctx._no("no road the player is on has a free spot out of sight ahead")
        gang, borrowed = ctx._gang((spot[7], spot[8]), t)
        if gang is None:
            return ctx._no("no gang on the roads and no camp to send one from")
        sid = ctx._new_id()
        ctx._hold(gang, spot[7], spot[8], sid, "attacker", t, borrowed=borrowed, wander=70.0)
        return ctx._record(
            sid, "ambush", {"attacker": gang.id}, spot[7], spot[8], t, reward=False,
            talk={"gang": ctx._lead(gang), "camp": ctx._camp(gang)},
            decision=(f"The storyteller decided that {ctx._lead(gang)}'s brigands would lie in "
                      f"wait for {story_text.PLAYER} because it is dark and a gang was within reach."),
            result=(f"Put {ctx._lead(gang)}'s gang ({ctx._from(gang, borrowed)}) in hiding by the "
                    f"road, {ctx._where(spot[7], spot[8])}; they attack when {story_text.PLAYER} "
                    "comes within sight."))
