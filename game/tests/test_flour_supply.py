"""The real wheat → mill → road → shelf → meal chain, including disruptions."""

import copy
import json
import random

import pytest

pytest.importorskip('PyQt5')

from engine.player import Player
from .. import farm_work
from ..entities import NPC
from ..flour_supply import (BUYING, COLLECTING, EATING, OPENING, QUEUEING, RETURNING,
                            SERVICE_HOURS, SHOP_OPEN, shelf_price)
from ..map_memory import MapMemory
from ..rpg import daily, inventory, items, needs
from ..runtime import MiniwindSession
from ..windmills import delivery_point, item_stock, mill_flour, wheat_stock
from .test_windmills import ROOT, _pair, logic as logic
from .test_farm_work import Field

pytestmark = pytest.mark.qt

PLAN = [{'hour': 5.0, 'state': 'IDLE', 'location': 'home'},
        {'hour': 9.5, 'state': 'WORKING', 'location': 'work'},
        {'hour': 19.0, 'state': 'GOING_HOME', 'location': 'home'},
        {'hour': 22.0, 'state': 'SLEEPING', 'location': 'home'}]


def _shop(logic, name='grocer', pos=(0, 50, 0), target=3):
    actor = NPC(pos=list(pos), properties={
        'name': name, 'npc_role': 'merchant', 'merchant': True,
        'home': list(pos), 'work_location': list(pos), 'schedule': copy.deepcopy(PLAN),
        'inventory': [], 'stock': ['torch'], 'flour_target': target,
        'merchant_gold': 200, 'merchant_gold_base': 200, 'gold': 30,
        'need_hunger': 0.0, 'need_fatigue': 0.0, 'autonomy': False,
        'opening_day': 1, 'opening_hour': SHOP_OPEN})
    logic.editor_state.things.append(actor)
    return actor


def _resident(logic, name='resident', pos=(500, 50, 0), **props):
    actor = NPC(pos=list(pos), properties={
        'name': name, 'npc_role': 'villager', 'home': list(pos),
        'work_location': list(pos), 'schedule': copy.deepcopy(PLAN),
        'inventory': [], 'gold': 30, 'autonomy': False,
        'need_hunger': 0.0, 'need_fatigue': 0.0, **props})
    logic.editor_state.things.append(actor)
    return actor


def _reindex(session):
    session.logic.world_runtime.build_entity_caches()
    session.flour_supply.install()


@pytest.fixture
def supply(logic):
    mill, _rotor = _pair(logic, producing=False, pos=(2000, 0, 0))
    shop = _shop(logic)
    buyer = _resident(logic)
    logic.player_runtime.player = Player(-10000, -10000)
    logic.world_runtime.build_entity_caches()
    session = MiniwindSession(logic, cfg={'start_hour': 5.0})
    session.clock.set_time(5.0, 1)
    session.rng.seed(15)
    session.windmills.install()
    session.flour_supply.install()
    try:
        yield session, mill, shop, buyer
    finally:
        session.windmills.clear()


def _stock(actor, quantity, item='flour'):
    inventory.add_item(inventory.get_inventory(actor), items.make(item, quantity))


def _join(session, mill, shop):
    session._decide(shop)
    assert shop.properties['flour_job']['phase'] == 'collect'
    session._move(shop, 600.0)
    session._decide(shop)
    assert shop.properties['sched_state'] == QUEUEING


def _serve(session, mill, shop):
    session.clock.advance(SERVICE_HOURS / session.clock.hours_per_second)
    session._decide(shop)
    assert shop.properties['flour_job']['phase'] == 'return'


def test_milling_consumes_exactly_ten_wheat_across_stacks_and_keeps_remainders(supply):
    session, mill, *_ = supply
    mill.properties['inventory'] = [items.make('wheat', 6), items.make('wheat', 25), items.make('milk')]
    assert mill_flour(mill, 0.24) == 0
    assert mill_flour(mill, 0.01) == 1
    assert wheat_stock(mill) == 21 and item_stock(mill, 'flour') == 1
    assert mill_flour(mill, 0.50) == 2
    assert wheat_stock(mill) == 1 and item_stock(mill, 'flour') == 3
    assert item_stock(mill, 'milk') == 1
    assert mill_flour(mill, 100.0) == 0
    session.windmills.update(3.0)  # the earlier wheat-in-stock sail rule still holds
    assert session.windmills.mills[0].motion.speed > 0


