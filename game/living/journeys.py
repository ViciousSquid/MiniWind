"""
The world off-screen: journeys, encounters and news, simulated as data.

Big World keeps only the region round the player resident and simulated;
everything beyond it is parked, and a parked actor does not move. So a
traveller who must walk from Ashby to Kettlewick cannot be an actor the whole
way. Here they are *a journey*: who is travelling, why, along which road, since
when and how fast. Where they are is a function of the clock --
:meth:`Journey.position_at` -- so a journey costs nothing at all between the
moments something asks about it. That is the Radiant-AI trick: the world is
not simulated far away, it is *computed* when it matters.

What happens to journeys, in game time:

* **Departures.** The :class:`JourneyBoard` keeps a living population of
  parties on the roads -- traders, caravans with hired swords, pilgrims to
  the shrines, bands of adventurers bound for the barrows, the watch riding
  between towns, couriers, minstrels, brigands moving between hideouts,
  wolf packs and greenskin raiders out after dark, and, once word of a
  bounty has spread, hunters who come looking for the player. Townsfolk with
  a trade (a merchant, a farmer) make market trips to the next town and come
  home again.
* **Encounters on the road.** When two hostile parties pass on the road while
  neither is near the player, the meeting is resolved with dice weighted by
  strength: a caravan beats off brigands or is robbed, a pilgrim is cut down,
  the watch catches a gang. The dead leave remains; the living carry the news.
* **Arrivals.** Adventurers who reach a lair fight it (the world clears the
  creatures there, or the party never comes back); raiders take livestock;
  traders sell and move on; hunters ask after the player and follow the
  trail.
* **News** is made by all of the above (and by the player: a bounty, a
  notable kill), starts at a place, and spreads only as fast as travellers
  carry it. Anyone met on the road can tell what they have heard.

When a journey comes within the region Big World simulates, the session turns
it into real actors (:mod:`game.living.world`) and the engine's AI takes over;
when it leaves again its progress is written back here. This module itself is
pure Python -- it never touches the scene; the session answers its questions
through the small :class:`WorldHooks` interface.
"""

from __future__ import annotations

import json
import math
import random
from typing import Dict, Iterable, List, Optional, Tuple

from . import roads

# ---------------------------------------------------------------------------
# Party kinds
# ---------------------------------------------------------------------------
#: Place kinds (from what a location marker's site is) a journey can head for.
TOWNS = ("town", "hamlet", "inn")
HOMES = ("town", "hamlet", "farm", "inn")
DANGER = ("danger",)
SHRINES = ("shrine",)
CAMPS = ("camp", "danger")

#: Each kind of party: who is in it, where it goes, when it travels.
#:
#: ``members``  list of (role, count range) -- the first is the leader
#: ``faction``  whose side they are on (game/data/factions.json)
#: ``origins``/``dests`` the place kinds they set out from / head for
#: ``legs``     how many trips before they are done (and replaced)
#: ``hours``    the game hours they will set out in
#: ``weight``   how often the board picks this kind
#: ``speed``    pace relative to an ordinary walker
#: ``hostile``  attacks the player on sight
KINDS: Dict[str, Dict] = {
    "trader": dict(members=[("merchant", (1, 1)), ("mercenary", (0, 1))],
                   faction="villagers", origins=HOMES, dests=TOWNS, legs=(2, 4),
                   hours=(6, 16), weight=6, speed=0.9),
    "caravan": dict(members=[("merchant", (1, 1)), ("merchant", (0, 1)),
                             ("mercenary", (2, 3))],
                    faction="villagers", origins=TOWNS, dests=TOWNS, legs=(2, 3),
                    hours=(6, 12), weight=3, speed=0.8),
    "pilgrims": dict(members=[("pilgrim", (1, 3))], faction="villagers",
                     origins=HOMES, dests=SHRINES, legs=(2, 2), hours=(5, 14),
                     weight=3, speed=0.85),
    "adventurers": dict(members=[("adventurer", (2, 4))], faction="adventurers",
                        origins=TOWNS, dests=DANGER, legs=(2, 2), hours=(6, 15),
                        weight=4, speed=1.0),
    "patrol": dict(members=[("guard", (2, 3))], faction="guards", origins=TOWNS,
                   dests=TOWNS, legs=(2, 4), hours=(0, 24), weight=3, speed=1.0),
    "courier": dict(members=[("courier", (1, 1))], faction="villagers",
                    origins=TOWNS, dests=TOWNS, legs=(3, 5), hours=(5, 20),
                    weight=3, speed=1.35),
    "minstrel": dict(members=[("minstrel", (1, 1))], faction="villagers",
                     origins=TOWNS, dests=TOWNS, legs=(2, 4), hours=(8, 17),
                     weight=1, speed=0.85),
    "bandits": dict(members=[("bandit_chief", (1, 1)), ("bandit", (2, 3)),
                             ("bandit_archer", (0, 2))],
                    faction="bandits", origins=CAMPS, dests=CAMPS, legs=(2, 3),
                    hours=(17, 24), weight=3, speed=1.0, hostile=True),
    "wolves": dict(members=[("wolf", (3, 5))], faction="wildlife", origins=DANGER,
                   dests=("farm", "hamlet"), legs=(2, 2), hours=(20, 24),
                   weight=1, speed=1.15, hostile=True, raid=True, beasts=True),
    "greenskins": dict(members=[("greenskin", (3, 5))], faction="monsters",
                       origins=DANGER, dests=("farm", "hamlet"), legs=(2, 2),
                       hours=(21, 24), weight=1, speed=1.0, hostile=True, raid=True),
    "hunters": dict(members=[("bounty_hunter", (2, 3))], faction="mercenaries",
                    origins=TOWNS, dests=TOWNS, legs=(6, 8), hours=(0, 24),
                    weight=0, speed=1.1, hunts_player=True),
    "market": dict(members=[], faction="villagers", origins=HOMES, dests=TOWNS,
                   legs=(2, 2), hours=(7, 10), weight=0, speed=0.9),
    "faction_raid": dict(members=[], faction="", origins=HOMES + CAMPS,
                         dests=HOMES + CAMPS, legs=(2, 2), hours=(0, 24), weight=0, speed=1.0),
}

