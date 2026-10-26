"""
Drawing magic: the GL half of :mod:`game.magic_fx`.

Two passes, both run from Fio's ``render.post_scene`` hook (the world is drawn,
the 2D overlay not yet):

* :func:`draw_sprites` -- every live effect quad in one instanced draw call,
  additively blended and depth-tested (a wall still hides a fireball behind
  it). The shapes are procedural, in the fragment shader, so nothing is loaded:
  a bolt orb is a lit sphere with a **fresnel** rim, a ward a fresnel bubble
  with a drifting hex shimmer, plus shockwave rings, rotating rune circles,
  radial rays, flashes, ice stars, lightning arcs and soft motes.
* :func:`draw_lenses` -- the **fisheye** impacts. The finished frame is
  blitted into a texture and drawn back through a distortion shader: around
  each impact the picture bulges as if through a lens, splits a little into
  red, green and blue at the rim, and a refracting shock ring runs outward.
  Only frames with a live lens pay for it.

Everything is guarded: if a GL call fails, the pass turns itself off for the
session rather than taking the frame down with it.
"""

from __future__ import annotations

import ctypes
import math
import time

import numpy as np

_SPRITE_VERT = """#version 330 core
layout (location = 0) in vec2 corner;
layout (location = 1) in vec4 centerSize;
layout (location = 2) in vec4 colour;
layout (location = 3) in vec4 params;      // mode, progress, seed, flat
uniform mat4 viewProj;
uniform vec3 camRight;
uniform vec3 camUp;
out vec2 uv;
out vec4 vColour;
flat out int vMode;
out float vProgress;
out float vSeed;
void main() {
    bool flatQuad = params.w > 0.5;
    vec3 right = flatQuad ? vec3(1.0, 0.0, 0.0) : camRight;
    vec3 up = flatQuad ? vec3(0.0, 0.0, 1.0) : camUp;
    vec3 p = centerSize.xyz + (right * corner.x + up * corner.y) * centerSize.w * 0.5;
    gl_Position = viewProj * vec4(p, 1.0);
    uv = corner;
    vColour = colour;
    vMode = int(params.x + 0.5);
    vProgress = params.y;
    vSeed = params.z;
}"""

