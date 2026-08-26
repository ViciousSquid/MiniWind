"""
MiniWind — the integrated fantasy RPG, built natively into this Fio branch.

This module is the **native game host**: the seam between the pure RPG game core
(:mod:`game.rpg`) and the live Fio scene. It registers the game's entities and
their editor properties/I/O, installs the runtime session on play, drives all
input (top-down melee & archery combat, spellcasting, the inventory/character/
journal screens, dialogue and trade) each tick, and paints the HUD, dialogue box
and menus through the ``render.overlay`` hook.

Unlike a Fio *plugin*, :class:`MiniwindGame` is **not** discovered on disk, is
never toggled on/off, carries no ``api_version``/``requires`` and never appears
in the Plugins menu. It is a first-class part of the branch, installed by the
application bootstrap (see :func:`game.install`) through the manager's generic
built-in-game surface. The plugin *machinery* remains generic Fio technology
that other plugins (e.g. BigWorld) still use — MiniWind simply no longer wears
it. Every rule and every stat lives in the engine-agnostic :mod:`game.rpg` core
and the :mod:`game.ui` screens; this file is just the seam.
"""

from __future__ import annotations

# Generic Fio API helpers (entity-I/O and property descriptors, the per-tick
# context type, and key-name translation). These are engine-side utilities, not
# the plugin lifecycle: MiniWind uses them the way any native game layer would.
from plugins.api import TickContext, io_def, prop, key_code

from .runtime import MiniwindSession, TALK_RADIUS

# key vocabulary we translate raw Qt codes back into (for menu/dialogue nav)
_NAV_NAMES = (list("abcdefghijklmnopqrstuvwxyz") + [str(d) for d in range(0, 10)] +
              ["up", "down", "left", "right", "return", "enter", "escape",
               "space", "tab", "shift", "backspace"])

# action bindings (single-press unless noted)
K_ATTACK = "f"
K_CAST = "r"
K_BLOCK = "b"          # held
K_INTERACT = "e"       # talk to / trade with / use the nearest NPC
K_SNEAK = "v"
K_NEXT_SPELL = "x"
K_HEAL = "h"
K_INVENTORY = "i"
K_CHARACTER = "c"
K_JOURNAL = "j"
K_SPELLS = "p"
K_LEVELUP = "l"
K_MAP = "m"


# ---------------------------------------------------------------------------
# MiniWind editor-extension providers (registered through the generic EditorAPI
# so generic Fio editor/engine code stays game-agnostic).
# ---------------------------------------------------------------------------
def _miniwind_kv_suggestions():
    """Key/value quick-insert templates for the LogicKeyValueStore editor.

    Returns ``(menu_label, key, default_value, tooltip)`` rows for the store keys
    MiniWind actually uses — quest ``state``/``stage`` (one pair per authored
    quest, plus an editable ``<id>`` template) and a generic flag. Fully guarded:
    if the data layer isn't importable this returns ``[]``."""
    out = [
        ("Generic flag  (flag = true)", "flag", "true",
         "A simple on/off flag other entities/dialogue can test."),
        ("Quest state  (quest.<id>.state)", "quest.<id>.state", "active",
         "Quest lifecycle: active / complete / failed. Replace <id>."),
        ("Quest stage  (quest.<id>.stage)", "quest.<id>.stage", "0",
         "Current stage index of a quest. Replace <id>."),
    ]
    try:
        from game import data
        quests = data.load("quests") or {}
        for qid in sorted(quests.keys()):
            out.append((f"Quest '{qid}' state", f"quest.{qid}.state", "active",
                        f"Lifecycle flag for quest '{qid}'."))
            out.append((f"Quest '{qid}' stage", f"quest.{qid}.stage", "0",
                        f"Stage index for quest '{qid}'."))
    except Exception:
        pass
    return out


def _miniwind_inspector_snapshot(thing, monster_state, logic_thread):
    """Build the MiniWind mental-state snapshot for the debug inspector popup.

    Wraps :func:`game.mental_state.snapshot`, pulling the live session off the
    logic thread here so the engine never needs MiniWind knowledge."""
    try:
        from . import mental_state
        session = getattr(logic_thread, "_miniwind", None)
        return mental_state.snapshot(thing, monster_state=monster_state, session=session)
    except Exception:
        return None


