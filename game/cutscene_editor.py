"""MiniWind's actors in Fio's cutscene editor (editor/cutscene_wizard.py).

The cutscene editor casts MiniWind's own NPCs and creatures -- ``+ NPC`` and
``+ Creature`` -- so a cutscene's actors are the game's actors: they look,
fight and die as the game's do. Selecting actors in the cast shows this panel:

* **Who they are**: name (one actor), role, team, temperament;
* **How they fight**: health, damage, attack style (melee, bow, magic), the
  weapon in the main hand and what is in the off hand (a shield, a second
  weapon, a torch);
* **What they carry and cast**: the editor's own Inventory and Spells tabs
  for the actor (one actor at a time).

With several actors selected, a change applies to all of them: raise a
company, select it, and arm it in one go. A role change remakes the actor from
the role's template (its art, stats and default kit), keeping its name, place,
team and anything carried.

Registered by :func:`register` from the editor integration (game/integration.py).
"""

from __future__ import annotations

#: The styles an actor can lead with (game.combat_loadout).
STYLES = (("Melee", "melee"), ("Ranged (bow)", "bow"), ("Magic", "magic"))
#: The weapon an actor is handed when given a style it has nothing for.
STYLE_WEAPON = {"melee": "iron_shortsword", "bow": "hunting_bow", "magic": "apprentice_staff"}
#: The attack spell a caster is taught when it knows none.
STARTER_SPELL = "firebolt"
TEAMS = ("guards", "villagers", "bandits", "cultists", "monsters", "wildlife")
AGGRESSION = ("hostile", "defensive", "passive")
#: What a role's template fills in: dropped on a role change, so the new role's
#: own art, stats and kit take their place.
ROLE_FIELDS = ("custom_idle", "custom_shoot", "custom_dead", "portrait", "sprite_width",
               "sprite_height", "health", "max_health", "damage", "attack_style",
               "equipped_weapon", "offhand_weapon", "aggression", "loot", "xp_value",
               "creature_level", "move_speed", "sight_range", "schedule", "spells",
               "hand_spells", "merchant", "merchant_gold", "merchant_gold_base", "head",
               "display_name", "can_hear", "view_cone", "monster_type")


def register():
    """Give Fio's cutscene editor MiniWind's actors and their panel."""
    from editor import cutscene_wizard as wizard
    from .entities import Creature, NPC
    wizard.register_actor_kind("+ NPC", NPC, {"npc_role": "guard"},
                               replace_default=True, entity_type="npc")
    wizard.register_actor_kind("+ Creature", Creature, {"npc_role": "bandit"},
                               entity_type="creature")
    wizard.register_actor_panel(actor_panel)


# ---------------------------------------------------------------------------
# What the panel offers (pure: no Qt), so tests and tools can use it too.
# ---------------------------------------------------------------------------
def kind_of(actor) -> str:
    return str(getattr(actor, "properties", {}).get("type", "") or "")


def roles_for(kind):
    import game.rpg.bestiary as bestiary
    return list(bestiary.roles_of_kind(kind)) if kind in ("npc", "creature") else []


def weapons():
    """``[(name, id)]`` of every weapon, by name."""
    import game.rpg.items as items
    return sorted((d.name, i) for i, d in items.ITEMS.items()
                  if d.category == items.WEAPON and i != "fist")


def offhand_choices():
    """``[(name, id)]`` for the off hand: shields, one-handed weapons, a torch."""
    import game.rpg.equipment as equipment
    import game.rpg.items as items
    shields = sorted((f"{d.name} (shield)", i) for i, d in items.ITEMS.items()
                     if d.get("slot") == items.SLOT_SHIELD)
    lights = sorted((d.name, i) for i, d in items.ITEMS.items() if items.is_light_source(d))
    blades = sorted((d.name, i) for i, d in items.ITEMS.items()
                    if d.category == items.WEAPON and i != "fist"
                    and not equipment.is_two_handed(d)
                    and _weapon_style(i) == "melee")
    return shields + blades + lights


