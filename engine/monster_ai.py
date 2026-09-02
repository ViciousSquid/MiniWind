"""
Monster AI – all enemy behaviour, patrol logic, sight, shooting, and physics.

PERF: All brush collision/raycast methods delegate to SpatialGrid,
reducing per-monster cost from O(all_brushes) to O(nearby_brushes).
"""

import threading
import time
import glm
import math
import json
from html import escape
from typing import Dict, List, Any, Optional, Tuple
from editor.debug_console import debug_log
from game.diceroll import DICE_TYPES
from .monster_constants import (
    MONSTER_SIGHT_RANGE,
    MONSTER_SHOOT_INTERVAL,
    MONSTER_SHOOT_ANIM_TIME,
    MONSTER_MOVE_SPEED,
    MONSTER_STOP_DISTANCE,
    MONSTER_GRAVITY,
    MONSTER_TERMINAL_VEL,
    MONSTER_WALL_MARGIN,
    MONSTER_STUCK_THRESHOLD,
    MONSTER_DETOUR_RANGE,
    WEAPON_DAMAGE,
    MONSTER_SHOOT_SOUNDS,
    MONSTER_SHOOT_SOUND_DEFAULT,
    MONSTER_BITE_DISTANCE,
    MONSTER_BITE_DAMAGE_MULT,
    MONSTER_MELEE_RANGE,
    MONSTER_MELEE_SOUND,
    MONSTER_BOW_SOUND,
    MONSTER_ARROW_SPRITE,
    MONSTER_ARROW_SPRITE_SIZE,
    MONSTER_BOW_PROJECTILE_SPEED,
    MONSTER_MAGIC_SOUND,
    MONSTER_MAGIC_SPRITE,
    MONSTER_MAGIC_SPRITE_SIZE,
    MONSTER_MAGIC_PROJECTILE_SPEED,
    MONSTER_HIT_FLASH_TIME,
)

try:
    from editor.things import PathNode, Monster as MonsterThing
except ImportError:
    PathNode = None
    MonsterThing = None


