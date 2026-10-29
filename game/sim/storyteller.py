"""Drama pacing by sampling existing opportunities, never by authoring events.

A :class:`~.system.SimSystem`: the director ticks it after each simulation pass
and resets, persists and restores it with the world's history. Only the KV key
owned here is writable. Hooks supply read-only world views; consumers ask for
lever values and sampling weights. No engine/Qt dependency. All designer
tuning is in TUNING. Hours and dwell times are game hours.
"""

from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace

from .. import data
from . import appraisal, crime, knowledge
from .director import PLAYER_KEY, actor_key
from .system import SimSystem


DEFAULT_TUNING = {
    "store_key": "storyteller.state",
    "version": 3,
    "prosperity_bandit_bias": 2.0,
    "notoriety_hunter_scale": 0.5,
    "enabled": True,
    "sample_hours": 0.25,
    "event_hours": 2.0,
    "event_limit": 200,
    "reason_cap": 24,
    "observation_cap": 10,
    "receipt_cap": 40,
    "healthy": 0.7,
    "danger_health": 0.35,
    "peak_tension": 0.65,
    "recovered_tension": 0.25,
    "attack_tension": 0.18,
    "death_tension": 1.0,
    "hostile_tension": 0.08,
    "pressure_bounty": 150,
    "pressure_phases": ("pursuit", "search"),
    "town_kinds": ("town", "hamlet", "inn"),
    "threat_tiers": (0, 1),
    "sight_radius": 1800.0,
    "staging_distance": 900.0,
    "vendetta_trip_distance": 6000.0,
    "arrival_window_hours": 2.0,
    "unpaid_writ_hours": 24.0,
    "states": {
        "CALM": {
            "next": "RISING", "min_hours": 3.0, "max_hours": 8.0,
            "reason": "Quiet roads give existing troubles time to develop.",
            "advance_reason": "The player is healthy after a quiet interval; existing pressure or a long lull can build tension.",
            "hold_reason": "Wait for enough quiet time and a healthy player before building pressure.",
            "levers": {
                "kind_weights": {"bandits": 2, "wolves": 1, "greenskins": 1},
                "kind_hours": {}, "population": 26, "hunter_bounty": 150,
                "lair_refill_scale": 1.0, "market_chance": 0.25,
                "destination_bias": 2.0, "vendetta_bias": 1.0,
                "writ_hunter_scale": 0.75,
            },
        },
        "RISING": {
            "next": "PEAK", "min_hours": 2.0, "max_hours": 6.0,
            "reason": "More hostile departures after dark bring existing trouble closer.",
            "advance_reason": "Danger, brewing consequences or a sustained rise have brought the roads to a short crest.",
            "hold_reason": "Give existing trouble time to approach before the crest.",
            "levers": {
                "kind_weights": {"bandits": 6, "wolves": 3, "greenskins": 3},
                "kind_hours": {"bandits": [18, 6], "wolves": [19, 6],
                               "greenskins": [20, 5]},
                "population": 30, "hunter_bounty": 125,
                "lair_refill_scale": 0.85, "market_chance": 0.2,
                "destination_bias": 4.0, "vendetta_bias": 4.0,
                "writ_hunter_scale": 0.75,
            },
        },
        "PEAK": {
            "next": "RESPITE", "min_hours": 0.5, "max_hours": 2.0,
            "reason": "A short crest lets consequences play out before easing the roads.",
            "advance_reason": "Injury, sustained tension or the crest's time limit calls for recovery.",
            "hold_reason": "Let the short crest play out while the player can cope.",
            "levers": {
                "kind_weights": {"bandits": 5, "wolves": 2, "greenskins": 2},
                "kind_hours": {"bandits": [18, 6], "wolves": [19, 6],
                               "greenskins": [20, 5]},
                "population": 30, "hunter_bounty": 125,
                "lair_refill_scale": 0.85, "market_chance": 0.15,
                "destination_bias": 5.0, "vendetta_bias": 6.0,
                "writ_hunter_scale": 0.75,
            },
        },
        "RESPITE": {
            "next": "CALM", "min_hours": 4.0,
            "reason": "Gentler traffic gives the player room to recover.",
            "advance_reason": "The recovery interval has passed and the player is healthy with low tension.",
            "hold_reason": "Keep gentler traffic until the recovery interval passes and health and tension recover.",
            "levers": {
                "kind_weights": {"bandits": 1, "wolves": 0, "greenskins": 0,
                                 "trader": 10, "caravan": 5, "minstrel": 5},
                "kind_hours": {}, "population": 24, "hunter_bounty": 300,
                "lair_refill_scale": 1.5, "market_chance": 0.5,
                "destination_bias": 1.5, "vendetta_bias": 1.0,
                "writ_hunter_scale": 0.75,
            },
        },
    },
}


