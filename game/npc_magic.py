"""
Spellcasting for NPCs and creatures: the spells they know, cast as the player
casts them.

An actor's ``spells`` (assigned in the editor's NPC spell picker: entries of
``{"id", "damage", "speed", "color"}``, or bare spell ids) and a staff in its
kit are what it can cast. When the combat AI says a shot is due
(:meth:`game.npc_archery.NpcArchery.shot_hook`):

* a caster that knows a ward (Shield, Dragon Skin, a flame cloak) raises it
  the first time it engages -- having seen its foe, before the first blow --
  and again whenever it has lapsed in a fight. The ward soaks damage as the
  player's does and is drawn round the caster as the same breathing lens;
  only some casters know one (:func:`roll_ward`: :data:`WARD_CHANCE` of
  those not authored with one learn Shield);
* a caster hurt below :data:`HEAL_BELOW` of its health first heals itself, if
  it knows a healing spell and has the magicka;
* otherwise, when its loadout picks magic for this range
  (:mod:`game.combat_loadout`), it looses its strongest affordable attack
  spell as a real bolt -- the player's projectile pipeline, lit in the spell's
  colour -- at whoever it is fighting.

**Spells are held in the hands.** As the player's are, an actor's spells are
readied in its hands (``hand_spells``: ``{"main": id, "off": id}``), and it
casts only what is in them; the spell glows in that hand while it fights.
Authored hands win (the editor's Spell in main/off hand); otherwise they are
readied the first time the actor
fights or at play start (:func:`ready_hands`): a caster with no weapon drawn
holds its strongest attack spell in its main hand and a ward or a heal in
its off hand; an armed fighter keeps its weapon and holds one spell in its
off hand -- an attack when it carries no bow or staff (its way to fight at
range), else a ward or a heal. A staff channels its own spell regardless. An empty ``hand_spells`` means it casts nothing.
Raised followers keep the spells they knew in life, and fight with them.

**Casts can fizzle.** As the player's do, an actor's cast is rolled against
its skill in the spell's school (:func:`cast_chance`): a fizzle spends the
magicka and the moment, does nothing, and floats "*fizzled*" over its head.
A staff channels its spell, and never fizzles.

Spells cost magicka. An actor's pool is its authored ``max_magicka`` (else
:data:`MAGICKA_BASE` plus :data:`MAGICKA_PER_LEVEL` a level) and refills at
:data:`MAGICKA_REGEN` a second. It is settled only when asked about, so idle
casters cost nothing per tick. A caster that cannot afford a spell no longer
counts magic as a way to fight (:func:`can_attack_with_magic`, the combat
loadout's magic check), so it draws its blade or bow until the magicka is back.
"""

from __future__ import annotations

import math
import weakref
from types import SimpleNamespace

from . import fio

#: Below this fraction of its health, a caster that can heals before fighting on.
HEAL_BELOW = 0.4
#: An actor's magicka when the map authors none: a base and a share per level.
MAGICKA_BASE = 40.0
MAGICKA_PER_LEVEL = 12.0
#: Magicka refilled per second of play.
MAGICKA_REGEN = 3.0
#: A staff channels its bound spell at this share of the spell's cost.
STAFF_COST_SCALE = 0.5
#: Bolts leave the caster this far above its origin.
CAST_LIFT = 48.0
#: Fio's hit sphere is lifted this far above an actor's origin.
EYE_LIFT = 64.0
#: Bolts fizzle beyond this range.
SPELL_MAX_RANGE = 2048.0
#: Ward effects and the colour each is drawn in.
WARD_KINDS = {"shield": (110, 190, 255), "fire_shield": (255, 130, 40)}
#: The share of fighting casters, not authored with a ward, who know Shield.
WARD_CHANCE = 0.35
WARD_SPELL = "sp_shield"

#: An actor's chance that a spell works: this much at no skill, more per
#: point of its school's skill, less per point of the spell's magicka cost,
#: never below the floor and never above certainty. A fizzle costs the
#: magicka and the moment, does nothing, and shows "*fizzled*" over its head.
CAST_BASE = 0.75
CAST_PER_SKILL = 0.004
CAST_PER_COST = 0.003
CAST_FLOOR = 0.5
#: An actor's skill in a school when the map authors none (``skills`` by
#: school, or one ``magic_skill`` for all three): a base and a share per level.
SKILL_BASE = 20
SKILL_PER_LEVEL = 4

#: The session clock magicka refills against (seconds of unpaused play).
#: :class:`NpcMagic` points it at its session; 0 with none.
clock = lambda: 0.0      # noqa: E731