def test_harvest_delivery_milling_collection_sale_and_meal_conserve_the_whole_supply(supply):
    session, mill, shop, buyer = supply
    farmer = _resident(session.logic, 'farmer', pos=(1500, 50, 0), npc_role='farmer',
                       schedule=[{'hour': 0, 'state': 'WORKING', 'location': 'work'}],
                       inventory=[items.make('scythe')],
                       _farm_rows=[[1400.0, 0.0], [1600.0, 0.0]],
                       _farm_task={'kind': 'reap', 'since': 31.0, 'until': 33.0})
    _reindex(session)
    session.clock.set_time(7.0)
    for _load in range(2):
        session._decide(farmer)
        assert farmer.properties['sched_state'] == farm_work.REAPING
        for _swing in range(5):
            session.farm_work.update(farm_work.SWING_EVERY, [farmer], Field())
        session._decide(farmer)
        assert farmer.properties['sched_state'] == farm_work.DELIVERING
        session._move(farmer, 60.0)
        session._decide(farmer)
    assert wheat_stock(mill) == 10 and wheat_stock(farmer) == 0
    session.windmills.produce(0.25)
    assert wheat_stock(mill) == 0 and item_stock(mill, 'flour') == 1
    _join(session, mill, shop)
    _serve(session, mill, shop)
    session._move(shop, 60.0)
    session._decide(shop)
    session.clock.set_time(10.0)
    session._decide(shop)
    buyer.properties['need_hunger'] = 0.9
    session._decide(buyer)
    session._move(buyer, 60.0)
    session._decide(buyer)
    assert buyer.properties['need_hunger'] == pytest.approx(0.3)
    assert sum(item_stock(a, 'flour') for a in (mill, farmer, shop, buyer)) == 0
    assert shop.properties['merchant_gold'] == 200
    assert buyer.properties['gold'] == 20 and item_stock(mill, 'gold') == 10


def test_milling_obeys_disabled_and_paused_time_and_the_last_batch_coasts_down(supply):
    session, mill, *_ = supply
    _stock(mill, 10, 'wheat')
    mill.properties['disabled'] = True
    assert mill_flour(mill, 3.0) == 0 and wheat_stock(mill) == 10
    mill.properties['disabled'] = False
    session.clock.paused = True
    session.tick(15.0)
    assert wheat_stock(mill) == 10
    session.clock.paused = False
    session.windmills.update(3.0)
    session.tick(15.0)
    assert item_stock(mill, 'flour') == 1 and wheat_stock(mill) == 0
    session.windmills.update(3.0)
    assert session.windmills.mills[0].motion.speed == 0


def test_waiting_until_morning_includes_milling_time_without_repeating_a_saved_batch(supply):
    session, mill, *_ = supply
    _stock(mill, 25, 'wheat')
    session.windmills.produce_until(29.0)
    session.windmills.produce_until(29.1)
    assert item_stock(mill, 'flour') == 0
    session.windmills.produce_until(32.0)  # sleep or wait advances the calendar
    assert item_stock(mill, 'flour') == 2 and wheat_stock(mill) == 5
    session.windmills.produce_until(32.0)  # the same saved timestamp cannot yield twice
    assert item_stock(mill, 'flour') == 2


@pytest.mark.parametrize('decide', ['_decide', '_decide_distant'])
def test_a_shopkeeper_walks_queues_pays_carries_and_returns_before_opening(supply, decide):
    session, mill, shop, _buyer = supply
    _stock(mill, 5)
    getattr(session, decide)(shop)
    assert shop.properties['sched_state'] == COLLECTING
    assert item_stock(shop, 'flour') == 0 and item_stock(mill, 'flour') == 5
    session._move(shop, 60.0)
    getattr(session, decide)(shop)
    assert shop.properties['sched_state'] == QUEUEING
    _serve(session, mill, shop)
    assert item_stock(shop, 'flour') == 3 and item_stock(mill, 'flour') == 2
    assert item_stock(mill, 'gold') == 30 and shop.properties['merchant_gold'] == 170
    assert not session.flour_supply.is_open(shop)
    session._move(shop, 60.0)
    getattr(session, decide)(shop)
    assert 'flour_job' not in shop.properties
    session.clock.set_time(9.5)
    getattr(session, decide)(shop)
    assert session.flour_supply.is_open(shop)
    assert session.stock_left(session.stock_entry(shop, 'flour')) == 3


