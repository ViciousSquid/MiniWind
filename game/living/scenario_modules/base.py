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
    THOUGHTS = {}
    AMBIENT = {}

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