_SPRITE_FRAG = """#version 330 core
in vec2 uv;
in vec4 vColour;
flat in int vMode;
in float vProgress;
in float vSeed;
uniform float time;
out vec4 frag;
const float TAU = 6.2831853;
float hash(float n) { return fract(sin(n) * 43758.5453); }
float band(float r, float at, float w) { float d = (r - at) / w; return exp(-d * d); }
void main() {
    float r = length(uv);
    if (r > 1.0) discard;
    vec3 c = vColour.rgb;
    vec3 white = vec3(1.0);
    float p = vProgress;
    float ang = atan(uv.y, uv.x);
    float a = 0.0;
    vec3 col = c;
    if (vMode == 0) {                      // ORB: a lit sphere, fresnel rim
        float z = sqrt(max(0.0, 1.0 - r * r));
        float fres = pow(1.0 - z, 2.2);
        float core = exp(-r * r * 7.0);
        float flick = 0.85 + 0.15 * sin(time * 31.0 + vSeed * 17.0);
        float swirl = 0.5 + 0.5 * sin(ang * 3.0 + time * 9.0 + r * 8.0);
        col = mix(c, white, core * 0.85) * 1.25 + c * fres * 1.8 + c * swirl * 0.25 * z;
        a = (core * 1.1 + fres * 0.95 + 0.25 * z) * flick * smoothstep(1.0, 0.85, r);
    } else if (vMode == 1) {               // RING: an expanding shockwave
        float at = mix(0.12, 0.95, sqrt(p));
        float w = mix(0.16, 0.035, p);
        float ring = band(r, at, w);
        col = mix(c, white, ring * 0.45);
        a = ring * (1.0 - p) * 1.2 + exp(-r * r * 9.0) * (1.0 - p) * 0.25;
    } else if (vMode == 2) {               // RUNES: a turning rune circle
        float env = smoothstep(0.0, 0.12, p) * (1.0 - smoothstep(0.75, 1.0, p));
        float dir = hash(vSeed) > 0.5 ? 1.0 : -1.0;
        float t1 = ang + time * 1.4 * dir;
        float t2 = ang - time * 2.1 * dir;
        float rings = band(r, 0.93, 0.025) + band(r, 0.78, 0.018) + band(r, 0.45, 0.02);
        float cell = floor(fract(t1 / TAU) * 28.0);
        float glyph = step(0.35, hash(cell + vSeed * 13.0))
                    * step(0.25, fract(fract(t1 / TAU) * 28.0))
                    * smoothstep(0.80, 0.82, r) * smoothstep(0.91, 0.89, r);
        float spokes = exp(-pow(sin(t2 * 3.0) * r / 0.018, 2.0)) * step(0.45, r) * step(r, 0.78);
        float star = exp(-pow(abs(cos(t2 * 2.5)) * r / 0.02, 2.0)) * step(r, 0.45) * 0.6;
        float glow = exp(-r * r * 3.0) * 0.15;
        a = (rings + glyph * 0.9 + spokes * 0.8 + star + glow) * env;
        col = mix(c, white, rings * 0.35);
    } else if (vMode == 3) {               // MOTE: a soft spark
        a = exp(-r * r * 5.0);
        col = mix(c, white, exp(-r * r * 22.0));
    } else if (vMode == 4) {               // BUBBLE: a fresnel ward
        float z = sqrt(max(0.0, 1.0 - r * r));
        float fres = pow(1.0 - z, 3.0);
        vec2 q = uv * 9.0 + vec2(time * 0.6, -time * 0.45);
        float hexes = 0.5 + 0.5 * sin(q.x * 2.0) * sin(q.y * 1.73 + q.x);
        float pulse = 0.8 + 0.2 * sin(time * 3.0 + vSeed * 6.0);
        float ghost = vSeed > 0.25 ? 0.45 : 1.0;   // invisibility: a fainter shell
        a = (fres * 1.3 + 0.05 + hexes * fres * 0.35) * pulse * ghost * smoothstep(1.0, 0.95, r);
        col = mix(c, white, fres * 0.4);
    } else if (vMode == 5) {               // RAYS: a burst of light
        float env = smoothstep(0.0, 0.08, p) * (1.0 - p);
        float rays = pow(abs(sin(ang * 7.0 + vSeed * 6.0 + time * 0.7)), 24.0)
                   + pow(abs(sin(ang * 11.0 - time * 0.5 + vSeed)), 40.0) * 0.7;
        a = (rays * (1.0 - r) * 1.4 + exp(-r * r * 6.0)) * env;
        col = mix(c, white, exp(-r * r * 8.0) * 0.7);
    } else if (vMode == 6) {               // FLASH
        float env = (1.0 - p) * (1.0 - p);
        a = exp(-r * r * 4.0) * env * 1.3;
        col = mix(c, white, 0.55);
    } else if (vMode == 7) {               // SHARDS: an ice star
        float env = 1.0 - p;
        float star = pow(abs(cos(ang * 3.0 + vSeed * 6.0)), 60.0) * (1.0 - r) * 1.6
                   + pow(abs(cos(ang * 5.0 + vSeed * 3.0)), 90.0) * (1.0 - r);
        a = (star + band(r, 0.55 + 0.4 * p, 0.05) * 0.6) * env;
        col = mix(c, white, 0.45);
    } else {                               // ARC: a crackle of lightning
        float k = floor(time * 30.0 + vSeed * 7.0);
        float wob = sin(uv.x * 9.0 + hash(k) * 6.0) * 0.25 + sin(uv.x * 23.0 + hash(k + 1.0) * 6.0) * 0.1;
        float line = exp(-pow((uv.y - wob) / 0.06, 2.0)) * (1.0 - abs(uv.x));
        a = line * 1.6;
        col = mix(c, white, line * 0.7);
    }
    frag = vec4(col, clamp(a, 0.0, 1.0) * vColour.a);
}"""

