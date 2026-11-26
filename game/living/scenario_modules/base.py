"""Shared contract and deliberately small service surface for world scenarios."""


def _scenarios():
    from .. import scenarios
    return scenarios


class ScenarioContext:
    """Shared world operations exposed to scenario implementations.

    The director remains the owner of global pacing, persistence and learning.
    Modules receive this context rather than the director itself.
    """
    def __init__(self, director):
        self._director = director

    @property
    def session(self):
        return self._director.session

    @property
    def world(self):
        return self._director.world

    @property
    def board(self):
        return self._director.board

    @property
    def scenes(self):
        return self._director.scenes

    @property
    def peaceful_kinds(self):
        from .. import scenarios
        return scenarios.PEACEFUL_KINDS

    @property
    def outlaw_factions(self):
        from .. import scenarios
        return scenarios.OUTLAW_FACTIONS

    @property
    def grievance_days(self):
        from .. import scenarios
        return scenarios.GRIEVANCE_DAYS

    @property
    def quarry_gap(self):
        from .. import scenarios
        return scenarios.QUARRY_GAP

    @property
    def hold_hours(self):
        from .. import scenarios
        return scenarios.HOLD_HOURS

    @property
    def rite_hours(self):
        from .. import scenarios
        return scenarios.RITE_HOURS

    @property
    def thank_radius(self):
        from .. import scenarios
        return scenarios.THANK_RADIUS

    def _no(self, why):
        return self._director._no(why)

    def _road_ahead(self, hostile=True, min_d=None, max_d=None, rng_jitter=0.3):
        return self._director._road_ahead(hostile, min_d, max_d, rng_jitter)

    def _toward_player(self, spot):
        return self._director._toward_player(spot)

    def _away_from_player(self, spot, extra=0.0):
        return self._director._away_from_player(spot, extra)

    def _new_id(self):
        return self._director._new_id()

    def _new_journey(self, kind, members, route, dest, t, home=None):
        return self._director._new_journey(kind, members, route, dest, t, home)

    def _hold(self, j, x, z, scene_id, role, t, hours=None, greeting="",
              wander=90.0, borrowed=False):
        return self._director._hold(j, x, z, scene_id, role, t, hours, greeting, wander, borrowed)

    def _walking(self, j, route, dest, scene_id, role, t, greeting="", borrowed=False):
        return self._director._walking(j, route, dest, scene_id, role, t, greeting, borrowed)

    def _borrow(self, kinds, near_xz, max_dist=9000.0):
        return self._director._borrow(kinds, near_xz, max_dist)

    def _gang(self, near_xz, t, kind="bandits"):
        return self._director._gang(near_xz, t, kind)

    def _resident_member(self, thing, rid):
        return self._director._resident_member(thing, rid)

    def _can_take(self, rid):
        return self._director._can_take(rid)

    def _take_resident(self, j, rid):
        return self._director._take_resident(j, rid)

    def _side_offset(self, spot, distance):
        return self._director._side_offset(spot, distance)

    def _keep_apart(self, *journeys):
        return self._director._keep_apart(*journeys)

    def _record(self, sid, kind, journeys, x, z, t, **extra):
        return self._director._record(sid, kind, journeys, x, z, t, **extra)

    def _place_at(self, x, z):
        return self._director._place_at(x, z)

    def _where(self, x, z):
        return self._director._where(x, z)

    def _from(self, journey, borrowed):
        return self._director._from(journey, borrowed)

    def _camp(self, journey):
        return self._director._camp(journey)

    def _lead(self, journey):
        return self._director._lead(journey)

    def _place_of(self, fact):
        return self._director._place_of(fact)

    def _live_things(self, jid):
        return self._director._live_things(jid)

    def _party_up(self, jid):
        return self._director._party_up(jid)

    def _learn_scene(self, scene, stepped_in, how):
        return self._director._learn_scene(scene, stepped_in, how)

    def _purse(self, journey, lead):
        return self._director._purse(journey, lead)

    def _pay(self, journey, lead, amount):
        return self._director._pay(journey, lead, amount)

    def _release(self, journey, t, dest=None):
        return self._director._release(journey, t, dest)

    def _narrate(self, text, log=True, **data):
        return self._director._narrate(text, log=log, **data)


class BaseScenario:
    """Identity plus shared formatting for scene-derived dialogue."""
    kind = ""
    display_name = ""
    scene_name = ""
    hints = ()
    THOUGHTS = {}
    AMBIENT = {}

    def spawned(self, ctx, scene, journey, things):
        """Handle scenario-specific work when staged actors materialise."""
        return None

    def stage_expired(self, ctx, journey, scene, role, t):
        """Handle scenario-specific expiry; return None for shared release handling."""
        return None

    def watch(self, ctx, scene, px, pz, t):
        """Handle scenario-specific watch behaviour; return True when consumed."""
        return False

    def thank_line(self, scene):
        return "Gods bless you, stranger -- they'd have had everything."

    def reward(self, ctx, scene, journey, lead, purse):
        if not scene.get("reward") or journey is None:
            return 0
        want = min(120, purse // 2 + ctx.session.rng.randint(5, 25))
        return ctx._pay(journey, lead, min(purse, max(10, want)))

    def learned_intervention(self, name):
        return f"they came to {name}'s aid"

    def watch_solo_attacker(self, ctx, scene):
        """Resolve a scene whose only party is the attacking side."""
        journeys = scene.get("journeys") or {}
        if set(journeys) != {"attacker"}:
            return False
        if not ctx._party_up(journeys["attacker"]) and scene.get("hinted"):
            from ...sim import story_text
            scene["resolved"] = True
            ctx._learn_scene(scene, True, "they took the fight to it")
            ctx._narrate(
                f"Outcome: {self.scene_name or self.display_name} is over -- "
                f"{story_text.PLAYER} came near and the attackers are gone.",
                scene=scene["id"])
        return True

    def thoughts(self, role, talk, want=""):
        from .. import scene_talk
        table = self.THOUGHTS.get(role) or {}
        if role == "seeker":
            table = table.get(want) or {}
        known = scene_talk._known(talk)
        result = {}
        for situation, lines in table.items():
            said = scene_talk._fmt(lines, known)
            if said:
                result[situation] = said
        return result

    def ambient(self, role, talk):
        from .. import scene_talk
        return scene_talk._fmt(self.AMBIENT.get(role) or (), scene_talk._known(talk))

    def topic(self, role, talk, want=""):
        return None
