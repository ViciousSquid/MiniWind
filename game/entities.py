"""
Entity types for the MiniWind RPG.

MiniWind authors two **distinct** actor entities, because an NPC and a monster
are not the same thing to a designer — even though both run on the same engine
:class:`~editor.things.Monster` + team-aware
:class:`~engine.monster_ai.MonsterAI` underneath (so both get billboards,
health, ``team``, death and combat for free):

* :class:`NPC` (type ``npc``) — a **social** townsperson or quest actor:
  villager, guard, merchant, blacksmith, farmer, beggar. Carries identity,
  faction, a daily schedule, home/work/bed anchors, dialogue, inventory and
  disposition. Non-hostile NPCs are created **parked** (``triggered=True``) so
  the core AI ignores them and the MiniWind schedule/autonomy drives them;
  guards un-park to defend and re-park afterwards.

* :class:`Creature` (type ``creature``) — a **monster** or wild animal: wolf,
  bear, bandit, cultist, skeleton, wraith. Carries combat stats, a loot table,
  respawn and persistence. Usually hostile and live for the core AI from the
  start.

Both are role-driven from the :mod:`rpg.bestiary` (a role's ``kind`` decides
which entity it belongs to). Every actor carries an ``attack_style`` of
``melee``, ``bow`` or ``magic`` — fantasy combat, never a gun.

:class:`Marker` (type ``marker``) is an authorable named anchor an NPC
references by id; :class:`GameSettings` (type ``miniwindsettings``) marks a map
as a MiniWind RPG map and configures the clock + starting scenario.
"""

from __future__ import annotations

import os

try:
    from editor.things import Monster, Thing
    _HAVE_EDITOR = True
except Exception:  # pragma: no cover - PyQt-free player
    from plugins.entitybase import Thing
    Monster = Thing
    _HAVE_EDITOR = False

from .rpg import schedule as _schedule
from .rpg import bestiary
from .rpg import factions

# ---------------------------------------------------------------------------
# Art: which committed sprite/portrait a role uses (unknown roles fall back).
# ---------------------------------------------------------------------------
_ART_ROLES = {"villager", "guard", "merchant", "blacksmith", "farmer",
              "beggar", "bandit", "cultist", "wolf", "monster"}
#: roles without their own art borrow another role's billboard
_ART_ALIAS = {
    "bandit_archer": "bandit", "bandit_chief": "bandit",
    "guard_archer": "guard",
    "skeleton": "monster", "skeleton_archer": "monster", "wraith": "monster",
    "bear": "wolf", "boar": "wolf", "mudcrab": "wolf",
}
# MiniWind art lives under the engine's ``assets/`` tree (namespaced), because
# every Fio sprite loader — the 3D billboard renderer, the editor 2D icons and
# the minimap — resolves sprite paths relative to ``assets/``. A path outside it
# (e.g. ``game/assets/…``) is mangled by the renderer's ``assets/``-stripping and
# renders as a white square, so the role art is kept here.
_SPRITE_DIR = "assets/sprites/miniwind"
_PORTRAIT_DIR = "assets/portraits/miniwind"

# Default weapons by attack style for humanoid actors
_DEFAULT_WEAPON = {
    "melee": "iron_shortsword",
    "bow": "hunting_bow",
    "magic": "apprentice_staff",
}
# Creature roles that should NOT receive a default metal weapon
_ANIMAL_ROLES = {"wolf", "bear", "boar", "mudcrab"}


def _art_role(role: str) -> str:
    r = str(role or "villager").lower()
    if r in _ART_ROLES:
        return r
    return _ART_ALIAS.get(r, "villager")


def sprite_for(role: str) -> str:
    return f"{_SPRITE_DIR}/{_art_role(role)}.png"


def portrait_for(role: str) -> str:
    return f"{_PORTRAIT_DIR}/{_art_role(role)}.png"


def _apply_head_sprite(p: dict) -> None:
    """If a ``head`` id is set, point the actor's billboard frames at that head
    sprite (a single static image); otherwise leave the role art in place.
    Accepts either a regular head (headNN) or, for guard-named NPCs, one of
    the special guard heads (guard01…guard06)."""
    from .rpg import heads
    hid = str(p.get("head", "") or "")
    if heads.is_any_head(hid):
        path = heads.any_head_path(hid)
        p["custom_idle"] = path
        p["custom_shoot"] = path
        # No custom death sprite: a slain head-wearing actor shows its head with
        # the shared heads/dead.png overlay (see Monster.get_sprite_path).
    p.pop("custom_dead", None)


