"""Flour stays finite through the existing road board and its live actors."""

import json
import random

import pytest

pytest.importorskip('PyQt5')

from ..entities import Marker
from ..flour_supply import MEAL_HUNGER, QUEUEING, SERVICE_HOURS
from ..living import journeys
from ..living.world import LivingWorld
from ..rpg import inventory
from ..windmills import item_stock
from .test_flour_supply import _reindex, _resident, _shop, _stock, supply as supply
from .test_windmills import logic as logic

pytestmark = pytest.mark.qt


def _park(actor):
    actor.properties.update(_bw_parked_hidden=False, _bw_parked_disabled=False,
                             hidden=True, disabled=True, _sim_tier=3)


@pytest.fixture
def roads(supply):
    session, mill, shop, buyer = supply
    _resident(session.logic, 'miller', pos=mill.pos)
    for name, pos in [('Town', shop.pos), ('Windmill', mill.pos)]:
        session.logic.editor_state.things.append(Marker(pos=list(pos), properties={
            'name': 'loc_' + name, 'marker_kind': 'location', 'place_name': name,
            'discover_radius': 900}))
    _reindex(session)
    world = session.living = LivingWorld(session, population=0)
    assert world.build()
    session.flour_supply.connect_roads(world)
    for actor in session.flour_supply.actors.values():
        _park(actor)
    _park(mill)
    try:
        yield session, world, mill, shop, buyer
    finally:
        world.shutdown()


def _step(session, world, hour):
    session.clock.set_time(hour)
    world.flour_roads.tick()
    world.board.update(session.flour_supply.now)


def _delivery(world):
    return next(j for j in world.board.journeys.values() if world.flour_roads.handles(j))


def test_parked_shops_use_the_existing_board_and_deliver_paid_stock_without_loading_cells(roads):
    session, world, mill, shop, _ = roads
    _stock(mill, 5)
    assert session.windmills.find(mill.properties['id']) is mill
    _step(session, world, 5.0)
    j = _delivery(world)
    assert j.kind == 'courier' and j.resident == shop.properties['id']
    assert world.board.residents_on_trips[j.resident] == j.id and not world.live
    _step(session, world, 6.0)
    assert j.state == 'rest' and shop.properties['sched_state'] == QUEUEING
    _step(session, world, 6.0 + SERVICE_HOURS)
    assert j.state == 'travel' and item_stock(shop, 'flour') == 3
    assert item_stock(mill, 'flour') == 2 and item_stock(mill, 'gold') == 30
    _step(session, world, 7.0)
    _step(session, world, 7.01)
    assert 'away_on_journey' not in shop.properties and 'flour_job' not in shop.properties
    assert item_stock(shop, 'flour') == 3 and not world.live
    assert shop.properties['disabled']  # the cell was never forced to load


def test_the_same_fifo_and_service_delay_apply_to_offscreen_arrivals(roads):
    session, world, mill, shop, _ = roads
    other = _shop(session.logic, 'second grocer', pos=(100, 50, 0))
    _reindex(session)
    # Rebind the ordinary registry after adding this authored resident.
    world._index_scene(list(session.logic.editor_state.things))
    session.flour_supply.connect_roads(world)
    for actor in session.flour_supply.actors.values():
        _park(actor)
    _stock(mill, 10)
    _step(session, world, 5.0)
    _step(session, world, 6.0)
    assert len(mill.properties['flour_queue']) == 2
    _step(session, world, 6.0 + SERVICE_HOURS)
    assert sum(item_stock(a, 'flour') for a in (shop, other)) == 3
    _step(session, world, 6.05)
    _step(session, world, 6.10)
    assert sum(item_stock(a, 'flour') for a in (shop, other)) == 6
    assert item_stock(mill, 'flour') == 4


