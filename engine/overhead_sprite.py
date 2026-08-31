"""
MiniWind overhead sprite renderer.

Weapons are rendered as a separate transparent ground quad:
- resting position is offset to the actor's right, close to the head;
- attacks make the weapon thrust forward rapidly and return;
- the same draw_weapon() path is used by player, NPC and monster actors.
"""

from __future__ import annotations

import math
import os
from typing import Optional


WEAPON_SIZE_MULTIPLIER = 2.0

# Fixed resting offset from the actor centre.
# Positive right_offset means the actor's local right-hand side.
WEAPON_RIGHT_OFFSET = 42.0

# Forward movement during a melee stab.
WEAPON_STAB_DISTANCE = 72.0
WEAPON_STAB_DURATION = 0.14

# Backward "draw" movement during a bow (or staff) firing animation. Shorter
# than the stab distance/duration and moves the opposite way (toward the
# actor) so a bow reads as being drawn and released rather than thrust
# forward like a blade. Kept well under the shortest attacking-window used
# by any caller (the player's 0.2s attack pose) so the motion always
# completes a full draw-and-release cycle instead of snapping mid-pull.
WEAPON_BOW_PULL_DISTANCE = 24.0
WEAPON_BOW_DURATION = 0.18


class SpriteController:
    IDLE = "idle"
    WALK_A = "walk_a"
    WALK_B = "walk_b"
    IDLE_G = "idle_g"
    WALK_A_G = "walk_a_g"
    WALK_B_G = "walk_b_g"
    SHOOT = "shoot"

    def __init__(
        self,
        walk_fps: float = 6.0,
        move_epsilon: float = 0.75,
        shoot_hold: float = 0.18,
    ):
        self.walk_fps = float(walk_fps)
        self.move_epsilon = float(move_epsilon)
        self.shoot_hold = float(shoot_hold)
        self.facing = 0.0
        self.moving = False
        self.armed = False
        self._last_pos = None
        self._anim_t = 0.0
        self._now = 0.0
        self._shoot_until = -1.0

    def update(
        self,
        pos,
        facing: float,
        now: float,
        armed: bool = False,
        shooting: bool = False,
    ) -> None:
        self.facing = float(facing)
        self._now = float(now)
        self.armed = bool(armed)

        p = (float(pos[0]), float(pos[1]), float(pos[2]))

        if self._last_pos is not None:
            dx = p[0] - self._last_pos[0]
            dz = p[2] - self._last_pos[2]
            self.moving = (
                dx * dx + dz * dz
            ) > (self.move_epsilon * self.move_epsilon)
        else:
            self.moving = False

        if self.moving:
            self._anim_t = float(now)

        if shooting:
            self._shoot_until = float(now) + self.shoot_hold

        self._last_pos = p

    def frame(self) -> str:
        if self.armed and self._now < self._shoot_until:
            return self.SHOOT

        if not self.moving:
            base = self.IDLE
        else:
            base = (
                self.WALK_A
                if int(self._anim_t * self.walk_fps) % 2 == 0
                else self.WALK_B
            )

        return (base + "_g") if self.armed else base


_SPRITE_VERT = """#version 330 core
layout (location = 0) in vec2 aPos;
out vec2 TexCoords;
uniform mat4 mvp;
void main() {
    TexCoords = vec2(aPos.x + 0.5, 0.5 - aPos.y);
    gl_Position = mvp * vec4(aPos.x, 0.0, aPos.y, 1.0);
}"""

_SPRITE_FRAG = """#version 330 core
in vec2 TexCoords;
out vec4 FragColor;
uniform sampler2D tex;
uniform vec4 tint;
void main() {
    vec4 c = texture(tex, TexCoords);
    if (c.a < 0.05) discard;
    FragColor = vec4(
        mix(c.rgb, tint.rgb, clamp(tint.a, 0.0, 1.0)),
        c.a
    );
}"""


def _assets_root() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets",
    )