_LENS_VERT = """#version 330 core
out vec2 uv;
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}"""

_LENS_FRAG = """#version 330 core
in vec2 uv;
uniform sampler2D scene;
uniform vec4 lens[8];        // xy centre (uv), z radius (uv height), w strength
uniform vec4 ring[8];        // x progress, yzw rim colour
uniform float shimmer[8];    // a ward's ripple through the glass (0: none)
uniform int count;
uniform float aspect;
uniform float time;
out vec4 frag;
void main() {
    vec2 offR = vec2(0.0), offG = vec2(0.0), offB = vec2(0.0);
    vec3 glow = vec3(0.0);
    for (int i = 0; i < 8; i++) {
        if (i >= count) break;
        vec2 c = lens[i].xy;
        float R = max(lens[i].z, 1e-4);
        float s = lens[i].w;
        vec2 d = uv - c;
        d.x *= aspect;
        float r = length(d) / R;
        if (r >= 1.0) continue;
        // Fisheye: the middle magnified, squeezed toward the rim.
        float k = s * (1.0 - r * r) * (1.0 - r * r);
        // A ward shimmers: slow ripples run round and through the glass.
        float ang = atan(d.y, d.x);
        k *= 1.0 + shimmer[i] * 0.18 * sin(r * 14.0 - time * 3.1 + sin(ang * 3.0 + time * 1.3));
        vec2 pull = -(d * k);
        pull += shimmer[i] * 0.004 * (1.0 - r) * R
              * vec2(sin(ang * 5.0 + time * 2.3 + r * 9.0), cos(ang * 4.0 - time * 1.9));
        // The shock ring refracts outward as it runs.
        float at = ring[i].x;
        float wave = exp(-pow((r - at) / 0.07, 2.0)) * s;
        vec2 dir = r > 1e-4 ? d / (r * R) : vec2(0.0);
        pull += dir * wave * 0.035;
        pull.x /= aspect;
        offR += pull * 1.06;
        offG += pull;
        offB += pull * 0.94;
        glow += ring[i].yzw * wave * 0.25;
    }
    frag = vec4(texture(scene, uv + offR).r, texture(scene, uv + offG).g,
                texture(scene, uv + offB).b, 1.0);
    frag.rgb += glow;
}"""

#: Effects are hidden by walls in front of them.
DEPTH_TEST = True
#: Instance floats per sprite: centre + size, colour, params.
_STRIDE = 12


class _State:
    ok = None
    prog = vao = quad = inst = 0
    lens_prog = lens_vao = 0
    fbo = tex = 0
    tex_size = (0, 0)
    loc = {}
    lens_loc = {}
    capacity = 0


_S = _State()


def _compile(gl, vert, frag):
    from OpenGL.GL import shaders
    return shaders.compileProgram(shaders.compileShader(vert, gl.GL_VERTEX_SHADER),
                                  shaders.compileShader(frag, gl.GL_FRAGMENT_SHADER),
                                  validate=False)