def test_cargo_survives_live_materialisation_dematerialisation_and_board_save_load(roads):
    session, world, mill, shop, _ = roads
    _stock(mill, 3)
    _step(session, world, 5.0)
    j = _delivery(world)
    world._spawn(j, session.flour_supply.now)
    proxy = world.live[j.id]['things'][0]
    assert proxy.properties['flour_resident'] == shop.properties['id']
    assert proxy.properties['id'] != shop.properties['id']
    world._drive(j.id)
    session._move(proxy, 60.0)
    world._drive(j.id)
    assert proxy.properties['sched_state'] == QUEUEING
    session.clock.advance(SERVICE_HOURS / session.clock.hours_per_second)
    world._drive(j.id)
    assert item_stock(proxy, 'flour') == 3
    world.persist()
    saved = json.loads(session.store.get('living.board'))
    row = next(x for x in saved['journeys'] if x['id'] == j.id)
    assert not row.get('live')
    assert sum(s['qty'] for s in row['members'][0]['inventory'] if s['id'] == 'flour') == 3
    world._despawn(j.id, j)
    assert proxy not in session.logic.editor_state.things
    assert session.flour_supply.shops[j.resident] is shop
    assert item_stock(shop, 'flour') == 3 and item_stock(mill, 'flour') == 0
    world.board.load_json(json.dumps(saved))
    _step(session, world, 7.0)
    _step(session, world, 7.01)
    assert item_stock(shop, 'flour') == 3 and 'away_on_journey' not in shop.properties


def test_offscreen_robbery_moves_the_flour_to_the_robbers_and_the_town_goes_hungry(roads):
    session, world, mill, shop, buyer = roads
    _stock(mill, 3)
    _step(session, world, 5.0)
    _step(session, world, 6.0)
    _step(session, world, 6.0 + SERVICE_HOURS)
    courier = _delivery(world)
    bandit = dict(name='robber', display='The Robber', role='bandit',
                  alive=True, health=10**6, damage=10**6, gold=0)
    gang = journeys.Journey('test-bandits', 'bandits', [bandit], courier.origin,
                             courier.dest, courier.route, session.flour_supply.now,
                             courier.speed, 1, courier.home)
    world.board.rng = random.Random(1)  # wins, takes goods, leaves the courier alive
    made = []
    world.board._clash(gang, courier, session.flour_supply.now, (1000, 0), made)
    assert item_stock(courier.members[0], 'flour') == 0
    assert item_stock(bandit, 'flour') == 3 and made
    _step(session, world, 7.0)
    _step(session, world, 7.01)
    assert item_stock(shop, 'flour') == 0
    buyer.properties['need_hunger'] = 0.95
    _step(session, world, 10.0)
    assert buyer.properties['need_hunger'] >= 0.95
    # Recoverable goods: when the brigand is materialised it carries the same flour.
    props = world._actor_props(gang, bandit, 0)
    assert sum(s['qty'] for s in props['inventory'] if s['id'] == 'flour') == 3
    assert any(s['id'] == props['equipped_weapon'] for s in props['inventory'])
    assert sum(s['qty'] for s in props['inventory'] if s['id'] == 'gold') == bandit['gold']


def test_a_slain_abstract_courier_leaves_flour_in_one_lootable_sack(roads):
    session, world, mill, shop, _ = roads
    _stock(mill, 3)
    _step(session, world, 5.0)
    _step(session, world, 6.0)
    _step(session, world, 6.0 + SERVICE_HOURS)
    j = _delivery(world)
    world.board._kill(j.members[0], j, session.flour_supply.now, where=(1000, 0))
    remains = world.board.remains[-1]
    assert sum(s['qty'] for s in remains['inventory'] if s['id'] == 'flour') == 3
    _step(session, world, 7.0)
    assert shop.properties['dead'] and item_stock(shop, 'flour') == 0
    sack = world._remains_container(remains)
    assert item_stock(sack, 'flour') == 3


def test_parked_residents_buy_and_consume_from_the_same_local_shelf(roads):
    session, world, _mill, shop, buyer = roads
    _stock(shop, 2)
    buyer.properties['need_hunger'] = MEAL_HUNGER
    _step(session, world, 10.0)
    assert buyer.properties['gold'] == 20
    assert buyer.properties['need_hunger'] < MEAL_HUNGER
    assert item_stock(shop, 'flour') == 1
