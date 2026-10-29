"""Session-owned read-only sensors for the headless storyteller."""

import math

from .sim.storyteller import StorytellerHooks, TUNING


#: Slack (world units) on the hostile prefilter for movement since the rebuild.
REBUILD_MARGIN = 512.0


class SessionStorytellerHooks(StorytellerHooks):
    def __init__(self, session):
        self.session = session

    def actors(self):
        return self.session._sim_actors()

    def _town_at(self, pos):
        living = self.session.living
        if living is None or living.board is None or pos is None:
            return None
        key = living.board.nearest_place(pos[0], pos[2], TUNING["town_kinds"])
        place = living.places.get(key)
        if place and math.hypot(pos[0] - place["x"], pos[2] - place["z"]) <= place["radius"]:
            return key
        return None

    def actor_town(self, actor):
        # An away resident's hidden home proxy is not their current location.
        if actor.properties.get("away_on_journey"):
            return None
        return self._town_at(actor.pos)

    def player_town(self):
        return self._town_at(self.session._player_pos())

    def player_region(self):
        living = self.session.living
        pos = self.session._player_pos()
        if living is None or living.board is None or pos is None:
            return None
        return pos[0], pos[2], living.reach()

    def hostile_materialisations(self):
        living = self.session.living
        pos = self.session._player_pos()
        if living is None or living.board is None or pos is None:
            return None, 0
        board = living.board
        region = board.nearest_place(pos[0], pos[2], TUNING["town_kinds"])
        return region, board.hostile_materialisations.get(region, 0)

    def player_health_fraction(self):
        c = self.session.game.character
        return float(c.health) / max(1.0, float(c.max_health))

    def hostile_counts_by_tier(self):
        s = self.session
        index = s.world_index
        player = s.player_actor
        if player.pos is None:
            return {}
        if not getattr(s, "_wi_live", True):
            # Small casts bypass the session's per-frame index, which may
            # still contain an older large cast. Snapshot only on sampling;
            # leave that shared index and its optimisation untouched.
            index = type(index)()
            index.rebuild(s._sim_actors())

        def perceived_hostile(actor):
            p = actor.properties
            return (not p.get("dead") and not p.get("hidden") and not p.get("disabled")
                    and s._tier_of(actor) in TUNING["threat_tiers"]
                    and (s._natively_hostile(p) or p.get("_aggro_target") == id(player))
                    and math.hypot(actor.pos[0] - player.pos[0], actor.pos[2] - player.pos[2]) <= TUNING["sight_radius"]
                    and s._law_visible(player, actor.pos))

        # The index's positions date from this tick's rebuild; the margin keeps
        # anyone who has stepped into sight since, and the predicate decides.
        near = (player.pos[0], player.pos[2], TUNING["sight_radius"] + REBUILD_MARGIN)
        return index.counts_by_tier(predicate=perceived_hostile, near=near)

    def law_pressure(self):
        # Reading bounty()/record() would create records; project existing rows.
        return {region: {"bounty": sum(int(c["amount"]) for c in row["charges"].values()),
                         "phase": row["phase"]}
                for region, row in self.session.law.regions.items()}

    def market_traffic(self):
        from .footprint import market_traffic
        living = self.session.living
        return market_traffic(living.board if living is not None else None)

    def player_wealth(self):
        from .rpg.inventory import total_value
        c = self.session.game.character
        return total_value(getattr(c, "inventory", [])) + float(getattr(c, "gold", 0))

    def player_karma(self):
        return float(getattr(self.session.game.character, "alignment", 0.0))