def _init(gl) -> bool:
    if _S.ok is not None:
        return _S.ok
    try:
        _S.prog = _compile(gl, _SPRITE_VERT, _SPRITE_FRAG)
        _S.loc = {n: gl.glGetUniformLocation(_S.prog, n)
                  for n in ("viewProj", "camRight", "camUp", "time")}
        _S.vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(_S.vao)
        corners = np.array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1], dtype=np.float32)
        _S.quad = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, _S.quad)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, corners.nbytes, corners, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        _S.inst = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, _S.inst)
        _S.capacity = 256
        gl.glBufferData(gl.GL_ARRAY_BUFFER, _S.capacity * _STRIDE * 4, None, gl.GL_STREAM_DRAW)
        for loc in (1, 2, 3):
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(loc, 4, gl.GL_FLOAT, gl.GL_FALSE, _STRIDE * 4,
                                     ctypes.c_void_p((loc - 1) * 16))
            gl.glVertexAttribDivisor(loc, 1)
        gl.glBindVertexArray(0)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

        _S.lens_prog = _compile(gl, _LENS_VERT, _LENS_FRAG)
        _S.lens_loc = {n: gl.glGetUniformLocation(_S.lens_prog, n)
                       for n in ("scene", "lens", "ring", "shimmer", "count", "aspect",
                                 "time")}
        _S.lens_vao = gl.glGenVertexArrays(1)
        _S.ok = True
    except Exception as exc:
        print(f"[MiniWind] magic effects unavailable: {exc}")
        _S.ok = False
    return _S.ok


def _camera_axes(view):
    """World-space right and up of the camera, from a glm view matrix."""
    right = (float(view[0][0]), float(view[1][0]), float(view[2][0]))
    up = (float(view[0][1]), float(view[1][1]), float(view[2][1]))
    return right, up


