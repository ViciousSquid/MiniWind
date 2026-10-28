"""Faction actors grounded in local people and their inspectable knowledge.

The storyteller cannot call decide(): it only reads projections. A faction
learns through members at its home and returning survivors, never event history.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from . import appraisal, crime, knowledge, moods
from .director import actor_key

STORE_KEY = "factions.state"
VERSION = 1
HOSTILE_GOODWILL = -20
CRIME_COST = {"death": -40, "attack": -12, "theft": -8, "lockpick": -5, "trespass": -3}
KINDNESS = {"heal": 12, "gift": 5, "trade": 2}


def identity(actor):
    # mem_key may memoise on properties: projections must use a detached view.
    return actor_key(SimpleNamespace(properties=dict(actor.properties)))


def ledger(faction, accounts):
    """Deduplicated directed goodwill, with a receipt for every contribution.

    accounts is (holder key, facts). Strongest identified account per event
    wins, regardless of gossip count. Legacy missing factions stay unknown.
    Heal is the existing vocabulary's rescue; no diplomacy event is invented.
    """
    best = {}
    for holder, facts in accounts:
        for fact in facts:
            eid = int(fact.get("e", 0) or 0)
            subject = str(fact.get("actor", ""))
            other = str(fact.get("actor_faction", ""))
            target_faction = str(fact.get("target_faction", ""))
            if (not eid or not subject or not other or other == faction
                    or target_faction != faction or not fact.get("identified", True)
                    or float(fact.get("certainty", 0)) < crime.REPORT_CERTAINTY):
                continue
            kind = fact.get("kind")
            amount = CRIME_COST.get(kind, 0) if crime.is_crime(fact) else KINDNESS.get(kind, 0)
            if not amount:
                continue
            row = dict(event=eid, holder=holder, subject=subject, faction=other,
                       amount=round(amount * float(fact["certainty"]), 6),
                       fact=copy.deepcopy(fact))
            prior = best.get(eid)
            if prior is None or (fact["certainty"], holder) > (prior["fact"]["certainty"], prior["holder"]):
                best[eid] = row
    rows = sorted(best.values(), key=lambda r: r["event"])
    totals = {}
    for row in rows:
        totals[row["faction"]] = round(totals.get(row["faction"], 0) + row["amount"], 6)
    return dict(totals=totals, receipts=rows)


class FactionSpine:
    def __init__(self, store, director, enabled=lambda: True):
        self.store, self.director, self.enabled = store, director, enabled
        self.board = None
        self.members = {}
        self.restore()

    def reset(self):
        self.entities = {}
        self.ledgers = {}
        self.intents = {}
        self.orders = []
        self.dispatched = set()
        self.receipts = []
        self.last_decision = None
        self._member_sources = {}
        self.begin_tick()

    def begin_tick(self):
        """Start a shared board-update projection, including decisions/streaming.

        These caches are transient. Reads never populate the director's intent
        cache or consume dirty flags, write knowledge, or draw randomness.
        """
        self._cache_tick = getattr(self, "_cache_tick", 0) + 1
        self._cache_revision = self.director.knowledge_revision
        self._fact_cache = {}
        self._goodwill_cache = {}
        self._mood_cache = {}
        self._traffic = None

    def _sync_caches(self):
        revision = self.director.knowledge_revision
        if revision != self._cache_revision:
            self._cache_revision = revision
            self._goodwill_cache.clear()
            self._mood_cache.clear()

    def facts(self, key):
        """Parse each unchanged holder's facts once per board update."""
        raw = knowledge.token(self.store, key)
        cached = self._fact_cache.get(key)
        if cached is None or cached[0] != raw:
            cached = (raw, knowledge.facts(self.store, key))
            self._fact_cache[key] = cached
        return copy.deepcopy(cached[1])

    def context_key(self, actor):
        """Cheap dependencies for the director's ordinary intent cache."""
        p = actor.properties
        return (self._cache_tick, self.director.knowledge_revision, self.enabled(),
                p.get("courage"), p.get("alignment"), p.get("npc_role"), p.get("creature_role"),
                p.get("faction"), p.get("team"),
                knowledge.token(self.store, identity(actor)))

    def bind(self, board, actors):
        """Discover homes from real scene actors; never fabricate a force."""
        self.board = board
        self.members = {}
        entities = {}
        for actor in actors:
            p = actor.properties
            faction = str(p.get("faction") or p.get("team") or "").strip().lower()
            if faction in ("", "player", "wildlife") or p.get("_journey") or p.get("dead"):
                continue
            home = board.nearest_place(actor.pos[0], actor.pos[2])
            place = board.places.get(home)
            if not place or home not in board.network.place_node:
                continue
            if ((actor.pos[0] - place["x"]) ** 2 + (actor.pos[2] - place["z"]) ** 2
                    > float(place.get("radius", 2500)) ** 2):
                continue
            key = f"faction_{faction}_{home}"
            entities[key] = self.entities.get(key, dict(faction=faction, home=home))
            self.members.setdefault(key, {})[identity(actor)] = actor
        self.entities = entities
        self.ledgers = {k: v for k, v in self.ledgers.items() if k in entities}
        self.intents = {k: v for k, v in self.intents.items() if k in entities}
        self.orders = [o for o in self.orders if o["cause"]["entity"] in entities]
        self._member_sources.clear()
        self.begin_tick()

    def actor(self, key):
        row = self.entities[key]
        place = self.board.places[row["home"]]
        return SimpleNamespace(properties=dict(id=key, name=key, faction=row["faction"],
                               type="faction", _faction_actor=True, combatant=True, courage=0.8),
                               pos=[place["x"], 0, place["z"]])

    def _at_home(self, key):
        for member, actor in sorted(self.members.get(key, {}).items()):
            p = actor.properties
            if not p.get("dead") and not p.get("away_on_journey"):
                place = self.board.places[self.entities[key]["home"]]
                if ((actor.pos[0] - place["x"]) ** 2 + (actor.pos[2] - place["z"]) ** 2
                        <= float(place.get("radius", 2500)) ** 2):
                    yield member

    def accounts(self, key):
        yield key, self.facts(key)
        for member in self._at_home(key):
            yield member, self.facts(member)

    def goodwill(self, faction, other):
        # Recompute from facts, rather than retaining a hidden reputation score.
        if not self.enabled():
            return 0.0
        self._sync_caches()
        if faction not in self._goodwill_cache:
            accounts = (account for key, row in self.entities.items() if row["faction"] == faction
                        for account in self.accounts(key))
            self._goodwill_cache[faction] = ledger(faction, accounts)["totals"]
        return self._goodwill_cache[faction].get(other, 0.0)

    def mood(self, actor, facts):
        if not self.enabled() or self.board is None:
            return None
        self._sync_caches()
        key = identity(actor)
        # Include the supplied beliefs so direct pure evaluations of a detached
        # fact list cannot accidentally reuse another evaluation's mood.
        belief_key = tuple((f.get("e"), f.get("kind"), f.get("actor"), f.get("identified", True),
                            f.get("certainty"), f.get("actor_alignment")) for f in facts)
        stamp = self.context_key(actor), belief_key
        cached = self._mood_cache.get(key)
        if cached is None or cached[0] != stamp:
            from ..footprint import market_traffic
            if self._traffic is None:
                self._traffic = market_traffic(self.board)
            home = self.board.nearest_place(actor.pos[0], actor.pos[2])
            faction = str(actor.properties.get("faction", ""))
            feeling = moods.evaluate(actor.properties, facts, min(1.0, self._traffic.get(home, 0) / 4),
                                     self.goodwill(faction, "player"))
            cached = (stamp, feeling)
            self._mood_cache[key] = cached
        return copy.deepcopy(cached[1])

    def _tell(self, speaker, listener, fact):
        if knowledge.tell(self.store, speaker, listener, fact, decay=0.0):
            self.director.invalidate(listener)

    def _hear_members(self, key):
        for holder in self._at_home(key):
            raw = knowledge.token(self.store, holder)
            previous = self._member_sources.get((key, holder))
            if previous is not None and previous[0] == raw:
                continue
            facts = self.facts(holder)
            old = previous[1] if previous is not None else {}
            for fact in facts:
                if old.get(fact.get("e")) != fact:
                    self._tell(holder, key, fact)
            self._member_sources[key, holder] = (raw, {f.get("e"): f for f in facts})

    def decide(self, t):
        """An actor decision touchpoint, called before board sampling, never by it."""
        if not self.enabled() or self.board is None:
            return
        if self.last_decision is not None and t - self.last_decision < 1.0:
            return
        self.last_decision = float(t)
        self.orders = []
        for key, entity in sorted(self.entities.items()):
            if key not in self.members or entity["home"] not in self.board.places:
                continue
            # Members communicate only at home. Copies remain ordinary facts,
            # with the original witness and retelling chain available to inspect.
            self._hear_members(key)
            known = self.facts(key)
            account = ledger(entity["faction"], [(key, known)])
            self.ledgers[key] = account
            ctx = appraisal.Context(hostile=self.director.ctx.hostile, store=self.store,
                                    goodwill=lambda a, b: account["totals"].get(b, 0))
            intents = appraisal.appraise_all(self.actor(key).properties, key, known, ctx)
            self.intents[key] = [dict(i.to_dict(), fact=copy.deepcopy(i.fact)) for i in intents]
            for intent in intents:
                if intent.reaction != appraisal.FIGHT or not intent.event_id:
                    continue
                token = (key, intent.event_id)
                if token in self.dispatched:
                    continue
                fact = intent.fact
                # A later known deed can establish a trail after an offence
                # at home. Never consult the offender's live scene position.
                trail = max((f for f in known if f.get("actor") == intent.target
                             and f.get("identified", True)
                             and float(f.get("certainty", 0)) >= crime.REPORT_CERTAINTY),
                            key=lambda f: (f.get("day", 0), f.get("hour", 0), f.get("e", 0)),
                            default=fact)
                pos = trail.get("pos", [0, 0, 0])
                dest = self.board.nearest_place(pos[0], pos[2])
                home = entity["home"]
                # No current-position oracle. Go to the last known scene,
                # and only if it is somewhere other than home and reachable.
                if dest == home or dest not in self.board.places or self.board._route(home, dest) is None:
                    continue
                force = []
                for member, actor in sorted(self.members[key].items()):
                    p = actor.properties
                    place = self.board.places[home]
                    at_home = ((actor.pos[0] - place["x"]) ** 2 + (actor.pos[2] - place["z"]) ** 2
                               <= float(place.get("radius", 2500)) ** 2)
                    if (p.get("dead") or p.get("away_on_journey") or not appraisal.is_combatant(p)
                            or not at_home
                            or not self.board.hooks.resident_can_leave(str(p.get("id") or p.get("name")))):
                        continue
                    force.append(dict(resident=str(p.get("id") or p.get("name")),
                                      name=p.get("name", member), display=p.get("display_name") or p.get("name", member),
                                      role=("bandit" if entity["faction"] in ("bandits", "cultists", "monsters") else "guard"),
                                      health=p.get("health", 60), max_health=p.get("max_health", 60),
                                      damage=p.get("damage", 10), alive=True, gold=0, head=p.get("head", "")))
                if not force:
                    continue
                cause = dict(entity=key, faction=entity["faction"], home=home, target=intent.target,
                             target_faction=fact.get("actor_faction", ""), event=intent.event_id,
                             reason=intent.reason, fact=copy.deepcopy(fact), holder=key,
                             trail=copy.deepcopy(trail))
                self.orders.append(dict(origin=home, dest=dest, members=force[:3], cause=cause))
                break

    def pending(self):
        if not self.enabled():
            return []
        out = []
        for order in self.orders:
            cause = order["cause"]
            # Revalidate a cached decision without generating a new intent.
            known = knowledge.knows(self.store, cause["holder"], cause["event"])
            trail = knowledge.knows(self.store, cause["holder"], cause["trail"]["e"])
            if (known and known.get("identified", True)
                    and float(known.get("certainty", 0)) >= crime.REPORT_CERTAINTY
                    and known.get("actor") == cause["target"]
                    and trail and trail.get("identified", True)
                    and trail.get("actor") == cause["target"]
                    and float(trail.get("certainty", 0)) >= crime.REPORT_CERTAINTY
                    and (cause["entity"], cause["event"]) not in self.dispatched
                    and any(i["reaction"] == appraisal.FIGHT and i["event"] == cause["event"]
                            for i in self.intents.get(cause["entity"], []))):
                out.append(order)
        return copy.deepcopy(out)

    def departed(self, journey):
        cause = journey.cause
        self.dispatched.add((cause["entity"], cause["event"]))
        self.receipts.append(dict(journey=journey.id, **copy.deepcopy(cause)))
        self.receipts = self.receipts[-80:]
        # Orders are actionable only once. This is an action, not sampling.
        self.orders = [o for o in self.orders if o["cause"]["entity"] != cause["entity"]]
        for m in journey.members:
            actor = self.member(m["resident"])
            if actor is not None:
                self._tell(cause["holder"], identity(actor), cause["fact"])
                self._tell(cause["holder"], identity(actor), cause["trail"])

    def member(self, resident):
        return next((a for group in self.members.values() for a in group.values()
                     if str(a.properties.get("id") or a.properties.get("name")) == resident), None)

    def returned(self, journey):
        """Only living returnees can tell the home faction what they witnessed."""
        if not journey.cause or not self.enabled() or journey.dest != journey.home:
            return
        key = journey.cause["entity"]
        for m in journey.alive():
            actor = self.member(m.get("resident"))
            if actor is not None:
                for fact in self.facts(identity(actor)):
                    self._tell(identity(actor), key, fact)

    def encounter(self, winner, loser, t, where, fallen):
        """Existing board combat enters the same attack/death knowledge pipeline.

        This hook observes a resolved fight; it rolls no dice and causes no
        damage. No survivor means no returning testimony.
        The abstract fight identifies parties, not individual killers: the
        winner's leader represents its party in these coarse death accounts.
        """
        if not self.enabled() or not (winner.cause or loser.cause):
            return
        def proxy(j, m):
            real = self.member(m.get("resident"))
            p = dict(real.properties) if real is not None else dict(name=m["name"])
            p.update(faction=j.faction, dead=not m.get("alive", True))
            if j.cause:
                p.update(_faction_cause=j.provenance(), _journey=j.id)
            return SimpleNamespace(properties=p, pos=[where[0], 0, where[1]])
        survivors = [proxy(j, m) for j in (winner, loser) for m in j.alive()]
        attacker = proxy(winner, winner.leader() or winner.members[0])
        # The outcome proves blows landed; it does not claim who started it.
        victim = proxy(loser, loser.leader() or loser.members[0])
        self.director.emit("attack", actor=attacker, target=victim, pos=victim.pos,
                           observers=survivors, crime=False, journey=winner.id, home=winner.home, at=t)
        for j, m in fallen:
            victim = proxy(j, m)
            self.director.emit("death", actor=attacker, target=victim, pos=victim.pos,
                               observers=survivors, crime=False, journey=j.id, home=j.home, at=t)

    def snapshot(self):
        return copy.deepcopy(dict(version=VERSION, entities=self.entities, ledgers=self.ledgers,
                                  intents=self.intents, orders=self.orders,
                                  dispatched=sorted(self.dispatched), receipts=self.receipts,
                                  last_decision=self.last_decision))

    def persist(self):
        if self.store is not None:
            self.store.set(STORE_KEY, json.dumps(self.snapshot()))

    def restore(self):
        self.reset()
        if self.store is None:
            return False
        try:
            saved = json.loads(self.store.get(STORE_KEY, ""))
            if not isinstance(saved, dict) or saved.get("version") != VERSION:
                return False
            for name in ("entities", "ledgers", "intents"):
                if not isinstance(saved.get(name), dict):
                    return False
            self.entities = copy.deepcopy(saved["entities"])
            self.ledgers = copy.deepcopy(saved["ledgers"])
            self.intents = copy.deepcopy(saved["intents"])
            self.orders = copy.deepcopy(saved.get("orders", []))
            self.dispatched = {(str(k), int(e)) for k, e in saved.get("dispatched", [])}
            self.receipts = copy.deepcopy(saved.get("receipts", []))
            self.last_decision = saved.get("last_decision")
        except (TypeError, ValueError, KeyError):
            self.reset()
            return False
        return True
