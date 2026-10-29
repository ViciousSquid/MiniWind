"""Harvest, walk, deposit, run: the placed mill's complete wheat supply path."""

import copy
import json

import pytest

pytest.importorskip('PyQt5')

from engine.player import Player
from engine.prop_entity import Prop
from .. import farm_work, mental_state
from ..entities import Marker, NPC
from ..map_memory import MapMemory
from ..rpg import inventory, items
from ..runtime import MiniwindSession
from ..sim import knowledge, ownership
from ..sim.director import actor_key
from ..ui.worldmap import map_features
from ..windmills import delivery_point, is_producing, wheat_stock
from .test_farm_work import Field
from .test_windmills import ROOT, _pair, logic as logic

pytestmark = pytest.mark.qt


@pytest.fixture
def farm(logic):
    body, _rotor = _pair(logic, producing=False, pos=(3000, 0, 0))
    farmer = NPC(pos=[1500.0, 50.0, 0.0], properties={
        'name': 'Test farmer', 'npc_role': 'farmer', 'home': [1500.0, 50.0, 0.0],
        'schedule': [{'hour': 0, 'state': 'WORKING', 'location': 'work'}],
        '_farm_rows': [[1400.0, 0.0], [1600.0, 0.0]],
        'inventory': [items.make('milk'), items.make('scythe')],
    })
    logic.editor_state.things.append(farmer)
    logic.world_runtime.build_entity_caches()
    logic.player_runtime.player = Player(-10000, -10000)
    session = MiniwindSession(logic, cfg={'start_hour': 12.0})
    session.clock.set_time(12.0, 1)
    session.windmills.install()
    ownership.set_owner(body.properties, actor_key(farmer), 'Test farmer', 'villagers')
    try:
        yield session, farmer, body
    finally:
        session.windmills.clear()


def test_a_farmer_harvests_walks_to_the_door_deposits_and_resumes_work(farm):
    session, farmer, mill = farm
    session._decide(farmer)
    assert farmer.properties['sched_state'] == farm_work.REAPING
    for _ in range(farm_work.DELIVERY_BATCH):
        session.farm_work.update(farm_work.SWING_EVERY, [farmer], Field())
    assert wheat_stock(farmer) == farm_work.DELIVERY_BATCH
    session._decide(farmer)
    assert farmer.properties['sched_state'] == farm_work.DELIVERING
    assert '_farm_work' not in farmer.properties and '_farm_tool' not in farmer.properties
    assert wheat_stock(mill) == 0
    assert farmer.properties['_dest'][::2] == pytest.approx(delivery_point(mill)[::2])
    session._move(farmer, 30.0)
    session._decide(farmer)
    assert wheat_stock(farmer) == 0 and wheat_stock(mill) == farm_work.DELIVERY_BATCH
    assert inventory.quantity(farmer.properties['inventory'], 'milk') == 1
    assert inventory.quantity(farmer.properties['inventory'], 'scythe') == 1
    session.windmills.update(3.0)
    assert is_producing(mill) and session.windmills.mills[0].motion.speed > 0
    session._decide(farmer)
    assert farmer.properties['sched_state'] == farm_work.REAPING
    assert farmer.properties['_dest'][0] in (1400.0, 1600.0)
    assert wheat_stock(mill) == farm_work.DELIVERY_BATCH


@pytest.mark.parametrize('decide', ['_decide', '_decide_distant'])
def test_delivery_runs_through_both_near_and_distant_decision_paths(farm, decide):
    session, farmer, mill = farm
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 5))
    getattr(session, decide)(farmer)
    assert farmer.properties['sched_state'] == farm_work.DELIVERING
    assert wheat_stock(mill) == 0
    session._move(farmer, 30.0)
    getattr(session, decide)(farmer)
    assert wheat_stock(mill) == 5 and wheat_stock(farmer) == 0


def test_a_delivery_keeps_its_target_and_moves_only_wheat_once(farm):
    session, farmer, mill = farm
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 5))
    session.farm_work.drive(session, farmer)
    target_id = farmer.properties['_farm_delivery']
    # More travel decisions neither teleport stock nor duplicate it.
    for _ in range(3):
        session.farm_work.drive(session, farmer)
    assert farmer.properties['_farm_delivery'] == target_id
    assert wheat_stock(farmer) == 5 and wheat_stock(mill) == 0
    farmer.pos = delivery_point(mill)
    for _ in range(3):
        session.farm_work.drive(session, farmer)
    assert wheat_stock(farmer) == 0 and wheat_stock(mill) == 5
    assert {s['id'] for s in farmer.properties['inventory']} == {'milk', 'scythe'}