def draw_sprites(projection, view, sprites, now=None) -> int:
    """Draw *sprites* (``(n, 12)`` rows from :meth:`MagicFX.frame`); returns
    how many were drawn."""
    if sprites is None or not len(sprites):
        return 0
    import OpenGL.GL as gl
    import glm
    if not _init(gl):
        return 0
    try:
        data = np.ascontiguousarray(sprites, dtype=np.float32)
        n = len(data)
        prev_prog = gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM)
        blend = gl.glIsEnabled(gl.GL_BLEND)
        depth = gl.glIsEnabled(gl.GL_DEPTH_TEST)
        cull = gl.glIsEnabled(gl.GL_CULL_FACE)
        gl.glUseProgram(_S.prog)
        vp = projection * view
        gl.glUniformMatrix4fv(_S.loc["viewProj"], 1, gl.GL_FALSE, glm.value_ptr(vp))
        right, up = _camera_axes(view)
        gl.glUniform3f(_S.loc["camRight"], *right)
        gl.glUniform3f(_S.loc["camUp"], *up)
        gl.glUniform1f(_S.loc["time"], float((time.perf_counter() if now is None else now) % 1000.0))
        gl.glBindVertexArray(_S.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, _S.inst)
        if n > _S.capacity:
            _S.capacity = max(n, _S.capacity * 2)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, _S.capacity * _STRIDE * 4, None,
                            gl.GL_STREAM_DRAW)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, data.nbytes, data)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)       # additive light
        (gl.glEnable if DEPTH_TEST else gl.glDisable)(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDrawArraysInstanced(gl.GL_TRIANGLES, 0, 6, n)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glBindVertexArray(0)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glUseProgram(int(prev_prog))
        (gl.glEnable if blend else gl.glDisable)(gl.GL_BLEND)
        (gl.glEnable if depth else gl.glDisable)(gl.GL_DEPTH_TEST)
        (gl.glEnable if cull else gl.glDisable)(gl.GL_CULL_FACE)
        return n
    except Exception as exc:
        print(f"[MiniWind] magic sprites failed, turned off: {exc}")
        _S.ok = False
        return 0


def project_lenses(projection, view, lenses, width, height):
    """``[(cx, cy, radius, strength, progress, colour, shimmer)]`` in screen uv
    for the lenses in front of the camera (``(x, y, z, strength, radius_world,
    progress, colour, shimmer)`` each)."""
    import glm
    out = []
    if not lenses or width <= 0 or height <= 0:
        return out
    vp = projection * view
    right, _up = _camera_axes(view)
    aspect = width / float(height)
    for x, y, z, strength, radius, progress, colour, shimmer in lenses:
        if strength <= 1e-3:
            continue
        c = vp * glm.vec4(x, y, z, 1.0)
        if c.w <= 1e-4:
            continue
        e = vp * glm.vec4(x + right[0] * radius, y + right[1] * radius,
                          z + right[2] * radius, 1.0)
        if e.w <= 1e-4:
            continue
        cx, cy = c.x / c.w * 0.5 + 0.5, c.y / c.w * 0.5 + 0.5
        ex, ey = e.x / e.w * 0.5 + 0.5, e.y / e.w * 0.5 + 0.5
        r = math.hypot((ex - cx) * aspect, ey - cy)
        if r <= 1e-4 or cx < -r or cx > 1 + r or cy < -r or cy > 1 + r:
            continue
        out.append((cx, cy, min(r, 1.5), min(1.0, strength), progress, colour, shimmer))
    return out[:8]


def draw_lenses(projection, view, lenses) -> int:
    """The fisheye pass over the finished frame (see the module doc)."""
    if not lenses:
        return 0
    import OpenGL.GL as gl
    if not _init(gl):
        return 0
    try:
        x0, y0, w, h = (int(v) for v in gl.glGetIntegerv(gl.GL_VIEWPORT))
        screen = project_lenses(projection, view, lenses, w, h)
        if not screen:
            return 0
        prev_draw = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        prev_read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
        if _S.tex_size != (w, h):
            if _S.fbo:
                gl.glDeleteFramebuffers(1, [_S.fbo])
                gl.glDeleteTextures([_S.tex])
            _S.tex = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, _S.tex)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0, gl.GL_RGBA,
                            gl.GL_UNSIGNED_BYTE, None)
            for param, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                                 (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                                 (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                                 (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, param, value)
            _S.fbo = gl.glGenFramebuffers(1)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, _S.fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                      gl.GL_TEXTURE_2D, _S.tex, 0)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, prev_draw)
            _S.tex_size = (w, h)
        # Copy the frame (resolving any multisampling) into the texture.
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, prev_draw)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, _S.fbo)
        gl.glBlitFramebuffer(x0, y0, x0 + w, y0 + h, 0, 0, w, h,
                             gl.GL_COLOR_BUFFER_BIT, gl.GL_NEAREST)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, prev_draw)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, prev_read)

        prev_prog = gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM)
        depth = gl.glIsEnabled(gl.GL_DEPTH_TEST)
        blend = gl.glIsEnabled(gl.GL_BLEND)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(_S.lens_prog)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, _S.tex)
        loc = _S.lens_loc
        gl.glUniform1i(loc["scene"], 0)
        lens = np.zeros((8, 4), dtype=np.float32)
        ring = np.zeros((8, 4), dtype=np.float32)
        shimmer = np.zeros(8, dtype=np.float32)
        for i, (cx, cy, r, s, progress, colour, ripple) in enumerate(screen):
            lens[i] = (cx, cy, r, s)
            ring[i] = (progress, *colour)
            shimmer[i] = ripple
        gl.glUniform4fv(loc["lens"], 8, lens)
        gl.glUniform4fv(loc["ring"], 8, ring)
        gl.glUniform1fv(loc["shimmer"], 8, shimmer)
        gl.glUniform1f(loc["time"], float(time.perf_counter() % 1000.0))
        gl.glUniform1i(loc["count"], len(screen))
        gl.glUniform1f(loc["aspect"], w / float(h))
        gl.glBindVertexArray(_S.lens_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        gl.glUseProgram(int(prev_prog))
        (gl.glEnable if depth else gl.glDisable)(gl.GL_DEPTH_TEST)
        (gl.glEnable if blend else gl.glDisable)(gl.GL_BLEND)
        return len(screen)
    except Exception as exc:
        print(f"[MiniWind] magic lens failed, turned off: {exc}")
        _S.ok = False
        return 0
