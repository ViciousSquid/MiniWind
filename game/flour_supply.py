"""Flour errands use ordinary people, purses, inventories and movement.

This is a work goal, below danger, testimony, companions and personal needs.
There are no guaranteed deliveries: a runner can flee, lose the cargo or die;
an empty mill or shop stays empty. Only the head of a physical FIFO queue can
buy from a mill, and the cargo reaches a shelf only on the return journey.
"""

from __future__ import annotations

import math

from .rpg import inventory, items, schedule, shops
from .windmills import FLOUR, delivery_point, item_stock, take_stock

DAWN = 5.0
SHOP_OPEN = 9.5
SERVICE_HOURS = 2.0 / 60.0
RETURN_BUFFER = 0.25
PERSONAL_TRIP_HOURS = 2.0
RUNNER_HOME = 22.0
LOCAL_RADIUS = 2500.0
REACH = 70.0
QUEUE_SPACING = 110.0
TOWN_MARKUP = 0.10
MEAL_HUNGER = 0.60
MEAL_RELIEF = 0.60

COLLECTING = "COLLECTING_FLOUR"
QUEUEING = "QUEUEING_FLOUR"
RETURNING = "RETURNING_FLOUR"
BUYING = "BUYING_FLOUR"
EATING = "EATING_FLOUR"
OPENING = "OPENING_SHOP"
WORK_STATES = {COLLECTING, QUEUEING, RETURNING, BUYING, EATING, OPENING}
BUSY_STATES = {"COMBAT", "FLEE", "RALLY", "ALERT", "REPORT", "CONFRONT",
               "ESCORT", "PURSUE", "SEARCH", "ARREST_APPROACH", "ARREST_READY"}

# The map remembers the finite stocks and errands, including a runner's actual
# position. Full saves already keep these ordinary properties automatically.
MEMORY_FIELDS = ("inventory", "stock", "merchant_gold", "gold", "flour_markup", "dead", "health",
                 "flour_dependent", "food_shop", "need_hunger", "need_fatigue",
                 "flour_job", "flour_day", "mill_progress", "mill_updated_at",
                 "flour_queue", "flour_service", "opening_day", "opening_hour")


def _id(actor):
    return str(actor.properties.get("flour_resident") or actor.properties.get("id") or "")


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _alive(actor):
    p = actor.properties
    if p.get("dead"):
        return False
    if p.get("away_on_journey") and p.get("_flour_abstract"):
        return True  # the board hides the resident while its road actor exists
    return not p.get("_bw_parked_disabled", p.get("disabled"))


def _present(actor):
    p = actor.properties
    if p.get("_flour_abstract"):
        return _alive(actor)
    return (_alive(actor) and not p.get("hidden") and not p.get("away_on_journey")
            and (not p.get("_journey") or p.get("flour_resident"))
            and p.get("_sim_tier", 0) < 3)


def _money(actor):
    key = "merchant_gold" if actor.properties.get("merchant") else "gold"
    return key, max(0, int(actor.properties.get(key, 0) or 0))


def shelf_price(shop) -> int:
    """The ordinary flour price plus this shelf's actual import cost."""
    return max(1, math.ceil(items.get(FLOUR).value *
                            (1.0 + float(shop.properties.get("flour_markup", 0.0)))))


