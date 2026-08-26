"""
Creation wizards for MiniWind entities that need configuring up front.

These are **composed** from the same reusable authoring components used by the
property tabs (:mod:`game.editor_ui`) — the schedule editor and the Aurora-style
dialogue tree — rather than being a second, monolithic panel. A wizard collects
only the *authored* properties; the entity derives the rest (sprite, stats,
faction defaults) from them when it is constructed, so the result stays correct
and the stored data stays text/mod-friendly.

All Qt imports are local so a headless/player process never imports PyQt5. A
wizard returns:

* a ``dict`` of authored properties (place the entity with these), or
* ``None`` if the user cancelled (place nothing), or
* ``{}`` if Qt is unavailable (place the entity with its plain defaults).
"""

from __future__ import annotations


def _qt():
    from PyQt5 import QtWidgets, QtCore
    return QtWidgets, QtCore


class _Holder:
    """A minimal ``thing``-like object so components can bind to a scratch
    properties dict inside a wizard exactly as they do to a real entity."""

    def __init__(self, props=None):
        self.properties = props if props is not None else {}


_FACTIONS = ["player", "villagers", "guards", "bandits", "cultists",
             "wildlife", "monsters"]
_STYLES = ["melee", "bow", "magic"]


def _clean(props: dict) -> dict:
    """Drop empty schedule/dialogue so the entity applies its role defaults."""
    if not props.get("schedule"):
        props.pop("schedule", None)
    if not props.get("dialogue"):
        props.pop("dialogue", None)
    return props


def npc_wizard(parent=None):
    """Configure a new NPC: identity/role/faction/behaviour, then (composed)
    schedule and dialogue-tree components."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return {}
    from .rpg import bestiary
    from . import editor_ui

    holder = _Holder({})
    wiz = QtWidgets.QWizard(parent)
    wiz.setWindowTitle("New NPC — MiniWind")
    wiz.setWizardStyle(QtWidgets.QWizard.ModernStyle)

    # -- Page 1: identity & role --
    p1 = QtWidgets.QWizardPage()
    p1.setTitle("Identity & Role")
    p1.setSubTitle("Who is this townsperson?")
    f1 = QtWidgets.QFormLayout(p1)
    name = QtWidgets.QLineEdit("Villager")
    role = QtWidgets.QComboBox()
    role.addItems(bestiary.roles_of_kind(bestiary.NPC))
    faction = QtWidgets.QComboBox()
    faction.addItems(_FACTIONS)
    faction.setCurrentText("villagers")
    aggr = QtWidgets.QComboBox()
    aggr.addItems(["passive", "defensive", "hostile"])
    combatant = QtWidgets.QCheckBox("Can fight (non-combatants flee instead)")
    style = QtWidgets.QComboBox()
    style.addItems(_STYLES)

    def _role_changed():
        tmpl = bestiary.get(role.currentText())
        if tmpl:
            name.setText(tmpl.name)
            faction.setCurrentText(tmpl.faction)
            aggr.setCurrentText(tmpl.aggression)
            combatant.setChecked(tmpl.aggression in ("defensive", "hostile"))
            style.setCurrentText(tmpl.attack_style)
    role.currentTextChanged.connect(lambda *_: _role_changed())
    _role_changed()

    f1.addRow("Name", name)
    f1.addRow("Role", role)
    f1.addRow("Faction", faction)
    f1.addRow("Aggression", aggr)
    f1.addRow("Combat style", style)
    f1.addRow("", combatant)
    wiz.addPage(p1)

    # -- Page 2: daily schedule (composed component) --
    p2 = QtWidgets.QWizardPage()
    p2.setTitle("Daily Schedule")
    p2.setSubTitle("When and where this NPC works, sleeps and idles. Leave empty "
                   "to use the sensible default for the role.")
    v2 = QtWidgets.QVBoxLayout(p2)
    v2.addWidget(editor_ui.make_schedule_tab(holder))
    wiz.addPage(p2)

    # -- Page 3: dialogue tree (composed component) --
    p3 = QtWidgets.QWizardPage()
    p3.setTitle("Dialogue")
    p3.setSubTitle("Optional conversation tree. You can also edit this later on "
                   "the NPC's Dialogue tab.")
    v3 = QtWidgets.QVBoxLayout(p3)
    v3.addWidget(editor_ui.dialogue_tree_widget(holder, QtWidgets, QtCore))
    wiz.addPage(p3)

    if wiz.exec_() != QtWidgets.QWizard.Accepted:
        return None

    props = dict(holder.properties)  # schedule + dialogue written by components
    props["display_name"] = name.text().strip() or "Villager"
    props["npc_role"] = role.currentText()
    props["faction"] = faction.currentText()
    props["aggression"] = aggr.currentText()
    props["attack_style"] = style.currentText()
    props["combatant"] = combatant.isChecked()
    return _clean(props)


def creature_wizard(parent=None):
    """Configure a new monster/creature: type, faction, combat and loot."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return {}
    from .rpg import bestiary

    wiz = QtWidgets.QWizard(parent)
    wiz.setWindowTitle("New Monster — MiniWind")
    wiz.setWizardStyle(QtWidgets.QWizard.ModernStyle)

    page = QtWidgets.QWizardPage()
    page.setTitle("Creature")
    page.setSubTitle("A monster or wild animal (combat, loot, respawn).")
    f = QtWidgets.QFormLayout(page)
    name = QtWidgets.QLineEdit("Wolf")
    role = QtWidgets.QComboBox()
    role.addItems(bestiary.roles_of_kind(bestiary.CREATURE))
    faction = QtWidgets.QComboBox()
    faction.addItems(_FACTIONS)
    faction.setCurrentText("wildlife")
    aggr = QtWidgets.QComboBox()
    aggr.addItems(["hostile", "defensive", "passive"])
    style = QtWidgets.QComboBox()
    style.addItems(_STYLES)
    health = QtWidgets.QSpinBox()
    health.setRange(1, 100000)
    health.setValue(40)
    loot = QtWidgets.QLineEdit("")
    respawn = QtWidgets.QCheckBox("Respawns when killed")

    def _role_changed():
        tmpl = bestiary.get(role.currentText())
        if tmpl:
            name.setText(tmpl.name)
            faction.setCurrentText(tmpl.faction)
            aggr.setCurrentText(tmpl.aggression)
            style.setCurrentText(tmpl.attack_style)
            health.setValue(int(tmpl.health))
            loot.setText(tmpl.loot or "")
    role.currentTextChanged.connect(lambda *_: _role_changed())
    _role_changed()

    f.addRow("Name", name)
    f.addRow("Creature type", role)
    f.addRow("Faction", faction)
    f.addRow("Aggression", aggr)
    f.addRow("Combat style", style)
    f.addRow("Health", health)
    f.addRow("Loot table", loot)
    f.addRow("", respawn)
    wiz.addPage(page)

    if wiz.exec_() != QtWidgets.QWizard.Accepted:
        return None
    return {
        "display_name": name.text().strip() or "Creature",
        "npc_role": role.currentText(),
        "faction": faction.currentText(),
        "aggression": aggr.currentText(),
        "attack_style": style.currentText(),
        "health": health.value(),
        "loot": loot.text().strip(),
        "respawn": respawn.isChecked(),
    }
