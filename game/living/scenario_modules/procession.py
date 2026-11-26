"""Cult Procession: a travelling cult party on the road at night."""

from ...sim import story_text
from .base import BaseScenario


class ProcessionScenario(BaseScenario):
    kind = "procession"
    display_name = "Cult Procession"
    scene_name = "a cult procession"
    hints = ("Hooded figures walk the road ahead.",)
    THOUGHTS = {
        "attacker": {"calm": ("Walk in silence. Walk in shadow.", "The dark goes with us.")},
    }
    AMBIENT = {
        "attacker": ("By ash and by ember...", "Walk in shadow. Walk in silence.",
                     "The dark goes before us."),
    }

    def watch(self, ctx, scene, px, pz, t):
        return self.watch_solo_attacker(ctx, scene)

    def stage(self, ctx, t):
        spot = ctx._road_ahead(hostile=True)
        if spot is None:
            return ctx._no("no road the player is on has a free spot out of sight ahead")
        cult, borrowed = ctx._gang((spot[7], spot[8]), t, "cultists")
        if cult is None:
            return ctx._no("no cult on the roads and no camp to send one from")
        route, dest = ctx._toward_player(spot)
        sid = ctx._new_id()
        ctx._walking(cult, route, dest, sid, "attacker", t, borrowed=borrowed)
        return ctx._record(
            sid, "procession", {"attacker": cult.id}, spot[7], spot[8], t, reward=False,
            talk={"cult": ctx._lead(cult), "camp": ctx._camp(cult)},
            decision=(f"The storyteller decided that {ctx._lead(cult)}'s cult would walk the road "
                      f"toward {story_text.PLAYER} because it is night and a cult was within reach."),
            result=(f"Put {ctx._lead(cult)}'s cult ({ctx._from(cult, borrowed)}) on the road "
                    f"{ctx._where(spot[7], spot[8])} and sent them walking toward "
                    f"{story_text.PLAYER}."))