class OverheadSpriteRenderer:
    """Draw overhead actors and their equipped weapons."""

    def __init__(
        self,
        frame_files: Optional[dict] = None,
        size: float = 128.0,
        y_offset: float = 2.0,
        facing_offset_deg: float = 0.0,
    ):
        directory = os.path.join(
            _assets_root(), "sprites", "topdown"
        )

        self.frame_files = frame_files or {
            SpriteController.IDLE:
                os.path.join(directory, "player1.png"),
            SpriteController.WALK_A:
                os.path.join(directory, "player2.png"),
            SpriteController.WALK_B:
                os.path.join(directory, "player3.png"),
            SpriteController.IDLE_G:
                os.path.join(directory, "player1_g.png"),
            SpriteController.WALK_A_G:
                os.path.join(directory, "player2_g.png"),
            SpriteController.WALK_B_G:
                os.path.join(directory, "player3_g.png"),
            SpriteController.SHOOT:
                os.path.join(directory, "player_shoot_g.png"),
        }

        self.size = float(size)
        self.y_offset = float(y_offset)
        self.facing_offset_deg = float(facing_offset_deg)

        self._ok = None
        self._prog = None
        self._vao = None
        self._vbo = None
        self._mvp_loc = -1
        self._tex_loc = -1
        self._tint_loc = -1
        self._textures = {}
        self._gl = None
        self._glm = None

    def facing_theta(self, facing: float) -> float:
        return float(facing) + math.radians(self.facing_offset_deg)

    _FALLBACKS = {
        SpriteController.SHOOT: (
            SpriteController.SHOOT,
            SpriteController.IDLE_G,
            SpriteController.IDLE,
        ),
        SpriteController.IDLE_G: (
            SpriteController.IDLE_G,
            SpriteController.IDLE,
        ),
        SpriteController.WALK_A_G: (
            SpriteController.WALK_A_G,
            SpriteController.WALK_A,
            SpriteController.IDLE_G,
            SpriteController.IDLE,
        ),
        SpriteController.WALK_B_G: (
            SpriteController.WALK_B_G,
            SpriteController.WALK_B,
            SpriteController.IDLE_G,
            SpriteController.IDLE,
        ),
        SpriteController.WALK_A: (
            SpriteController.WALK_A,
            SpriteController.IDLE,
        ),
        SpriteController.WALK_B: (
            SpriteController.WALK_B,
            SpriteController.IDLE,
        ),
        SpriteController.IDLE: (SpriteController.IDLE,),
    }

    def _texture_for(self, frame_key):
        for key in self._FALLBACKS.get(
            frame_key,
            (frame_key, SpriteController.IDLE),
        ):
            texture = self._textures.get(key)
            if texture:
                return texture
        return 0

    def _init_gl(self) -> bool:
        try:
            import numpy as np
            import OpenGL.GL as gl
            import glm
        except Exception:
            return False

        self._gl = gl
        self._glm = glm

        try:
            def compile_shader(source, kind):
                shader = gl.glCreateShader(kind)
                gl.glShaderSource(shader, source)
                gl.glCompileShader(shader)
                if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
                    raise RuntimeError(gl.glGetShaderInfoLog(shader))
                return shader

            vertex = compile_shader(_SPRITE_VERT, gl.GL_VERTEX_SHADER)
            fragment = compile_shader(_SPRITE_FRAG, gl.GL_FRAGMENT_SHADER)

            program = gl.glCreateProgram()
            gl.glAttachShader(program, vertex)
            gl.glAttachShader(program, fragment)
            gl.glLinkProgram(program)

            if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
                raise RuntimeError(gl.glGetProgramInfoLog(program))

            gl.glDeleteShader(vertex)
            gl.glDeleteShader(fragment)

            self._prog = program
            self._mvp_loc = gl.glGetUniformLocation(program, "mvp")
            self._tex_loc = gl.glGetUniformLocation(program, "tex")
            self._tint_loc = gl.glGetUniformLocation(program, "tint")

            quad = np.array(
                [
                    -0.5, -0.5,
                     0.5, -0.5,
                     0.5,  0.5,
                    -0.5, -0.5,
                     0.5,  0.5,
                    -0.5,  0.5,
                ],
                dtype=np.float32,
            )

            self._vao = gl.glGenVertexArrays(1)
            self._vbo = gl.glGenBuffers(1)

            gl.glBindVertexArray(self._vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
            gl.glBufferData(
                gl.GL_ARRAY_BUFFER,
                quad.nbytes,
                quad,
                gl.GL_STATIC_DRAW,
            )
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(
                0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None
            )
            gl.glBindVertexArray(0)

            for key, path in self.frame_files.items():
                self._textures[key] = self._load_texture(path)

            return any(self._textures.values())

        except Exception:
            return False

    def _load_texture(self, path) -> int:
        try:
            import numpy as np
            import OpenGL.GL as gl
            from PIL import Image
        except Exception:
            return 0

        try:
            image = Image.open(path).convert("RGBA")
            data = np.array(image, dtype=np.uint8)

            texture = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)

            gl.glTexParameteri(
                gl.GL_TEXTURE_2D,
                gl.GL_TEXTURE_MIN_FILTER,
                gl.GL_LINEAR,
            )
            gl.glTexParameteri(
                gl.GL_TEXTURE_2D,
                gl.GL_TEXTURE_MAG_FILTER,
                gl.GL_LINEAR,
            )
            gl.glTexParameteri(
                gl.GL_TEXTURE_2D,
                gl.GL_TEXTURE_WRAP_S,
                gl.GL_CLAMP_TO_EDGE,
            )
            gl.glTexParameteri(
                gl.GL_TEXTURE_2D,
                gl.GL_TEXTURE_WRAP_T,
                gl.GL_CLAMP_TO_EDGE,
            )

            gl.glTexImage2D(
                gl.GL_TEXTURE_2D,
                0,
                gl.GL_RGBA,
                image.width,
                image.height,
                0,
                gl.GL_RGBA,
                gl.GL_UNSIGNED_BYTE,
                data,
            )

            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
            return int(texture)

        except Exception:
            return 0

    def _draw_texture(
        self,
        projection,
        view,
        pos,
        facing: float,
        texture: int,
        size: float,
        y_offset: float,
        rotation_offset: float = 0.0,
        tint=(0.0, 0.0, 0.0, 0.0),
    ) -> None:
        try:
            gl = self._gl
            glm = self._glm

            theta = (
                self.facing_theta(facing)
                + float(rotation_offset)
            )

            model = glm.translate(
                glm.mat4(1.0),
                glm.vec3(
                    float(pos[0]),
                    float(pos[1]) + float(y_offset),
                    float(pos[2]),
                ),
            )

            model = glm.rotate(
                model,
                theta,
                glm.vec3(0.0, 1.0, 0.0),
            )

            model = glm.scale(
                model,
                glm.vec3(float(size), 1.0, float(size)),
            )

            mvp = projection * view * model

            gl.glUseProgram(self._prog)
            gl.glUniformMatrix4fv(
                self._mvp_loc,
                1,
                gl.GL_FALSE,
                glm.value_ptr(mvp),
            )

            if self._tint_loc not in (-1, None):
                gl.glUniform4f(
                    self._tint_loc,
                    float(tint[0]),
                    float(tint[1]),
                    float(tint[2]),
                    float(tint[3]),
                )

            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
            gl.glUniform1i(self._tex_loc, 0)

            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(
                gl.GL_SRC_ALPHA,
                gl.GL_ONE_MINUS_SRC_ALPHA,
            )
            gl.glDisable(gl.GL_CULL_FACE)

            gl.glBindVertexArray(self._vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
            gl.glBindVertexArray(0)
            gl.glUseProgram(0)

        except Exception:
            self._ok = False

    def _ready(self) -> bool:
        if self._ok is False:
            return False

        if self._ok is None:
            self._ok = self._init_gl()

        return bool(self._ok)

    def draw(
        self,
        projection,
        view,
        pos,
        facing: float,
        frame_key: str,
        tint=(0.0, 0.0, 0.0, 0.0),
    ) -> None:
        if not self._ready():
            return

        texture = self._texture_for(frame_key)

        if texture:
            self._draw_texture(
                projection,
                view,
                pos,
                facing,
                texture,
                self.size,
                self.y_offset,
                tint=tint,
            )

    def draw_weapon(
        self,
        projection,
        view,
        pos,
        facing: float,
        weapon_path: str,
        now: float,
        attacking: bool = False,
        weapon_kind: str = "melee",
        size: Optional[float] = None,
    ) -> None:
        """Draw an equipped weapon to the actor's right.

        The resting position is offset to the actor's local right-hand side.
        Because the offset is calculated from ``facing``, the weapon remains on
        the character's right regardless of which direction the actor faces.

        During an attack the weapon keeps that right-side origin and performs
        a short, rapid motion before returning to its resting position. Which
        motion depends on ``weapon_kind``:
          - ``"melee"`` (default, covers every non-ranged weapon: swords,
            daggers, maces, axes, warhammers, clubs, ...): a forward stab.
          - ``"bow"`` / ``"staff"``: a shorter pull *back* toward the actor
            (drawing the string / channelling) before snapping back to rest,
            so a ranged weapon visibly moves without lunging forward like a
            blade.
        Player, NPC and monster callers all go through this one path and
        therefore receive identical behaviour for a given weapon kind.
        """

        if not weapon_path or not self._ready():
            return

        key = "weapon:" + str(weapon_path)
        texture = self._textures.get(key)

        if not texture:
            texture = self._load_texture(weapon_path)
            if texture:
                self._textures[key] = texture

        if not texture:
            return

        actor_size = max(1.0, float(self.size))

        weapon_size = max(
            1.0,
            (
                float(size)
                if size is not None
                else actor_size * 0.55
            ) * WEAPON_SIZE_MULTIPLIER,
        )

        facing = float(facing)

        # Engine forward = (sin(facing), cos(facing)).
        forward_x = math.sin(facing)
        forward_z = math.cos(facing)

        # Character's local right = forward rotated clockwise 90 degrees.
        # This is deliberately tied to facing rather than screen coordinates.
        right_x = forward_z
        right_z = -forward_x

        # The weapon's normal resting position: beside the right side of
        # the head, rather than floating in front of the actor.
        weapon_x = (
            float(pos[0])
            + right_x * WEAPON_RIGHT_OFFSET
        )
        weapon_z = (
            float(pos[2])
            + right_z * WEAPON_RIGHT_OFFSET
        )

        thrust = 0.0

        if attacking:
            kind = str(weapon_kind or "melee").lower()

            if kind in ("bow", "staff"):
                # One short draw-and-release cycle: the sine pulls the
                # weapon *back* toward the actor and returns, instead of
                # lunging forward.
                phase = (
                    float(now) % WEAPON_BOW_DURATION
                ) / WEAPON_BOW_DURATION

                thrust = (
                    -math.sin(math.pi * phase)
                    * WEAPON_BOW_PULL_DISTANCE
                )
            else:
                # One short stab cycle. The sine rises rapidly from the
                # resting position to maximum extension and then returns.
                phase = (
                    float(now) % WEAPON_STAB_DURATION
                ) / WEAPON_STAB_DURATION

                thrust = (
                    math.sin(math.pi * phase)
                    * WEAPON_STAB_DISTANCE
                )

        weapon_x += forward_x * thrust
        weapon_z += forward_z * thrust

        self._draw_texture(
            projection,
            view,
            (weapon_x, float(pos[1]), weapon_z),
            facing,
            texture,
            weapon_size,
            self.y_offset + 0.6,
        )
