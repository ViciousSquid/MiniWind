"""The barrel is an oak barrel, and only an oak barrel: the oil drums are gone.

Representation -> Model picks it (the whole preset); a map that still names an
oil drum gets the oak barrel in its place; the asset browser lists neither."""

import os

import pytest

from engine.prop_entity import (BARREL_SETTINGS, DEFAULT_MODEL_PATH, MODEL_PRESETS,
                                Prop, current_model_path, model_preset_name,
                                model_settings, topples_by_default)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OAK = "assets/models/Oak_Barrel.obj"


def test_the_barrel_is_the_oak_barrel_and_its_files_ship():
    assert DEFAULT_MODEL_PATH == OAK
    assert list(MODEL_PRESETS) == ["Oak Barrel", "Ball"]
    assert model_preset_name(OAK) == "Oak Barrel"
    assert topples_by_default(OAK)
    assert model_settings(OAK)["collision_shape"] == BARREL_SETTINGS["collision_shape"]
    for name in ("Oak_Barrel.obj", "Oak_Barrel.mtl", "Oak_Barrel_Texture.png"):
        assert os.path.isfile(os.path.join(ROOT, "assets", "models", name)), name


def test_the_oil_drums_are_gone():
    models = os.listdir(os.path.join(ROOT, "assets", "models"))
    assert not [n for n in models if n.lower().startswith("oil_drum")]


@pytest.mark.parametrize("old", ["assets/models/Oil_Drum.obj",
                                 "assets\\models/Oil_Drum_Grey.obj",
                                 "Oil_Drum.obj"])
def test_a_map_naming_an_oil_drum_gets_the_oak_barrel(old):
    assert current_model_path(old) == OAK
    prop = Prop(properties={"name": "barrel", "render_mode": "model",
                            "model_path": old, "explosive": True})
    assert prop.properties["model_path"] == OAK
    assert prop.properties["topples"] is True
    assert model_preset_name(old) == "Oak Barrel"


def test_other_models_are_left_alone():
    assert current_model_path("assets/models/ball.obj") == "assets/models/ball.obj"
    assert current_model_path("") == ""


def test_the_oak_barrel_keeps_the_old_drums_bounds():
    """Same collision box, same physics: 45.64 across, 65.18 tall, origin on
    the floor."""
    with open(os.path.join(ROOT, OAK), encoding="utf-8") as f:
        v = [tuple(map(float, line.split()[1:4])) for line in f if line.startswith("v ")]
    lo = [min(p[i] for p in v) for i in range(3)]
    hi = [max(p[i] for p in v) for i in range(3)]
    assert [h - l for l, h in zip(lo, hi)] == pytest.approx([45.64271, 65.181947, 45.64271], abs=1e-3)
    assert lo[1] == pytest.approx(0.0, abs=1e-3)


@pytest.mark.qt
def test_switching_to_model_picks_the_oak_barrel(qt_app):
    pytest.importorskip("PyQt5")
    from PyQt5.QtWidgets import QComboBox
    from editor.main_window import MainWindow
    window = MainWindow(ROOT)
    try:
        prop = Prop(properties={"name": "thing", "render_mode": "billboard"})
        prop.properties.pop("model_path", None)
        window.state.things.append(prop)
        panel = window.property_editor
        panel.current_object = prop
        panel.populate_for_thing(prop)
        mode = next(c for c in panel.findChildren(QComboBox)
                    if [c.itemText(i) for i in range(c.count())] == ["Model", "Sprite"])
        mode.setCurrentText("Model")
        assert prop.properties["model_path"] == OAK
        assert prop.properties["topples"] is True
        assert panel._widgets["prop_model_preset_combo"].currentText() == "Oak Barrel"
        assert "prop_model_variant_combo" not in panel._widgets
    finally:
        window.unsaved_changes = False
        window.close()
        window.deleteLater()
        qt_app.processEvents()