def _apply_actor_common(thing, entity_type, default_role, default_faction):
    """Fill the properties both actor entities share, from the bestiary template.

    Sets identity, faction/team, combat stats, the AI posture (parked vs live),
    per-entity sight, loot/level/xp/resistances and the top-down billboard art
    (idle/dead/**shoot** + size) so the 2D icon and the 3D billboard always
    match. Only fills what the map did not author, so a hand-tuned entity wins.
    Returns ``(role, tmpl, aggression, faction)``.
    """
    p = thing.properties
    _authored = getattr(thing, "_mw_authored", set())
    _authored_w = "sprite_width" in _authored
    _authored_h = "sprite_height" in _authored

    p["type"] = entity_type
    p.setdefault("entity_type", entity_type)
    p.setdefault("npc_role", default_role)
    role = str(p.get("npc_role", default_role)).lower()
    tmpl = bestiary.get(role)

    # identity / faction
    p.setdefault("display_name", p.get("name", tmpl.name if tmpl else default_role.title()))
    faction = tmpl.faction if tmpl else default_faction
    p.setdefault("faction", faction)
    if not p.get("team"):
        p["team"] = p["faction"]
    faction = p["faction"]

    # combat posture + stats from the bestiary (only where the map was silent).
    aggression = tmpl.aggression if tmpl else "passive"
    if "aggression" not in _authored:
        p["aggression"] = aggression
    aggression = p["aggression"]
    # An NPC on a faction friendly to the player (villagers, guards) must never
    # spawn already 'hostile': an aggressive-to-player actor treats the player as
    # a target, so a "hostile" town guard cuts the player down on sight. The only
    # legitimate way such an NPC turns on the player is at runtime via the
    # bounty/arrest system, which mutates the live actor directly and so bypasses
    # this constructor. An authored 'hostile' here is therefore a mistake (a true
    # enemy belongs on an enemy faction), so fold it back to 'defensive' — the
    # NPC still fights faction enemies but no longer hunts the player.
    if (entity_type == "npc" and str(aggression).lower() == "hostile"
            and factions.is_friendly(faction, factions.PLAYER)):
        p["aggression"] = aggression = "defensive"
    if "health" not in _authored:
        p["health"] = tmpl.health if tmpl else 60
    # Full-health baseline (used by health bars / balance).
    p.setdefault("max_health", p["health"])
    if "damage" not in _authored:
        p["damage"] = tmpl.damage if tmpl else 6
    if "attack_style" not in _authored:
        p["attack_style"] = tmpl.attack_style if tmpl else bestiary.MELEE
    p.setdefault("monster_type", "human")   # ground unit for the core AI
    p.setdefault("sight_range", tmpl.sight if tmpl else 1024)
    p.setdefault("loot", tmpl.loot if tmpl else "")
    p.setdefault("creature_level", tmpl.level if tmpl else 1)
    p.setdefault("xp_value", tmpl.xp if tmpl else 0)
    p.setdefault("move_speed", tmpl.speed if tmpl else 90.0)
    for kind, frac in (tmpl.resistances if tmpl else {}).items():
        p.setdefault(f"resist_{kind}", frac)

    if aggression == "hostile":
        p.setdefault("triggered", False)    # live for the core AI
        p.setdefault("wake_on_sight", True)
    else:
        p["triggered"] = True               # parked: core AI ignores it
        p.setdefault("wake_on_sight", False)
    if aggression == "defensive":
        p.setdefault("can_defend", True)
    # Combat *capability* is a distinct axis from faction (who is an enemy) and
    # from the civilian flee reaction: a passive townsperson is a non-combatant
    # who flees, while a guard or a monster fights. Authorable; defaulted here.
    p.setdefault("combatant", aggression in ("defensive", "hostile"))

    # Courage: how likely this NPC is to stand and fight rather than flee.
    _COURAGE_DEFAULTS = {
        "guard": 0.8, "guard_archer": 0.8,
        "militia": 0.7,
        "blacksmith": 0.55, "hunter": 0.55,
        "villager": 0.3, "farmer": 0.3,
        "merchant": 0.2, "beggar": 0.2,
        "child": 0.1,
    }
    p.setdefault("courage", _COURAGE_DEFAULTS.get(role, 0.3))

    # top-down art: the idle and the attack ('shoot') frame use the role's own
    # billboard, so an attacking NPC never flips to the stock human sprite. There
    # is no custom death sprite — a slain actor shows its head + dead.png overlay.
    p.setdefault("custom_idle", sprite_for(role))
    p.setdefault("custom_shoot", sprite_for(role))
    # Head override: an NPC's whole appearance can be one of the head sprites
    # (a single billboard, no animation) — or, for a guard-named NPC, one of
    # the special guardNN heads. Empty = use the role art; the runtime assigns
    # a random (non-guard) head — never the player's — at play start.
    p.setdefault("head", "")
    _apply_head_sprite(p)
    p.setdefault("portrait", portrait_for(role))
    if not _authored_w:
        p["sprite_width"] = tmpl.scale if tmpl else 112
    if not _authored_h:
        p["sprite_height"] = tmpl.scale if tmpl else 112

    p.setdefault("inventory", [])
    p.setdefault("persistent", True)

    # Equip a default weapon matching attack style so every humanoid combatant
    # shows one in overhead mode. Authoring still wins if a weapon was set.
    if "equipped_weapon" not in _authored:
        if role not in _ANIMAL_ROLES:
            style = str(p.get("attack_style", "melee")).lower()
            p["equipped_weapon"] = _DEFAULT_WEAPON.get(style, "")
        else:
            p["equipped_weapon"] = ""
    p.setdefault("inventory", [])
    p.setdefault("persistent", True)
    return role, tmpl, aggression, faction