class FlourSupply:
    def __init__(self, session):
        self.session = session
        self.actors = {}
        self.shops = {}
        self.roads = None

    def connect_roads(self, world):
        from .flour_roads import FlourRoads
        self.roads = world.flour_roads = FlourRoads(self, world)

    @property
    def now(self):
        clock = self.session.clock
        return float(clock.day) * 24.0 + float(clock.hour)

    def work(self, actor):
        return self.session._resolve_location(actor, "work")

    def install(self):
        self.actors = {_id(a): a for a in self.session._things_of_type("npc") if _id(a)}
        self.shops = {key: a for key, a in self.actors.items()
                      if a.properties.get("merchant")
                      and int(a.properties.get("flour_target", 0) or 0) > 0}
        for shop in self.shops.values():
            self.sync_shelf(shop)
        for actor in self.actors.values():
            p = actor.properties
            if p.get("faction") not in ("villagers", "guards") or not _alive(actor):
                continue
            home = self.session._resolve_location(actor, "home")
            local = [s for s in self.shops.values() if _distance(home, self.work(s)) <= LOCAL_RADIUS]
            if local:
                shop = min(local, key=lambda s: _distance(home, self.work(s)))
                p.setdefault("flour_dependent", True)
                p["food_shop"] = _id(shop)
                # A finite household purse, editable as ordinary NPC data.
                # Restocking never creates either flour or household coin.
                p.setdefault("gold", 30)

    def sync_shelf(self, shop):
        """The sale row is a view of the pack, never a second stock of flour."""
        p = shop.properties
        stock = p.get("stock")
        if not isinstance(stock, list):
            # Preserve the normal role's wares when opting into flour sales.
            stock = shops.stock_for(shop)
            p["stock"] = stock
        stock[:] = [row for row in stock if
                    (row.get("id") if isinstance(row, dict) else row) != FLOUR]
        stock.append({"id": FLOUR, "qty": item_stock(shop, FLOUR), "supply": "mill"})

    def refresh(self):
        for shop in self.shops.values():
            self.opening_hour(shop)
            self.sync_shelf(shop)
        for mill in self.session.windmills.bodies():
            self._clean_queue(mill)

    def _travel(self, actor, start, end):
        distance = _distance(start, end)
        graph = getattr(self.session, "_road_graph", None)
        if graph is not None:
            route = graph.plan((start[0], start[2]), (end[0], end[2]))
            if route:
                points = [(start[0], start[2]), *route, (end[0], end[2])]
                distance = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                               for a, b in zip(points, points[1:]))
        speed = max(1.0, float(actor.properties.get("move_speed", 90.0) or 90.0))
        # Allow for corners and pedestrian traffic; the actual walk remains
        # collision checked and can take longer, or fail altogether.
        return distance * 1.35 / speed * self.session.clock.hours_per_second

    def _fits(self, actor, source, home, deadline):
        travel = self._travel(actor, actor.pos, source) + self._travel(actor, source, home)
        return self.session.clock.hour + travel + SERVICE_HOURS + RETURN_BUFFER < deadline

    def opening_hour(self, shop):
        """One small daily delay, saved so waiting/reloading cannot reroll it."""
        p = shop.properties
        if p.get("opening_day") != self.session.clock.day:
            p["opening_day"] = self.session.clock.day
            delay = (self.session.rng.uniform(2.0, 15.0)
                     if self.session.rng.random() < 0.3 else 0.0)
            p["opening_hour"] = SHOP_OPEN + delay / 60.0
        return float(p["opening_hour"])

    def is_open(self, shop):
        if not _present(shop) or shop.properties.get("sched_state") in BUSY_STATES:
            return False
        hour = self.session.clock.hour
        entry = self.session._schedule_entry(shop)
        return (hour >= self.opening_hour(shop) and entry is not None
                and entry.get("state") == schedule.WORKING
                and _distance(shop.pos, self.work(shop)) <= REACH)

    def drive(self, actor, state):
        """Offer an interruptible errand after the runtime's urgent decisions."""
        p = actor.properties
        if not _present(actor) or p.get("follow_player") or state == schedule.SLEEPING:
            return False
        if self._meal(actor):
            return True
        if p.get("_need_reason"):
            return False
        job = p.get("flour_job")
        if isinstance(job, dict):
            return self._drive_job(actor, job)
        if _id(actor) not in self.shops:
            return False
        hour = self.session.clock.hour
        if SHOP_OPEN <= hour < self.opening_hour(actor):
            p["sched_state"] = OPENING
            p["_dest"] = self.work(actor)
            return True
        if DAWN <= hour < SHOP_OPEN and p.get("flour_day") != self.session.clock.day:
            if self._plan(actor):
                job = p.get("flour_job")
                if job:
                    return self._drive_job(actor, job)
        return False

    def _meal(self, actor, *, abstract=False):
        p = actor.properties
        if not p.get("flour_dependent") or float(p.get("need_hunger", 0)) < MEAL_HUNGER:
            p.pop("_food_reason", None)
            return False
        job = p.get("flour_job") or {}
        carried = item_stock(actor, FLOUR) - int(job.get("cargo", 0))
        if carried > 0:
            take_stock(actor, FLOUR, 1)
            p["need_hunger"] = max(0.0, float(p["need_hunger"]) - MEAL_RELIEF)
            p["sched_state"] = EATING
            p.pop("_need_reason", None)
            p.pop("_food_reason", None)
            p.pop("_dest", None)
            if _id(actor) in self.shops:
                self.sync_shelf(actor)
            return True
        shop = self.shops.get(p.get("food_shop"))
        key, money = _money(actor)
        if (shop is None or not self.is_open(shop) or not item_stock(shop, FLOUR)
                or money < shelf_price(shop)):
            home = self.session._resolve_location(actor, "home")
            alternatives = [s for s in self.shops.values()
                            if s is not actor and _distance(home, self.work(s)) <= LOCAL_RADIUS
                            and self.is_open(s) and item_stock(s, FLOUR)
                            and money >= shelf_price(s)]
            if alternatives:
                shop = min(alternatives, key=lambda s: _distance(actor.pos, s.pos))
                p["food_shop"] = _id(shop)
        if shop is None or not self.is_open(shop):
            p["_food_reason"] = "The local flour shop is closed."
            return False
        if not item_stock(shop, FLOUR):
            p["_food_reason"] = "The local shop has run out of flour."
            return False
        price = shelf_price(shop)
        if money < price:
            p["_food_reason"] = "Cannot afford flour."
            return False
        p["sched_state"] = BUYING
        p["_dest"] = list(shop.pos)
        if not abstract and _distance(actor.pos, shop.pos) > REACH:
            return True
        take_stock(shop, FLOUR, 1)
        inventory.add_item(inventory.get_inventory(actor), items.make(FLOUR))
        p[key] = money - price
        shop.properties["merchant_gold"] = _money(shop)[1] + price
        self.sync_shelf(shop)
        self._trade(actor, shop, 1, price)
        return self._meal(actor, abstract=abstract)

    def _plan(self, shop):
        p = shop.properties
        if item_stock(shop, FLOUR) >= int(p["flour_target"]):
            p["flour_day"] = self.session.clock.day
            return False
        if any((a.properties.get("flour_job") or {}).get("shop") == _id(shop)
               for a in self.actors.values() if _alive(a)):
            return False  # the earlier runner may still be bringing it home
        mill = self.session.windmills.nearest(self.work(shop))
        if mill is not None:
            door = delivery_point(mill)
            trip = self._travel(shop, shop.pos, door) + self._travel(shop, door, self.work(shop))
            if trip <= PERSONAL_TRIP_HOURS and self._fits(shop, door, self.work(shop), SHOP_OPEN):
                self._assign(shop, shop, mill, "mill")
                return True
            runners = [a for a in self.actors.values() if self._runner_free(a, shop)
                       and self._fits(a, door, self.work(shop), RUNNER_HOME)]
            if runners:
                runner = min(runners, key=lambda a: _distance(a.pos, self.work(shop)))
                self._assign(runner, shop, mill, "mill")
                return True
        # Buy finite stock from a closer town; no virtual import fills a shelf.
        towns = [s for s in self.shops.values() if s is not shop and _alive(s)
                 and item_stock(s, FLOUR) > max(1, int(s.properties["flour_target"]) // 2)
                 and _distance(self.work(s), self.work(shop)) > LOCAL_RADIUS
                 and self._fits(shop, self.work(s), self.work(shop), SHOP_OPEN)
                 and (mill is None or _distance(self.work(s), self.work(shop))
                      < _distance(delivery_point(mill), self.work(shop)))]
        if towns:
            supplier = min(towns, key=lambda s: _distance(shop.pos, self.work(s)))
            self._assign(shop, shop, supplier, "town")
            return True
        p["_supply_reason"] = "No collection route fits before opening; awaiting a supplier."
        return False

    def _runner_free(self, runner, shop):
        p = runner.properties
        if not (p.get("flour_runner") and _present(runner)):
            return False
        if (p.get("flour_job") or p.get("follow_player") or p.get("merchant")
                or p.get("_need_reason") or p.get("_sim_reason")
                or p.get("sched_state") in BUSY_STATES
                or p.get("faction") != shop.properties.get("faction")):
            return False
        entry = self.session._schedule_entry(runner)
        return (entry is not None and entry.get("state") == schedule.IDLE
                and float(p.get("need_hunger", 0)) < MEAL_HUNGER
                and float(p.get("need_fatigue", 0)) < 0.9
                and _distance(runner.pos, self.work(shop)) <= LOCAL_RADIUS)

    def _assign(self, carrier, shop, source, kind):
        carrier.properties["flour_job"] = dict(
            shop=_id(shop), source=_id(source), kind=kind, phase="collect",
            cargo=0, day=self.session.clock.day, markup=0.0)
        shop.properties["flour_day"] = self.session.clock.day
        shop.properties["_supply_reason"] = (
            "Collecting flour." if carrier is shop else
            f"Sent {carrier.properties.get('display_name') or carrier.properties.get('name')} for flour.")

    def _drive_job(self, carrier, job):
        shop = self.shops.get(job.get("shop"))
        if shop is None or not _alive(shop):
            self._cancel(carrier)  # surviving cargo remains in its real pack
            return False
        if job.get("phase") == "return":
            return self._return(carrier, shop, job)
        source = (self.session.windmills.find(job.get("source")) if job.get("kind") == "mill"
                  else self.shops.get(job.get("source")))
        deadline = SHOP_OPEN if carrier is shop else RUNNER_HOME
        if (source is None or not _alive(source)
                or self.session.clock.hour + self._travel(carrier, carrier.pos, self.work(shop))
                + RETURN_BUFFER + SERVICE_HOURS >= deadline):
            self._leave_queue(carrier)
            job["phase"] = "return"
            return self._return(carrier, shop, job)
        if job.get("kind") == "mill":
            return self._queue(carrier, shop, source, job)
        carrier.properties["sched_state"] = COLLECTING
        carrier.properties["_dest"] = self.work(source)
        # Morning wholesale trade is possible before retail opening, but the
        # supplier still has to be physically present and free to serve.
        if (_distance(carrier.pos, source.pos) <= REACH and _present(source)
                and _distance(source.pos, self.work(source)) <= REACH
                and source.properties.get("sched_state") not in BUSY_STATES):
            self._collect(carrier, shop, source, job)
            job["phase"] = "return"
            return self._return(carrier, shop, job)
        return True

    def _clean_queue(self, mill):
        queue = mill.properties.setdefault("flour_queue", [])
        valid = []
        for key in queue:
            actor = self.actors.get(key)
            if actor is None or key in valid or not _present(actor):
                continue
            p = actor.properties
            job = p.get("flour_job") or {}
            if (job.get("source") == _id(mill) and job.get("phase") == "collect"
                    and p.get("sched_state") == QUEUEING
                    and _distance(actor.pos, delivery_point(mill)) <= 400 + len(queue) * QUEUE_SPACING):
                valid.append(key)
        queue[:] = valid
        service = mill.properties.get("flour_service") or {}
        if not queue or service.get("actor") != queue[0]:
            mill.properties.pop("flour_service", None)
        return queue

    def _leave_queue(self, actor):
        for mill in self.session.windmills.bodies():
            queue = mill.properties.get("flour_queue", [])
            if _id(actor) in queue:
                queue.remove(_id(actor))
            service = mill.properties.get("flour_service") or {}
            if service.get("actor") == _id(actor):
                mill.properties.pop("flour_service", None)

    def _queue(self, carrier, shop, mill, job):
        p = carrier.properties
        p["sched_state"] = QUEUEING
        door = delivery_point(mill)
        queue = self._clean_queue(mill)
        if _distance(carrier.pos, door) <= 300 + len(queue) * QUEUE_SPACING:
            if _id(carrier) not in queue:
                queue.append(_id(carrier))
        if _id(carrier) not in queue:
            p["sched_state"] = COLLECTING
            p["_dest"] = door
            return True
        index = queue.index(_id(carrier))
        dx, dz = door[0] - mill.pos[0], door[2] - mill.pos[2]
        length = math.hypot(dx, dz) or 1.0
        point = [door[0] + dx / length * QUEUE_SPACING * index, carrier.pos[1],
                 door[2] + dz / length * QUEUE_SPACING * index]
        p["_dest"] = point
        if index or _distance(carrier.pos, point) > REACH:
            return True
        service = mill.properties.get("flour_service")
        if not service or service.get("actor") != _id(carrier):
            mill.properties["flour_service"] = dict(actor=_id(carrier), since=self.now)
            return True
        if self.now - float(service["since"]) + 1e-9 < SERVICE_HOURS:
            return True
        if not item_stock(mill, FLOUR) and _money(shop)[1] >= items.get(FLOUR).value:
            shop.properties["_supply_reason"] = "Waiting for the mill to finish its next batch."
            return True
        self._collect(carrier, shop, mill, job)
        self._leave_queue(carrier)
        job["phase"] = "return"
        return self._return(carrier, shop, job)

    def _collect(self, carrier, shop, source, job):
        missing = max(0, int(shop.properties["flour_target"]) - item_stock(shop, FLOUR))
        price = shelf_price(source) if job["kind"] == "town" else items.get(FLOUR).value
        available = item_stock(source, FLOUR)
        if job["kind"] == "town":
            available = max(0, available - max(1, int(source.properties["flour_target"]) // 2))
        key, money = _money(shop)
        amount = min(missing, available, money // price)
        if not amount:
            shop.properties["_supply_reason"] = "No flour collected: stock or coin ran short."
            return
        take_stock(source, FLOUR, amount)
        inventory.add_item(inventory.get_inventory(carrier), items.make(FLOUR, amount))
        shop.properties[key] = money - amount * price
        if job["kind"] == "town":
            source.properties["merchant_gold"] = _money(source)[1] + amount * price
            job["markup"] = float(source.properties.get("flour_markup", 0)) + TOWN_MARKUP
            self.sync_shelf(source)
        else:
            inventory.add_item(inventory.get_inventory(source), items.make("gold", amount * price))
        job["cargo"] = amount
        self._trade(carrier, source, amount, amount * price)

    def _return(self, carrier, shop, job):
        p = carrier.properties
        p["sched_state"] = RETURNING
        p["_dest"] = self.work(shop)
        if _distance(carrier.pos, self.work(shop)) > REACH:
            return True
        if carrier is not shop and (not _present(shop) or _distance(carrier.pos, shop.pos) > REACH):
            return True
        # Missing cargo was lost on the road, not replenished at the shop door.
        amount = min(int(job.get("cargo", 0)), item_stock(carrier, FLOUR))
        old = item_stock(shop, FLOUR) - (amount if carrier is shop else 0)
        if carrier is not shop:
            take_stock(carrier, FLOUR, amount)
            if amount:
                inventory.add_item(inventory.get_inventory(shop), items.make(FLOUR, amount))
        if old + amount:
            shop.properties["flour_markup"] = (
                old * float(shop.properties.get("flour_markup", 0))
                + amount * float(job.get("markup", 0))) / (old + amount)
        self.sync_shelf(shop)
        p.pop("flour_job", None)
        p.pop("_dest", None)
        shop.properties["_supply_reason"] = f"Received {amount} flour." if amount else "No flour arrived."
        return False

    def _cancel(self, actor):
        self._leave_queue(actor)
        actor.properties.pop("flour_job", None)

    def _trade(self, buyer, seller, quantity, gold):
        self.session.director.emit("trade", actor=buyer, target=seller,
                                   pos=buyer.pos,
                                   data={"item": FLOUR, "quantity": quantity, "gold": gold},
                                   observers=self.session._sim_observers())