def _feet(thing):
    """The ground under *thing*: Fio keeps an actor's origin mid-sprite."""
    half = _float(thing.properties.get("sprite_height", 112), 112.0) / 2.0
    return [float(thing.pos[0]), float(thing.pos[1]) - half, float(thing.pos[2])]


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


HANDS = ("main", "off")


def _all_known(props):
    """``(spell, entry)`` for every spell *props*' actor knows, in hand or not."""
    from .rpg import magic
    spells = props.get("spells")
    if not isinstance(spells, list):
        return
    for entry in spells:
        if isinstance(entry, str):
            entry = {"id": entry}
        if not isinstance(entry, dict):
            continue
        spell = magic.get(entry.get("id", ""))
        if spell is not None:
            yield spell, entry


def _known(props):
    """``(spell, entry)`` for every spell *props*' actor holds in a hand: the
    ones it can cast (see the module doc)."""
    held = set(hands(props).values())
    for spell, entry in _all_known(props):
        if spell.id in held:
            yield spell, entry


def hands(props) -> dict:
    """``{"main": id, "off": id}``: the spells *props*' actor holds, readied
    now if it has never had any (:func:`ready_hands`)."""
    held = props.get("hand_spells")
    if not isinstance(held, dict):
        ready_hands(props)
        held = props.get("hand_spells")
    return {h: str(sid) for h, sid in (held or {}).items() if h in HANDS and sid}


def _ranked(props):
    """*props*' known spells sorted into attacks, wards and heals, best first."""
    from .rpg import magic
    attack, ward, heal = [], [], []
    for spell, entry in _all_known(props):
        damage = _float(entry.get("damage", spell.damage))
        if spell.delivery == magic.PROJECTILE and damage > 0:
            attack.append((damage, spell.id))
        elif spell.delivery == magic.SELF:
            power = max((_float(e.get("magnitude")) for e in spell.effects or ()
                         if e.get("kind") in WARD_KINDS), default=0.0)
            if power > 0:
                ward.append((power, spell.id))
            elif _heals(spell) > 0:
                heal.append((_heals(spell), spell.id))
    return [[sid for _v, sid in sorted(group, reverse=True)] for group in (attack, ward, heal)]


def ready_hands(props) -> dict:
    """Ready *props*' actor's spells in its hands, unless authored (see the
    module doc). Returns the hands."""
    held = props.get("hand_spells")
    if isinstance(held, dict):
        return held
    held = {h: str(props.get(f"hand_spell_{h}") or "") for h in HANDS}
    held = {h: sid for h, sid in held.items() if sid}
    if held:
        # Authored in the editor: those are the hands, and what is in them
        # is known.
        spells = props.get("spells")
        if not isinstance(spells, list):
            spells = props["spells"] = []
        have = {e.get("id") if isinstance(e, dict) else e for e in spells}
        spells.extend({"id": sid} for sid in held.values() if sid not in have)
        props["hand_spells"] = held
        return held
    attack, ward, heal = _ranked(props)
    held = {}
    if attack or ward or heal:
        from . import combat_loadout
        if not props.get("equipped_weapon"):
            # Hands free: the strongest attack leads; the other hand guards.
            first = (attack or ward or heal)[0]
            held["main"] = first
            rest = [sid for sid in ward + heal + attack[1:] if sid != first]
            if rest:
                held["off"] = rest[0]
        else:
            # A weapon in the main hand: one spell in the other.
            styles = {combat_loadout._item_style(combat_loadout._stack_id(st))
                      for st in props.get("inventory") or ()}
            styles.add(combat_loadout._item_style(props.get("equipped_weapon")))
            # A bow or a staff (which channels its own spell) already
            # reaches the enemy: the free hand guards instead.
            if attack and not styles & {combat_loadout.BOW, combat_loadout.MAGIC}:
                held["off"] = attack[0]
            else:
                held["off"] = (ward + heal + attack)[0]
    props["hand_spells"] = held
    return held


def hand_glows(props):
    """``[(hand, spell)]`` for the spells *props*' actor shows in its hands
    now: only while it fights, and not in a hand a weapon has taken."""
    from .rpg import magic
    if props.get("dead") or not (props.get("awake") or props.get("_aggro_target") is not None):
        return []
    out = []
    held = hands(props)
    from . import combat_loadout
    wielding = combat_loadout._item_style(props.get("_active_weapon") or "")
    for hand in HANDS:
        spell = magic.get(held.get(hand, ""))
        if spell is None:
            continue
        if hand == "main" and wielding in (combat_loadout.MELEE, combat_loadout.BOW):
            continue          # the blade or bow is drawn: the spell is put by
        if hand == "off" and (props.get("_torch_lit") or props.get("offhand_weapon")):
            continue
        out.append((hand, spell))
    return out