def test_a_smaller_last_harvest_is_delivered_when_reaping_finishes(farm):
    session, farmer, mill = farm
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 2))
    farmer.properties['_farm_task'] = dict(kind='reap', since=34.0, until=35.0)
    assert session.farm_work.drive(session, farmer)
    assert farmer.properties['sched_state'] == farm_work.DELIVERING
    farmer.pos = delivery_point(mill)
    session.farm_work.drive(session, farmer)
    assert wheat_stock(mill) == 2 and wheat_stock(farmer) == 0


def test_dusk_interrupts_a_delivery_without_losing_the_wheat(farm):
    session, farmer, mill = farm
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 5))
    session.farm_work.drive(session, farmer)
    session.clock.set_time(20.0)
    assert not session.farm_work.drive(session, farmer)
    assert '_farm_delivery' not in farmer.properties
    assert wheat_stock(farmer) == 5 and wheat_stock(mill) == 0
    session.clock.set_time(12.0, 2)
    assert session.farm_work.drive(session, farmer)
    assert farmer.properties['sched_state'] == farm_work.DELIVERING


def test_without_a_usable_mill_the_farmer_keeps_the_wheat_and_farms(farm):
    session, farmer, mill = farm
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 5))
    mill.properties['disabled'] = True
    assert session.farm_work.drive(session, farmer)
    assert farmer.properties['sched_state'] == farm_work.REAPING
    assert wheat_stock(farmer) == 5 and wheat_stock(mill) == 0


def test_delivery_selects_the_nearest_available_mill(farm):
    session, farmer, far = farm
    near, _rotor = _pair(session.logic, 'near', producing=False, pos=(1700, 0, 0))
    session.windmills.install()
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 5))
    session.farm_work.drive(session, farmer)
    assert farmer.properties['_farm_delivery'] == near.properties['id']
    farmer.pos = delivery_point(near)
    session.farm_work.drive(session, farmer)
    assert wheat_stock(near) == 5 and wheat_stock(far) == 0


def test_the_player_can_open_the_mill_inventory_store_wheat_and_empty_it(farm):
    session, _farmer, mill = farm
    assert session.nearest_container(delivery_point(mill)) is mill
    assert session.open_container(mill)
    assert session.container_name() == 'Windmill'
    assert session.container_take_is_theft()
    session.game.character.inventory = [items.make('wheat', 3)]
    assert session.store_in_container(0)
    assert wheat_stock(mill) == 3 and is_producing(mill)
    assert session.take_from_container(0)
    assert wheat_stock(mill) == 0 and not is_producing(mill)
    assert inventory.quantity(session.game.character.inventory, 'wheat') == 3
    assert ownership.is_stolen(inventory.find(session.game.character.inventory, 'wheat'))


def test_emptying_the_mill_is_a_theft_even_without_a_witness(farm):
    session, farmer, mill = farm
    inventory.add_item(mill.properties['inventory'], items.make('wheat', 5))
    session.game.character.inventory = []
    assert session.open_container(mill)
    assert session.take_all_from_container() == 1
    event = session.director.bus.recent(1)[0]
    assert event.kind == 'theft' and event.actor == 'player'
    assert event.target == actor_key(farmer)
    assert event.data['item'] == 'wheat'
    stolen = inventory.find(session.game.character.inventory, 'wheat')
    assert ownership.is_stolen(stolen) and stolen['stolen_from'] == 'Test farmer'
    assert wheat_stock(mill) == 0 and not is_producing(mill)
    assert session.game.character.bounty == 0


def test_stolen_wheat_stays_marked_when_it_joins_the_players_existing_stack(farm):
    session, _farmer, mill = farm
    session.game.character.inventory = [items.make('wheat', 2)]
    inventory.add_item(mill.properties['inventory'], items.make('wheat', 5))
    session.open_container(mill)
    assert session.take_from_container(0)
    stock = inventory.find(session.game.character.inventory, 'wheat')
    assert stock['qty'] == 7 and ownership.is_stolen(stock)
    assert session.director.bus.recent(1)[0].kind == 'theft'


