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


def test_only_a_name_of_its_own_counts_as_named():
    """Four "Smuggler"s, a raid of "Greenskin Raider"s or a "Giant Spider"
    are kinds, not names: before, each scored as a named foe, so any pack of
    renamed monsters made a fight "interesting" by itself."""
    def foe(role, name):
        return entities.Creature(pos=[0, 0, 0], properties={
            "npc_role": role, "name": name, "display_name": name})
    smugglers = [foe("bandit", "Smuggler") for _ in range(3)]
    raiders = [foe("greenskin", "Greenskin Raider") for _ in range(2)]
    spiders = [foe("monster", "Giant Spider") for _ in range(2)]
    wrexa = foe("bandit_chief", "Smuggler Captain Wrexa")
    session = _session(smugglers + raiders + spiders + [wrexa])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, _clock = _recorder(session)
    for actor in smugglers + raiders + spiders[:1]:
        rec.engage(actor)
    assert "named" not in rec.current.reasons
    assert rec.current.score == 6 and rec.current.interesting_at is None
    rec.engage(wrexa)
    assert rec.current.reasons["named"] == 2


def test_the_chronicle_survives_a_new_map_and_a_load():
    """Every map (a cave, the way out, a loaded save) starts a new session:
    the chronicle used to start empty each time, forgetting every fight."""
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, clock = _recorder(session)
    session.encounters = rec
    for i in range(3):
        rec.engage(entities.Creature(pos=[0, 0, 0], properties={
            "npc_role": "bandit_chief", "display_name": f"Boss {i}"}))
    clock.t += 20
    rec.tick()
    assert len(rec.chronicle) == 1
    cave = _session([])
    cave.store = cave.game.store = session.store      # one store, as across maps
    cave.restore()
    (record,) = cave.encounters.chronicle
    assert record["summary"] == rec.chronicle[0]["summary"]
    assert record["provenance"] == rec.chronicle[0]["provenance"]


def test_a_killing_blow_closes_the_encounter_as_a_fall(monkeypatch):
    """The killing blow lands in the engine's monster pass, which then stops
    ticking the game: the per-tick watch never saw the death, so the fight
    that killed the player was never remembered."""
    from .. import fio, runtime
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, _clock = _recorder(session)
    session.encounters = rec
    chief = entities.Creature(pos=[0, 0, 0], properties={
        "npc_role": "bandit_chief", "display_name": "Hal Corbin"})
    fio.player_runtime(session.logic).last_damage = (chief, "attack", "physical")
    monkeypatch.setattr(runtime.rpg_combat, "resolve_incoming",
                        lambda *a, **kw: {"final": 9999, "armor_class": "none"})
    session.store.set("fortune.escape_day", str(session.clock.day))   # no lucky escape
    session._mitigate_incoming(9999)
    assert session.game.character.is_dead
    assert rec.current is None
    (record,) = rec.chronicle
    assert record["fell"] and record["lowest_health"] == 0.0
    assert record["provenance"][0].startswith("Hal Corbin")
    # The rest of the gang strikes the fallen in the same pass: that is the
    # fight that just ended, and it was once recorded again as a second fall.
    archer = entities.Creature(pos=[0, 0, 0], properties={
        "npc_role": "bandit_archer", "display_name": "Wil the Brigand"})
    fio.player_runtime(session.logic).last_damage = (archer, "attack", "physical")
    session._mitigate_incoming(9999)
    rec.crit(False)
    assert rec.current is None and len(rec.chronicle) == 1


def test_provenance_reads_as_a_sentence():
    """It said "of a bandits", "of a faction_raid" and "from Spawn_wolf_571"."""
    gang = {"who": "Nils the Brigand", "kind": "journey", "journey_kind": "bandits",
            "origin": "Ashby", "destination": "Thornfield"}
    assert sentence(gang) == "Nils the Brigand, of a bandit gang on the road from Ashby to Thornfield."
    pack = {"who": "Wolf", "kind": "journey", "journey_kind": "wolves"}
    assert sentence(pack) == "Wolf, of a wolf pack."
    assert sentence({"who": "Odd", "kind": "journey", "journey_kind": "night_watch"}) \
        == "Odd, of a night watch party."
    from types import SimpleNamespace as NS
    den = NS(pos=[0, 0, 0], properties={"type": "creaturespawn", "name": "Spawn_wolf_571",
                                         "id": "sp-9", "creature_role": "wolf"})
    session = _session([den])
    wolf = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "wolf", "name": "Wolf",
                                                         "_spawner": "sp-9", "_spawn_slot": 0})
    assert sentence(of(session, wolf)) == "Wolf, from the wolf lair."
    den.properties["display_name"] = "Greywood's wolf den"
    assert sentence(of(session, wolf)) == "Wolf, from Greywood's wolf den."