def _heals(spell) -> float:
    """How much health *spell* restores to its caster (0 when it doesn't)."""
    from .rpg import magic
    if spell.delivery != magic.SELF:
        return 0.0
    total = 0.0
    for effect in spell.effects or ():
        if effect.get("kind") == "restore_health":
            total += _float(effect.get("magnitude")) * max(1.0, _float(effect.get("duration")))
    return total


def _staff_spell(props):
    """The spell a staff in *props*' kit channels, or None."""
    from .rpg import items, magic
    weapons = [props.get("_active_weapon"), props.get("equipped_weapon")]
    for stack in props.get("inventory") or ():
        weapons.append(stack.get("id") if isinstance(stack, dict) else stack)
    for item_id in weapons:
        definition = items.get(str(item_id or ""))
        if definition is not None and definition.get("kind") == items.KIND_STAFF:
            spell = magic.get(definition.get("staff_spell", "flare"))
            if spell is not None:
                return spell
    return None


def attacks(props):
    """Every attack ``(spell, damage, speed, colour, cost)`` *props* can cast,
    strongest first. Per-actor overrides on the spell entry win."""
    from .rpg import magic
    found = []
    for spell, entry in _known(props):
        damage = _float(entry.get("damage", spell.damage))
        if spell.delivery != magic.PROJECTILE or damage <= 0:
            continue
        found.append((spell, damage, _float(entry.get("speed", spell.projectile_speed), 900.0),
                      list(entry.get("color") or spell.color), spell.base_cost))
    staff = _staff_spell(props)
    if staff is not None and staff.damage > 0 and not any(f[0] is staff for f in found):
        found.append((staff, staff.damage, staff.projectile_speed, list(staff.color),
                      staff.base_cost * STAFF_COST_SCALE))
    found.sort(key=lambda f: f[1], reverse=True)
    return found


def wards(props):
    """``(spell, kind, magnitude, duration)`` for every ward *props*' actor
    knows, strongest first."""
    from .rpg import magic
    out = []
    for spell, _entry in _known(props):
        if spell.delivery != magic.SELF:
            continue
        for effect in spell.effects or ():
            if effect.get("kind") in WARD_KINDS:
                out.append((spell, effect["kind"], _float(effect.get("magnitude")),
                            _float(effect.get("duration"), 20.0)))
    out.sort(key=lambda w: w[2], reverse=True)
    return out


def roll_ward(props, rng) -> bool:
    """Once per actor: perhaps teach a fighting caster with no ward of its own
    the Shield spell (see :data:`WARD_CHANCE`). True if it learned it."""
    if props.get("_ward_rolled"):
        return False
    props["_ward_rolled"] = True
    if not props.get("combatant") or any(True for _ in _wards_known(props)) \
            or not attacks(props):
        return False
    if rng.random() >= WARD_CHANCE:
        return False
    spells = props.get("spells")
    if not isinstance(spells, list):
        spells = props["spells"] = []
    spells.append({"id": WARD_SPELL})
    # Learned now, readied in a free hand if there is one.
    held = props.get("hand_spells")
    if isinstance(held, dict) and len(held) < len(HANDS):
        free = next(h for h in HANDS if h not in held)
        if not (free == "main" and props.get("equipped_weapon")):
            held[free] = WARD_SPELL
    return True


def _wards_known(props):
    """Every ward *props*' actor knows, in hand or not."""
    from .rpg import magic
    for spell, _entry in _all_known(props):
        if spell.delivery == magic.SELF and any(
                e.get("kind") in WARD_KINDS for e in spell.effects or ()):
            yield spell


def warded(props, now=None):
    """``(kind, magnitude)`` of the ward *props*' actor wears now, or None."""
    now = clock() if now is None else now
    if _float(props.get("_ward_until")) <= now:
        return None
    return props.get("_ward_kind", "shield"), _float(props.get("_ward_magnitude"))


def ward_soak(props, damage, now=None) -> float:
    """*damage* after the ward *props*' actor wears soaks its share (half the
    ward's magnitude a blow, as the player's shield)."""
    ward = warded(props, now)
    if ward is None or damage <= 0:
        return damage
    return max(0.0, damage - min(damage, ward[1] * 0.5))