def _weapon_style(item_id):
    try:
        import game.combat_styles as combat_styles
        return combat_styles.weapon_attack_style(item_id)
    except Exception:
        return None


def set_style(props, style) -> None:
    """Lead with *style*: and be equipped for it -- a weapon for that style in
    hand if the one there is not, and an attack spell for a caster that
    knows none (both changeable after)."""
    props["attack_style"] = style
    if _weapon_style(props.get("equipped_weapon")) != style:
        props["equipped_weapon"] = STYLE_WEAPON[style]
        if style == "bow" and props.get("offhand_weapon"):
            props["offhand_weapon"] = ""      # a bow takes both hands
    if style == "magic":
        import game.rpg.magic as magic
        spells = props.get("spells") if isinstance(props.get("spells"), list) else []
        attack = [e for e in spells
                  if magic.get(e.get("id") if isinstance(e, dict) else e) is not None
                  and magic.get(e.get("id") if isinstance(e, dict) else e).delivery == magic.PROJECTILE]
        if not attack:
            spells.append({"id": STARTER_SPELL})
            props["spells"] = spells
            props.pop("hand_spells", None)    # readied afresh from the spells


def remake_with_role(actor, role):
    """A new actor of *actor*'s class in *role*: the role's art, stats and
    kit, keeping its id, name, place, facing, team and what it carries."""
    props = {k: v for k, v in actor.properties.items()
             if k not in ROLE_FIELDS and k != "_io_connections"}
    props["npc_role"] = role
    twin = type(actor)(pos=list(actor.pos), properties=props)
    twin.angle = float(getattr(actor, "angle", 0.0))
    return twin


