"""Encounters worth remembering, with where everyone came from."""

from __future__ import annotations

import json
import os

from .. import entities
from ..encounters import EncounterRecorder, THRESHOLD
from ..provenance import of, sentence
from .test_quest_files import _session


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _recorder(session, recording=False, root=None):
    clock = _Clock()
    rec = EncounterRecorder(session, clock=clock)
    rec.recording = lambda: recording
    rec.saves_root = root
    return rec, clock


def test_a_dull_scrap_is_forgotten_and_a_hard_fight_is_remembered():
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, clock = _recorder(session)
    wolf = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "wolf"})
    rec.engage(wolf)
    rec.kill(wolf)
    clock.t += 20
    rec.tick()
    assert rec.current is None and rec.chronicle == [], "one wolf: not worth a record"
    chief = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "bandit_chief",
                                                          "display_name": "Hal Corbin"})
    archer = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "bandit_archer"})
    rec.engage(chief)
    rec.engage(archer)
    rec.crit(False)
    rec.health(0.2)
    rec.kill(archer)
    rec.kill(chief)
    assert rec.current.score >= THRESHOLD and rec.current.interesting_at is not None
    clock.t += 20
    rec.tick()
    (record,) = rec.chronicle
    assert "Hal Corbin" in record["summary"] and record["lowest_health"] == 0.2
    assert record["why"]["boss"] == 4 and record["why"]["named"] == 2


def test_provenance_says_where_a_spawned_actor_came_from():
    spawner = entities.CreatureSpawn(pos=[0, 0, 0], properties={"name": "BanditSpawner",
                                                                "id": "sp-1"}) \
        if hasattr(entities, "CreatureSpawn") else None
    things = [spawner] if spawner is not None else []
    session = _session(things)
    bandit = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "bandit",
                                                           "_spawner": "sp-1", "_spawn_slot": 2})
    prov = of(session, bandit)
    assert prov["kind"] == "spawn" and prov["slot"] == 2
    assert sentence(prov).startswith("Bandit, from ")
    placed = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "wolf"})
    assert of(session, placed)["kind"] == "authored"


def test_recording_writes_the_record_and_asks_for_screenshots(tmp_path):
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, clock = _recorder(session, recording=True, root=str(tmp_path))
    for i in range(4):
        rec.engage(entities.Creature(pos=[0, 0, 0], properties={
            "npc_role": "bandit_chief", "display_name": f"Boss {i}"}))
    assert rec.capture_due and rec.capture_due[1] == "interesting"
    rec.capture_due = None
    rec.fell()
    folders = os.listdir(tmp_path / "encounters")
    (folder,) = folders
    with open(tmp_path / "encounters" / folder / "encounter.json") as fh:
        record = json.load(fh)
    assert record["fell"] and len(record["foes"]) == 4
    assert rec.capture_due and rec.capture_due[1] == "end"