class NPC(Monster):
    """A social, role-driven townsperson or quest actor (villager…merchant…guard)."""

    pixmap_path = "assets/sprites/miniwind/villager.png"

    def __init__(self, pos=None, properties=None):
        self._mw_authored = set((properties or {}).keys())
        super().__init__(pos, properties)
        role, tmpl, aggression, faction = _apply_actor_common(
            self, "npc", "villager", "villagers")
        p = self.properties

        # schedule + world anchors (what makes an NPC "live")
        if "schedule" not in p:
            p["schedule"] = _schedule.schedule_for(role)
        p.setdefault("sched_state", _schedule.IDLE)
        p.setdefault("home", list(self.pos))
        p.setdefault("work_location", "")
        p.setdefault("autonomy", True)          # allowed to wander locally when idle
        p.setdefault("wander_radius", 220.0)
        # Companion behaviour: walk to keep pace with the player when not
        # fighting, and join in on whatever the player just attacked. Off by
        # default — set via the editor's raw properties or the console's
        # `setprop <name> follow_player true` while testing. Works best on a
        # combatant NPC (guard/companion role, or combatant=True authored
        # directly) so it also re-parks itself via the existing defend logic
        # once a fight ends.
        p.setdefault("follow_player", False)
        p.setdefault("follow_distance", 220.0)

        # social / dialogue / trade
        p.setdefault("dialogue", {})
        p.setdefault("merchant", role == "merchant")
        p.setdefault("merchant_gold", 200 if role == "merchant" else 0)
        p.setdefault("respawn", False)
        p.setdefault("quest_flags", {})
        # Authored social ties to other named NPCs ({"Mara": "sister", …}). Empty
        # by default; the settlement data / editor fills it for authored townsfolk.
        p.setdefault("relationships", {})
        p.setdefault("disposition_base", 45 if faction in ("villagers", "guards") else 30)


class Creature(Monster):
    """A monster or wild animal (wolf, bear, bandit, cultist, skeleton…)."""

    pixmap_path = "assets/sprites/miniwind/wolf.png"

    def __init__(self, pos=None, properties=None):
        self._mw_authored = set((properties or {}).keys())
        super().__init__(pos, properties)
        role, tmpl, aggression, faction = _apply_actor_common(
            self, "creature", "wolf", "wildlife")
        p = self.properties

        # monster gameplay: loot table, respawn, and an idle roam radius so wild
        # creatures drift around their spawn instead of standing stock-still.
        p.setdefault("respawn", False)
        p.setdefault("roam", aggression != "hostile")
        p.setdefault("roam_radius", 300.0)
        # Creatures have no schedule/dialogue by default, but the fields exist so
        # a boss/quest creature can be given them without a new entity type.
        p.setdefault("home", list(self.pos))
        p.setdefault("inventory", [])