def test_two_arrivals_are_served_in_fifo_order_with_separate_service_times(supply):
    session, mill, first, _buyer = supply
    second = _shop(session.logic, 'second', pos=(100, 50, 0), target=2)
    _reindex(session)
    _stock(mill, 10)
    _join(session, mill, first)
    _join(session, mill, second)
    assert mill.properties['flour_queue'] == [first.properties['id'], second.properties['id']]
    session.clock.advance(SERVICE_HOURS / session.clock.hours_per_second)
    session._decide(second)  # no cutting in, even when its decision runs first
    assert item_stock(second, 'flour') == 0
    session._decide(first)
    assert item_stock(first, 'flour') == 3
    session._move(first, 60.0)
    session._decide(second)
    session._move(second, 60.0)
    session._decide(second)
    assert item_stock(second, 'flour') == 0  # its own service has just begun
    _serve(session, mill, second)
    assert item_stock(second, 'flour') == 2 and item_stock(mill, 'flour') == 5
    assert mill.properties['flour_queue'] == []


def test_empty_mill_waits_for_real_production_without_creating_flour(supply):
    session, mill, shop, _ = supply
    _join(session, mill, shop)
    session.clock.advance(60.0)
    session._decide(shop)
    assert shop.properties['sched_state'] == QUEUEING and item_stock(shop, 'flour') == 0
    _stock(mill, 10, 'wheat')
    session.windmills.produce(0.25)
    session._decide(shop)
    assert item_stock(shop, 'flour') == 1 and wheat_stock(mill) == 0


def test_return_deadline_abandons_an_empty_queue_without_teleporting(supply):
    session, mill, shop, _ = supply
    _join(session, mill, shop)
    there = list(shop.pos)
    session.clock.set_time(9.0)
    session._decide(shop)
    assert shop.properties['sched_state'] == RETURNING
    assert list(shop.pos) == there and item_stock(shop, 'flour') == 0
    assert mill.properties['flour_queue'] == []
    session._move(shop, 60.0)
    session._decide(shop)
    session.clock.set_time(9.5)
    session._decide(shop)
    assert session.flour_supply.is_open(shop)  # opens with an empty shelf


def test_a_dead_head_of_queue_does_not_hold_up_the_next_customer(supply):
    session, mill, first, _ = supply
    second = _shop(session.logic, 'second', pos=(100, 50, 0))
    _reindex(session)
    _stock(mill, 6)
    _join(session, mill, first)
    _join(session, mill, second)
    first.properties['dead'] = True
    session.flour_supply.refresh()
    assert mill.properties['flour_queue'] == [second.properties['id']]
    session._decide(second)
    session._move(second, 60.0)
    session._decide(second)
    _serve(session, mill, second)
    assert item_stock(second, 'flour') == 3


def test_a_threat_interrupts_service_and_a_resumed_customer_rejoins_the_back(supply):
    session, mill, first, _ = supply
    second = _shop(session.logic, 'second', pos=(100, 50, 0))
    _reindex(session)
    _stock(mill, 6)
    _join(session, mill, first)
    _join(session, mill, second)
    bandit = NPC(pos=[first.pos[0] + 120, first.pos[1], first.pos[2]], properties={
        'name': 'road bandit', 'npc_role': 'bandit', 'faction': 'bandits',
        'aggression': 'hostile', 'combatant': True})
    session.logic.editor_state.things.append(bandit)
    session.logic.world_runtime.build_entity_caches()
    first.properties.update(courage=0.0, health=1.0)
    session._refresh_actor_cache()
    session.clock.advance(5.0)
    session._decide(first)
    assert first.properties['sched_state'] in ('FLEE', 'ALERT', 'RALLY')
    session.flour_supply.refresh()
    assert first.properties['id'] not in mill.properties['flour_queue']
    assert item_stock(first, 'flour') == 0
    bandit.properties['dead'] = True
    session._refresh_actor_cache()
    session._decide(first)
    assert mill.properties['flour_queue'][-1] == first.properties['id']


