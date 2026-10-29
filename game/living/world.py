"""
The living world, wired into a play session.

:mod:`game.living.journeys` keeps the roads' population as data. This module
is the bridge between that data and the scene, and it is built around Big
World's rule that only the region round the player is simulated:

* **Materialise.** When a journey's computed position comes within the region
  Big World keeps live (its activation radius), its party becomes real
  actors -- NPCs (or beasts) with names, faces, gear, dialogue and, for a
  trader, wares -- standing on the road where the clock says they are. From
  then on the engine's AI is in charge of them: a caravan meeting brigands is
  a real fight; a trader passing the player can be talked to, traded with,
  robbed, or escorted.
* **Walk.** Live parties follow their route: the leader walks the road a
  little ahead of where they are, the rest keep formation behind; they stop to
  greet the player; fighters engage enemies in sight and non-fighters run to
  them; they rest at their destination and wander about the town until it is
  time to go on.
* **Dematerialise.** When a party drifts back out of the live region, its
  progress, wounds, deaths and purse are written back to the journey and the
  actors are removed. Far away it is, once again, only arithmetic.

Everything else the board does (encounters, arrivals, news, raids, delves,
hunters, townsfolk on market trips) happens off-screen through
:class:`SessionHooks`, which lets the board act on the scene without knowing
it: clear a lair's creatures, take a farm's livestock, hide a merchant who has
gone to market.

The roads are your ``ROAD_*`` PathNodes (see :mod:`game.living.roads`), with
fallback tracks between places until you have authored them. Other PathNodes
(patrol routes and the like) are not roads.
"""

from __future__ import annotations

import copy
import json
import math
import time
from typing import Dict, List, Optional

from .. import fio
from ..rpg import factions
from ..rpg import heads as rpg_heads
from ..rpg import items as rpg_items
from ..rpg import quests as rpg_quests
from . import journeys as jn
from . import roads

#: Seconds (real) between board updates, and between live-party decisions.
BOARD_INTERVAL = 1.0
DECIDE_INTERVAL = 0.35
#: Persist the board at most this often (s).
PERSIST_INTERVAL = 10.0
#: Most parties live as actors at once (the rest wait their turn as data).
MAX_LIVE = 6
#: How far ahead along the road the leader aims.
LOOK_AHEAD = 320.0
#: Followers keep this far behind the leader, per place in the file.
FILE_SPACING = 95.0
#: The leader waits for anyone further behind than this.
STRAGGLE = 520.0
#: A peaceful traveller stops to greet a player this near.
GREET_RADIUS = 300.0
#: Fighters engage enemies this near; everyone else runs from them.
SIGHT = 900.0
#: Disengage after this long with nothing to fight (s).
CALM_SECONDS = 6.0
#: How long remains of the dead stay on the road (game hours).
REMAINS_HOURS = 72.0
#: The store key the board is saved under.
STORE_KEY = "living.board"
QUEST_KEY = "living.quests"

#: What each journey role becomes as an actor: (bestiary role, faction,
#: aggression, combatant, weapon, head choice).
ACTOR_ROLES = {
    "merchant": ("merchant", None, "passive", False, "iron_dagger", "head"),
    "mercenary": ("guard", "villagers", "defensive", True, "iron_longsword", "head"),
    "pilgrim": ("villager", None, "passive", False, "", "head"),
    "adventurer": ("guard", "adventurers", "defensive", True, "steel_longsword", "head"),
    "guard": ("guard", "guards", "defensive", True, "iron_longsword", "guard"),
    "courier": ("villager", None, "passive", False, "", "head"),
    "minstrel": ("villager", None, "passive", False, "", "head"),
    "bandit_chief": ("bandit_chief", "bandits", "hostile", True, "steel_longsword", "head"),
    "bandit": ("bandit", "bandits", "hostile", True, "iron_shortsword", "head"),
    "bandit_archer": ("bandit_archer", "bandits", "hostile", True, "hunting_bow", "head"),
    "wolf": ("wolf", "wildlife", "hostile", True, "", "wolf"),
    "greenskin": ("bandit", "monsters", "hostile", True, "iron_shortsword", "greenskin01"),
    "bounty_hunter": ("guard", "mercenaries", "defensive", True, "steel_longsword", "head"),
}

#: Wares a road trader carries.
TRADER_STOCK = ("bread", "potion_heal_minor", "potion_magicka", "torch", "iron_arrow",
                "cloth_robe", "hide_boots", "leather_cuirass", "copper_ring",
                "lockpick", "hide_armour", "buckler", "chain_coif", "ingr_flax")

#: What people say on the road, by party kind.
GREETINGS = {
    "trader": ("Fine wares, fair prices! Well -- fair-ish.", "Buying or selling, friend?",
               "Roads are long and my pack is heavy. Care to lighten it?"),
    "caravan": ("Keep your distance from the wagons, stranger.",
                "Caravan to {dest}. Trading, if you've coin."),
    "pilgrims": ("Blessings of the road upon you.", "We walk to {dest}, to pray.",
                 "Peace, traveller."),
    "adventurers": ("Off to {dest}. Wish us luck!", "There's treasure in {dest}, they say.",
                    "Fancy yourself a sword-arm? We're bound for {dest}."),
    "patrol": ("Keep to the road, citizen.", "Move along. Nothing to see.",
               "Watch yourself out here."),
    "courier": ("Can't stop -- letters for {dest}!", "Mind the road, I'm in a hurry."),
    "minstrel": ("♪ Oh the road goes ever on... ♪",
                 "A song for a coin, friend?", "Have you heard the one about the miller?"),
    "market": ("Off to market in {dest}.", "Good day! Market day in {dest}."),
    "hunters": ("Looking for someone. You'll do.", "Stay out of our way."),
    "bandits": ("Your purse or your life!", "Well, well. What have we here?",
                "Nobody passes without paying."),
}
PURPOSE = {
    "trader": "To sell what's in my pack and buy what isn't.",
    "caravan": "Goods for the market there, if the road allows it.",
    "pilgrims": "To pray at the shrine, as our mothers did.",
    "adventurers": "There's something nasty there that needs a sword through it.",
    "patrol": "The watch rides between the towns. Keeps the roads honest.",
    "courier": "Letters. Always letters.",
    "minstrel": "Wherever there's an audience and a hearth.",
    "market": "Market day. A body has to sell to eat.",
    "hunters": "Business.",
    "bandits": "None of yours.",
}


def _now_hours(clock) -> float:
    return float(clock.day) * 24.0 + float(clock.hour)


def _slug(text) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in str(text)).strip("_")