def max_magicka(props) -> float:
    authored = props.get("max_magicka")
    if authored is not None:
        return max(0.0, _float(authored))
    level = max(1, int(_float(props.get("creature_level", 1), 1)))
    return MAGICKA_BASE + MAGICKA_PER_LEVEL * level


def magicka(props, now=None) -> float:
    """*props*' actor's magicka now, refilled for the time since it was last
    settled (and stored, so the next question starts from here)."""
    now = clock() if now is None else now
    top = max_magicka(props)
    if "_magicka" not in props:
        current = top if props.get("magicka") is None else _float(props.get("magicka"), top)
    else:
        elapsed = max(0.0, now - _float(props.get("_magicka_at"), now))
        current = _float(props.get("_magicka")) + elapsed * MAGICKA_REGEN
    current = min(top, max(0.0, current))
    props["_magicka"] = current
    props["_magicka_at"] = now
    return current


def spend(props, cost, now=None) -> bool:
    """Take *cost* magicka from *props*' actor; False (and nothing taken) when
    it hasn't that much."""
    current = magicka(props, now)
    if current + 1e-6 < cost:
        return False
    props["_magicka"] = current - cost
    return True


def skill(props, school) -> int:
    """*props*' actor's skill (0-100) in the magic *school*."""
    skills = props.get("skills")
    if isinstance(skills, dict) and school in skills:
        return int(max(0, min(100, _float(skills[school]))))
    if props.get("magic_skill") is not None:
        return int(max(0, min(100, _float(props.get("magic_skill")))))
    level = max(1, int(_float(props.get("creature_level", 1), 1)))
    return min(100, SKILL_BASE + SKILL_PER_LEVEL * level)


def cast_chance(props, spell) -> float:
    """Probability that *props*' actor's cast of *spell* works (see
    :data:`CAST_BASE`). Powers that cost nothing never fizzle."""
    if spell.base_cost <= 0:
        return 1.0
    chance = (CAST_BASE + CAST_PER_SKILL * skill(props, spell.school)
              - CAST_PER_COST * spell.base_cost)
    return max(CAST_FLOOR, min(1.0, chance))


def can_attack_with_magic(props) -> bool:
    """Whether *props*' actor can cast an attack spell right now: the combat
    loadout's magic check (see the module doc)."""
    found = attacks(props)
    return bool(found) and magicka(props) + 1e-6 >= min(f[4] for f in found)