def test_distant_shop_sends_a_real_runner_and_opens_while_the_cargo_is_still_on_the_road(supply):
    session, mill, shop, _ = supply
    shop.pos = [14000, 50, 0]
    shop.properties.update(home=[14000, 50, 0], work_location=[14000, 50, 0])
    runner = _resident(session.logic, 'runner', pos=(14000, 50, 100), flour_runner=True)
    _reindex(session)
    _stock(mill, 5)
    session._decide(shop)
    assert 'flour_job' not in shop.properties and runner.properties['flour_job']['shop'] == shop.properties['id']
    _join(session, mill, runner)
    _serve(session, mill, runner)
    assert item_stock(runner, 'flour') == 3 and item_stock(shop, 'flour') == 0
    session.clock.set_time(9.5)
    session._decide(shop)
    assert session.flour_supply.is_open(shop)
    session._move(runner, 200.0)
    session._decide(runner)
    assert item_stock(shop, 'flour') == 3 and item_stock(runner, 'flour') == 0


def test_lost_cargo_leaves_a_shortage_and_a_dead_runner_is_not_replaced(supply):
    session, mill, shop, buyer = supply
    runner = _resident(session.logic, 'runner', flour_runner=True)
    _reindex(session)
    _stock(mill, 3)
    session.flour_supply._assign(runner, shop, mill, 'mill')
    _join(session, mill, runner)
    _serve(session, mill, runner)
    runner.properties.update(dead=True, health=0)
    session.game.stock_corpse(runner.properties)
    assert item_stock(runner, 'flour') == 3  # ordinary loot, available to the player
    session.clock.set_time(10.0)
    session._decide(shop)
    buyer.properties['need_hunger'] = 0.9
    session._decide(buyer)
    needs.advance(buyer.properties, 2.0, 'GOING_HOME')
    assert buyer.properties['need_hunger'] >= 0.9
    assert item_stock(shop, 'flour') == 0
    assert len(session.flour_supply.actors) == 3 and runner.properties['dead']


def test_surviving_runner_delivers_only_cargo_that_is_still_in_the_pack(supply):
    session, mill, shop, _ = supply
    runner = _resident(session.logic, 'runner', flour_runner=True)
    _reindex(session)
    _stock(mill, 3)
    session.flour_supply._assign(runner, shop, mill, 'mill')
    _join(session, mill, runner)
    _serve(session, mill, runner)
    inventory.remove_item(runner.properties['inventory'], 'flour', 2)
    runner.pos = list(shop.pos)
    session._decide(runner)
    assert item_stock(shop, 'flour') == 1 and item_stock(runner, 'flour') == 0


def test_closer_town_supplies_finite_surplus_and_charges_a_ten_percent_import_markup(supply):
    session, mill, shop, _ = supply
    mill.pos = [-14000, 0, 0]
    shop.pos = [6500, 50, 0]
    shop.properties.update(home=[6500, 50, 0], work_location=[6500, 50, 0])
    source = _shop(session.logic, 'town grocer', pos=(3000, 50, 0), target=4)
    _stock(source, 8)
    _reindex(session)
    session._decide(shop)
    assert shop.properties['flour_job']['kind'] == 'town'
    assert item_stock(shop, 'flour') == 0
    session._move(shop, 60.0)
    session._decide(shop)
    session._move(shop, 60.0)
    session._decide(shop)
    assert item_stock(shop, 'flour') == 3 and item_stock(source, 'flour') == 5
    assert shop.properties['flour_markup'] == pytest.approx(0.1)
    assert shelf_price(shop) == 11 and shelf_price(source) == 10
    assert shop.properties['merchant_gold'] == 170 and source.properties['merchant_gold'] == 230
    assert session._price(10, True, shop, item_id='flour') > session._price(10, True, source, item_id='flour')
    assert session._price(10, True, shop, item_id='torch') == session._price(10, True, source, item_id='torch')


def test_no_available_runner_or_town_stock_means_no_magic_import(supply):
    session, mill, shop, _ = supply
    mill.pos = [-20000, 0, 0]
    session._decide(shop)
    assert 'flour_job' not in shop.properties and item_stock(shop, 'flour') == 0