class MonsterAI:
    """Handles all monster AI updates, patrol, sight, combat, and debug visualisation."""

    def __init__(self, logic_thread):
        self.lt = logic_thread                     # parent LogicThread
        self.monster_states: Dict[int, Dict[str, Any]] = {}
        self._debug_rays: List[Dict[str, Any]] = []   # for F7 debug lines
        self.monster_debug_active = False
        self._grid = None                          # SpatialGrid, set by LogicThread

    def set_spatial_grid(self, grid):
        """Called by LogicThread after populating the grid."""
        self._grid = grid

    @staticmethod
    def _attack_damage_notation(maximum: int) -> str:
        """Return a supported dice expression whose maximum covers *maximum*."""
        maximum = max(1, int(maximum))
        best = None
        for sides in DICE_TYPES:
            count = max(1, math.ceil(maximum / sides))
            candidate = (count * sides, count, -sides, sides)
            if best is None or candidate[:3] < best[:3]:
                best = candidate
        return f"{best[1]}d{best[3]}"

    def _roll_attack_damage(self, attacker, maximum: int, attack_style: str):
        """Roll an actor's damage through MiniWind's shared dice service."""
        maximum = int(maximum)
        if maximum < 2:
            return max(0, maximum), None
        session = getattr(self.lt, "_miniwind", None)
        dice = getattr(getattr(session, "game", None), "dice", None)
        if dice is None:
            return maximum, None
        name = str(attacker.properties.get("name", "monster"))
        notation = self._attack_damage_notation(maximum)
        result = dice.request_roll(
            notation, source="monster.attack",
            context={"attacker": name, "attack_style": attack_style})
        return int(result["roll_result"]), result

    @staticmethod
    def _attack_target_name(aggro_monster):
        """Return a readable target label for combat logging."""
        if aggro_monster is not None:
            return str(aggro_monster.properties.get("name", "monster"))
        return "player"


    @staticmethod
    def _face_dir(thing, direction) -> None:
        """Record an actor's heading so its head sprite turns to face where it's
        moving or looking. Stored in the transient ``properties['_facing']`` as
        radians in the engine's forward convention — forward = (sin a, 0, cos a),
        so ``_facing = atan2(dir.x, dir.z)`` (matches how the player's angle is
        derived). This is what the 3D head billboard and the overhead ground
        sprite read. The leading underscore keeps it out of saved maps, and
        near-zero directions are ignored so a stationary actor holds its heading."""
        try:
            dx = float(direction.x); dz = float(direction.z)
        except AttributeError:
            dx, dz = float(direction[0]), float(direction[2])
        if dx * dx + dz * dz > 1e-9:
            thing.properties['_facing'] = math.atan2(dx, dz)

    # -------------------------------------------------------------------------
    # Main update entry point
    # -------------------------------------------------------------------------

    def update(self, delta: float):
        """Called every tick from LogicThread._tick_play_mode."""
        if not self.lt.player or not MonsterThing:
            return

        if self.lt.player_dead:
            return

        # World frozen by a game menu (character creation, inventory, …): don't
        # move, target, attack or make noise until play resumes.
        if getattr(self.lt, 'gameplay_paused', False):
            return

        player_pos = self.lt.player.pos
        self._debug_rays.clear()

        # PERF: iterate the precomputed monster list instead of isinstance-
        # scanning every brush/thing in the level every tick.
        monster_things = getattr(self.lt, '_monster_things', None)
        if monster_things is None:
            monster_things = [t for t in self.lt.things if isinstance(t, MonsterThing)]

        for thing in monster_things:
            if thing.properties.get('hidden', False):
                thing.properties.pop('is_shooting', None)
                continue
            if thing.properties.get('disabled', False):
                continue

            mid = id(thing)

            # Decay the damage flash (set on any hit, incl. parked NPCs that are
            # struck but never reach the AI logic below). Runs before the early
            # continues so a flash always clears.
            _flash = thing.properties.get('_hit_flash', 0.0)
            if _flash:
                _flash -= delta
                if _flash <= 0.0:
                    thing.properties.pop('_hit_flash', None)
                else:
                    thing.properties['_hit_flash'] = _flash

            # ---- Dead monsters: sprite falls ----
            if thing.properties.get('dead', False):
                thing.properties.pop('is_shooting', None)
                vel_y = thing.properties.get('_vel_y', 0.0)
                pos = thing.pos
                ground_y = self._monster_raycast_down(pos[0], pos[2], pos[1])
                if ground_y is not None:
                    sprite_h = thing.properties.get('sprite_height', 128)
                    target_y = ground_y + sprite_h / 2.0
                    if pos[1] > target_y + 1.0:
                        vel_y += MONSTER_GRAVITY * delta
                        if vel_y < MONSTER_TERMINAL_VEL:
                            vel_y = MONSTER_TERMINAL_VEL
                        new_y = pos[1] + vel_y * delta
                        if new_y <= target_y:
                            new_y = target_y
                            vel_y = 0.0
                        thing.pos = [pos[0], new_y, pos[2]]
                        thing.properties['_vel_y'] = vel_y
                    else:
                        if abs(pos[1] - target_y) > 1.0:
                            thing.pos = [pos[0], target_y, pos[2]]
                        thing.properties['_vel_y'] = 0.0
                else:
                    thing.properties['_vel_y'] = 0.0
                continue

            # ---- Awake / triggered logic ----
            triggered = thing.properties.get('triggered', False)
            wake_sight = thing.properties.get('wake_on_sight', True)
            awake = thing.properties.get('awake', False)

            # Per-entity perception: how far this actor sees enemies before it
            # engages. Lets a bandit camp stay dormant until approached instead
            # of aggroing the whole map. Falls back to the global default.
            try:
                sight = float(thing.properties.get('sight_range', MONSTER_SIGHT_RANGE))
            except (TypeError, ValueError):
                sight = float(MONSTER_SIGHT_RANGE)

            if not awake:
                if triggered:
                    # Scripted ambush: waits for its I/O trigger, ignores sight & sound
                    continue
                elif not wake_sight:
                    thing.properties['awake'] = True
                    awake = True
                else:
                    # Try, in order: see the player, see an enemy-team monster,
                    # or HEAR a recent player noise (gunshot / water splash).
                    woke_reason = None

                    # Sight of the player (squared distance — threshold-only compare)
                    diff_to_player = player_pos - glm.vec3(thing.pos)
                    dist_to_player_sq = glm.dot(diff_to_player, diff_to_player)
                    player_hostile = self._teams_hostile(
                        thing.properties.get('team', ''), 'player')
                    if player_hostile and dist_to_player_sq <= sight * sight:
                        woke_reason = 'sight'
                    else:
                        # Sight of an enemy-team monster
                        my_team = thing.properties.get('team', '')
                        if my_team:
                            enemy = self._find_closest_enemy_team_monster(
                                thing, my_team, player_pos, sight)
                            if enemy is not None:
                                woke_reason = 'enemy'
                                if self.monster_debug_active:
                                    name = thing.properties.get('name', '?')
                                    ename = enemy.properties.get('name', '?')
                                    eteam = enemy.properties.get('team', '?')
                                    debug_log("MonsterAI",
                                              f"{name} woke to enemy {ename} (team={eteam})")

                    # Hearing: a recent nearby noise wakes a can_hear monster.
                    # Investigation (moving to the source) is handled once awake
                    # by _investigate_sounds on the out-of-sight path.
                    if woke_reason is None and self._hears_noise(thing) is not None:
                        woke_reason = 'sound'
                        if self.monster_debug_active:
                            name = thing.properties.get('name', '?')
                            debug_log("MonsterAI", f"{name} woke to a noise")

                    if woke_reason is None:
                        continue

                    thing.properties['awake'] = True
                    awake = True

            # ---- Kill input handling ----
            if thing.properties.pop('_kill', False):
                thing.properties['dead'] = True
                thing.properties.pop('is_shooting', None)
                if self.monster_debug_active:
                    name = thing.properties.get('name', '?')
                    debug_log("MonsterAI",
                        f'<a href="filter:{name}" style="color: #EF5350; font-weight: bold; text-decoration: none;">{name}</a> '
                        f'<span style="color: #B71C1C; font-weight: bold;">DIED</span> (killed by input)')
                continue

            mtype = thing.properties.get('monster_type', 'human')
            thing_pos = glm.vec3(thing.pos)

            # ---- Per‑monster state initialisation ----
            if mid not in self.monster_states:
                self.monster_states[mid] = {
                    'shoot_timer': MONSTER_SHOOT_INTERVAL,
                    'anim_timer': 0.0,
                    'in_sight': False,
                    'vel_y': 0.0,
                    'investigating_sound': None,  # (pos, expiry_time) or None
                }

            state = self.monster_states[mid]

            # ---- Gravity for ground monsters ----
            if mtype != 'flying':
                vel_y = state.get('vel_y', 0.0)
                ground_y = self._monster_raycast_down(thing_pos.x, thing_pos.z, thing_pos.y + 10.0)
                sprite_height = thing.properties.get('sprite_height', 128)
                half_height = sprite_height / 2.0
                if ground_y is not None:
                    foot_y = thing_pos.y - half_height
                    if foot_y > ground_y + 1.0:
                        vel_y += MONSTER_GRAVITY * delta
                        if vel_y < MONSTER_TERMINAL_VEL:
                            vel_y = MONSTER_TERMINAL_VEL
                        new_foot_y = foot_y + vel_y * delta
                        if new_foot_y <= ground_y:
                            new_foot_y = ground_y
                            vel_y = 0.0
                        new_center_y = new_foot_y + half_height
                        thing.pos = [thing_pos.x, new_center_y, thing_pos.z]
                    else:
                        desired_center_y = ground_y + half_height
                        if abs(thing_pos.y - desired_center_y) > 1.0:
                            thing.pos = [thing_pos.x, desired_center_y, thing_pos.z]
                        vel_y = 0.0
                state['vel_y'] = vel_y

            # ---- Notarget: skip all player-targeting when cheat is active ----
            #      Monsters still gravity-fall and patrol, just don't chase/attack.
            if self.lt.notarget:
                thing.properties['is_shooting'] = False
                if mid in self.monster_states:
                    self.monster_states[mid]['anim_timer'] = 0.0
                # Even in notarget mode, monsters with can_hear investigate sounds
                if thing.properties.get('can_hear', False):
                    self._investigate_sounds(thing, state, mtype, delta, player_pos)
                else:
                    self._update_monster_patrol(thing, state, mtype, delta)
                continue

            # ---- Target name override (set via I/O settarget input) ----
            target_name = thing.properties.get('target_name', None)
            override_target_pos = None
            if target_name is not None:
                if target_name == '':
                    # Empty string: clear override and fall back to normal logic
                    thing.properties.pop('target_name', None)
                else:
                    target_entity = self.lt._find_entity_by_name(target_name)
                    if target_entity is not None and hasattr(target_entity, 'pos'):
                        # Valid named target found — use its position
                        override_target_pos = glm.vec3(target_entity.pos)
                    else:
                        # Missing or invalid name: clear override and fall back
                        thing.properties.pop('target_name', None)

            # ---- Resolve target (player or aggro monster for infighting) ----
            if override_target_pos is not None:
                # Bypass normal target selection when a valid override is active
                target_pos = override_target_pos
                aggro_monster = None
            else:
                aggro_id = thing.properties.get('_aggro_target', None)
                aggro_monster = None
                if aggro_id is not None:
                    aggro_monster = self._find_monster_by_id(aggro_id)
                    if aggro_monster is None or aggro_monster.properties.get('dead', False):
                        # Aggro target gone — revert to player
                        thing.properties.pop('_aggro_target', None)
                        aggro_monster = None

                if aggro_monster is not None:
                    target_pos = glm.vec3(aggro_monster.pos)
                else:
                    # ---- Team-based enemy targeting (priority over player) ----
                    my_team = thing.properties.get('team', '')
                    enemy_monster = None
                    if my_team:
                        enemy_monster = self._find_closest_enemy_team_monster(
                            thing, my_team, player_pos, sight)
                    if enemy_monster is not None:
                        aggro_monster = enemy_monster
                        target_pos = glm.vec3(enemy_monster.pos)
                        if self.monster_debug_active:
                            name = thing.properties.get('name', '?')
                            ename = enemy_monster.properties.get('name', '?')
                            eteam = enemy_monster.properties.get('team', '?')
                            debug_log("MonsterAI",
                                      f"{name} (team={my_team}) targeting enemy {ename} (team={eteam})")
                    elif self._hostile_to_player(thing):
                        # Only actors hostile to the player fall back to hunting
                        # the player. A guard or wild animal that isn't hostile to
                        # the player (and has no enemy in sight) just idles/patrols
                        # instead of chasing them.
                        target_pos = player_pos
                    else:
                        target_pos = None

            # No valid target this frame — behave as "out of sight" (patrol/idle).
            if target_pos is None:
                thing.properties['is_shooting'] = False
                state['anim_timer'] = 0.0
                if state['in_sight']:
                    state['in_sight'] = False
                if thing.properties.get('can_hear', False):
                    if not self._investigate_sounds(thing, state, mtype, delta, player_pos):
                        self._update_monster_patrol(thing, state, mtype, delta)
                else:
                    self._update_monster_patrol(thing, state, mtype, delta)
                continue

            # Distance is needed for the sight-range decision regardless of LOS.
            # Avoid a spatial ray query for targets that cannot be engaged; debug
            # visualization deliberately retains the full LOS check.
            _dist_diff = thing_pos - target_pos
            distance_sq = glm.dot(_dist_diff, _dist_diff)
            in_sight_range = distance_sq <= sight * sight

            monster_eye = glm.vec3(thing_pos.x, thing_pos.y + 64.0, thing_pos.z)
            if aggro_monster is not None:
                target_eye = glm.vec3(target_pos.x, target_pos.y + 64.0, target_pos.z)
            else:
                target_eye = glm.vec3(player_pos.x, player_pos.y + self.lt.player.camera_height, player_pos.z)
            has_los = self._has_line_of_sight(monster_eye, target_eye) if (in_sight_range or self.monster_debug_active) else False

            if self.monster_debug_active:
                self._debug_rays.append({
                    'start': [monster_eye.x, monster_eye.y, monster_eye.z],
                    'end':   [target_eye.x, target_eye.y, target_eye.z],
                    'color': 'green' if has_los else 'red',
                })

            if in_sight_range:
                # ---- Entered sight range ----
                if not state['in_sight']:
                    state['in_sight'] = True
                    if aggro_monster is None and self.lt.io_manager:
                        self.lt.io_manager.fire_output(thing, 'OnSeePlayer')
                    if self.monster_debug_active:
                        name = thing.properties.get('name', '?')
                        if aggro_monster is not None:
                            tgt_name = aggro_monster.properties.get('name', '?')
                            debug_log("MonsterAI",
                                f'<a href="filter:{name}" style="color: #42A5F5; font-weight: bold; text-decoration: none;">{name}</a> '
                                f'engaging enemy: '
                                f'<a href="filter:{tgt_name}" style="color: #EF5350; font-weight: bold; text-decoration: none;">{tgt_name}</a>')
                        else:
                            debug_log("MonsterAI",
                                f'<a href="filter:{name}" style="color: #42A5F5; font-weight: bold; text-decoration: none;">{name}</a> '
                                f'engaging enemy: '
                                f'<span style="color: #AB47BC; font-weight: bold;">player</span>')

                # Face the target while engaged, even at melee stop distance, so
                # the head sprite looks at what it's fighting.
                self._face_dir(thing, target_pos - thing_pos)

                # ---- Move toward target ----
                if distance_sq > MONSTER_STOP_DISTANCE * MONSTER_STOP_DISTANCE:
                    direction = target_pos - thing_pos
                    dir_len = glm.length(direction)
                    if dir_len > 0.001:
                        direction = direction / dir_len
                        if mtype != 'flying':
                            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
                        step = direction * MONSTER_MOVE_SPEED * delta
                        new_pos = thing_pos + step

                        if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
                            thing.pos = [new_pos.x, new_pos.y, new_pos.z]
                        else:
                            # slide along walls
                            slide_x = glm.vec3(thing_pos.x + step.x, thing_pos.y, thing_pos.z)
                            slide_z = glm.vec3(thing_pos.x, thing_pos.y, thing_pos.z + step.z)
                            if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                                thing.pos = [slide_x.x, slide_x.y, slide_z.z]
                            elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                                thing.pos = [slide_z.x, slide_z.y, slide_z.z]
                            # else: blocked on both axes – no movement

                # ---- Attacking ----
                # Fantasy combat: a monster/NPC either strikes in MELEE (no
                # ranged attack, no gunshot) or looses an ARROW with a bow.
                # ``attack_style`` selects which; when it is absent the legacy
                # behaviour (flying = projectile, human = hitscan) is kept so
                # pre-existing non-fantasy maps are unchanged.
                state['shoot_timer'] -= delta
                attack_style = str(thing.properties.get('attack_style', '')).lower()
                melee_range = float(thing.properties.get('melee_range', MONSTER_MELEE_RANGE))
                in_melee = distance_sq <= melee_range * melee_range

                if attack_style == 'melee':
                    ready = state['shoot_timer'] <= 0.0 and in_melee
                elif attack_style in ('bow', 'magic'):
                    ready = state['shoot_timer'] <= 0.0 and has_los
                else:
                    ready = state['shoot_timer'] <= 0.0 and has_los  # legacy

                if ready:
                    state['shoot_timer'] = MONSTER_SHOOT_INTERVAL
                    state['anim_timer'] = MONSTER_SHOOT_ANIM_TIME

                    authored_damage = int(thing.properties.get('damage', 20))
                    damage, attack_roll = self._roll_attack_damage(
                        thing, authored_damage, attack_style or mtype)
                    sound_file = MONSTER_SHOOT_SOUNDS.get(mtype, MONSTER_SHOOT_SOUND_DEFAULT)

                    if attack_style == 'melee':
                        # Instant strike at close range — player or, when
                        # infighting, the aggro'd enemy monster. No projectile.
                        if aggro_monster is not None:
                            self._apply_monster_damage(aggro_monster, damage, attacker=thing)
                        else:
                            self.lt._apply_player_damage(damage)
                        sound_file = MONSTER_MELEE_SOUND
                    elif attack_style == 'bow':
                        # Loose an arrow toward the target (dodgeable projectile).
                        self._spawn_monster_projectile(
                            thing, target_pos, damage, mid,
                            sprite=MONSTER_ARROW_SPRITE,
                            size=MONSTER_ARROW_SPRITE_SIZE,
                            speed=MONSTER_BOW_PROJECTILE_SPEED,
                            embeds=True, kind='arrow')
                        sound_file = MONSTER_BOW_SOUND
                    elif attack_style == 'magic':
                        # Hurl a glowing magic bolt (dodgeable projectile). If the
                        # caster has an assigned spell (authored in the Spells
                        # tab), use its colour / per-shot damage / speed so each
                        # bolt matches the spell being cast.
                        m_color, m_speed = None, MONSTER_MAGIC_PROJECTILE_SPEED
                        m_damage = damage
                        spell = self._primary_spell(thing)
                        if spell:
                            m_color = spell.get('color')
                            if spell.get('damage'):
                                m_damage = int(spell['damage'])
                            if spell.get('speed'):
                                m_speed = float(spell['speed'])
                        self._spawn_monster_projectile(
                            thing, target_pos, m_damage, mid,
                            sprite=MONSTER_MAGIC_SPRITE,
                            size=MONSTER_MAGIC_SPRITE_SIZE,
                            speed=m_speed, color=m_color)
                        sound_file = MONSTER_MAGIC_SOUND
                    elif mtype == 'flying':
                        # ---- Legacy flying monsters: bite if very close, else projectile ----
                        if distance_sq <= MONSTER_BITE_DISTANCE * MONSTER_BITE_DISTANCE and aggro_monster is None:
                            bite_damage = int(damage * MONSTER_BITE_DAMAGE_MULT)
                            self.lt._apply_player_damage(bite_damage)
                        else:
                            self._spawn_monster_projectile(thing, target_pos, damage, mid)
                    else:
                        # ---- Legacy human monsters: instant hitscan damage ----
                        if aggro_monster is not None:
                            self._apply_monster_damage(aggro_monster, damage, attacker=thing)
                        else:
                            crossfire_victim = self._find_monster_in_crossfire(
                                thing, monster_eye, target_eye)
                            if crossfire_victim is not None:
                                self._apply_monster_damage(
                                    crossfire_victim, damage, attacker=thing)
                            else:
                                self.lt._apply_player_damage(damage)

                    target_name = self._attack_target_name(aggro_monster)
                    attack_payload = {
                        'attacker': thing.properties.get('name', 'monster'),
                        'target': target_name,
                        'damage': damage,
                        'attack_style': attack_style or mtype,
                    }
                    if attack_roll is not None:
                        attack_payload['dice'] = attack_roll
                        attack_payload['damage_roll'] = attack_roll
                    attacker_label = escape(str(attack_payload['attacker']))
                    target_label = escape(str(target_name))
                    if attack_roll is not None:
                        dice_label = escape(str(attack_roll['dice_notation']))
                        result_label = escape(str(attack_roll['roll_result']))
                        attack_message = (
                            f'<span style="color: #42A5F5; font-weight: bold;">'
                            f'{attacker_label}</span> attacked {target_label} for '
                            f'<span style="color: #FF7043; font-weight: bold;">'
                            f'{damage} damage</span> '
                            f'(<span style="color: #FFFFFF;">{dice_label}</span> = '
                            f'<span style="color: #69F0AE; font-weight: bold;">'
                            f'{result_label}</span>)')
                    else:
                        attack_message = (
                            f'<span style="color: #42A5F5; font-weight: bold;">'
                            f'{attacker_label}</span> attacked {target_label} for '
                            f'<span style="color: #FF7043; font-weight: bold;">'
                            f'{damage} damage</span>')
                    debug_log("Roll" if attack_roll is not None else "IO", attack_message)


                    self.lt.game_state.queue_sound({
                        'file': sound_file,
                        'volume': 0.6,
                        'entity_id': mid,
                    })

                    if self.lt.io_manager:
                        self.lt.io_manager.fire_output(
                            thing, 'OnAttack',
                            json.dumps(attack_payload, separators=(',', ':')))

                    if self.monster_debug_active:
                        name = thing.properties.get('name', '?')
                        tgt = aggro_monster.properties.get('name', '?') if aggro_monster else 'player'
                        debug_log("MonsterAI", f"{name} attacks {tgt} for {damage} damage ({attack_style or mtype})")

                elif state['shoot_timer'] <= 0.0:
                    state['shoot_timer'] = 0.1   # re-check soon (out of range/LOS)

                if state['anim_timer'] > 0.0:
                    state['anim_timer'] -= delta
                    thing.properties['is_shooting'] = True
                else:
                    thing.properties['is_shooting'] = False

            else:
                # ---- Out of sight ----
                if state['in_sight']:
                    state['in_sight'] = False
                    if aggro_monster is None and self.lt.io_manager:
                        self.lt.io_manager.fire_output(thing, 'OnLostPlayer')
                    if self.monster_debug_active:
                        name = thing.properties.get('name', '?')
                        debug_log("MonsterAI", f"{name} lost target (dist={math.sqrt(distance_sq):.0f})")

                thing.properties['is_shooting'] = False
                state['anim_timer'] = 0.0

                # If we had an aggro target but it's out of range, drop it
                if aggro_monster is not None:
                    thing.properties.pop('_aggro_target', None)

                # ---- Sound investigation (can_hear monsters) ----
                if thing.properties.get('can_hear', False):
                    investigating = self._investigate_sounds(thing, state, mtype, delta, player_pos)
                    if not investigating:
                        # ---- Patrol behaviour (only when target not in sight and not investigating) ----
                        self._update_monster_patrol(thing, state, mtype, delta)
                else:
                    # ---- Patrol behaviour (only when target not in sight) ----
                    self._update_monster_patrol(thing, state, mtype, delta)

        # ---- Player death check (after all monsters processed) ----
        if self.lt.player_health <= 0 and not self.lt.player_dead:
            self.lt.player_dead = True
            if self.lt.io_manager:
                try:
                    from editor.things import PlayerStart
                    for thing in self.lt.things:
                        if isinstance(thing, PlayerStart):
                            self.lt.io_manager.fire_output(thing, 'OnPlayerDeath')
                            break
                except ImportError:
                    pass
            debug_log("MonsterAI", "Player has died.")

    # -------------------------------------------------------------------------
    # Monster infighting helpers
    # -------------------------------------------------------------------------

    def _find_monster_by_id(self, monster_id: int):
        """Return a living Monster thing by Python id, or None."""
        monster_by_id = getattr(self.lt, '_monster_by_id', None)
        if monster_by_id is not None:
            return monster_by_id.get(monster_id)
        for t in self.lt.things:
            if isinstance(t, MonsterThing) and id(t) == monster_id:
                return t
        return None

    def _teams_hostile(self, team_a, team_b) -> bool:
        """Whether two teams are enemies.

        Generic Fio behaviour is "any two different teams are enemies". A game
        layer can install a faction model by setting ``logic._faction_hostile
        (a, b) -> bool`` (MiniWind wires in its faction matrix), and this
        consults it so, e.g., wild animals stay neutral to villagers while
        bandits are hostile to both. Missing/erroring predicate falls back to
        the legacy different-team rule so non-RPG maps are unchanged.
        """
        fn = getattr(self.lt, '_faction_hostile', None)
        if fn is None:
            return True
        try:
            return bool(fn(team_a, team_b))
        except Exception:
            return True

    def _hostile_to_player(self, thing) -> bool:
        """True if *thing* would attack the player: an explicitly hostile actor,
        or one whose faction is hostile to the player. Guards/villagers/neutral
        wildlife are therefore never driven to chase the player."""
        if str(thing.properties.get('aggression', '')).lower() == 'hostile':
            return True
        return self._teams_hostile(thing.properties.get('team', ''), 'player')

    def _find_closest_enemy_team_monster(self, thing, my_team: str, player_pos: glm.vec3, max_range: float):
        """Find the closest living monster on a DIFFERENT, hostile team within
        range. Returns the monster or None.  Team-based enemies are targeted
        first before the player."""
        if not my_team or MonsterThing is None:
            return None

        my_pos = glm.vec3(thing.pos)
        best_dist_sq = float('inf')
        best_monster = None
        max_range_sq = max_range * max_range
        monster_things = getattr(self.lt, '_monster_things', None) or self.lt.things

        for t in monster_things:
            if monster_things is self.lt.things and not isinstance(t, MonsterThing):
                continue
            if t is thing:
                continue
            if t.properties.get('dead', False) or t.properties.get('hidden', False):
                continue
            other_team = t.properties.get('team', '')
            if not other_team:
                continue
            if other_team == my_team:
                continue  # Same team = ally, not enemy
            if not self._teams_hostile(my_team, other_team):
                continue  # Different team but not enemies (e.g. neutral factions)

            # PERF: compare squared distances — only used for a threshold
            # and closest-of check, so the sqrt in glm.distance is wasted.
            diff = my_pos - glm.vec3(t.pos)
            dist_sq = glm.dot(diff, diff)
            if dist_sq > max_range_sq:
                continue
            if dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_monster = t

        return best_monster


    def _find_monster_in_crossfire(self, shooter, ray_start: glm.vec3,
                                    ray_end: glm.vec3):
        """Check if a living monster (other than the shooter) intersects
        the ray from ray_start to ray_end.  Returns the closest hit monster
        or None.  Used for Doom-style infighting — when monster A fires at
        the player and monster B is in the way, B takes the hit instead.

        Team-aware: same-team monsters are never hit by crossfire."""
        ray_dir = ray_end - ray_start
        ray_len = glm.length(ray_dir)
        if ray_len < 1.0:
            return None
        ray_dir = ray_dir / ray_len

        best_t = ray_len
        best_victim = None
        shooter_team = shooter.properties.get('team', '')
        monster_things = getattr(self.lt, '_monster_things', None) or self.lt.things

        for t in monster_things:
            if monster_things is self.lt.things and not isinstance(t, MonsterThing):
                continue
            if t is shooter:
                continue
            if t.properties.get('dead', False) or t.properties.get('hidden', False):
                continue

            # Team-aware crossfire: never hit same-team allies
            target_team = t.properties.get('team', '')
            if shooter_team and target_team and shooter_team == target_team:
                continue

            # Sphere intersection (same radius used by player shooting)
            radius = 80.0
            center = glm.vec3(t.pos[0], t.pos[1] + 64.0, t.pos[2])
            oc = ray_start - center
            a = glm.dot(ray_dir, ray_dir)
            b = 2.0 * glm.dot(oc, ray_dir)
            c = glm.dot(oc, oc) - radius * radius
            disc = b * b - 4.0 * a * c
            if disc < 0.0:
                continue
            hit_t = (-b - math.sqrt(disc)) / (2.0 * a)
            if 0.0 < hit_t < best_t:
                best_t = hit_t
                best_victim = t

        return best_victim

    def _apply_monster_damage(self, victim, damage: int, attacker=None):
        """Deal damage to a monster from another monster (infighting).
        Sets the victim's aggro target to the attacker so it retaliates."""
        health_raw = victim.properties.get('health', 100)
        try:
            health = int(health_raw)
        except (ValueError, TypeError):
            health = 100

        new_health = health - damage
        victim.properties['health'] = new_health
        # Brief red flash so a hit reads clearly in the top-down view.
        victim.properties['_hit_flash'] = MONSTER_HIT_FLASH_TIME

        if self.lt.io_manager:
            self.lt.io_manager.fire_output(victim, 'OnDamaged')

        if self.monster_debug_active:
            v_name = victim.properties.get('name', '?')
            a_name = attacker.properties.get('name', '?') if attacker else '?'
            debug_log("MonsterAI",
                       f"Infighting: {v_name} took {damage} dmg from {a_name} "
                       f"(health {health} -> {new_health})")

        if new_health <= 0:
            victim.properties['dead'] = True
            victim.properties.pop('is_shooting', None)
            victim.properties.pop('_aggro_target', None)
            if self.lt.io_manager:
                self.lt.io_manager.fire_output(victim, 'OnDeath')
            if self.monster_debug_active:
                v_name = victim.properties.get('name', '?')
                debug_log("MonsterAI",
                    f'<a href="filter:{v_name}" style="color: #EF5350; font-weight: bold; text-decoration: none;">{v_name}</a> '
                    f'<span style="color: #B71C1C; font-weight: bold;">DIED</span>')
        elif attacker is not None:
            # Retaliate — set aggro toward the attacker
            victim.properties['_aggro_target'] = id(attacker)
            # Wake the victim if it was asleep
            victim.properties['awake'] = True
            if self.monster_debug_active:
                v_name = victim.properties.get('name', '?')
                a_name = attacker.properties.get('name', '?')
                debug_log("MonsterAI",
                    f'<a href="filter:{v_name}" style="color: #EF5350; font-weight: bold; text-decoration: none;">{v_name}</a> '
                    f'was shot by '
                    f'<a href="filter:{a_name}" style="color: #42A5F5; font-weight: bold; text-decoration: none;">{a_name}</a> '
                    f'and has gone '
                    f'<span style="color: #FFEE58; font-weight: bold;">AGGRO</span>')

    # -------------------------------------------------------------------------
    # Projectile system (flying monsters)
    # -------------------------------------------------------------------------

    @staticmethod
    def _primary_spell(thing):
        """The next assigned spell dict for a caster, or None.

        Reads ``properties['spells']`` — a list of ``{id, color, damage, speed}``
        entries authored in the editor's Spells tab — and rotates through them
        one per shot so a mage with several spells cycles its bolts."""
        spells = thing.properties.get('spells')
        if not isinstance(spells, list) or not spells:
            return None
        idx = int(thing.properties.get('_spell_rr', 0)) % len(spells)
        thing.properties['_spell_rr'] = idx + 1
        entry = spells[idx]
        return entry if isinstance(entry, dict) else None

    def _spawn_monster_projectile(self, thing, target_pos: glm.vec3, damage: int, owner_id: int,
                                  sprite: str = None, size=None, speed: float = None,
                                  color=None, embeds: bool = False, kind: str = None):
        """Spawn a projectile sprite (a lobbed bolt, or an arrow for archers).

        The projectile travels toward the target position and can be dodged.
        *sprite* / *size* / *speed* let a bow-armed attacker fire a fast arrow
        instead of the default flying-monster bolt. *embeds* mirrors the
        player arrow's behaviour (see ``game.runtime._spawn_player_arrow_projectile``):
        when true the shaft is left sticking in whatever it hits (or the wall)
        via ``LogicThread._embed_projectile`` instead of just vanishing on
        impact. *kind* is a free-form tag (e.g. ``"arrow"``) carried through
        to the embedded-shaft record for anything that wants to distinguish
        arrows from bolts later."""
        from .monster_constants import (
            MONSTER_PROJECTILE_SPEED,
            MONSTER_PROJECTILE_MAX_DIST,
            MONSTER_PROJECTILE_SPRITE_SIZE,
            MONSTER_PROJECTILE_SPRITE,
        )

        proj_speed = float(speed) if speed else MONSTER_PROJECTILE_SPEED

        start_pos = glm.vec3(thing.pos[0], thing.pos[1] + 64.0, thing.pos[2])
        direction = target_pos - start_pos
        dir_len = glm.length(direction)
        if dir_len < 0.001:
            direction = glm.vec3(0, 0, 1)
            dir_len = 1.0
        direction = direction / dir_len

        # Get custom projectile sprite or the caller-supplied / default one.
        sprite = (sprite or thing.properties.get('projectile_sprite')
                  or MONSTER_PROJECTILE_SPRITE)
        if size is None:
            size = thing.properties.get('projectile_size', MONSTER_PROJECTILE_SPRITE_SIZE)
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            size = MONSTER_PROJECTILE_SPRITE_SIZE

        # Projectile tint (RGB 0-255): explicit colour, else the caster's
        # authored projectile_colour. None renders the sprite untinted.
        if color is None:
            color = thing.properties.get('projectile_colour')

        projectile = {
            'pos': [start_pos.x, start_pos.y, start_pos.z],
            'vel': [direction.x * proj_speed,
                    direction.y * proj_speed,
                    direction.z * proj_speed],
            'owner_id': owner_id,
            'sprite': sprite,
            'lifetime': MONSTER_PROJECTILE_MAX_DIST / proj_speed,
            'damage': damage,
            'size': tuple(size),
            'color': list(color) if color else None,
            'distance_travelled': 0.0,
            'embeds': embeds,
            'kind': kind,
        }

        # Add to logic thread's projectile list for update
        if not hasattr(self.lt, '_monster_projectiles'):
            self.lt._monster_projectiles = []
        self.lt._monster_projectiles.append(projectile)

        if self.monster_debug_active:
            name = thing.properties.get('name', '?')
            debug_log("MonsterAI", f"{name} spawned projectile → ({target_pos.x:.0f}, {target_pos.y:.0f}, {target_pos.z:.0f})")

    # -------------------------------------------------------------------------
    # Patrol system (PathNode navigation)
    # -------------------------------------------------------------------------

    @staticmethod
    def _nearest_audible_noise(thing_pos: glm.vec3, hearing_range: float, events: list):
        """Return the closest noise event audible from thing_pos, or None.

        Each event's reach is the monster's hearing range scaled by the
        event's 'loudness' (gunfire carries further than a water splash), so
        a quiet event has to be closer to register.
        PERF: squared distances — only used for threshold + closest compares.
        """
        best_event = None
        best_dist_sq = float('inf')
        for event in events:
            ex, ey, ez = event['pos']
            dx = thing_pos.x - ex
            dy = thing_pos.y - ey
            dz = thing_pos.z - ez
            dist_sq = dx * dx + dy * dy + dz * dz
            reach = hearing_range * event.get('loudness', 1.0)
            if dist_sq <= reach * reach and dist_sq < best_dist_sq:
                best_dist_sq = dist_sq
                best_event = event
        return best_event

    def _hears_noise(self, monster):
        """Return the closest recent player-noise event this monster can hear,
        or None. Deaf monsters (can_hear False) never hear anything. Used to
        wake sleeping monsters — investigation of the source is handled by
        _investigate_sounds once the monster is awake."""
        if not monster.properties.get('can_hear', False):
            return None
        events = self.lt.get_recent_noise_events(max_age=2.0)
        if not events:
            return None
        hearing_range = float(monster.properties.get('sight', MONSTER_SIGHT_RANGE))
        return self._nearest_audible_noise(glm.vec3(monster.pos), hearing_range, events)

    def _investigate_sounds(self, monster, state: Dict, mtype: str, delta: float, player_pos: glm.vec3) -> bool:
        """Check for recent player noises and move toward them if within range. Returns True if investigating."""
        if not monster.properties.get('can_hear', False):
            return False

        # Check for recent player-noise events (gunfire, water splashes, …)
        noise_events = self.lt.get_recent_noise_events(max_age=3.0)
        if not noise_events:
            # Clear any expired investigation
            if state.get('investigating_sound') is not None:
                state['investigating_sound'] = None
            return False

        thing_pos = glm.vec3(monster.pos)
        hearing_range = float(monster.properties.get('sight', MONSTER_SIGHT_RANGE))
        current_time = time.perf_counter()

        # Find the closest noise event within (loudness-scaled) hearing range
        best_event = self._nearest_audible_noise(thing_pos, hearing_range, noise_events)

        if best_event is None:
            # No sounds in range
            if state.get('investigating_sound') is not None:
                state['investigating_sound'] = None
            return False

        # Check if investigation has expired (sound is too old)
        sound_pos = glm.vec3(best_event['pos'][0], best_event['pos'][1], best_event['pos'][2])
        sound_age = current_time - best_event['time']

        # If the sound is older than 2 seconds, stop investigating
        if sound_age > 2.0:
            state['investigating_sound'] = None
            return False

        # Check if we've arrived at the sound source (within 64 units)
        _arrive_diff = thing_pos - sound_pos
        if glm.dot(_arrive_diff, _arrive_diff) <= 64.0 * 64.0:
            # Reached the sound location - look around briefly then resume patrol
            if self.monster_debug_active:
                name = monster.properties.get('name', '?')
                debug_log("MonsterAI", f"{name} reached sound location, looking around...")
            state['investigating_sound'] = None
            return False

        # Move toward the sound source
        direction = sound_pos - thing_pos
        dir_len = glm.length(direction)
        if dir_len > 0.001:
            direction = direction / dir_len
            if mtype != 'flying':
                direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
            self._face_dir(monster, direction)
            step = direction * MONSTER_MOVE_SPEED * delta
            new_pos = thing_pos + step

            if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
                monster.pos = [new_pos.x, new_pos.y, new_pos.z]
            else:
                # Try sliding along walls
                slide_x = glm.vec3(thing_pos.x + step.x, thing_pos.y, thing_pos.z)
                slide_z = glm.vec3(thing_pos.x, thing_pos.y, thing_pos.z + step.z)
                if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                    monster.pos = [slide_x.x, slide_x.y, slide_z.z]
                elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                    monster.pos = [slide_z.x, slide_z.y, slide_z.z]

        state['investigating_sound'] = (sound_pos, current_time + 3.0)

        if self.monster_debug_active:
            name = monster.properties.get('name', '?')
            src = best_event.get('source', 'noise')
            noise_label = {
                'gunfire': 'gunfire', 'player': 'gunfire',
                'water_enter': 'a splash', 'water_exit': 'a splash',
            }.get(src, 'a noise')
            debug_log("MonsterAI",
                f'<a href="filter:{name}" style="color: #FFA726; font-weight: bold; text-decoration: none;">{name}</a> '
                f'<span style="color: #FFA726;">investigating {noise_label} within Range at ({sound_pos.x:.0f}, {sound_pos.y:.0f}, {sound_pos.z:.0f})</span>')
            # Draw debug ray to sound source
            self._debug_rays.append({
                'start': [thing_pos.x, thing_pos.y + 64.0, thing_pos.z],
                'end': [sound_pos.x, sound_pos.y, sound_pos.z],
                'color': 'orange',
            })

        return True

    def _update_monster_patrol(self, monster, state: Dict, mtype: str, delta: float):
        """Move monster along a chain of PathNodes when player is out of sight."""
        if not monster.properties.get('patrol', False):
            if state.get('patrol_at_target'):
                state['patrol_at_target'] = False
                state['patrol_chain'] = []
            state.pop('detour_node', None)
            return

        target_name = monster.properties.get('patrol_target', '') or ''
        if not target_name:
            return

        mname = monster.properties.get('name', '?')
        patrol_mode = str(monster.properties.get('patrol_mode', 'loop')).lower()
        if patrol_mode not in ('loop', 'ping_pong', 'once'):
            patrol_mode = 'loop'

        # ---- Build / rebuild chain when target changes ----
        chain_built_from = state.get('patrol_chain_built_from', '')
        if chain_built_from != target_name or not state.get('patrol_chain'):
            chain = self._build_patrol_chain(target_name, mtype)
            if not chain:
                if state.get('patrol_warn_missing') != target_name:
                    state['patrol_warn_missing'] = target_name
                    node = self._find_path_node_by_name(target_name)
                    if node is None:
                        debug_log("Pathfinding", f"Monster '{mname}' patrol_target '{target_name}' not found.")
                    else:
                        debug_log("Pathfinding", f"Monster '{mname}' (type={mtype}) rejected by PathNode '{target_name}' (affects_type={node.get_affects_type()}).")
                return
            state['patrol_chain'] = chain
            state['patrol_chain_built_from'] = target_name
            state['patrol_chain_idx'] = 0
            state['patrol_chain_dir'] = 1
            state['patrol_at_target'] = False
            state['patrol_waiting'] = False
            state['patrol_wait_remaining'] = 0.0
            state['patrol_finished'] = False
            state['patrol_warn_missing'] = ''
            state['patrol_walking_to'] = ''
            state['detour_node'] = ''
            debug_log("Pathfinding", f"'{mname}' patrol chain built: {' -> '.join(chain)}  (mode={patrol_mode})")

        chain = state.get('patrol_chain', [])
        if not chain:
            return

        if state.get('patrol_finished'):
            return

        idx = state.get('patrol_chain_idx', 0)
        if idx < 0 or idx >= len(chain):
            idx = 0
            state['patrol_chain_idx'] = 0

        current_node_name = chain[idx]
        node = self._find_path_node_by_name(current_node_name)
        if node is None:
            state['patrol_chain'] = []
            return

        # ---- Waiting at node? ----
        if state.get('patrol_waiting'):
            remaining = state.get('patrol_wait_remaining', 0.0) - delta
            if remaining > 0.0:
                state['patrol_wait_remaining'] = remaining
                return
            state['patrol_waiting'] = False
            state['patrol_wait_remaining'] = 0.0
            if self.lt.io_manager:
                self.lt.io_manager.fire_output(node, 'OnWaitEnd')
            debug_log("Pathfinding", f"'{mname}' finished waiting at '{current_node_name}'")
            self._advance_patrol_index(monster, state, chain, patrol_mode, mname)
            if state.get('patrol_finished'):
                return
            idx = state.get('patrol_chain_idx', 0)
            if idx < 0 or idx >= len(chain):
                return
            current_node_name = chain[idx]
            node = self._find_path_node_by_name(current_node_name)
            if node is None:
                state['patrol_chain'] = []
                return

        # ---- Distance to target node ----
        m_pos = glm.vec3(monster.pos)
        n_pos = glm.vec3(node.pos)
        if mtype == 'flying':
            to_node = n_pos - m_pos
            dist_to_node = glm.length(to_node)
        else:
            flat = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
            dist_to_node = glm.length(flat)
            to_node = flat

        radius = node.get_radius()

        # ---- Arrived at current node? ----
        if dist_to_node <= radius:
            if not state.get('patrol_at_target'):
                state['patrol_at_target'] = True
                if self.lt.io_manager:
                    self.lt.io_manager.fire_output(node, 'OnMonsterArrived')
                debug_log("Pathfinding", f"'{mname}' arrived at '{current_node_name}' (dist={dist_to_node:.0f}, radius={radius:.0f})")

            wait = node.get_wait_time()
            if wait > 0.0 and not state.get('patrol_waiting'):
                state['patrol_waiting'] = True
                state['patrol_wait_remaining'] = wait
                if self.lt.io_manager:
                    self.lt.io_manager.fire_output(node, 'OnWaitStart')
                debug_log("Pathfinding", f"'{mname}' waiting {wait:.1f}s at '{current_node_name}'")
                return

            self._advance_patrol_index(monster, state, chain, patrol_mode, mname)
            if state.get('patrol_finished'):
                return
            idx = state.get('patrol_chain_idx', 0)
            if idx < 0 or idx >= len(chain):
                return
            current_node_name = chain[idx]
            node = self._find_path_node_by_name(current_node_name)
            if node is None:
                state['patrol_chain'] = []
                return
            n_pos = glm.vec3(node.pos)
            if mtype == 'flying':
                to_node = n_pos - m_pos
                dist_to_node = glm.length(to_node)
            else:
                flat = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
                dist_to_node = glm.length(flat)
                to_node = flat
            radius = node.get_radius()
            if dist_to_node <= radius:
                return

        # ---- Left a node? ----
        if state.get('patrol_at_target'):
            prev_name = chain[state.get('patrol_chain_idx', 0)]
            prev_node = self._find_path_node_by_name(prev_name)
            if prev_node is not None and self.lt.io_manager:
                self.lt.io_manager.fire_output(prev_node, 'OnMonsterLeft')
            state['patrol_at_target'] = False
            debug_log("Pathfinding", f"'{mname}' left radius of '{prev_name}'")

        if state.get('patrol_walking_to') != current_node_name:
            state['patrol_walking_to'] = current_node_name
            debug_log("Pathfinding", f"'{mname}' patrolling -> '{current_node_name}' (dist={dist_to_node:.0f})")

        # ---- Detour handling ----
        detour_name = state.get('detour_node', '')
        if detour_name:
            detour_node = self._find_path_node_by_name(detour_name)
            if detour_node is None or detour_node.properties.get('disabled', False):
                state['detour_node'] = ''
                debug_log("Pathfinding", f"'{mname}' detour node '{detour_name}' gone – resuming normal patrol")
            else:
                d_pos = glm.vec3(detour_node.pos)
                if mtype == 'flying':
                    d_vec = d_pos - m_pos
                else:
                    d_vec = glm.vec3(d_pos.x - m_pos.x, 0.0, d_pos.z - m_pos.z)
                d_dist = glm.length(d_vec)
                d_radius = detour_node.get_radius()
                if d_dist <= d_radius:
                    state['detour_node'] = ''
                    state['patrol_blocked_count'] = 0
                    debug_log("Pathfinding", f"'{mname}' reached detour node '{detour_name}' – resuming patrol toward '{current_node_name}'")
                    return
                to_node = d_vec
                dist_to_node = d_dist
                speed_mult = detour_node.get_patrol_speed()
        else:
            speed_mult = node.get_patrol_speed()

        # ---- Movement toward node ----
        dir_len = glm.length(to_node)
        if dir_len <= 0.001:
            return
        direction = to_node / dir_len
        if mtype != 'flying':
            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
        self._face_dir(monster, direction)

        step = direction * MONSTER_MOVE_SPEED * speed_mult * delta
        new_pos = m_pos + step

        if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
            monster.pos = [new_pos.x, new_pos.y, new_pos.z]
            state['patrol_blocked_count'] = 0
        else:
            slide_x = glm.vec3(m_pos.x + step.x, m_pos.y, m_pos.z)
            slide_z = glm.vec3(m_pos.x, m_pos.y, m_pos.z + step.z)
            if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                monster.pos = [slide_x.x, slide_x.y, slide_z.z]
                state['patrol_blocked_count'] = 0
            elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                monster.pos = [slide_z.x, slide_z.y, slide_z.z]
                state['patrol_blocked_count'] = 0
            else:
                blocked_count = state.get('patrol_blocked_count', 0) + 1
                state['patrol_blocked_count'] = blocked_count
                if blocked_count == 1 or blocked_count % 120 == 0:
                    debug_log("Pathfinding", f"'{mname}' blocked by wall en route to '{current_node_name}' (stuck for {blocked_count} ticks)")

                if blocked_count >= MONSTER_STUCK_THRESHOLD and not state.get('detour_node'):
                    detour = self._find_nearby_detour_node(m_pos, current_node_name, mtype)
                    if detour:
                        state['detour_node'] = detour
                        state['patrol_blocked_count'] = 0
                        debug_log("Pathfinding", f"'{mname}' DETOUR: blocked at '{current_node_name}', switching to '{detour}'")

    def _advance_patrol_index(self, monster, state: Dict, chain: List[str], patrol_mode: str, mname: str):
        """Advance patrol index and fire OnMonsterLeft on the node we leave."""
        if not chain:
            return

        old_idx = state.get('patrol_chain_idx', 0)
        old_name = chain[old_idx] if old_idx < len(chain) else ''
        direction = state.get('patrol_chain_dir', 1)

        if old_name:
            old_node = self._find_path_node_by_name(old_name)
            if old_node is not None and self.lt.io_manager:
                self.lt.io_manager.fire_output(old_node, 'OnMonsterLeft')
        state['patrol_at_target'] = False
        state['patrol_walking_to'] = ''

        new_idx = old_idx + direction

        if patrol_mode == 'loop':
            if new_idx >= len(chain):
                new_idx = 0
            elif new_idx < 0:
                new_idx = len(chain) - 1

        elif patrol_mode == 'ping_pong':
            if new_idx >= len(chain):
                direction = -1
                new_idx = max(0, old_idx - 1)
                if len(chain) == 1:
                    new_idx = 0
                debug_log("Pathfinding", f"'{mname}' ping_pong reverse at end of chain")
            elif new_idx < 0:
                direction = 1
                new_idx = min(len(chain) - 1, old_idx + 1)
                if len(chain) == 1:
                    new_idx = 0
                debug_log("Pathfinding", f"'{mname}' ping_pong reverse at start of chain")
            state['patrol_chain_dir'] = direction

        elif patrol_mode == 'once':
            if new_idx >= len(chain) or new_idx < 0:
                state['patrol_finished'] = True
                debug_log("Pathfinding", f"'{mname}' completed 'once' patrol – holding at '{old_name}'")
                return

        state['patrol_chain_idx'] = new_idx
        next_name = chain[new_idx] if new_idx < len(chain) else ''
        if next_name:
            debug_log("Pathfinding", f"'{mname}' advancing → '{next_name}' (chain idx {new_idx}/{len(chain)-1})")

    def _build_patrol_chain(self, start_name: str, mtype: str) -> List[str]:
        """Walk next_node links to build an ordered patrol chain."""
        chain = []
        visited = set()
        current = start_name
        while current and current not in visited:
            node = self._find_path_node_by_name(current)
            if node is None:
                break
            if not node.accepts_monster_type(mtype):
                break
            visited.add(current)
            chain.append(current)
            current = node.get_next_node_name()
        return chain

    def _find_path_node_by_name(self, name: str):
        """Return PathNode thing with given name, or None.
        Uses LogicThread's name cache for O(1) lookup."""
        if not name or PathNode is None:
            return None
        # Use the O(1) name cache on the parent LogicThread
        entity = self.lt._name_cache.get(name)
        if entity is not None and isinstance(entity, PathNode):
            return entity
        return None

    def _find_nearby_detour_node(self, m_pos: glm.vec3, blocked_node_name: str, mtype: str) -> str:
        """Find a nearby PathNode that accepts this monster type to route around an obstacle."""
        if PathNode is None:
            return ''

        best_name = ''
        best_dist = MONSTER_DETOUR_RANGE + 1.0

        for t in self.lt.things:
            if not isinstance(t, PathNode):
                continue
            node_name = t.properties.get('name', '')
            if not node_name or node_name == blocked_node_name:
                continue
            if t.properties.get('disabled', False):
                continue
            if not t.accepts_monster_type(mtype):
                continue

            n_pos = glm.vec3(t.pos)
            if mtype == 'flying':
                diff = n_pos - m_pos
            else:
                diff = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
            dist = glm.length(diff)
            if dist > MONSTER_DETOUR_RANGE or dist < 1.0:
                continue
            if dist >= best_dist:
                continue

            direction = diff / dist
            test_pos = m_pos + direction * MONSTER_MOVE_SPEED * 0.016
            if self._monster_overlaps_wall(test_pos.x, test_pos.y, test_pos.z, MONSTER_WALL_MARGIN):
                continue

            best_dist = dist
            best_name = node_name

        if best_name:
            debug_log("Pathfinding", f"Detour found: {best_name} at distance {best_dist:.0f}")
        return best_name

    # -------------------------------------------------------------------------
    # Helper methods — NOW DELEGATE TO SPATIAL GRID
    # -------------------------------------------------------------------------

    def _has_line_of_sight(self, start: glm.vec3, end: glm.vec3) -> bool:
        """Return True if ray from start to end hits no solid wall brush."""
        if self._grid:
            return self._grid.has_line_of_sight(start, end, self.lt.intersect_ray_aabb)

        # Fallback: full brush scan (should not happen in play mode)
        ray_dir = end - start
        ray_len = glm.length(ray_dir)
        if ray_len < 0.001:
            return True
        ray_dir = ray_dir / ray_len

        for brush in self.lt.brushes:
            if brush.get('hidden') or is_water_brush(brush) or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            b_min = pos - size * 0.5
            b_max = pos + size * 0.5
            hit, dist = self.lt.intersect_ray_aabb(start, ray_dir, b_min, b_max)
            if hit and dist < ray_len - 0.1:
                return False
        return True

    def _monster_raycast_down(self, x: float, z: float, start_y: float = 10000.0) -> Optional[float]:
        """Return Y of the highest solid brush surface below (x, z), or None."""
        if self._grid:
            return self._grid.raycast_down(x, z, start_y)

        # Fallback
        best_y = None
        for brush in self.lt.brushes:
            if brush.get('hidden') or is_water_brush(brush) or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = brush['pos']
            size = brush['size']
            bx_min = pos[0] - size[0] * 0.5
            bx_max = pos[0] + size[0] * 0.5
            bz_min = pos[2] - size[2] * 0.5
            bz_max = pos[2] + size[2] * 0.5
            by_max = pos[1] + size[1] * 0.5

            if bx_min <= x <= bx_max and bz_min <= z <= bz_max:
                if by_max <= start_y:
                    if best_y is None or by_max > best_y:
                        best_y = by_max
        return best_y

    def _monster_overlaps_wall(self, mx: float, my: float, mz: float, margin: float) -> bool:
        """Check if a monster-sized box at (mx, my, mz) overlaps any solid wall brush."""
        if self._grid:
            return self._grid.overlaps_wall(mx, my, mz, margin)

        # Fallback
        for brush in self.lt.brushes:
            if brush.get('hidden') or is_water_brush(brush) or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = brush['pos']
            size = brush['size']
            bx_min = pos[0] - size[0] * 0.5
            bx_max = pos[0] + size[0] * 0.5
            by_min = pos[1] - size[1] * 0.5
            by_max = pos[1] + size[1] * 0.5
            bz_min = pos[2] - size[2] * 0.5
            bz_max = pos[2] + size[2] * 0.5

            m_xmin = mx - margin
            m_xmax = mx + margin
            m_ymin = my
            m_ymax = my + 128.0
            m_zmin = mz - margin
            m_zmax = mz + margin

            if (m_xmax > bx_min and m_xmin < bx_max and
                m_ymax > by_min and m_ymin < by_max and
                m_zmax > bz_min and m_zmin < bz_max):
                return True
        return False


class MonsterAIThread(threading.Thread):
    """
    Dedicated thread for running MonsterAI updates.
    Runs at a lower tick rate (default 30 Hz) to reduce contention
    with the main logic thread.
    """
    def __init__(self, logic_thread, monster_ai, lock, tick_rate: int = 30):
        super().__init__(daemon=True, name="MonsterAIThread")
        self.lt = logic_thread
        self.monster_ai = monster_ai
        self.lock = lock
        self.tick_rate = tick_rate
        self.tick_duration = 1.0 / tick_rate
        self.running = False
        
    def run(self):
        self.running = True
        last_time = time.perf_counter()
        accumulator = 0.0
        
        while self.running:
            current_time = time.perf_counter()
            frame_time = current_time - last_time
            last_time = current_time
            
            if frame_time > 0.25:
                frame_time = 0.25
                
            accumulator += frame_time
            
            while accumulator >= self.tick_duration:
                with self.lock:
                    self.monster_ai.update(self.tick_duration)
                accumulator -= self.tick_duration
                
            sleep_time = self.tick_duration - (time.perf_counter() - current_time)
            if sleep_time > 0:
                time.sleep(sleep_time * 0.9)
                
    def stop(self):
        self.running = False