class NpcMagic:
    """Casting for one session's actors (see the module doc)."""

    def __init__(self, session):
        global clock
        self.session = session
        #: id(actor) -> actor, for those wearing a ward (drawn as bubbles).
        self.warded = {}
        # Weakly: the clock must not keep a finished session alive.
        ref = weakref.ref(session)
        clock = lambda: float(getattr(ref(), "_archery_clock", 0.0))   # noqa: E731

    def try_ward(self, thing) -> bool:
        """Raise *thing*'s ward if it knows one and wears none; True if cast."""
        p = thing.properties
        now = clock()
        if warded(p, now) is not None:
            return False
        for spell, kind, magnitude, duration in wards(p):
            if spend(p, spell.base_cost, now):
                if self._fizzles(thing, spell):
                    return True
                p["_ward_until"] = now + duration
                p["_ward_kind"] = kind
                p["_ward_magnitude"] = magnitude
                p["_attack_anim"] = 0.2
                self.warded[id(thing)] = thing
                fx = getattr(self.session, "magic_fx", None)
                if fx is not None:
                    from .magic_fx import look_for
                    fx.cast(_feet(thing), look_for(spell.id, WARD_KINDS[kind], spell.element,
                                                   getattr(spell, "visuals", None)))
                return True
        return False

    def ward_bubbles(self):
        """``[(feet, colour, kind)]`` for every actor wearing a ward now."""
        now = clock()
        out = []
        for key, thing in list(self.warded.items()):
            p = thing.properties
            ward = None if p.get("dead") else warded(p, now)
            if ward is None:
                del self.warded[key]
                continue
            out.append((_feet(thing), WARD_KINDS.get(ward[0], WARD_KINDS["shield"]), ward[0]))
        return out

    def damage_filter(self, victim, damage, _attacker=None):
        """Fio's damage filter: a ward soaks part of each blow."""
        props = getattr(victim, "properties", None)
        dealt = ward_soak(props, damage) if isinstance(props, dict) else damage
        bleed = getattr(self.session, "gore_npc_hit", None)
        if bleed is not None:
            try:
                bleed(victim, dealt, _attacker)
            except Exception:
                pass
        return dealt

    def try_heal(self, thing) -> bool:
        """Heal *thing* if it is badly hurt and can; True when it cast."""
        p = thing.properties
        health = _float(p.get("health"))
        top = _float(p.get("max_health") or p.get("_max_health"), health)
        if top <= 0 or health <= 0 or health >= top * HEAL_BELOW:
            return False
        heals = sorted(((_heals(spell), spell) for spell, _entry in _known(p)),
                       key=lambda h: h[0], reverse=True)
        current = magicka(p)
        for amount, spell in heals:
            if amount > 0 and current + 1e-6 >= spell.base_cost and spend(p, spell.base_cost):
                if self._fizzles(thing, spell):
                    return True
                p["health"] = min(top, health + amount)
                p["_attack_anim"] = 0.2
                self._journal(thing)
                fx = getattr(self.session, "magic_fx", None)
                if fx is not None:
                    fx.heal(_feet(thing), spell.color)
                return True
        return False

    def cast_attack(self, thing, target) -> bool:
        """Loose *thing*'s strongest affordable attack spell at *target* (an
        actor, or ``"player"``); True when a bolt flew."""
        p = thing.properties
        target_pos = self.session.archery._target_pos(target)
        if target_pos is None:
            return False
        current = magicka(p)
        for spell, damage, speed, colour, cost in attacks(p):
            if current + 1e-6 >= cost and spend(p, cost):
                # A staff channels its spell: it never fizzles.
                channelled = (spell is _staff_spell(p)
                              and spell.id not in hands(p).values())
                if not channelled and self._fizzles(thing, spell):
                    return True
                self._loose(thing, target, target_pos, spell, damage, speed, colour)
                return True
        return False

    # -- internals ------------------------------------------------------------
    def _fizzles(self, thing, spell) -> bool:
        """Roll *thing*'s cast of *spell* (its magicka already spent); True,
        and "*fizzled*" over its head, when it came to nothing. A session
        with no ``rng`` rolls nothing: every cast works."""
        rng = getattr(self.session, "rng", None)
        if rng is None or rng.random() < cast_chance(thing.properties, spell):
            return False
        thing.properties["_attack_anim"] = 0.2
        self._journal(thing)
        fizzled = getattr(self.session, "fizzled", None)
        if fizzled is not None:
            fizzled(thing)
        return True

    def _loose(self, thing, target, target_pos, spell, damage, speed, colour) -> None:
        session = self.session
        logic = session.logic
        p = thing.properties
        p["_attack_anim"] = 0.2
        start = [float(thing.pos[0]), float(thing.pos[1]) + CAST_LIFT, float(thing.pos[2])]
        lift = EYE_LIFT
        if target == "player":
            player = fio.player(logic)
            lift = float(getattr(player, "camera_height", 48.0) or 48.0) * 0.6
        aim = [target_pos[0], target_pos[1] + lift, target_pos[2]]
        dx, dy, dz = aim[0] - start[0], aim[1] - start[1], aim[2] - start[2]
        if dx or dz:
            p["_facing"] = math.atan2(dx, dz)
        dist = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        speed = max(1.0, speed)
        vel = [dx / dist * speed, dy / dist * speed, dz / dist * speed]
        ai = getattr(logic, "monster_ai", None)

        def _on_hit(victim, caster=thing, dmg=damage):
            if ai is not None:
                ai._apply_monster_damage(victim, dmg, attacker=caster)

        row = fio.spawn_projectile(logic, start, vel, lifetime=SPELL_MAX_RANGE / speed,
                                   damage=damage, owner_id=id(thing),
                                   max_dist=SPELL_MAX_RANGE, on_hit=_on_hit)
        attach = getattr(session, "_attach_bolt_light", None)
        if row is not None and attach is not None:
            attach(row, start, SimpleNamespace(
                color=colour, linger=getattr(spell, "linger", 0.0),
                light_scale=getattr(spell, "light_scale", lambda: (1.0, 1.0))))
        # The cast and the bolt, as the player's look (game/magic_fx.py).
        fx = getattr(session, "magic_fx", None)
        if fx is not None:
            from .magic_fx import look_for
            look = look_for(spell.id, colour, spell.element, getattr(spell, "visuals", None))
            fx.cast(_feet(thing), look)
            if row is not None:
                fx.bolt(fio.projectile_tag(logic, row), look, hostile=target == "player")

    def _journal(self, thing) -> None:
        try:
            from engine.change_journal import touch
            touch(thing)
        except Exception:
            pass
