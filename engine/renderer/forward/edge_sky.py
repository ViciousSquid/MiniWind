"""The sky behind the world, by ``[Renderer] skystyle``.

* **0** (the default): the sky as it always was -- the map's panorama when
  its Primary PlayerStart has one, else the clear colour. Nothing here runs.
* **1**: the map's panorama, or else the game's own sky (the one the water
  reflects: gradient, sun, clouds and weather, the moon and stars). As the
  camera nears the world's edge, space (the built-in Space panorama) comes
  in on the walls of the sky, the clouds kept overhead, the blend running
  down the walls -- so at the edge the world looks out across space.
* **2**: the same, but the whole sky turns to space.
* **3**: space everywhere, all the time.

The change to space eases in and out (EDGE_SKY_FADE seconds for the whole
way) as the camera comes within EDGE_SKY_FAR of the edge, full at
EDGE_SKY_NEAR. Where the edge is not known -- a map without terrain, or
without its strata walls -- the sky is as it always was.
"""

from __future__ import annotations

import glm
import OpenGL.GL as gl

from engine import shaders
from ..core import gl_state
from ..core.raw_calls import uniform_matrix4

#: The sky styles ``skystyle`` takes; any other value is 0.
SKY_STYLES = (0, 1, 2, 3)


class EdgeSkyMixin:
    """The ``skystyle`` sky (see the module). Mixed into ForwardRenderer."""

    #: The built-in Space panorama (the PlayerStart's "Space" sky).
    EDGE_SKY_SPACE = "assets/backgrounds/void-panorama-q80.webp"
    #: Space is full within EDGE_SKY_NEAR of the world's edge and gone beyond
    #: EDGE_SKY_FAR (world units), easing over EDGE_SKY_FADE seconds.
    EDGE_SKY_NEAR = 2500.0
    EDGE_SKY_FAR = 8000.0
    EDGE_SKY_FADE = 1.5

    @staticmethod
    def sky_style_from_config(settings):
        """``[Renderer] skystyle`` as one of SKY_STYLES (0 without one)."""
        if settings is None:
            return 0
        try:
            style = settings.getint('Renderer', 'skystyle', fallback=0)
        except (TypeError, ValueError):
            return 0
        return style if style in SKY_STYLES else 0

    @classmethod
    def edge_sky_target(cls, x, z, bounds):
        """0..1: how much space the sky shows with the camera at (*x*, *z*)
        in a world whose rectangle is *bounds* (min x, max x, min z, max z)."""
        min_x, max_x, min_z, max_z = (float(v) for v in bounds[:4])
        d = min(float(x) - min_x, max_x - float(x), float(z) - min_z, max_z - float(z))
        t = (cls.EDGE_SKY_FAR - d) / (cls.EDGE_SKY_FAR - cls.EDGE_SKY_NEAR)
        t = min(max(t, 0.0), 1.0)
        return t * t * (3.0 - 2.0 * t)

    def advance_edge_sky(self, target, now):
        """Ease the sky's space towards *target* (the frame's time *now*):
        the whole way in EDGE_SKY_FADE seconds. The first frame, or a jump in
        time, takes the target at once. Returns the amount to draw."""
        last = getattr(self, '_edge_sky_time', None)
        amount = getattr(self, '_edge_sky_amount', None)
        now = float(now or 0.0)
        if amount is None or last is None or not (0.0 <= now - last <= 1.0):
            amount = float(target)
        else:
            step = (now - last) / max(self.EDGE_SKY_FADE, 1e-3)
            amount += max(-step, min(step, float(target) - amount))
        self._edge_sky_time = now
        self._edge_sky_amount = amount
        return amount

    def _edge_sky_bounds(self, config):
        terrain = config.get('terrain', None)
        if terrain is None or not terrain.enabled or terrain.skirt is None:
            return None
        return terrain.skirt[:4]

    def _draw_sky(self, projection, view, camera_pos, config, behind=False):
        """The sky pass: the ``skystyle`` sky, or the sky as it always was."""
        style = getattr(self, 'sky_style', 0)
        bounds = self._edge_sky_bounds(config) if style else None
        if (not style or bounds is None or self._portal_scene_pass
                or getattr(self, '_probe_capture_pass', False)
                or not self._ensure_edge_sky()):
            self._draw_background_image(projection, view, behind=behind)
            return
        x, _y, z = self._camera_xyz(camera_pos)
        target = 1.0 if style == 3 else self.edge_sky_target(x, z, bounds)
        amount = self.advance_edge_sky(target, config.get('time', 0.0))
        self._draw_edge_sky(projection, view, camera_pos, amount, style, behind)

    def _ensure_edge_sky(self):
        """The program and the Space panorama's cube map, made on first use
        (False if either cannot be: the sky is then as it always was)."""
        if getattr(self, '_edge_sky_failed', False):
            return False
        if getattr(self, '_edge_sky_program', 0) and getattr(self, '_edge_sky_space', 0):
            return True
        try:
            if not getattr(self, '_edge_sky_program', 0):
                from OpenGL.GL.shaders import compileProgram, compileShader
                program = compileProgram(
                    compileShader(shaders.DEFAULT_SHADERS['void_background.vert'],
                                  gl.GL_VERTEX_SHADER),
                    compileShader(shaders.DEFAULT_SHADERS['edge_sky.frag'],
                                  gl.GL_FRAGMENT_SHADER),
                    validate=False)
                self._edge_sky_program = int(program)
                self._edge_sky_vao = int(gl.glGenVertexArrays(1))
                self._edge_sky_uniforms = {
                    name: gl.glGetUniformLocation(program, name)
                    for name in ('u_inverse_projection', 'u_inverse_view', 'u_sky',
                                 'u_panorama', 'u_space', 'u_edge', 'u_mode', 'u_eye',
                                 'time', 'skyState', 'skyDrift', 'skyClouds')}
            if not getattr(self, '_edge_sky_space', 0):
                textures = self._panorama_textures(self.EDGE_SKY_SPACE)
                if textures is None:
                    raise RuntimeError("the Space panorama could not be loaded")
                flat, cube = textures
                gl_state.glDeleteTextures([flat])
                self._edge_sky_space = cube
            return True
        except Exception as exc:
            print(f"[Renderer] skystyle sky unavailable, drawing the usual sky: {exc}")
            self._edge_sky_failed = True
            return False

    def _draw_edge_sky(self, projection, view, camera_pos, amount, style, behind):
        """Draw the sky at infinite distance: over the whole frame, or,
        *behind*, only where nothing has been drawn yet."""
        u = self._edge_sky_uniforms
        panorama = 0
        if self._background_image_path:
            if self._background_image_texture or self._load_background_image():
                panorama = self._background_cube_texture
        if behind:
            gl_state.glEnable(gl.GL_DEPTH_TEST)
            gl_state.glDepthFunc(gl.GL_LEQUAL)
        else:
            gl_state.glDisable(gl.GL_DEPTH_TEST)
        gl_state.glDepthMask(gl.GL_FALSE)
        gl_state.glDisable(gl.GL_BLEND)
        gl_state.glUseProgram(self._edge_sky_program)
        inverse_projection = glm.inverse(projection)
        inverse_view = glm.inverse(view)
        uniform_matrix4(u['u_inverse_projection'], glm.value_ptr(inverse_projection))
        uniform_matrix4(u['u_inverse_view'], glm.value_ptr(inverse_view))
        eye = self._camera_xyz(camera_pos)
        gl_state.glUniform3f(u['u_eye'], *eye)
        gl_state.glUniform1f(u['u_edge'], float(amount))
        gl_state.glUniform1i(u['u_mode'], int(style))
        gl_state.glUniform1i(u['u_panorama'], 1 if panorama else 0)
        gl_state.glUniform1f(u['time'], float(getattr(self, '_edge_sky_time', 0.0)) % 4096.0)
        sky = getattr(self, 'sky_state', None) or self.DEFAULT_SKY_STATE
        drift = getattr(self, 'sky_drift', None) or (0.0, 0.0)
        gl_state.glUniform4f(u['skyState'], *[float(v) for v in sky])
        gl_state.glUniform2f(u['skyDrift'], float(drift[0]), float(drift[1]))
        # Units 0 and 1: the map's panorama and space; the clouds on theirs.
        gl_state.glUniform1i(u['u_sky'], 0)
        gl_state.glUniform1i(u['u_space'], 1)
        gl_state.glActiveTexture(gl.GL_TEXTURE0)
        gl_state.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, panorama or self._edge_sky_space)
        gl_state.glActiveTexture(gl.GL_TEXTURE1)
        gl_state.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, self._edge_sky_space)
        gl_state.glActiveTexture(gl.GL_TEXTURE0 + self.SKY_CLOUD_UNIT)
        gl_state.glBindTexture(gl.GL_TEXTURE_2D, self._sky_cloud_texture())
        gl_state.glUniform1i(u['skyClouds'], self.SKY_CLOUD_UNIT)
        gl_state.glActiveTexture(gl.GL_TEXTURE0)
        gl_state.glBindVertexArray(self._edge_sky_vao)
        gl_state.glEnable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl_state.glDisable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)
        gl_state.glBindVertexArray(0)
        gl_state.glActiveTexture(gl.GL_TEXTURE1)
        gl_state.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, 0)
        gl_state.glActiveTexture(gl.GL_TEXTURE0)
        gl_state.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, 0)
        gl_state.glUseProgram(0)
        gl_state.glDepthMask(gl.GL_TRUE)
        gl_state.glEnable(gl.GL_DEPTH_TEST)
        gl_state.glDepthFunc(gl.GL_LESS)

    def _cleanup_edge_sky(self):
        """Release the ``skystyle`` sky's GL objects (the context is current)."""
        if getattr(self, '_edge_sky_space', 0):
            gl_state.glDeleteTextures([self._edge_sky_space])
        if getattr(self, '_edge_sky_vao', 0):
            gl_state.glDeleteVertexArrays(1, [self._edge_sky_vao])
        if getattr(self, '_edge_sky_program', 0):
            gl_state.glDeleteProgram(self._edge_sky_program)
        self._edge_sky_space = self._edge_sky_vao = self._edge_sky_program = 0
        self._edge_sky_failed = False