class MiniwindGame:
    """The native MiniWind game layer.

    Exposes the same lifecycle surface a plugin would (``register`` /
    ``register_runtime`` / ``connect`` / ``on_play_start`` / ``on_tick`` /
    ``on_play_stop``) so it slots into Fio's generic engine extension points,
    but it is **not** a :class:`~plugins.api.FioPlugin`: no discovery, no
    enable/disable, no ``api_version``/``requires``, no Plugins-menu entry. The
    manager installs it as a built-in game (see
    :meth:`~plugins.manager.PluginManager.register_builtin_game`).
    """

    # Descriptive identity used by the editor palette/menus and log lines.
    # These are plain attributes, not plugin metadata: there is deliberately no
    # ``enabled``/``api_version``/``requires`` here.
    name = "miniwind"
    version = "1.0.0"
    description = ("MiniWind — a small living fantasy RPG: character creation, "
                   "skills, magic, quests, factions, schedules, melee & archery.")
    category = "MiniWind"
    # Marks this object as a built-in game to the manager's shared registries so
    # its entities surface under a native MiniWind menu, never the Plugins menu.
    is_builtin_game = True

    # ------------------------------------------------------------------ load
    def register(self, api):
        from .entities import (NPC, Creature, GameSettings, MiniwindSettings,
                               Marker, MARKER_KINDS, ItemPickup, CreatureSpawn,
                               MiniwindTrigger, Spellbook, SPELLBOOK_COVERS)
        from .rpg import bestiary
        from .rpg import items as rpg_items
        from .rpg import magic as rpg_magic
        api.register_entity(NPC, menu_label="NPC")
        api.register_entity(Creature, menu_label="Monster / Creature")
        api.register_entity(ItemPickup, menu_label="Item")
        api.register_entity(Spellbook, menu_label="Spellbook")
        api.register_entity(MiniwindTrigger, menu_label="Trigger")
        api.register_entity(CreatureSpawn, menu_label="Spawn Point")
        api.register_entity(Marker, menu_label="Path / Schedule Marker")
        api.register_entity(GameSettings, menu_label="Game Settings")
        # A map may hold at most one Game Settings marker — it configures the
        # single game clock / start scenario, so a second one is meaningless.
        try:
            api.register_singleton_entity("miniwindsettings")
        except Exception:
            pass
        item_ids = sorted(rpg_items.ITEMS.keys())
        factions = ["player", "villagers", "guards", "bandits", "cultists",
                    "wildlife", "monsters"]
        styles = ["melee", "bow", "magic"]
        npc_roles = bestiary.roles_of_kind(bestiary.NPC)
        creature_roles = bestiary.roles_of_kind(bestiary.CREATURE)
        api.register_properties("itempickup", [
            prop("item_id", "enum", "Item", default="gold", choices=item_ids,
                 group="ITEM", help="Which item this pickup grants."),
            prop("quantity", "int", "Quantity", default=1, min=1, max=100000,
                 group="ITEM"),
            prop("pickup_radius", "float", "Pickup radius", default=60.0, min=1.0,
                 max=100000.0, group="ITEM"),
            prop("respawn", "bool", "Respawns after taken", default=False,
                 group="ITEM"),
        ])
        spell_ids = sorted(rpg_magic.SPELLS.keys())
        api.register_properties("spellbook", [
            prop("spell", "enum", "Teaches spell", default="flare",
                 choices=spell_ids, group="SPELLBOOK",
                 help="The spell the player learns on reading this book."),
            prop("cover", "enum", "Cover", default="red",
                 choices=list(SPELLBOOK_COVERS), group="SPELLBOOK",
                 help="Cover colour / sprite."),
            prop("title", "string", "Title", default="", group="SPELLBOOK",
                 help="Optional shown title (defaults to the spell's name)."),
            prop("pickup_radius", "float", "Pickup radius", default=70.0,
                 min=1.0, max=100000.0, group="SPELLBOOK"),
            prop("respawn", "bool", "Respawns after read", default=False,
                 group="SPELLBOOK"),
        ])
        # The spawn point's rich configuration (what to spawn, group faction and
        # per-member inventory) lives in a dedicated, guided "Spawn" tab
        # (game.editor_ui.make_spawn_tab) instead of a wall of raw enums, so the
        # creature-vs-NPC choice is clear and the role list is filtered to the
        # chosen kind. Only the plain scalar knobs stay on the Properties tab.
        api.register_properties("creaturespawn", [
            prop("count", "int", "Count", default=1, min=1, max=100, group="SPAWN",
                 help="How many to spawn — 2+ makes a same-faction group."),
            prop("spawn_radius", "float", "Scatter radius", default=0.0, min=0.0,
                 max=100000.0, group="SPAWN",
                 help="Members are scattered randomly within this radius of the "
                      "point (0 = all exactly on the point)."),
            prop("respawn", "bool", "Respawns the group", default=False,
                 group="SPAWN"),
            prop("hidden_in_game", "bool", "Hidden during play", default=True,
                 group="SPAWN"),
        ])
        api.register_properties("miniwindtrigger", [
            prop("trigger_radius", "float", "Trigger radius", default=120.0,
                 min=1.0, max=100000.0, group="TRIGGER"),
            prop("once", "bool", "Fire once", default=True, group="TRIGGER"),
            prop("set_flag", "string", "Set flag", default="", group="TRIGGER",
                 help="'key=value' written to the quest store when the player enters."),
            prop("start_quest", "string", "Start quest", default="", group="TRIGGER",
                 help="A quest id to start when the player enters."),
            prop("hidden_in_game", "bool", "Hidden during play", default=True,
                 group="TRIGGER"),
        ])
        api.register_properties("marker", [
            prop("marker_kind", "enum", "Marker kind", default="idle",
                 choices=list(MARKER_KINDS), group="MARKER",
                 help="What this anchor is for. NPCs reference it by name "
                      "(home / work / bed / schedule location)."),
            prop("hidden_in_game", "bool", "Hidden during play", default=True,
                 group="MARKER",
                 help="Markers are authoring aids: shown in the editor, hidden "
                      "when the game runs."),
        ])

        # NPC — a social/quest actor, organised into Aurora-style sections.
        api.register_properties("npc", [
            prop("display_name", "string", "Name", default="Villager",
                 group="IDENTITY", help="Name shown when talking / on the nameplate."),
            prop("npc_role", "enum", "Role", default="villager", choices=npc_roles,
                 group="IDENTITY",
                 help="Drives stats, faction, attack style, schedule and loot."),
            prop("faction", "enum", "Faction", default="villagers", choices=factions,
                 group="FACTION", help="Team used for relationships and combat."),
            prop("disposition_base", "int", "Disposition", default=45, min=0, max=100,
                 group="FACTION", help="How warmly this NPC greets the player (0–100)."),
            prop("health", "int", "Health", default=60, min=1, max=100000, group="STATS"),
            prop("damage", "int", "Attack damage", default=8, min=0, max=10000, group="STATS"),
            prop("creature_level", "int", "Level", default=1, min=1, max=100, group="STATS"),
            prop("aggression", "enum", "Aggression", default="passive",
                 choices=["passive", "defensive", "hostile"], group="BEHAVIOUR",
                 help="passive = never fights; defensive = fights when threatened "
                      "(guards); hostile = attacks on sight."),
            prop("combatant", "bool", "Can fight", default=False, group="BEHAVIOUR",
                 help="Whether this NPC fights at all. Non-combatants (merchants, "
                      "farmers) flee to safety instead. Separate from faction."),
            prop("attack_style", "enum", "Combat style", default="melee",
                 choices=styles, group="BEHAVIOUR",
                 help="Fantasy combat: melee strike, bow arrow, or magic bolt."),
            prop("courage", "float", "Courage", default=0.3, min=0.0, max=1.0,
                 group="BEHAVIOUR",
                 help="How likely to stand and fight (0=coward, 1=fearless). "
                      "Affects confidence-based rally decisions."),
            prop("autonomy", "bool", "Wanders when idle", default=True, group="BEHAVIOUR"),
            prop("move_speed", "float", "Movement speed", default=90.0, min=0.0,
                 max=1000.0, group="BEHAVIOUR"),
            prop("work_location", "string", "Workplace marker", default="",
                 group="SCHEDULE", help="Name of a World Marker this NPC works at."),
            prop("wander_radius", "float", "Wander radius", default=220.0, min=0.0,
                 max=100000.0, group="SCHEDULE"),
            prop("merchant", "bool", "Is a merchant", default=False, group="INVENTORY"),
            prop("merchant_gold", "int", "Merchant gold", default=0, min=0, max=1000000,
                 group="INVENTORY"),
            prop("respawn", "bool", "Respawns when killed", default=False, group="STATE"),
            prop("persistent", "bool", "Persistent identity", default=True, group="STATE"),
        ])

        # Creature — a monster/animal: combat, loot, respawn (no schedule/dialogue).
        api.register_properties("creature", [
            prop("display_name", "string", "Name", default="Wolf", group="IDENTITY"),
            prop("npc_role", "enum", "Creature type", default="wolf",
                 choices=creature_roles, group="IDENTITY",
                 help="Drives stats, faction, attack style, loot and sprite."),
            prop("faction", "enum", "Faction", default="wildlife", choices=factions,
                 group="FACTION"),
            prop("health", "int", "Health", default=40, min=1, max=100000, group="STATS"),
            prop("damage", "int", "Attack damage", default=8, min=0, max=10000, group="STATS"),
            prop("creature_level", "int", "Level", default=1, min=1, max=100, group="STATS"),
            prop("xp_value", "int", "XP reward", default=10, min=0, max=100000, group="STATS"),
            prop("aggression", "enum", "Aggression", default="hostile",
                 choices=["passive", "defensive", "hostile"], group="BEHAVIOUR"),
            prop("attack_style", "enum", "Combat style", default="melee",
                 choices=styles, group="BEHAVIOUR"),
            prop("sight_range", "int", "Sight range", default=1024, min=0, max=100000,
                 group="BEHAVIOUR", help="How far it perceives enemies before engaging."),
            prop("move_speed", "float", "Movement speed", default=90.0, min=0.0,
                 max=1000.0, group="BEHAVIOUR"),
            prop("roam", "bool", "Roams its spawn area", default=True, group="BEHAVIOUR"),
            prop("roam_radius", "float", "Roam radius", default=300.0, min=0.0,
                 max=100000.0, group="BEHAVIOUR"),
            prop("loot", "string", "Loot table", default="", group="LOOT",
                 help="Loot-table id rolled on death (see game/rpg/loot)."),
            prop("respawn", "bool", "Respawns when killed", default=False, group="STATE"),
            prop("persistent", "bool", "Persistent identity", default=True, group="STATE"),
        ])
        api.register_properties("miniwindsettings", [
            prop("region_name", "string", "Region name",
                 default="The Vale of Miniwind", group="WORLD"),
            prop("start_scenario", "enum", "Start", default="prompt",
                 choices=["prompt", "quick"], group="WORLD",
                 help="'prompt' opens character creation; 'quick' drops in as a default hero."),
            prop("difficulty", "enum", "Difficulty", default="normal",
                 choices=["easy", "normal", "hard"], group="WORLD"),
            prop("start_hour", "float", "Start hour", default=8.0, min=0.0, max=24.0,
                 group="TIME"),
            prop("start_day", "int", "Start day", default=1, min=1, max=100000, group="TIME"),
            prop("minutes_per_day", "float", "Real minutes per game day",
                 default=20.0, min=0.5, max=1440.0, group="TIME"),
            prop("show_clock", "bool", "Show clock HUD", default=True, group="TIME"),
            prop("state_store", "string", "Quest-state store name", default="miniwind",
                 group="STATE"),
        ])

        npc_io = dict(
            inputs=[
                io_def("StartDialogue", "Open this NPC's dialogue tree"),
                io_def("GiveItem", "Add an item to this NPC's inventory (id[,qty])", "string"),
                io_def("SetFaction", "Change this NPC's faction/team", "string"),
                io_def("StartQuest", "Start a quest by id", "string"),
                io_def("Kill", "Kill this NPC"),
                io_def("Wake", "Un-park for combat"),
            ],
            outputs=[
                io_def("OnTalked", "Fired when the player opens this dialogue"),
                io_def("OnDialogueEnd", "Fired when the conversation closes"),
                io_def("OnDied", "Fired when this NPC dies"),
            ],
        )
        api.register_io("npc", **npc_io)
        # Creatures share the same combat/kill I/O (dialogue inputs are harmless).
        api.register_io("creature", **npc_io)

        try:
            from . import editor_ui
            api.register_property_tab("Appearance", editor_ui.make_appearance_tab, entity_type="npc")
            api.register_property_tab("Appearance", editor_ui.make_appearance_tab, entity_type="creature")
            api.register_property_tab("Inventory", editor_ui.make_inventory_tab, entity_type="npc")
            api.register_property_tab("Dialogue", editor_ui.make_dialogue_tab, entity_type="npc")
            api.register_property_tab("Schedule", editor_ui.make_schedule_tab, entity_type="npc")
            api.register_property_tab("Spells", editor_ui.make_spells_tab, entity_type="npc")
            api.register_property_tab("Loot", editor_ui.make_inventory_tab, entity_type="creature")
            api.register_property_tab("Spells", editor_ui.make_spells_tab, entity_type="creature")
            api.register_property_tab("Quests", editor_ui.make_quests_tab,
                                      entity_type="miniwindsettings")
            # Assign starting spells to the player from a checklist of every
            # spell (built-in and custom, from the Spell Editor).
            api.register_property_tab("Player Spells",
                                      editor_ui.make_player_spells_tab,
                                      entity_type="miniwindsettings")
            # The spawn point ('logicspawner') gets a guided Spawn tab that makes
            # the creature-vs-NPC choice explicit, filters the role list to the
            # chosen kind, forces a shared group faction, and edits the starting
            # inventory as a proper item table (no one-line string).
            api.register_property_tab("Spawn", editor_ui.make_spawn_tab,
                                      entity_type="creaturespawn")
        except Exception:
            pass

        # Route MiniWind-specific editor extensions through the generic
        # registration surface so no MiniWind knowledge lives in generic Fio
        # editor/engine code: the KeyValue editor's quest-key quick-insert and
        # the debug inspector's mental-state snapshot are supplied here.
        try:
            api.register_kv_suggestions(_miniwind_kv_suggestions)
            api.register_entity_inspector(_miniwind_inspector_snapshot)
        except Exception:
            pass

    # --------------------------------------------------------- runtime I/O
    def register_runtime(self, api):
        from .rpg import inventory as inv

        def _start_dialogue(entity, param, logic):
            session = getattr(logic, "_miniwind", None)
            player = getattr(logic, "player", None)
            if session is not None and player is not None:
                if session.start_dialogue(entity, player):
                    api.fire_output(entity, "OnTalked")

        def _give_item(entity, param, logic):
            parts = str(param or "").split(",")
            item_id = parts[0].strip()
            qty = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 1
            if item_id:
                from .rpg import items as rpg_items
                stack = rpg_items.make(item_id, qty) or inv.make_item(item_id, qty=qty)
                inv.add_item(inv.get_inventory(entity), stack)

        def _set_faction(entity, param, logic):
            team = str(param or "").strip().lower()
            if team:
                entity.properties["faction"] = team
                entity.properties["team"] = team

        def _start_quest(entity, param, logic):
            session = getattr(logic, "_miniwind", None)
            if session is not None and param:
                session.game.start_quest(str(param).strip())

        def _kill(entity, param, logic):
            entity.properties["dead"] = True
            entity.properties["health"] = 0
            api.fire_output(entity, "OnDied")

        def _wake(entity, param, logic):
            entity.properties["triggered"] = False
            entity.properties["awake"] = True

        for etype in ("npc", "creature"):
            api.register_input_handler(etype, "startdialogue", _start_dialogue)
            api.register_input_handler(etype, "giveitem", _give_item)
            api.register_input_handler(etype, "setfaction", _set_faction)
            api.register_input_handler(etype, "startquest", _start_quest)
            api.register_input_handler(etype, "kill", _kill)
            api.register_input_handler(etype, "wake", _wake)

    # ------------------------------------------------------------ host wiring
    def connect(self, host):
        self._host = host
        host.on("render.overlay", self._on_overlay)

    # ------------------------------------------------------------- lifecycle
    def on_play_start(self, logic):
        logic._miniwind = None
        settings = self._find_settings(logic)
        cfg = dict(settings.properties) if settings is not None else {}
        host = getattr(self, "_host", None)
        globals_store = host.globals if host is not None else None
        session = MiniwindSession(logic, cfg=cfg, globals_store=globals_store)
        session.restore()
        session.install()
        if session.needs_char_creation:
            session.open_screen = "charcreate"
            # Freeze the world from frame zero so no combat/sound runs behind the
            # character-creation screen before the first plugin tick.
            logic.gameplay_paused = True
        logic._miniwind = session
        self._prev_keys = frozenset()
        if host is not None:
            try:
                host.provide("miniwind", session)
            except Exception:
                pass

    def on_play_stop(self, logic):
        session = getattr(logic, "_miniwind", None)
        if session is not None:
            session.persist(force=True)
            session.uninstall()
            logic._miniwind = None
        host = getattr(self, "_host", None)
        if host is not None:
            try:
                host.provide("miniwind", None)
            except Exception:
                pass

    # ----------------------------------------------------------------- tick
    def on_tick(self, logic, ctx: TickContext):
        session = getattr(logic, "_miniwind", None)
        if session is None:
            return

        just = self._just_pressed(ctx)

        # While a modal screen (character creation, inventory, journal…) or a
        # conversation is open, the *world* is frozen: freeze it here so the
        # engine idles the monsters/physics, advance nothing, and route input to
        # the menu only. Time, NPC schedules and combat resume on close.
        world_paused = (session.needs_char_creation or session.open_screen is not None
                        or session.dialogue is not None)
        logic.gameplay_paused = world_paused

        if world_paused:
            session.tick_ui(ctx.delta)   # ages toasts/floaters only, no world sim
            if session.open_screen is not None:
                self._handle_screen_input(session, just, ctx)
            elif session.dialogue is not None:
                self._handle_dialogue_input(session, just, ctx)
            ctx.set_prompt("", priority=100)
            session.persist()
            return

        # Normal play: simulate the world, then handle combat/interaction input.
        session.tick(ctx.delta)
        self._handle_gameplay_input(session, just, ctx)
        self._handle_interaction(logic, ctx, session, just)
        session.persist()

    # -- input helpers ------------------------------------------------------
    def _just_pressed(self, ctx):
        """Set of key *names* newly pressed this tick."""
        keys = ctx.keys or frozenset()
        prev = getattr(self, "_prev_keys", frozenset())
        new_codes = set(keys) - set(prev)
        self._prev_keys = frozenset(keys)
        names = set()
        for name in _NAV_NAMES:
            code = key_code(name)
            if code is not None and code in new_codes:
                names.add(name)
        return names

    def _handle_gameplay_input(self, session, just, ctx):
        # held: block
        session.toggle_block(ctx.key_down(K_BLOCK))
        # Mouse combat intents (left = attack, right = cast) posted from the UI
        # thread and consumed here on the logic thread. Keyboard equivalents
        # (K_ATTACK / K_CAST) still work.
        gs = getattr(getattr(ctx, "logic", None), "game_state", None)
        if gs is not None:
            if gs.consume_rpg_attack():
                session.do_attack()
            if gs.consume_rpg_cast():
                session.do_cast()
        # edge actions
        if K_ATTACK in just or "space" in just:
            session.do_attack()
        if K_CAST in just:
            session.do_cast()
        if K_NEXT_SPELL in just:
            session.next_spell()
        if K_SNEAK in just:
            session.toggle_sneak()
        if K_HEAL in just:
            session.use_health_potion()
        # The loadout popup (weapons + spells) toggles with I and stays open
        # while you fight — it does not pause the world.
        if K_INVENTORY in just:
            session.show_loadout = not getattr(session, "show_loadout", False)
        # screens
        elif K_CHARACTER in just:
            session.open_screen = "character"
        elif K_JOURNAL in just:
            session.open_screen = "journal"
        elif K_SPELLS in just:
            session.open_screen = "spells"
        elif K_LEVELUP in just and session.game.character.can_level_up:
            session.open_screen = "levelup"

    def _handle_screen_input(self, session, just, ctx):
        from .ui import screens
        for name in just:
            if screens.handle_key(session, name):
                # one meaningful key per tick is enough; keep it simple
                pass

    def _handle_dialogue_input(self, session, just, ctx):
        view = session.current_view()
        if view is not None:
            for i in range(len(view["responses"])):
                if str(i + 1) in just:
                    session.choose(i)
                    return
        if "escape" in just:
            session.end_dialogue()

    def _handle_interaction(self, logic, ctx, session, just=frozenset()):
        session.interact_prompt = ""
        player = getattr(logic, "player", None)
        if player is None or session.game.character.is_dead:
            return
        npc = session.nearest_talkable(player.pos, TALK_RADIUS)
        if npc is not None:
            name = npc.properties.get("display_name") or npc.properties.get("name", "NPC")
            verb = "trade with" if npc.properties.get("merchant") else "talk to"
            prompt = f"Press E to {verb} {name}"
            # Show it both via the engine prompt and MiniWind's own HUD (the RPG
            # suppresses the stock HUD, so the HUD copy is what the player sees).
            ctx.set_prompt(prompt, priority=5)
            session.interact_prompt = prompt
            # Interact on the E key (the engine's optional USE action is also
            # honoured where a host wires it up).
            if K_INTERACT in just or ctx.use_pressed:
                session.start_dialogue(npc, player)

    # -------------------------------------------------------------- overlay
    def _on_overlay(self, ev):
        if not ev.get("play_mode"):
            return
        host = getattr(self, "_host", None)
        logic = host.logic if host is not None else None
        session = getattr(logic, "_miniwind", None)
        if session is None:
            return
        painter = ev.get("painter")
        viewport = ev.get("viewport")
        if painter is None:
            return
        # suppress the stock health/weapon HUD; the RPG draws its own.
        if viewport is not None:
            try:
                viewport._suppress_default_hud = True
            except Exception:
                pass
        w, h = ev.get("width", 0), ev.get("height", 0)
        try:
            from .ui import hud, dialogue_ui, screens
            # Present dialogue / menu screens as draggable, collapsible, closable
            # floating windows through the viewport's WindowManager (same chrome
            # as SysMon and the NPC inspector). Falls back to the legacy
            # full-screen draw where no window manager exists (e.g. headless).
            windowed = self._sync_overlay_windows(session, viewport, w, h)
            # The non-modal loadout popup (weapons + spells) lives alongside the
            # modal popups; it stays open while the player fights.
            self._sync_loadout_window(session, viewport, w, h)

            if not session.needs_char_creation and session.open_screen != "charcreate":
                hud.draw_time_tint(painter, session, w, h)
                hud.draw(painter, session, w, h)
                # Speech bubbles over nearby NPCs (only during free play, not
                # while a menu or conversation is open).
                if session.open_screen is None and session.dialogue is None \
                        and not session.game.character.is_dead:
                    hud.draw_bubbles(painter, session, viewport, w, h)
            if not windowed:
                if session.dialogue is not None:
                    dialogue_ui.draw(painter, session, w, h)
                if session.open_screen is not None:
                    screens.draw(painter, session, w, h)
            if session.game.character.is_dead:
                self._draw_death(painter, w, h)
        except Exception:
            import traceback
            traceback.print_exc()

    # -- floating-window overlay hosting ------------------------------------
    _SCREEN_TITLES = {
        "charcreate": "Create Your Character", "inventory": "Inventory",
        "character": "Character", "journal": "Quest Journal",
        "spells": "Spellbook", "levelup": "Level Up", "trade": "Trade",
    }

    def _close_overlay_screen(self, session, screen):
        """Close-button handler for a menu-screen window (mirrors Esc)."""
        if screen == "charcreate":
            # Closing character creation commits the current picks (a valid
            # character is always required before play resumes).
            try:
                from .ui import screens as _screens
                _screens._finish_charcreate(session)
            except Exception:
                pass
            session.needs_char_creation = False
        session.open_screen = None

    def _sync_loadout_window(self, session, viewport, w, h):
        """Create / remove the non-modal loadout popup on the viewport's window
        manager to follow ``session.show_loadout`` (toggled with the I key)."""
        wm = getattr(viewport, "window_manager", None) if viewport is not None else None
        if wm is None:
            return
        try:
            from .ui.loadout_window import LoadoutWindow
        except Exception:
            return

        # Purge any loadout window bound to a different (old) session — e.g. left
        # over from a previous play run in the same viewport.
        for existing in list(wm.windows):
            if isinstance(existing, LoadoutWindow) and existing.session is not session:
                existing.active = False
                wm.remove(existing)

        win = getattr(session, "_loadout_win", None)
        # Closed via its [X]: reflect that back into the toggle state.
        if win is not None and not getattr(win, "active", False):
            wm.remove(win)
            session._loadout_win = None
            session.show_loadout = False
            win = None

        want = (bool(getattr(session, "show_loadout", False))
                and not session.game.character.is_dead)
        if want and win is None:
            win = LoadoutWindow(session, x=max(20, w - 320), y=72)
            wm.add(win)
            session._loadout_win = win
        elif not want and win is not None:
            win.active = False
            wm.remove(win)
            session._loadout_win = None

    def _sync_overlay_windows(self, session, viewport, w, h):
        """Create / update / tear down the floating window that hosts the active
        popup. Returns True when it owns the popup drawing this frame (so the
        caller suppresses the legacy full-screen draw)."""
        wm = getattr(viewport, "window_manager", None) if viewport is not None else None
        if wm is None:
            return False
        try:
            from engine.floating_windows import CallbackWindow
            from .ui import dialogue_ui, screens
        except Exception:
            return False

        if session.dialogue is not None:
            key = "dialogue"
        elif session.open_screen is not None:
            key = f"screen:{session.open_screen}"
        else:
            key = None

        cur = getattr(session, "_overlay_win", None)
        cur_key = getattr(session, "_overlay_key", None)

        # Tear down when nothing should show or the popup changed identity.
        if cur is not None and (key is None or key != cur_key):
            cur.active = False
            try:
                wm.remove(cur)
            except Exception:
                pass
            session._overlay_win = None
            session._overlay_key = None
            cur = None

        if key is None:
            return True  # own the (empty) popup slot: suppress legacy draw

        if cur is None:
            if key == "dialogue":
                npc = session.dialogue_npc
                title = "Conversation"
                if npc is not None:
                    title = (npc.properties.get("display_name")
                             or npc.properties.get("name") or title)
                bw, bh = dialogue_ui.window_body_size(session)
                draw_fn = (lambda p, x, y, ww, hh, s=session:
                           dialogue_ui.draw_in_rect(p, s, x, y, ww, hh))
                on_close = session.end_dialogue
            else:
                screen = session.open_screen
                title = self._SCREEN_TITLES.get(screen, str(screen).title())
                bw, bh = screens.window_body_size(screen)
                draw_fn = (lambda p, x, y, ww, hh, s=session:
                           screens.draw_in_rect(p, s, x, y, ww, hh))
                on_close = (lambda s=session, sc=session.open_screen:
                            self._close_overlay_screen(s, sc))
            win = CallbackWindow(key, title, draw_fn, width=bw, body_height=bh,
                                 x=max(20, (w - bw) // 2),
                                 y=max(20, (h - bh) // 2 - 24),
                                 on_close_cb=on_close)
            wm.add(win)
            session._overlay_win = win
            session._overlay_key = key
        elif key == "dialogue":
            # The conversation box grows/shrinks with the number of responses.
            bw, bh = dialogue_ui.window_body_size(session)
            cur.set_body_size(bw, bh)
        return True

    def _draw_death(self, painter, w, h):
        from PyQt5.QtCore import QRect
        from .ui import theme as T
        T.dim_screen(painter, w, h, alpha=180)
        T.text_in(painter, QRect(0, h // 2 - 30, w, 60), "You have died",
                  size=28, color=T.HEALTH.lighter(130), align=T.ALIGN_CENTER, bold=True)

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _find_settings(logic):
        for t in getattr(logic, "things", None) or []:
            if str(t.properties.get("type", "")).replace("_", "").lower() == "miniwindsettings":
                return t
        return None