def test_hungry_resident_walks_to_the_local_shop_pays_and_consumes_one_flour(supply):
    session, _mill, shop, buyer = supply
    _stock(shop, 2)
    session.clock.set_time(10.0)
    session._decide(shop)
    buyer.properties['need_hunger'] = 0.9
    session._decide(buyer)
    assert buyer.properties['sched_state'] == BUYING
    assert buyer.properties['gold'] == 30 and item_stock(shop, 'flour') == 2
    session._move(buyer, 60.0)
    session._decide(buyer)
    assert buyer.properties['sched_state'] == EATING
    assert buyer.properties['gold'] == 20 and shop.properties['merchant_gold'] == 210
    assert item_stock(shop, 'flour') == 1 and item_stock(buyer, 'flour') == 0
    assert buyer.properties['need_hunger'] == pytest.approx(0.3)
    assert session.stock_left(session.stock_entry(shop, 'flour')) == 1


@pytest.mark.parametrize('problem', ['empty', 'closed', 'poor', 'dead', 'exhausted'])
def test_unavailable_food_or_urgent_rest_cannot_be_bypassed(supply, problem):
    session, _mill, shop, buyer = supply
    _stock(shop, 2)
    session.clock.set_time(10.0)
    session._decide(shop)
    buyer.pos = list(shop.pos)
    buyer.properties['need_hunger'] = 0.9
    if problem == 'empty':
        shop.properties['inventory'].clear()
    elif problem == 'closed':
        session.clock.set_time(9.6)
        shop.properties['opening_hour'] = 9.75
    elif problem == 'poor':
        buyer.properties['gold'] = 0
    elif problem == 'dead':
        shop.properties['dead'] = True
    else:
        buyer.properties['need_fatigue'] = 0.95
    before = item_stock(shop, 'flour')
    session._decide(buyer)
    assert buyer.properties['need_hunger'] >= 0.9
    assert item_stock(shop, 'flour') == before


def test_the_shopkeeper_and_the_guard_need_food_too(supply):
    session, _mill, shop, _ = supply
    guard = _resident(session.logic, 'guard', pos=(300, 50, 0), npc_role='guard', combatant=True)
    _reindex(session)
    _stock(shop, 3)
    session.clock.set_time(10.0)
    shop.properties['need_hunger'] = 0.9
    session._decide(shop)
    assert shop.properties['need_hunger'] == pytest.approx(0.3)
    guard.properties['need_hunger'] = 0.9
    session._decide(guard)
    session._move(guard, 60.0)
    session._decide(guard)
    assert guard.properties['need_hunger'] == pytest.approx(0.3)
    assert item_stock(shop, 'flour') == 1


def test_an_empty_local_shop_does_not_prevent_buying_from_another_local_keeper(supply):
    session, _mill, empty, buyer = supply
    other = _shop(session.logic, 'other local grocer', pos=(700, 50, 0))
    _stock(other, 2)
    _reindex(session)
    buyer.properties['food_shop'] = empty.properties['id']
    buyer.properties['need_hunger'] = 0.9
    session.clock.set_time(10.0)
    session._decide(other)
    session._decide(buyer)
    session._move(buyer, 60.0)
    session._decide(buyer)
    assert buyer.properties['need_hunger'] == pytest.approx(0.3)
    assert item_stock(other, 'flour') == 1 and item_stock(empty, 'flour') == 0


def test_player_trade_and_npc_meals_share_one_inventory_and_daily_resolution_does_not_refill_it(supply):
    session, _mill, shop, buyer = supply
    _stock(shop, 1)
    session.flour_supply.sync_shelf(shop)
    session.merchant_npc = shop
    session.game.character.gold = 1000
    assert session.buy('flour')
    assert not session.buy('flour')
    assert item_stock(shop, 'flour') == 0
    row = session.stock_entry(shop, 'flour')
    row['restock'] = 8  # even an old authored refill row cannot create flour
    daily.resolve_pending(session.store, 1, [shop.properties])
    daily.resolve_pending(session.store, 2, [shop.properties])
    assert row['qty'] == 0 and item_stock(shop, 'flour') == 0
    assert session.sell('flour')  # player trade can relieve a shortage
    assert item_stock(shop, 'flour') == 1
    session.clock.set_time(10.0)
    session._decide(shop)
    buyer.pos = list(shop.pos)
    buyer.properties['need_hunger'] = 0.9
    session._decide(buyer)
    assert item_stock(shop, 'flour') == 0 and buyer.properties['need_hunger'] < 0.9