def load_tuning():
    """Editable content plus mods, with code fallbacks and fixed-size lists."""
    return data._merge(copy.deepcopy(DEFAULT_TUNING),
                       data.load("storyteller", replace_lists=True), replace_lists=True)


TUNING = load_tuning()


class StorytellerHooks:
    """Read-only projections, injected by the session like WorldHooks.

    actors yields living knowledge holders (including parked residents).
    actor_town uses the holder's current town, never the hidden event location.
    Hostile counts must include only threats the player can perceive.
    """

    def actors(self):
        return ()

    def actor_town(self, actor):
        return None

    def player_town(self):
        return None

    def player_health_fraction(self):
        return 1.0

    def hostile_counts_by_tier(self):
        return {}

    def law_pressure(self):
        """{region: {bounty, phase}}, without creating Writs records."""
        return {}

    def player_region(self):
        """(x, z, live radius), or None when the board is unavailable."""
        return None

    def hostile_materialisations(self):
        """(region key, cumulative successful hostile party arrivals)."""
        return None, 0

    def market_traffic(self):
        return {}

    def player_wealth(self):
        return 0.0

    def player_karma(self):
        return 0.0


class Storyteller(SimSystem):
    name = "storyteller"

    def __init__(self, store=None, director=None, hooks=None):
        self.store = store
        self.director = director
        self.hooks = hooks if hooks is not None else StorytellerHooks()
        self.restore()

    def reset(self):
        self.state = "CALM"
        self.entered_at = None
        self.last_sample = None
        self._levers = copy.deepcopy(TUNING["states"][self.state]["levers"])
        self._base_levers = copy.deepcopy(self._levers)
        self._local_weights = dict(self._levers["kind_weights"])
        self._local_hunter_bounty = self._levers["hunter_bounty"]
        self.sensors = {}
        self._threads = {}
        self._discharged = set()
        self._observations = ()
        self._reasons = {}
        self._holder_cache = None
        self._arrival_region = None
        self._arrival_samples = []
        self._pressure_since = None
        self._population_cap = None
        self._writ_since = {}
        self._studio_overrides = {}
        self._enabled_override = None
        self._thread_facts = {}
        self._vendetta_view = {}
        self._receipts = ()
        self._footprint_pricing = dict(bandit_bias=TUNING["prosperity_bandit_bias"],
                                       hunter_scale=TUNING["notoriety_hunter_scale"])
        self._publish_levers()

    @property
    def enabled(self):
        return bool(TUNING["enabled"] and self._enabled_override is not False)

    def set_enabled(self, enabled):
        self._enabled_override = bool(enabled)
        self._reason("Ecology switch", "Storyteller pacing enabled." if self.enabled else
                     "Pristine ecology: storyteller sensors are idle and all overrides and biases are disabled.")
        self.persist()

    def state_levers(self, state):
        """Designer table, including session edits; inspection is read-only."""
        base = self._base_levers if state == self.state else TUNING["states"][state]["levers"]
        return data._merge(copy.deepcopy(base), self._studio_overrides.get(state, {}), replace_lists=True)

    def edit_lever(self, state, path, value, *, persist=True):
        """Studio edits only numeric lever data, never sensors, facts or intents."""
        if state not in TUNING["states"]:
            raise ValueError("Unknown pacing state")
        from ..living.journeys import KINDS
        path = tuple(path)
        if len(path) == 1:
            key = path[0]
            if key not in self._base_levers or key in ("kind_weights", "kind_hours"):
                raise ValueError("Unknown scalar lever")
            lo, hi = ((0, 1) if key == "market_chance" else (0, 10000))
            if key == "destination_bias":
                lo = 0.01  # every legal destination must retain a positive draw
        elif len(path) == 2 and path[0] == "kind_weights" and path[1] in KINDS:
            lo, hi = 0, 10000
        elif len(path) == 3 and path[0] == "kind_hours" and path[1] in KINDS and path[2] in (0, 1):
            lo, hi = 0, 24
        else:
            raise ValueError("Unknown lever cell")
        value = float(value)
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f"Lever must be between {lo} and {hi}")
        if path[0] == "population":
            value = int(round(value))
        overrides = self._studio_overrides.setdefault(state, {})
        if len(path) == 1:
            overrides[path[0]] = value
        elif path[0] == "kind_weights":
            overrides.setdefault("kind_weights", {})[path[1]] = value
        else:
            windows = overrides.setdefault("kind_hours", {})
            hours = list(self.state_levers(state)["kind_hours"].get(path[1], KINDS[path[1]]["hours"]))
            hours[path[2]] = value
            windows[path[1]] = hours
        if state == self.state:
            self._adjust_levers(self.last_sample or 0, self.sensors or {"law": {}})
        self._reason("Studio edit", f"Designer set {state} {' / '.join(map(str, path))} to {value:g}; "
                     "ordinary board and streaming samples use the edited lever.")
        if persist:
            self.persist()

    def reset_edits(self, state):
        self._studio_overrides.pop(state, None)
        if state == self.state:
            self._adjust_levers(self.last_sample or 0, self.sensors or {"law": {}})
        self._reason("Studio edit", f"Designer restored the saved base lever table for {state}.")
        self.persist()

    def board_levers(self):
        """One detached snapshot per board update; pristine mode has no overrides."""
        return self.levers if self.enabled else {}

    @property
    def levers(self):
        """A detached snapshot: consumers cannot mutate authored/restored values."""
        return copy.deepcopy(self._levers)

    @property
    def observations(self):
        """The last accepted samples, newest first, detached for live inspection."""
        return copy.deepcopy(list(reversed(self._observations)))

    def _reason(self, decision, reason):
        # Latest explanation per decision; bounded even with many destinations.
        self._reasons.pop(decision, None)
        self._reasons[decision] = str(reason)
        while len(self._reasons) > TUNING["reason_cap"]:
            oldest = next((key for key in self._reasons if key.startswith("Destination ")),
                          next(iter(self._reasons)))
            del self._reasons[oldest]

    def _publish_levers(self):
        why = TUNING["states"][self.state]["reason"]
        self._reason("Pacing", f"{self.state}: {why}")
        for label, key in (("Journey weights", "kind_weights"),
                           ("Departure hours", "kind_hours"),
                           ("Road population", "population"),
                           ("Hunter bounty threshold", "hunter_bounty"),
                           ("New lair refill delay multiplier", "lair_refill_scale"),
                           ("Market trip chance", "market_chance"),
                           ("Town destination multiplier", "destination_bias"),
                           ("Vendetta arrival multiplier", "vendetta_bias"),
                           ("Old unpaid writ hunter threshold multiplier", "writ_hunter_scale")):
            self._reason(label, f"{self._levers[key]}. {why}")

    def _holders(self):
        holders = {}
        for actor in self.hooks.actors():
            if actor.properties.get("dead"):
                continue
            # actor_key caches on properties. Resolve against a detached view
            # so even a previously uninspected actor remains entirely read-only.
            key = actor_key(SimpleNamespace(properties=dict(actor.properties)))
            if key:
                holders[key] = actor
        return holders

    def _cached_holders(self):
        if self._holder_cache is None:
            self._holder_cache = self._holders()
        return self._holder_cache

    def _vendettas(self, holders):
        """Read cached intentions only; never appraise, dirty or replace them."""
        out = {}
        if self.director is None:
            return out
        for key, actor in holders.items():
            cached = self.director.cached_intents(key)
            if actor.properties.get("dead") or cached is None:
                continue
            known = {f.get("e"): f for f in knowledge.facts(self.store, key)}
            for intent in cached:
                fact = known.get(intent.event_id)
                if (intent.reaction != appraisal.FIGHT or intent.target != PLAYER_KEY
                        or not fact or fact.get("kind") != "death"
                        or fact.get("actor") != PLAYER_KEY
                        or not fact.get("identified", True)
                        or float(fact.get("certainty", 0)) < crime.REPORT_CERTAINTY):
                    continue
                token = (key, intent.event_id)
                if any(ev.actor == key and ev.target == PLAYER_KEY
                       and ev.kind in ("attack", "death") and ev.id > intent.event_id
                       for ev in self.director.bus.recent(limit=TUNING["event_limit"], actor=PLAYER_KEY)):
                    self._discharged.add(token)
                if token in self._discharged:
                    continue
                tie = appraisal.relationship_to(actor.properties, fact.get("target", ""),
                                                 fact.get("target_name", ""))
                if tie in appraisal.KIN_TIES:
                    out[key] = intent
                    break
        return out

    def _sense(self, now):
        self._holder_cache = holders = self._holders()
        bus = self.director.bus if self.director is not None else None
        # unsolved() is an omniscient history query: its ids are only a filter.
        # Never inspect its event locations, offenders or other hidden fields.
        open_ids = {ev.id for ev in crime.unsolved(
            self.store, bus, limit=TUNING["event_limit"])} if bus is not None else set()
        threads, ids, evidence = {}, set(), {}
        for key, actor in holders.items():
            if key == PLAYER_KEY:
                continue
            for fact in knowledge.facts(self.store, key):
                eid = fact.get("e")
                # A remembered crime can outlive the bounded event history.
                # Unknown events must not erase a living holder's loose thread
                # merely by pushing its event out of unsolved()'s history tail.
                reported = eid not in open_ids and crime.already_reported(self.store, eid)
                if (not eid or reported or not crime.is_crime(fact)
                        or fact.get("reported") or crime.settled(self.store, eid)
                        or float(fact.get("certainty", 0)) < knowledge.FORGET_BELOW):
                    continue
                ids.add(eid)
                town = self.hooks.actor_town(actor)
                if town:
                    threads.setdefault(town, set()).add(eid)
                    evidence.setdefault(town, []).append(dict(event=eid, holder=key,
                        holder_name=actor.properties.get("display_name") or actor.properties.get("name") or key,
                        kind=fact.get("kind", "crime")))
        self._threads = {town: len(events) for town, events in threads.items()}
        self._thread_facts = evidence
        health = max(0.0, min(1.0, float(self.hooks.player_health_fraction())))
        attacks = deaths = 0
        if bus is not None:
            for ev in bus.recent(limit=TUNING["event_limit"], actor=PLAYER_KEY):
                # The player necessarily perceives attacks/deaths targeting them.
                if ev.target != PLAYER_KEY or not 0 <= now - (ev.day * 24 + ev.hour) <= TUNING["event_hours"]:
                    continue
                attacks += ev.kind == "attack"
                deaths += ev.kind == "death"
        counts = self.hooks.hostile_counts_by_tier()
        hostiles = sum(counts.get(tier, 0) for tier in TUNING["threat_tiers"])
        law = self.hooks.law_pressure()
        pressure = any(row.get("bounty", 0) >= TUNING["pressure_bounty"]
                       or row.get("phase") in TUNING["pressure_phases"]
                       for row in law.values())
        vendettas = self._vendettas(holders)
        self._vendetta_view = {key: dict(reason=intent.reason, staging="Awaiting an ordinary trip or nearby arrival",
            holder=holders[key].properties.get("display_name") or holders[key].properties.get("name") or key,
            event=intent.event_id) for key, intent in vendettas.items()}
        from ..footprint import evaluate
        footprint = evaluate(((key, knowledge.facts(self.store, key)) for key in holders),
                             threads=len(ids), writs=law, vendettas=len(vendettas),
                             traffic=self.hooks.market_traffic(), wealth=self.hooks.player_wealth(),
                             karma=self.hooks.player_karma())
        tension = min(1.0, 1.0 - health + attacks * TUNING["attack_tension"]
                      + deaths * TUNING["death_tension"] + hostiles * TUNING["hostile_tension"])
        return dict(health=health, attacks=attacks, deaths=deaths, hostiles=hostiles,
                    tension=tension, loose_threads=len(ids), vendettas=len(vendettas),
                    law=law, law_pressure=pressure, footprint=footprint)

    def _outcomes(self, now, sensors):
        region, total = self.hooks.hostile_materialisations()
        if region != self._arrival_region or (self._arrival_samples and total < self._arrival_samples[-1][1]):
            self._arrival_samples = []
            self._pressure_since = now if self.state in ("RISING", "PEAK") else None
            self._population_cap = None
        self._arrival_region = region
        window = TUNING["arrival_window_hours"]
        self._arrival_samples.append((now, int(total)))
        # Retain the sample immediately before the window, including on jumps.
        while len(self._arrival_samples) > 2 and self._arrival_samples[1][0] <= now - window:
            self._arrival_samples.pop(0)
        start, prior = self._arrival_samples[0]
        elapsed = now - start
        count = max(0, int(total) - prior)
        sensors.update(arrival_region=region, hostile_arrivals=count,
                       hostile_arrivals_per_hour=count / elapsed if elapsed else 0.0,
                       arrival_hours=elapsed)
        stalled = (region is not None and self.state in ("RISING", "PEAK")
                   and self._pressure_since is not None
                   and now - self._pressure_since >= window and elapsed >= window and count == 0)
        if stalled and self._population_cap is None:
            self._population_cap = TUNING["states"]["CALM"]["levers"]["population"]
        elif count or self.state not in ("RISING", "PEAK"):
            self._population_cap = None
        sensors["arrival_stalled"] = stalled
        self._reason("Arrival feedback", (
            f"No hostile arrivals reached {region} over {elapsed:.2f} game hours of pressure; "
            f"cap road population at {self._population_cap} and wait for ordinary journeys."
            if stalled else f"{count} hostile arrivals in {elapsed:.2f} game hours in {region}; "
            "no empty pressure window calls for a population cap."))

    def _adjust_levers(self, now, sensors):
        old_writs = {}
        for region, row in sensors["law"].items():
            if row.get("bounty", 0) > 0:
                old_writs[region] = self._writ_since.get(region, now)
        self._writ_since = old_writs
        overdue = [r for r, since in old_writs.items() if now - since >= TUNING["unpaid_writ_hours"]]
        levers = self.state_levers(self.state)
        self._local_weights = dict(levers["kind_weights"])
        self._local_hunter_bounty = levers["hunter_bounty"]
        if self.state == "RESPITE":
            # Relief is a local incoming-journey query. Distant ecology retains
            # authored hostile weights and the ordinary hunter threshold.
            for kind in ("bandits", "wolves", "greenskins"):
                levers["kind_weights"].pop(kind, None)
            levers["hunter_bounty"] = DEFAULT_TUNING["states"]["CALM"]["levers"]["hunter_bounty"]
        if overdue:
            levers["hunter_bounty"] *= levers["writ_hunter_scale"]
            self._local_hunter_bounty *= levers["writ_hunter_scale"]
        notoriety = sensors.get("footprint", {}).get("notoriety", 0)
        self._footprint_pricing = dict(bandit_bias=TUNING["prosperity_bandit_bias"],
                                       hunter_scale=TUNING["notoriety_hunter_scale"])
        scale = 1.0 - self._footprint_pricing["hunter_scale"] * notoriety
        levers["hunter_bounty"] *= scale
        self._local_hunter_bounty *= scale
        self._reason("Player footprint", f"Prosperity {sensors.get('footprint', {}).get('prosperity', 0):.2f}; "
                     f"notoriety {notoriety:.2f} prices hunter threshold x{scale:.2f}. "
                     "Known deeds supply legend; Karma supplies the existing moral axis.")
        self._reason("Writ pressure", f"Hunter threshold {levers['hunter_bounty']:g}: " + (
            f"unpaid writs in {', '.join(overdue)} have persisted for at least "
            f"{TUNING['unpaid_writ_hours']:g} game hours."
            if overdue else "No sampled unpaid writ has yet reached the age threshold."))
        if self._population_cap is not None and self.state in ("RISING", "PEAK"):
            levers["population"] = min(levers["population"], self._population_cap)
        self._levers = levers
        self._publish_levers()

    def tick(self, now):
        """Sample on world time; one transition per sample, including large jumps."""
        if not self.enabled:
            self._reason("Ecology switch", "Pristine ecology: storyteller sensors are idle and all overrides and biases are disabled.")
            return
        now = float(now)
        if self.last_sample is not None and now < self.last_sample:
            return                 # load must call restore(), not advance backwards
        if self.last_sample is not None and now - self.last_sample < TUNING["sample_hours"]:
            return
        self.last_sample = now
        if self.entered_at is None:
            self.entered_at = now
        self.sensors = s = self._sense(now)
        self._outcomes(now, s)
        row = TUNING["states"][self.state]
        age = now - self.entered_at
        danger = s["health"] <= TUNING["danger_health"] or s["tension"] >= TUNING["peak_tension"]
        ready = s["loose_threads"] or s["vendettas"] or s["law_pressure"]
        recovered = s["health"] >= TUNING["healthy"] and s["tension"] <= TUNING["recovered_tension"]
        advance = False
        if self.state == "CALM":
            advance = age >= row["min_hours"] and s["health"] >= TUNING["healthy"] and (
                ready or age >= row["max_hours"])
        elif self.state == "RISING":
            advance = danger or age >= row["max_hours"] or (age >= row["min_hours"] and ready)
        elif self.state == "PEAK":
            advance = s["health"] <= TUNING["danger_health"] or age >= row["max_hours"] or (
                age >= row["min_hours"] and s["tension"] >= TUNING["peak_tension"])
        elif self.state == "RESPITE":
            advance = recovered and age >= row["min_hours"]
        previous = self.state
        if advance:
            self.state = row["next"]
            self.entered_at = now
            self._base_levers = copy.deepcopy(TUNING["states"][self.state]["levers"])
            if self.state == "RISING":
                self._pressure_since = now
                self._population_cap = None
                # Only arrivals during this pressure episode can justify growth.
                self._arrival_samples = [(now, self._arrival_samples[-1][1])]
            elif self.state not in ("RISING", "PEAK"):
                self._pressure_since = None
                self._population_cap = None
        self._adjust_levers(now, s)
        explanation = row["advance_reason"] if advance else row["hold_reason"]
        self._reason("State decision", f"{previous} → {self.state}: {explanation} After {age:.2f} hours: "
                     f"health {s['health']:.0%}, tension {s['tension']:.2f}, "
                     f"{s['attacks']} recent attacks, {s['deaths']} deaths, {s['hostiles']} visible hostiles, "
                     f"{s['loose_threads']} unreported memories, {s['vendettas']} kin vendettas; "
                     f"law pressure {'present' if s['law_pressure'] else 'absent'}; "
                     f"{s['hostile_arrivals_per_hour']:.2f} hostile arrivals per game hour. "
                     + ("Population growth is capped after an empty pressure window." if s["arrival_stalled"] else ""))
        observation = dict(time=now, state=self.state, sensors=copy.deepcopy(s),
                           reason=self._reasons["State decision"])
        # Replace atomically so the UI can read history while the session ticks.
        self._observations = (*self._observations, observation)[-TUNING["observation_cap"]:]
        self.persist()

    def player_town(self):
        """The town the player is standing in, through the read-only hooks."""
        return self.hooks.player_town()

    def destination_weight(self, town):
        if not self.enabled:
            return 1.0
        weight = self._levers["destination_bias"] if town in self._threads else 1.0
        self._reason(f"Destination {town}", f"Weight {weight:g}: "
                     f"{self._threads.get(town, 0)} unreported crimes remembered by people in this town.")
        return weight

    def materialisation_weight(self, actor_keys, distance):
        """Prioritise natural arrivals already near the player, never teleport.

        Revalidate knowledge/intents at the point of sampling so a discharged,
        forgotten or changed intention cannot keep a stale staging bonus.
        """
        if not self.enabled:
            return 1.0
        keys = set(actor_keys)
        vendettas = self._vendettas({key: actor for key, actor in self._cached_holders().items()
                                    if key in keys})
        eligible = next((key for key in actor_keys if key in vendettas), None)
        ready = (eligible and self.hooks.player_town()
                 and self.hooks.player_health_fraction() >= TUNING["healthy"]
                 and distance <= TUNING["staging_distance"])
        weight = self._levers["vendetta_bias"] if ready else 1.0
        why = f"Weight {weight:g}: " + (
            f"{eligible} already intends to fight ({vendettas[eligible].reason}); "
            "the player is healthy in town and this journey is already nearby."
            if ready else "No nearby justified kin fight is ready for a healthy player in town.")
        self._reason("Vendetta staging", why)
        if eligible in self._vendetta_view:
            self._vendetta_view[eligible]["staging"] = why
        return weight

    def bandit_destination_weight(self, distance):
        """Price existing legal bandit destinations by sampled player wealth."""
        if not self.enabled:
            return 1.0
        prosperity = self.sensors.get("footprint", {}).get("prosperity", 0)
        return 1.0 + prosperity * self._footprint_pricing["bandit_bias"] / (1.0 + distance / 6000) ** 2

    def resident_destination(self, resident_id, towns, distance):
        """Select only a legal ordinary market destination, never an intent."""
        if not self.enabled:
            return None
        key = actor_key(resident_id)
        holder = self._cached_holders().get(key)
        vendettas = self._vendettas({key: holder}) if holder is not None else {}
        town = self.hooks.player_town()
        ready = (key in vendettas and town in towns
                 and self.hooks.player_health_fraction() >= TUNING["healthy"]
                 and distance <= TUNING["vendetta_trip_distance"])
        why = (
            f"{key} already intends to fight ({vendettas[key].reason}); weight the ordinary market trip "
            f"toward {town}, where the healthy player is staying."
            if ready else "Keep the authored market destinations: no nearby clean, undischarged kin fight can approach a healthy player in town.")
        self._reason("Vendetta market destination", why)
        if key in self._vendetta_view:
            self._vendetta_view[key].update(staging=why, destination=town if ready else None)
        return town if ready else None

    def journey_weight(self, kind, position, hostile):
        """Local relief samples a computed board position; live actors keep control."""
        if not self.enabled:
            return 1.0
        region = self.hooks.player_region()
        nearby = region is not None and math.hypot(position[0] - region[0], position[1] - region[1]) <= region[2]
        suppressed = self.state == "RESPITE" and hostile and nearby
        # Respite's hostile entries now tune local admission. Zero suppresses;
        # raising a weight in the Studio immediately admits ordinary candidates.
        bounty = max((r.get("bounty", 0) for r in self.sensors.get("law", {}).values()), default=0)
        override = self._local_weights.get(kind, float(bounty >= self._local_hunter_bounty) if kind == "hunters" else 0)
        weight = override if suppressed else 1.0
        self._reason("Local relief", f"Incoming {kind} weight {weight:g}: " + (
            "this hostile journey's computed position is inside the player's live region during respite."
            if suppressed else "this journey is peaceful, distant, or respite is inactive; ordinary ecology applies."))
        return weight

    def record_journey(self, journey, now, *, arrived=False, destination_sampled=False):
        """Retain biased choices and real arrivals, without routine planner churn."""
        if not self.enabled:
            return
        evidence = self._thread_facts.get(journey.dest, []) if destination_sampled else []
        events = sorted({row["event"] for row in evidence})
        bias = self._levers["destination_bias"] if evidence else 1.0
        influenced = bool(evidence) and bias != 1.0
        why = (f"Destination weight {bias:g}: " + "; ".join(
            f"{r.get('holder_name', r['holder'])} ({r['holder']}) remembers {r['kind']} #{r['event']} in {journey.dest}" for r in evidence))
        if not evidence:
            why = "Ordinary authored destination sampling."
        cause = getattr(journey, "cause", None)
        if cause:
            influenced = True
            events = sorted({cause["event"], cause["trail"]["e"]})
            why = (f"{cause['faction']} departed {cause['home']}: {cause['reason']}. "
                   f"Known account #{cause['event']} and trail #{cause['trail']['e']} "
                   f"held by {cause['holder']}; an actor's order.")
        for member in journey.members:
            key = actor_key(member.get("resident", ""))
            staged = self._vendetta_view.get(key, {})
            if destination_sampled and staged.get("destination") == journey.dest:
                influenced = True
                why = staged["staging"]
                events = [staged["event"]]
                break
        if not arrived and not influenced:
            return
        # Remaining legs identify the board's current trip even if streaming
        # rebases its departure time. A resting party has just completed a leg.
        leg = journey.legs + int(arrived and journey.state == "rest")
        if arrived:
            previous = next((r for r in reversed(self._receipts)
                             if r["journey"] == journey.id and r.get("leg") == leg
                             and r["origin"] == journey.origin and r["destination"] == journey.dest), None)
            if previous:
                why, events = previous["reason"], previous["events"]
        lead = journey.leader() or {}
        receipt = dict(time=float(now), journey=journey.id, kind=journey.kind,
                       leg=leg,
                       party=lead.get("display") or lead.get("name") or journey.id,
                       origin=journey.origin, destination=journey.dest, events=events,
                       outcome="Materialised in the live region" if arrived else "Routed journey sampled",
                       state=self.state, reason=why)
        if cause:
            receipt["provenance"] = journey.provenance()
            if not arrived:
                receipt["outcome"] = "Faction order departed"
        self._receipts = (*self._receipts, receipt)[-TUNING["receipt_cap"]:]
        self._reason("Journey outcome", f"{journey.id} {journey.kind} → {journey.dest}: {receipt['outcome']}. {why}")

    def world_view(self):
        """Detached sampled evidence and actual board receipts; no queries/ticks."""
        return copy.deepcopy(dict(threads=[dict(town=town, count=count,
            bias=self._levers["destination_bias"] if self.enabled else 1.0,
            evidence=self._thread_facts.get(town, [])) for town, count in self._threads.items()],
            vendettas=self._vendetta_view, receipts=list(reversed(self._receipts))))

    def inspector_rows(self):
        if not self.enabled:
            return [("Ecology switch", "Pristine ecology: storyteller sensors are idle and all overrides and biases are disabled.")]
        return list(self._reasons.items())

    def persist(self):
        if self.store is not None:
            self.store.set(TUNING["store_key"], json.dumps({
                "version": TUNING["version"], "state": self.state,
                "entered_at": self.entered_at, "last_sample": self.last_sample,
                "levers": self._levers, "sensors": self.sensors,
                "local_weights": self._local_weights, "local_hunter_bounty": self._local_hunter_bounty,
                "base_levers": self._base_levers,
                "threads": self._threads, "reasons": self._reasons,
                "discharged": sorted(self._discharged),
                "observations": self._observations,
                "arrival_region": self._arrival_region, "arrival_samples": self._arrival_samples,
                "pressure_since": self._pressure_since, "population_cap": self._population_cap,
                "writ_since": self._writ_since,
                "studio_overrides": self._studio_overrides, "enabled_override": self._enabled_override,
                "thread_facts": self._thread_facts, "vendetta_view": self._vendetta_view,
                "receipts": self._receipts,
                "footprint_pricing": self._footprint_pricing,
            }))

    def restore(self):
        """Restore the saved lever snapshot exactly, even after designer retuning."""
        self.reset()
        if self.store is None:
            return False
        try:
            data = json.loads(self.store.get(TUNING["store_key"], ""))
            if not isinstance(data, dict) or data.get("version") != TUNING["version"]:
                return False
            if data.get("state") not in TUNING["states"] or not isinstance(data.get("levers"), dict):
                return False
            if set(data["levers"]) != set(self._levers):
                return False
            entered = data.get("entered_at")
            sampled = data.get("last_sample")
            self.entered_at = None if entered is None else float(entered)
            self.last_sample = None if sampled is None else float(sampled)
            self.state = data["state"]
            self._levers = copy.deepcopy(data["levers"])
            self._base_levers = copy.deepcopy(data.get("base_levers", data["levers"]))
            self._local_weights = dict(data.get("local_weights", self._base_levers["kind_weights"]))
            self._local_hunter_bounty = data.get("local_hunter_bounty", self._base_levers["hunter_bounty"])
            self.sensors = dict(data.get("sensors") or {})
            self._threads = dict(data.get("threads") or {})
            self._reasons = dict(data.get("reasons") or {})
            self._discharged = {(str(key), int(eid)) for key, eid in data.get("discharged", [])}
            self._observations = tuple(copy.deepcopy(data.get("observations") or [])[-TUNING["observation_cap"]:])
            self._arrival_region = data.get("arrival_region")
            self._arrival_samples = [(float(t), int(n)) for t, n in data.get("arrival_samples", [])]
            self._pressure_since = data.get("pressure_since")
            self._population_cap = data.get("population_cap")
            self._writ_since = dict(data.get("writ_since") or {})
            self._studio_overrides = copy.deepcopy(data.get("studio_overrides") or {})
            self._enabled_override = data.get("enabled_override")
            self._thread_facts = copy.deepcopy(data.get("thread_facts") or {})
            self._vendetta_view = copy.deepcopy(data.get("vendetta_view") or {})
            self._receipts = tuple(copy.deepcopy(data.get("receipts") or [])[-TUNING["receipt_cap"]:])
            self._footprint_pricing = dict(data.get("footprint_pricing") or self._footprint_pricing)
        except (TypeError, ValueError):
            self.reset()
            return False
        return True
