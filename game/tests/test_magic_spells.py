"""
Headless tests for the spell colour model and data-driven spell load/save that
back the projectile-colour feature and the Tools ▸ Spell Editor.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import magic


def test_element_colours_are_distinct_and_have_a_default():
    assert magic.element_color("fire") == [255, 140, 50]
    assert magic.element_color("frost") != magic.element_color("fire")
    # unknown element falls back to the arcane default
    assert magic.element_color("nonsense") == magic.DEFAULT_SPELL_COLOR


def test_spell_colour_defaults_to_element_but_override_wins():
    frost = magic.Spell("t_frost", "T", magic.sk.DESTRUCTION, 10, magic.PROJECTILE,
                        [{"kind": "damage_health", "magnitude": 5}], element="frost")
    assert frost.color == magic.element_color("frost")
    custom = magic.Spell("t_c", "T", magic.sk.DESTRUCTION, 10, magic.PROJECTILE,
                         [], element="fire", color=[1, 2, 3])
    assert custom.color == [1, 2, 3]          # explicit override beats element


def test_spell_damage_sums_damage_effects_only():
    sp = magic.Spell("t_d", "T", magic.sk.DESTRUCTION, 10, magic.PROJECTILE,
                     [{"kind": "damage_health", "magnitude": 12},
                      {"kind": "restore_health", "magnitude": 99}])
    assert sp.damage == 12


def test_to_dict_from_dict_roundtrip():
    sp = magic.get("firebolt")
    d = sp.to_dict()
    back = magic.Spell.from_dict(d)
    assert back.id == sp.id
    assert back.name == sp.name
    assert back.element == sp.element
    assert back.color == sp.color
    assert back.damage == sp.damage


def test_castable_spells_lists_projectile_and_damage_spells():
    from game.editor_ui import _castable_spells
    ids = {sid for sid, _label in _castable_spells()}
    assert "firebolt" in ids and "frostbite" in ids
    # a self-only heal is not castable as a bolt
    assert "heal_minor" not in ids


def test_save_and_load_custom_spells_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "spells.json"
    monkeypatch.setattr(magic, "_spells_data_path", lambda: str(path))

    rows = [{
        "id": "gibblast", "name": "Gib Blast", "school": magic.sk.DESTRUCTION,
        "cost": 40, "delivery": magic.PROJECTILE,
        "effects": [{"kind": "damage_health", "magnitude": 999, "duration": 0}],
        "element": "fire", "projectile_speed": 1200.0, "color": [0, 255, 0],
    }]
    assert magic.save_custom_spells(rows) is True
    assert path.exists()

    # save also applies to the live registry
    sp = magic.get("gibblast")
    assert sp is not None
    assert sp.color == [0, 255, 0]      # explicit green override, not fire default
    assert sp.damage == 999

    # a fresh load from the same file re-registers it
    magic.SPELLS.pop("gibblast", None)
    n = magic.load_custom_spells()
    assert n == 1
    assert magic.get("gibblast") is not None


def test_load_missing_file_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(magic, "_spells_data_path",
                        lambda: str(tmp_path / "does_not_exist.json"))
    assert magic.load_custom_spells() == 0


def test_instadeath_spell_is_always_red_and_kills_instantly():
    sp = magic.get("instadeath")
    assert sp is not None
    # Always red — an explicit override, independent of its element.
    assert sp.color == [255, 0, 0]
    # Delivered as a projectile and deals overwhelming damage (one-shot + gib).
    assert sp.delivery == magic.PROJECTILE
    assert sp.damage >= 99999
    # It's offered to NPCs as a castable projectile spell.
    from game.editor_ui import _castable_spells
    assert "instadeath" in {sid for sid, _ in _castable_spells()}