def test_daily_opening_has_both_on_time_and_slightly_late_days_and_never_rerolls(supply):
    session, _mill, shop, _ = supply
    session.rng = random.Random(4)
    openings = []
    for day in range(2, 32):
        session.clock.set_time(9.5, day)
        hour = session.flour_supply.opening_hour(shop)
        assert session.flour_supply.opening_hour(shop) == hour
        openings.append(hour)
    assert SHOP_OPEN in openings and any(h > SHOP_OPEN for h in openings)
    assert all(SHOP_OPEN <= h <= SHOP_OPEN + 0.25 for h in openings)
    shop.properties.update(opening_day=31, opening_hour=9.7)
    session._decide(shop)
    assert shop.properties['sched_state'] == OPENING and not session.flour_supply.is_open(shop)
    session.clock.set_time(9.71)
    session._decide(shop)
    assert session.flour_supply.is_open(shop)


def test_missed_opening_is_a_real_delay_and_never_moves_the_keeper_for_free(supply):
    session, mill, shop, _ = supply
    _stock(mill, 3)
    _join(session, mill, shop)
    _serve(session, mill, shop)
    there = list(shop.pos)
    session.clock.set_time(9.8)
    session._decide(shop)
    assert list(shop.pos) == there and not session.flour_supply.is_open(shop)
    assert shop.properties['sched_state'] == RETURNING


def test_map_revisit_remembers_paid_cargo_its_position_stock_needs_and_opening(supply):
    session, mill, shop, buyer = supply
    _stock(mill, 10, 'wheat')
    session.windmills.produce(0.10)
    _stock(mill, 3)
    _join(session, mill, shop)
    _serve(session, mill, shop)
    buyer.properties['need_hunger'] = 0.9
    memory = session.memory = MapMemory(session)
    memory.load('supply-test')
    memory.save()
    saved_pos = list(shop.pos)
    saved_purse = shop.properties['merchant_gold']
    saved_job = copy.deepcopy(shop.properties['flour_job'])
    shop.properties.update(inventory=[], stock=[], merchant_gold=200, flour_job=None, opening_hour=11.0)
    shop.pos = [0, 50, 0]
    mill.properties['mill_progress'] = 0.0
    buyer.properties['need_hunger'] = 0.0
    returning = session.memory = MapMemory(session)
    returning.load('supply-test')
    returning.apply()
    session.flour_supply.install()
    assert list(shop.pos) == saved_pos and shop.properties['flour_job'] == saved_job
    assert shop.properties['merchant_gold'] == saved_purse and item_stock(shop, 'flour') == 3
    assert mill.properties['mill_progress'] == pytest.approx(0.10)
    assert buyer.properties['need_hunger'] == 0.9 and shop.properties['opening_hour'] == 9.5


def test_shipped_shops_and_runners_are_ordinary_finite_residents_and_specialists_keep_their_roles():
    world = json.loads((ROOT / 'maps/miniwind_world.json').read_text())
    shops = [t for t in world['things'] if t['properties'].get('flour_target')]
    runners = [t for t in world['things'] if t['properties'].get('flour_runner')]
    assert len(shops) == 5 and len(runners) == 4
    assert len({t['properties']['id'] for t in shops + runners}) == 9
    assert all(t['type'] == 'npc' and not t['properties'].get('respawn') for t in runners)
    assert all(next(e for e in t['properties']['schedule'] if e['state'] == 'WORKING')['hour'] == 9.5
               for t in shops)
    thalen = next(t for t in world['things'] if t['properties'].get('name') == 'Thalen')
    assert not thalen['properties'].get('flour_target')


def test_a_dead_supplier_stays_dead_even_if_the_map_is_left_immediately(supply):
    session, _mill, shop, _buyer = supply
    session.memory.load('supplier-death')
    shop.properties.update(dead=True, health=0)
    session.memory.save()
    shop.properties.update(dead=False, health=60)
    session.memory = MapMemory(session)
    session.memory.load('supplier-death')
    session.memory.apply()
    assert shop.properties['dead'] and shop.properties['health'] == 0