class SessionHooks(jn.WorldHooks):
    """The board's view of the scene, answered by the session."""

    def __init__(self, world: "LivingWorld"):
        self.w = world

    @property
    def _storyteller(self):
        """The simulation's pacing subsystem, or None for a session without one."""
        return getattr(self.w.session, "storyteller", None)

    def journey_levers(self):
        storyteller = self._storyteller
        return storyteller.board_levers() if storyteller is not None else {}

    def resident_destination(self, resident_id, towns, origin):
        storyteller = self._storyteller
        if storyteller is None or not storyteller.enabled:
            return None
        town = storyteller.player_town()
        target, home = self.w.places.get(town), self.w.places.get(origin)
        distance = math.hypot(target["x"] - home["x"], target["z"] - home["z"]) if target and home else math.inf
        return storyteller.resident_destination(resident_id, towns, distance)

    def journey_weight(self, kind, position, hostile):
        storyteller = self._storyteller
        return storyteller.journey_weight(kind, position, hostile) if storyteller is not None else 1.0

    def journey_sampled(self, journey, t, *, arrived=False, destination_sampled=False):
        storyteller = self._storyteller
        if storyteller is not None:
            storyteller.record_journey(journey, t, arrived=arrived, destination_sampled=destination_sampled)

    def destination_weight(self, place_key):
        storyteller = self._storyteller
        return storyteller.destination_weight(place_key) if storyteller is not None else 1.0

    def bandit_destination_weight(self, place_key):
        storyteller = self._storyteller
        if storyteller is None or not storyteller.enabled:
            return 1.0
        target = self.w.places.get(storyteller.player_town())
        place = self.w.places.get(place_key)
        if target is None or place is None:
            return 1.0
        return storyteller.bandit_destination_weight(math.hypot(place["x"] - target["x"],
                                                               place["z"] - target["z"]))

    def faction_orders(self):
        spine = getattr(self.w.session, "faction_spine", None)
        return spine.pending() if spine is not None else ()

    def faction_departed(self, journey):
        self.w.session.faction_spine.departed(journey)

    def faction_returned(self, journey):
        self.w.session.faction_spine.returned(journey)

    def encounter_resolved(self, winner, loser, t, where, fallen):
        spine = getattr(self.w.session, "faction_spine", None)
        if spine is not None:
            spine.encounter(winner, loser, t, where, fallen)

    def materialisation_weight(self, actor_keys, distance):
        storyteller = self._storyteller
        return storyteller.materialisation_weight(actor_keys, distance) if storyteller is not None else 1.0

    def site_strength(self, place_key):
        return sum(float(t.properties.get("health", 0) or 0)
                   * float(t.properties.get("damage", 5) or 5)
                   for t in self.w.site_creatures(place_key))

    def clear_site(self, place_key, fraction):
        alive = self.w.site_creatures(place_key)
        n = int(round(len(alive) * max(0.0, min(1.0, fraction))))
        for t in alive[:n]:
            p = t.properties
            p["dead"] = True
            p["health"] = 0
            p["triggered"] = True
        return n

    def raid_place(self, place_key, strength):
        stock = self.w.livestock_near(place_key)
        n = min(len(stock), 1 + int(strength // 6000))
        for t in stock[:n]:
            p = t.properties
            p["dead"] = True
            p["health"] = 0
        return n

    def player_bounty(self):
        c = getattr(self.w.session.game, "character", None)
        return int(getattr(c, "bounty", 0) or 0)

    def player_place(self):
        pos = self.w.session._player_pos()
        if pos is None:
            return None
        return self.w.board.nearest_place(pos[0], pos[2], jn.TOWNS)

    def player_name(self):
        c = getattr(self.w.session.game, "character", None)
        return getattr(c, "name", "the stranger")

    def resident_can_leave(self, resident_id):
        t = self.w.resident_thing(resident_id)
        if t is None or t.properties.get("dead"):
            return False
        from engine.spatial import TIER_DISTANT
        p = t.properties
        # Only someone the player cannot see goes: nobody vanishes on screen.
        parked = "_bw_parked_hidden" in p
        tier = int(p.get("_sim_tier", 0) or 0)
        spine = getattr(self.w.session, "faction_spine", None)
        if spine is not None and spine.enabled():
            # Journey sampling may read appraisal, never populate its cache.
            intents = self.w.session.director.evaluate(t)
            if intents and intents[0].reaction == "MOURN":
                return False
        return parked or tier >= TIER_DISTANT

    def resident_left(self, resident_id, journey):
        t = self.w.resident_thing(resident_id)
        if t is not None:
            t.properties["away_on_journey"] = journey.id
            self.w.set_hidden(t, True)

    def resident_home(self, resident_id, journey, alive):
        t = self.w.resident_thing(resident_id)
        if t is None:
            return
        t.properties.pop("away_on_journey", None)
        member = next((m for m in journey.members if m.get("resident") == resident_id), {})
        if alive and journey.cause:
            t.properties["health"] = member.get("health", t.properties.get("health", 60))
            for key in ("inventory", "equipped_weapon", "alignment"):
                if key in member:
                    t.properties[key] = copy.deepcopy(member[key])
        if not alive:
            t.properties["dead"] = True
            t.properties["health"] = 0
        self.w.set_hidden(t, False)


class LivingWorld:
    """The bridge between the journey board and the scene (module docstring)."""

    def __init__(self, session, population: int = 26):
        self.session = session
        self.population = population
        self.board: Optional[jn.JourneyBoard] = None
        self.places: Dict[str, Dict] = {}
        self.live: Dict[str, Dict] = {}            # journey id -> {"things": [...]}
        self.live_remains: Dict[int, object] = {}  # remains index -> container
        self._board_t = 0.0
        self._decide_t = 0.0
        self._persist_t = 0.0
        self._site_index: Dict[str, List] = {}
        self._livestock_index: Dict[str, List] = {}
        self._residents: Dict[str, object] = {}
        self._quests_def: List[Dict] = []
        self._head_pool: List[str] = []
        self.enabled = True

    # ------------------------------------------------------------------ build
    def build(self) -> bool:
        """Read the map: places, roads, lairs, livestock, townsfolk. Then load
        the saved board, or seed a world that has been running a while."""
        s = self.session
        things = list(fio.things(s.logic))
        places = self._classify_places(things)
        if len(places) < 2:
            self.enabled = False
            return False
        network = roads.RoadNetwork.build(
            roads.authored_roads(things), [(k, v["x"], v["z"]) for k, v in places.items()])
        self.places = places
        self.board = jn.JourneyBoard(network, places, s.clock.hours_per_second,
                                     rng=s.rng, hooks=SessionHooks(self),
                                     population=self.population)
        self._index_scene(things)
        spine = getattr(s, "faction_spine", None)
        if spine is not None:
            spine.bind(self.board, [t for t in things if str(t.properties.get("type")) in ("npc", "creature")])
        self._head_pool = [h for h in rpg_heads.HEAD_IDS
                           if h != getattr(s.game.character, "head", "")]
        now = _now_hours(s.clock)
        raw = s.store.get(STORE_KEY, "")
        if not (raw and raw != "false" and self.board.load_json(raw)):
            self.board.seed(now)
            self.board.last_t = now
        self._restore_quests()
        return True

    def _classify_places(self, things) -> Dict[str, Dict]:
        """Every named location, and what sort of place it is, read off what
        stands near it: townsfolk make a town, hostile creatures a lair."""
        markers = []
        actors = []
        for t in things:
            p = t.properties
            kind = str(p.get("type", "")).replace("_", "").lower()
            if kind == "marker" and str(p.get("marker_kind", "")).lower() == "location" \
                    and p.get("place_name"):
                markers.append(t)
            elif kind in ("npc", "creature"):
                actors.append(t)
        out = {}
        for m in markers:
            p = m.properties
            name = str(p["place_name"])
            r = max(900.0, float(p.get("discover_radius", 900.0) or 900.0))
            mx, mz = float(m.pos[0]), float(m.pos[2])
            folk = hostile = livestock = 0
            for a in actors:
                ap = a.properties
                if ap.get("dead"):
                    continue
                if math.hypot(a.pos[0] - mx, a.pos[2] - mz) > r:
                    continue
                if str(ap.get("type")) == "npc" and ap.get("faction") in ("villagers", "guards"):
                    folk += 1
                elif str(ap.get("aggression")) == "hostile":
                    hostile += 1
                elif ap.get("npc_role") in ("cow", "sheep", "hen"):
                    livestock += 1
            low = name.lower()
            if any(w in low for w in ("shrine", "moonwell", "circle", "sisters", "stones")) \
                    and hostile < 2:
                kind = "shrine"
            elif hostile >= 2:
                kind = "danger"
            elif any(w in low for w in ("farm", "steading")):
                kind = "farm"
            elif any(w in low for w in ("rest", "lantern", "lodge", "inn")):
                kind = "inn"
            elif folk >= 4:
                kind = "town"
            elif folk >= 1:
                kind = "hamlet"
            elif livestock >= 3:
                kind = "farm"
            else:
                continue
            out[_slug(name)] = {"name": name, "x": mx, "z": mz, "kind": kind, "radius": r}
        return out

    def _index_scene(self, things) -> None:
        """Which creatures guard which lair, which beasts graze at which farm,
        and the townsfolk who may go to market."""
        sites = {k: v for k, v in self.places.items() if v["kind"] == "danger"}
        farms = {k: v for k, v in self.places.items() if v["kind"] in ("farm", "hamlet")}
        pool = []
        for t in things:
            p = t.properties
            kind = str(p.get("type", "")).lower()
            if kind not in ("npc", "creature"):
                continue
            rid = str(p.get("id") or p.get("name") or "")
            if rid:
                self._residents[rid] = t
            x, z = float(t.pos[0]), float(t.pos[2])
            if kind == "creature" and str(p.get("aggression")) == "hostile":
                for k, v in sites.items():
                    if math.hypot(x - v["x"], z - v["z"]) <= v["radius"]:
                        self._site_index.setdefault(k, []).append(t)
                        break
            elif kind == "creature" and p.get("npc_role") in ("cow", "sheep", "hen"):
                for k, v in farms.items():
                    if math.hypot(x - v["x"], z - v["z"]) <= 1800.0:
                        self._livestock_index.setdefault(k, []).append(t)
                        break
            elif kind == "npc" and p.get("npc_role") in ("merchant", "farmer", "villager") \
                    and p.get("faction") == "villagers" and not self._gives_quests(p):
                home = self.board.nearest_place(x, z, jn.HOMES)
                if home is None:
                    continue
                hp = self.places[home]
                if math.hypot(x - hp["x"], z - hp["z"]) > 2500.0:
                    continue
                rid = str(p.get("id") or p.get("name"))
                self._residents[rid] = t
                pool.append({"id": rid, "home": home, "role": p.get("npc_role"),
                             "name": p.get("name", rid),
                             "display": p.get("display_name", p.get("name", "Someone")),
                             "health": p.get("health", 60), "damage": p.get("damage", 5),
                             "head": p.get("head", "")})
        self.board.resident_pool = pool[:40]

    @staticmethod
    def _gives_quests(props) -> bool:
        tree = props.get("dialogue")
        try:
            return "start_quest" in json.dumps(tree)
        except (TypeError, ValueError):
            return False

    def site_creatures(self, place_key) -> List:
        return [t for t in self._site_index.get(place_key, ())
                if not t.properties.get("dead")]

    def livestock_near(self, place_key) -> List:
        return [t for t in self._livestock_index.get(place_key, ())
                if not t.properties.get("dead")]

    def resident_thing(self, resident_id):
        return self._residents.get(resident_id)

    @staticmethod
    def set_hidden(thing, hidden: bool) -> None:
        """Hide or show an actor, respecting Big World's parking: a parked
        actor keeps what it will be restored to in its parking marks."""
        p = thing.properties
        if "_bw_parked_hidden" in p:
            p["_bw_parked_hidden"] = bool(hidden)
            p["_bw_parked_disabled"] = bool(hidden)
        else:
            p["hidden"] = bool(hidden)
            p["disabled"] = bool(hidden)
        try:
            from engine.change_journal import touch
            touch(thing)
        except Exception:
            pass

    # -------------------------------------------------------------------- tick
    def tick(self, delta: float) -> None:
        if not self.enabled or self.board is None:
            return
        now = time.monotonic()
        s = self.session
        self._board_t += delta
        if self._board_t >= BOARD_INTERVAL:
            self._board_t = 0.0
            spine = getattr(s, "faction_spine", None)
            if spine is not None:
                spine.begin_tick()
                spine.decide(_now_hours(s.clock))
            made = self.board.update(_now_hours(s.clock))
            self._enforce_away()
            self._stream()
            self._stream_remains()
            if made:
                self._overheard(made)
        self._decide_t += delta
        if self._decide_t >= DECIDE_INTERVAL:
            self._decide_t = 0.0
            for jid in list(self.live):
                self._drive(jid)
        # Beasts are not NPCs, so the session's mover does not walk them.
        for entry in self.live.values():
            for t in entry["things"]:
                if str(t.properties.get("type")) == "creature":
                    s._move(t, delta)
        if now - self._persist_t >= PERSIST_INTERVAL:
            self.persist()

    def _enforce_away(self) -> None:
        """Townsfolk on a trip stay hidden at home, whatever unparks them."""
        for rid in self.board.residents_on_trips:
            t = self.resident_thing(rid)
            if t is not None and not t.properties.get("hidden") \
                    and "_bw_parked_hidden" not in t.properties:
                self.set_hidden(t, True)

    def _overheard(self, made) -> None:
        """Fresh news the player is near enough to hear of at once."""
        s = self.session
        pos = s._player_pos()
        if pos is None:
            return
        here = self.board.nearest_place(pos[0], pos[2])
        for nid in made:
            n = self.board.news.get(nid)
            if n and n.get("place") == here and n.get("kind") not in ("bounty",):
                s.notify(n["text"], 5.0)

    # ------------------------------------------------------------- streaming
    def reach(self) -> float:
        """How far out journeys become actors: the region Big World keeps
        live (its activation radius), so nothing is created where the world
        is not simulated."""
        bw = fio.bigworld(self.session.logic)
        manager = getattr(bw, "manager", None)
        radius = getattr(manager, "activation_radius", None)
        try:
            return max(1200.0, float(radius) * 0.9) if radius else 2200.0
        except (TypeError, ValueError):
            return 2200.0

    def _stream(self) -> None:
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return
        px, pz = ppos[0], ppos[2]
        t = _now_hours(s.clock)
        near = self.reach()
        far = near + 700.0
        # Out first, so a slot is free for whoever is coming in.
        for jid in list(self.live):
            j = self.board.journeys.get(jid)
            if j is None:
                self._despawn(jid, None)
                continue
            things = [x for x in self.live[jid]["things"] if not x.properties.get("dead")]
            if not things:
                self._despawn(jid, j)
                continue
            gone = all(math.hypot(x.pos[0] - px, x.pos[2] - pz) > far for x in things)
            fighting = any(x.properties.get("triggered") is False for x in things)
            if gone and not fighting:
                self._despawn(jid, j)
        if len(self.live) >= MAX_LIVE:
            return
        candidates = []
        for j in self.board.journeys.values():
            if j.live or j.state == "done" or not j.alive():
                continue
            x, z = self._abstract_pos(j, t)
            d = math.hypot(x - px, z - pz)
            if d <= near:
                local_weight = self.board.hooks.journey_weight(j.kind, (x, z),
                        j.hostile or bool(jn.KINDS[j.kind].get("hunts_player")))
                if local_weight <= 0:
                    continue
                from ..sim.director import actor_key
                keys = [actor_key(identity) for m in j.members if m.get("alive", True)
                        for identity in (m.get("resident"), m.get("id") or m.get("name"))
                        if identity]
                weight = self.board.hooks.materialisation_weight(keys, d)
                candidates.append((d / max(1e-6, local_weight * max(1.0, weight)), j))
        for _d, j in sorted(candidates, key=lambda c: c[0]):
            if len(self.live) >= MAX_LIVE:
                break
            self._spawn(j, t)
            if j.id in self.live:
                self.board.hooks.journey_sampled(j, t, arrived=True)
            if j.id in self.live and (j.hostile or jn.KINDS[j.kind].get("hunts_player")):
                region = self.board.nearest_place(px, pz, jn.TOWNS)
                if region is not None:
                    counts = self.board.hostile_materialisations
                    counts[region] = counts.get(region, 0) + 1

    def _abstract_pos(self, j, t):
        if j.state == "rest":
            p = self.places.get(j.dest)
            if p is not None:
                return p["x"], p["z"]
        return j.position_at(t)

    def _ground_y(self, x, z) -> float:
        g = fio.ground_height(self.session.logic, x, z)
        if g is not None:
            return float(g) + 56.0
        ppos = self.session._player_pos()
        return float(ppos[1]) if ppos else 256.0

    def _spawn(self, j, t) -> None:
        """Turn journey *j* into actors where the clock says it is."""
        try:
            from ..entities import NPC, Creature
        except Exception:
            return
        s = self.session
        if j.state == "travel" and len(j.route) >= 2:
            sx = j.progress_at(t)
            x0, z0, seg = roads.point_at(j.route, j.cum, sx)
            nxt = j.route[min(len(j.route) - 1, seg + 1)]
            dx, dz = nxt[0] - x0, nxt[1] - z0
            dl = math.hypot(dx, dz) or 1.0
            ux, uz = dx / dl, dz / dl
        else:
            x0, z0 = self._abstract_pos(j, t)
            ux, uz = 1.0, 0.0
        things = []
        for i, m in enumerate(j.members):
            if not m.get("alive", True):
                continue
            k = len(things)
            back = k * FILE_SPACING
            side = (-1 if k % 2 else 1) * (30.0 if k else 0.0)
            x = x0 - ux * back - uz * side + s.rng.uniform(-12, 12)
            z = z0 - uz * back + ux * side + s.rng.uniform(-12, 12)
            props = self._actor_props(j, m, i)
            cls = Creature if m["role"] in ("wolf",) else NPC
            try:
                thing = cls(pos=[x, self._ground_y(x, z), z], properties=props)
            except Exception:
                continue
            p = thing.properties
            m["id"] = p.get("id") or m["name"]
            # The bestiary fills what the template knows; the journey's own
            # numbers (wounds carried from an earlier fight) win.
            p["health"] = max(1, int(m.get("health", p.get("health", 60))))
            p["max_health"] = int(m.get("max_health", p["health"]))
            p["damage"] = int(m.get("damage", p.get("damage", 6)))
            p["_base_aggression"] = props["aggression"]
            p["aggression"] = props["aggression"]
            p["triggered"] = True
            p["awake"] = False
            things.append(thing)
            director = getattr(s, "director", None)
            if director is not None and director.mood_context is not None:
                director.evaluate(thing)  # pure materialisation touchpoint
        if not things:
            return
        scene = fio.things(s.logic)
        scene.extend(things)
        fio.rebuild_entity_caches(s.logic)
        s._rebuild_entity_caches()
        j.live = True
        self.live[j.id] = {"things": things, "calm_since": time.monotonic(),
                           "greeted": False}
        if j.resident:
            # The real townsperson stays hidden at home; this is them.
            pass
        self._maybe_offer_quest(j, things)

    def _actor_props(self, j, m, index) -> Dict:
        role, faction, aggression, combatant, weapon, head_kind = ACTOR_ROLES.get(
            m["role"], ("villager", None, "passive", False, "", "head"))
        s = self.session
        head = m.get("head") or ""
        if not head:
            if head_kind == "head" and self._head_pool:
                head = s.rng.choice(self._head_pool)
            elif head_kind == "guard":
                head = s.rng.choice(rpg_heads.GUARD_HEAD_IDS)
            elif head_kind not in ("wolf",):
                head = head_kind
            m["head"] = head
        faction = faction or j.faction
        if j.cause:
            faction, aggression, combatant = j.faction, "defensive", True
        props = {
            "name": m["name"], "display_name": m["display"], "npc_role": role,
            "faction": faction, "team": faction, "aggression": aggression,
            "combatant": combatant, "persistent": False, "respawn": False,
            "schedule": [], "autonomy": True, "home": None,
            "move_speed": jn.WALK_SPEED * float(jn.KINDS.get(j.kind, {}).get("speed", 1.0)),
            "_journey": j.id, "_member": index, "sight_range": SIGHT,
            "inventory": [], "dialogue": {}, "courage": 0.6 if combatant else 0.25,
        }
        if head:
            props["head"] = head
        if weapon and rpg_items.get(weapon):
            props["inventory"].append(rpg_items.make(weapon, 1))
            props["equipped_weapon"] = weapon
        if m["role"] == "bandit_archer":
            props["attack_style"] = "bow"
            props["inventory"].append(rpg_items.make("iron_arrow", 20))
        if j.hostile:
            props["_journey_hostile"] = True
        if m.get("gold"):
            props["inventory"].append(rpg_items.make("gold", int(m["gold"])) or
                                      {"id": "gold", "qty": int(m["gold"])})
        if m["role"] == "merchant":
            props["merchant"] = True
            props["merchant_gold"] = 120 + int(m.get("gold", 0))
            rng = s.rng
            props["stock"] = rng.sample(TRADER_STOCK, k=min(6, len(TRADER_STOCK)))
        st, en, ch = __import__("game.rpg.bios", fromlist=["npc_rolls"]).npc_rolls(
            m["name"], m["role"])
        props.update({"strength": st, "endurance": en, "charisma": ch,
                      "body_from_stats": True})
        if m.get("resident"):
            # A townsperson on a market trip: the same person, same dialogue.
            real = self.resident_thing(m["resident"])
            if real is not None:
                rp = real.properties
                # Share social identity, while keeping the proxy's scene UUID
                # distinct from the hidden resident for savegame overlays.
                props["_memory_identity"] = (rp.get("_memory_identity") or rp.get("id")
                                             or rp.get("name"))
                for k in ("dialogue", "merchant", "merchant_gold", "stock", "head",
                          "relationships", "portrait", "strength", "endurance", "charisma",
                          "courage", "alignment", "combatant"):
                    if k in rp:
                        props[k] = rp[k]
                if j.cause:
                    # A faction force is made of these actual people, including
                    # their authored role and possessions, rather than new guards.
                    for k in ("npc_role", "equipped_weapon", "attack_style", "inventory"):
                        if k in rp:
                            props[k] = copy.deepcopy(rp[k])
        if m.get("id"):
            props["id"] = m["id"]
        if not props.get("dialogue"):
            props["dialogue"] = self._tree(j, m, index)
        if j.cause:
            for key in ("inventory", "equipped_weapon", "alignment"):
                if key in m:
                    props[key] = copy.deepcopy(m[key])
            props["_faction_cause"] = j.provenance()
        return props

    def _despawn(self, jid, j) -> None:
        """Hand a party back to the board: progress, wounds, deaths, purse."""
        entry = self.live.pop(jid, None)
        if entry is None:
            return
        s = self.session
        things = entry["things"]
        if j is not None:
            alive = [x for x in things if not x.properties.get("dead")]
            by_member = {x.properties.get("_member"): x for x in things}
            for i, m in enumerate(j.members):
                x = by_member.get(i)
                if x is None:
                    continue
                p = x.properties
                if p.get("dead"):
                    if m.get("alive", True):
                        m["alive"] = False
                        m["health"] = 0
                        place = self.board.nearest_place(x.pos[0], x.pos[2])
                        nid = self.board.say(
                            f"{m['display']} was found dead on the road near "
                            f"{self.board.place_name(place)}.",
                            _now_hours(s.clock), place, "death")
                        if nid not in j.news:
                            j.news.append(nid)
                else:
                    m["health"] = max(1, int(p.get("health", m.get("health", 50)) or 1))
                if j.cause and m.get("resident"):
                    real = self.resident_thing(m["resident"])
                    for key in ("inventory", "equipped_weapon", "alignment"):
                        if key in p:
                            m[key] = copy.deepcopy(p[key])
                            if real is not None:
                                real.properties[key] = copy.deepcopy(p[key])
            if j.state == "travel" and alive and len(j.route) >= 2:
                lead = alive[0]
                sx = roads.project(j.route, j.cum, lead.pos[0], lead.pos[2])
                j.set_progress(sx, _now_hours(s.clock))
            if not j.alive():
                j.state = "done"
            j.live = False
        scene = fio.things(s.logic)
        for x in things:
            try:
                scene.remove(x)
            except ValueError:
                pass
        fio.rebuild_entity_caches(s.logic)
        s._rebuild_entity_caches()

    def shutdown(self) -> None:
        """Every party back to data (the end of a session, or a load)."""
        for jid in list(self.live):
            self._despawn(jid, self.board.journeys.get(jid) if self.board else None)
        scene = fio.things(self.session.logic)
        for thing in list(self.live_remains.values()):
            try:
                scene.remove(thing)
            except ValueError:
                pass
        self.live_remains.clear()

    # ----------------------------------------------------------- remains
    def _stream_remains(self) -> None:
        """The dead of the roads, as a sack of belongings where they fell,
        when the player is near; forgotten after a few days or once looted."""
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return
        t = _now_hours(s.clock)
        near = self.reach()
        keep = []
        scene = fio.things(s.logic)
        changed = False
        for idx, r in enumerate(self.board.remains):
            thing = self.live_remains.get(id(r))
            if t - float(r.get("t", t)) > REMAINS_HOURS or r.get("looted"):
                if thing is not None:
                    try:
                        scene.remove(thing)
                    except ValueError:
                        pass
                    self.live_remains.pop(id(r), None)
                    changed = True
                continue
            keep.append(r)
            d = math.hypot(r["x"] - ppos[0], r["z"] - ppos[2])
            if thing is None and d <= near:
                thing = self._remains_container(r)
                if thing is not None:
                    scene.append(thing)
                    self.live_remains[id(r)] = thing
                    changed = True
            elif thing is not None:
                if not thing.properties.get("inventory"):
                    r["looted"] = True
                if d > near + 700.0:
                    try:
                        scene.remove(thing)
                    except ValueError:
                        pass
                    self.live_remains.pop(id(r), None)
                    changed = True
        self.board.remains = keep
        if changed:
            fio.rebuild_entity_caches(s.logic)
            s._rebuild_entity_caches()

    def _remains_container(self, r):
        try:
            from ..entities import Container
        except Exception:
            return None
        inv = []
        if r.get("gold"):
            g = rpg_items.make("gold", int(r["gold"]))
            if g:
                inv.append(g)
        if r.get("keepsake") and rpg_items.get("adventurers_keepsake"):
            inv.append(rpg_items.make("adventurers_keepsake", 1))
        if self.session.rng.random() < 0.5:
            extra = self.session.rng.choice(("bread", "torch", "potion_heal_minor",
                                             "lockpick", "iron_arrow"))
            if rpg_items.get(extra):
                inv.append(rpg_items.make(extra, 1))
        x, z = r["x"], r["z"]
        try:
            return Container(pos=[x, self._ground_y(x, z) - 30.0, z], properties={
                "name": f"remains_{_slug(r['name'])}", "container_kind": "sack",
                "display_name": f"Remains of {r['name']}", "inventory": inv,
                "_remains": True})
        except Exception:
            return None

    # ------------------------------------------------------------- live AI
    def owns(self, npc) -> bool:
        return bool(npc.properties.get("_journey")) and npc.properties.get("_journey") in self.live

    def _drive(self, jid) -> None:
        """One decision pass for a live party."""
        j = self.board.journeys.get(jid)
        entry = self.live.get(jid)
        if j is None or entry is None:
            return
        s = self.session
        things = [x for x in entry["things"] if not x.properties.get("dead")]
        if not things:
            return
        ppos = s._player_pos()
        now = time.monotonic()
        threat_seen = False
        for x in things:
            if x.properties.get("_arrest_state"):
                continue                 # the arrest flow has this one
            if self._react(j, x, ppos):
                threat_seen = True
        if threat_seen:
            entry["calm_since"] = now
        elif now - entry["calm_since"] >= CALM_SECONDS:
            for x in things:
                self._stand_down(x)
        if threat_seen:
            return
        leader = things[0]
        t = _now_hours(s.clock)
        if j.state == "travel":
            self._walk(j, things, t)
            end = j.route[-1]
            if math.hypot(leader.pos[0] - end[0], leader.pos[2] - end[1]) <= 260.0:
                made = []
                self.board.arrive(j, t, made)
                if made:
                    self._overheard(made)
        elif j.state == "rest":
            if t >= j.rest_until:
                self.board.next_leg(j, t)
            else:
                self._loiter(j, things)
        if ppos is not None and not j.hostile and not entry["greeted"]:
            if math.hypot(leader.pos[0] - ppos[0], leader.pos[2] - ppos[2]) <= GREET_RADIUS:
                entry["greeted"] = True
                s.bark(leader, self._greeting(j, leader))
                face = __import__("game.facing", fromlist=["face_heading"]).face_heading
                face(leader.properties, ppos[0] - leader.pos[0], ppos[2] - leader.pos[2], 1.0)

    def _react(self, j, x, ppos) -> bool:
        """Fight or flight for one traveller. True when there is a threat."""
        s = self.session
        spine = getattr(s, "faction_spine", None)
        if j.cause or (spine is not None and spine.enabled() and x.properties.get("_memory_identity")):
            intents = s.director.evaluate(x)
            offender = s._sim_actor_by_key(intents[0].target) if intents else None
            if (offender is not None and offender.pos is not None
                    and not offender.properties.get("dead")
                    and math.hypot(x.pos[0] - offender.pos[0], x.pos[2] - offender.pos[2]) <= SIGHT
                    and s._law_visible(x, offender.pos) and s._apply_sim_intent(x)):
                if offender is getattr(s, "player_actor", None):
                    self._say_why(x)
                return True
        p = x.properties
        combatant = bool(p.get("combatant"))
        enemy = s._nearest_hostile(x, SIGHT)
        player_threat = False
        if ppos is not None:
            d = math.hypot(x.pos[0] - ppos[0], x.pos[2] - ppos[2])
            if d <= SIGHT:
                if not j.cause and (j.hostile and j.kind != "wolves" or j.kind == "wolves" and d < 500):
                    player_threat = True
                elif j.kind == "hunters" and self.board.hooks.player_bounty() > 0:
                    player_threat = True
                elif str(p.get("aggression")) == "hostile" and not j.hostile:
                    player_threat = True       # provoked by the player
        if enemy is None and not player_threat:
            return False
        if combatant:
            if p.get("triggered", True):
                if j.kind == "hunters" and player_threat and enemy is None:
                    s.bark(x, f"There's {self.board.hooks.player_bounty()} gold walking "
                              "on two legs. Take them!")
                elif j.hostile and player_threat:
                    s.bark(x, s.rng.choice(GREETINGS.get("bandits", ("Get them!",))))
            p["triggered"] = False
            p["awake"] = True
            if enemy is not None:
                p["_aggro_target"] = id(enemy)
            elif player_threat:
                p["aggression"] = "hostile"
                p["wake_on_sight"] = True
            p["sched_state"] = "COMBAT"
        else:
            threat = enemy if enemy is not None else s.player_actor
            if threat is None or getattr(threat, "pos", None) is None:
                return True
            p["sched_state"] = "FLEE"
            p["_dest"] = s._refuge_point(x, threat)
            if not p.get("_fled_bark"):
                p["_fled_bark"] = True
                s.bark(x, s.rng.choice(("Help! Help!", "Run!", "Not my purse!",
                                        "Gods preserve us!")))
        return True

    @staticmethod
    def _stand_down(x) -> None:
        p = x.properties
        if p.get("triggered") is False:
            p["triggered"] = True
            p["awake"] = False
            p.pop("_aggro_target", None)
            p["aggression"] = p.get("_base_aggression", p.get("aggression"))
        p.pop("_fled_bark", None)
        if p.get("sched_state") in ("FLEE", "COMBAT"):
            p["sched_state"] = "TRAVEL"

    def _walk(self, j, things, t) -> None:
        """The leader walks the road; the others keep the file behind."""
        leader = things[0]
        lp = leader.properties
        sx = roads.project(j.route, j.cum, leader.pos[0], leader.pos[2])
        straggler = any(math.hypot(o.pos[0] - leader.pos[0], o.pos[2] - leader.pos[2])
                        > STRAGGLE for o in things[1:])
        lp["sched_state"] = "TRAVEL"
        if straggler:
            lp.pop("_dest", None)        # wait for the slow ones
        else:
            x, z, _seg = roads.point_at(j.route, j.cum, min(j.length, sx + LOOK_AHEAD))
            lp["_dest"] = [x, leader.pos[1], z]
        # The journey's clock follows its actors while they walk it.
        j.set_progress(sx, t)
        for k, o in enumerate(things[1:], start=1):
            op = o.properties
            op["sched_state"] = "TRAVEL"
            bx, bz, _ = roads.point_at(j.route, j.cum, max(0.0, sx - k * FILE_SPACING))
            side = (-1 if k % 2 else 1) * 30.0
            if math.hypot(o.pos[0] - bx, o.pos[2] - bz) > 70.0:
                op["_dest"] = [bx + side * 0.3, o.pos[1], bz + side * 0.3]
            else:
                op.pop("_dest", None)

    def _loiter(self, j, things) -> None:
        """Resting at the destination: idle and stroll about the place."""
        place = self.places.get(j.dest)
        if place is None:
            return
        s = self.session
        for x in things:
            p = x.properties
            p["_anchor"] = [place["x"], x.pos[1], place["z"]]
            p["wander_radius"] = 380.0
            s._idle_or_wander(x)
            p["sched_state"] = "RESTING"

    # ---------------------------------------------------------- dialogue
    def _justified_line(self, x) -> str:
        """Why this traveller came looking for the player, once, if they did.

        Reads the storyteller's sampled justification for the same social
        identity; the journey and the intent behind it already exist."""
        story = getattr(self.session, "storyteller", None)
        if story is None or not story.enabled or x.properties.get("_justified_said"):
            return ""
        from ..sim.director import peek_actor_key
        from .. import chatter
        row = story.justified_view(peek_actor_key(x))
        if not row or row.get("destination") != self.board.nearest_place(x.pos[0], x.pos[2], jn.TOWNS):
            return ""
        speaker = x.properties.get("display_name") or x.properties.get("name") or ""
        return chatter.justified_line(row.get("kind", ""), row.get("victim", ""), speaker)

    def _say_why(self, x) -> None:
        line = self._justified_line(x)
        if line:
            x.properties["_justified_said"] = True
            self.session.bark(x, line)

    def _greeting(self, j, leader) -> str:
        s = self.session
        line = self._justified_line(leader)
        if line:
            leader.properties["_justified_said"] = True
            return line
        if self.board.knows_bounty(j) and self.board.hooks.player_bounty() > 0 \
                and j.kind not in ("hunters", "bandits"):
            return s.rng.choice(("You're the one they're paying for...",
                                 "I know that face. There's a price on it.",
                                 "Wanted, aren't you? I want no trouble."))
        lines = GREETINGS.get(j.kind, ("Well met.",))
        return s.rng.choice(lines).format(dest=self.board.place_name(j.dest))

    def _tree(self, j, m, index) -> Dict:
        """The conversation a traveller offers: where they're bound, what
        they've heard on the road, wares if they have them."""
        dest = self.board.place_name(j.dest)
        origin = self.board.place_name(j.origin)
        lines = GREETINGS.get(j.kind, ("Well met, traveller.",))
        greeting = lines[index % len(lines)].format(dest=dest)
        responses = [{"text": "Where are you headed?", "goto": "where"},
                     {"text": "What news from the road?", "goto": "news"}]
        if m["role"] == "merchant":
            responses.append({"text": "Let's see your wares.", "goto": "END",
                              "actions": [{"op": "open_trade"}]})
        responses.append({"text": "Safe travels.", "goto": "END"})
        purpose = PURPOSE.get(j.kind, "")
        if j.cause:
            purpose = (f"{j.faction}, from {self.board.place_name(j.home)}. {j.cause['reason']}. "
                       "Our people at home can tell you what happened.")
        return {"start": "greet", "nodes": {
            "greet": {"text": greeting, "responses": responses},
            "where": {"text": f"From {origin}, bound for {dest}. "
                              f"{purpose}",
                      "responses": [{"text": "I see.", "goto": "greet"}]},
            "news": {"text": "", "news_of": j.id,
                     "responses": [{"text": "Thanks for the word.", "goto": "greet"}]},
        }}

    # ----------------------------------------------------------- rumours
    def _place_label(self, x, z) -> str:
        key = self.board.nearest_place(x, z) if self.board is not None else None
        return self.board.place_name(key) if key else ""

    def _today(self):
        clock = getattr(self.session, "clock", None)
        return int(getattr(clock, "day", 0)) if clock is not None else None

    def rumours(self, npc, limit: int = 2, skip=()) -> List:
        """``[(event id, sentence)]``: what *npc* believes and would volunteer.

        Narration of their own stored facts (game/sim/rumours.py); reading
        them writes nothing and draws no random number."""
        from ..sim import knowledge, rumours
        from ..sim.director import peek_actor_key
        store = getattr(self.session, "store", None)
        key = peek_actor_key(npc)
        if store is None or not key or self.board is None:
            return []
        name = npc.properties.get("display_name") or npc.properties.get("name") or ""
        picked = rumours.pick(knowledge.facts_view(store, key), limit, skip)
        return [(int(f.get("e", 0) or 0),
                 rumours.line(f, self._place_label, self._today(), speaker=name,
                              place_name=self.board.place_name))
                for f in picked]

    def departures(self, place, limit: int = 2) -> List[str]:
        """Neighbours' accounts of actual journeys that set out from *place*:
        faction orders, and residents on justified trips."""
        from ..sim import rumours
        from ..sim.director import PLAYER_KEY, peek_actor_key
        if self.board is None or not place:
            return []
        story = getattr(self.session, "storyteller", None)
        out = []
        for j in sorted(self.board.journeys.values(), key=lambda j: -j.depart_t):
            if j.state != "travel" or j.home != place or j.dest == place:
                continue
            dest = self.board.place_name(j.dest)
            if j.cause:
                fact = j.cause.get("fact") or {}
                target = "you" if j.cause.get("target") == PLAYER_KEY else (
                    fact.get("actor_name") or j.cause.get("target", ""))
                out.append(rumours.departure("", dest, faction=j.cause.get("faction", ""),
                                             target=target, reason_fact=fact or None))
            elif j.resident and story is not None and story.enabled:
                lead = j.members[0] if j.members else {}
                row = story.justified_view(peek_actor_key(j.resident))
                if row and row.get("destination") == j.dest:
                    out.append(rumours.departure(lead.get("display", "Someone"), dest,
                                                 row.get("kind", ""), row.get("victim", "")))
            if len(out) >= limit:
                break
        return out

    def notices(self, place, limit: int = 4) -> List[str]:
        """What the watch has posted in *place*: reported crimes its residents
        know of, newest first. Only reported accounts are posted."""
        from ..sim import crime, knowledge, rumours
        from ..sim.director import peek_actor_key
        store = getattr(self.session, "store", None)
        if store is None or self.board is None or not place:
            return []
        best = {}
        for npc in self.session._things_of_type("npc"):
            p = npc.properties
            if p.get("dead") or p.get("_journey") or npc.pos is None:
                continue
            if self.board.nearest_place(npc.pos[0], npc.pos[2]) != place:
                continue
            for f in knowledge.facts_view(store, peek_actor_key(npc)):
                eid = int(f.get("e", 0) or 0)
                if (not eid or not f.get("reported") or not crime.is_crime(f)
                        or crime.settled(store, eid)):
                    continue
                if eid not in best or float(f.get("certainty", 0)) > float(best[eid].get("certainty", 0)):
                    best[eid] = f
        rows = sorted(best.values(), key=lambda f: (-int(f.get("day", 0)), -float(f.get("hour", 0.0)), -int(f["e"])))
        return [rumours.notice(f, self._place_label, self._today()) for f in rows[:limit]]

    def news_text(self, ids, place=None) -> str:
        lines = self.board.news_for(ids, 3) if ids else []
        if place and not lines:
            lines = self.board.news_at(place, 3)
        if not lines:
            return "Nothing worth the telling. Quiet roads, thank the gods."
        return "  ".join(lines)

    def prepare_tree(self, tree, npc):
        """Fill in what a conversation says about the world *now*: a
        traveller's news node, and for anyone else a 'news?' question
        answered with what has been heard in their town."""
        if not isinstance(tree, dict) or self.board is None:
            return tree
        import copy
        p = npc.properties
        nodes = tree.get("nodes") or {}
        jid = p.get("_journey")
        if jid and "news" in nodes:
            tree = copy.deepcopy(tree)
            j = self.board.journeys.get(jid)
            ids = j.news if j else []
            tree["nodes"]["news"]["text"] = self.news_text(ids)
            return tree
        if p.get("aggression") == "hostile" or jid:
            return tree
        place = self.board.nearest_place(npc.pos[0], npc.pos[2])
        if not place:
            return tree
        # What they themselves believe, who has set out from here and why,
        # then what travellers have brought: all of it already true.
        lines = [text for _e, text in self.rumours(npc, 2)] + self.departures(place, 1)
        if self.board.heard.get(place):
            lines += self.board.news_at(place, 2 if lines else 3)
        if not lines:
            return tree
        start = tree.get("start")
        if start not in nodes:
            return tree
        tree = copy.deepcopy(tree)
        tree["nodes"]["_town_news"] = {
            "text": "  ".join(lines),
            "responses": [{"text": "Interesting.", "goto": start}]}
        resp = tree["nodes"][start].setdefault("responses", [])
        at = max(0, len(resp) - 1)
        resp.insert(at, {"text": "Heard any news?", "goto": "_town_news"})
        return tree

    # ------------------------------------------------------------ quests
    def _maybe_offer_quest(self, j, things) -> None:
        """Now and then someone on the road has a job for the player."""
        s = self.session
        if j.hostile or j.quest is not None or s.rng.random() > 0.45:
            return
        giver = things[0]
        quest = (self._bounty_quest(j, giver) or self._remains_quest(j, giver)
                 or self._letter_quest(j, giver))
        if quest is None:
            j.quest = {}
            return
        j.quest = quest
        self._register(quest)
        tree, _ = rpg_quests.offer_dialogue_branch(giver.properties.get("dialogue"),
                                                   quest["id"], quest["name"],
                                                   quest["offer"])
        giver.properties["dialogue"] = tree

    def _bounty_quest(self, j, giver):
        gangs = [g for g in self.board.journeys.values()
                 if g.kind == "bandits" and g.alive() and g.state != "done"]
        gangs = [g for g in gangs if not any(m.get("wanted") for m in g.members)]
        if not gangs:
            return None
        s = self.session
        gang = s.rng.choice(gangs)
        chief = gang.leader()
        chief["wanted"] = True
        reward = s.rng.randint(80, 180)
        near = self.board.place_name(gang.dest)
        qid = f"rq_bounty_{gang.id}"
        return {"id": qid, "name": f"Bounty: {chief['display']}",
                "giver": giver.properties.get("name", ""),
                "offer": (f"{chief['display']} and his cutthroats have been working the road "
                          f"toward {near}. The watch pays {reward} gold for him. "
                          "Interested?"),
                "xp": 60, "rewards": {"gold": reward},
                "stages": [
                    {"index": 0, "journal": f"Hunt down the brigand {chief['display']}, last "
                                            f"heard of on the road toward {near}.",
                     "objective": f"Kill {chief['display']}",
                     "condition": {"kind": "kill", "target": chief["name"], "count": 1},
                     "waypoint": chief["name"]},
                    {"index": 10, "journal": f"{chief['display']} is dead. The bounty "
                                             "is paid.", "finishes": True}]}

    def _remains_quest(self, j, giver):
        lost = [r for r in self.board.remains if r.get("keepsake") and not r.get("quested")]
        if not lost or not rpg_items.get("adventurers_keepsake"):
            return None
        r = lost[-1]
        r["quested"] = True
        place = self.board.place_name(r.get("place")) if r.get("place") else "the wilds"
        qid = f"rq_remains_{_slug(r['name'])}"
        reward = 60 + int(r.get("gold", 0))
        return {"id": qid, "name": f"What Became of {r['name']}",
                "giver": giver.properties.get("name", ""),
                "offer": (f"{r['name']} went into {place} with a company of adventurers and "
                          "never came back. Bring me back something of theirs, so I know.")
                         , "xp": 50, "rewards": {"gold": reward},
                "stages": [
                    {"index": 0, "journal": f"Find what is left of {r['name']} at {place} "
                                            "and recover a keepsake.",
                     "objective": f"Recover {r['name']}'s keepsake",
                     "condition": {"kind": "fetch", "target": "adventurers_keepsake",
                                   "count": 1},
                     "waypoint": f"remains_{_slug(r['name'])}"},
                    {"index": 10, "journal": f"I found {r['name']}'s keepsake.",
                     "finishes": True}]}

    def _letter_quest(self, j, giver):
        if j.kind not in ("courier", "trader", "caravan", "pilgrims", "minstrel"):
            return None
        dest = j.dest
        folk = [t for rid, t in self._residents.items()
                if self.board.nearest_place(t.pos[0], t.pos[2]) == dest
                and not t.properties.get("dead")]
        if not folk:
            return None
        s = self.session
        who = s.rng.choice(folk)
        name = who.properties.get("display_name", who.properties.get("name"))
        qid = f"rq_letter_{j.id}"
        place = self.board.place_name(dest)
        return {"id": qid, "name": f"A Letter for {name}",
                "giver": giver.properties.get("name", ""),
                "offer": (f"You look like you could walk faster than me. There's word "
                          f"for {name} in {place}; tell them I'm on my way, would you? "
                          "They'll see you right."),
                "xp": 25, "rewards": {"gold": s.rng.randint(15, 40)},
                "stages": [
                    {"index": 0, "journal": f"Carry word to {name} in {place}.",
                     "objective": f"Speak to {name}",
                     "condition": {"kind": "talk", "target": who.properties.get("name", ""),
                                   "count": 1},
                     "waypoint": who.properties.get("name", "")},
                    {"index": 10, "journal": f"{name} has the message.", "finishes": True}]}

    def _register(self, quest) -> None:
        q = rpg_quests.quest_from_dict(quest)
        if q is None:
            return
        rpg_quests.register(q)
        if not any(d.get("id") == quest["id"] for d in self._quests_def):
            self._quests_def.append(quest)

    def _restore_quests(self) -> None:
        raw = self.session.store.get(QUEST_KEY, "")
        if not raw or raw == "false":
            return
        try:
            defs = json.loads(raw)
        except (TypeError, ValueError):
            return
        for d in defs if isinstance(defs, list) else []:
            self._register(d)

    def locate(self, target_slug):
        """Where a named traveller is, even while only a journey: for quest
        arrows that point at someone on the roads."""
        if self.board is None or not target_slug:
            return None
        t = _now_hours(self.session.clock)
        for j in self.board.journeys.values():
            if j.live:
                continue
            for m in j.alive():
                if _slug(m["name"]) == target_slug:
                    x, z = self._abstract_pos(j, t)
                    return [x, 0.0, z]
        for r in self.board.remains:
            if f"remains_{_slug(r['name'])}" == target_slug and not r.get("looted"):
                return [r["x"], 0.0, r["z"]]
        return None

    # -------------------------------------------------------- persistence
    def persist(self) -> None:
        if self.board is None:
            return
        self._persist_t = time.monotonic()
        # Live parties are saved where they stand.
        t = _now_hours(self.session.clock)
        for jid, entry in self.live.items():
            j = self.board.journeys.get(jid)
            alive = [x for x in entry["things"] if not x.properties.get("dead")]
            if j is not None and j.cause:
                for thing in entry["things"]:
                    m = j.members[thing.properties["_member"]]
                    m["alive"] = not bool(thing.properties.get("dead"))
                    m["health"] = float(thing.properties.get("health", m.get("health", 0)))
                    for key in ("inventory", "equipped_weapon", "alignment"):
                        if key in thing.properties:
                            m[key] = copy.deepcopy(thing.properties[key])
            if j is not None and j.state == "travel" and alive and len(j.route) >= 2:
                j.set_progress(roads.project(j.route, j.cum, alive[0].pos[0],
                                             alive[0].pos[2]), t)
        raw = self.board.to_json()
        # Live flags are a session matter: a loaded game rebuilds them.
        self.session.store.set(STORE_KEY, raw.replace('"live": true', '"live": false'))
        self.session.store.set(QUEST_KEY, json.dumps(self._quests_def))
        spine = getattr(self.session, "faction_spine", None)
        if spine is not None:
            spine.persist()

    def restore(self) -> None:
        """A save was loaded: every party back to data, then the saved board."""
        if self.board is None:
            return
        self.shutdown()
        raw = self.session.store.get(STORE_KEY, "")
        if raw and raw != "false":
            self.board.load_json(raw)
        for j in self.board.journeys.values():
            j.live = False
        self._restore_quests()

    # ------------------------------------------------------------ inspection
    def summary(self) -> List[str]:
        """Plain lines for the console: who is on the roads, and where."""
        if self.board is None:
            return ["The living world is not running on this map."]
        t = _now_hours(self.session.clock)
        out = [f"{len(self.board.journeys)} parties, {len(self.live)} near you; "
               f"roads: {self.board.network.stats()}"]
        for j in sorted(self.board.journeys.values(), key=lambda j: j.id):
            x, z = self._abstract_pos(j, t)
            lead = j.leader()
            out.append(f"{j.id:>5} {j.kind:<11} {lead['display'] if lead else '-':<26} "
                       f"{j.state:<6} {self.board.place_name(j.origin)} -> "
                       f"{self.board.place_name(j.dest)}  at ({x:.0f}, {z:.0f})"
                       + ("  [LIVE]" if j.live else ""))
        return out