def _init_settings(self):
    p = self.properties
    p["type"] = "miniwindsettings"
    p.setdefault("start_hour", 8.0)
    p.setdefault("start_day", 1)
    p.setdefault("minutes_per_day", 24.0)
    p.setdefault("show_clock", True)
    p.setdefault("state_store", "miniwind")
    p.setdefault("difficulty", "normal")        # easy | normal | hard
    p.setdefault("start_scenario", "prompt")    # prompt=char creation, or quick
    p.setdefault("region_name", "The Vale of Miniwind")
    # Spell ids granted to the player at character creation (in addition to the
    # ones their race / birthsign / class provide). Edited via the "Player
    # Spells" tab on this entity.
    p.setdefault("player_spells", [])


if _HAVE_EDITOR:
    class GameSettings(Thing):
        """Per-map RPG settings + game-clock config. Presence = RPG map opt-in."""
        map_type = "miniwindsettings"
        pixmap_path = "assets/sprites/logic_keyvalue.png"

        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_settings(self)
else:  # pragma: no cover
    class GameSettings(Thing):
        map_type = "miniwindsettings"

        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_settings(self)


# Backwards-compatible alias for the original entity name/type.
MiniwindSettings = GameSettings


# ---------------------------------------------------------------------------
# World markers (§14) — authorable, named anchor points an NPC references by a
# stable id/name rather than a hard-coded coordinate. The runtime already
# resolves a schedule ``location`` (or an NPC's ``work_location``) that names an
# entity to that entity's position (see ``runtime._resolve_location`` /
# ``_find_named``), so a Marker needs no bespoke runtime support: place it, name
# it, and point an NPC's home/work/bed/schedule at that name.
# ---------------------------------------------------------------------------
#: Marker kinds an author can pick from (drives only the editor label/icon; the
#: behaviour comes from what an NPC references, not the kind).
MARKER_KINDS = ("home", "bed", "work", "forge", "shop", "farm", "guardpost",
                "patrol", "social", "idle", "location", "prison", "quest")


def marker_sprite(kind: str) -> str:
    """The per-kind marker pin icon (falls back to the generic marker sprite)."""
    k = str(kind or "idle").lower()
    if k not in MARKER_KINDS:
        return f"{_SPRITE_DIR}/marker.png"
    return f"{_SPRITE_DIR}/marker_{k}.png"


def _init_marker(self):
    p = self.properties
    p["type"] = "marker"
    p.setdefault("marker_kind", "idle")
    # Markers are authoring aids: visible in the editor, hidden during play.
    p.setdefault("hidden_in_game", True)
    # Each marker kind gets its own pin icon so a map full of markers is legible.
    p["custom_idle"] = marker_sprite(p.get("marker_kind", "idle"))


def _marker_instance_pixmap(marker):
    """Load the per-kind marker sprite for the editor's 2D view.

    In 3D the renderer already uses each marker's ``custom_idle`` (its per-kind
    ``marker_<kind>.png``), so markers show variety there. The 2D view, however,
    falls back to the class ``pixmap_path`` — making every marker look identical.
    Resolving the instance's own sprite here fixes that. Cached per path."""
    from PyQt5.QtGui import QPixmap
    cache = _MARKER_PIXMAP_CACHE
    path = (marker.properties.get("custom_idle")
            or marker_sprite(marker.properties.get("marker_kind", "idle")))
    if path in cache:
        return cache[path]
    pix = None
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        abs_path = os.path.join(root, path)
        if os.path.exists(abs_path):
            loaded = QPixmap(abs_path)
            if not loaded.isNull():
                pix = loaded
    except Exception:
        pix = None
    cache[path] = pix
    return pix


_MARKER_PIXMAP_CACHE = {}


if _HAVE_EDITOR:
    class Marker(Thing):
        """A named world anchor NPCs reference by id (home, bed, forge, …)."""
        pixmap_path = "assets/sprites/miniwind/marker.png"

        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_marker(self)

        def get_instance_pixmap(self):
            # Use this marker's own per-kind sprite so the 2D view shows the same
            # variety the 3D view does (home/bed/forge/… each look distinct).
            pix = _marker_instance_pixmap(self)
            return pix if pix is not None else super().get_instance_pixmap()

        def get_icon_pixmap(self):
            pix = _marker_instance_pixmap(self)
            if pix is not None and not pix.isNull():
                from PyQt5.QtCore import Qt
                return pix.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return super().get_icon_pixmap()