#: Roles that fight (everyone else runs).
FIGHTERS = frozenset({"mercenary", "adventurer", "guard", "bandit_chief", "bandit",
                      "bandit_archer", "wolf", "greenskin", "bounty_hunter"})
#: (health, damage, attack style) by role, for the abstract fights and for the
#: actors a journey becomes.
ROLE_STATS = {
    "merchant": (55, 5, "melee"), "mercenary": (95, 14, "melee"),
    "pilgrim": (50, 4, "melee"), "adventurer": (100, 16, "melee"),
    "guard": (110, 15, "melee"), "courier": (55, 5, "melee"),
    "minstrel": (45, 4, "melee"), "bandit_chief": (130, 20, "melee"),
    "bandit": (85, 13, "melee"), "bandit_archer": (70, 12, "bow"),
    "wolf": (45, 9, "melee"), "greenskin": (75, 12, "melee"),
    "bounty_hunter": (120, 18, "melee"),
}

#: Names for the people of the roads.
FIRST = ("Hal", "Aldo", "Bryce", "Corin", "Dagny", "Edda", "Fenn", "Garret", "Hester",
         "Ingram", "Jessa", "Kael", "Lorne", "Mabel", "Nils", "Orla", "Perrin", "Quinn",
         "Rook", "Sorrel", "Tam", "Ulla", "Vance", "Wren", "Yorick", "Zelda", "Ansel",
         "Brigid", "Cael", "Della", "Emrys", "Fiona", "Gil", "Hamish", "Ida", "Jory",
         "Keir", "Lark", "Morwen", "Ned", "Olwen", "Pip", "Rhosyn", "Silas", "Tilda")
EPITHET = {
    "bandit_chief": ("Black", "Red", "One-Eye", "the Knife", "Grinning", "Mad"),
    "bounty_hunter": ("Iron", "the Hound", "Grim", "Cold", "the Tracker"),
    "adventurer": ("the Bold", "Swift", "the Lucky", "Stout", "the Young"),
    "minstrel": ("the Fair", "Silvertongue", "the Wanderer"),
}

#: Abstract encounters: how near on the road two parties must pass.
ENCOUNTER_RADIUS = 700.0
#: Abstract world pace: an ordinary walker covers this many world units per
#: real second (game.runtime.NPC_WALK_SPEED), converted to per game hour by
#: the clock's rate when the board is made.
WALK_SPEED = 90.0
#: How long a party lingers at its destination before the next leg, hours.
REST_HOURS = (2.0, 7.0)
#: A faction force that reaches the place its order named holds it at least
#: this long (game hours): a hostile presence, not a rest stop.
PRESENCE_HOURS = 6.0
#: Faction kinds whose forces take livestock while they hold a place, as
#: raiders do; others only ask after their quarry.
RAIDING_FACTIONS = ("bandits", "cultists", "monsters")
#: News is forgotten after this many game hours.
NEWS_HOURS = 24.0 * 6
NEWS_CAP = 80
#: Most remains kept on record.
REMAINS_CAP = 40


class WorldHooks:
    """What the board asks of the world. The session implements these; the
    defaults make a quiet world (tests override what they need)."""

    def site_strength(self, place_key: str) -> float:
        """How much fight is left in a lair (0 when cleared)."""
        return 0.0

    def clear_site(self, place_key: str, fraction: float) -> int:
        """Kill *fraction* of the creatures at a lair; returns how many."""
        return 0

    def raid_place(self, place_key: str, strength: float) -> int:
        """Raiders reach a farm: kill some livestock; returns how many."""
        return 0

    def player_bounty(self) -> int:
        return 0

    def player_place(self) -> Optional[str]:
        """The place nearest the player (where hunters ask after them)."""
        return None

    def player_name(self) -> str:
        return "the stranger"

    def resident_can_leave(self, resident_id: str) -> bool:
        return False

    def resident_left(self, resident_id: str, journey) -> None:
        pass

    def resident_home(self, resident_id: str, journey, alive: bool) -> None:
        pass

    def resident_arrived(self, journey, t: float) -> bool:
        """An authored supply errand may own its stop and return leg."""
        return False

    def resident_waited(self, journey, t: float) -> bool:
        return False

    def robbed_cargo(self, loser, winner) -> None:
        pass

    def journey_levers(self) -> Dict:
        """Optional session pacing values; defaults preserve the authored board."""
        return {}

    def destination_weight(self, place_key: str) -> float:
        return 1.0

    def materialisation_weight(self, actor_keys, distance: float) -> float:
        return 1.0

    def resident_destination(self, resident_id, towns, origin):
        return None

    def journey_weight(self, kind, position, hostile):
        return 1.0

    def journey_sampled(self, journey, t, *, arrived=False, destination_sampled=False):
        pass

    def bandit_destination_weight(self, place_key):
        return 1.0

    def faction_orders(self):
        """Read already decided actor orders. This query cannot appraise actors."""
        return ()

    def faction_departed(self, journey):
        pass

    def faction_returned(self, journey):
        pass

    def faction_present(self, journey, t):
        """A faction force has reached the place its order named and holds it."""
        pass

    def encounter_resolved(self, winner, loser, t, where, fallen):
        pass


