"""Host-owned party companions using the same RPG actions and player physics."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .. import fio
from ..rpg import equipment, items, magic
from .companion_behavior import CompanionMind
from .model import InputFrame


def distance(a, b):
    return math.hypot(float(a[0]) - float(b[0]), float(a[2]) - float(b[2]))


@dataclass
class Sighting:
    actor: object
    position: tuple
    seen_at: float
    react_at: float
    committed_until: float


class PartyBots:
    GUARD_RADIUS = 520
    HUMAN_SPACE = 180
    COMPANION_SPACE = 110

    def __init__(self, coop):
        self.coop = coop
        self.clock = 0.0
        self.next_think = {}
        self.next_heal = {}
        self.attackers = {}
        self.sightings = {}
        self.next_weapon = {}
        self.next_attack = {}
        self.aim_bias = {}
        self.next_idle = {}
        self.idle_until = {}

    def mind(self, bot):
        if getattr(bot, "mind", None) is None:
            bot.mind = CompanionMind(self.coop.lobby.state["campaign_id"], bot.player_id)
        return bot.mind

    def note_attack(self, source):
        """Remember an actual assault even if the attacker has no hostile flag."""
        if source is not None and isinstance(getattr(source, "properties", None), dict):
            self.attackers[id(source)] = self.clock + 8.0

    def tick(self, delta):
        if not self.coop.authority:
            return
        self.clock += max(0, min(0.1, delta))
        bots = [p for p in self.coop.players.values() if p.bot and p.connected]
        for index, bot in enumerate(bots):
            bot.last_input = time.monotonic()
            if bot.session.game.character.is_dead:
                bot.frame, bot.task = InputFrame(), "Downed companion"
                bot.bot_target = None
                self.sightings.pop(bot.player_id, None)
                continue
            mind = self.mind(bot)
            if bot.player_id not in self.next_think:
                self.next_think[bot.player_id] = self.clock + mind.reaction_delay()
                bot.frame = InputFrame()
            if self.clock < self.next_think[bot.player_id]:
                continue
            self.next_think[bot.player_id] = self.clock + mind.think_interval()
            frame, actions = self.decide(bot, index)
            bot.frame = frame
            if frame.aim is not None:
                bot.physics.angle = frame.aim
            for action, args in actions:
                self.coop.action(bot, action, args)

    def decide(self, bot, index):
        players = list(self.coop.players.values())
        humans = [p for p in players if not p.bot and p.connected]
        if not humans:
            bot.task = "Waiting for a player"
            return InputFrame(), []
        alive = [p for p in humans if not p.session.game.character.is_dead]
        leader = next((p for p in alive if p.owner == "host"), None)
        leader = leader or (alive or humans)[0]
        c = bot.session.game.character
        mind = self.mind(bot)
        bot.bot_target = None
        if c.can_level_up:
            c.level_up()
        actions = []
        healing = self._support_spell(bot)
        spell = healing
        casting = healing is not None
        if healing is not None:
            actions.append(self._spell_action(bot, healing))
        if (
            not casting and c.health < c.max_health * mind.heal_at
            and self.clock >= self.next_heal.get(bot.player_id, 0)
            and (c.effect_magnitude("restore_health") <= 0
                 or c.health < c.max_health * 0.25)
        ):
            potion = self._healing_potion(c, mind)
            if potion is not None:
                actions.append(("rpg_action", ["use_item", [potion.id]]))
                self.next_heal[bot.player_id] = self.clock + mind.uniform(1.1, 1.8)

        threat = self._threat(bot, leader)
        sighting = self.sightings.get(bot.player_id)
        if threat is not None:
            if sighting is None or sighting.actor is not threat:
                sighting = Sighting(
                    threat, tuple(threat.pos), self.clock,
                    self.clock + mind.reaction_delay(),
                    self.clock + mind.uniform(0.9, 1.8),
                )
                self.sightings[bot.player_id] = sighting
            sighting.position, sighting.seen_at = tuple(threat.pos), self.clock
        elif sighting is not None and (
            sighting.actor.properties.get("dead")
            or sighting.actor.properties.get("disabled")
            or self.clock - sighting.seen_at > 2.5
        ):
            self.sightings.pop(bot.player_id, None)
            sighting = None
        if bot.returning and threat is None:
            if distance(bot.physics.pos, leader.physics.pos) > 180:
                bot.task = "Returning from village"
                return self._walk(bot, leader.physics.pos, stop=100, roads=True), actions
            bot.returning = False
            self.coop.root._road_plans.pop(id(bot.actor), None)

        downed = [
            p
            for p in players
            if p is not bot and p.connected and p.session.game.character.is_dead
        ]
        victim = min(
            downed,
            key=lambda p: (p.bot, distance(bot.physics.pos, p.physics.pos)),
            default=None,
        )
        # A party with no conscious human needs rescue first. Otherwise finish
        # off an immediate attacker before settling down for the revive timer.
        if victim is not None and (
            not alive or threat is None or distance(bot.physics.pos, threat.pos) > 200
        ):
            bot.task = "Reviving " + victim.profile["name"]
            if distance(bot.physics.pos, victim.physics.pos) <= 110:
                return InputFrame(held=frozenset({"interact"})), actions
            return self._walk(bot, victim.physics.pos, stop=85), actions

        if threat is not None:
            if self.clock < sighting.react_at:
                bot.task = "Noticing danger"
                return InputFrame(), actions
            gap = distance(bot.physics.pos, threat.pos)
            aim = self._aim(bot, threat.pos)
            bot.task = "Defending the party"
            clear = (self._clear_shot(bot, threat)
                     and self._clear_shot(bot, threat, aim=aim))
            nav = bot.session.nav
            visible = nav is None or nav.line_clear(
                bot.physics.pos[0],
                bot.physics.pos[2],
                threat.pos[0],
                threat.pos[2],
                bot.physics.pos[1],
            )
            if not casting:
                if self.clock >= self.next_weapon.get(bot.player_id, 0):
                    self._choose_weapon(bot, threat, clear=clear and visible)
                    self.next_weapon[bot.player_id] = self.clock + mind.uniform(0.9, 1.8)
                spell = self._support_spell(bot, defending=True)
                if spell is None and clear and visible:
                    spell = self._attack_spell(bot, gap)
                if spell is not None and self._ready_to_act(bot):
                    actions.append(self._spell_action(bot, spell, threat))
                    casting = True
            weapon = equipment.weapon(c)
            bot.bot_target = threat
            spell_ranged = casting and spell.delivery in (magic.PROJECTILE, magic.TARGET)
            ranged = spell_ranged or weapon is not None and weapon.get("kind") in (
                *items.RANGED_KINDS, items.KIND_STAFF,
            )
            reach = 500 if ranged else 130
            if ranged and not spell_ranged and weapon is not None:
                reach = min(reach, float(weapon.get("reach", 500)))
            if (not casting and spell is None and gap <= reach and clear and visible
                    and bot.session._attack_cooldown <= 0):
                if self._ready_to_act(bot):
                    actions.append(("attack", []))
            desired = (min(240, reach * 0.6) if ranged else 88)
            desired *= 1.15 - 0.3 * mind.personality.courage
            frame = self._walk(bot, threat.pos, stop=desired if visible else 0, aim=aim)
            # Cautious teammates give ground when hurt or winded. They still
            # use normal collision/navigation and never abandon the last human's rescue.
            fatigue = 1 - c.stamina / max(1, c.max_stamina)
            if alive and gap < 200 and (
                c.health < c.max_health * mind.retreat_at or fatigue > 0.88
            ):
                dx = float(bot.physics.pos[0] - threat.pos[0])
                dz = float(bot.physics.pos[2] - threat.pos[2])
                length = math.hypot(dx, dz)
                if length < 1:
                    dx, dz, length = -math.sin(aim), -math.cos(aim), 1
                goal = (bot.physics.pos[0] + dx / length * 160,
                        bot.physics.pos[1], bot.physics.pos[2] + dz / length * 160)
                bot.task = "Falling back"
                frame = self._walk(bot, goal, stop=20, aim=aim)
            if not clear and visible:
                # Walk around a bystander instead of swinging or firing through
                # them. Human avatars and friendly NPCs can share a busy lane.
                side = 1 if index % 2 else -1
                goal = (
                    bot.physics.pos[0] + math.cos(aim) * 90 * side,
                    bot.physics.pos[1],
                    bot.physics.pos[2] - math.sin(aim) * 90 * side,
                )
                frame = self._walk(bot, goal, stop=15, aim=aim)
            if (gap < 145 and bot.session._attack_cooldown > 0 and c.stamina > 10
                    and mind.uniform(0, 1) > mind.lapse_chance(fatigue) * 3):
                frame = InputFrame(
                    frame.move_x, frame.move_z, aim, frame.held | {"block"}
                )
            return frame, actions

        if sighting is not None:
            # Pursue the place actually seen, never an unseen actor's live position.
            bot.task = "Looking for the attacker"
            return self._walk(bot, sighting.position, stop=70), actions

        # Distinct formation points keep heads apart while the physics hull and
        # existing navigator keep bots on walkable ground around doors/walls.
        angle = (
            index * math.tau / max(1, sum(p.bot for p in players))
            + leader.physics.angle
            + math.pi
            + (mind.preference("formation") - 1) * 1.5
        )
        goal = (
            leader.physics.pos[0] + math.sin(angle) * mind.follow_radius,
            leader.physics.pos[1],
            leader.physics.pos[2] + math.cos(angle) * mind.follow_radius,
        )
        bot.task = "Following " + leader.profile["name"]
        if distance(bot.physics.pos, leader.physics.pos) < 330:
            if self.clock >= self.next_idle.get(bot.player_id, 0):
                self.next_idle[bot.player_id] = self.clock + mind.uniform(5, 12)
                self.idle_until[bot.player_id] = self.clock + mind.uniform(0.2, 0.7)
            if (self.clock < self.idle_until.get(bot.player_id, 0)
                    and self._spacing_goal(bot) is None):
                return InputFrame(), actions
        return self._walk(bot, goal, stop=26), actions

    def _ready_to_act(self, bot):
        """Sometimes miss an opening; a lapse is bounded, not permanent dithering."""
        if self.clock < self.next_attack.get(bot.player_id, 0):
            return False
        mind = self.mind(bot)
        c = bot.session.game.character
        fatigue = 1 - c.stamina / max(1, c.max_stamina)
        if mind.uniform(0, 1) < mind.lapse_chance(fatigue):
            self.next_attack[bot.player_id] = self.clock + mind.uniform(0.25, 0.65)
            return False
        self.next_attack[bot.player_id] = self.clock + mind.uniform(0.25, 0.5)
        return True

    def _aim(self, bot, point):
        mind = self.mind(bot)
        c = bot.session.game.character
        bias, until = self.aim_bias.get(bot.player_id, (0.0, 0.0))
        if self.clock >= until:
            bias = mind.aim_error(1 - c.stamina / max(1, c.max_stamina))
            self.aim_bias[bot.player_id] = bias, self.clock + mind.uniform(0.5, 1.2)
        return math.atan2(point[0] - bot.physics.pos[0],
                          point[2] - bot.physics.pos[2]) + bias

    def _walk(self, bot, goal, stop=26, aim=None, roads=False):
        start = bot.physics.pos
        spacing = self._spacing_goal(bot)
        if spacing is not None:
            goal, stop, roads = spacing, 8, False
        gap = distance(start, goal)
        if gap <= stop:
            return InputFrame(aim=aim)
        if roads and bot.actor is not None:
            self.coop.root._refresh_roads()
            leg = self.coop.root._road_target(bot.actor, start, goal)
            if leg is not None:
                goal = leg[0]
        self._open_door_ahead(bot, goal)
        nav = bot.session.nav
        waypoint = (
            nav.steer_actor(bot.actor, start, goal)
            if nav is not None and bot.actor is not None
            else goal
        )
        dx, dz = float(waypoint[0] - start[0]), float(waypoint[2] - start[2])
        length = math.hypot(dx, dz)
        if length < 1:
            return InputFrame(aim=aim)
        c = bot.session.game.character
        held = (frozenset({"sprint"}) if gap > 300
                and c.stamina > c.max_stamina * 0.25 else frozenset())
        return InputFrame(
            dx / length,
            dz / length,
            aim if aim is not None else math.atan2(dx, dz),
            held,
        )

    def _spacing_goal(self, bot):
        """Step out of a party member's space, even when already in formation."""
        start = bot.physics.pos
        push_x = push_z = 0.0
        members = list(self.coop.players.values())
        for member in members:
            if (member is bot or not member.connected
                    or member.session.game.character.is_dead):
                continue
            dx = float(start[0] - member.physics.pos[0])
            dz = float(start[2] - member.physics.pos[2])
            gap = math.hypot(dx, dz)
            space = self.COMPANION_SPACE if member.bot else self.HUMAN_SPACE
            if gap >= space or abs(float(start[1] - member.physics.pos[1])) > 100:
                continue
            if gap < 1:
                # Distinct, repeatable directions break an exact overlap.
                angle = members.index(bot) * 2.4
                dx, dz, gap = math.sin(angle), math.cos(angle), 1.0
            weight = (space - gap) * (1 if member.bot else 2.5)
            push_x += dx / gap * weight
            push_z += dz / gap * weight
        length = math.hypot(push_x, push_z)
        if length < 1:
            return None
        step = min(120, length + 16)
        return (start[0] + push_x / length * step, start[1],
                start[2] + push_z / length * step)

    @staticmethod
    def _open_door_ahead(bot, goal):
        """Use unlocked doors on the route, without starting conversations/exits."""
        movers = bot.session.logic.mover_runtime
        pos = bot.physics.pos
        for index, door in movers.doors:
            centre, size = door["pos"], door["size"]
            if any(
                abs(centre[i] - pos[i]) >= size[i] / 2 + (64 if i == 1 else 80)
                for i in range(3)
            ):
                continue
            if (centre[0] - pos[0]) * (goal[0] - pos[0]) + (centre[2] - pos[2]) * (
                goal[2] - pos[2]
            ) < 0:
                continue
            if door.get("door_locked") or (
                door.get("door_needs_key")
                and door.get("door_key_name")
                not in bot.session.logic.player_runtime.collected_keys
            ):
                continue
            if movers.door_states.get(index, {}).get("state", "closed") == "closed":
                movers._trigger_door_open(index, door)

    def _threat(self, bot, leader):
        mind = self.mind(bot)
        living = [p for p in self.coop.players.values()
                  if p.connected and not p.session.game.character.is_dead]
        party = {id(p.actor) for p in living if p.actor is not None}
        self.attackers = {key: until for key, until in self.attackers.items()
                          if until > self.clock}
        threats = []
        for actor in fio.monster_things(self.coop.logic):
            p = actor.properties
            if (
                p.get("multiplayer_player")
                or p.get("dead")
                or p.get("hidden")
                or p.get("disabled")
            ):
                continue
            attacking = p.get("_aggro_target") in party or id(actor) in self.attackers
            hostile = str(p.get("aggression", "")) == "hostile" or (
                str(p.get("aggression", "")) != "passive"
                and self.coop.logic.monster_ai._hunts_player(actor)
            )
            if (
                not (attacking or hostile)
                or not any(distance(actor.pos, member.physics.pos) <= self.GUARD_RADIUS
                           for member in living)
                or distance(actor.pos, bot.physics.pos) > mind.awareness
                or abs(float(actor.pos[1] - bot.physics.pos[1])) > 128
            ):
                continue
            nav = bot.session.nav
            if nav is not None and not nav.line_clear(
                bot.physics.pos[0], bot.physics.pos[2], actor.pos[0], actor.pos[2],
                bot.physics.pos[1],
            ):
                continue
            threats.append(actor)
        sighting = self.sightings.get(bot.player_id)
        if (sighting is not None and self.clock < sighting.committed_until
                and any(actor is sighting.actor for actor in threats)):
            return sighting.actor
        return min(
            threats,
            key=lambda actor: (not (actor.properties.get("_aggro_target") == id(bot.actor)
                                   or id(actor) in self.attackers),
                               distance(actor.pos, bot.physics.pos)),
            default=None,
        )

    @staticmethod
    def _spells(bot):
        c = bot.session.game.character
        if not c.can_use_magic() or bot.session._cast_cooldown > 0:
            return []
        return [spell for sid in c.known_spells
                if (spell := magic.for_caster(c, sid)) is not None
                and magic.cast_cost(c, spell) <= c.magicka]

    def _support_spell(self, bot, defending=False):
        c = bot.session.game.character
        choices = []
        for spell in self._spells(bot):
            if spell.delivery != magic.SELF:
                continue
            healing = sum(float(e.get("magnitude", 0))
                          * max(1.0, float(e.get("duration", 0)))
                          for e in spell.effects if e.get("kind") == "restore_health")
            if (healing > 0 and c.health < c.max_health * self.mind(bot).heal_at
                    and c.effect_magnitude("restore_health") <= 0):
                missing = c.max_health - c.health
                choices.append(((2, min(healing, missing) / max(1, magic.cast_cost(c, spell))
                                 * self.mind(bot).preference(spell.id)), spell))
            elif defending:
                ward = sum(float(e.get("magnitude", 0)) for e in spell.effects
                           if e.get("kind") in ("shield", "fire_shield", "frost_shield", "shock_shield")
                           and c.effect_magnitude(e["kind"]) <= 0)
                if ward > 0:
                    choices.append(((1, ward / max(1, magic.cast_cost(c, spell))
                                     * self.mind(bot).preference(spell.id)), spell))
        return max(choices, key=lambda pair: pair[0], default=(None, None))[1]

    def _attack_spell(self, bot, gap):
        c = bot.session.game.character
        weapon = equipment.weapon(c)
        if (gap <= 130 and weapon is not None
                and weapon.get("kind", items.KIND_MELEE) == items.KIND_MELEE):
            return None
        choices = []
        for spell in self._spells(bot):
            reach = 130 if spell.delivery == magic.TOUCH else 500
            if spell.delivery not in (magic.PROJECTILE, magic.TARGET, magic.TOUCH) or gap > reach:
                continue
            damage = sum(float(e.get("magnitude", 0))
                         * max(1.0, float(e.get("duration", 0))) for e in spell.effects
                         if e.get("kind") in ("damage_health", "burn"))
            if damage > 0:
                choices.append((damage * magic.cast_chance(c, spell)
                                / max(1, magic.cast_cost(c, spell))
                                * self.mind(bot).preference(spell.id), spell))
        return max(choices, key=lambda pair: pair[0], default=(0, None))[1]

    def _spell_action(self, bot, spell, target=None):
        """Use the character's real hands, cast costs, rolls and cooldown."""
        c = bot.session.game.character
        bot.session._cancel_bow_draw()
        equipment.equip_spell(c, spell.id, "off")
        c.active_spell = spell.id
        aimed = target is not None and spell.delivery != magic.SELF
        if aimed and spell.delivery == magic.PROJECTILE:
            # Passing a target ID makes cast_at snap back to its exact position.
            # A human aims a point, and a moving opponent can dodge the bolt.
            aim = self._aim(bot, target.pos)
            gap = distance(bot.physics.pos, target.pos)
            point = [float(bot.physics.pos[0] + math.sin(aim) * gap),
                     float(target.pos[1]),
                     float(bot.physics.pos[2] + math.cos(aim) * gap)]
            return "cast_at", [point, None]
        return "cast_at", [([float(v) for v in target.pos] if aimed else None),
                           (str(target.properties.get("id") or "") if aimed else None)]

    def _clear_shot(self, bot, target, aim=None):
        start, end = bot.physics.pos, target.pos
        if aim is not None:
            gap = distance(start, end)
            end = (start[0] + math.sin(aim) * gap, end[1],
                   start[2] + math.cos(aim) * gap)
        dx, dz = float(end[0] - start[0]), float(end[2] - start[2])
        length2 = dx * dx + dz * dz
        if length2 < 1:
            return True
        for actor in fio.monster_things(self.coop.logic):
            if actor is bot.actor or actor is target:
                continue
            props = actor.properties
            if (
                props.get("dead")
                or props.get("hidden")
                or (props.get("disabled") and not props.get("multiplayer_player"))
            ):
                continue
            if (
                not props.get("multiplayer_player")
                and props.get("aggression") == "hostile"
            ):
                continue
            if abs(float(actor.pos[1]) - float(target.pos[1])) > 100:
                continue
            x, z = float(actor.pos[0] - start[0]), float(actor.pos[2] - start[2])
            along = (x * dx + z * dz) / length2
            if 0.03 < along < 0.97 and math.hypot(x - dx * along, z - dz * along) < 38:
                return False
        return True

    @staticmethod
    def _healing_potion(character, mind=None):
        choices = []
        for stack in character.inventory:
            potion = items.get(stack.get("id"))
            if stack.get("qty", 0) <= 0 or potion is None or not items.is_potion(potion):
                continue
            healing = sum(
                float(e.get("magnitude", 0)) * max(1.0, float(e.get("duration", 0)))
                for e in potion.get("effects", []) if e.get("kind") == "restore_health"
            )
            if healing > 0:
                choices.append((healing, potion))
        missing = character.max_health - character.health
        if mind is not None:
            # Familiarity can outweigh a slightly more efficient dose.
            def score(choice):
                amount, potion = choice
                useful = min(amount, missing) / max(1, missing)
                waste = max(0, amount - missing) / max(1, amount)
                return (useful * mind.preference(potion.id)
                        - waste * (0.1 + 0.35 * mind.personality.thrift))

            return max(choices, key=score, default=(0, None))[1]
        enough = [(amount, potion) for amount, potion in choices if amount >= missing]
        # The smallest sufficient dose, or the strongest available dose.
        if enough:
            return min(enough, key=lambda p: p[0])[1]
        return max(choices, key=lambda p: p[0], default=(0, None))[1]

    def _choose_weapon(self, bot, threat=None, clear=True):
        c = bot.session.game.character
        mind = self.mind(bot)
        current = equipment.weapon(c)
        current_ranged = current is not None and current.get("kind") in (
            *items.RANGED_KINDS, items.KIND_STAFF,
        )
        # A small distance band prevents changing hands on every think tick
        # when an enemy hovers at the edge of melee range.
        prefer_ranged = (
            threat is None
            or clear and distance(bot.physics.pos, threat.pos)
            > (140 if current_ranged else 190) * (0.85 + 0.3 * mind.personality.courage)
        )
        choices = []
        for stack in c.inventory:
            weapon = items.get(stack.get("id"))
            if (stack.get("qty", 0) > 0 and weapon is not None
                    and weapon.category == items.WEAPON):
                choices.append((weapon, stack))

        def score(choice):
            weapon, stack = choice
            kind = weapon.get("kind")
            damage = float(weapon.get("damage", 1))
            speed = float(weapon.get("speed", 1))
            if kind == items.KIND_STAFF:
                spell = magic.get(weapon.get("staff_spell", "flare"))
                if spell is None or c.magicka < magic.cast_cost(c, spell) * 0.5:
                    return (-1, 0, False)
                damage = sum(
                    float(e.get("magnitude", 0))
                    * max(1.0, float(e.get("duration", 0)))
                    for e in spell.effects if e.get("kind") in ("damage_health", "burn")
                )
                speed = 1 / 0.8
            elif kind in items.RANGED_KINDS:
                ammo = equipment.ammo_for(c, weapon)
                if ammo is None:
                    return (-1, 0, False)
                damage += float(ammo.get("damage", 0))
            rarity = items.RARITY_INFO[items.rarity_of(stack)]["stat"]
            skill = c.skill(weapon.get("skill", "blade"))
            style = ("magic" if kind == items.KIND_STAFF else
                     "ranged" if kind in items.RANGED_KINDS else "melee")
            familiar = 1.2 if mind.personality.style == style else 1.0
            rating = (damage * speed * rarity * (0.4 + skill / 110.0)
                      * mind.preference(weapon.id) * familiar)
            ranged = kind in (*items.RANGED_KINDS, items.KIND_STAFF)
            suited = threat is None or ranged == prefer_ranged
            return (int(suited), rating, current is not None and current.id == weapon.id)

        ranked = [(score(choice), choice[0]) for choice in choices]
        usable = [(rating, weapon) for rating, weapon in ranked if rating[0] >= 0]
        if not usable:
            if current is not None:
                bot.session._cancel_bow_draw()
                bot.session.game.unequip(items.SLOT_WEAPON)
            return
        best = max(usable, key=lambda choice: choice[0])[1]
        if (
            equipment.equipped_id(c, "weapon") != best.id
            or equipment.hand_spell(c, "main") is not None
        ):
            bot.session._cancel_bow_draw()
            # The interactive ready-weapon verb toggles/draws the second hand.
            # AI replacement deliberately equips its chosen primary weapon.
            bot.session.game.equip(best.id)
