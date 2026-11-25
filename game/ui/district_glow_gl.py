"""
The border glow (game/district_glow.py), in the 3D pass.

Drawn in Fio's ``render.pre_sprites`` hook -- after the terrain, before the
actors -- only while the player is near a border: the soft fill lightens the
ground under it (a screen blend, so it reads on dark grass), and the crisp
edge against the ink is laid over it. Depth-tested (a hill hides it), never
writing depth (whatever stands on it covers it). Uploaded only when the
strip is rebuilt; two draw calls a frame while it shows, none otherwise.

Guarded like the magic: if a GL call fails, the glow turns itself off for
the session rather than taking the frame down.
"""

from __future__ import annotations

import ctypes

import numpy as np

_VERT = """#version 330 core
layout (location = 0) in vec3 pos;
layout (location = 1) in vec4 colour;
uniform mat4 viewProj;
out vec4 vColour;
void main() {
    vColour = colour;
    gl_Position = viewProj * vec4(pos, 1.0);
}"""

_FRAG = """#version 330 core
in vec4 vColour;
uniform float show;
uniform int screen;     // 1: premultiplied, for a screen blend
out vec4 FragColor;
void main() {
    float a = vColour.a * show;
    FragColor = screen == 1 ? vec4(vColour.rgb * a, a) : vec4(vColour.rgb, a);
}"""


class _State:
    ok = None
    prog = 0
    loc = {}
    vaos = {}           # "fill"/"edge" -> (vao, vbo, uploaded key, count)


_S = _State()


def _init(gl) -> bool:
    if _S.ok is not None:
        return _S.ok
    try:
        from OpenGL.GL import shaders
        _S.prog = shaders.compileProgram(
            shaders.compileShader(_VERT, gl.GL_VERTEX_SHADER),
            shaders.compileShader(_FRAG, gl.GL_FRAGMENT_SHADER), validate=False)
        _S.loc = {n: gl.glGetUniformLocation(_S.prog, n) for n in ("viewProj", "show", "screen")}
        for name in ("fill", "edge"):
            vao = gl.glGenVertexArrays(1)
            vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 28, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(1)
            gl.glVertexAttribPointer(1, 4, gl.GL_FLOAT, gl.GL_FALSE, 28, ctypes.c_void_p(12))
            _S.vaos[name] = [vao, vbo, None, 0]
        gl.glBindVertexArray(0)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        _S.ok = True
    except Exception as exc:
        print(f"[MiniWind] border glow unavailable: {exc}")
        _S.ok = False
    return _S.ok


def _upload(gl, name, data, key):
    slot = _S.vaos[name]
    if slot[2] != key:
        arr = np.ascontiguousarray(data, dtype=np.float32)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, slot[1])
        gl.glBufferData(gl.GL_ARRAY_BUFFER, arr.nbytes, arr, gl.GL_DYNAMIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        slot[2], slot[3] = key, len(arr)
    return slot


def draw(projection, view, glow) -> int:
    """Draw *glow* (a :class:`game.district_glow.Glow`, updated this frame);
    returns how many triangles were drawn."""
    if glow is None or glow.show <= 0.0 or glow.fill is None:
        return 0
    import OpenGL.GL as gl
    import glm
    if not _init(gl):
        return 0
    try:
        prev_prog = gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM)
        blend = gl.glIsEnabled(gl.GL_BLEND)
        depth = gl.glIsEnabled(gl.GL_DEPTH_TEST)
        cull = gl.glIsEnabled(gl.GL_CULL_FACE)
        offset = gl.glIsEnabled(gl.GL_POLYGON_OFFSET_FILL)
        gl.glUseProgram(_S.prog)
        view_proj = projection * view           # held: value_ptr points into it
        gl.glUniformMatrix4fv(_S.loc["viewProj"], 1, gl.GL_FALSE, glm.value_ptr(view_proj))
        gl.glUniform1f(_S.loc["show"], float(glow.show))
        gl.glEnable(gl.GL_BLEND)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(-2.0, -4.0)
        gl.glDepthMask(gl.GL_FALSE)
        drawn = 0
        key = (id(glow), glow.version)
        for name, data, screen in (("fill", glow.fill, 1), ("edge", glow.edge, 0)):
            if data is None or not len(data):
                continue
            vao, _vbo, _key, count = _upload(gl, name, data, key)
            if screen:
                gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE_MINUS_SRC_COLOR)      # screen: lightens
            else:
                gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glUniform1i(_S.loc["screen"], screen)
            gl.glBindVertexArray(vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, count)
            drawn += count // 3
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glBindVertexArray(0)
        gl.glUseProgram(int(prev_prog))
        (gl.glEnable if offset else gl.glDisable)(gl.GL_POLYGON_OFFSET_FILL)
        (gl.glEnable if blend else gl.glDisable)(gl.GL_BLEND)
        (gl.glEnable if depth else gl.glDisable)(gl.GL_DEPTH_TEST)
        (gl.glEnable if cull else gl.glDisable)(gl.GL_CULL_FACE)
        return drawn
    except Exception as exc:
        print(f"[MiniWind] border glow failed, turned off: {exc}")
        _S.ok = False
        return 0