# ---------------------------------------------------------------------------
# A journey
# ---------------------------------------------------------------------------
class Journey:
    """One party on the road (or resting between legs)."""

    def __init__(self, jid: str, kind: str, members: List[Dict], origin: str,
                 dest: str, route, depart_t: float, speed: float, legs: int,
                 home: str):
        self.id = jid
        self.kind = kind
        self.members = members
        self.origin = origin
        self.dest = dest
        self.route = [tuple(p) for p in route]
        self.cum = roads.cumulative(self.route)
        self.depart_t = float(depart_t)
        self.speed = float(speed)             # world units per game hour
        self.legs = int(legs)
        self.home = home
        self.state = "travel"                 # travel | rest | done
        self.rest_until = 0.0
        self.news: List[str] = []             # news ids carried
        self.live = False                     # turned into actors near the player
        self.resident = ""                    # id of a townsperson making a trip
        self.quest = None                     # radiant quest offered, if any
        self.fought: List[str] = []           # journeys already met on this leg
        self.cause = None                    # faction action's knowledge receipt

    # -- where -----------------------------------------------------------
    @property
    def length(self) -> float:
        return self.cum[-1] if self.cum else 0.0

    def progress_at(self, t: float) -> float:
        if self.state != "travel":
            return self.length
        return max(0.0, min(self.length, (float(t) - self.depart_t) * self.speed))

    def position_at(self, t: float) -> Tuple[float, float]:
        x, z, _seg = roads.point_at(self.route, self.cum, self.progress_at(t))
        return (x, z)

    def arrives_at(self) -> float:
        return self.depart_t + (self.length / self.speed if self.speed > 0 else 0.0)

    def set_progress(self, s: float, t: float) -> None:
        """Re-base the journey so that at time *t* it is *s* along the road
        (used when actors that walked part of it hand it back)."""
        if self.speed > 0:
            self.depart_t = float(t) - max(0.0, min(self.length, s)) / self.speed

    # -- who -------------------------------------------------------------
    def alive(self) -> List[Dict]:
        return [m for m in self.members if m.get("alive", True)]

    def leader(self) -> Optional[Dict]:
        alive = self.alive()
        return alive[0] if alive else None

    def strength(self) -> float:
        total = 0.0
        for m in self.alive():
            hp = float(m.get("health", 50))
            dmg = float(m.get("damage", 5))
            weight = 1.0 if m.get("role") in FIGHTERS else 0.15
            total += hp * dmg * weight
        return total

    @property
    def faction(self) -> str:
        if self.cause:
            return self.cause["faction"]
        return KINDS.get(self.kind, {}).get("faction", "villagers")

    @property
    def hostile(self) -> bool:
        if self.cause:
            return self.cause["target"] == "player"
        return bool(KINDS.get(self.kind, {}).get("hostile"))

    def provenance(self):
        """A road party always has a faction, home, purpose and receipts."""
        import copy
        return copy.deepcopy(self.cause) if self.cause else dict(
            faction=self.faction, home=self.home, reason=f"Authored {self.kind} journey",
            news=list(self.news))

    def describe(self) -> str:
        lead = self.leader()
        who = lead["display"] if lead else "a party"
        return f"{who} ({self.kind})"

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> Dict:
        result = {"id": self.id, "kind": self.kind, "members": self.members,
                "origin": self.origin, "dest": self.dest, "route": self.route,
                "depart_t": self.depart_t, "speed": self.speed, "legs": self.legs,
                "home": self.home, "state": self.state, "rest_until": self.rest_until,
                "news": list(self.news), "resident": self.resident,
                "quest": self.quest, "fought": list(self.fought)}
        if self.cause is not None:
            result["cause"] = self.cause
        return result

    @classmethod
    def from_dict(cls, d: Dict) -> "Journey":
        j = cls(d["id"], d["kind"], list(d.get("members", [])), d.get("origin", ""),
                d.get("dest", ""), d.get("route", []), d.get("depart_t", 0.0),
                d.get("speed", 1.0), d.get("legs", 1), d.get("home", ""))
        j.state = d.get("state", "travel")
        j.rest_until = float(d.get("rest_until", 0.0))
        j.news = list(d.get("news", []))
        j.resident = d.get("resident", "") or ""
        j.quest = d.get("quest")
        j.fought = list(d.get("fought", []))
        j.cause = d.get("cause")
        return j


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------
class JourneyBoard:
    """Every journey in the world, the news, and the dead left by the road."""

    def __init__(self, network: roads.RoadNetwork, places: Dict[str, Dict],
                 hours_per_second: float, rng=None, hooks: WorldHooks = None,
                 population: int = 26):
        self.network = network
        #: place key -> {"name", "x", "z", "kind"}
        self.places = places
        self.rng = rng or random.Random()
        self.hooks = hooks or WorldHooks()
        self.population = int(population)
        #: An ordinary walker's pace, in world units per game hour.
        self.walk_per_hour = WALK_SPEED / max(1e-6, float(hours_per_second))
        self.journeys: Dict[str, Journey] = {}
        self.news: Dict[str, Dict] = {}
        #: place key -> news ids heard there
        self.heard: Dict[str, List[str]] = {}
        self.remains: List[Dict] = []
        self.next_id = 1
        self.last_t: Optional[float] = None
        self.bounty_news = ""                 # the news id about the player's bounty
        self.bounty_seen = 0
        self.residents_on_trips: Dict[str, str] = {}   # resident id -> journey id
        self.resident_pool: List[Dict] = []   # {"id", "home", "role"} eligible to travel
        self._names_used = set()
        self._update_levers = None
        # Streamer-owned telemetry, read by the storyteller without events.
        self.hostile_materialisations = {}

    # -- places --------------------------------------------------------------
    def _lever(self, name, default):
        levers = self._update_levers
        return (self.hooks.journey_levers() if levers is None else levers).get(name, default)

    def _hours(self, kind):
        return self._lever("kind_hours", {}).get(kind, KINDS[kind]["hours"])

    @staticmethod
    def _in_hours(hour, hours):
        lo, hi = hours
        return lo <= hour < hi if lo <= hi else hour >= lo or hour < hi

    def places_of(self, kinds: Iterable[str]) -> List[str]:
        kinds = tuple(kinds)
        return [k for k, p in self.places.items()
                if p.get("kind") in kinds and k in self.network.place_node]

    def place_name(self, key: str) -> str:
        return self.places.get(key, {}).get("name", key or "somewhere")

    def nearest_place(self, x: float, z: float, kinds=None) -> Optional[str]:
        best, best_d = None, math.inf
        for k, p in self.places.items():
            if kinds and p.get("kind") not in kinds:
                continue
            d = math.hypot(p["x"] - x, p["z"] - z)
            if d < best_d:
                best, best_d = k, d
        return best

    # -- names ---------------------------------------------------------------
    def _new_name(self, role: str) -> Tuple[str, str]:
        rng = self.rng
        for _ in range(40):
            first = rng.choice(FIRST)
            ep = EPITHET.get(role)
            display = f"{first} {rng.choice(ep)}" if ep and rng.random() < 0.8 else first
            if display not in self._names_used:
                break
        self._names_used.add(display)
        title = {"merchant": "the Trader", "mercenary": "the Sellsword",
                 "pilgrim": "the Pilgrim", "courier": "the Courier",
                 "guard": "of the Watch", "bandit": "the Brigand",
                 "bandit_archer": "the Brigand", "greenskin": "", "wolf": ""}.get(role)
        if role in ("wolf",):
            display = "Wolf"
        elif role == "greenskin":
            display = "Greenskin Raider"
        elif title and " " not in display:
            display = f"{display} {title}"
        slug = "".join(c.lower() if c.isalnum() else "_" for c in display).strip("_")
        return f"road_{slug}_{self.next_id}", display

    def _member(self, role: str) -> Dict:
        hp, dmg, style = ROLE_STATS.get(role, (60, 6, "melee"))
        name, display = self._new_name(role)
        return {"role": role, "name": name, "display": display, "health": hp,
                "max_health": hp, "damage": dmg, "style": style, "alive": True,
                "gold": self.rng.randint(5, 40) if role not in ("wolf", "greenskin") else 0,
                "head": ""}

    # -- making journeys -----------------------------------------------------
    def _route(self, a: str, b: str):
        route = self.network.route(a, b)
        if not route or len(route) < 2:
            return None
        return route

    def plan(self, kind: str, t: float, origin: str = None, dest: str = None,
             members: List[Dict] = None, depart_t: float = None) -> Optional[Journey]:
        """Start a journey of *kind* (picking its places if not given)."""
        spec = KINDS[kind]
        rng = self.rng
        destination_sampled = dest is None
        origins = [origin] if origin else self.places_of(spec["origins"])
        if not origins:
            return None
        origin = origin or rng.choice(origins)
        if dest is None:
            dests = [d for d in self.places_of(spec["dests"]) if d != origin]
            if not dests:
                return None
            ox, oz = self.places[origin]["x"], self.places[origin]["z"]
            # Nearer places are likelier: most trips are to the next town over.
            weights = [1.0 / (1.0 + math.hypot(self.places[d]["x"] - ox,
                                               self.places[d]["z"] - oz) / 6000.0) ** 2
                       for d in dests]
            weights = [w * self.hooks.destination_weight(d) for d, w in zip(dests, weights)]
            if kind == "bandits":
                weights = [w * self.hooks.bandit_destination_weight(d) for d, w in zip(dests, weights)]
            dest = rng.choices(dests, weights=weights)[0]
        route = self._route(origin, dest)
        if route is None:
            return None
        if members is None:
            members = []
            for role, (lo, hi) in spec["members"]:
                for _ in range(rng.randint(lo, hi)):
                    members.append(self._member(role))
        if not members:
            return None
        jid = f"j{self.next_id}"
        self.next_id += 1
        speed = self.walk_per_hour * float(spec.get("speed", 1.0))
        j = Journey(jid, kind, members, origin, dest, route,
                    t if depart_t is None else depart_t, speed,
                    rng.randint(*spec["legs"]), origin)
        # Whatever is being said where they set out, they set out knowing.
        j.news = list(self.heard.get(origin, []))[-8:]
        self.journeys[jid] = j
        if kind not in ("market", "faction_raid"):  # metadata is attached just after plan()
            self.hooks.journey_sampled(j, t, destination_sampled=destination_sampled)
        return j

    def _pick_kind(self, hour=None) -> Optional[str]:
        overrides = self._lever("kind_weights", {})
        kinds = [k for k, s in KINDS.items()
                 if overrides.get(k, s.get("weight", 0)) > 0
                 and (hour is None or self._in_hours(hour, self._hours(k)))]
        if not kinds:
            return None
        weights = [overrides.get(k, KINDS[k]["weight"]) for k in kinds]
        return self.rng.choices(kinds, weights=weights)[0]

    def seed(self, t: float) -> None:
        """A world that has been going for a while: a full population, caught
        part-way along their roads."""
        self._update_levers = self.hooks.journey_levers()
        try:
            self._seed(t)
        finally:
            self._update_levers = None

    def _seed(self, t):
        population = int(self._lever("population", self.population))
        for _ in range(population * 3):
            if len(self.journeys) >= population:
                break
            kind = self._pick_kind(t % 24.0)
            if kind is None:
                break
            j = self.plan(kind, t)
            if j is not None and j.speed > 0 and j.length > 0:
                j.depart_t = t - self.rng.uniform(0.0, j.length / j.speed)

    # -- the clock ------------------------------------------------------------
    def update(self, t: float) -> List[str]:
        """Advance the off-screen world to absolute game hour *t*. Returns the
        news ids made this update (for the session to surface, if it likes)."""
        self._update_levers = self.hooks.journey_levers()
        try:
            return self._update(t)
        finally:
            self._update_levers = None

    def _update(self, t):
        made: List[str] = []
        last = self.last_t if self.last_t is not None else t
        self.last_t = t
        if t < last:
            return made                     # time went backwards (a load): skip
        self._watch_bounty(t, made)
        for j in list(self.journeys.values()):
            if not j.alive() and not j.live:
                j.state = "done"
            if j.state == "done":
                self._retire(j)
                continue
            if j.live:
                continue                    # actors are walking it; they report back
            if j.state == "travel" and t >= j.arrives_at():
                self.arrive(j, t, made)
            elif j.state == "rest" and t >= j.rest_until:
                self.next_leg(j, t)
        self._encounters(t, made)
        self._departures(t)
        self._resident_trips(t)
        self._faction_departures(t)
        self._forget(t)
        return made

    def _departures(self, t: float) -> None:
        hour = t % 24.0
        active = sum(1 for j in self.journeys.values() if j.kind not in ("market",))
        tries = 0
        while active < int(self._lever("population", self.population)) and tries < 6:
            tries += 1
            kind = self._pick_kind(hour)
            if kind is None:
                break
            if self.plan(kind, t) is not None:
                active += 1
        # Hunters, when there is a price on the player's head worth the walk.
        if (self.bounty_news and self.hooks.player_bounty() >= self._lever("hunter_bounty", HUNTER_BOUNTY)
                and not any(j.kind == "hunters" for j in self.journeys.values())):
            target = self.hooks.player_place()
            towns = [p for p in self.places_of(TOWNS) if p != target]
            if target and towns and self.bounty_news in self._heard_anywhere():
                origin = self.rng.choice(towns)
                j = self.plan("hunters", t, origin=origin, dest=target)
                if j is not None:
                    j.news.append(self.bounty_news)

    def _heard_anywhere(self):
        out = set()
        for ids in self.heard.values():
            out.update(ids)
        return out

    # -- arrival and onward -------------------------------------------------
    def _faction_departures(self, t):
        """Commit legal orders from faction actors through the ordinary board."""
        for order in self.hooks.faction_orders():
            cause = order.get("cause") or {}
            home, dest = order.get("origin"), order.get("dest")
            members = order.get("members") or []
            if (home not in self.places or dest not in self.places or home == dest
                    or not cause.get("event") or cause.get("home") != home
                    or not cause.get("faction") or not cause.get("holder")
                    or not cause.get("fact") or not members
                    or any(j.cause and j.cause["entity"] == cause["entity"] for j in self.journeys.values())
                    or any(not m.get("resident") or m["resident"] in self.residents_on_trips
                           or not self.hooks.resident_can_leave(m["resident"]) for m in members)
                    or self._route(home, dest) is None):
                continue
            j = self.plan("faction_raid", t, origin=home, dest=dest, members=members)
            if j is None:
                continue
            j.cause = cause
            self.hooks.faction_departed(j)
            for m in members:
                self.residents_on_trips[m["resident"]] = j.id
                self.hooks.resident_left(m["resident"], j)
            self.hooks.journey_sampled(j, t)

    def arrive(self, j: Journey, t: float, made: List[str]) -> None:
        """*j* has reached its destination."""
        place = j.dest
        name = self.place_name(place)
        lead = j.leader()
        spec = KINDS.get(j.kind, {})
        # Tell what they carry; learn what is said here.
        heard = self.heard.setdefault(place, [])
        for nid in j.news:
            if nid in self.news and nid not in heard:
                heard.append(nid)
        for nid in heard[-10:]:
            if nid not in j.news:
                j.news.append(nid)
        if self.hooks.resident_arrived(j, t):
            return
        if j.kind == "adventurers" and place in self.places_of(DANGER):
            self._delve(j, place, t, made)
        elif spec.get("raid"):
            n = self.hooks.raid_place(place, j.strength())
            if n:
                what = "Wolves" if j.kind == "wolves" else "Greenskin raiders"
                made.append(self.say(f"{what} fell on {name} in the night and "
                                     f"carried off {n} head of livestock.", t, place,
                                     "raid"))
        elif j.kind == "hunters":
            target = self.hooks.player_place()
            if target and target != place and self.hooks.player_bounty() > 0:
                # The trail leads on: they follow it.
                route = self._route(place, target)
                if route is not None:
                    j.origin, j.dest, j.route = place, target, route
                    j.cum = roads.cumulative(route)
                    j.depart_t = t + 0.5
                    j.fought = []
                    return
        elif j.kind in ("trader", "caravan") and lead is not None:
            for m in j.alive():
                if m["role"] == "merchant":
                    m["gold"] = int(m.get("gold", 0)) + self.rng.randint(10, 60)
        j.legs -= 1
        if j.legs <= 0 and j.dest == j.home:
            j.state = "done"
            return
        j.state = "rest"
        j.rest_until = t + self.rng.uniform(*REST_HOURS)
        if j.cause and j.dest != j.home:
            # The same draw as any rest; a force holds the place for longer.
            j.rest_until = max(j.rest_until, t + PRESENCE_HOURS)
            self._hold(j, t, made)
        j.route = [j.route[-1]] if j.route else []
        j.cum = roads.cumulative(j.route)

    def _hold(self, j: Journey, t: float, made: List[str]) -> None:
        """A faction force arrives where its order sent it and holds the place.

        Everything here is an existing mechanism applied to a party that is
        really there: news of it, heard first in that place; livestock taken
        through the same hook wolves and greenskins use, for raiding factions;
        for raiding factions off screen; and the faction spine's account of
        who saw them and what the locals told them (``faction_present``). Nobody is attacked by fiat: fights
        still need the parties to meet (:meth:`_encounters` includes a holding
        force) or live opponents in sight."""
        place = j.dest
        name = self.place_name(place)
        home = self.place_name(j.home)
        fact = j.cause.get("fact") or {}
        quarry = (self.hooks.player_name() if j.cause.get("target") == "player"
                  else fact.get("actor_name") or "someone")
        who = j.cause.get("faction", "a faction").title()
        taken = 0
        if j.cause.get("faction") in RAIDING_FACTIONS and not j.live:
            # Off screen only: a live force has to be seen doing it.
            taken = self.hooks.raid_place(place, j.strength())
        text = f"{who} out of {home} are holding {name}, asking after {quarry}"
        text += (f", and have carried off {taken} head of livestock." if taken else ".")
        nid = self.say(text, t, place, "presence", "player" if j.cause.get("target") == "player" else "")
        made.append(nid)
        if nid not in j.news:
            j.news.append(nid)
        self.hooks.faction_present(j, t)

    def holding(self, place: str) -> List[Journey]:
        """Faction forces holding *place* now (resting where their order sent them)."""
        return [j for j in self.journeys.values()
                if j.cause and j.state == "rest" and j.dest == place
                and j.dest != j.home and j.alive()]

    def next_leg(self, j: Journey, t: float) -> None:
        """Rest is over: set out again -- home if this was the last leg."""
        if self.hooks.resident_waited(j, t):
            return
        here = j.dest
        destination_sampled = False
        if j.legs <= 0:
            dest = j.home
        elif j.kind in ("market", "faction_raid"):
            dest = j.home
        else:
            spec = KINDS.get(j.kind, {})
            options = [d for d in self.places_of(spec.get("dests", TOWNS)) if d != here]
            if j.legs == 1 and j.home != here:
                dest = j.home
            elif options:
                hx, hz = self.places[here]["x"], self.places[here]["z"]
                options.sort(key=lambda d: math.hypot(self.places[d]["x"] - hx,
                                                      self.places[d]["z"] - hz))
                nearby = options[:4]
                destination_sampled = True
                dest = self.rng.choices(nearby, weights=[self.hooks.destination_weight(d)
                                                       * (self.hooks.bandit_destination_weight(d) if j.kind == "bandits" else 1.0)
                                                       for d in nearby])[0]
            else:
                dest = j.home
        if dest == here:
            j.state = "done"
            return
        route = self._route(here, dest)
        if route is None:
            j.state = "done"
            return
        j.origin, j.dest = here, dest
        j.route = route
        j.cum = roads.cumulative(route)
        j.depart_t = t
        j.state = "travel"
        j.fought = []
        self.hooks.journey_sampled(j, t, destination_sampled=destination_sampled)

    def _delve(self, j: Journey, place: str, t: float, made: List[str]) -> None:
        """Adventurers at a lair: they clear it, or they do not come back."""
        name = self.place_name(place)
        lead = j.leader()
        site = self.hooks.site_strength(place)
        if site <= 0:
            made.append(self.say(f"{lead['display'] if lead else 'Adventurers'} went to "
                                 f"{name} and found it already picked clean.", t, place,
                                 "delve"))
            return
        ours = j.strength()
        p_win = ours / (ours + site) if ours + site > 0 else 0.5
        if self.rng.random() < p_win:
            killed = self.hooks.clear_site(place, self.rng.uniform(0.6, 1.0))
            for m in j.alive():
                m["health"] = max(1, int(m["health"] * self.rng.uniform(0.4, 0.9)))
                m["gold"] = int(m.get("gold", 0)) + self.rng.randint(20, 120)
            if self.rng.random() < 0.35 and len(j.alive()) > 1:
                self._kill(j.alive()[-1], j, t, place)
            made.append(self.say(
                f"A company led by {lead['display'] if lead else 'adventurers'} cleared "
                f"{name}" + (f", leaving {killed} of the things there dead" if killed else "")
                + ".", t, place, "delve"))
        else:
            self.hooks.clear_site(place, self.rng.uniform(0.0, 0.25))
            for m in j.alive():
                self._kill(m, j, t, place)
            j.state = "done"
            made.append(self.say(
                f"{lead['display'] if lead else 'A company of adventurers'} and their "
                f"company went into {name} and never came out.", t, place, "lost"))

    def _kill(self, member: Dict, j: Journey, t: float, place: str = "",
              where=None) -> None:
        member["alive"] = False
        member["health"] = 0
        x, z = where if where is not None else (
            (self.places[place]["x"], self.places[place]["z"]) if place in self.places
            else j.position_at(t))
        self.remains.append({"name": member["display"], "role": member["role"],
                             "x": x + self.rng.uniform(-160, 160),
                             "z": z + self.rng.uniform(-160, 160),
                             "gold": int(member.get("gold", 0)), "t": t,
                             "home": j.home, "place": place, "journey": j.id,
                             "keepsake": j.kind == "adventurers"})
        if isinstance(member.get("inventory"), list):
            self.remains[-1]["inventory"] = member.pop("inventory")
            if any(s.get("id") == "gold" for s in self.remains[-1]["inventory"]):
                self.remains[-1]["gold"] = 0  # the actual coin stack already holds it
        if len(self.remains) > REMAINS_CAP:
            self.remains = self.remains[-REMAINS_CAP:]

    # -- encounters on the road ------------------------------------------------
    def _encounters(self, t: float, made: List[str]) -> None:
        # A force holding a place meets whoever comes near it there.
        moving = [j for j in self.journeys.values()
                  if (j.state == "travel" or j.cause and j.state == "rest" and j.dest != j.home)
                  and not j.live and j.alive()]
        for i, a in enumerate(moving):
            ax, az = a.position_at(t)
            for b in moving[i + 1:]:
                if not (a.hostile or b.hostile or a.cause or b.cause or a.kind == "patrol" or b.kind == "patrol"):
                    continue
                if not (_hostile(a.faction, b.faction)
                        or a.cause and a.cause.get("target_faction") == b.faction
                        or b.cause and b.cause.get("target_faction") == a.faction):
                    continue
                if b.id in a.fought:
                    continue
                bx, bz = b.position_at(t)
                if math.hypot(ax - bx, az - bz) > ENCOUNTER_RADIUS:
                    continue
                a.fought.append(b.id)
                b.fought.append(a.id)
                self._clash(a, b, t, ((ax + bx) / 2, (az + bz) / 2), made)

    def _clash(self, a: Journey, b: Journey, t: float, where, made: List[str]) -> None:
        """Two hostile parties meet out of anyone's sight. Dice decide."""
        before = [(j, m) for j in (a, b) for m in j.alive()]
        sa, sb = a.strength(), b.strength()
        if sa + sb <= 0:
            return
        winner, loser = (a, b) if self.rng.random() < sa / (sa + sb) else (b, a)
        near = self.place_name(self.nearest_place(*where))
        wl, ll = winner.leader(), loser.leader()
        wname = wl["display"] if wl else winner.kind
        lname = ll["display"] if ll else loser.kind
        fighters = [m for m in loser.alive() if m["role"] in FIGHTERS]
        if winner.hostile and not fighters and loser.kind in ("trader", "caravan",
                                                               "pilgrims", "courier",
                                                               "minstrel", "market"):
            # Robbery: the gang takes the purse; a victim who argues is killed.
            taken = sum(int(m.get("gold", 0)) for m in loser.alive())
            for m in loser.alive():
                m["gold"] = 0
            self.hooks.robbed_cargo(loser, winner)
            dead = 0
            for m in list(loser.alive()):
                if self.rng.random() < 0.3:
                    self._kill(m, loser, t, where=where)
                    dead += 1
            for m in winner.alive():
                m["gold"] = int(m.get("gold", 0)) + taken // max(1, len(winner.alive()))
            text = (f"Brigands under {wname} robbed {lname} on the road near {near}"
                    + (f"; {dead} did not live to tell of it." if dead else "."))
            made.append(self.say(text, t, self.nearest_place(*where), "robbery"))
        else:
            dead = 0
            for m in list(loser.alive()):
                # A gang's chief with a price on his head slips away; the
                # bounty stays the player's to claim.
                if m.get("wanted"):
                    continue
                if self.rng.random() < 0.65:
                    self._kill(m, loser, t, where=where)
                    dead += 1
            for m in winner.alive():
                m["health"] = max(1, int(m["health"] * self.rng.uniform(0.5, 0.95)))
            text = f"{wname}'s party fought {lname}'s near {near}"
            text += (f" and left {dead} dead on the road." if dead else ", and won.")
            made.append(self.say(text, t, self.nearest_place(*where), "battle"))
            if not loser.alive():
                loser.state = "done"
        for j in (a, b):
            for nid in made[-1:]:
                if nid not in j.news:
                    j.news.append(nid)
        self.hooks.encounter_resolved(winner, loser, t, where,
                                     [(j, m) for j, m in before if not m.get("alive", True)])

    # -- news -----------------------------------------------------------------
    def say(self, text: str, t: float, place: Optional[str], kind: str = "",
            subject: str = "") -> str:
        """Make a piece of news, heard first at *place*."""
        nid = f"n{self.next_id}"
        self.next_id += 1
        self.news[nid] = {"id": nid, "t": t, "text": text, "place": place or "",
                          "kind": kind, "subject": subject}
        if place:
            self.heard.setdefault(place, []).append(nid)
        return nid

    def news_for(self, ids: Iterable[str], limit: int = 3) -> List[str]:
        """The freshest of *ids*, as sentences, newest first."""
        found = [self.news[i] for i in ids if i in self.news]
        found.sort(key=lambda n: -n["t"])
        return [n["text"] for n in found[:limit]]

    def news_at(self, place: str, limit: int = 3) -> List[str]:
        return self.news_for(self.heard.get(place, []), limit)

    def _forget(self, t: float) -> None:
        stale = [k for k, n in self.news.items() if t - n["t"] > NEWS_HOURS]
        if len(self.news) - len(stale) > NEWS_CAP:
            ordered = sorted(self.news.values(), key=lambda n: n["t"])
            stale += [n["id"] for n in ordered[:len(self.news) - NEWS_CAP]]
        if not stale:
            return
        for k in set(stale):
            if k == self.bounty_news and self.hooks.player_bounty() > 0:
                continue
            self.news.pop(k, None)
        for ids in self.heard.values():
            ids[:] = [i for i in ids if i in self.news]
        for j in self.journeys.values():
            j.news = [i for i in j.news if i in self.news]

    def _watch_bounty(self, t: float, made: List[str]) -> None:
        """A new or bigger price on the player's head becomes news -- heard
        first where the player is, and spread from there by the roads."""
        bounty = int(self.hooks.player_bounty() or 0)
        if bounty <= 0:
            self.bounty_seen = 0
            return
        if bounty <= self.bounty_seen:
            return
        self.bounty_seen = bounty
        place = self.hooks.player_place()
        nid = self.say(f"There's a price of {bounty} gold on the head of "
                       f"{self.hooks.player_name()}.", t, place, "bounty", "player")
        self.bounty_news = nid
        made.append(nid)

    def knows_bounty(self, j: Journey) -> bool:
        return bool(self.bounty_news) and self.bounty_news in j.news

    # -- townsfolk trips -------------------------------------------------------
    def _resident_trips(self, t: float) -> None:
        """Now and then a merchant or farmer walks to market in the next town
        and comes home again (they are hidden at home while away)."""
        if not self.resident_pool or len(self.residents_on_trips) >= MAX_RESIDENT_TRIPS:
            return
        hour = t % 24.0
        if not self._in_hours(hour, self._hours("market")) or self.rng.random() >= self._lever("market_chance", 0.25):
            return
        r = self.rng.choice(self.resident_pool)
        if r["id"] in self.residents_on_trips:
            return
        if not self.hooks.resident_can_leave(r["id"]):
            return
        home = r["home"]
        towns = [p for p in self.places_of(TOWNS) if p != home]
        if not towns or home not in self.network.place_node:
            return
        hx, hz = self.places[home]["x"], self.places[home]["z"]
        towns.sort(key=lambda p: math.hypot(self.places[p]["x"] - hx,
                                            self.places[p]["z"] - hz))
        member = {"role": r.get("role", "merchant"), "name": r["name"],
                  "display": r["display"], "health": r.get("health", 60),
                  "max_health": r.get("health", 60), "damage": r.get("damage", 5),
                  "style": "melee", "alive": True, "gold": 30, "head": r.get("head", ""),
                  "resident": r["id"]}
        # Keep market trips local while letting remembered trouble draw traffic.
        nearby = towns[:4]
        preferred = self.hooks.resident_destination(r["id"], towns, home)
        if preferred in towns and self._route(home, preferred) is not None:
            if preferred not in nearby:
                nearby.append(preferred)
            weights = [float(d == preferred) for d in nearby]
        else:
            weights = [self.hooks.destination_weight(d) for d in nearby]
        town = self.rng.choices(nearby, weights=weights)[0]
        j = self.plan("market", t, origin=home, dest=town, members=[member])
        if j is None:
            return
        j.resident = r["id"]
        j.home = home
        j.legs = 2
        self.residents_on_trips[r["id"]] = j.id
        self.hooks.journey_sampled(j, t, destination_sampled=True)
        self.hooks.resident_left(r["id"], j)

    def _retire(self, j: Journey) -> None:
        if j.cause:
            self.hooks.faction_returned(j)
            for member in j.members:
                rid = member.get("resident")
                self.residents_on_trips.pop(rid, None)
                self.hooks.resident_home(rid, j, bool(member.get("alive", True)))
        if j.resident:
            self.residents_on_trips.pop(j.resident, None)
            lead = j.members[0] if j.members else {}
            self.hooks.resident_home(j.resident, j, bool(lead.get("alive", True)))
        self.journeys.pop(j.id, None)

    # -- persistence -------------------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({
            "journeys": [j.to_dict() for j in self.journeys.values()],
            "news": list(self.news.values()), "heard": self.heard,
            "remains": self.remains, "next_id": self.next_id, "last_t": self.last_t,
            "bounty_news": self.bounty_news, "bounty_seen": self.bounty_seen,
            "residents_on_trips": self.residents_on_trips,
            "streaming": {"version": 1, "hostile_materialisations": self.hostile_materialisations},
        })

    def load_json(self, raw: str) -> bool:
        try:
            d = json.loads(raw)
        except (TypeError, ValueError):
            return False
        if not isinstance(d, dict):
            return False
        self.journeys = {}
        for jd in d.get("journeys", []):
            try:
                j = Journey.from_dict(jd)
            except Exception:
                continue
            if j.kind in KINDS:
                self.journeys[j.id] = j
        self.news = {n["id"]: n for n in d.get("news", []) if isinstance(n, dict)}
        self.heard = {k: list(v) for k, v in (d.get("heard") or {}).items()}
        self.remains = list(d.get("remains", []))
        self.next_id = int(d.get("next_id", self.next_id))
        self.last_t = d.get("last_t")
        self.bounty_news = d.get("bounty_news", "") or ""
        self.bounty_seen = int(d.get("bounty_seen", 0) or 0)
        self.residents_on_trips = dict(d.get("residents_on_trips") or {})
        streaming = d.get("streaming") or {}
        self.hostile_materialisations = (dict(streaming.get("hostile_materialisations") or {})
                                        if streaming.get("version") == 1 else {})
        for j in self.journeys.values():
            for m in j.members:
                self._names_used.add(m.get("display", ""))
        return True


#: Bounty at which hunters come for the player.
HUNTER_BOUNTY = 150
#: Most townsfolk away on market trips at once.
MAX_RESIDENT_TRIPS = 3


def _hostile(a: str, b: str) -> bool:
    from ..rpg import factions
    return factions.is_hostile(a, b)
