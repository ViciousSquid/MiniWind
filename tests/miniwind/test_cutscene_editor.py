"""The cutscene editor as a design tool for MiniWind: cast the game's NPCs and
creatures, equip them, and give them MOVE / SAY / THINK / ATTACK keyframes --
through the real CutsceneWizard on the real editor window."""

import json
from pathlib import Path

import pytest

pytest.importorskip("PyQt5", reason="the cutscene wizard uses Qt")

pytestmark = pytest.mark.qt


@pytest.fixture
def wizard(main_window, qt_app, tmp_path, monkeypatch):
    import game.cutscene_editor as cutscene_editor
    from editor import cutscene_wizard
    monkeypatch.setattr(cutscene_wizard, "ACTOR_KINDS", list(cutscene_wizard.ACTOR_KINDS))
    monkeypatch.setattr(cutscene_wizard, "ACTOR_PANELS", list(cutscene_wizard.ACTOR_PANELS))
    monkeypatch.setattr(cutscene_wizard, "ACTOR_TYPES", set(cutscene_wizard.ACTOR_TYPES))
    monkeypatch.setattr(cutscene_wizard, "ACTOR_CLASSES", dict(cutscene_wizard.ACTOR_CLASSES))
    cutscene_editor.register()
    # Saved into the test's own folder, not the project's cutscenes/.
    monkeypatch.setattr(cutscene_wizard, "CUTSCENE_DIR", str(tmp_path / "cutscenes"))
    w = cutscene_wizard.CutsceneWizard(main_window)
    w.show()
    qt_app.processEvents()
    yield w
    w._saved_signature = w._cutscene_signature()      # no unsaved-changes prompt
    w.close()
    w.deleteLater()
    qt_app.processEvents()


def _kind(wizard, label):
    from editor import cutscene_wizard
    return next(k for k in cutscene_wizard.ACTOR_KINDS if k[0] == label)


def _panel_widget(wizard, cls, nth=0):
    found = wizard.actor_panel_host.findChildren(cls)
    return found[nth]


def test_the_cast_buttons_make_miniwind_npcs_and_creatures(wizard):
    from game.entities import Creature, NPC
    assert [b.text() for b in wizard.kind_buttons] == ["+ NPC", "+ Creature"]
    npc = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    beast = wizard._create_temporary_actor(_kind(wizard, "+ Creature"))
    assert isinstance(npc, NPC) and npc.properties["npc_role"] == "guard"
    assert isinstance(beast, Creature) and beast.properties["npc_role"] == "bandit"


def test_the_actor_panel_arms_every_selected_actor_at_once(wizard, qt_app):
    from PyQt5 import QtWidgets
    actors = [wizard._create_temporary_actor(_kind(wizard, "+ Creature")) for _ in range(3)]
    wizard._select_actor_ids([a.properties["id"] for a in actors])
    qt_app.processEvents()
    combos = wizard.actor_panel_host.findChildren(QtWidgets.QComboBox)
    style = next(c for c in combos if c.findData("magic") >= 0)
    style.setCurrentIndex(style.findData("magic"))
    style.activated.emit(style.currentIndex())
    for actor in actors:
        p = actor.properties
        assert p["attack_style"] == "magic" and p["equipped_weapon"] == "apprentice_staff"
        assert any((e.get("id") if isinstance(e, dict) else e) == "firebolt" for e in p["spells"])


def test_a_single_actor_gets_the_inventory_and_spells_tabs(wizard, qt_app):
    from PyQt5 import QtWidgets
    npc = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    wizard._select_actor_ids([npc.properties["id"]])
    qt_app.processEvents()
    tabs = wizard.actor_panel_host.findChildren(QtWidgets.QTabWidget)
    assert [tabs[0].tabText(i) for i in range(tabs[0].count())] == ["Inventory", "Spells"]


def test_a_role_change_remakes_the_actor_keeping_who_and_where(wizard, qt_app):
    from PyQt5 import QtWidgets
    npc = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    aid = npc.properties["id"]
    npc.properties["name"] = npc.properties["display_name"] = "Captain Aldric"
    npc.properties["inventory"] = [{"id": "potion_heal_minor", "qty": 2}]
    wizard._select_actor_ids([aid])
    qt_app.processEvents()
    role = next(c for c in wizard.actor_panel_host.findChildren(QtWidgets.QComboBox)
                if c.findData("guard_archer") >= 0)
    role.setCurrentIndex(role.findData("guard_archer"))
    role.activated.emit(role.currentIndex())
    twin = wizard._find_map_actor(aid)
    assert twin is not npc and twin.properties["npc_role"] == "guard_archer"
    assert twin.properties["display_name"] == "Captain Aldric"
    assert twin.properties["inventory"] == [{"id": "potion_heal_minor", "qty": 2}]
    assert twin.properties["attack_style"] == "bow"            # the role's own kit
    assert wizard.actor_objects[aid] is twin