def test_the_owned_stock_screen_labels_taking_wheat_as_stealing(farm, qt_app, monkeypatch):
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import screens

    session, _farmer, mill = farm
    inventory.add_item(mill.properties['inventory'], items.make('wheat', 5))
    session.open_container(mill)
    labels = []
    monkeypatch.setattr(screens, 'button', lambda painter, rect, label, *args, **kwargs: labels.append(label))
    image = QImage(800, 600, QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        screens._draw_container(painter, session, 800, 600)
    finally:
        painter.end()
    assert 'Steal all' in labels and 'Take all' not in labels


def test_a_guard_witnessing_the_theft_remembers_it_and_reports_it(farm):
    session, _farmer, mill = farm
    inventory.add_item(mill.properties['inventory'], items.make('wheat', 5))
    guard = NPC(pos=[mill.pos[0] + 20, 50, mill.pos[2]], properties={
        'name': 'Mill watch', 'npc_role': 'guard', 'faction': 'guards',
        'sight_range': 1200, 'sched_state': 'PATROL'})
    session.logic.editor_state.things.append(guard)
    session.logic.world_runtime.build_entity_caches()
    session._refresh_actor_cache()
    session.logic.player_runtime.player.pos.x = mill.pos[0]
    session.logic.player_runtime.player.pos.z = mill.pos[2]
    session.open_container(mill)
    assert session.take_from_container(0)
    event = session.director.bus.recent(1)[0]
    assert event.kind == 'theft'
    assert knowledge.knows(session.store, actor_key(guard), event.id)
    assert session.director.resolve_reports([guard]) == 1
    assert session.game.character.bounty > 0


def test_mill_stock_survives_serialization_and_map_departure_and_return(farm):
    session, _farmer, mill = farm
    inventory.add_item(mill.properties['inventory'], items.make('wheat', 7))
    record = json.loads(json.dumps(mill.to_dict()))
    restored = Prop(pos=record['pos'], properties=record['properties'])
    assert wheat_stock(restored) == 7 and restored.properties['id'] == mill.properties['id']
    session.memory.load('mill-stock-test')
    session.memory.save()
    mill.properties['inventory'] = []
    returned = MapMemory(session)
    returned.load('mill-stock-test')
    returned.apply()
    assert wheat_stock(mill) == 7
    mill.properties['inventory'].clear()
    returned.save()
    inventory.add_item(mill.properties['inventory'], items.make('wheat', 99))
    returned.load('mill-stock-test')
    returned.apply()
    assert wheat_stock(mill) == 0


def test_the_placed_mill_is_discovered_once_and_appears_on_the_world_map(farm):
    session, _farmer, _mill = farm
    world = json.loads((ROOT / 'maps/miniwind_world.json').read_text())
    record = next(t for t in world['things'] if t['properties'].get('place_name') == 'Windmill')
    marker = Marker(pos=record['pos'], properties=copy.deepcopy(record['properties']))
    assert marker.properties['marker_kind'] == 'location'
    session.logic.editor_state.things.append(marker)
    assert not any(p[0] == 'Windmill' for p in map_features(session)['places'])
    session._tick_locations()
    assert not any(n['text'] == 'Windmill discovered' for n in session.notifications)
    session.logic.player_runtime.player.pos.x = marker.pos[0]
    session.logic.player_runtime.player.pos.z = marker.pos[2]
    session._tick_locations()
    assert [n['text'] for n in session.notifications].count('Windmill discovered') == 1
    assert session.store.get('visited.windmill') == '1'
    assert any(p[0] == 'Windmill' for p in map_features(session)['places'])
    session._tick_locations()
    marker.properties.pop('_discovered')   # returning to a freshly loaded map
    session._tick_locations()
    assert [n['text'] for n in session.notifications].count('Windmill discovered') == 1
    assert marker.properties['_discovered']


def test_a_delivery_has_a_readable_state_and_thought(farm):
    session, farmer, _mill = farm
    inventory.add_item(farmer.properties['inventory'], items.make('wheat', 5))
    session.farm_work.drive(session, farmer)
    key, thought = mental_state.thought(farmer.properties)
    assert key == farm_work.DELIVERING
    assert 0 < len(thought.split()) <= mental_state.THOUGHT_WORDS
