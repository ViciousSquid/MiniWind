"""The cutscene editor as a design tool for MiniWind: cast the game's NPCs and
creatures, equip them, and give them MOVE / SAY / THINK / ATTACK keyframes --
through the real CutsceneWizard on the real editor window."""

import importlib
import json
from pathlib import Path

import pytest

pytest.importorskip("PyQt5", reason="the cutscene wizard uses Qt")

pytestmark = pytest.mark.qt


@pytest.fixture
def wizard(main_window, qt_app, tmp_path, monkeypatch):
    cutscene_editor = importlib.import_module("game.cutscene_editor")
    from editor import cutscene_wizard
    monkeypatch.setattr(cutscene_wizard, "ACTOR_KINDS", list(cutscene_wizard.ACTOR_KINDS))
    monkeypatch.setattr(cutscene_wizard, "ACTOR_PANELS", list(cutscene_wizard.ACTOR_PANELS))
    monkeypatch.setattr(cutscene_wizard, "ACTOR_TYPES", set(cutscene_wizard.ACTOR_TYPES))
    monkeypatch.setattr(cutscene_wizard, "ACTOR_CLASSES", dict(cutscene_wizard.ACTOR_CLASSES))
    monkeypatch.setattr(cutscene_wizard, "TOP_DOWN_CAMERA", cutscene_wizard.TOP_DOWN_CAMERA)
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
    entities = importlib.import_module("game.entities")
    Creature, NPC = entities.Creature, entities.NPC
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
    entities = importlib.import_module("game.entities")
    Creature, NPC = entities.Creature, entities.NPC
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
    raw = saved.read_text()
    assert "\n" not in raw and ": " not in raw.split('"text"')[0]   # minified
    data = json.loads(raw)
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