else:  # pragma: no cover
    class Marker(Thing):
        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_marker(self)


# ---------------------------------------------------------------------------
# Item pickup, creature spawn point and quest trigger — the remaining first-class
# RPG placeables. Each is a simple Thing (no combat) driven entirely by editable
# properties, so they are data/mod-friendly and the runtime interprets them.
# ---------------------------------------------------------------------------
def _init_item_pickup(self):
    p = self.properties
    p["type"] = "itempickup"
    p.setdefault("item_id", "gold")
    p.setdefault("quantity", 1)
    p.setdefault("respawn", False)
    p.setdefault("pickup_radius", 60.0)
    p.setdefault("custom_idle", "assets/sprites/pickup.png")


def _init_creature_spawn(self):
    p = self.properties
    p["type"] = "creaturespawn"
    # A spawn point (the 'logicspawner') materialises one actor or a whole
    # same-faction GROUP of them at play start. 'spawn_kind' picks which entity
    # each member is — a Creature (monster/animal) or an NPC (townsperson /
    # guard / bandit) — while 'creature_role' drives their appearance & stats.
    p.setdefault("spawn_kind", "creature")   # 'creature' or 'npc'
    p.setdefault("creature_role", "wolf")    # role -> appearance/stats/faction
    p.setdefault("faction", "")              # "" = keep the role's own faction
    p.setdefault("count", 1)                 # 2+ = a group
    p.setdefault("spawn_radius", 0.0)
    # Starting items handed to each member, authored as a list of item stacks in
    # the editor's Spawn tab (a legacy 'id:qty, id:qty' string is still accepted).
    p.setdefault("inventory", [])
    p.setdefault("respawn", False)
    p.setdefault("hidden_in_game", True)
    p.setdefault("custom_idle", "assets/sprites/logic_spawner.png")


def _init_trigger(self):
    p = self.properties
    p["type"] = "miniwindtrigger"
    p.setdefault("trigger_radius", 120.0)
    p.setdefault("once", True)
    p.setdefault("set_flag", "")        # "key=value" written to the quest store
    p.setdefault("start_quest", "")     # a quest id to start on enter
    p.setdefault("hidden_in_game", True)
    p.setdefault("custom_idle", "assets/sprites/logic_relay.png")


#: Container styles (drives the sprite; behaviour is identical).
CONTAINER_KINDS = ("chest", "barrel", "crate", "sack", "urn")


def container_sprite(kind: str) -> str:
    """The per-kind container sprite (falls back to the generic chest)."""
    k = str(kind or "chest").lower()
    if k not in CONTAINER_KINDS:
        return f"{_SPRITE_DIR}/container_chest.png"
    return f"{_SPRITE_DIR}/container_{k}.png"


def _init_container(self):
    p = self.properties
    p["type"] = "container"
    p.setdefault("container_kind", "chest")
    p.setdefault("display_name", "Chest")
    # The container's OWN inventory — a list of item stacks, authored in the
    # editor's Contents tab, separate from the player's inventory.
    p.setdefault("inventory", [])
    p.setdefault("use_radius", 120.0)
    p.setdefault("locked", False)          # reserved: a future key/lockpick gate
    p["custom_idle"] = container_sprite(p.get("container_kind", "chest"))


def _make_thing_pair(init_fn, icon):
    """Build (editor, headless) Thing subclasses sharing one initialiser."""
    if _HAVE_EDITOR:
        class _E(Thing):
            pixmap_path = icon

            def __init__(self, pos=None, properties=None):
                super().__init__(pos, properties)
                init_fn(self)
        return _E

    class _H(Thing):  # pragma: no cover
        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            init_fn(self)
    return _H


ItemPickup = _make_thing_pair(_init_item_pickup, "assets/sprites/pickup.png")
ItemPickup.__name__ = ItemPickup.__qualname__ = "ItemPickup"


