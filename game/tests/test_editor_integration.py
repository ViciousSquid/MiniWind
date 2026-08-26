"""
Headless checks for MiniWind's editor authoring wiring.

The Qt widgets themselves (property tabs, dialogue tree, wizards) need PyQt5 and
so can't run here, but the *wiring* they depend on is data and can be verified:
the built-in entities are registered, their property schemas are grouped into
Aurora-style sections, and creation wizards are installed and degrade gracefully
without Qt.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import game
from plugins.manager import get_manager


def _mgr():
    game.install()
    return get_manager()


def test_npc_and_creature_are_distinct_registered_entities():
    m = _mgr()
    labels = {label: cls.__name__ for _g, label, cls in m.builtin_menu_entries()}
    assert labels.get("NPC") == "NPC"
    assert labels.get("Monster / Creature") == "Creature"
    assert m.entity_class_for_type("npc").__name__ == "NPC"
    assert m.entity_class_for_type("creature").__name__ == "Creature"


def test_schemas_are_grouped_into_sections():
    m = _mgr()
    npc = m.property_schema_for("npc") or []
    groups = [s.group for s in npc if getattr(s, "group", "")]
    # Aurora-style sections are present and cover the key facets
    for section in ("IDENTITY", "STATS", "FACTION", "BEHAVIOUR", "SCHEDULE"):
        assert section in groups, f"missing NPC section {section}"
    # combat capability lives in BEHAVIOUR, separate from faction
    combatant = [s for s in npc if s.name == "combatant"]
    assert combatant and combatant[0].group == "BEHAVIOUR"
    creature = m.property_schema_for("creature") or []
    assert "LOOT" in [s.group for s in creature if getattr(s, "group", "")]


def test_creation_wizards_registered_and_headless_safe():
    m = _mgr()
    npc_w = m.entity_wizard_for("npc")
    cre_w = m.entity_wizard_for("creature")
    assert callable(npc_w) and callable(cre_w)
    # Without Qt a wizard returns {} → the entity is placed with plain defaults
    # (never None, which would mean "cancelled").
    assert npc_w(None) == {}
    assert cre_w(None) == {}


def test_game_settings_is_registered_as_a_singleton():
    m = _mgr()
    # A map may hold at most one Game Settings marker.
    assert m.is_singleton_entity("miniwindsettings") is True
    # Type-name normalisation means the underscored form matches too.
    assert m.is_singleton_entity("miniwind_settings") is True
    # Ordinary entities are not limited.
    assert m.is_singleton_entity("npc") is False
    assert m.is_singleton_entity("creaturespawn") is False


def test_miniwind_registers_generic_editor_extension_providers():
    # MiniWind supplies its editor extensions through the generic registration
    # surface, so generic Fio editor/engine code carries no MiniWind knowledge.
    m = _mgr()

    # KeyValue quick-insert suggestions (quest/flag keys) come from the game.
    kv = m.kv_key_suggestions()
    keys = {row[1] for row in kv}
    assert "flag" in keys
    assert any(k.startswith("quest.") for k in keys)

    # The debug inspector snapshot is provided by the game, not the engine.
    class _T:
        properties = {"type": "npc", "npc_role": "guard", "faction": "guards",
                      "sched_state": "WORKING"}
    snap = m.inspector_snapshot(_T(), {}, None)
    assert snap and snap["title"].startswith("Guard")
    assert snap["tasks"]        # the rich mental-state view, from the game


def test_markers_have_distinct_per_kind_sprites():
    # The 2D view now uses each marker's own sprite (custom_idle) so markers of
    # different kinds look different — matching the 3D view.
    from game import entities
    seen = {}
    for kind in ("home", "bed", "forge", "shop", "farm", "guardpost"):
        mk = entities.Marker(pos=[0, 0, 0], properties={"marker_kind": kind})
        seen[kind] = mk.properties.get("custom_idle")
    # every kind resolves to a distinct sprite path
    assert len(set(seen.values())) == len(seen), seen
    assert entities.marker_sprite("forge").endswith("marker_forge.png")