def test_duplicate_raises_a_company_with_the_same_kit(wizard):
    npc = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    npc.properties["equipped_weapon"] = "steel_longsword"
    wizard._select_actor_ids([npc.properties["id"]])
    wizard._duplicate_selected_actors()
    wizard._duplicate_selected_actors()
    assert len(wizard.actor_meta) == 3
    assert all(wizard.actor_objects[a].properties["equipped_weapon"] == "steel_longsword"
               for a in wizard.actor_meta)


def _key(wizard, kind):
    wizard.key_kind.setCurrentIndex(wizard.key_kind.findData(kind))


def test_move_say_think_and_attack_keyframes_for_many_actors(wizard):
    guards = [wizard._create_temporary_actor(_kind(wizard, "+ NPC")) for _ in range(3)]
    bandits = [wizard._create_temporary_actor(_kind(wizard, "+ Creature")) for _ in range(4)]
    gids = [g.properties["id"] for g in guards]
    bids = [b.properties["id"] for b in bandits]

    wizard._select_actor_ids(gids)
    wizard.key_time.setValue(1.0)
    _key(wizard, "move")
    wizard._add_keyframe()
    assert all(len(wizard.actor_tracks[g]) == 1 for g in gids)

    wizard._select_actor_ids(gids[:1])
    wizard.key_time.setValue(2.0)
    _key(wizard, "say")
    wizard.line_text.setText("Hold the line!")
    wizard.line_duration.setValue(2.5)
    wizard._add_keyframe()
    _key(wizard, "think")
    wizard.line_text.setText("There are so many.")
    wizard.line_duration.setValue(3.0)
    wizard._add_keyframe()

    # A group pick ticks the whole other team as targets.
    wizard._select_actor_ids(gids)
    _key(wizard, "attack")
    team = next(i for i in range(wizard.attack_group.count())
                if str(wizard.attack_group.itemText(i)).startswith("Team: bandits"))
    wizard._check_group(team)
    wizard.attack_duration.setValue(12.0)
    wizard.key_time.setValue(5.0)
    wizard._add_keyframe()

    lines = [e for e in wizard.events if e["type"] in ("say", "think")]
    assert [(e["type"], e["actor"], e["text"], e["duration"]) for e in lines] == [
        ("say", gids[0], "Hold the line!", 2.5), ("think", gids[0], "There are so many.", 3.0)]
    (fight,) = [e for e in wizard.events if e["type"] == "fight"]
    assert fight["attackers"] == gids and sorted(fight["defenders"]) == sorted(bids)
    assert fight["time"] == 5.0 and fight["duration"] == 12.0 and fight["mutual"] is True
    labels = [wizard.key_list.item(i).text() for i in range(wizard.key_list.count())]
    assert any("ATTACK: 3 vs 4" in label for label in labels)


def test_a_cutscene_saves_and_loads_its_equipped_cast_and_keyframes(wizard, main_window):
    from game.entities import Creature, NPC
    npc = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    beast = wizard._create_temporary_actor(_kind(wizard, "+ Creature"))
    npc.properties["inventory"] = [{"id": "potion_heal_minor", "qty": 3}]
    beast.properties["spells"] = [{"id": "frostbite"}]
    wizard._select_actor_ids([npc.properties["id"]])
    _key(wizard, "say")
    wizard.line_text.setText("Begone, foul thing!")
    wizard._add_keyframe()
    wizard.camera_keys = [{"time": 0.0, "pos": [0, 0, 0], "yaw": 0, "pitch": 0, "fov": 90}]
    assert wizard._write_cutscene("story.json")
    from editor import cutscene_wizard
    saved = Path(cutscene_wizard.CUTSCENE_DIR) / "story.json"
    data = json.loads(saved.read_text())
    kinds = {row["definition"]["type"] for row in data["actors"]}
    assert kinds == {"npc", "creature"}

    wizard._delete_temporary_actors()
    wizard._load_cutscene(str(saved))
    loaded = {type(wizard.actor_objects[a]) for a in wizard.actor_meta}
    assert loaded == {NPC, Creature}
    again = wizard.actor_objects[npc.properties["id"]]
    assert again.properties["inventory"] == [{"id": "potion_heal_minor", "qty": 3}]
    assert [e["text"] for e in wizard.events if e["type"] == "say"] == ["Begone, foul thing!"]


def test_a_rename_reaches_every_list_naming_the_cast(wizard, qt_app):
    from PyQt5 import QtWidgets
    npc = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    wizard._create_temporary_actor(_kind(wizard, "+ Creature"))
    wizard._select_actor_ids([npc.properties["id"]])
    qt_app.processEvents()
    name = wizard.actor_panel_host.findChildren(QtWidgets.QLineEdit)[0]
    name.setText("Captain Aldric")
    name.editingFinished.emit()
    targets = [wizard.attack_targets.item(i).text() for i in range(wizard.attack_targets.count())]
    assert "Captain Aldric" in targets
    assert any("Captain Aldric" in wizard.move_to.itemText(i) for i in range(wizard.move_to.count()))
    assert any("Captain Aldric" in wizard.look_at.itemText(i) for i in range(wizard.look_at.count()))