# ---------------------------------------------------------------------------
# Container — a world object the player USEs (E) to open a graphical inventory
# holding its own item stacks (separate from the player's). See runtime and the
# 'container' screen.
# ---------------------------------------------------------------------------
if _HAVE_EDITOR:
    class Container(Thing):
        """A usable world container with its own inventory."""
        pixmap_path = "assets/sprites/miniwind/container_chest.png"

        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_container(self)

        def get_instance_pixmap(self):
            self.properties["custom_idle"] = container_sprite(
                self.properties.get("container_kind", "chest"))
            pix = _container_pixmap(self)
            return pix if pix is not None else super().get_instance_pixmap()

        def get_icon_pixmap(self):
            pix = _container_pixmap(self)
            if pix is not None and not pix.isNull():
                from PyQt5.QtCore import Qt
                return pix.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return super().get_icon_pixmap()
else:  # pragma: no cover - headless player
    class Container(Thing):
        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_container(self)


def _container_pixmap(cont):
    """Load this container's sprite (per its ``container_kind``) for the views."""
    from PyQt5.QtGui import QPixmap
    cache = _MARKER_PIXMAP_CACHE
    path = container_sprite(cont.properties.get("container_kind", "chest"))
    if path in cache:
        return cache[path]
    pix = None
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        abs_path = os.path.join(root, path)
        if os.path.exists(abs_path):
            loaded = QPixmap(abs_path)
            if not loaded.isNull():
                pix = loaded
    except Exception:
        pix = None
    cache[path] = pix
    return pix


# ---------------------------------------------------------------------------
# Spellbook — a world placeable (Tidy-plugin book art) that teaches its spell
# to the player on pickup. Four cover colours; the sprite follows the cover.
# ---------------------------------------------------------------------------
SPELLBOOK_COVERS = ("red", "green", "brown", "purple")


def spellbook_sprite(cover: str) -> str:
    c = str(cover or "red").lower()
    if c not in SPELLBOOK_COVERS:
        c = "red"
    return f"{_SPRITE_DIR}/spellbook_{c}.png"


def _init_spellbook(self):
    p = self.properties
    p["type"] = "spellbook"
    p.setdefault("spell", "flare")        # spell id taught when picked up
    p.setdefault("cover", "red")
    p.setdefault("pickup_radius", 70.0)
    p.setdefault("respawn", False)
    p.setdefault("title", "")             # optional display title
    p["custom_idle"] = spellbook_sprite(p.get("cover", "red"))


def _spellbook_pixmap(book):
    """Load this book's cover sprite (per its ``cover``) for the 2D/3D views."""
    from PyQt5.QtGui import QPixmap
    cache = _MARKER_PIXMAP_CACHE
    path = spellbook_sprite(book.properties.get("cover", "red"))
    if path in cache:
        return cache[path]
    pix = None
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        abs_path = os.path.join(root, path)
        if os.path.exists(abs_path):
            loaded = QPixmap(abs_path)
            if not loaded.isNull():
                pix = loaded
    except Exception:
        pix = None
    cache[path] = pix
    return pix


if _HAVE_EDITOR:
    class Spellbook(Thing):
        """A world spellbook that teaches its ``spell`` to the player on pickup."""
        pixmap_path = "assets/sprites/miniwind/spellbook.png"

        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_spellbook(self)

        def get_instance_pixmap(self):
            # Keep the sprite in step with the chosen cover colour.
            self.properties["custom_idle"] = spellbook_sprite(
                self.properties.get("cover", "red"))
            pix = _spellbook_pixmap(self)
            return pix if pix is not None else super().get_instance_pixmap()

        def get_icon_pixmap(self):
            pix = _spellbook_pixmap(self)
            if pix is not None and not pix.isNull():
                from PyQt5.QtCore import Qt
                return pix.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return super().get_icon_pixmap()
else:  # pragma: no cover - headless player
    class Spellbook(Thing):
        def __init__(self, pos=None, properties=None):
            super().__init__(pos, properties)
            _init_spellbook(self)
CreatureSpawn = _make_thing_pair(_init_creature_spawn, "assets/sprites/logic_spawner.png")
CreatureSpawn.__name__ = CreatureSpawn.__qualname__ = "CreatureSpawn"
# Named MiniwindTrigger (type 'miniwindtrigger') so it never collides with Fio's
# own generic Trigger entity (type 'trigger'), which is preserved unchanged.
MiniwindTrigger = _make_thing_pair(_init_trigger, "assets/sprites/logic_relay.png")
MiniwindTrigger.__name__ = MiniwindTrigger.__qualname__ = "MiniwindTrigger"
