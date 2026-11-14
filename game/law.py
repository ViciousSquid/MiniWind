"""Scene glue for settlement watches. Movement, gossip and combat stay shared."""

from __future__ import annotations

import math
import time

from .sim import crime, knowledge, perception
from .sim.director import PLAYER_KEY, actor_key
from .sim.law import SEARCH_RADIUS


#: Seconds an observer's roll to notice the sneaking player stands before it
#: rolls again (RULES.md §11).
NOTICE_MEMORY = 6.0


class SettlementLaw:
    def _law_now(self):
        return self.clock.day * 24.0 + self.clock.hour

    def _law_region(self, pos=None, npc=None):
        if npc is not None and npc.properties.get("law_region"):
            return str(npc.properties["law_region"])
        pos = pos if pos is not None else self._player_pos()
        if pos is None:
            return self.region_name
        # Jurisdictions are static scenery: their radii and names are read
        # once per marker set, not on each of the dozens of asks a tick makes.
        markers = self._things_of_type("marker")
        cached = getattr(self, "_law_regions", None)
        if cached is None or cached[0] is not markers or cached[2] != len(markers):
            areas = [(m, float(m.properties.get("radius", 2200.0)),
                      str(m.properties.get("law_region") or m.properties.get("name")))
                     for m in self._markers_of_kind("jurisdiction")]
            areas.extend((m, float(m.properties.get("radius", 2200.0)),
                          str(m.properties.get("law_region")))
                         for m in self._markers_of_kind("location")
                         if m.properties.get("law_region"))
            cached = self._law_regions = (markers, areas, len(markers))
        x, z = pos[0], pos[2]
        nearest, nearest_d = None, None
        for marker, radius, name in cached[1]:
            mp = marker.pos
            d = math.hypot(x - mp[0], z - mp[2])
            if d <= radius and (nearest_d is None or d < nearest_d):
                nearest, nearest_d = name, d
        return nearest if nearest is not None else self.region_name

    def _law_sync(self):
        # Keep the character sheet, disposition and save format's old aggregate.
        self.law.migrate(self._law_region(), int(self.game.character.bounty or 0))
        self.game.character.bounty = self.law.total

    def _guard_knows_writ(self, guard, region):
        charges = self.law.record(region)["charges"]
        if "legacy" in charges:
            return True
        return any(str(f.get("e")) in charges and f.get("actor") == self.player_key
                   and f.get("identified", True)
                   and float(f.get("certainty", 0)) >= crime.REPORT_CERTAINTY
                   for f in knowledge.facts(self.store, actor_key(guard)))

    def notices_sneaking_player(self, observer, distance=None) -> bool:
        """Whether *observer*, who has the player in plain sight, notices
        them. Standing, always. Sneaking, it rolls to notice them -- a d20 at
        :func:`game.sim.perception.notice_chance`, in a roll box over it
        (RULES.md §1, §11) -- and that roll stands for
        :data:`NOTICE_MEMORY` seconds, so asking again (every look a patrol
        takes) never rolls again until then. Beyond its sneak-shortened
        sight it sees nothing and rolls nothing."""
        if not getattr(getattr(self, "game", None), "sneaking", False):
            return True
        player = self.player_actor
        if player is None or observer is None or getattr(observer, "pos", None) is None:
            return True
        props = observer.properties
        reach = (perception.sight_range(props, self.clock.hour)
                 * perception.stealth_factor(player.properties))
        if distance is None:
            distance = self._dist2d(observer.pos, player.pos)
        chance = perception.notice_chance(distance, reach)
        if chance <= 0.0:
            return False
        memo = self.__dict__.setdefault("_notice_rolls", {})
        now = time.monotonic()
        held = memo.get(id(observer))
        if held is not None and held[1] > now:
            return held[0]
        if self.game.dice is None:
            return True
        from .diceroll import roll_check
        name = str(props.get("display_name") or props.get("name") or "Someone")
        roll = roll_check(self.game.dice, chance, f"{name} rolls to notice you",
                          source="sneak.notice",
                          why=f"You sneak, {distance:.0f} of their {reach:.0f} away — "
                              f"{chance * 100:.0f}%",
                          # In this player's log alone, like a blow at them.
                          context={"quiet": True, "against_player": True})
        roll["notice"] = True            # what they saw is told when it lands
        self.show_roll_box(observer, roll, against=("YOU", "you"))
        for key in [k for k, (_seen, until) in memo.items() if until <= now]:
            del memo[key]
        memo[id(observer)] = (bool(roll["success"]), now + NOTICE_MEMORY)
        return bool(roll["success"])

    def _guard_sees_player(self, guard):
        """The same darkness/stealth rules as witnesses, plus the scene's walls
        -- and, while the player sneaks, the guard's roll to notice them."""
        p = guard.properties
        if p.get("dead") or perception._is_asleep(p):
            return False
        actor = self.player_actor
        if self.game.character.effect_magnitude("invisibility") > 0:
            return False
        reach = perception.sight_range(p, self.clock.hour)
        reach *= perception.stealth_factor(actor.properties)
        distance = self._dist2d(guard.pos, actor.pos)
        if distance > reach:
            return False
        if not self._law_visible(guard, actor.pos):
            return False
        # Sneaking, in plain sight: the guard rolls to notice you.
        return self.notices_sneaking_player(guard, distance)

    def _law_visible(self, observer, pos):
        runtime = getattr(self.logic, "session_runtime", None)
        grid = getattr(runtime, "spatial_grid", None)
        if grid is not None:
            import glm
            eye = glm.vec3(*observer.pos) + glm.vec3(0, 60, 0)
            target = glm.vec3(*pos) + glm.vec3(0, 60, 0)
            return bool(grid.has_line_of_sight(eye, target))
        return True

    def _raise_hue_and_cry(self, region, reporter_key, event):
        """A named accusation shouted within earshot, never a world broadcast."""
        now = self._law_now()
        row = self.law.record(region)
        if now - row["bell_at"] < 1.0:
            return
        reporter = self._sim_actor_by_key(reporter_key)
        if reporter is None:
            return
        row["bell_at"] = now
        account = knowledge.knows(self.store, reporter_key, event.id)
        if account is None:
            return
        self.bark(reporter, "Raise the hue and cry! A blood writ for this outlaw!")
        for guard in self.npcs():
            if not self._is_guard(guard) or self._law_region(guard.pos, guard) != region:
                continue
            if self._dist2d(guard.pos, reporter.pos) <= 1800.0:
                knowledge.tell(self.store, reporter_key, actor_key(guard), account, decay=0.0)
                self.director.invalidate(guard)
        event.note("the watch raised the hue and cry within earshot")
        self.law.persist()

    def witness_markers(self):
        """Live messengers carrying unreported player crimes, for both maps.

        Includes indirect accounts: word of mouth can make a new messenger.
        A dead, silenced, uncertain or already-reporting-complete witness drops
        out without a second marker lifecycle or a duplicate witness registry.

        Drawn every frame by the minimap, so it is answered from what changed:
        the roster (non-guard NPCs and their belief keys) follows the NPC set
        and the change journal (an NPC's role, side or death); the accounts
        are re-derived only when a belief token, a death or a reported flag
        changes. Positions are read fresh for the (few) witnesses.
        """
        from engine.change_journal import JOURNAL, OVERFLOW
        store = self.store
        bucket = self._things_of_type("npc")
        roster = getattr(self, "_witness_roster", None)
        if roster is None:
            roster = self._witness_roster = _WitnessRoster()
        changes = JOURNAL.drain(roster)
        if roster.bucket is not bucket or roster.count != len(bucket) or changes is OVERFLOW:
            roster.rebuild(self, bucket)
        elif changes:
            roster.refresh(self, changes)
        cache = roster.cache
        token = (knowledge.tokens(store, cache["keys"]),
                 tuple([bool(npc.properties.get("dead")) for npc in cache["npcs"]]),
                 tuple([crime.already_reported(store, e)
                        for _npc, _identified, events in cache["witnesses"] for e in events]))
        if token != cache["token"]:
            witnesses = []
            for npc, key in cache["roster"]:
                if npc.properties.get("dead"):
                    continue
                accounts = [f for f in knowledge.facts_view_key(store, key)
                            if f.get("actor") == self.player_key and crime.is_crime(f)
                            and not f.get("reported")
                            and not crime.already_reported(store, f.get("e", 0))
                            and float(f.get("certainty", 0)) >= crime.REPORT_CERTAINTY]
                if accounts:
                    witnesses.append((npc, any(f.get("identified", True) for f in accounts),
                                      tuple(f.get("e", 0) for f in accounts)))
            cache["witnesses"] = witnesses
            # The reported flags of the accounts just read are part of the key.
            cache["token"] = token[:2] + (tuple([
                crime.already_reported(store, e)
                for _npc, _identified, events in witnesses for e in events]),)
        out = []
        for npc, identified, _events in cache["witnesses"]:
            p = npc.properties
            out.append({"x": float(npc.pos[0]), "z": float(npc.pos[2]),
                        "name": str(p.get("display_name") or p.get("name", "Witness")),
                        "identified": identified,
                        "reporting": p.get("sched_state") == "REPORT",
                        "state": "identified" if identified else "uncertain"})
        return out

    def law_status(self):
        region = self._law_region()
        row = self.law.record(region)
        return {"region": region, "bounty": self.law.bounty(region),
                "phase": row["phase"], "blood": self.law.blood_writ(region),
                "curfew": self.law.curfew(region, self._law_now()),
                "remaining": self.law.remaining(region),
                "show_radius": str(self.store.get("law.searchradius", "1")) != "0",
                "centre": row["last_pos"], "radius": SEARCH_RADIUS}

    def _law_payment_tree(self, guard, tree):
        """Keep authored guard conversations and append an optional local fine."""
        from copy import deepcopy
        region = self._law_region(guard.pos, guard)
        amount = self.law.bounty(region)
        if not amount or self._arrest_state == "pursuit":
            return tree
        tree = deepcopy(tree)
        node = tree.get("nodes", {}).get(tree.get("start"))
        if isinstance(node, dict):
            node.setdefault("responses", []).insert(0, {
                "text": f"Settle my writ in {region} ({amount} gold).",
                "goto": "END", "actions": [{"op": "pay_bounty"}]})
        return tree


