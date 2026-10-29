"""Hand flour errands to MiniWind's existing journey board outside view.

The board owns distant movement, encounters, materialisation and persistence.
This adapter supplies only the errand's cargo, mill stop and return destination.
Local meals are resolved arithmetically for parked residents, like the existing
daily settlement resolver; live residents still walk to their shopkeeper.
"""

from __future__ import annotations

import copy

from .flour_supply import (DAWN, MEAL_HUNGER, MEMORY_FIELDS, QUEUEING, SHOP_OPEN,
                            _alive, _id, _money)
from .living import journeys, roads
from .rpg import inventory, items, needs, schedule
from .windmills import FLOUR, delivery_point, item_stock, take_stock

STATE_FIELDS = (*MEMORY_FIELDS, 'sched_state', 'loot_rolled', 'living_inventory')


def _parked(actor):
    p = actor.properties
    return '_bw_parked_hidden' in p or p.get('_sim_tier', 0) >= 3


class FlourRoads:
    def __init__(self, supply, world):
        self.supply = supply
        self.world = world
        self.session = supply.session
        self.residents = dict(supply.actors)
        for j in world.board.journeys.values():
            if self.handles(j):
                self._restore(j)

    @staticmethod
    def handles(journey):
        return bool(journey.members and journey.members[0].get('flour_errand'))

    def _remember(self, j, actor):
        p, m = actor.properties, j.members[0]
        m['flour_state'] = {k: copy.deepcopy(p[k]) for k in STATE_FIELDS
                            if k in p and k != 'inventory'}
        m['inventory'] = copy.deepcopy(inventory.get_inventory(actor))
        m['alive'] = not p.get('dead', False)
        m['health'] = float(p.get('health', 60))
        m['gold'] = _money(actor)[1]
        m['flour_pos'] = [float(actor.pos[0]), float(actor.pos[2])]
        m['flour_y'] = float(actor.pos[1])

    def _restore(self, j):
        real = self.residents.get(j.resident)
        if real is None:
            return None
        p, m = real.properties, j.members[0]
        state = m.get('flour_state', {})
        for key in STATE_FIELDS:
            if key == 'inventory':
                continue
            if key in state:
                p[key] = copy.deepcopy(state[key])
            else:
                p.pop(key, None)
        p['inventory'] = copy.deepcopy(m.get('inventory', []))
        p['health'] = float(m.get('health', p.get('health', 60)))
        if not m.get('alive', True):
            p.update(dead=True, health=0)
        key, _ = _money(real)
        p[key] = int(m.get('gold', 0))
        p['away_on_journey'] = j.id
        p['_flour_abstract'] = True
        x, z = m.get('flour_pos', j.route[-1])
        real.pos = [x, float(m.get('flour_y', real.pos[1])), z]
        return real

    def _route(self, j, actor, destination):
        start, end = (actor.pos[0], actor.pos[2]), (destination[0], destination[2])
        graph = getattr(self.session, '_road_graph', None)
        path = graph.plan(start, end) if graph is not None else None
        j.route = [start, *(path or ()), end]
        j.cum = roads.cumulative(j.route)
        j.origin = self.world.board.nearest_place(*start) or j.home
        j.dest = self.world.board.nearest_place(*end) or j.home
        j.depart_t = self.supply.now
        j.state = 'travel'
        j.fought = []

    def _destination(self, actor):
        job = actor.properties.get('flour_job') or {}
        shop = self.supply.shops.get(job.get('shop'))
        if job.get('phase') == 'return':
            return self.supply.work(shop) if shop is not None else list(actor.pos)
        source = (self.session.windmills.find(job.get('source')) if job.get('kind') == 'mill'
                  else self.supply.shops.get(job.get('source')))
        if source is None:
            return list(actor.pos)
        return delivery_point(source) if job.get('kind') == 'mill' else self.supply.work(source)

    def _start(self, actor):
        board = self.world.board
        rid = _id(actor)
        home = board.nearest_place(actor.pos[0], actor.pos[2])
        if home is None or self.session.clock.hours_per_second <= 0:
            return
        key = f'j{board.next_id}'
        board.next_id += 1
        p = actor.properties
        member = dict(flour_errand=True, resident=rid, role='courier',
                      name=p.get('name', rid), display=p.get('display_name') or p.get('name', rid),
                      max_health=p.get('max_health', 60), damage=p.get('damage', 5),
                      style='melee', head=p.get('head', ''))
        j = journeys.Journey(key, 'courier', [member], home, home, [], self.supply.now,
                             float(p.get('move_speed', 90) or 90) / self.session.clock.hours_per_second,
                             1, home)
        j.resident = rid
        self._route(j, actor, self._destination(actor))
        self._remember(j, actor)
        board.journeys[key] = j
        board.residents_on_trips[rid] = key
        board.hooks.resident_left(rid, j)
        p['_flour_abstract'] = True

    def _needs(self, actor):
        p = actor.properties
        now = self.supply.now
        last = float(p.get('_flour_need_at', p.get('_need_t', now)))
        p['_flour_need_at'] = p['_need_t'] = now
        needs.seed(p, self.session.rng)
        needs.advance(p, max(0.0, now - last), p.get('sched_state', schedule.IDLE))

    def tick(self):
        now = self.supply.now
        # Distant errands belong to the board; never move a parked scene actor
        # frame by frame or force its cell to remain loaded.
        for j in list(self.world.board.journeys.values()):
            if not self.handles(j) or j.live:
                continue
            actor = self._restore(j)
            if actor is None or not _alive(actor):
                continue
            if j.state == 'travel':
                x, z = j.position_at(now)
                actor.pos = [x, actor.pos[1], z]
            self._needs(actor)
            if float(actor.properties.get('need_fatigue', 0)) >= needs.HIGH_FATIGUE:
                actor.properties['sched_state'] = schedule.SLEEPING
                j.state, j.rest_until = 'rest', now + 0.25
            self._remember(j, actor)
        # Parked towns still eat from the same finite local shelves. They do
        # not perform perception or pathfinding while outside the active area.
        for actor in self.residents.values():
            p = actor.properties
            if p.get('away_on_journey'):
                continue
            p['_flour_abstract'] = _parked(actor)
            if not _parked(actor) or not _alive(actor):
                continue
            if not (p.get('flour_dependent') or p.get('flour_target') or p.get('flour_runner')):
                continue
            entry = self.session._schedule_entry(actor)
            state = entry.get('state', schedule.IDLE) if entry else schedule.IDLE
            self._needs(actor)
            p['sched_state'] = state
            if p.get('flour_target') and state == schedule.WORKING and not p.get('flour_job'):
                actor.pos = self.supply.work(actor)
            if state != schedule.SLEEPING:
                self.supply._meal(actor, abstract=True)
            if (p.get('flour_target') and DAWN <= self.session.clock.hour < SHOP_OPEN
                    and state != schedule.SLEEPING and not p.get('flour_job')
                    and p.get('flour_day') != self.session.clock.day
                    and float(p.get('need_fatigue', 0)) < needs.HIGH_FATIGUE
                    and float(p.get('need_hunger', 0)) < needs.HIGH_HUNGER):
                self.supply._plan(actor)
        for actor in self.residents.values():
            if (_parked(actor) and _alive(actor) and actor.properties.get('flour_job')
                    and not actor.properties.get('away_on_journey')):
                self._start(actor)

    def arrive(self, j, _time):
        if not self.handles(j):
            return False
        actor = self._restore(j)
        if actor is None or not j.alive():
            j.state = 'done'
            return True
        p = actor.properties
        if float(p.get('need_fatigue', 0)) >= needs.HIGH_FATIGUE:
            p['sched_state'] = schedule.SLEEPING
            j.state, j.rest_until = 'rest', self.supply.now + 0.25
            self._remember(j, actor)
            return True
        # Arrival and queue spacing are coarse outside view; quantities, money
        # and service timestamps go through the same transaction as live NPCs.
        if j.state == 'rest':
            point = (p.get('_dest') if p.get('sched_state') == QUEUEING else None) or list(actor.pos)
        else:
            point = [j.route[-1][0], actor.pos[1], j.route[-1][1]]
        actor.pos = [point[0], actor.pos[1], point[2]]
        before = (p.get('flour_job') or {}).get('phase')
        job = p.get('flour_job')
        if job:
            self.supply._drive_job(actor, job)
        if not p.get('flour_job'):
            j.state = 'done'
        elif p['flour_job']['phase'] != before or p.get('sched_state') != QUEUEING:
            self._route(j, actor, self._destination(actor))
        else:
            j.state, j.rest_until = 'rest', self.supply.now + 1.0 / 60.0
        self._remember(j, actor)
        return True

    def actor_props(self, j):
        real = self.residents[j.resident]
        p, m = real.properties, j.members[0]
        props = copy.deepcopy(m.get('flour_state', {}))
        props['inventory'] = copy.deepcopy(m.get('inventory', []))
        for key in ('schedule', 'home', 'work_location', 'npc_role', 'merchant',
                    'flour_target', 'flour_runner', 'autonomy', 'combatant'):
            if key in p:
                props[key] = copy.deepcopy(p[key])
        props['flour_resident'] = j.resident
        return props

    def bind(self, j, actor):
        self.supply.actors[j.resident] = actor
        if j.resident in self.supply.shops:
            self.supply.shops[j.resident] = actor

    def unbind(self, j, actor):
        self._remember(j, actor)
        real = self._restore(j)
        if real is not None:
            self.supply.actors[j.resident] = real
            if j.resident in self.supply.shops:
                self.supply.shops[j.resident] = real

    def sync_live(self):
        for jid, entry in self.world.live.items():
            j = self.world.board.journeys.get(jid)
            if j is not None and self.handles(j):
                actor = entry['things'][0]
                self._remember(j, actor)
                self._restore(j)

    def drive(self, j, actor):
        actor.properties['_flour_driving'] = True
        try:
            self.session._decide(actor)
        finally:
            actor.properties.pop('_flour_driving', None)
        self._remember(j, actor)
        if not actor.properties.get('flour_job') or actor.properties.get('dead'):
            j.state = 'done'
            self.world._despawn(j.id, j)
            self.world.board._retire(j)
        elif actor.properties.get('sched_state') == QUEUEING:
            j.state = 'rest'
        else:
            # Rebase at the actual position when handing back to abstraction;
            # fleeing or being delayed must never advance a scheduled journey.
            destination = actor.properties.get('_dest') or self._destination(actor)
            self._route(j, actor, destination)

    def home(self, j, alive):
        real = self._restore(j)
        if real is None:
            return
        real.properties.pop('away_on_journey', None)
        real.properties.pop('_flour_abstract', None)
        if not alive:
            real.properties.update(dead=True, health=0)
            real.properties.pop('flour_job', None)
        self.world.set_hidden(real, False)

    def robbed(self, loser, winner):
        if not self.handles(loser) or not winner.alive():
            return
        recipient = winner.alive()[0]
        for member in loser.alive():
            amount = item_stock(member, FLOUR)
            take_stock(member, FLOUR, amount)
            if amount:
                if 'inventory' not in recipient:
                    recipient['inventory'] = []
                    recipient['cargo_only'] = True
                inventory.add_item(recipient.setdefault('inventory', []), items.make(FLOUR, amount))