# -- authoring in the map, RTS style -------------------------------------------
def _company(wizard, kind, n, group, x0):
    import glm
    out = []
    for i in range(n):
        a = wizard._create_temporary_actor(_kind(wizard, kind))
        a.pos = glm.vec3(x0 + (i % 3) * 70.0, 0.0, (i // 3) * 90.0)
        a.properties["brush_group"] = group
        out.append(a)
    wizard._refresh_actor_lists()
    return out


def _ids(actors):
    return [a.properties["id"] for a in actors]


def test_the_open_editor_is_the_views_cutscene_author(wizard, main_window, qt_app):
    assert main_window.cutscene_author is wizard
    wizard.hide()
    qt_app.processEvents()
    assert main_window.cutscene_author is None
    wizard.show()
    qt_app.processEvents()


def test_an_attack_on_anyone_in_a_group_takes_the_group_ctrl_just_one(wizard):
    guards = _company(wizard, "+ NPC", 6, "Guards", 0.0)
    brigands = _company(wizard, "+ Creature", 5, "Brigands", 900.0)
    wizard._select_actor_ids(_ids(guards))
    wizard._arm_pick("attack", _ids(guards))
    assert wizard.pick_armed()
    wizard.pick_click(brigands[2], None)
    (fight,) = [e for e in wizard.events if e["type"] == "fight"]
    assert fight["attackers"] == _ids(guards) and sorted(fight["defenders"]) == sorted(_ids(brigands))
    wizard._arm_pick("attack", _ids(guards))
    wizard.pick_click(brigands[2], None, ctrl=True)
    assert [e["defenders"] for e in wizard.events if e["type"] == "fight"][-1] == [_ids(brigands)[2]]


def test_clicking_a_group_member_selects_the_group(wizard):
    guards = _company(wizard, "+ NPC", 4, "Guards", 0.0)
    loner = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    wizard.select_from_view(guards[1])
    assert sorted(wizard._current_actor_ids()) == sorted(_ids(guards))
    wizard.select_from_view(loner, add=True)
    assert set(wizard._current_actor_ids()) == set(_ids(guards)) | {loner.properties["id"]}


def test_a_move_drops_a_pin_and_the_company_keeps_its_shape(wizard):
    guards = _company(wizard, "+ NPC", 3, "Guards", 0.0)        # x = 0, 70, 140
    wizard._select_actor_ids(_ids(guards))
    wizard.key_time.setValue(2.0)
    wizard._arm_pick("move", _ids(guards))
    wizard.pick_click(None, [1000.0, 0.0, 500.0])
    xs = [wizard.actor_tracks[g][0]["pos"][0] for g in _ids(guards)]
    assert xs == [930.0, 1000.0, 1070.0]                       # same spacing, centred on the pin
    assert all(wizard.actor_tracks[g][0]["time"] == 2.0 for g in _ids(guards))
    from editor import cutscene_intents
    (pin,) = [i for i in cutscene_intents.intents(wizard) if i.kind == "move"]   # one arrow, one pin
    assert pin.dst == (1000.0, 0.0, 500.0) and len(pin.ghosts) == 3 and "3 actors" in pin.label


def test_a_line_points_at_who_it_is_said_to(wizard):
    import glm
    cap, other = (wizard._create_temporary_actor(_kind(wizard, "+ NPC")) for _ in range(2))
    other.pos = glm.vec3(float(cap.pos[0]) + 300.0, float(cap.pos[1]), float(cap.pos[2]))
    wizard._arm_pick("say", [cap.properties["id"]], text="Hold the line!")
    wizard.pick_click(other, None)
    (line,) = [e for e in wizard.events if e["type"] == "say"]
    assert line["to"] == other.properties["id"] and line["text"] == "Hold the line!"
    from editor import cutscene_intents
    (intent,) = [i for i in cutscene_intents.intents(wizard) if i.kind == "say"]
    assert intent.head and intent.src != intent.dst


def test_a_big_battle_is_one_arrow_a_small_one_an_arrow_a_pair(wizard):
    from editor import cutscene_intents
    guards = _company(wizard, "+ NPC", 6, "Guards", 0.0)
    brigands = _company(wizard, "+ Creature", 5, "Brigands", 900.0)
    wizard.events.append({"time": 3.5, "type": "fight", "duration": 10.0,
                          "attackers": _ids(guards), "defenders": _ids(brigands), "mutual": True})
    (big,) = [i for i in cutscene_intents.intents(wizard) if i.kind == "attack"]
    assert big.src_group is not None and big.both and "6 vs 5" in big.label
    wizard.events[:] = [{"time": 1.0, "type": "fight", "duration": 5.0,
                         "attackers": _ids(guards[:2]), "defenders": _ids(brigands[:1]), "mutual": False}]
    small = [i for i in cutscene_intents.intents(wizard) if i.kind == "attack"]
    assert len(small) == 2 and all(i.src_group is None and not i.both for i in small)


def test_the_scrubber_shows_the_moment_but_never_moves_where_the_cutscene_starts(wizard):
    import glm
    hero = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    hero.pos = glm.vec3(0.0, 0.0, 0.0)
    aid = hero.properties["id"]
    wizard.actor_tracks[aid] = [{"time": 0.0, "pos": [0.0, 0.0, 0.0], "yaw": 0.0},
                                {"time": 4.0, "pos": [400.0, 0.0, 0.0], "yaw": 0.0}]
    wizard.scrub(2.0)
    assert 150.0 < float(hero.pos[0]) < 250.0 and wizard.key_time.value() == 2.0
    from PyQt5 import QtCore
    assert wizard.scrub_key(QtCore.Qt.Key_Right)
    assert abs(wizard._preview_time - 2.1) < 1e-6
    assert wizard.scrub_key(QtCore.Qt.Key_Right, shift=True)      # the next keyframe
    assert wizard._preview_time == 4.0
    wizard.camera_keys = [{"time": 0.0, "pos": [0, 0, 0], "yaw": 0, "pitch": 0, "fov": 90}]
    data_pos = None
    assert wizard._validate_for_save()
    data_pos = wizard._actor_definition(aid)["pos"]
    assert data_pos == [0.0, 0.0, 0.0]                            # back at its start


def test_new_actors_never_stand_on_top_of_each_other(wizard):
    made = [wizard._create_temporary_actor(_kind(wizard, "+ NPC")) for _ in range(8)]
    wizard._select_actor_ids([made[0].properties["id"]])
    wizard._duplicate_selected_actors()
    wizard._duplicate_selected_actors()
    actors = [wizard.actor_objects[a] for a in wizard.actor_meta]
    pts = [(float(a.pos[0]), float(a.pos[2])) for a in actors]
    gap = wizard.ACTOR_SPACING - 1e-6
    assert all((x1 - x2) ** 2 + (z1 - z2) ** 2 >= gap * gap
               for i, (x1, z1) in enumerate(pts) for (x2, z2) in pts[i + 1:])


def test_face_turns_the_selected_actors_toward_what_is_clicked(wizard):
    import glm
    a = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    b = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    a.pos = glm.vec3(0.0, 0.0, 0.0)
    b.pos = glm.vec3(500.0, 0.0, 0.0)                 # due +X of a
    wizard._arm_pick("face", [a.properties["id"]])
    wizard.pick_click(b, None)
    assert a.properties["angle"] == pytest.approx(90.0)
    wizard._arm_pick("face", [a.properties["id"]])
    wizard.pick_click(None, [0.0, 0.0, -300.0])       # a spot due -Z
    assert a.properties["angle"] == pytest.approx(180.0)


def test_the_facing_dial_turns_every_selected_actor(wizard, qt_app):
    from PyQt5 import QtWidgets
    actors = [wizard._create_temporary_actor(_kind(wizard, "+ Creature")) for _ in range(3)]
    wizard._select_actor_ids([x.properties["id"] for x in actors])
    qt_app.processEvents()
    dial = next(sb for sb in wizard.actor_panel_host.findChildren(QtWidgets.QSpinBox)
                if sb.suffix() == "°")
    dial.setValue(270)
    assert all(x.properties["angle"] == 270.0 for x in actors)


def test_a_cutscene_keeps_its_actors_facing(wizard):
    import glm
    hero = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    hero.properties["angle"] = 135.0
    wizard._select_actor_ids([hero.properties["id"]])
    wizard.key_kind.setCurrentIndex(wizard.key_kind.findData("move"))
    wizard._add_keyframe()
    aid = hero.properties["id"]
    assert wizard.actor_tracks[aid][0]["yaw"] == 135.0
    assert wizard._actor_definition(aid)["yaw"] == 135.0


def test_miniwind_camera_shots_look_straight_down(wizard, main_window):
    from editor import cutscene_wizard
    assert cutscene_wizard.TOP_DOWN_CAMERA
    camera = main_window.view_3d.camera
    camera.pitch, camera.yaw = -30.0, 45.0
    wizard._capture_camera_keyframe()
    (shot,) = wizard.camera_keys
    assert shot["pitch"] == cutscene_wizard.TOP_DOWN_PITCH and shot["yaw"] == 0.0
    assert wizard._build_cutscene_data()["settings"]["camera"] == "top_down"


def test_cast_is_offered_only_for_an_actor_with_spells_and_lists_its_own(wizard):
    plain = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    plain.properties["spells"] = []
    mage = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    mage.properties["spells"] = [{"id": "resurrection"}, {"id": "firebolt"}]
    assert wizard._spells_of(plain) == []
    names = dict(wizard._spells_of(mage))
    assert set(names) == {"resurrection", "firebolt"}
    other = wizard._create_temporary_actor(_kind(wizard, "+ Creature"))
    wizard._arm_pick("cast", [mage.properties["id"]], spell="resurrection")
    wizard.pick_click(other, None)
    (cast,) = [e for e in wizard.events if e["type"] == "cast"]
    assert cast["spell"] == "resurrection" and cast["target"] == other.properties["id"]


def test_a_rule_is_recorded_and_reads_plainly(wizard):
    hero = wizard._create_temporary_actor(_kind(wizard, "+ NPC"))
    hero.properties["name"] = hero.properties["display_name"] = "Aldric"
    wizard.actors_changed([hero])
    rule = wizard._rule_event(hero.properties["id"], "health_below", 40, "", "flee")
    assert rule == {"time": 0.0, "type": "rule", "actor": hero.properties["id"],
                    "if": "health_below", "value": 40.0, "then": "flee"}
    assert wizard._describe(rule) == "Aldric: when its health falls below 40 → FLEE"


def test_selecting_any_npc_in_the_map_casts_it(wizard, main_window):
    NPC = importlib.import_module("game.entities").NPC
    villager = NPC(pos=[300.0, 0.0, 300.0], properties={"npc_role": "villager", "name": "Tam"})
    main_window.state.things.append(villager)
    main_window.set_selected_objects([villager])
    wizard.sync_selection_from_editor()
    aid = villager.properties["id"]
    assert aid in wizard.actor_meta and not wizard.actor_meta[aid]["spawn"]   # a real map actor
    assert wizard._current_actor_ids() == [aid]