def test_bounty_hunters_count_as_sent_for_the_player():
    """SENT_KINDS named "hunter"; the journey kind is "hunters", so a band
    sent for the player's bounty never scored as sent."""
    from types import SimpleNamespace as NS
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    journey = NS(kind="hunters", origin="ashby", dest="thornfield", cause=None)
    session.living = NS(board=NS(journeys={"j7": journey}, nearest_place=lambda x, z: "ashby"),
                        places={"ashby": {"name": "Ashby"}, "thornfield": {"name": "Thornfield"}})
    rec, _clock = _recorder(session)
    hunter = entities.Creature(pos=[0, 0, 0], properties={
        "npc_role": "bounty_hunter", "display_name": "Garet the Hunter", "_journey": "j7"})
    rec.engage(hunter)
    assert rec.current.reasons.get("sent") == 6
    assert rec.current.events[0]["from"] == \
        "Garet the Hunter, of a band of bounty hunters on the road from Ashby to Thornfield."


def test_an_encounter_is_named_for_the_place_it_happens():
    """Places came from the road board only: its towns, not the camps,
    shrines and cave mouths among the map's location markers, and the
    nearest town however far off. Inside a cave there is no board, and every
    cave fight was "At the roadside"."""
    from types import SimpleNamespace as NS
    from ..provenance import _place
    mouth = NS(pos=[0.0, 0.0, 0.0], properties={
        "type": "marker", "marker_kind": "location", "place_name": "Wolfmaw Cave",
        "discover_radius": 700.0})
    world = _session([mouth])
    assert _place(world, (900.0, 0.0, 0.0)) == "Wolfmaw Cave"
    assert _place(world, (9000.0, 0.0, 0.0)) == ""
    cave = _session([])
    cave.underground, cave.region_name = True, "The Bonepit"
    cave.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, clock = _recorder(cave)
    for i in range(3):
        rec.engage(entities.Creature(pos=[0, 0, 0], properties={
            "npc_role": "skeleton", "display_name": f"Bone Lord {i}"}))
    rec.health(0.1)
    clock.t += 20
    rec.tick()
    (record,) = rec.chronicle
    assert record["place"] == "The Bonepit"
    assert record["summary"].startswith("At The Bonepit: ")
    assert record["provenance"][0] == "Bone Lord 0, who belongs at The Bonepit."


def test_one_picture_of_the_lowest_moment(tmp_path):
    """Each new low asked for a new numbered screenshot: a long fight listed
    02-lowest ... 07-lowest, most never taken (one capture is pending at a
    time). The lowest moment is one file, taken again at each new low."""
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, clock = _recorder(session, recording=True, root=str(tmp_path))
    for i in range(3):
        rec.engage(entities.Creature(pos=[0, 0, 0], properties={
            "npc_role": "bandit_chief", "display_name": f"Boss {i}"}))
    assert rec.capture_due[1] == "interesting"
    for health in (0.8, 0.6, 0.4, 0.2):
        rec.health(health)
        assert rec.capture_due[0].endswith("02-lowest.png")
    clock.t += 20
    rec.tick()
    (record,) = rec.chronicle
    assert record["screenshots"] == ["01-interesting.png", "02-lowest.png", "03-end.png"]


def test_a_queen_is_a_boss_whatever_her_kind():
    """BOSS_ROLES named "giant_spider_queen", "warboss", "yeti" and
    "necromancer", roles nothing in the Vale has: the Spider Queen is a
    "monster", the Ashen Hierophant a "cultist", the Den Mother a "wolf",
    and none counted as a boss. A named foe far tougher than its kind is."""
    def foe(role, name, health):
        return entities.Creature(pos=[0, 0, 0], properties={
            "npc_role": role, "name": name, "display_name": name, "health": health})
    queen = foe("monster", "Spider Queen", 170)
    mother = foe("wolf", "Den Mother", 75)
    archers = [foe("bandit_archer", "Bandit Archer", 100) for _ in range(2)]
    spider = foe("monster", "Webwood Spinner", 60)
    session = _session([queen, mother, spider] + archers)
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec, _clock = _recorder(session)
    rec.engage(queen)
    rec.engage(mother)
    assert rec.current.reasons["boss"] == 8
    for actor in archers + [spider]:      # tough but nameless; named but ordinary
        rec.engage(actor)
    assert rec.current.reasons["boss"] == 8


def test_an_encounter_keeps_the_worlds_time_and_ends_with_the_map(monkeypatch):
    """The recorder timed quiet spells and fight lengths on the wall clock: a
    pause mid-fight ended it, and a fight still open when the player walked
    out of a cave was lost with that map's session -- every cave fight of a
    playtest (scores 12 to 30) reached no chronicle."""
    from types import SimpleNamespace as NS
    from ..host import MiniwindGame
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    rec = session.encounters
    rec.recording = lambda: False

    def wights(tag):
        for i in range(3):
            rec.engage(entities.Creature(pos=[0, 0, 0], properties={
                "npc_role": "wraith", "display_name": f"Barrow Wight {tag}{i}"}))
    wights("a")
    session._archery_clock = 20.0          # 20 s of the world's time, quiet
    rec.tick()
    assert len(rec.chronicle) == 1 and rec.current is None
    wights("b")
    assert rec.current is not None
    logic = NS(_miniwind=session, game_session=session)
    for name in ("leave_map", "persist", "uninstall"):
        monkeypatch.setattr(session, name, lambda *a, **k: None)
    MiniwindGame.on_play_stop(NS(_host=None), logic)
    assert rec.current is None and len(rec.chronicle) == 2