class _WitnessRoster:
    """The NPCs who could carry word of a crime (not guards), with their
    belief keys: rebuilt when the NPC set changes, re-checked per NPC when the
    change journal says that NPC changed (a guard's role, a side, a death)."""

    __slots__ = ("bucket", "count", "guard", "by_id", "cache", "__weakref__")

    def __init__(self):
        self.bucket = None
        self.count = -1
        self.guard = {}
        self.by_id = {}
        self.cache = None

    def rebuild(self, law, bucket):
        self.bucket, self.count = bucket, len(bucket)
        self.by_id = {id(npc): npc for npc in bucket}
        self.guard = {key: bool(law._is_guard(npc)) for key, npc in self.by_id.items()}
        self._publish(bucket)

    def refresh(self, law, changes):
        """Re-check the NPCs whose state the journal says changed (a move
        alone cannot make or unmake a guard)."""
        from engine.change_journal import STATE
        by_id, guard = self.by_id, self.guard
        flipped = False
        for key, flags in changes.items():
            if not flags & STATE:
                continue
            npc = by_id.get(key)
            if npc is None:
                continue
            now = bool(law._is_guard(npc))
            if guard.get(key) != now:
                guard[key] = now
                flipped = True
        if flipped:
            self._publish(self.bucket)

    def _publish(self, bucket):
        guard = self.guard
        roster = [(npc, knowledge.facts_key(actor_key(npc))) for npc in bucket
                  if not guard.get(id(npc))]
        old = self.cache
        if old is not None and old["roster"] == roster:
            return
        self.cache = {"roster": roster, "npcs": [npc for npc, _ in roster],
                      "keys": [key for _, key in roster], "token": None, "witnesses": []}
