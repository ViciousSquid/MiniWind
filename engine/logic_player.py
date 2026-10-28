"""
Player runtime for LogicThread.

Owns primary-player and split-screen Player 2 movement/input mechanics plus
the player's water-state sound feedback. LogicThread remains the tick-order
orchestrator.
"""

import math
import threading
import glm

from .physics import world_gravity
from .logic_camera import CAMERA_PITCH_LIMIT

# Qt key values used by the engine's input state.
KEY_W = 0x57
KEY_S = 0x53
KEY_A = 0x41
KEY_D = 0x44
KEY_SPACE = 0x20
KEY_C = 0x43
# Qt::Key_Shift; kept numeric so the engine remains Qt-free.
KEY_SHIFT = 0x01000020
KEY_BRACKET_LEFT = 0x5B
KEY_BRACKET_RIGHT = 0x5D
# Equivalent to a fully deflected right stick, in look pixels per second.
KEYBOARD_LOOK_SPEED = 900.0

_WATER_LOUDNESS = 0.7


class LogicPlayer:
    """Runtime mechanics for the engine's player actors."""

    WATERWALK_INTERVAL = 0.45

    def __init__(self, logic):
        self.logic = logic
        self.player = None
        self._pad_pitch_player = None
        self._pad_pitch_offset = 0.0
        self.player2 = None
        self._player_was_in_water = False
        self._waterwalk_timer = 0.0
        self.collected_keys = set()
        self.p2_turn_sensitivity = 10.0
        self.god_mode = False
        self.buddha_mode = False
        self.notarget = False
        self.player_health = 100
        self.player_max_health = 100
        #: Armor points, taken by damage before health (see
        #: LogicTriggers._apply_player_damage); given by armor pickups.
        self.player_armor = 0
        self.player_max_armor = 100
        self.player_dead = False
        #: What dealt the player's latest hit, ``(source, cause, damage_kind)``
        #: or None: *source* is the attacking entity, a hurt trigger's brush,
        #: or a projectile owner's ``id()``; *cause* says how ("attack",
        #: "bite", "projectile", "trigger", or a game's own). Set by
        #: LogicTriggers._apply_player_damage before the game's damage filter
        #: runs, so a game can say what killed the player.
        self.last_damage = None
        self.damage_lock = threading.Lock()
        self.player2_health = 100
        self.player2_max_health = 100
        self.player2_dead = False

    def give_armor(self, amount):
        """Add *amount* armor, up to ``player_max_armor``."""
        self.player_armor = min(self.player_max_armor,
                                self.player_armor + max(0, int(amount)))

    def update_primary(self, delta, keys, mouse_dx, mouse_dy):
        """Apply primary-player look, movement and physics for one tick."""
        logic = self.logic
        player = self.player
        if not player:
            return

        from .game_input import modal_input_active
        modal = modal_input_active(logic)
        read_pad = getattr(logic.game_state, "consume_gamepad_input", None)
        pad_move, pad_look = read_pad() if read_pad is not None else (None, (0, 0))
        if modal:
            keys = frozenset()
            mouse_dx = mouse_dy = 0
            pad_move = None

        overhead_pad = pad_move is not None and logic.camera.is_overhead()
        if not modal:
            rotation_enabled = getattr(getattr(logic, "game_session", None),
                                       "camera_rotation_enabled", lambda: True)()
            if not rotation_enabled or pad_move is None:
                pad_look = (0.0, 0.0)
            keyboard_dx = (((KEY_BRACKET_RIGHT in keys) - (KEY_BRACKET_LEFT in keys))
                           * KEYBOARD_LOOK_SPEED * delta if rotation_enabled else 0.0)
        else:
            pad_look, keyboard_dx = (0.0, 0.0), 0.0
        if not modal and (pad_move is not None or keyboard_dx):
            if logic.camera.is_overhead():
                if (any(pad_look)
                        or keyboard_dx
                        or str(logic.camera.overhead_orientation).strip().lower() == "player"):
                    logic.camera.rotate_overhead(pad_look[0] + keyboard_dx, pad_look[1],
                                                 player_angle=player.angle)
            else:
                mouse_dx += pad_look[0] + keyboard_dx
                if self._pad_pitch_player is not player:
                    self._pad_pitch_player, self._pad_pitch_offset = player, 0.0
                base = player.pitch - self._pad_pitch_offset
                limit = math.radians(CAMERA_PITCH_LIMIT)
                self._pad_pitch_offset = max(-limit, min(limit,
                    self._pad_pitch_offset - pad_look[1] * 0.002))
                player.pitch = base + self._pad_pitch_offset

        sensitivity = 0.002
        player.angle -= mouse_dx * sensitivity
        player.pitch -= mouse_dy * sensitivity
        player.pitch = max(-1.5, min(1.5, player.pitch))

        # Pointer aiming with an overhead camera: the view publishes the
        # heading under the pointer each frame; None leaves yaw to mouse look.
        aim_yaw = logic.game_state.get_aim_yaw()
        if aim_yaw is not None and not modal and pad_move is None:
            player.angle = aim_yaw

        move_dir = glm.vec3(0)
        if KEY_W in keys:
            move_dir.z += 1
        if KEY_S in keys:
            move_dir.z -= 1
        if KEY_A in keys:
            move_dir.x += 1
        if KEY_D in keys:
            move_dir.x -= 1

        movement_angle = None
        self.pad_moving = pad_move is not None and any(pad_move)
        if pad_move is not None:
            lx, ly = pad_move
            move_dir = glm.vec3(-lx, 0, -ly)
            if overhead_pad:
                movement_angle = logic.camera.overhead_heading(player.angle)
                if lx or ly:
                    # Screen right is (-cos h, sin h); screen up is (sin h, cos h).
                    dx = -lx * math.cos(movement_angle) - ly * math.sin(movement_angle)
                    dz = lx * math.sin(movement_angle) - ly * math.cos(movement_angle)
                    player.angle = math.atan2(dx, dz)

        jump = KEY_SPACE in keys
        crouch = KEY_C in keys
        # A game can hold the player to a walk (out of breath, say).
        sprint = KEY_SHIFT in keys and getattr(player, "sprint_allowed", True)

        extra = {"movement_angle": movement_angle} if movement_angle is not None else {}
        player.update(
            delta,
            move_dir,
            jump,
            crouch,
            logic.collision_runtime._collision_brushes_cache,
            logic.mover_runtime._mover_brush_list,
            logic.mover_runtime._door_brush_list,
            logic.world_runtime.terrain,
            spatial_grid=logic.session_runtime.spatial_grid,
            sprint=sprint,
            gravity=world_gravity(logic.session_runtime.physics_world),
            **extra,
        )

    def update_player2(self, delta):
        """Apply split-screen Player 2 input, look and physics for one tick."""
        logic = self.logic
        if not self.player2 or self.player2_dead:
            return

        p2 = logic.game_state.get_p2_input()
        p2_dir = glm.vec3(float(p2['move_x']), 0.0, float(p2['move_z']))

        turn_input = float(p2['look_dx'])
        self.player2.angle -= turn_input * self.p2_turn_sensitivity * delta
        self.player2.pitch -= float(p2['look_dy']) * 0.002
        self.player2.pitch = max(-1.5, min(1.5, self.player2.pitch))

        self.player2.update(
            delta,
            p2_dir,
            bool(p2['jump']),
            False,
            logic.collision_runtime._collision_brushes_cache,
            logic.mover_runtime._mover_brush_list,
            logic.mover_runtime._door_brush_list,
            logic.world_runtime.terrain,
            spatial_grid=logic.session_runtime.spatial_grid,
            gravity=world_gravity(logic.session_runtime.physics_world),
        )

    def update_water_sounds(self, delta):
        """Queue sounds and monster-noise events from player water state."""
        logic = self.logic
        player = self.player
        if not player:
            return

        in_water = bool(player.in_water)

        if in_water and not self._player_was_in_water:
            logic.game_state.queue_sound(
                {'file': 'enterwater.wav', 'volume': 1.0})
            logic.combat_runtime._emit_noise_event(
                player.pos,
                source='water_enter',
                loudness=_WATER_LOUDNESS,
            )
            self._waterwalk_timer = 0.0
        elif not in_water and self._player_was_in_water:
            logic.game_state.queue_sound(
                {'file': 'exitwater.wav', 'volume': 1.0})
            logic.combat_runtime._emit_noise_event(
                player.pos,
                source='water_exit',
                loudness=_WATER_LOUDNESS,
            )

        self._player_was_in_water = in_water

        wading = (
            in_water
            and not player.swimming
            and player.on_ground
        )
        horiz_speed = math.hypot(
            player.velocity.x,
            player.velocity.z,
        )
        if wading and horiz_speed > 20.0:
            self._waterwalk_timer -= delta
            if self._waterwalk_timer <= 0.0:
                logic.game_state.queue_sound(
                    {'file': 'waterwalk.wav', 'volume': 0.8})
                self._waterwalk_timer = self.WATERWALK_INTERVAL
        else:
            self._waterwalk_timer = 0.0