# ---------------------------------------------------------------------------
# The panel.
# ---------------------------------------------------------------------------
def actor_panel(wizard, actors):
    """The panel for *actors* (MiniWind NPCs and creatures), or None."""
    actors = [a for a in actors if kind_of(a) in ("npc", "creature")]
    if not actors:
        return None
    from PyQt5 import QtWidgets
    import game.editor_ui as editor_ui

    first = actors[0].properties
    many = len(actors) > 1
    panel = QtWidgets.QWidget()
    outer = QtWidgets.QVBoxLayout(panel)
    outer.setContentsMargins(0, 0, 0, 0)

    def changed(rebuild=False):
        wizard.actors_changed(actors, rebuild=rebuild)

    def apply(fn, rebuild=False):
        for actor in actors:
            fn(actor.properties)
        changed(rebuild)

    who = QtWidgets.QGroupBox(f"{len(actors)} actors — changes apply to all" if many else "Actor")
    form = QtWidgets.QFormLayout(who)
    if not many:
        name = QtWidgets.QLineEdit(str(first.get("display_name") or first.get("name") or ""))

        def rename():
            text = name.text().strip()
            if text:
                apply(lambda p: p.update(name=text, display_name=text))
        name.editingFinished.connect(rename)
        form.addRow("Name", name)

    kinds = {kind_of(a) for a in actors}
    role = QtWidgets.QComboBox()
    if len(kinds) == 1:
        for r in roles_for(kinds.pop()):
            role.addItem(r.replace("_", " ").title(), r)
        role.setCurrentIndex(max(0, role.findData(first.get("npc_role"))))
    else:
        role.addItem("(NPCs and creatures mixed)", None)
        role.setEnabled(False)

    def change_role(_index):
        new = role.currentData()
        if not new:
            return
        state = wizard.main_window.state
        remade = []
        for actor in actors:
            if actor.properties.get("npc_role") == new:
                remade.append(actor)
                continue
            twin = remake_with_role(actor, new)
            try:
                state.things[state.things.index(actor)] = twin
            except ValueError:
                state.things.append(twin)
            remade.append(twin)
        actors[:] = remade
        try:
            wizard.main_window.set_selected_objects(list(remade))
        except Exception:
            pass
        changed(rebuild=True)
    role.activated.connect(change_role)
    form.addRow("Role", role)

    team = QtWidgets.QComboBox()
    team.setEditable(True)
    team.addItems(TEAMS)
    team.setCurrentText(str(first.get("team") or first.get("faction") or ""))
    team.setToolTip("Who they side with. Battles are set on the Keyframes tab.")

    def set_team():
        text = team.currentText().strip()
        if text:
            apply(lambda p: p.update(team=text, faction=text))
    team.activated.connect(lambda _i: set_team())
    team.lineEdit().editingFinished.connect(set_team)
    form.addRow("Team", team)

    temper = QtWidgets.QComboBox()
    for a in AGGRESSION:
        temper.addItem(a.title(), a)
    temper.setCurrentIndex(max(0, temper.findData(str(first.get("aggression", "")).lower())))
    temper.activated.connect(lambda _i: apply(lambda p: p.update(aggression=temper.currentData())))
    form.addRow("Temperament", temper)
    outer.addWidget(who)

    fight = QtWidgets.QGroupBox("Combat")
    ff = QtWidgets.QFormLayout(fight)
    health = QtWidgets.QSpinBox()
    health.setRange(1, 100000)
    health.setValue(int(float(first.get("max_health", first.get("health", 60)) or 60)))
    health.editingFinished.connect(lambda: apply(lambda p: p.update(
        health=health.value(), max_health=health.value())))
    ff.addRow("Health", health)
    damage = QtWidgets.QSpinBox()
    damage.setRange(0, 10000)
    damage.setValue(int(float(first.get("damage", 6) or 0)))
    damage.editingFinished.connect(lambda: apply(lambda p: p.update(damage=damage.value())))
    ff.addRow("Damage", damage)

    style = QtWidgets.QComboBox()
    for label, value in STYLES:
        style.addItem(label, value)
    style.setCurrentIndex(max(0, style.findData(str(first.get("attack_style", "melee")).lower())))
    style.setToolTip("What they lead with. In a fight each uses what it carries: "
                     "a bow at range, a blade up close, spells if it knows any.")

    main = QtWidgets.QComboBox()
    main.addItem("(bare hands / claws)", "")
    for label, iid in weapons():
        main.addItem(label, iid)
    main.setCurrentIndex(max(0, main.findData(str(first.get("equipped_weapon") or ""))))

    off = QtWidgets.QComboBox()
    off.addItem("(empty)", "")
    for label, iid in offhand_choices():
        off.addItem(label, iid)
    off.setCurrentIndex(max(0, off.findData(str(first.get("offhand_weapon") or ""))))

    def pick_style(_i):
        apply(lambda p: set_style(p, style.currentData()), rebuild=True)
    style.activated.connect(pick_style)
    main.activated.connect(lambda _i: apply(lambda p: p.update(equipped_weapon=main.currentData())))
    off.activated.connect(lambda _i: apply(lambda p: p.update(offhand_weapon=off.currentData())))
    ff.addRow("Attack style", style)
    ff.addRow("Main hand", main)
    ff.addRow("Off hand", off)
    outer.addWidget(fight)

    if many:
        note = QtWidgets.QLabel("Select a single actor to edit what it carries and its spells.")
        note.setWordWrap(True)
        outer.addWidget(note)
        return panel
    kit = QtWidgets.QTabWidget()
    kit.setMinimumHeight(360)
    actor = actors[0]
    for label, factory in (("Inventory" if kind_of(actor) == "npc" else "Loot",
                            editor_ui.make_inventory_tab),
                           ("Spells", editor_ui.make_spells_tab)):
        try:
            tab = factory(actor)
        except Exception as exc:
            tab = QtWidgets.QLabel(f"Unavailable: {exc}")
        if tab is not None:
            kit.addTab(tab, label)
    outer.addWidget(kit)
    return panel
