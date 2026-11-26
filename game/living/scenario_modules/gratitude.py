"""Gratitude: a resident who remembers the player's help comes to thank them."""

from .reckoning import MeetingScenario


class GratitudeScenario(MeetingScenario):
    kind = "gratitude"
    display_name = "Gratitude"
    THOUGHTS = {
        "seeker": {
            "gratitude": {"calm": ("There they are. I owe them.", "I never thanked them properly.")},
        },
    }

    def stage(self, ctx, t):
        return self.meet(ctx, t, ("gratitude",), "gratitude", False)

    def maybe_gift(self, ctx, scene, px, pz, t):
        jid = scene["journeys"].get("seeker")
        things = ctx._live_things(jid)
        if not things:
            return
        lead = things[0]
        if math.hypot(lead.pos[0] - px, lead.pos[2] - pz) > THANK_RADIUS:
            return
        s = ctx.session
        scene["resolved"] = True
        j = ctx.board.journeys.get(jid)
        purse = ctx._purse(j, lead)
        amount = ctx._pay(j, lead, min(purse, max(5, min(40, purse // 2)))) if purse else 0
        s.bark(lead, "I never thanked you properly. Here -- it isn't much." if amount else
               "I never thanked you properly. I've nothing to give, but -- thank you.")
        credit = getattr(s, "_credit_found_gold", None)
        if credit is not None and amount:
            credit(amount, "Given")
        if j is not None:
            ctx._release(j, t)

    # -- housekeeping ------------------------------------------------------------

    def topic(self, role, talk, want=""):
        if role != "seeker" or want != "gratitude":
            return None
        from .. import scene_talk as st
        t = st._known(talk)
        if not t.get("deed"):
            return None
        text = f"You {t['deed']}. I've not forgotten it."
        return {"prompt": "Do I know you?", "nodes": {
            "scene": {"text": text, "responses": [
                {"text": "I see.", "goto": "@start"}]}}, "first": "scene"}
