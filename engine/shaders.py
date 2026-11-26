import os
import platform
import re
import sys



# ==============================================================================
# PLATFORM: which lighting shader variant this machine should run
# ------------------------------------------------------------------------------
# The ``*_arm`` variants trade light capacity and per-fragment precision for a
# smaller uniform footprint and less shader work. That is the right trade on
# low-power hardware and the wrong one everywhere else, so what this answers is
# "is this a low-power part?" — *not* "is this ARM?". The two are not the same
# question and never were: a Surface Pro X's SQ3 (a Snapdragon 8cx) wants the
# cheap shaders, while Apple Silicon and a Snapdragon X Elite have desktop-class
# GPUs and want the full ones, and all three are aarch64.
#
# The rule is therefore "ARM, minus the parts known to be fast". A new fast ARM
# part that is not yet listed gets the conservative treatment rather than a
# broken one, and anybody can override the guess outright in settings.ini.
#
# One implementation, used by both the renderer and the Settings window — they
# used to detect this separately and could disagree about the same machine.
# ==============================================================================

#: Substrings of a CPU's model name that mark it as *not* low-power, matched
#: case-insensitively. Snapdragon X Elite/Plus report as "Snapdragon(R) X Elite
#: - X1E..." / "X Plus - X1P..."; Oryon is their core. Ampere/Graviton/Neoverse
#: are server parts that turn up in CI and remote desktops.
_FAST_ARM_MARKERS = (
    'x elite', 'x1e', 'x plus', 'x1p', 'oryon',
    'ampere', 'graviton', 'neoverse',
)


def _arm_cpu_name():
    """The CPU's model name, as specifically as this OS will give it.

    Windows on ARM reports a useless generic string in ``PROCESSOR_IDENTIFIER``
    ("ARMv8 (64-bit) Family 8 Model 1..."), so the friendly name is read from
    the registry where the part is actually identified. Best-effort throughout:
    an empty string just means the caller falls back to the conservative guess.
    """
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            try:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            finally:
                winreg.CloseKey(key)
            if name:
                return str(name)
        except Exception:
            pass
        return os.environ.get('PROCESSOR_IDENTIFIER', '')

    if sys.platform.startswith('linux'):
        try:
            with open('/proc/cpuinfo', 'r') as handle:
                fields = []
                for line in handle:
                    label = line.split(':', 1)
                    if len(label) == 2 and label[0].strip().lower() in (
                            'model name', 'hardware', 'cpu part', 'cpu implementer'):
                        fields.append(label[1].strip())
            if fields:
                return ' '.join(fields)
        except OSError:
            pass

    try:
        return platform.processor() or ''
    except Exception:
        return ''


def detect_low_power_arm():
    """``(is_low_power, reason)`` for this machine.

    ``reason`` is a short human-readable phrase the Settings window shows.
    """
    override = os.environ.get('FIO_ARM_MODE', '').strip().lower()
    if override in ('1', 'true', 'yes', 'on'):
        return True, "forced by FIO_ARM_MODE"
    if override in ('0', 'false', 'no', 'off'):
        return False, "disabled by FIO_ARM_MODE"

    machine = platform.machine().lower()
    is_arm_cpu = 'arm' in machine or 'aarch' in machine
    if not is_arm_cpu and sys.platform == 'win32':
        # Windows lies about the architecture to an emulated x64 process.
        is_arm_cpu = (
            os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() == 'ARM64'
            or os.environ.get('PROCESSOR_ARCHITEW6432', '').upper() == 'ARM64'
        )

    if not is_arm_cpu:
        return False, "x64/x86 processor detected"

    if sys.platform == 'darwin':
        return False, "Apple Silicon detected - desktop-class GPU"

    name = _arm_cpu_name().lower()
    for marker in _FAST_ARM_MARKERS:
        if marker in name:
            return False, "high-performance ARM detected - desktop-class GPU"

    return True, "low-power ARM detected"


# ==============================================================================
# SHADOW MAPPING (depth cube-map, omnidirectional point-light shadows)
# ------------------------------------------------------------------------------
# Shared GLSL injected into every lighting fragment shader that *receives*
# shadows.  A shadow-casting point light renders scene depth into a cube-map
# (linear distance / far_plane stored per texel); receivers reconstruct the
# distance and compare it against the fragment's distance to the light.
#
# NOTE: In GLSL 3.30 a sampler array may only be indexed with a *constant*
# expression, so the cube lookup uses an explicit if-ladder instead of
# dynamic indexing (which is only legal from GLSL 4.00 onwards).  Keeping the
# indices constant makes the shaders portable across desktop GL 3.3 drivers.
# ==============================================================================
MAX_SHADOW_LIGHTS = 8

# A shadow-casting Light's default filter (engine.constants).
from engine.constants import SHADOW_BIAS_DEFAULT, SHADOW_SOFTNESS_DEFAULT  # noqa: E402

# ==============================================================================
# DYNAMIC LIGHT CAPACITY
# ------------------------------------------------------------------------------
# How many point lights a lighting shader can hold. This is the *only* place the
# number is written down: the shader sources below are built from it and
# `ForwardRenderer.MAX_LIGHTS` reads it, because the renderer's budget and the
# shader's array have to be the same number.
#
# They used not to be. The renderer uploaded up to 32 lights and set
# `active_lights` to that count, while `lit.frag` and `textured.frag` declared
# `lights[8]` and looped to `active_lights` with no bound — so any scene with
# more than eight lights had the shader read past the end of the array, which is
# undefined behaviour, and 24 of the "32" lights never worked in the first
# place. Every loop over `active_lights` is now clamped to its own array as
# well, so a mismatch can never be more than lights quietly not contributing.
MAX_LIGHTS = 128

# The Android/GLES player keeps the previous 64. Its shared light block packs
# each light into three vec4s, and some Android GLES translators count block
# members against the default-uniform budget, whose ES 3.0 minimum is 224
# vectors: 64 lights (192 vectors) fit, 128 (384) would not link there.
MAX_LIGHTS_PLAYER = 64

# The ARM/low-power variants keep a smaller array deliberately. Uniform storage
# is the scarce resource on those GPUs, and the per-fragment loop runs
# `active_lights` times either way, so a lower cap costs a dense scene some of
# its lights and costs an ordinary one nothing at all.
MAX_LIGHTS_ARM = 16

# Water and terrain light themselves from the nearest lights rather than the
# whole set; their shaders are sized for that on purpose and the renderer clamps
# `active_lights` to match (see ForwardRenderer._shader_light_cap).
MAX_LIGHTS_WATER = 8
MAX_LIGHTS_TERRAIN = 18
MAX_TERRAIN_STAMPS = 32
MAX_TERRAIN_STAMP_TEXTURES = 16

# GL 3.3 UBO binding used by every lighting shader.  The binding is assigned
# from Python with glUniformBlockBinding rather than using a GLSL 4.2-style
# explicit binding qualifier, keeping this portable to the engine's GL 3.3
# target.
LIGHT_UBO_BINDING = 2

_LIGHT_DECL_RE = re.compile(
    r"struct\s+Light\s*\{.*?\};\s*uniform\s+Light\s+lights\s*\[\s*(\d+)\s*\]\s*;",
    re.DOTALL,
)


#: A light whose source has a size is not a point. A point light is at its
#: brightest on whatever is nearest it -- a spot on the wall behind a neon
#: tube -- where a tube lights that wall evenly and faintly along its length.
#: So such a light fades in over its source's half-size: what is right next
#: to it gets little, what is a tube-length away gets all of it. Size 0 (every
#: Light, Effect and decal) is a point, exactly as before.
LIGHT_SOURCE_SIZE_GLSL = """
float fioSourceFade(float size, highp vec3 toLight) {
    if (size <= 0.0) return 1.0;
    return smoothstep(0.0, size, length(toLight));
}
"""


#: The texture unit of the shared light-cookie array (engine.light_cookies).
#: Above every unit a fragment stage already uses (0..15: diffuse, terrain,
#: shadow cube-maps, heights, paint, geometry transforms, panorama); GL 3.3
#: guarantees 48 combined units and GLES 3.0 32, and the fragment-stage
#: sampler count stays within 16 because only one more sampler is added.
COOKIE_TEXTURE_UNIT = 16

#: How many mip levels blurrier a cookie is at the light's radius than at its
#: centre. Linear in distance / radius: the near image is sharp, the far one
#: soft but still recognisable (a level is half the resolution).
COOKIE_SOFTEN_LODS = 3.0

#: Projected-image lighting (engine.light_cookies). ``fioLightColor`` stands
#: in for a light's colour in every light loop. For an ordinary light --
#: ``indices.z`` 0, the dynamically uniform branch every fragment of the draw
#: takes together -- it returns the colour itself and samples nothing.
#:
#: A cookie light reads its image along the direction from the light's centre
#: to the fragment, with an octahedral map (centre = down, corners = up), so
#: the image stretches with distance as a projection does. The level of
#: detail is chosen explicitly -- the light loop is non-uniform control flow,
#: where implicit derivatives are undefined, and the octahedral fold would
#: give a seam if they were taken there: the pixel's world size (taken once
#: at the top of main, in uniform flow) over the texel's world size at that
#: distance picks the level that does not alias, and a distance bias of up to
#: COOKIE_SOFTEN_LODS levels softens it toward the radius. One textureLod:
#: the blur is the hardware's trilinear filter over the mip chain.
LIGHT_COOKIE_GLSL = """
uniform mediump sampler2DArray fioCookies;
highp float fioCookiePixel;
vec2 fioOctahedral(highp vec3 d) {
    d /= (abs(d.x) + abs(d.y) + abs(d.z));
    vec2 p = d.xz;
    if (d.y > 0.0) {
        vec2 s = vec2(p.x >= 0.0 ? 1.0 : -1.0, p.y >= 0.0 ? 1.0 : -1.0);
        p = (1.0 - abs(p.yx)) * s;
    }
    return p * 0.5 + 0.5;
}
vec3 fioLightColor(int i, highp vec3 fragPos) {
    int layer = lights[i].indices.z;
    if (layer <= 0) return lights[i].color.xyz;
    highp vec3 fromLight = fragPos - lights[i].position.xyz;
    highp float dist = max(length(fromLight), 0.001);
    vec2 uv = fioOctahedral(fromLight / dist);
    // An octahedral texel spans about sqrt(4 pi) / size radians.
    highp float texel = dist * 3.5449 / float(textureSize(fioCookies, 0).x);
    float lod = log2(max(fioCookiePixel / texel, 1.0))
              + """ + repr(COOKIE_SOFTEN_LODS) + """ * clamp(dist / max(lights[i].params.y, 1.0), 0.0, 1.0);
    return lights[i].color.xyz * textureLod(fioCookies, vec3(uv, float(layer - 1)), lod).rgb;
}
// A cookie light's own shadow darkens its image but never erases it: its
// visibility is max(1 - shadow, floor), the floor being the light's
// cookie_shadow_floor (params.w). Only this light's shadow is involved; an
// ordinary light's shadow is returned unchanged.
float fioCookieShadow(int i, float shadow) {
    if (lights[i].indices.z <= 0) return shadow;
    return min(shadow, 1.0 - clamp(lights[i].params.w, 0.0, 1.0));
}
"""

_COOKIE_MARKER = "\n// <fio light cookies>\n"
_MAIN_RE = re.compile(r"void\s+main\s*\(\s*(?:void)?\s*\)\s*\{")


#: The cookie shadow floor a Light starts with (``cookie_shadow_floor``).
COOKIE_SHADOW_FLOOR = 0.15

_SHADOW_CALL_RE = re.compile(r"calcPointShadow\(\s*lights\[([^]]+)\]\.shadowIndex\b")


def _floor_cookie_shadows(source):
    """Wrap each light loop's ``calcPointShadow(lights[i].shadowIndex, ...)``
    in ``fioCookieShadow(i, ...)`` (LIGHT_COOKIE_GLSL)."""
    out, pos = [], 0
    for match in _SHADOW_CALL_RE.finditer(source):
        depth, end = 0, match.start() + len("calcPointShadow")
        for end in range(end, len(source)):
            if source[end] == "(":
                depth += 1
            elif source[end] == ")":
                depth -= 1
                if not depth:
                    break
        out.append(source[pos:match.start()])
        out.append("fioCookieShadow(" + match.group(1) + ", "
                   + source[match.start():end + 1] + ")")
        pos = end + 1
    out.append(source[pos:])
    return "".join(out)


def light_ubo_source(source):
    """Rewrite a legacy Light[] fragment shader to the shared std140 UBO.

    The original shader interface is intentionally accepted here so the source
    files remain readable and the same transform applies to loose shaders,
    fallback strings, ARM variants and instanced variants alike.
    """
    if not source or 'uniform Light lights[' not in source:
        return source

    match = _LIGHT_DECL_RE.search(source)
    if match is None:
        return source

    count = int(match.group(1))
    # The name the shader gives the fragment's world position: every light
    # loop takes ``lights[i].position - <that>``. FragPos here; the Android
    # player's adaptation of these shaders renames it first.
    where = re.search(r"lights\[[^]]+\]\.position\s*-\s*([A-Za-z_]\w*)", source)
    fragment_position = where.group(1) if where else "FragPos"
    block = (
        "struct Light {\n"
        "    highp vec4 position;\n"
        "    vec4 color;\n"
        "    vec4 params;       // x=intensity, y=radius, z=source size, w=cookie shadow floor\n"
        "    ivec4 indices;     // x=shadow index, y=terrain shadow only (MiniWind),\n"
        "                       // z=cookie layer + 1 (0: none),\n"
        "                       // w=terrain shadow strength x1000 (MiniWind)\n"
        "};\n"
        "layout(std140) uniform FioLightBlock {\n"
        f"    Light lights[{count}];\n"
        "};\n"
        + LIGHT_SOURCE_SIZE_GLSL
        + _COOKIE_MARKER
    )
    result = _LIGHT_DECL_RE.sub(lambda _m: block, source, count=1)

    result = re.sub(r"lights\[([^]]+)\]\.position\b", r"lights[\1].position.xyz", result)
    # A light's colour comes through its cookie (identity without one). The
    # helper is spliced in after these rewrites, so its own reads stay as
    # written; it needs the pixel footprint from the top of main().
    main = _MAIN_RE.search(result)
    if main is not None:
        result = _floor_cookie_shadows(result)
        result = re.sub(r"lights\[([^]]+)\]\.color\b",
                        r"fioLightColor(\1, " + fragment_position + ")", result)
        result = (result[:main.end()]
                  + "\n    fioCookiePixel = max(length(dFdx(" + fragment_position + ")), "
                  "length(dFdy(" + fragment_position + ")));"
                  + result[main.end():])
    else:
        result = re.sub(r"lights\[([^]]+)\]\.color\b", r"lights[\1].color.xyz", result)
    # A light with a source size (an emissive brush: a tube, not a point)
    # fades in over that distance. Every light loop takes the fragment's
    # offset from the light as ``lights[i].position - FragPos``.
    result = re.sub(
        r"lights\[([^]]+)\]\.intensity\b",
        r"(lights[\1].params.x * fioSourceFade("
        r"lights[\1].params.z, lights[\1].position.xyz - " + fragment_position + "))",
        result)
    result = re.sub(r"lights\[([^]]+)\]\.radius\b", r"lights[\1].params.y", result)
    result = re.sub(
        r"lights\[([^]]+)\]\.terrainShadowStrength\b",
        r"(float(lights[\1].indices.w) * 0.001)", result,
    )
    result = re.sub(
        r"lights\[([^]]+)\]\.terrainShadowOnly\b",
        r"lights[\1].indices.y", result,
    )
    result = re.sub(
        r"lights\[([^]]+)\]\.shadowIndex\b",
        r"int(lights[\1].indices.x)",
        result,
    )
    return result.replace(_COOKIE_MARKER, LIGHT_COOKIE_GLSL if main is not None else "")

SHADOW_GLSL = """
#define MAX_SHADOW_LIGHTS """ + str(MAX_SHADOW_LIGHTS) + """
uniform samplerCube shadowMaps[""" + str(MAX_SHADOW_LIGHTS) + """];

highp float _sampleShadowCube(int idx, highp vec3 dir) {
    if (idx == 0) return texture(shadowMaps[0], dir).r;
    else if (idx == 1) return texture(shadowMaps[1], dir).r;
    else if (idx == 2) return texture(shadowMaps[2], dir).r;
    else if (idx == 3) return texture(shadowMaps[3], dir).r;
    else if (idx == 4) return texture(shadowMaps[4], dir).r;
    else if (idx == 5) return texture(shadowMaps[5], dir).r;
    else if (idx == 6) return texture(shadowMaps[6], dir).r;
    return texture(shadowMaps[7], dir).r;
}

// The cube-map's face width in texels (every face of a cube is square).
highp float _shadowCubeTexels(int idx) {
    if (idx == 0) return float(textureSize(shadowMaps[0], 0).x);
    else if (idx == 1) return float(textureSize(shadowMaps[1], 0).x);
    else if (idx == 2) return float(textureSize(shadowMaps[2], 0).x);
    else if (idx == 3) return float(textureSize(shadowMaps[3], 0).x);
    else if (idx == 4) return float(textureSize(shadowMaps[4], 0).x);
    else if (idx == 5) return float(textureSize(shadowMaps[5], 0).x);
    else if (idx == 6) return float(textureSize(shadowMaps[6], 0).x);
    return float(textureSize(shadowMaps[7], 0).x);
}

// Each shadow slot's filter, from the Light that owns it: x = softness (the
// PCF disk radius in cube-map texels), y = bias multiplier. 0 stands for the
// default, so a program nobody has given values to still filters sensibly.
uniform vec2 uShadowFilter[MAX_SHADOW_LIGHTS];
vec2 _shadowFilter(int idx) {
    vec2 f = uShadowFilter[idx];
    return vec2(f.x > 0.0 ? f.x : """ + repr(SHADOW_SOFTNESS_DEFAULT) + """,
                f.y > 0.0 ? f.y : """ + repr(SHADOW_BIAS_DEFAULT) + """);
}

// idx          : which cube-map (0..7), or <0 for a non-shadow-casting light
// fragToLight  : lightPos - fragmentWorldPos (world space)
// farPlane     : the light radius used when the cube-map was rendered
// ndotl        : diffuse term, used to scale the slope bias
// Returns 0 (fully lit) .. 1 (fully shadowed).  highp throughout because the
// world coordinates can be in the thousands and mediump would band badly.
float calcPointShadow(int idx, highp vec3 fragToLight, highp float farPlane, float ndotl) {
    if (idx < 0) return 0.0;
    highp float currentDepth = length(fragToLight);
    if (currentDepth >= farPlane) return 0.0;   // beyond the light's reach
    // The cube-map was rendered from the light looking outward, so the lookup
    // direction runs light -> fragment, i.e. the negation of fragToLight.
    highp vec3 lookDir = -fragToLight;
    // One cube-map texel at this distance, in world units: a face spans 90
    // degrees -- 2 units across at unit distance -- over its width in texels.
    // The filter and the bias are measured in texels, so a shadow is as sharp
    // as its map resolves and keeps thin casters (railings, grating) solid.
    // They used to be fractions of the light's radius -- the same blur for a
    // 2048-unit light at any resolution, ~20 world units wide, which smeared
    // a catwalk's bars into a faint grey and dropped thin ones altogether.
    highp float texel = currentDepth * 2.0 / _shadowCubeTexels(idx);
    vec2 shadowFilter = _shadowFilter(idx);
    highp float diskRadius = texel * shadowFilter.x;
    // Bias covers the depth spread across one texel and the PCF disk on a
    // surface sloped away from the light (the tangent of its angle, capped),
    // so lit surfaces don't self-shadow ("shadow acne"), scaled by the
    // light's bias multiplier.
    highp float slope = clamp(sqrt(max(1.0 - ndotl * ndotl, 0.0)) / max(ndotl, 0.1),
                              0.0, 10.0);
    highp float bias = (diskRadius + (texel + diskRadius) * (1.0 + slope)) * shadowFilter.y;
    vec3 sampleDirs[20] = vec3[](
        vec3( 1, 1, 1), vec3( 1,-1, 1), vec3(-1,-1, 1), vec3(-1, 1, 1),
        vec3( 1, 1,-1), vec3( 1,-1,-1), vec3(-1,-1,-1), vec3(-1, 1,-1),
        vec3( 1, 1, 0), vec3( 1,-1, 0), vec3(-1,-1, 0), vec3(-1, 1, 0),
        vec3( 1, 0, 1), vec3(-1, 0, 1), vec3( 1, 0,-1), vec3(-1, 0,-1),
        vec3( 0, 1, 1), vec3( 0,-1, 1), vec3( 0,-1,-1), vec3( 0, 1,-1)
    );
    float shadow = 0.0;
    for (int s = 0; s < 20; ++s) {
        highp float closest = _sampleShadowCube(idx, lookDir + sampleDirs[s] * diskRadius) * farPlane;
        if (currentDepth - bias > closest) shadow += 1.0;
    }
    return shadow / 20.0;
}
"""
# ==============================================================================
# DISTANCE FOG + GLOBAL AMBIENT
# ------------------------------------------------------------------------------
# Shared GLSL injected into every fragment shader that draws world geometry.
#
# Far-plane fog. The camera's far plane is adjustable (engine.view_distance), and
# a far plane on its own pops geometry out of existence at a hard edge. So every
# surface fades toward `uFogColor` as it recedes, and the CPU side guarantees
# `uFogEnd` lands strictly before the clip -- by default at 92% of the view
# distance -- so a fragment is already fully fogged by the time the depth test
# would have discarded it. The frame is cleared to the same colour, so what the
# fog dissolves into and what lies past the far plane are the same pixel value
# and the boundary is not visible at all.
#
# Distance is radial from the eye (`length(FragPos - uFogCamPos)`), not
# view-space depth: the fog wall is then a sphere concentric with the cull
# sphere the broad phase already uses, so a surface does not lighten or darken
# just because the camera turned to put it off-axis.
#
# `uFogDensity` > 0 layers an exponential-squared curve on top of the linear
# ramp (taking whichever is thicker), which deepens the near half of the band
# without moving the opaque point -- the clip stays hidden at any density.
#
# Global ambient. `uAmbient` is a flat omnidirectional term added to every lit
# surface: the `ambient` console command, i.e. a level-wide Light entity that
# does not exist in the world. It is *added* to each shader's own baked ambient
# constant rather than replacing it, so the default of black leaves every
# existing map rendering exactly as before.
#
# Both are declared in one chunk so a shader opts into the pair with a single
# splice, and both are inert at their defaults (uFogEnabled 0, uAmbient black).
# ==============================================================================
FOG_GLSL = """
uniform int   uFogEnabled;
uniform vec3  uFogColor;
uniform float uFogStart;
uniform float uFogEnd;
uniform float uFogDensity;
uniform highp vec3 uFogCamPos;
uniform vec3  uAmbient;

// 0 at uFogStart, 1 at uFogEnd and beyond. Returns 0 outright when fog is off
// so the branch costs a uniform read and nothing else.
float fogFactor(highp vec3 fragPos) {
    if (uFogEnabled == 0) return 0.0;
    highp float d = length(fragPos - uFogCamPos);
    float band = max(uFogEnd - uFogStart, 1e-4);
    float f = clamp((d - uFogStart) / band, 0.0, 1.0);
    if (uFogDensity > 0.0) {
        float e = uFogDensity * max(d - uFogStart, 0.0);
        f = max(f, clamp(1.0 - exp(-e * e), 0.0, 1.0));
    }
    return f;
}

vec3 applyFog(vec3 color, highp vec3 fragPos) {
    return mix(color, uFogColor, fogFactor(fragPos));
}
"""

# ==============================================================================
# DEFAULT SHADER SOURCES
# These are the fallback strings used if the .vert/.frag files are missing from
# disk (e.g. in a packaged build that doesn't include loose shader files).
# Keep these in sync with the files under assets/shaders/.
# ==============================================================================
#: Screen-space reflections fade out with distance from the camera: full
#: strength out to REFLECTION_FADE_START world units, none from
#: REFLECTION_FADE_END -- where no ray is marched at all. A far reflection
#: is a few pixels, each a full ray march; nobody can see it.
REFLECTION_FADE_START = 1024.0
REFLECTION_FADE_END = 1536.0

#: Screen-space reflection, shared by the water and wet decals. The host
#: shader declares ``sceneDepth``, ``sceneColor`` (copies of the frame so
#: far), ``projection`` and ``invProjection``.
SSR_GLSL = """
// 1 near the camera, 0 from REFLECTION_FADE_END on (see engine/shaders.py):
// a reflection is not traced where this is 0.
float reflectionFade(highp vec3 viewPos) {
    return 1.0 - smoothstep(""" + repr(REFLECTION_FADE_START) + """, """ + \
    repr(REFLECTION_FADE_END) + """, length(viewPos));
}
highp vec3 viewPosFromDepth(highp vec2 uv, highp float depth) {
    highp vec4 p = invProjection * vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    return p.xyz / p.w;
}

// Screen-space reflection: march the reflected ray through the copied depth
// buffer for the surface it hits. True with the hit's uv in the frame copy,
// how far along the ray it lies (view units) and a confidence; false for a
// miss. 10 linear steps with a growing stride, then a short binary
// refinement.
bool marchReflection(highp vec3 originView, highp vec3 dirView,
                     highp float firstStride, out highp vec2 hitUV,
                     out highp float hitS, out float hitFade) {
    hitUV = vec2(0.0);
    hitS = 0.0;
    hitFade = 0.0;
    // The ray's clip-space position is affine in the distance travelled
    // along it, so a step is a multiply-add, not a matrix multiply: the same
    // points as stepping the view-space position and projecting each.
    highp vec4 clipOrigin = projection * vec4(originView, 1.0);
    highp vec4 clipDir = projection * vec4(dirView, 0.0);
    highp float stride = firstStride;
    highp float s = 0.0;
    highp float prevS = 0.0;
    for (int i = 0; i < 10; i++) {
        prevS = s;
        s += stride;
        stride *= 1.22;
        highp float pz = originView.z + dirView.z * s;
        if (pz > -0.5) break;
        highp vec4 c = clipOrigin + clipDir * s;
        highp vec2 uv = c.xy / c.w * 0.5 + 0.5;
        if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) break;
        // textureLod: no implicit derivatives inside the loop.
        highp float d = textureLod(sceneDepth, uv, 0.0).r;
        if (d >= 0.99999) continue;
        highp float sceneZ = viewPosFromDepth(uv, d).z;
        highp float gap = sceneZ - pz;
        // Only a ray that has just gone behind a surface hits it. Without a
        // cap on how far behind, a ray passing behind a thin object (a box
        // standing in the water) counted as hitting it and smeared a long
        // streak of it across the water.
        highp float thickness = clamp(stride * 1.5, 2.0, 48.0);
        if (gap > 0.0 && gap < thickness) {
            highp float lo = prevS;
            highp float hi = s;
            for (int j = 0; j < 5; j++) {
                highp float mid = (lo + hi) * 0.5;
                highp vec4 mc = clipOrigin + clipDir * mid;
                highp vec2 muv = mc.xy / mc.w * 0.5 + 0.5;
                highp float mz = viewPosFromDepth(muv, textureLod(sceneDepth, muv, 0.0).r).z;
                if (mz > originView.z + dirView.z * mid) hi = mid; else lo = mid;
            }
            highp vec4 hc = clipOrigin + clipDir * hi;
            highp vec2 huv = hc.xy / hc.w * 0.5 + 0.5;
            highp float hz = viewPosFromDepth(huv, textureLod(sceneDepth, huv, 0.0).r).z;
            if (hz - (originView.z + dirView.z * hi) > thickness) return false;
            vec2 edge = smoothstep(vec2(0.0), vec2(0.08), huv)
                      * smoothstep(vec2(0.0), vec2(0.08), vec2(1.0) - huv);
            hitUV = huv;
            hitS = hi;
            hitFade = edge.x * edge.y * (1.0 - smoothstep(7.0, 10.0, float(i)));
            return true;
        }
    }
    return false;
}

// The scene colour the reflected ray hits (rgb), sharp, and a confidence
// (a); 0 for a miss.
vec4 traceReflectionStride(highp vec3 originView, highp vec3 dirView,
                           highp float firstStride) {
    highp vec2 uv;
    highp float s;
    float fade;
    if (!marchReflection(originView, dirView, firstStride, uv, s, fade))
        return vec4(0.0);
    return vec4(textureLod(sceneColor, uv, 0.0).rgb, fade);
}

// The water's march: its first stride grows with distance. A decal that
// must reach a few hundred units starts with a longer one.
vec4 traceReflection(highp vec3 originView, highp vec3 dirView) {
    return traceReflectionStride(originView, dirView, max(2.0, -originView.z * 0.02));
}
"""

# The four Gerstner waves water.vert lifts the surface by would line up in a
# regular lattice (every crest repeating on a grid, with its foam), plain to
# see wherever the surface's grid is fine enough to draw them. Each wave's
# phase drifts and its height swells and falls across the water instead,
# smoothly, over hundreds of units -- the same everywhere it is used
# (water.vert, and the waterfall's tongue, which lies on that surface).
WAVE_VARIATION_GLSL = """
highp float waveHash(highp vec2 p) {
    highp vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
highp float waveNoise(highp vec2 p) {
    highp vec2 i = floor(p);
    highp vec2 f = fract(p);
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(waveHash(i), waveHash(i + vec2(1.0, 0.0)), u.x),
               mix(waveHash(i + vec2(0.0, 1.0)), waveHash(i + vec2(1.0, 1.0)), u.x), u.y);
}
// Wave number w at p (in the flowing surface's frame): (phase offset,
// height scale).
vec2 waveVariation(highp vec2 p, float w) {
    highp vec2 q = p * 0.0019 + vec2(w * 7.31, w * 3.17);
    float phase = (waveNoise(q) - 0.5) * 7.0 + (waveNoise(q * 2.3 + 11.0) - 0.5) * 3.0;
    float scale = 0.45 + 1.1 * waveNoise(p * 0.0013 + vec2(w * 5.7 + 2.0, 9.1 - w));
    return vec2(phase, scale);
}
"""


#: The sky panorama's equirectangular lookup, shared by the sky pass
#: (``void_background.frag``) and the water that reflects it, so a reflection
#: samples the very texel the sky shows in that direction.
PANORAMA_GLSL = """
const float PANORAMA_PI = 3.14159265358979323846;
// Texture coordinates of the panorama in the unit world direction *dir*.
highp vec2 panoramaUV(highp vec3 dir) {
    return vec2(atan(dir.x, -dir.z) / (2.0 * PANORAMA_PI) + 0.5,
                0.5 - asin(clamp(dir.y, -1.0, 1.0)) / PANORAMA_PI);
}
"""


DEFAULT_SHADERS = {
    'simple.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}""",
    'simple.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
uniform vec3 color;
uniform float alpha;
void main() {
    FragColor = vec4(color, alpha);
}""",

    'lit.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
out vec3 FragPos;         // implicitly highp
out mediump vec3 Normal;  // explicit mediump to match frag default
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalize(normalMatrix * aNormal);
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'lit.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
in highp vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
uniform vec3 emissive_factor;
struct Light { highp vec3 position; vec3 color; float intensity; highp float radius; int shadowIndex; };
uniform Light lights[""" + str(MAX_LIGHTS) + """];
uniform int active_lights;""" + SHADOW_GLSL + FOG_GLSL + """
void main() {
    vec3 norm = normalize(Normal);
    vec3 result = (vec3(0.1) + uAmbient) * object_color;
    for(int i = 0; i < active_lights && i < """ + str(MAX_LIGHTS) + """; i++) {
        highp vec3  toLight  = lights[i].position - FragPos;
        highp float distSq   = dot(toLight, toLight);
        highp float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            highp float dist = sqrt(distSq);
            vec3  lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att  = 1.0 - (dist / lights[i].radius);
            att = att * att;
            float shadow = calcPointShadow(lights[i].shadowIndex, toLight, lights[i].radius, diff);
            result += (1.0 - shadow) * (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    result += emissive_factor;
    FragColor = vec4(applyFog(result, FragPos), alpha);
}""",

    'textured.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out mediump vec3 Normal;
out vec2 TexCoords;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform vec2 tex_scale;   // per-face stretch / tiling factor
uniform float tex_angle;  // per-face free rotation in radians
uniform vec2 tex_shift;   // per-face UV offset (in texture repeats)
uniform mat3 normalMatrix;

void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalize(normalMatrix * aNormal);
    // Surface-inspector transform: rotate the base 0..1 face UVs about their
    // centre, then apply stretch and shift (Radiant-style free controls).
    vec2 uv = aTexCoords - vec2(0.5);
    float s = sin(tex_angle);
    float c = cos(tex_angle);
    uv = vec2(uv.x * c - uv.y * s, uv.x * s + uv.y * c);
    TexCoords = (uv + vec2(0.5)) * tex_scale + tex_shift;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'textured.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in vec3 Normal;
in highp vec2 TexCoords;

uniform sampler2D texture_diffuse;
uniform vec4 model_tint;
uniform vec3 emissive_factor;
struct Light { highp vec3 position; vec3 color; float intensity; highp float radius; int shadowIndex; };
uniform Light lights[""" + str(MAX_LIGHTS) + """];
uniform int active_lights;""" + SHADOW_GLSL + FOG_GLSL + """
void main() {
    vec4 texColor = texture(texture_diffuse, TexCoords);
    if(texColor.a < 0.1) discard;
    // A model's tint; all zeros (the default) leaves the texture as it is.
    texColor.rgb *= mix(vec3(1.0), model_tint.rgb, model_tint.a);

    vec3 norm = normalize(Normal);
    vec3 result = (vec3(0.1) + uAmbient) * texColor.rgb;

    for(int i = 0; i < active_lights && i < """ + str(MAX_LIGHTS) + """; i++) {
        highp vec3  toLight  = lights[i].position - FragPos;
        highp float distSq   = dot(toLight, toLight);
        highp float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            highp float dist = sqrt(distSq);
            vec3  lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att  = 1.0 - (dist / lights[i].radius);
            att = att * att;
            float shadow = calcPointShadow(lights[i].shadowIndex, toLight, lights[i].radius, diff);
            result += (1.0 - shadow) * (diff * lights[i].color * lights[i].intensity * att) * texColor.rgb;
        }
    }
    result += emissive_factor;
    FragColor = vec4(applyFog(result, FragPos), texColor.a);
}""",

    'sprite.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec2 aPos;
out vec2 TexCoords;
out vec3 FragPos;
uniform mat4 projection;
uniform mat4 view;
uniform vec3 sprite_pos_world;
uniform vec2 sprite_size;
uniform bool use_fixed_facing;
layout (location = 3) in float sprite_fixed_yaw;
// (heading, on) for a top-down head actor. Unset, a generic attribute reads
// (0, 0): no spin, so every other billboard and draw path is unaffected.
layout (location = 6) in vec2 sprite_spin;
void main() {
    TexCoords = aPos + 0.5;
    vec3 cameraRight = vec3(view[0][0], view[1][0], view[2][0]);
    vec3 cameraUp = vec3(view[0][1], view[1][1], view[2][1]);
    if (use_fixed_facing && sprite_fixed_yaw > -9999.0) {
        float yaw = sprite_fixed_yaw;
        cameraRight = vec3(cos(yaw), 0.0, -sin(yaw));
        cameraUp = vec3(0.0, 1.0, 0.0);
    } else if (sprite_spin.y > 0.5) {
        // Head art faces down its image: seen from above, turn the billboard
        // in the screen plane until the image's bottom points along the
        // actor's heading (forward = (sin a, 0, cos a)), as the player's own
        // head does. Eased in with how far the camera looks down, so a first
        // person view keeps its heads upright.
        vec3 spinView = vec3(view[0][2], view[1][2], view[2][2]);
        float spinAmount = smoothstep(0.35, 0.8, spinView.y);
        vec3 heading = vec3(sin(sprite_spin.x), 0.0, cos(sprite_spin.x));
        vec2 f = vec2(dot(heading, cameraRight), dot(heading, cameraUp));
        if (spinAmount > 0.0 && dot(f, f) > 1e-6) {
            f = normalize(f);
            // The turn that takes the image's down (0, -1) onto f.
            float turn = atan(f.x, -f.y) * spinAmount;
            vec3 right = cos(turn) * cameraRight + sin(turn) * cameraUp;
            vec3 up = -sin(turn) * cameraRight + cos(turn) * cameraUp;
            cameraRight = right;
            cameraUp = up;
        }
    }
    vec3 worldPos = sprite_pos_world
                  + cameraRight * aPos.x * sprite_size.x
                  + cameraUp * aPos.y * sprite_size.y;
    // Seen from above, a camera-facing billboard lies flat where it is, at
    // its own size: it is never pulled toward the camera, which would
    // magnify it (a dragon's head came out far larger than its size).
    FragPos = worldPos;
    gl_Position = projection * view * vec4(worldPos, 1.0);
}""",
    'sprite.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
in highp vec2 TexCoords;
uniform sampler2D sprite_texture;
in highp vec3 FragPos;""" + FOG_GLSL + """
void main() {
    vec4 texColor = texture(sprite_texture, TexCoords);
    if(texColor.a < 0.1) discard;
    FragColor = vec4(applyFog(texColor.rgb, FragPos), texColor.a);
}""",

    'fog.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 a_pos;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

out vec3 localPos;

void main() {
    localPos = a_pos;
    gl_Position = projection * view * model * vec4(a_pos, 1.0);
}""",

    'fog.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
in highp vec3 localPos;

uniform highp mat4 model;
uniform highp mat4 inverseModel;
uniform highp vec3 viewPos;

uniform float density;
uniform vec3 fogColor;
uniform sampler3D noiseTexture;
uniform float noiseScale;
uniform highp float time;

highp vec2 intersectBox(highp vec3 rayOrigin, highp vec3 rayDir) {
    highp vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    highp vec3 tMax = ( 0.5 - rayOrigin) / rayDir;
    highp vec3 t1 = min(tMin, tMax);
    highp vec3 t2 = max(tMin, tMax);
    return vec2(max(max(t1.x, t1.y), t1.z),
                min(min(t2.x, t2.y), t2.z));
}

void main() {
    highp vec3 fragWorldPos = vec3(model * vec4(localPos, 1.0));
    highp vec3 rayDirWorld  = normalize(fragWorldPos - viewPos);

    highp vec3 rayOriginLocal = (inverseModel * vec4(viewPos,       1.0)).xyz;
    highp vec3 rayDirLocal    = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);

    highp vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    if (t.x >= t.y) discard;

    highp float tNear    = max(0.0, t.x);
    highp float stepSize = (t.y - tNear) / 16.0;

    vec4  acc        = vec4(0.0);
    highp float timeOffset = time * 0.1;

    for (int i = 0; i < 16; ++i) {
        highp vec3 sp = rayOriginLocal + rayDirLocal * (tNear + float(i) * stepSize);
        float n       = texture(noiseTexture, sp * noiseScale + vec3(0.0, 0.0, timeOffset)).r;
        float tr      = exp(-density * n * stepSize);
        acc.rgb      += fogColor * (1.0 - tr) * (1.0 - acc.a);
        acc.a        += (1.0 - tr);
        if (acc.a > 0.99) break;
    }

    FragColor = vec4(acc.rgb, clamp(acc.a, 0.0, 1.0));
}""",

    'water.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out vec2 TexCoords;
out mediump vec3 Normal;
out mediump float WaveCrest;
out mediump float ShoreDist;
out highp float RestY;       // height of the still surface under this vertex
out highp vec3 LocalPos;     // the vertex in the brush's unit box (box water)
out highp vec2 SkyUV;        // the sky panorama texel this vertex reflects

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform highp float time;
uniform mat3 normalMatrix;

uniform float waveAmp;    // total wave amplitude in world units
uniform highp vec3 brushSize;   // world-space brush dimensions (also water.frag)
uniform highp int reflectSky;   // 1: the map has a sky panorama to reflect (also water.frag)
uniform float waveSpread; // "Wave Spacing": 0 tight and choppy, 1 broad
// "Direction": how far the surface has flowed (world x, z), so its pattern
// is sampled that far upstream. Zero -- still water -- leaves every
// position exactly as it is (also water.frag).
uniform highp vec2 flowOffset;

""" + PANORAMA_GLSL + WAVE_VARIATION_GLSL + """
// One Gerstner wave: displaces the vertex and accumulates normal derivatives.
// *v* is its (phase offset, height scale) here (waveVariation).
void addWave(vec2 dir, float wavelength, float amp, float speed, vec2 p, vec2 v,
             inout float dy, inout vec2 dxz, inout vec3 n)
{
    amp *= v.y;
    float k = 6.2831853 / wavelength;
    float f = k * dot(dir, p) + speed * time + v.x;
    float s = sin(f);
    float c = cos(f);
    float steep = min(0.8 / (k * max(amp, 0.0001) * 4.0), 1.2);
    dy  += amp * s;
    dxz += steep * amp * c * dir;
    n.x -= dir.x * k * amp * c;
    n.z -= dir.y * k * amp * c;
    n.y -= steep * k * amp * s * 0.25;
}

void main()
{
    vec3 worldPos = vec3(model * vec4(aPos, 1.0));
    RestY = worldPos.y;

    // World-space distance from this vertex to the nearest lateral brush edge.
    // Waves are pinned to zero at the edges so the surface always meets the
    // side faces / pool walls exactly (keeps the volume watertight).
    vec2 edgeLocal = vec2(0.5) - abs(aPos.xz);
    float edgeWorld = min(edgeLocal.x * brushSize.x, edgeLocal.y * brushSize.z);
    float fadeW = clamp(min(brushSize.x, brushSize.z) * 0.25, 4.0, 48.0);
    float edgeFade = smoothstep(0.0, fadeW, edgeWorld);

    float topVert = step(0.49, aPos.y);   // only the top surface deforms
    float amp = waveAmp * edgeFade * topVert;

    float dy = 0.0;
    vec2 dxz = vec2(0.0);
    vec3 n = vec3(0.0, 1.0, 0.0);
    if (amp > 0.001) {
        // Wavelengths in world units (a player is ~64 tall). At 190, 118, 74
        // and 38 -- "Wave Spacing" fully left -- crests are a couple of
        // strides apart: tight, choppy water. Fully right (the default)
        // each is 2.2x longer, and slower by sqrt(2.2), as longer waves on
        // real water are: a broad, calm swell.
        float longer = mix(1.0, 2.2, clamp(waveSpread, 0.0, 1.0));
        float slower = inversesqrt(longer);
        highp vec2 wavePos = worldPos.xz - flowOffset;
        addWave(vec2( 0.788,  0.616), 190.0 * longer, amp * 0.42, 1.05 * slower, wavePos,
                waveVariation(wavePos, 0.0), dy, dxz, n);
        addWave(vec2(-0.552,  0.834), 118.0 * longer, amp * 0.28, 1.45 * slower, wavePos,
                waveVariation(wavePos, 1.0), dy, dxz, n);
        addWave(vec2( 0.943, -0.333),  74.0 * longer, amp * 0.19, 1.95 * slower, wavePos,
                waveVariation(wavePos, 2.0), dy, dxz, n);
        addWave(vec2(-0.673, -0.740),  38.0 * longer, amp * 0.11, 2.70 * slower, wavePos,
                waveVariation(wavePos, 3.0), dy, dxz, n);
        worldPos.y  += dy;
        worldPos.xz += dxz * 0.75 * edgeFade;
    }

    vec3 baseNormal = normalize(normalMatrix * aNormal);
    // Only the upward-facing surface takes the wave normal; side walls keep
    // their flat normals even at their top verts (which do get displaced)
    float topFaceVert = topVert * step(0.5, aNormal.y);
    Normal    = normalize(mix(baseNormal, normalize(n), topFaceVert));
    FragPos   = worldPos;
    TexCoords = aTexCoords;
    WaveCrest = clamp(dy / max(waveAmp * 0.85, 0.001) * 0.5 + 0.5, 0.0, 1.0);
    ShoreDist = edgeWorld;
    LocalPos  = aPos;
    SkyUV     = vec2(0.0);
    if (reflectSky == 1) {
        // Where in the panorama this vertex's reflection points, by the sky
        // pass's own mapping: worked out here, per vertex, so a pixel pays
        // one texture read and no trigonometry (water.frag skyColor). The
        // horizontal coordinate is taken relative to the camera's heading,
        // so the texture's seam (GL_REPEAT wraps it) stays behind the
        // camera instead of cutting across a triangle in view.
        vec3 eyePos = -transpose(mat3(view)) * view[3].xyz;
        vec3 reflected = reflect(normalize(worldPos - eyePos), Normal);
        vec3 forward = -vec3(view[0][2], view[1][2], view[2][2]);
        highp vec2 uv = panoramaUV(reflected);
        highp float headingU = panoramaUV(forward).x;
        highp float relative = uv.x - headingU;
        relative -= floor(relative + 0.5);
        SkyUV = vec2(headingU + relative, uv.y);
    }

    gl_Position = projection * view * vec4(worldPos, 1.0);
}""",

    'water.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in highp vec2 TexCoords;
in vec3 Normal;
in float WaveCrest;
in float ShoreDist;
in highp float RestY;
in highp vec3 LocalPos;
in highp vec2 SkyUV;

struct Light {
    highp vec3 position;
    vec3 color;
    float intensity;
    highp float radius;
};

#define MAX_LIGHTS """ + str(MAX_LIGHTS_WATER) + """
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
// highp as in the vertex stage: GLSL ES links a shared uniform only when
// both stages declare the same precision (the player's GLES path).
uniform highp mat4 view;
uniform highp mat4 projection;
uniform highp vec3 viewPos;
uniform sampler2D normalMap;
uniform sampler2D sceneColor;
uniform highp float time;
// The map's sky panorama, reflected instead of the procedural sky whenever
// the map has one (reflectSky 1, high quality and cheap alike); 0 is the
// procedural sky, as always.
uniform sampler2D skyPanorama;
uniform highp int reflectSky;
// Box water's side walls, high quality: localEye is the camera in the box's
// unit space, sideSkipMargin the highest crest above its still top (box
// units). See main().
uniform int skipCoveredSides;
uniform highp vec3 localEye;
uniform float sideSkipMargin;
uniform highp vec3 brushSize;   // world size of the brush (shared with water.vert)

uniform highp float waveSpread;   // "Wave Spacing": 0 tight and choppy, 1 broad
uniform highp vec2 flowOffset;    // "Direction": how far it has flowed (water.vert)
uniform float waterOpacity;
uniform float waterReflectivity;
uniform float distortionStrength;
uniform float refractionIndex;
uniform float roughness;
uniform float fresnelIntensity;
uniform vec2 screenSize;
uniform vec3 waterTint;
// 1 for emissive water (it glows in its tint, whatever light falls on it);
// 0 for all other water, which this then leaves exactly as it was.
uniform float waterEmissive;

// Scene depth, copied once per water pass alongside sceneColor. With it the
// water knows how much of it lies in front of the bed: colour absorption by
// depth, soft foamy shorelines, caustics and screen-space reflections. With
// hasSceneDepth == 0 (no depth buffer to copy) the shader falls back to the
// depth-less look.
uniform highp sampler2D sceneDepth;
uniform int hasSceneDepth;
uniform int ssrEnabled;
uniform highp mat4 invProjection;
// Effects (ORB, FIRE, custom GIFs) reflected directly: the nearest few drawn
// this frame, as the camera-facing quads they are. xyz centre (world), w
// half width; the half heights beside them.
#define MAX_REFLECTED_EFFECTS 4
uniform int effectCount;
uniform highp vec4 effectQuads[MAX_REFLECTED_EFFECTS];
uniform float effectHalfHeights[MAX_REFLECTED_EFFECTS];""" + FOG_GLSL + """

const vec3 SUN_DIR   = vec3(0.4767, 0.6555, 0.5859);  // pre-normalized
const vec3 SUN_COLOR = vec3(1.00, 0.95, 0.82);

highp float hash21(highp vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
highp float vnoise(highp vec2 p) {
    highp vec2 i = floor(p);
    highp vec2 f = fract(p);
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

""" + SSR_GLSL + """
// An effect is a flat, camera-facing quad: the ray march above steps through
// or past it. It is reflected directly instead. Where the reflected ray
// passes the effect's centre, its offset from the centre says which texel of
// the quad it meets; that texel is on screen, in the scene copy. The depth
// copy says whether the effect's solid part is really what is drawn there
// (the effect pass writes it for texels at least half opaque), so neither
// the transparent corners of the quad nor something standing in front of it
// is reflected. Returns the colour (rgb) and a confidence (a).
vec4 reflectEffects(highp vec3 P, vec3 R) {
    vec3 camRight = vec3(view[0][0], view[1][0], view[2][0]);
    vec3 camUp = vec3(view[0][1], view[1][1], view[2][1]);
    // "Up" and "right" across the ray.
    vec3 upAcross = vec3(0.0, 1.0, 0.0) - R * R.y;
    float upLength = length(upAcross);
    if (upLength < 0.001) return vec4(0.0);
    upAcross /= upLength;
    vec3 rightAcross = cross(upAcross, R);
    if (dot(rightAcross, camRight) < 0.0) rightAcross = -rightAcross;
    for (int i = 0; i < effectCount && i < MAX_REFLECTED_EFFECTS; i++) {
        highp vec3 centre = effectQuads[i].xyz;
        float halfWidth = effectQuads[i].w;
        float halfHeight = effectHalfHeights[i];
        highp float along = dot(centre - P, R);
        if (along <= 0.0) continue;
        highp vec3 offset = P + R * along - centre;
        float ox = dot(offset, rightAcross);
        float oy = dot(offset, upAcross);
        if (abs(ox) >= halfWidth || abs(oy) >= halfHeight) continue;
        highp vec3 texel = centre + camRight * ox + camUp * oy;
        highp vec4 clip = projection * view * vec4(texel, 1.0);
        if (clip.w <= 0.0) continue;
        highp vec2 uv = clip.xy / clip.w * 0.5 + 0.5;
        if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) continue;
        // Is the effect's solid part drawn there? At that pixel or beside
        // it: an animated texture has pin-holes just under half opaque,
        // which would otherwise speckle the reflection.
        highp float texelZ = (view * vec4(texel, 1.0)).z;
        highp float tolerance = 2.0 + abs(texelZ) * 0.004;
        highp vec2 px = 1.5 / vec2(textureSize(sceneDepth, 0));
        float solid = 0.0;
        for (int k = 0; k < 5; k++) {
            highp vec2 at = uv + px * (k == 0 ? vec2(0.0)
                                    : k == 1 ? vec2(1.0, 0.0) : k == 2 ? vec2(-1.0, 0.0)
                                    : k == 3 ? vec2(0.0, 1.0) : vec2(0.0, -1.0));
            highp float d = textureLod(sceneDepth, at, 0.0).r;
            if (d < 0.99999 && abs(viewPosFromDepth(at, d).z - texelZ) <= tolerance) {
                solid = 1.0;
                break;
            }
        }
        if (solid == 0.0) continue;
        vec2 edge = smoothstep(vec2(0.0), vec2(0.04), uv)
                  * smoothstep(vec2(0.0), vec2(0.04), vec2(1.0) - uv);
        return vec4(textureLod(sceneColor, uv, 0.0).rgb, edge.x * edge.y);
    }
    return vec4(0.0);
}

// The sky the water reflects wherever its reflected ray finds nothing on
// screen -- in a top-down game, nearly everywhere: a sky gradient with the sun
// by day, dusk's colour at either end of it, stars and the moon by night, and
// a layer of clouds CLOUD_HEIGHT above the world, seen from the water along
// the reflected ray, so the clouds slide across the water as the camera moves.
// The game sets skyState (night, cloud cover, gloom, dusk) and skyDrift (how
// far the wind has carried the clouds); left unset it is a fair day.
uniform vec4 skyState;
uniform vec2 skyDrift;
// Clouds baked once (engine/sky_clouds.py): R cloud, G toward the sun,
// B toward the moon, A the moon's seas. Tiles.
uniform sampler2D skyClouds;
const float CLOUD_HEIGHT = 6000.0;
const float SKY_REFLECTION_FLOOR = 0.35;
// One tile of the baked clouds covers 1 / CLOUD_SCALE world units of sky.
const float CLOUD_SCALE = 1.0 / 14000.0;
const vec3 MOON_DIR = vec3(-0.17008, 0.97049, -0.17008);   // unit length

float skyHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
// The moon and the stars: points of light that calm water mirrors hard,
// added over the water's colour rather than mixed into it (skyColor's soft
// sky would drown them), and hidden by the clouds.
vec3 skyLights(vec3 dir, vec3 P) {
    float night = clamp(skyState.x, 0.0, 1.0);
    float gloom = clamp(skyState.z, 0.0, 1.0);
    if (reflectSky == 1 || night <= 0.01 || dir.y <= 0.02) return vec3(0.0);
    // The moon rides high, where water seen from above can mirror it: a
    // disc with grey seas on it, and a halo.
    float moon = max(dot(dir, MOON_DIR), 0.0);
    float disc = smoothstep(0.99756, 0.99813, moon);      // about 4 degrees across
    float seas = texture(skyClouds, (dir.xz - MOON_DIR.xz) * 9.0 + 0.37).a;
    vec3 light = vec3(0.86, 0.89, 0.97) * disc * (1.25 - 0.55 * smoothstep(0.45, 0.7, seas))
               + vec3(0.45, 0.55, 0.8) * (pow(moon, 400.0) * 0.7 + pow(moon, 60.0) * 0.18);
    // A star field over the sky, coarse enough that a star is a few pixels
    // across from a top-down camera's height, twinkling.
    vec2 sp = dir.xz / (dir.y + 0.35) * 26.0;
    vec2 cell = floor(sp);
    vec2 f = fract(sp) - 0.5;
    float r = skyHash(cell);
    vec2 off = vec2(skyHash(cell + 1.7), skyHash(cell + 3.1)) - 0.5;
    float d = length(f - off * 0.6);
    float size = 0.06 + 0.1 * skyHash(cell + 7.7);
    float star = step(0.55, r) * smoothstep(size, size * 0.2, d)
               * (0.6 + 0.4 * sin(time * 2.3 + r * 71.0));
    vec3 stars = vec3(0.92, 0.94, 1.0) * star * 5.0 * (1.0 - disc);
    // Behind the clouds, none of it.
    vec2 hit = P.xz + dir.xz / dir.y * (CLOUD_HEIGHT - P.y) + skyDrift;
    float edge = mix(0.66, 0.28, clamp(skyState.y, 0.0, 1.0));
    float clear = 1.0 - smoothstep(edge, edge + 0.2, texture(skyClouds, hit * CLOUD_SCALE).r);
    // Cloud hides the stars; the moon shines through it, dimmed.
    return (light * mix(0.45, 1.0, clear) + stars * clear) * night * (1.0 - gloom * 0.7);
}

// The ripple of this pixel (main), which nudges the reflected panorama.
vec2 skyRipple = vec2(0.0);

// A map with a sky panorama (reflectSky 1; Fio's map-owned sky) reflects
// that instead, where the vertices worked it out (SkyUV), shimmering with
// the ripple: one texture read and no trigonometry -- not the exact
// per-pixel direction, and nobody can tell on moving water. The game's sky
// (and its moon and stars, skyLights) is for maps without one.
vec3 skyColor(vec3 dir, vec3 P) {
    if (reflectSky == 1) {
        return textureLod(skyPanorama, SkyUV + skyRipple * 0.03, 0.0).rgb;
    }
    float night = clamp(skyState.x, 0.0, 1.0);
    float cover = clamp(skyState.y, 0.0, 1.0);
    float gloom = clamp(skyState.z, 0.0, 1.0);
    float dusk = clamp(skyState.w, 0.0, 1.0);
    float h = clamp(dir.y, 0.0, 1.0);
    vec3 top = mix(vec3(0.19, 0.38, 0.66), vec3(0.03, 0.07, 0.19), night);
    vec3 horizon = mix(mix(vec3(0.66, 0.76, 0.83), vec3(0.09, 0.14, 0.27), night),
                       vec3(0.96, 0.56, 0.34), dusk);
    vec3 sky = mix(horizon, top, pow(h, 0.55));
    // Under cloud the whole sky greys.
    sky = mix(sky, mix(vec3(0.56, 0.59, 0.63), vec3(0.03, 0.04, 0.07), night), gloom * 0.8);
    float day = (1.0 - night) * (1.0 - gloom);
    float sunAmount = max(dot(dir, SUN_DIR), 0.0);
    sky += SUN_COLOR * (pow(sunAmount, 350.0) * 3.0 + pow(sunAmount, 24.0) * 0.18) * day;
    // The cloud layer, with light on its sunward side and shadowed beneath.
    if (dir.y > 0.02) {
        vec2 hit = P.xz + dir.xz / dir.y * (CLOUD_HEIGHT - P.y) + skyDrift;
        vec4 tex = texture(skyClouds, hit * CLOUD_SCALE);
        float n = tex.r;
        float edge = mix(0.66, 0.28, cover);
        float c = smoothstep(edge, edge + 0.2, n);
        // Thicker here than a step toward the sun: the cloud faces the light.
        float lit = clamp(0.6 + (n - tex.g) * 4.0, 0.25, 1.0);
        vec3 dayCloud = mix(vec3(0.5, 0.54, 0.6), vec3(1.0, 0.99, 0.96), lit);
        dayCloud = mix(dayCloud, vec3(1.0, 0.70, 0.52) * lit, dusk * 0.65);
        // By night the moon lights them: dark bellies, silver edges.
        float moonLit = clamp(0.5 + (n - tex.b) * 5.0, 0.0, 1.0);
        float rim = smoothstep(0.0, 0.35, c) * (1.0 - smoothstep(0.35, 0.95, c));
        vec3 nightCloud = mix(vec3(0.025, 0.035, 0.07), vec3(0.32, 0.37, 0.5), moonLit * 0.7)
                        + vec3(0.55, 0.62, 0.8) * rim * (0.4 + 0.6 * moonLit);
        vec3 cloud = mix(dayCloud, nightCloud, night);
        cloud = mix(cloud, cloud * vec3(0.6, 0.62, 0.66), gloom);
        sky = mix(sky, cloud, c * mix(1.0, 0.75, night) * smoothstep(0.02, 0.15, dir.y));
    }
    return sky;
}

void main()
{
    if (skipCoveredSides == 1) {
        // A high-quality top surface is opaque and drawn after the walls: a
        // wall fragment the view ray reaches through the top is overwritten
        // by it, so it is not worth shading (it writes nothing instead). The ray from the eye enters the
        // box's column (|x|, |z| <= 0.5) at tEnter; above the highest crest
        // there, it must pass the top surface before it reaches this wall --
        // and, to leave the top's own edge pixels alone, cross the still top
        // plane at least two of the top's pixels inside the column (its
        // footprint, which at a grazing angle is far more than the wall's).
        highp vec3 ray = LocalPos - localEye;
        highp vec2 top = localEye.xz
            + ray.xz * ((0.5 - localEye.y) / min(ray.y, -1.0e-6));
        highp vec2 topPerPixel = fwidth(top);
        highp float tEnter = 0.0;
        if (abs(localEye.x) > 0.5 && abs(ray.x) > 1.0e-6)
            tEnter = max(tEnter, (sign(localEye.x) * 0.5 - localEye.x) / ray.x);
        if (abs(localEye.z) > 0.5 && abs(ray.z) > 1.0e-6)
            tEnter = max(tEnter, (sign(localEye.z) * 0.5 - localEye.z) / ray.z);
        highp float twoPixels = 2.0 * max(topPerPixel.x, topPerPixel.y);
        highp float inset = 0.5 - twoPixels;
        // Wave troughs dip below the still top: the ray must also be below
        // the deepest of them two pixels before it reaches this wall, or it
        // could pass over a trough and see the wall's upper strip.
        highp float before = LocalPos.y
            - ray.y * twoPixels / max(length(ray.xz), 1.0e-6);
        // Not at a grazing angle (under about 11 degrees): seen that flat,
        // the wave mesh can leave pixel-wide cracks the wall shows through.
        highp vec3 worldRay = ray * brushSize;
        bool steep = -worldRay.y > 0.2 * length(worldRay.xz);
        if (steep && localEye.y + tEnter * ray.y > 0.5 + sideSkipMargin
                && before < 0.5 - sideSkipMargin
                && abs(top.x) < inset && abs(top.y) < inset) {
            // Not discard: a shader that can discard loses early depth
            // testing for every draw made with it, the top surface's too.
            // Alpha 0 under SRC_ALPHA / ONE_MINUS_SRC_ALPHA leaves the
            // pixel exactly as it was.
            FragColor = vec4(0.0);
            return;
        }
    }
    highp vec3 toView = viewPos - FragPos;
    highp float viewDist = length(toView);
    vec3 viewDir = toView / max(viewDist, 0.0001);

    vec3 geoN = normalize(Normal);
    // Above or below the water is decided against the still surface, not
    // per pixel: with the eye near the waterline, wave crests rise above it,
    // and a per-pixel test flipped those crests to the underwater look.
    bool topSurface = abs(geoN.y) > 0.5;
    bool backside = topSurface ? (viewPos.y < RestY) : (dot(geoN, viewDir) < 0.0);
    if (backside) geoN = -geoN;

    float topFace = step(0.35, abs(geoN.y));

    // World-space animated normal-map detail.  This is also the normal used
    // by Snell/Fresnel, so the optical effects follow the visible ripples.
    // Flowing water ("Direction") samples it all upstream, by flowOffset:
    // ripples, foam and the broad variation drift with the waves.
    highp vec2 flowPos = FragPos.xz - flowOffset;
    highp vec2 wuv;
    if (topFace > 0.5) {
        wuv = flowPos;
    } else if (abs(geoN.x) > abs(geoN.z)) {
        wuv = vec2(flowPos.y, FragPos.y - time * 6.0);
    } else {
        wuv = vec2(flowPos.x, FragPos.y - time * 6.0);
    }
    // The ripple detail is spread with the waves ("Wave Spacing"): the same
    // pattern, up to 1.7x broader.
    highp vec2 ruv = wuv * mix(1.0, 0.59, clamp(waveSpread, 0.0, 1.0));
    vec2 r1 = texture(normalMap, ruv * 0.0110 + time * vec2( 0.021,  0.014)).xy - 0.5;
    vec2 r2 = texture(normalMap, ruv * 0.0047 + time * vec2(-0.011,  0.008)).xy - 0.5;
    vec2 r3 = texture(normalMap, ruv * 0.0310 + time * vec2( 0.016, -0.029)).xy - 0.5;
    vec2 ripple = r1 + r2 * 0.65 + r3 * 0.35;

    // Broad world-space variation breaks up normal-map repetition on large water brushes.
    highp vec2 broadNoise = vec2(
        vnoise(flowPos * 0.006 + vec2(time * 0.004, -time * 0.003)),
        vnoise(flowPos * 0.008 + vec2(-time * 0.003, time * 0.005))
    ) - 0.5;
    broadNoise += (vec2(
        vnoise(flowPos * 0.0037 + vec2(-time * 0.002, time * 0.001)),
        vnoise(flowPos * 0.0051 + vec2(time * 0.001, time * 0.002))
    ) - 0.5) * 0.55;
    ripple += broadNoise * 0.55;
    skyRipple = ripple;

    float detailFade = 1.0 / (1.0 + viewDist * 0.0009);
    float rippleStrength = (0.34 + WaveCrest * 0.18) * detailFade;

    vec3 N;
    if (topFace > 0.5) {
        N = normalize(vec3(
            geoN.x + ripple.x * rippleStrength,
            geoN.y,
            geoN.z + ripple.y * rippleStrength
        ));
    } else {
        vec3 up = vec3(0.0, 1.0, 0.0);
        vec3 tangent = normalize(cross(up, geoN));
        N = normalize(
            geoN +
            (tangent * ripple.x + up * ripple.y) *
            rippleStrength * 0.6
        );
    }

    // ------------------------------------------------------------------
    // Refraction / transmission: the same screen-space optical treatment
    // used by Glass, but driven by the water's perturbed surface normal.
    // ------------------------------------------------------------------
    float ior = max(refractionIndex, 1.0);
    // Air -> water above the surface; water -> air when viewed from below.
    float eta = backside ? ior : (1.0 / ior);
    highp vec3 straightDir = -viewDir;
    highp vec3 refractDir = refract(straightDir, N, eta);
    // Past the critical angle (looking up at the surface from below at a
    // grazing angle) there is no refracted ray: total internal reflection.
    // refract() returns zero there, which used to fling the screen-space
    // offset across the frame; look straight through instead and let the
    // water body colour take over (see totalInternal below).
    float totalInternal = 0.0;
    if (dot(refractDir, refractDir) < 0.25) {
        refractDir = straightDir;
        totalInternal = 1.0;
    }
    highp vec3 refractDeltaView = mat3(view) * (refractDir - straightDir);
    highp float refractDeltaLen = length(refractDeltaView);
    if (refractDeltaLen > 1.0e-5) {
        refractDeltaView /= refractDeltaLen;
    } else {
        refractDeltaView = vec3(0.0);
    }

    highp vec2 projectionScale =
        vec2(projection[0][0], projection[1][1]);
    highp vec2 normalView =
        normalize(mat3(view) * N).xy;
    highp float grazing =
        1.0 - clamp(abs(dot(viewDir, N)), 0.0, 1.0);

    highp vec2 refractionWarp =
        refractDeltaView.xy *
        projectionScale *
        (0.055 + 0.035 * grazing);
    highp vec2 normalWarp =
        normalView *
        (0.012 + 0.010 * grazing);

    highp float nWarp1 =
        vnoise(FragPos.xz * 0.08 + TexCoords * 3.0);
    highp float nWarp2 =
        vnoise(FragPos.xy * 0.11 + TexCoords * 5.0);
    highp vec2 microWarp =
        (vec2(nWarp1, nWarp2) - 0.5) * 0.020;

    highp vec2 screenUV =
        gl_FragCoord.xy / max(screenSize, vec2(1.0));
    highp vec2 uvOffset =
        (refractionWarp + normalWarp + microWarp) *
        distortionStrength;
    highp vec2 refractUV = clamp(
        screenUV + uvOffset,
        vec2(0.001),
        vec2(0.999)
    );

    // How much water the view ray crosses before it reaches the bed, and
    // where that bed is (for caustics). Refracted samples of anything in
    // front of the water - a bank, a wading monster - would smear it into
    // the surface, so those fall back to the unrefracted pixel.
    bool haveDepth = hasSceneDepth == 1 && !backside;
    highp vec3 surfaceView = (view * vec4(FragPos, 1.0)).xyz;
    highp float thickness = 1.0e4;
    highp float bedDepth = 1.0e4;       // vertical depth of the bed below the surface
    highp vec3 bedWorld = FragPos - vec3(0.0, 1.0e4, 0.0);
    bool bedVisible = false;
    if (haveDepth) {
        // The refracted sample is the bed unless it lies in front of the
        // surface; only then is the unrefracted pixel read instead.
        highp float dBed = textureLod(sceneDepth, refractUV, 0.0).r;
        highp vec3 bedView = viewPosFromDepth(refractUV, dBed);
        if (bedView.z > surfaceView.z) {
            refractUV = clamp(screenUV, vec2(0.001), vec2(0.999));
            dBed = textureLod(sceneDepth, refractUV, 0.0).r;
            bedView = viewPosFromDepth(refractUV, dBed);
        }
        if (dBed < 0.99999) {
            thickness = max(length(bedView) - length(surfaceView), 0.0);
            bedWorld = viewPos - viewDir * length(bedView);
            bedDepth = max(FragPos.y - bedWorld.y, 0.0);
            bedVisible = true;
        }
    }

    vec3 transmitted = texture(sceneColor, refractUV).rgb;
    if (roughness > 0.001) {
        highp vec2 blurStep = roughness * 4.0 / max(screenSize, vec2(1.0));
        transmitted += texture(
            sceneColor,
            clamp(refractUV + vec2(blurStep.x, 0.0),
                  vec2(0.001), vec2(0.999))).rgb;
        transmitted += texture(
            sceneColor,
            clamp(refractUV - vec2(blurStep.x, 0.0),
                  vec2(0.001), vec2(0.999))).rgb;
        transmitted += texture(
            sceneColor,
            clamp(refractUV + vec2(0.0, blurStep.y),
                  vec2(0.001), vec2(0.999))).rgb;
        transmitted /= 4.0;
    }

    // ------------------------------------------------------------------
    // Water body / shallow colour and subsurface-looking crest scatter.
    // ------------------------------------------------------------------
    float NdV = max(dot(N, viewDir), 0.0);
    vec3 deepCol = waterTint * 0.55;
    vec3 shallowCol =
        waterTint * 1.25 +
        vec3(0.02, 0.10, 0.09);
    vec3 bodyCol =
        mix(deepCol, shallowCol,
            pow(1.0 - NdV, 1.5) * 0.7 + 0.15);

    float sss =
        pow(WaveCrest, 2.0) *
        pow(
            max(
                dot(
                    viewDir,
                    -normalize(vec3(SUN_DIR.x, 0.0, SUN_DIR.z))
                ),
                0.0
            ),
            2.0
        );
    bodyCol +=
        (waterTint * 0.8 + vec3(0.05, 0.22, 0.18)) * sss;

    bodyCol *=
        0.45 + 0.55 * max(dot(N, SUN_DIR), 0.0);

    vec3 transmission;
    // Caustics: light focused by the ripples dances over the bed, strongest
    // in the shallows. Sampled on the top surface only, where they are used:
    // haveDepth and topFace hold for a whole primitive, so the mipmapped
    // lookups stay in uniform control flow (bedVisible does not, and stays
    // inside).
    if (haveDepth) {
        if (topFace > 0.5) {
            highp vec2 cuv = (bedWorld.xz - flowOffset) * 0.03;
            float c1 = texture(normalMap, cuv + time * vec2(0.031, 0.022)).x;
            float c2 = texture(normalMap, cuv * 1.37 - time * vec2(0.024, 0.037)).y;
            if (bedVisible) {
                float caustic = pow(1.0 - abs(c1 + c2 - 1.0), 10.0);
                transmitted *= 1.0 + caustic * 0.55 * exp(-bedDepth * 0.03) * detailFade;
            }
        }
        // Beer-Lambert absorption: red goes first, so the shallows stay clear
        // and deeper water turns to the tint colour.
        // Authored opacity sets how murky the water is: 0.5 is the default.
        vec3 absorb = ((vec3(1.0) - clamp(waterTint, 0.0, 1.0)) * 0.018 + 0.002)
                    * clamp(waterOpacity, 0.05, 1.0) * 2.0;
        vec3 extinction = exp(-absorb * thickness);
        transmission = transmitted * extinction + bodyCol * (vec3(1.0) - extinction);
    } else {
        // Mix the refracted scene with the water's own body colour so shallow
        // geometry remains visible instead of replacing the water with a flat
        // post-process image.
        vec3 transmittedTinted =
            transmitted * mix(vec3(1.0), waterTint, 0.35);
        transmission =
            mix(transmittedTinted, bodyCol, 0.45);
    }

    // ------------------------------------------------------------------
    // Fresnel: physical R0 for water (~0.0204), multiplied by the authored
    // Fresnel/reflectivity intensity so existing maps retain their control.
    // ------------------------------------------------------------------
    float f0 = 0.020373;
    float fresnel =
        f0 + (1.0 - f0) * pow(1.0 - NdV, 5.0);
    fresnel = clamp(
        fresnel * clamp(fresnelIntensity, 0.0, 4.0),
        0.0, 1.0
    );

    vec3 R = reflect(-viewDir, N);
    // The sky is seen from the real camera (the view matrix's eye): the
    // reflected rays fan out across the water as they truly do from above,
    // the ripples tilting them a little, so the sky shimmers.
    vec3 eye = vec3(inverse(view)[3]);
    vec3 skyR = reflect(normalize(FragPos - eye), normalize(mix(vec3(0.0, 1.0, 0.0), N, 0.35)));
    vec3 reflection = skyColor(skyR, FragPos);
    float sceneReflection = 0.0;
    // The scene's reflection fades out with distance; past the fade no ray
    // is marched, and the sky is what the far water reflects.
    float ssrFade = reflectionFade(surfaceView);
    if (haveDepth && ssrEnabled == 1 && topFace > 0.5 && ssrFade > 0.0) {
        // Reflect the scene itself where the ray finds it on screen; the sky
        // fills in everywhere else. Rougher water blurs towards the sky.
        vec4 ssr = traceReflection(surfaceView, normalize(mat3(view) * R));
        sceneReflection = ssr.a * (1.0 - roughness * 0.6) * ssrFade;
        reflection = mix(reflection, ssr.rgb, sceneReflection);
        if (effectCount > 0) {
            // By the wave's own normal, with only a little of the ripple
            // detail: a small object a few hundred units off, reflected by
            // the full detail normal, scatters into speckle.
            vec3 calm = normalize(mix(geoN, N, 0.2));
            vec4 effect = reflectEffects(FragPos, reflect(-viewDir, calm));
            effect.a *= ssrFade;
            if (effect.a > 0.0) {
                reflection = mix(reflection, effect.rgb, effect.a);
                sceneReflection = max(sceneReflection, effect.a);
            }
        }
    }

    // Keep authored reflectivity visible at normal viewing angles. Physical
    // water Fresnel starts around 2%, which is too weak to make the optional
    // reflection perceptible from above on its own; grazing angles still get
    // the full Fresnel response.
    float reflectionWeight = max(
        fresnel,
        clamp(waterReflectivity, 0.0, 1.0) * 0.5
    );
    // Reflections of the scene are what make water read as water from
    // normal viewing heights, where physical Fresnel is only a few percent:
    // let the authored reflectivity carry them further.
    reflectionWeight = max(reflectionWeight,
        clamp(waterReflectivity, 0.0, 1.0) * 0.8 * sceneReflection);
    // Seen from above, the sky is what open water shows most of: its clouds,
    // dusk and stars carry at least SKY_REFLECTION_FLOOR of the colour of a
    // calm top surface (less where it is rough, none where the scene is).
    reflectionWeight = max(reflectionWeight,
        SKY_REFLECTION_FLOOR * topFace * (1.0 - roughness * 0.7) * (1.0 - sceneReflection));
    vec3 color = mix(transmission, reflection, reflectionWeight);
    color += skyLights(skyR, FragPos) * topFace * (1.0 - roughness * 0.8) * (1.0 - sceneReflection);

    // ------------------------------------------------------------------
    // Dynamic lights / specular / foam.
    // ------------------------------------------------------------------
    vec3 diffuseAcc = vec3(0.0);
    vec3 specAcc = vec3(0.0);
    for (int i = 0; i < active_lights && i < MAX_LIGHTS; i++) {
        highp vec3 toL = lights[i].position - FragPos;
        highp float dist = length(toL);
        if (dist < lights[i].radius) {
            vec3 Ldir = toL / dist;
            float att =
                1.0 - smoothstep(0.0, lights[i].radius, dist);
            vec3 lc =
                lights[i].color * lights[i].intensity * att;
            diffuseAcc += max(dot(N, Ldir), 0.0) * lc;
            vec3 Hl = normalize(Ldir + viewDir);
            float ndh = max(dot(N, Hl), 0.0);
            specAcc +=
                (pow(ndh, 240.0) * 1.6 +
                 pow(ndh, 28.0) * 0.15) * lc;
        }
    }
    color += color * diffuseAcc * 0.45;

    vec3 Hs = normalize(SUN_DIR + viewDir);
    float sunSpec =
        pow(max(dot(N, Hs), 0.0), 320.0);
    float sparkle =
        vnoise(wuv * 0.9 +
               vec2(time * 1.7, -time * 1.3)) *
        vnoise(wuv * 1.7 -
               vec2(time * 0.9, -time * 1.1));
    sunSpec *=
        (1.0 + sparkle * 6.0) *
        detailFade;
    vec3 specular =
        SUN_COLOR * sunSpec * 2.2 + specAcc;

    // Only the top surface foams (topFace is 0 or 1): the walls skip it.
    float foam = 0.0;
    if (topFace > 0.5) {
        float foamNoise =
            vnoise(wuv * 0.16 +
                   vec2(time * 0.05, -time * 0.04)) * 0.6 +
            vnoise(wuv * 0.45 -
                   vec2(time * 0.07, time * 0.06)) * 0.4;
        // Only some crests break, in broad patches drifting over the water,
        // so the foam never falls into a pattern of its own.
        float foamPatches = vnoise(wuv * 0.0035 + vec2(time * 0.012, -time * 0.009)) * 0.65 +
                            vnoise(wuv * 0.0091 - vec2(time * 0.017, time * 0.011)) * 0.35;
        float crestFoam =
            smoothstep(0.68, 0.92, WaveCrest) *
            smoothstep(0.35, 0.75, foamNoise) *
            smoothstep(0.42, 0.72, foamPatches);
        // No foam lines: not along the brush's edges (straight lines, and
        // where the water pours off the world's edge a line round the fall),
        // nor along the waterline. Only breaking crests foam.
        foam = clamp(crestFoam, 0.0, 1.0);
    }

    color += specular * (0.35 + 0.65 * waterReflectivity);
    color = mix(
        color,
        vec3(0.90, 0.95, 0.96),
        foam * 0.85
    );

    float alpha =
        clamp(waterOpacity, 0.05, 1.0) *
        (0.60 + 0.40 * (1.0 - NdV));
    alpha = clamp(
        alpha +
        fresnel * 0.35 +
        foam * 0.45 +
        sunSpec * 0.4,
        0.05,
        1.0
    );

    if (haveDepth && topFace > 0.5) {
        // The refracted, absorbed scene is already in the colour, so the
        // surface is opaque - blending it over the scene again would let the
        // unabsorbed bed show through. It only fades out where the water
        // meets the shore, so there is no hard seam.
        alpha = smoothstep(0.0, 1.5, bedDepth);
    }

    if (backside && totalInternal > 0.5) {
        // Total internal reflection mirrors the underwater world, which is
        // mostly the water's own body colour.
        color = mix(color, bodyCol, 0.85);
    }

    if (backside) {
        color = mix(
            color,
            waterTint * 1.4 + vec3(0.10, 0.18, 0.20),            0.35
        );
        alpha = min(alpha + 0.15, 1.0);
    }

    if (waterEmissive > 0.0) {
        // Glowing water: its own colour shows through the reflections and
        // the dark, strongest where the surface is seen square on.
        color = mix(color, waterTint * 1.6 + vec3(0.04), 0.7 * waterEmissive);
        alpha = min(alpha + 0.3 * waterEmissive, 1.0);
    }

    FragColor = vec4(applyFog(color, FragPos), alpha);
}""",

    'glass.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out highp vec3 FragPos;
out mediump vec3 Normal;
out highp vec2 TexCoords;
out highp vec3 ViewFragPos;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;

void main() {
    FragPos     = vec3(model * vec4(aPos, 1.0));
    Normal      = normalize(normalMatrix * aNormal);
    TexCoords   = aTexCoords;
    ViewFragPos = vec3(view * vec4(FragPos, 1.0));
    gl_Position = projection * vec4(ViewFragPos, 1.0);
}""",

    'glass.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in vec3 Normal;
in highp vec2 TexCoords;
in highp vec3 ViewFragPos;

uniform highp vec3 viewPos;
// highp as in the vertex stage: GLSL ES links a shared uniform only when
// both stages declare the same precision (the player's GLES path).
uniform highp mat4 view;
uniform highp mat4 projection;
uniform vec3 waterColor;
uniform float distortionStrength;
uniform float fresnelIntensity;
uniform float glassOpacity;
uniform float refractionIndex;
uniform float roughness;
uniform sampler2D sceneColor;
uniform vec2 screenSize;""" + FOG_GLSL + """

void main() {
    highp vec3 viewDir = normalize(viewPos - FragPos);
    highp vec3 baseNormal = normalize(Normal);

    // Screen-space transmission needs an authored, visible warp. The old
    // implementation projected a unit ray delta and then divided it by
    // scene depth, which leaves the resulting UV displacement well below a
    // pixel on normal editor/game distances. Keep the Snell direction so the
    // IOR slider still has a physical relationship to the result, but map the
    // angular change into a bounded screen-space offset controlled directly by
    // the distortion slider.
    float ior = max(refractionIndex, 1.0);
    float eta = 1.0 / ior;
    highp vec3 straightDir = -viewDir;
    highp vec3 refractDir = refract(straightDir, baseNormal, eta);
    highp vec3 refractDeltaView = mat3(view) * (refractDir - straightDir);
    highp float refractDeltaLen = length(refractDeltaView);
    if (refractDeltaLen > 1.0e-5) {
        refractDeltaView /= refractDeltaLen;
    } else {
        refractDeltaView = vec3(0.0);
    }

    highp vec2 projectionScale = vec2(projection[0][0], projection[1][1]);
    highp vec2 normalView = normalize(mat3(view) * baseNormal).xy;
    highp float grazing = 1.0 - clamp(abs(dot(viewDir, baseNormal)), 0.0, 1.0);

    // The refracted direction supplies the broad warp; the view-space normal
    // keeps a flat sheet of glass visibly responsive even when the ray delta is
    // tiny; grazing angles get a little more displacement, like real glass.
    highp vec2 refractionWarp =
        refractDeltaView.xy * projectionScale * (0.055 + 0.035 * grazing);
    highp vec2 normalWarp = normalView * (0.012 + 0.010 * grazing);

    highp vec2 screenUV = gl_FragCoord.xy / screenSize;

    // Keep the warp entirely on the core refraction/normal path. The former
    // procedural hash/noise helper triggered an Intel GLSL compiler failure on
    // some older integrated-GPU drivers.
    highp vec2 uvOffset =
        (refractionWarp + normalWarp) * distortionStrength;

    highp vec2 refractUV = clamp(
        screenUV + uvOffset,
        vec2(0.001),
        vec2(0.999)
    );

    // Roughness is a real filter over the transmitted scene rather than merely
    // changing a highlight exponent. Four taps are cheap, deterministic, and
    // make the control visibly useful on GL 3.3 hardware.
    highp vec2 blurStep = roughness * 4.0 / screenSize;
    vec3 transmitted = texture(sceneColor, refractUV).rgb;
    if (roughness > 0.001) {
        transmitted += texture(sceneColor, clamp(refractUV + vec2(blurStep.x, 0.0),
                                                 vec2(0.001), vec2(0.999))).rgb;
        transmitted += texture(sceneColor, clamp(refractUV - vec2(blurStep.x, 0.0),
                                                 vec2(0.001), vec2(0.999))).rgb;
        transmitted += texture(sceneColor, clamp(refractUV + vec2(0.0, blurStep.y),
                                                 vec2(0.001), vec2(0.999))).rgb;
        transmitted /= 4.0;
    }

    // Tint the transmitted scene without replacing it with a flat glass colour.
    vec3 filteredScene = transmitted * mix(vec3(1.0), waterColor, 0.35);

    // Schlick Fresnel: refractionIndex supplies the physically derived F0, while
    // the authored Fresnel slider controls its strength.
    float cosTheta = clamp(dot(viewDir, baseNormal), 0.0, 1.0);
    float f0 = pow((ior - 1.0) / (ior + 1.0), 2.0);
    float fresnel = f0 + (1.0 - f0) * pow(1.0 - cosTheta, 5.0);
    fresnel = clamp(fresnel * fresnelIntensity, 0.0, 1.0);

    vec3 reflectionColor = vec3(0.96, 0.99, 1.0);
    vec3 finalRGB = mix(filteredScene, reflectionColor, fresnel);

    // A compact view-dependent glint keeps Fresnel readable without requiring
    // the glass pass to upload the whole light table a second time.
    highp vec3 halfDir = normalize(viewDir + vec3(0.35, 0.9, 0.2));
    float shininess = mix(128.0, 12.0, roughness);
    float specular = pow(max(dot(baseNormal, halfDir), 0.0), shininess);
    finalRGB += vec3(specular * (0.15 + 0.55 * fresnel));

    float edgeAlpha = fresnel * 0.65 + roughness * 0.20;
    float alpha = clamp(
        glassOpacity + edgeAlpha * (1.0 - glassOpacity),
        0.05,
        1.0
    );

    FragColor = vec4(applyFog(finalRGB, FragPos), alpha);
}""",

    # Depth cube-map pass: renders scene geometry from a point light's position
    # into one cube face, storing linear distance (0..1 = 0..far_plane) so the
    # lighting shaders can do an omnidirectional shadow test.  One draw per face
    # (6 faces) keeps this portable to GL 3.3 with no geometry-shader dependency.
    'depth_cube.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 lightSpaceMatrix;   // proj * view for the current cube face
out vec3 FragPos;
void main() {
    vec4 world = model * vec4(aPos, 1.0);
    FragPos = world.xyz;
    gl_Position = lightSpaceMatrix * world;
}""",
    'depth_cube.frag': """#version 330 core
in vec3 FragPos;
uniform vec3 lightPos;
uniform float far_plane;
void main() {
    // Store distance to the light, normalised into [0, 1].
    gl_FragDepth = length(FragPos - lightPos) / far_plane;
}""",

    'terrain.vert': """#version 330 core
precision highp float;
precision highp int;
// Terrain drawn from a heightfield: no vertex buffer at all.
//
// Each chunk is drawn as 6 vertices per quad, in exactly the order the CPU
// mesh used -- quad q = ix * res + iz, triangle 1 at (ix,iz)(ix+1,iz)(ix,iz+1)
// and triangle 2 at (ix+1,iz)(ix+1,iz+1)(ix,iz+1) -- and every attribute the
// 14-float vertex carried is rebuilt here from the chunk's height grid:
// position, the flat face normal, the per-triangle colour, the UV and the
// smooth normal. The arithmetic follows the old NumPy builder step by step
// (float32 throughout), including its quirks, which are preserved on purpose:
// the face normal points down (cross(+x, +z) = -y) and the "variation" seed
// reduces to iz. (Colour is no longer normalised by the chunk's own height
// range, which coloured the same height differently on each chunk: a hard
// seam along every chunk border.)
out vec3 FragPos;
out mediump vec3 Normal;
out mediump vec3 VertexColor;
out vec2 TexCoords;
out vec2 PaintCoords;
out mediump vec3 SmoothNormal;

uniform mat4 projection;
uniform mat4 view;

// Height grid of the chunk: texel (x = k + 1, y = i + 1) holds grid point
// (i, k). The one-texel ring around it (i or k = -1 or res + 1) lies beyond
// the chunk's edges and is sampled only for smooth normals.
uniform highp sampler2DArray uHeights;
uniform ivec2 uChunkI;     // (quads per side, texture layer)
uniform vec3  uChunkX;     // (world x, world z, grid step), as float32
uniform vec2  uChunkY;     // (chunk min height, height range; 1 when flat)
// The whole terrain's (low, high) height (shared with terrain.frag's layers):
// the colour gradient is read against it, so a height has one colour on every
// chunk and neighbouring chunks meet without a seam.
uniform highp vec2 uHeightRange;
uniform float uTiling;     // Terrain.TILING_SCALE
uniform int   uFlatMode;

// The biome colour gradient, pre-cast exactly as the CPU cast it: stop
// heights and colours, and per segment the float32 width (h1 - h0, or 0 when
// h1 <= h0) and colour delta (c1 - c0).
#define MAX_GRADIENT_STOPS 32
uniform int   uGradCount;
uniform float uGradH[MAX_GRADIENT_STOPS];
uniform vec3  uGradC[MAX_GRADIENT_STOPS];
uniform float uGradW[MAX_GRADIENT_STOPS];
uniform vec3  uGradD[MAX_GRADIENT_STOPS];

float heightAt(int i, int k) {
    return texelFetch(uHeights, ivec3(k + 1, i + 1, uChunkI.y), 0).r;
}

vec3 gridPoint(ivec2 p) {
    return vec3(uChunkX.x + float(p.x) * uChunkX.z,
                heightAt(p.x, p.y),
                uChunkX.y + float(p.y) * uChunkX.z);
}

// Central differences everywhere, the chunk's edge included: the border ring
// supplies the sample beyond it, so both chunks sharing an edge compute the
// same smooth normal there. (The CPU mesh took one-sided differences at the
// edge -- np.gradient's edge_order=1 -- which kinked the normal by a few
// degrees and showed as a seam in the texture blend.)
float gradientAlong(int i, int k, bool alongX) {
    ivec2 a = alongX ? ivec2(i - 1, k) : ivec2(i, k - 1);
    ivec2 b = alongX ? ivec2(i + 1, k) : ivec2(i, k + 1);
    return (heightAt(b.x, b.y) - heightAt(a.x, a.y)) / (2.0 * uChunkX.z);
}

vec3 gradientColour(float h) {
    if (uGradCount == 0) return vec3(0.5);
    vec3 result = vec3(0.0);
    for (int s = 0; s < uGradCount - 1; ++s) {
        if (h >= uGradH[s] && h <= uGradH[s + 1]) {
            float t = uGradW[s] > 0.0 ? (h - uGradH[s]) / uGradW[s] : 0.0;
            result = uGradC[s] + t * uGradD[s];
        }
    }
    if (h > uGradH[uGradCount - 1]) result = uGradC[uGradCount - 1];
    return result;
}

void main() {
    int res = uChunkI.x;
    int quad = gl_VertexID / 6;
    int corner = gl_VertexID - quad * 6;
    int ix = quad / res;
    int iz = quad - ix * res;
    bool second = corner >= 3;

    ivec2 a = second ? ivec2(ix + 1, iz)     : ivec2(ix, iz);
    ivec2 b = second ? ivec2(ix + 1, iz + 1) : ivec2(ix + 1, iz);
    ivec2 c = ivec2(ix, iz + 1);
    int own = second ? corner - 3 : corner;
    ivec2 me = own == 0 ? a : (own == 1 ? b : c);

    vec3 pa = gridPoint(a);
    vec3 pb = gridPoint(b);
    vec3 pc = gridPoint(c);
    vec3 p  = own == 0 ? pa : (own == 1 ? pb : pc);

    // Flat face normal: cross(v1 - v0, v2 - v0) / |.|, as stored.
    vec3 n = cross(pb - pa, pc - pa);
    float nlen = sqrt(dot(n, n));
    Normal = nlen == 0.0 ? n : n / nlen;

    if (uFlatMode != 0) {
        VertexColor = vec3(0.7);
    } else {
        float meanHeight = (pa.y + pb.y + pc.y) / 3.0;   // "centroid" is reserved
        float norm = clamp((meanHeight - uHeightRange.x)
                           / max(uHeightRange.y - uHeightRange.x, 1e-3), 0.0, 1.0);
        int seed = second ? ((ix + 1000) * 1000 + iz + 1000) % 100
                          : (ix * 1000 + iz) % 100;
        float variation = (float(seed) / 100.0 - 0.5) * 0.08;
        VertexColor = clamp(gradientColour(norm) + variation, 0.0, 1.0);
    }

    float gx = gradientAlong(me.x, me.y, true);
    float gz = gradientAlong(me.x, me.y, false);
    SmoothNormal = vec3(-gx, 1.0, -gz) / sqrt(gx * gx + 1.0 + gz * gz);

    TexCoords = p.xz / uTiling;
    PaintCoords = vec2(float(me.x), float(me.y)) / float(max(res, 1));
    FragPos = p;
    gl_Position = projection * view * vec4(p, 1.0);
}""",

    # Blocks terracing: square land columns and their walls, built on the
    # CPU per chunk (engine.terrain_style.build_block_mesh), because a height
    # grid cannot hold vertical walls. Same outputs as terrain.vert.
    'terrain_mesh.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec3 aColor;
layout (location = 3) in vec2 aTexCoord;
layout (location = 4) in vec3 aSmoothNormal;

out vec3 FragPos;
out mediump vec3 Normal;
out mediump vec3 VertexColor;
out vec2 TexCoords;
out vec2 PaintCoords;
out mediump vec3 SmoothNormal;

uniform mat4 projection;
uniform mat4 view;

void main() {
    FragPos      = aPos;
    Normal       = aNormal;
    VertexColor  = aColor;
    TexCoords    = aTexCoord;
    PaintCoords  = aTexCoord;
    SmoothNormal = aSmoothNormal;
    gl_Position  = projection * view * vec4(aPos, 1.0);
}""",

    'terrain.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in vec3 Normal;
in vec3 VertexColor;
in highp vec2 TexCoords;
in highp vec2 PaintCoords;
in vec3 SmoothNormal;

uniform sampler2D texGrass;
uniform sampler2D texRock;
uniform sampler2D texSand;
uniform sampler2D texSnow;
uniform int use_textures;

// Baked terrain material paint. The editor composites source images into a
// persistent per-chunk RGBA8 terrain map, so this is one terrain lookup rather
// than a per-fragment loop over independent stamp/decal records.
uniform sampler2DArray terrainPaintMap;
uniform int uPaintLayer;
uniform int uPaintEnabled;

// Regional biomes (engine/terrain_biomes.py): one RGBA map over the
// terrain's bounds -- desert, snow, swamp, wheat.
uniform sampler2D uBiomeMap;
uniform int uBiomeEnabled;
uniform highp vec4 uBiomeBounds;     // min x, min z, 1 / range x, 1 / range z

// Settled snow over everything (a game's weather): 0 none .. 1 deep.
uniform float uSnowCover;

// Height texture layers. uHeightRange is the terrain's world-space height
// range; uLayerHeights are the sand->grass, grass->rock and rock->snow
// boundaries as fractions of it.
uniform highp vec2 uHeightRange;
uniform vec3 uLayerHeights;
uniform float uLayerBlend;
uniform float uSlopeRock;

// Appearance options (engine/terrain_style.py). Each one is independent.
uniform int uColorMode;              // 0 natural, 1 palette by height, 2 bands
uniform vec3 uPalette[8];
uniform int uPaletteSize;
uniform highp float uBandHeight;
uniform float uContour;
uniform float uContourWidth;
uniform float uGrid;
uniform highp float uGridSize;
uniform highp vec2 uGridOrigin;
uniform float uCellVariation;
uniform vec3 uWallColor;
uniform float uWall;
uniform float uWallStripes;
uniform vec3 uSpeckleColor;
uniform float uSpeckle;
uniform vec3 uPatchColor;
uniform float uPatch;
uniform int uSmoothShading;
uniform int uLightSteps;
uniform int uDither;

struct Light {
    highp vec3 position;
    vec3 color;
    float intensity;
    highp float radius;
    int shadowIndex;
    int terrainShadowOnly;
    float terrainShadowStrength;
};

uniform Light lights[""" + str(MAX_LIGHTS_TERRAIN) + """];
uniform int active_lights;
""" + SHADOW_GLSL + FOG_GLSL + """
highp float hash(highp vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
highp float noise(highp vec2 p) {
    highp vec2 i = floor(p);
    highp vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}
float fbm2(highp vec2 p) {
    return noise(p) * 0.6 + noise(p * 2.03 + 17.1) * 0.3 + noise(p * 4.1 + 5.3) * 0.1;
}

vec3 applyBiomes(vec3 base, highp vec3 p, float slope, float flatness) {
    highp vec2 uv = (p.xz - uBiomeBounds.xy) * uBiomeBounds.zw;
    if (uv.x < 0.0 || uv.y < 0.0 || uv.x > 1.0 || uv.y > 1.0) return base;
    vec4 w = texture(uBiomeMap, uv);
    if (dot(w, vec4(1.0)) < 0.004) return base;
    float n = fbm2(p.xz * 0.004);
    float grain = noise(p.xz * 0.35);
    vec3 col = base;
    if (w.r > 0.004) {
        // Sand in long dunes, red sandstone where it is steep.
        float dune = 0.5 + 0.5 * sin(p.x * 0.0042 + p.z * 0.0026 + n * 7.0);
        vec3 sand = mix(vec3(0.76, 0.61, 0.38), vec3(0.91, 0.79, 0.54), dune)
                  * mix(0.93, 1.05, grain);
        if (use_textures == 1)
            sand = mix(sand, texture(texSand, TexCoords * 1.5).rgb * vec3(1.06, 0.96, 0.80), 0.45);
        vec3 stone = vec3(0.62, 0.38, 0.24) * mix(0.82, 1.06, noise(p.xz * 0.05 + p.y * 0.08));
        sand = mix(sand, stone, smoothstep(0.3, 0.55, slope));
        float a = clamp(w.r + (n - 0.5) * 0.35, 0.0, 1.0);
        col = mix(col, sand, smoothstep(0.0, 1.0, a));
    }
    if (w.a > 0.004) {
        // Wheat: gold in furrows, each field turned its own way.
        highp vec2 cell = floor(p.xz / 900.0);
        float turn = hash(cell + 4.2) * 3.14159;
        highp float along = dot(p.xz, vec2(cos(turn), sin(turn)));
        float row = 0.5 + 0.5 * sin(along * 0.28);
        vec3 gold = mix(vec3(0.70, 0.54, 0.22), vec3(0.90, 0.76, 0.38), noise(p.xz * 0.012))
                  * mix(0.86, 1.04, row);
        float a = smoothstep(0.35, 0.6, w.a + (grain - 0.5) * 0.08);
        col = mix(col, gold, a);
    }
    if (w.b > 0.004) {
        // Swamp: moss and mud, with dark standing water in the hollows.
        vec3 moss = mix(vec3(0.19, 0.24, 0.11), vec3(0.31, 0.33, 0.16), n)
                  * mix(0.9, 1.06, grain);
        float puddle = smoothstep(0.55, 0.62, fbm2(p.xz * 0.012 + 3.1)) * flatness;
        moss = mix(moss, vec3(0.08, 0.12, 0.11), puddle * 0.85 * w.b);
        float a = clamp(w.b + (n - 0.5) * 0.3, 0.0, 1.0);
        col = mix(col, moss, smoothstep(0.0, 1.0, a));
    }
    if (w.g > 0.004) {
        // Snow, with rock breaking through on the steepest ground.
        vec3 snow = vec3(0.90, 0.93, 0.98) * mix(0.95, 1.03, grain);
        if (use_textures == 1)
            snow = mix(snow, texture(texSnow, TexCoords * 0.8).rgb, 0.5);
        float a = clamp(w.g + (n - 0.5) * 0.3, 0.0, 1.0);
        a = smoothstep(0.0, 1.0, a) * (1.0 - 0.7 * smoothstep(0.45, 0.7, slope));
        col = mix(col, snow, a);
    }
    return col;
}

float heightFraction(highp float y) {
    return clamp((y - uHeightRange.x) / max(uHeightRange.y - uHeightRange.x, 1e-3), 0.0, 1.0);
}

// Sand, grass, rock and snow weights. Each boundary is a smoothstep, so the
// weights always sum to one; a little noise wobbles the edges so they read
// as natural rather than as contour lines. Steep ground turns to rock.
vec4 layerWeights(highp vec3 worldPos, float slope) {
    float h = heightFraction(worldPos.y)
            + (fbm2(worldPos.xz * 0.01) - 0.5) * uLayerBlend * 2.0;
    float b = max(uLayerBlend, 1e-3);
    float s0 = smoothstep(uLayerHeights.x - b, uLayerHeights.x + b, h);
    float s1 = smoothstep(uLayerHeights.y - b, uLayerHeights.y + b, h);
    float s2 = smoothstep(uLayerHeights.z - b, uLayerHeights.z + b, h);
    vec4 w = vec4(1.0 - s0, s0 - s1, s1 - s2, s2);
    float steep = smoothstep(0.25, 0.5, slope) * uSlopeRock;
    return mix(w, vec4(0.0, 0.0, 1.0, 0.0), steep);
}

vec3 paletteAt(float t) {
    int n = max(uPaletteSize, 1);
    float x = clamp(t, 0.0, 1.0) * float(n - 1);
    int i = int(floor(x));
    int j = min(i + 1, n - 1);
    return mix(uPalette[i], uPalette[j], fract(x));
}

// Index of the colour band / terrace a height belongs to. Terrace flats sit
// exactly on multiples of the band height; the offset keeps each riser with
// the level below it until just under the lip, where the contour line runs.
float bandIndex(highp float y) {
    return floor(y / max(uBandHeight, 1e-3) + 0.12);
}

// Ordered-dither threshold in [0, 1) from a 4x4 Bayer matrix, computed
// arithmetically (no arrays, no integer maths) for the widest driver support.
float bayer2(vec2 a) {
    a = floor(a);
    return fract(dot(a, vec2(0.5, a.y * 0.75)));
}
float bayer4(vec2 fragCoord) {
    return bayer2(fragCoord * 0.5) * 0.25 + bayer2(fragCoord);
}

void main() {
    vec3 smoothNorm = normalize(SmoothNormal);
    vec3 faceNorm = normalize(Normal);
    // The ground is seen from above: keep the face normal on the same side
    // as the (always upward) smooth normal.
    if (dot(faceNorm, smoothNorm) < 0.0) faceNorm = -faceNorm;
    vec3 norm = (uSmoothShading == 1) ? smoothNorm : faceNorm;
    float faceSlope = 1.0 - clamp(faceNorm.y, 0.0, 1.0);
    float flatness = 1.0 - smoothstep(0.15, 0.35, faceSlope);
    vec3 texColor;

    // ---- Base colour --------------------------------------------------
    if (uColorMode == 1) {
        // Palette graded by height, stepped with the terraces.
        highp float y = bandIndex(FragPos.y) * uBandHeight;
        texColor = paletteAt(heightFraction(y));
    } else if (uColorMode == 2) {
        // Strata: each band is one flat colour taken from the palette at
        // the band's height, so colours climb the terrain in order (shore,
        // grass, earth, rock, ...). Neighbouring bands alternate slightly
        // lighter and darker, with a little jitter, so the layers read as
        // separate beds of the same material rather than a smooth ramp.
        highp float band = bandIndex(FragPos.y);
        texColor = paletteAt(heightFraction(band * uBandHeight));
        float alternate = mod(band, 2.0) < 0.5 ? 1.0 : 0.93;
        float jitter = 0.97 + 0.06 * hash(vec2(band, 3.7));
        texColor *= alternate * jitter;
    } else if (use_textures == 1) {
        vec4 splat = layerWeights(FragPos, 1.0 - max(smoothNorm.y, 0.0));

        vec4 grass_col = texture(texGrass, TexCoords * 1.0);
        vec4 rock_col  = texture(texRock,  TexCoords * 0.5);
        vec4 sand_col  = texture(texSand,  TexCoords * 1.5);
        vec4 snow_col  = texture(texSnow,  TexCoords * 0.8);

        vec3 splatColor = (
            sand_col.rgb  * splat.x +
            grass_col.rgb * splat.y +
            rock_col.rgb  * splat.z +
            snow_col.rgb  * splat.w
        );
        // The splat textures are the surface colour. (They used to be
        // multiplied by the biome vertex colour as well, which roughly
        // squared the darkness -- green grass times green vertex colour --
        // and carried the vertex colour's per-chunk seams into textured mode.)
        texColor = splatColor * 1.1;
    } else {
        texColor = VertexColor * 1.1;
    }

    // ---- Regional biomes ----------------------------------------------
    if (uBiomeEnabled == 1) {
        texColor = applyBiomes(texColor, FragPos, 1.0 - max(smoothNorm.y, 0.0), flatness);
    }

        // ---- Baked terrain material paint -------------------------------
    if (uPaintEnabled == 1) {
        vec4 paint = texture(
            terrainPaintMap, vec3(clamp(PaintCoords.yx, 0.0, 1.0),
                                  float(uPaintLayer)));
        texColor = mix(texColor, paint.rgb * 1.1, paint.a);
    }

    // ---- Settled snow ------------------------------------------------
    // Lies first in patches (where broad noise is highest), then joins up
    // into a white blanket from about 0.8 cover; steep ground stays darker.
    if (uSnowCover > 0.001) {
        float drift = fbm2(FragPos.xz * 0.003);
        float sgrain = noise(FragPos.xz * 0.3);
        float edge = 1.0 - uSnowCover * 1.25;
        float lie = smoothstep(edge, edge + 0.15, drift + (sgrain - 0.5) * 0.12);
        lie *= 1.0 - 0.75 * smoothstep(0.4, 0.7, faceSlope);
        vec3 snowLie = vec3(0.90, 0.93, 0.98) * mix(0.94, 1.03, sgrain);
        texColor = mix(texColor, snowLie, lie * 0.92);
    }

// ---- Surface details ---------------------------------------------
    highp vec2 cellCoord = (FragPos.xz - uGridOrigin) / max(uGridSize, 1e-3);
    if (uCellVariation > 0.0) {
        float jitter = hash(floor(cellCoord) + vec2(0.37, 0.71)) - 0.5;
        texColor *= 1.0 + jitter * uCellVariation * 0.5;
    }

    if (uPatch > 0.0) {
        float n = fbm2(FragPos.xz * 0.006);
        float m = smoothstep(0.50, 0.58, n) * uPatch * flatness;
        float grain = mix(0.88, 1.06, noise(FragPos.xz * 0.45));
        vec3 patchCol = uPatchColor * grain * mix(0.8, 1.0, smoothstep(0.5, 0.62, n));
        texColor = mix(texColor, patchCol, m);
    }

    if (uWall > 0.0) {
        float wallMask = smoothstep(0.35, 0.7, faceSlope) * uWall;
        highp float yb = FragPos.y / max(uBandHeight, 1e-3);
        vec3 wallCol = uWallColor * mix(0.78, 1.06, fract(yb));
        float stripe = step(fract(yb * 2.0), 0.18);
        wallCol *= 1.0 - stripe * uWallStripes * 0.35;
        texColor = mix(texColor, wallCol, wallMask);
    }

    if (uSpeckle > 0.0) {
        highp vec2 sc = FragPos.xz / 3.0;
        vec2 ci = floor(sc);
        vec2 cf = fract(sc);
        float density = uSpeckle * smoothstep(0.3, 0.7, noise(FragPos.xz * 0.02)) * flatness;
        vec2 centre = vec2(hash(ci + 7.3), hash(ci + 19.1)) * 0.6 + 0.2;
        float dotMask = step(hash(ci), density)
                      * (1.0 - smoothstep(0.16, 0.26, length(cf - centre)));
        // Far away the dots are smaller than a pixel: use their average.
        float farFade = smoothstep(0.15, 0.5, length(fwidth(sc)));
        float amount = mix(dotMask, density * 0.15, farFade);
        texColor = mix(texColor, uSpeckleColor * mix(0.8, 1.1, hash(ci + 3.1)), amount);
    }

    if (uGrid > 0.0) {
        vec2 fw = max(fwidth(cellCoord), vec2(1e-4));
        vec2 d = abs(fract(cellCoord - 0.5) - 0.5) / fw;
        float line = 1.0 - smoothstep(0.5, 1.5, min(d.x, d.y));
        line *= 1.0 - smoothstep(0.15, 0.4, max(fw.x, fw.y));
        texColor *= 1.0 - line * uGrid * (1.0 - smoothstep(0.3, 0.6, faceSlope));
    }

    if (uContour > 0.0) {
        highp float coord = FragPos.y / max(uBandHeight, 1e-3) + 0.12;
        float fw = max(fwidth(coord), 1e-4);
        float f = fract(coord);
        float d = min(f, 1.0 - f) / fw;
        float line = 1.0 - smoothstep(uContourWidth * 0.5 - 0.5, uContourWidth * 0.5 + 0.5, d);
        line *= 1.0 - smoothstep(0.3, 0.6, fw);
        texColor *= 1.0 - line * uContour;
    }

    // ---- Lighting -----------------------------------------------------
    vec3 skyColor    = vec3(0.6, 0.75, 0.9);
    vec3 groundColor = vec3(0.3, 0.25, 0.2);
    float skyFactor  = (norm.y + 1.0) * 0.5;
    vec3 ambient     = (mix(groundColor, skyColor, skyFactor) * 0.3 + uAmbient) * texColor;

    vec3 result  = ambient;
    vec3 sunDir  = normalize(vec3(0.4, 0.7, 0.3));
    vec3 sunColor = vec3(1.0, 0.95, 0.85);
    float sunDiff    = max(dot(norm, sunDir), 0.0);
    float wrappedDiff = (sunDiff + 0.3) / 1.3;
    if (uLightSteps > 0) {
        float steps = float(uLightSteps);
        wrappedDiff = floor(wrappedDiff * steps + 0.5) / steps;
    }
    result += wrappedDiff * sunColor * 0.7 * texColor;

    vec3 fillDir  = normalize(vec3(-0.3, 0.2, -0.4));
    float fillDiff = max(dot(norm, fillDir), 0.0) * 0.2;
    result += fillDiff * skyColor * texColor;

    // A shadow-only light multiplies the *final* terrain illumination, not
    // just sunlight or whichever ordinary light happened to be processed first.
    float terrainShadowMask = 1.0;
    for (int i = 0; i < active_lights && i < """ + str(MAX_LIGHTS_TERRAIN) + """; i++) {
        highp vec3  toLight  = lights[i].position - FragPos;
        highp float distance = length(toLight);
        if (distance < lights[i].radius) {
            vec3  lightDir    = toLight / distance;
            float diff        = max(dot(norm, lightDir), 0.0);
            float attenuation = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            attenuation       = attenuation * attenuation;
            float shadow      = calcPointShadow(lights[i].shadowIndex, toLight, lights[i].radius, diff);
            if (lights[i].terrainShadowOnly != 0) {
                if (diff > 0.0) {
                    float strength = clamp(lights[i].terrainShadowStrength, 0.0, 1.0);
                    terrainShadowMask *= 1.0 - shadow * strength * attenuation;
                }
            } else {
                result += (1.0 - shadow) * diff * lights[i].color * lights[i].intensity * attenuation * texColor;
            }
        }
    }
    result *= terrainShadowMask;

    float gray = dot(result, vec3(0.299, 0.587, 0.114));
    result = mix(vec3(gray), result, 1.15);

    result = applyFog(result, FragPos);
    if (uDither > 0) {
        float levels = float(uDither);
        result = floor(clamp(result, 0.0, 1.0) * levels + bayer4(gl_FragCoord.xy)) / levels;
    }
    FragColor = vec4(result, 1.0);
}""",

    'grass.vert': """#version 330 core

// One instance is one grass blade. The CPU supplies the root position (already
// sitting on the terrain surface), a size, a yaw/seed and a colour variation;
// the GPU builds the tapered blade from gl_VertexID.
//
// A blade with S segments is (S - 1) quads followed by a tip triangle, so a
// draw uses (S - 1) * 6 + 3 vertices per instance. Near chunks draw several
// segments; far chunks draw the S = 1 blade, which is the tip triangle alone.
// Between uLodStart and uLodEnd every blade morphs its width, bend and wind
// profile onto that single triangle, so the swap is invisible.
layout (location = 2) in vec3 iPosition;
layout (location = 3) in float iSize;
layout (location = 4) in float iPhase;
layout (location = 5) in float iVariation;
layout (location = 6) in vec3 iGround;     // colour of the ground under the blade

out vec3 FragPos;
out vec3 BladeNormal;
out float BladeHeight;
out vec3 BladeTint;
out vec3 GroundColor;

uniform mat4 projection;
uniform mat4 view;
uniform float time;
// The wind (TerrainGL.grass_wind): how hard (0.65 a fair breeze; past ~1 a
// storm's gale, which adds fast gusts and a violent flutter), which way (a
// zero vector is the default heading), and how far its gust field has rolled
// along that way so far -- accumulated on the CPU, so a turning or
// strengthening wind never jumps the pattern.
uniform float windStrength;
uniform vec2 uWindDir;
uniform vec2 uWindScroll;
uniform vec3 cameraPos;
uniform int uSegments;
uniform float uLodStart;
uniform float uLodEnd;
uniform float uFadeStart;
uniform float uFadeEnd;
uniform float uBladeHeight;
uniform float uBladeWidth;
// Actors in the grass: (x, z, radius, strength). Blades lean and flatten away
// from each; a fading trail behind a walker lets the grass spring back.
uniform vec4 uPushers[32];
uniform int uPusherCount;

float hash1(float n) {
    return fract(sin(n) * 43758.5453123);
}

// Classic Perlin 2D noise by Stefan Gustavson (MIT).
vec4 permute(vec4 x) { return mod(((x * 34.0) + 1.0) * x, 289.0); }
vec2 fade(vec2 t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
float cnoise(vec2 P) {
    vec4 Pi = floor(P.xyxy) + vec4(0.0, 0.0, 1.0, 1.0);
    vec4 Pf = fract(P.xyxy) - vec4(0.0, 0.0, 1.0, 1.0);
    Pi = mod(Pi, 289.0);
    vec4 ix = Pi.xzxz;
    vec4 iy = Pi.yyww;
    vec4 fx = Pf.xzxz;
    vec4 fy = Pf.yyww;
    vec4 i = permute(permute(ix) + iy);
    vec4 gx = 2.0 * fract(i * 0.0243902439) - 1.0;
    vec4 gy = abs(gx) - 0.5;
    vec4 tx = floor(gx + 0.5);
    gx = gx - tx;
    vec2 g00 = vec2(gx.x, gy.x);
    vec2 g10 = vec2(gx.y, gy.y);
    vec2 g01 = vec2(gx.z, gy.z);
    vec2 g11 = vec2(gx.w, gy.w);
    vec4 norm = 1.79284291400159 - 0.85373472095314 *
                vec4(dot(g00, g00), dot(g01, g01), dot(g10, g10), dot(g11, g11));
    g00 *= norm.x; g01 *= norm.y; g10 *= norm.z; g11 *= norm.w;
    float n00 = dot(g00, vec2(fx.x, fy.x));
    float n10 = dot(g10, vec2(fx.y, fy.y));
    float n01 = dot(g01, vec2(fx.z, fy.z));
    float n11 = dot(g11, vec2(fx.w, fy.w));
    vec2 fade_xy = fade(Pf.xy);
    vec2 n_x = mix(vec2(n00, n01), vec2(n10, n11), fade_xy.x);
    return 2.3 * mix(n_x.x, n_x.y, fade_xy.y);
}

// Quadratic bezier from 0 to 1 with a low control point: a blade that stays
// upright at the root and curls over towards the tip.
float bezier(float t, float p1) {
    float it = 1.0 - t;
    return 2.0 * it * t * p1 + t * t;
}

float bendT(float h, float bendStart) {
    return clamp((h - bendStart) / (1.0 - bendStart), 0.0, 1.0);
}

// Horizontal displacement of the blade's centre line at height fraction h.
vec2 centreOffset(float h, float lod, vec2 forward, vec2 windDir,
                  float bendStrength, float bendStart, float strong, float gentle) {
    float bend = mix(bezier(bendT(h, bendStart), 0.1), h, lod);
    float sway = mix(bendT(h, bendStart), h, lod);
    float windProfile = mix(h * h, h, lod);
    return forward * (bendStrength * bend + gentle * sway)
         + windDir * (strong * windProfile);
}

void main() {
    int segments = max(uSegments, 1);
    int bodyQuads = segments - 1;
    int quad = gl_VertexID / 6;
    int corner = gl_VertexID - quad * 6;

    float level;
    float side;
    if (quad < bodyQuads) {
        // (L,i) (R,i) (L,i+1) / (L,i+1) (R,i) (R,i+1)
        int up = (corner == 2 || corner == 3 || corner == 5) ? 1 : 0;
        side = (corner == 1 || corner == 4 || corner == 5) ? 1.0 : -1.0;
        level = float(quad + up) / float(segments);
    } else {
        level = (corner == 2) ? 1.0 : float(bodyQuads) / float(segments);
        side = (corner == 0) ? -1.0 : ((corner == 1) ? 1.0 : 0.0);
    }

    float dist = distance(cameraPos.xz, iPosition.xz);
    float lod = (segments == 1) ? 1.0 : smoothstep(uLodStart, uLodEnd, dist);
    float distanceScale = 1.0 - smoothstep(uFadeStart, uFadeEnd, dist);

    float seedA = hash1(iPhase * 12.9898 + iVariation * 78.233);
    float seedB = hash1(seedA * 91.7 + 3.1);
    float seedC = hash1(seedB * 47.3 + 7.9);

    float height = uBladeHeight * iSize * mix(0.7, 1.3, seedC) * distanceScale;
    float halfWidth = uBladeWidth * mix(0.8, 1.2, seedB) * (0.5 + 0.5 * distanceScale);
    // Tall stalks (reeds, wheat) are proportionally a little thicker.
    halfWidth *= max(1.0, sqrt(iSize) * 0.6);

    // Static curl direction is fixed in the world. The flat side of the
    // blade turns towards the camera (with a stable per-blade offset) so a
    // field never shows its blades edge-on.
    vec2 forward = vec2(cos(iPhase), sin(iPhase));
    vec2 toCamera = cameraPos.xz - iPosition.xz;
    toCamera = dot(toCamera, toCamera) > 1e-6 ? normalize(toCamera) : vec2(0.0, 1.0);
    float turn = (seedA - 0.5) * 1.2;
    vec2 cameraSide = vec2(-toCamera.y, toCamera.x);
    vec2 sideDir = vec2(cameraSide.x * cos(turn) - cameraSide.y * sin(turn),
                        cameraSide.x * sin(turn) + cameraSide.y * cos(turn));

    // Wind: a slow Perlin field rolling across the world, biased downwind,
    // plus a small per-blade flutter. A gale adds a finer, faster field of
    // gusts that lays the grass over and a hard flutter on top.
    vec2 windDir = dot(uWindDir, uWindDir) > 1e-6 ? normalize(uWindDir)
                                                  : normalize(vec2(1.0, 0.35));
    float wave = cnoise(iPosition.xz * 0.012 - uWindScroll);
    float gale = smoothstep(0.8, 1.1, windStrength);
    float gust = cnoise(iPosition.xz * 0.021 - uWindScroll * 2.7);
    float strong = ((wave * 0.5 + 0.2) * windStrength
                    + gale * (gust * 0.65 + 0.45)) * height;
    // However hard it blows, a blade lies down rather than stretching.
    strong = clamp(strong, -0.6 * height, 1.3 * height);
    float gentle = (sin(time * 1.9 + seedA * 10.0) * 0.08
                    + gale * sin(time * 11.0 + seedB * 20.0) * 0.2) * height;
    float bendStrength = mix(0.15, 0.45, seedA) * height;
    float bendStart = mix(0.0, 0.3, seedB);

    // Parting: sum each actor's push away from it, strongest at its centre.
    vec2 push = vec2(0.0);
    for (int i = 0; i < uPusherCount; ++i) {
        vec2 d = iPosition.xz - uPushers[i].xy;
        float r = uPushers[i].z;
        float d2 = dot(d, d);
        if (d2 < r * r) {
            float dist = sqrt(d2);
            float f = 1.0 - dist / r;
            f = f * f * (3.0 - 2.0 * f) * uPushers[i].w;
            push += (dist > 1e-3 ? d / dist : forward) * f;
        }
    }
    float pushLen = length(push);
    vec2 pushVec = pushLen > 1.0 ? push / pushLen : push;
    // A pushed blade leans from its root, up to nearly flat; per-blade
    // stiffness keeps the parting ragged rather than a clean circle.
    pushVec *= height * mix(0.85, 1.1, seedB);

    // Taper: the detailed blade narrows gently and then closes in the tip
    // triangle; the far blade is a plain triangle. Morph between the two.
    float widthHigh = halfWidth * (1.0 - 0.45 * level);
    float widthLow = halfWidth * (1.0 - level);
    float width = mix(widthHigh, widthLow, lod);

    vec2 offset = centreOffset(level, lod, forward, windDir,
                               bendStrength, bendStart, strong, gentle)
                + pushVec * level;
    // Keep the blade roughly its own length as it leans over.
    float rise = level * height;
    float y = sqrt(max(rise * rise - dot(offset, offset) * 0.6, 0.2 * rise * rise));

    vec3 root = iPosition;
    vec3 p = vec3(root.x + offset.x + sideDir.x * side * width,
                  root.y + y,
                  root.z + offset.y + sideDir.y * side * width);

    // Surface normal from the bent centre line and the blade's width axis,
    // then tilted across the width so the flat card shades like a rounded
    // blade.
    float h2 = min(level + 0.05, 1.0);
    float h1 = h2 - 0.05;
    vec2 o1 = centreOffset(h1, lod, forward, windDir, bendStrength, bendStart, strong, gentle)
            + pushVec * h1;
    vec2 o2 = centreOffset(h2, lod, forward, windDir, bendStrength, bendStart, strong, gentle)
            + pushVec * h2;
    vec3 tangent = vec3(o2.x - o1.x, (h2 - h1) * height, o2.y - o1.y);
    vec3 side3 = vec3(sideDir.x, 0.0, sideDir.y);
    vec3 n = cross(side3, tangent);
    n = dot(n, n) > 1e-10 ? normalize(n) : vec3(0.0, 1.0, 0.0);
    if (dot(n, cameraPos - p) < 0.0) n = -n;
    BladeNormal = normalize(n + side3 * side * 0.6);

    // Colour variation: a large-scale patchiness across the field and a few
    // sun-dried blades.
    float fieldPatch = cnoise(iPosition.xz * 0.0035) * 0.5 + 0.5;
    float dry = smoothstep(0.78, 1.0, seedC) * 0.7;
    BladeTint = mix(vec3(1.0), vec3(1.25, 1.1, 0.55), dry)
              * mix(0.82, 1.12, fieldPatch) * iVariation;

    GroundColor = iGround;
    FragPos = p;
    BladeHeight = level;
    gl_Position = projection * view * vec4(p, 1.0);
}

""",

    'grass.frag': """#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec3 BladeNormal;
in float BladeHeight;
in vec3 BladeTint;
in vec3 GroundColor;

uniform vec3 grassColor;       // blade colour, when one was chosen
uniform vec3 grassTipColor;    // tip colour, when one was chosen
uniform int uMatchGround;      // 1: blades take the colour of their ground
uniform int uTipAuto;          // 1: tips are a sun-bleached shade of the blade
uniform vec3 cameraPos;
""" + FOG_GLSL + """
void main() {
    // Shaded roots rising through the blade colour to the tip colour.
    float g = smoothstep(0.0, 1.0, BladeHeight);
    vec3 bladeColor = (uMatchGround == 1) ? GroundColor : grassColor;
    vec3 tipColor = (uTipAuto == 1)
        ? mix(min(bladeColor * 1.3, vec3(1.0)), vec3(0.80, 0.78, 0.55), 0.3)
        : grassTipColor;
    vec3 rootColor = bladeColor * 0.45;
    vec3 albedo = (g < 0.5 ? mix(rootColor, bladeColor, g * 2.0)
                           : mix(bladeColor, tipColor, g * 2.0 - 1.0)) * BladeTint;

    vec3 n = normalize(BladeNormal);
    // Lean the lighting normal towards the ground normal so a field reads
    // as one surface lit the same way as the terrain under it.
    vec3 nLight = normalize(mix(n, vec3(0.0, 1.0, 0.0), 0.45));
    vec3 viewDir = normalize(cameraPos - FragPos);

    vec3 sunDir = normalize(vec3(0.4, 0.7, 0.3));
    vec3 sunColor = vec3(1.0, 0.95, 0.85);
    vec3 skyColor = vec3(0.6, 0.75, 0.9);
    vec3 groundColor = vec3(0.3, 0.25, 0.2);

    float diffuse = (max(dot(nLight, sunDir), 0.0) + 0.3) / 1.3;
    // Light shining through the blade when looking towards the sun.
    float translucency = pow(max(dot(-viewDir, sunDir), 0.0), 4.0) * 0.45 * g;
    float specular = pow(max(dot(reflect(-sunDir, n), viewDir), 0.0), 24.0) * 0.12 * g;
    float occlusion = mix(0.55, 1.0, g);

    vec3 ambient = mix(groundColor, skyColor, (nLight.y + 1.0) * 0.5) * 0.3 + uAmbient;
    vec3 color = albedo * (ambient * occlusion + sunColor * (diffuse * 0.7 + translucency))
               + sunColor * specular;

    float gray = dot(color, vec3(0.299, 0.587, 0.114));
    color = mix(vec3(gray), color, 1.15);
    FragColor = vec4(applyFog(color, FragPos), 1.0);
}
""",

}

# ----- Low-power shaders (used by ForwardRenderer when lowpower_mode is True) ----
DEFAULT_SHADERS['lit_arm.vert'] = """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
out vec3 FragPos;
out vec3 Normal;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalMatrix * aNormal;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}"""

DEFAULT_SHADERS['lit_arm.frag'] = """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
uniform vec3 emissive_factor;
struct Light { vec3 position; vec3 color; float intensity; float radius; int shadowIndex; };
uniform Light lights[""" + str(MAX_LIGHTS_ARM) + """];
uniform int active_lights;""" + SHADOW_GLSL + FOG_GLSL + """
void main() {
    vec3 norm = normalize(Normal);
    vec3 result = (vec3(0.12) + uAmbient) * object_color;
    for(int i = 0; i < active_lights && i < """ + str(MAX_LIGHTS_ARM) + """; i++) {
        vec3 toLight = lights[i].position - FragPos;
        float distSq = dot(toLight, toLight);
        float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            float dist = sqrt(distSq);
            vec3 lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - (dist / lights[i].radius);
            att = att * att;
            float shadow = calcPointShadow(lights[i].shadowIndex, toLight, lights[i].radius, diff);
            result += (1.0 - shadow) * (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    result += emissive_factor;
    FragColor = vec4(applyFog(result, FragPos), alpha);
}"""

DEFAULT_SHADERS['textured_arm.vert'] = """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;
out vec3 FragPos;
out vec3 Normal;
out vec2 TexCoords;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;
uniform vec2 tex_scale;   // per-face stretch / tiling factor
uniform float tex_angle;  // per-face free rotation in radians
uniform vec2 tex_shift;   // per-face UV offset (in texture repeats)
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalMatrix * aNormal;
    // Surface-inspector transform: rotate the base 0..1 face UVs about their
    // centre, then apply stretch and shift (Radiant-style free controls).
    vec2 uv = aTexCoords - vec2(0.5);
    float s = sin(tex_angle);
    float c = cos(tex_angle);
    uv = vec2(uv.x * c - uv.y * s, uv.x * s + uv.y * c);
    TexCoords = (uv + vec2(0.5)) * tex_scale + tex_shift;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}"""

DEFAULT_SHADERS['textured_arm.frag'] = """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoords;
uniform sampler2D texture_diffuse;
uniform vec4 model_tint;
uniform vec3 emissive_factor;
struct Light { vec3 position; vec3 color; float intensity; float radius; int shadowIndex; };
uniform Light lights[""" + str(MAX_LIGHTS_ARM) + """];
uniform int active_lights;""" + SHADOW_GLSL + FOG_GLSL + """void main() {
    vec4 texColor = texture(texture_diffuse, TexCoords);
    if(texColor.a < 0.1) discard;
    // A model's tint; all zeros (the default) leaves the texture as it is.
    texColor.rgb *= mix(vec3(1.0), model_tint.rgb, model_tint.a);
    vec3 norm = normalize(Normal);
    vec3 result = (vec3(0.12) + uAmbient) * texColor.rgb;
    for(int i = 0; i < active_lights && i < """ + str(MAX_LIGHTS_ARM) + """; i++) {
        vec3 toLight = lights[i].position - FragPos;
        float distSq = dot(toLight, toLight);
        float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            float dist = sqrt(distSq);
            vec3 lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - (dist / lights[i].radius);
            att = att * att;
            float shadow = calcPointShadow(lights[i].shadowIndex, toLight, lights[i].radius, diff);
            result += (1.0 - shadow) * (diff * lights[i].color * lights[i].intensity * att) * texColor.rgb;
        }
    }
    result += emissive_factor;
    FragColor = vec4(applyFog(result, FragPos), texColor.a);
}"""

DEFAULT_SHADERS['fog_arm.frag'] = """#version 330 core
out vec4 FragColor;
in vec3 localPos;
uniform mat4 model;
uniform mat4 inverseModel;
uniform vec3 viewPos;
uniform float density;
uniform vec3 fogColor;
uniform sampler3D noiseTexture;
uniform float noiseScale;
uniform float time;

vec2 intersectBox(vec3 rayOrigin, vec3 rayDir) {
    vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    vec3 tMax = ( 0.5 - rayOrigin) / rayDir;
    vec3 t1 = min(tMin, tMax);
    vec3 t2 = max(tMin, tMax);
    float tNear = max(max(t1.x, t1.y), t1.z);
    float tFar  = min(min(t2.x, t2.y), t2.z);
    return vec2(tNear, tFar);
}

void main() {
    vec3 fragWorldPos   = vec3(model * vec4(localPos, 1.0));
    vec3 rayDirWorld    = normalize(fragWorldPos - viewPos);
    vec3 rayOriginLocal = (inverseModel * vec4(viewPos,       1.0)).xyz;
    vec3 rayDirLocal    = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);
    vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    float tNear = t.x;
    float tFar  = t.y;
    if (tNear >= tFar) discard;
    tNear = max(0.0, tNear);

    int   num_steps = 16;
    float stepSize  = (tFar - tNear) / float(num_steps);
    vec4  accumulatedColor = vec4(0.0);

    for (int i = 0; i < num_steps; ++i) {
        float currentT   = tNear + float(i) * stepSize;
        vec3  samplePos  = rayOriginLocal + rayDirLocal * currentT;
        vec3  noiseCoord = samplePos * noiseScale + vec3(0.0, 0.0, time * 0.1);
        float noiseValue = texture(noiseTexture, noiseCoord).r;
        float stepDensity   = density * noiseValue;
        float transmittance = exp(-stepDensity * stepSize);
        accumulatedColor.rgb += fogColor * (1.0 - transmittance) * (1.0 - accumulatedColor.a);
        accumulatedColor.a   += (1.0 - transmittance);
        if (accumulatedColor.a > 0.95) break;
    }
    accumulatedColor.a = clamp(accumulatedColor.a, 0.0, 1.0);
    FragColor = accumulatedColor;
}"""

# ----- Portal shaders (used by ForwardRenderer for stencil portals) -----
DEFAULT_SHADERS['portal_mask.vert'] = """#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 projection;
uniform mat4 view;
void main() {
    gl_Position = projection * view * vec4(aPos, 1.0);
}"""

DEFAULT_SHADERS['portal_mask.frag'] = """#version 330 core
out vec4 FragColor;
void main() {
    FragColor = vec4(0.0);
}"""

# A fading portal: what was behind the aperture, laid back over the portal's
# view with alpha (1 - fade), so the view's opacity is the portal's fade.
DEFAULT_SHADERS['portal_fade.frag'] = """#version 330 core
out vec4 FragColor;
uniform sampler2D behind;
uniform vec4 viewport_rect;
uniform float alpha;
void main() {
    vec2 uv = (gl_FragCoord.xy - viewport_rect.xy) / viewport_rect.zw;
    FragColor = vec4(texture(behind, uv).rgb, alpha);
}"""

DEFAULT_SHADERS['portal_rim.vert'] = """#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 projection;
uniform mat4 view;
void main() {
    gl_Position = projection * view * vec4(aPos, 1.0);
}"""

DEFAULT_SHADERS['portal_rim.frag'] = """#version 330 core
out vec4 FragColor;
uniform vec4 rim_color;
void main() {
    FragColor = rim_color;
}"""


DEFAULT_SHADERS['decal.vert'] = """#version 330 core
precision highp float;
// A projected decal: its box, drawn as the unit cube. One instance a decal.
layout (location = 0) in vec3 aPos;
layout (location = 3) in vec4 iModel0;
layout (location = 4) in vec4 iModel1;
layout (location = 5) in vec4 iModel2;
layout (location = 6) in vec4 iModel3;
layout (location = 7) in vec4 iParams;      // variant, opacity, kind, flags
// The box's inverse, worked out once on the CPU when the row was made
// (DecalTable), not for every vertex of every frame.
layout (location = 8) in vec4 iInverse0;
layout (location = 9) in vec4 iInverse1;
layout (location = 10) in vec4 iInverse2;
layout (location = 11) in vec4 iInverse3;

uniform mat4 projection;
uniform mat4 view;

flat out mat4 WorldToBox;
flat out vec4 Params;

void main() {
    mat4 model = mat4(iModel0, iModel1, iModel2, iModel3);
    WorldToBox = mat4(iInverse0, iInverse1, iInverse2, iInverse3);
    Params = iParams;
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}"""

DEFAULT_SHADERS['decal.frag'] = """#version 330 core
precision highp float;
// The surface under this pixel -- whatever was drawn there, read back from
// the depth copy -- is put in the decal box's own space. Inside the box it
// takes the decal's texture; outside, nothing. So one box paints a wall,
// the floor below it and the corner between, without knowing either.
//
// Kinds (Params.z): 0/1 blood on a wall/floor (a variant within that kind's
// images), 2 a placed image, 3 a placed wet patch (the image is a mask of
// where the surface is wet). The wet rows are drawn by a second draw of the
// same pass (wetPass 1), over a copy of the frame so far, darkening the
// surface and reflecting the scene in it.
out vec4 FragColor;

flat in mat4 WorldToBox;
flat in vec4 Params;

uniform highp sampler2D sceneDepth;
uniform mediump sampler2DArray decalTextures;
// Placed images: each sits unstretched in its layer of their own array, from
// the corner, filling this much of it (useLayerScale 1 while drawing them).
uniform vec2 imageLayerScale[64];
uniform int useLayerScale;
uniform vec4 decalRanges;       // first layer and count: wall images, floor images
uniform mat4 invViewProjection;
uniform vec4 viewport;          // x, y, width, height of the depth copy
uniform vec3 viewPos;
// The wet pass: the frame so far, and what the reflection march needs.
uniform int wetPass;
uniform int reflectionsOn;      // 'reflections 0' turns every one off
uniform float decalFadeEnd;     // 'decalfade': no reflection from here on
uniform sampler2D sceneColor;
uniform highp mat4 view;
uniform highp mat4 projection;
uniform highp mat4 invProjection;
""" + SSR_GLSL + """
// A wet surface's reflection of the hit at *uv*, *travelled* view units up
// the ray from *originView*: glossy, not a mirror. A cone of half-angle
// atan(coneTan) widens along the ray, so the reflection is sharp where the
// reflected thing meets the surface and softer the further away it is --
// read from the frame copy's mip chain at the cone's width on screen -- and
// smeared upright, as light on a wet floor is.
vec3 glossyReflection(highp vec2 uv, highp float travelled,
                      highp vec3 originView, highp vec3 dirView, float coneTan) {
    highp vec3 hit = originView + dirView * travelled;
    highp float height = float(textureSize(sceneColor, 0).y);
    highp float radiusPx = travelled * coneTan * projection[1][1] * 0.5 * height
                         / max(-hit.z, 1.0);
    float lod = clamp(log2(max(radiusPx, 1.0)), 0.0, 7.0);
    highp vec2 smear = vec2(0.0, radiusPx * 1.2 / height);
    return (textureLod(sceneColor, uv, lod).rgb * 2.0
            + textureLod(sceneColor, clamp(uv + smear, 0.0, 1.0), lod).rgb
            + textureLod(sceneColor, clamp(uv - smear, 0.0, 1.0), lod).rgb) * 0.25;
}

const float BLOOD_STRENGTH = 2.6;
const float IMAGE_STRENGTH = 2.0;   // modulate 2x: mid grey leaves it as it is

highp vec3 hash3(highp vec3 p) {
    p = fract(p * vec3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}

void main() {
    bool wetRow = Params.z > 2.5;
    // Flag 8: an emissive decal. Its own draw (wetPass 2), painted as it is.
    bool glow = !wetRow && Params.w > 7.5;
    if ((wetRow ? 1 : (glow ? 2 : 0)) != wetPass) discard;   // another draw's rows
    vec2 uv = (gl_FragCoord.xy - viewport.xy) / viewport.zw;
    float depth = texture(sceneDepth, uv).r;
    if (depth >= 0.99999) discard;                      // sky: no surface
    vec4 clip = vec4(uv * 2.0 - 1.0, depth * 2.0 - 1.0, 1.0);
    vec4 world = invViewProjection * clip;
    world /= world.w;
    vec3 local = (WorldToBox * world).xyz;              // -0.5..0.5 inside
    if (any(greaterThan(abs(local), vec3(0.5)))) discard;

    // The surface's facing, from how the world position changes across the
    // pixel, in the box's space. The box's z is the way the decal was
    // thrown: a surface facing that way (the far side of a thin wall) gets
    // none.
    vec3 normal = normalize(cross(dFdx(world.xyz), dFdy(world.xyz)));
    if (dot(normal, viewPos - world.xyz) < 0.0) normal = -normal;
    vec3 facing = normalize(mat3(WorldToBox) * normal);
    if (facing.z > 0.35) discard;

    // Across a surface square to the throw the texture lies on the box's
    // x and y. On one that turns away -- the floor under a wall, a side
    // wall -- it is unfolded about the box's middle: the distance out from
    // the wall carries on from where the wall left off, so a run that
    // reaches the foot of a wall goes on across the floor and nothing is
    // smeared along the throw.
    vec2 at = local.xy + facing.xy * local.z;
    if (any(greaterThan(abs(at), vec2(0.5)))) discard;
    float layer;
    if (Params.z > 1.5) {
        layer = Params.x;                               // a placed decal's image
    } else {
        vec2 range = Params.z > 0.5 ? decalRanges.zw : decalRanges.xy;
        layer = range.x + mod(Params.x, max(range.y, 1.0));
    }
    // Flags: 1 mirrored, 2 selected by the editor's Decal tool (tinted),
    // 4 a sign's white words (they lighten past the framebuffer's 1; below),
    // 8 emissive (above).
    bool mirrored = mod(Params.w, 2.0) > 0.5;
    bool picked = mod(floor(Params.w * 0.5), 2.0) > 0.5;
    bool lighten = mod(floor(Params.w * 0.25), 2.0) > 0.5;
    // The box's x runs to the left of someone looking along the throw (its
    // up is up, its z into the surface), so the image is read along -x: its
    // left is on the viewer's left, and text reads the right way round.
    float across = mirrored ? at.x : -at.x;
    vec2 st = vec2(across + 0.5, 0.5 - at.y);
    if (useLayerScale == 1) {
        int index = int(layer + 0.5);
        if (index < 64) st *= imageLayerScale[index];
    }
    vec4 texel = texture(decalTextures, vec3(st, layer));
    // A placed decal's tint, less one, rides in the bottom row of its box's
    // inverse -- (0, 0, 0, 1) for any box, and read by nothing above -- so
    // an untinted decal, and blood, multiply by white.
    vec3 tint = vec3(1.0) + vec3(WorldToBox[0].w, WorldToBox[1].w, WorldToBox[2].w);
    const vec3 PICKED = vec3(1.0, 0.55, 0.1);
    // Fade at the box's near and far ends rather than cut.
    float ends = 1.0 - smoothstep(0.38, 0.5, abs(local.z));
    float amount = texel.a * Params.y * ends;
    if (amount <= 0.004) discard;

    if (wetRow) {
        // Wet: where the mask is strongest, standing water -- flat, a glossy
        // reflection, sharp at contact and softening with distance; towards
        // its edges, damp -- a duller, broken-up, blurrier one.
        // Either way the surface darkens, which is most of looking wet. The
        // reflection fades out with distance and past that is not traced.
        float puddle = smoothstep(0.45, 0.9, texel.a);
        vec3 base = texture(sceneColor, uv).rgb;
        vec3 colour = base * mix(0.6, 0.45, puddle) * tint;
        highp vec3 surfaceView = (view * world).xyz;
        // Full strength to two thirds of the fade distance, none from it on.
        float fade = reflectionsOn == 1 && decalFadeEnd > 0.0
            ? 1.0 - smoothstep(decalFadeEnd * 0.6667, decalFadeEnd, length(surfaceView))
            : 0.0;
        if (fade > 0.0) {
            float rough = mix(0.32, 0.015, puddle);
            vec3 n = normalize(normal + (hash3(floor(world.xyz * 4.0)) - 0.5) * rough);
            vec3 nView = normalize(mat3(view) * n);
            vec3 toSurface = normalize(surfaceView);
            float facingCam = clamp(dot(nView, -toSurface), 0.0, 1.0);
            float fresnel = 0.04 + 0.96 * pow(1.0 - facingCam, 5.0);
            float strength = mix(0.3, 0.95, puddle) * mix(0.6, 1.0, fresnel);
            // A longer first stride than the water's: a puddle reflects the
            // crate standing a few hundred units off, not just its own rim.
            highp vec3 dirView = reflect(toSurface, nView);
            highp vec2 hitUV;
            highp float hitS;
            float hitFade;
            if (marchReflection(surfaceView, dirView, max(6.0, -surfaceView.z * 0.06),
                                hitUV, hitS, hitFade)) {
                vec3 glossy = glossyReflection(hitUV, hitS, surfaceView, dirView,
                                               mix(0.30, 0.12, puddle));
                // Far things reflect fainter, as they do on a wet floor.
                float reach = 1.0 - 0.6 * smoothstep(0.0, 900.0, hitS);
                colour = mix(colour, glossy, hitFade * strength * fade * reach);
            }
        }
        if (picked) colour = mix(colour, PICKED, 0.35);
        FragColor = vec4(colour, amount);               // over what is there
        return;
    }
    if (glow) {
        // Emissive: a screen, a lit sign. Painted over the surface in its
        // own colours, whatever light falls there -- the whole face equally
        // bright, in a dark room as in a lit one -- not stained into it.
        vec3 lit = texel.rgb * tint;
        if (picked) lit = mix(lit, PICKED, 0.5);
        FragColor = vec4(lit, amount);                  // over what is there
        return;
    }
    // Stained, not painted: the blend is dst * (src.rgb + 1 - src.a), so
    // the surface keeps its own light and shadow -- blood in a dark room is
    // dark -- while the colour, pushed past 1, stays red on a grey wall
    // instead of going to black. A placed image modulates 2x: grey leaves
    // the surface alone, darker parts darken it, lighter parts lighten it.
    float strength = Params.z > 1.5 ? IMAGE_STRENGTH : BLOOD_STRENGTH;
    vec3 stain = picked ? mix(texel.rgb * tint, PICKED, 0.5) : texel.rgb * tint;
    vec3 colour = stain * (amount * strength);
    float over = max(colour.r, max(colour.g, colour.b)) - 1.0;
    if (lighten && !picked && over > 0.0) {
        // A sign's white words: the framebuffer stops src.rgb at 1, so the
        // part past 1 goes in alpha -- dst * (rgb + 1 - a) is unchanged, up
        // to twice the surface's own brightness, its light still kept.
        FragColor = vec4(max(colour - over, 0.0), amount - over);
        return;
    }
    FragColor = vec4(colour, amount);
}"""


def _terrain_indexed_sources():
    """The heightfield terrain program as it is drawn: ``terrain_indexed.vert``
    and ``terrain_flat.frag``, derived from ``terrain.vert``/``terrain.frag``.

    ``terrain.vert`` draws a chunk as six unshared vertices a quad, and works
    out a triangle's flat normal and colour at each of its three vertices.
    Here the two are ``flat`` outputs, taken from the triangle's provoking
    vertex (its last: GL's default convention, which nothing in Fio changes),
    and the chunk is drawn indexed (``engine.terrain.heightfield_indices``)
    over two layers of the grid's points:

    * layer 0, ``id = i * (res + 1) + k``: grid point (i, k), carrying the
      face values of the first triangle of quad (i, k);
    * layer 1, ``id = (res + 1)^2 + i * (res + 1) + k``: the same point,
      carrying those of the second triangle of quad (i - 1, k - 1).

    So ``2 (res + 1)^2`` vertices are shaded instead of ``6 res^2`` (4,802
    against 13,824 at res 48). Every value that reaches a fragment comes from
    the same expressions on the same operands as in ``terrain.vert``, which
    stays as the reference the parity tests capture vertex by vertex;
    ``terrain.frag`` (smooth inputs) still serves the block-terrace mesh.
    """
    vert = DEFAULT_SHADERS['terrain.vert']
    head, marker, _ = vert.partition('void main() {')
    assert marker, 'terrain.vert: main() not found'
    for name in ('Normal', 'VertexColor'):
        old = 'out mediump vec3 %s;' % name
        assert old in head, name
        head = head.replace(old, 'flat ' + old)
    main = """void main() {
    int res = uChunkI.x;
    int side = res + 1;
    int points = side * side;
    bool second = gl_VertexID >= points;
    int g = second ? gl_VertexID - points : gl_VertexID;
    int i = g / side;
    int k = g - i * side;
    ivec2 me = ivec2(i, k);

    // The triangle this vertex provokes, with terrain.vert's corners a, b, c:
    // the first of quad (i, k), or the second of quad (i - 1, k - 1).
    int ix = second ? i - 1 : i;
    int iz = second ? k - 1 : k;
    ivec2 a = second ? ivec2(ix + 1, iz)     : ivec2(ix, iz);
    ivec2 b = second ? ivec2(ix + 1, iz + 1) : ivec2(ix + 1, iz);
    ivec2 c = ivec2(ix, iz + 1);

    vec3 pa = gridPoint(a);
    vec3 pb = gridPoint(b);
    vec3 pc = gridPoint(c);
    vec3 p  = second ? pb : pa;

    // Flat face normal: cross(v1 - v0, v2 - v0) / |.|, as stored.
    vec3 n = cross(pb - pa, pc - pa);
    float nlen = sqrt(dot(n, n));
    Normal = nlen == 0.0 ? n : n / nlen;

    if (uFlatMode != 0) {
        VertexColor = vec3(0.7);
    } else {
        float meanHeight = (pa.y + pb.y + pc.y) / 3.0;
        float norm = clamp((meanHeight - uHeightRange.x)
                           / max(uHeightRange.y - uHeightRange.x, 1e-3), 0.0, 1.0);
        int seed = second ? ((ix + 1000) * 1000 + iz + 1000) % 100
                          : (ix * 1000 + iz) % 100;
        float variation = (float(seed) / 100.0 - 0.5) * 0.08;
        VertexColor = clamp(gradientColour(norm) + variation, 0.0, 1.0);
    }

    float gx = gradientAlong(me.x, me.y, true);
    float gz = gradientAlong(me.x, me.y, false);
    SmoothNormal = vec3(-gx, 1.0, -gz) / sqrt(gx * gx + 1.0 + gz * gz);

    TexCoords = p.xz / uTiling;
    PaintCoords = vec2(float(me.x), float(me.y)) / float(max(res, 1));
    FragPos = p;
    gl_Position = projection * view * vec4(p, 1.0);
}"""
    frag = DEFAULT_SHADERS['terrain.frag']
    for name in ('Normal', 'VertexColor'):
        old = 'in vec3 %s;' % name
        assert frag.count(old) == 1, name
        frag = frag.replace(old, 'flat in vec3 %s;' % name)
    return head + main, frag


(DEFAULT_SHADERS['terrain_indexed.vert'],
 DEFAULT_SHADERS['terrain_flat.frag']) = _terrain_indexed_sources()


# ==============================================================================
# The terrain's edge: a cliff wall of rock strata
# ==============================================================================
# Where the terrain ends (the edge of the world) its side is drawn as a cut
# through the ground, like a geologist's block diagram: the ground itself at
# the lip, its topsoil with roots, a paler subsoil, then folded sedimentary
# beds -- sandstones, shales, limestone blocks, chalk, the odd coal seam,
# fossils and ore -- over a folded metamorphic band and a crystalline
# basement. Drawn by TerrainGL._draw_skirts, one triangle strip a chunk side,
# from the same height grid the chunk itself is drawn from, so the wall's top
# is exactly the terrain's edge.
#
# Both stages are built on the terrain's own: the vertex shader hands the
# fragment shader terrain.vert's outputs for the rim point above each
# fragment, and the fragment shader runs terrain.frag's material code there
# (textures, layers, biomes, paint, the palette looks), so the top layer is
# always the colour of the ground it lies under.
_SKIRT_VERT_DECLS = """
// The wall: which side of the chunk, its foot, the terrain's rectangle, and
// how far the face leans out per unit of drop. A sheer wall faces away from
// a camera above the ground, so the top-down view would never see it; a
// steep escarpment it can.
uniform int uSide;              // 0: -x, 1: +x, 2: -z, 3: +z
uniform highp float uFloor;     // the wall's foot, world y
uniform highp vec4 uEdge;       // the terrain's min x, max x, min z, max z
uniform float uLean;
out highp vec3 WallPos;
out highp float SurfaceY;
flat out vec3 WallNormal;
out highp float UnderDepth;     // the underside's depth here (the wall: none)
out highp float FootMirror;     // how deep the underside hangs below this foot
"""

_SKIRT_VERT_MAIN = """void main() {
    int res = uChunkI.x;
    int j = gl_VertexID / 2;
    // Top first on the -x and +z sides, foot first on the others, so every
    // strip is counter-clockwise seen from outside (back faces are culled).
    bool flip = uSide == 1 || uSide == 2;
    bool top = ((gl_VertexID & 1) == 0) != flip;
    ivec2 g = uSide == 0 ? ivec2(0, j)
            : uSide == 1 ? ivec2(res, j)
            : uSide == 2 ? ivec2(j, 0)
            :              ivec2(j, res);
    vec3 rim = gridPoint(g);
    highp float h = rim.y;
    highp vec3 p = rim;
    vec2 out2 = uSide == 0 ? vec2(-1.0, 0.0)
              : uSide == 1 ? vec2( 1.0, 0.0)
              : uSide == 2 ? vec2(0.0, -1.0)
              :              vec2(0.0,  1.0);
    if (!top) {
        highp float foot = min(uFloor, h - 1.0);
        highp float reach = (h - foot) * uLean;
        // At the world's corners the foot is mitred, so the two faces meet
        // along the diagonal with no gap between them.
        highp float eps = uChunkX.z * 0.01;
        vec2 along = vec2(abs(out2.y), abs(out2.x));
        highp float a = dot(p.xz, along);
        highp float lo = uSide < 2 ? uEdge.z : uEdge.x;
        highp float hi = uSide < 2 ? uEdge.w : uEdge.y;
        float mitre = a <= lo + eps ? -1.0 : (a >= hi - eps ? 1.0 : 0.0);
        p.xz += (out2 + along * mitre) * reach;
        p.y = foot;
    }
    WallNormal = normalize(vec3(out2.x, uLean, out2.y));
    UnderDepth = 1.0e6;
    FootMirror = mirrorDepth(rim.xz, h);
    SurfaceY = h;
    WallPos = p;

    // The ground at the rim, as terrain.vert hands it to terrain.frag --
    // as open, flat ground: the rim of a world's edge is often steep, and
    // the material would turn it to bare rock, where the top layer is to be
    // the colour of the land itself.
    SmoothNormal = vec3(0.0, 1.0, 0.0);
    Normal = SmoothNormal;
    if (uFlatMode != 0) {
        VertexColor = vec3(0.7);
    } else {
        float norm = clamp((h - uHeightRange.x)
                           / max(uHeightRange.y - uHeightRange.x, 1e-3), 0.0, 1.0);
        VertexColor = gradientColour(norm);
    }
    // Down the face the ground is read as if folded back inward over the
    // land (as far in as the point is below the rim), so its textures, grain
    // and speckles run on down the face rather than streaking straight down
    // it, and every sample stays over the terrain's biome map and paint.
    vec2 inward = -out2 * (h - p.y);
    TexCoords = (rim.xz + inward) / uTiling;
    PaintCoords = (vec2(float(g.x), float(g.y)) + inward / uChunkX.z) / float(max(res, 1));
    FragPos = vec3(rim.x + inward.x, h, rim.z + inward.y);
    gl_Position = projection * view * vec4(p, 1.0);
}
"""

_SKIRT_FRAG_DECLS = """
in highp vec3 WallPos;
in highp float SurfaceY;
flat in vec3 WallNormal;
in highp float UnderDepth;
in highp float FootMirror;
uniform highp float uFloor;      // the wall's foot
uniform highp float uBasement;   // top of the crystalline basement
uniform highp float uMeta;       // top of the folded metamorphic band
uniform highp float uBand;       // a sedimentary bed's mean thickness
uniform highp float uSoil;       // scale of the soil horizons

"""

_SKIRT_STRATA_HELPERS = """// ---- noise --------------------------------------------------------------
float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
vec2 hash22(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.xx + p3.yz) * p3.zy);
}
float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x),
               mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
    float a = 0.5;
    float s = 0.0;
    for (int i = 0; i < 4; ++i) {
        s += a * vnoise(p);
        p = p * 2.03 + 17.1;
        a *= 0.5;
    }
    return s / 0.9375;
}
// Distance to the nearest and second-nearest feature point of a jittered
// grid, and the nearest cell (for blocky crystalline rock).
vec3 voronoi(vec2 p, out vec2 cell) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float d1 = 8.0;
    float d2 = 8.0;
    cell = i;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            vec2 o = vec2(float(x), float(y));
            vec2 r = o + hash22(i + o) * 0.85 + 0.075 - f;
            float d = dot(r, r);
            if (d < d1) { d2 = d1; d1 = d; cell = i + o; }
            else if (d < d2) { d2 = d; }
        }
    }
    return vec3(sqrt(d1), sqrt(d2), 0.0);
}
// 1 inside a line |x| < w, anti-aliased over aa (world units a pixel).
float lineAA(float x, float w, float aa) {
    return 1.0 - smoothstep(w - aa, w + aa, abs(x));
}

// ---- rock ---------------------------------------------------------------
vec3 bedColour(int t) {
    if (t == 0) return vec3(0.62, 0.29, 0.21);   // red sandstone
    if (t == 1) return vec3(0.80, 0.74, 0.60);   // buff limestone
    if (t == 2) return vec3(0.37, 0.51, 0.53);   // teal shale
    if (t == 3) return vec3(0.29, 0.30, 0.33);   // grey mudstone
    if (t == 4) return vec3(0.79, 0.56, 0.49);   // pink siltstone
    if (t == 5) return vec3(0.78, 0.60, 0.36);   // ochre sandstone
    if (t == 6) return vec3(0.52, 0.59, 0.66);   // blue-grey limestone
    return vec3(0.89, 0.86, 0.77);               // chalk
}

// A fossil in the bed, or alpha 0. q is the point relative to the fossil's
// centre, R its size, kind which fossil.
vec4 fossil(vec2 q, float R, float kind, float aa) {
    vec3 bone = vec3(0.92, 0.87, 0.74);
    vec3 dark = vec3(0.30, 0.25, 0.20);
    float r = length(q);
    if (kind < 0.30) {
        // Ammonite: a coiled shell with its whorls and ribs.
        if (r > R) return vec4(0.0);
        float a = atan(q.y, q.x) / 6.2831853;
        float coil = fract(log(r / R + 0.04) * 1.9 - a);
        float ribs = fract(a * 26.0 + r / R * 2.0);
        float rim = 1.0 - smoothstep(R - 1.5 * aa - 0.6, R, r);
        vec3 c = bone * (0.82 + 0.18 * smoothstep(0.0, 0.5, coil));
        c = mix(c, dark, (1.0 - smoothstep(0.0, 0.12, coil)) * 0.8);
        c = mix(c, c * 0.8, step(0.75, ribs) * 0.6);
        c = mix(dark, c, rim);
        return vec4(c, 1.0);
    }
    if (kind < 0.55) {
        // Fish skeleton: spine, ribs and a skull.
        float x = q.x / R;
        float y = q.y / R;
        float spine = lineAA(y, 0.06, aa / R) * step(abs(x + 0.15), 1.05);
        float ribEnv = max(0.0, 0.48 * (1.0 - abs(x + 0.1) / 1.0));
        float ribs = lineAA(fract(x * 4.5) - 0.5, 0.11, aa * 4.5 / R)
                   * step(abs(y), ribEnv) * step(-1.0, x) * step(x, 0.75);
        float skull = 1.0 - smoothstep(0.30, 0.30 + aa / R, length(vec2((x - 1.05) * 0.9, y)));
        float eye = 1.0 - smoothstep(0.07, 0.07 + aa / R, length(vec2(x - 1.12, y - 0.06)));
        float tail = step(x, -1.05) * step(-1.5, x) * step(abs(y), (-1.05 - x) * 0.9 + 0.04);
        float m = max(max(spine, ribs), max(skull, tail));
        if (m <= 0.0) return vec4(0.0);
        return vec4(mix(bone, dark, eye * 0.9), m);
    }
    if (kind < 0.80) {
        // Bivalve: a ribbed fan.
        vec2 s = vec2(q.x, q.y + R * 0.55);
        float sr = length(s);
        float sa = atan(s.x, s.y);
        if (sr > R * 1.15 || abs(sa) > 1.0) return vec4(0.0);
        float ribs = 0.5 + 0.5 * cos(sa * 22.0);
        float edge = 1.0 - smoothstep(R * 1.15 - 2.0 * aa, R * 1.15, sr);
        vec3 c = bone * (0.78 + 0.22 * ribs);
        return vec4(mix(dark, c, edge), 1.0);
    }
    // Trilobite: a segmented oval.
    vec2 e = q / vec2(R * 0.62, R);
    float er = length(e);
    if (er > 1.0) return vec4(0.0);
    float seg = fract(e.y * 5.5);
    float lobe = abs(abs(e.x) - 0.33);
    vec3 c = bone * 0.86;
    c = mix(c, dark, (1.0 - smoothstep(0.0, 0.18, seg)) * 0.55 * step(e.y, 0.45));
    c = mix(c, dark, lineAA(lobe, 0.03, aa / R) * 0.5);
    c = mix(dark, c, 1.0 - smoothstep(1.0 - 2.0 * aa / R, 1.0, er));
    return vec4(c, 1.0);
}

"""

_SKIRT_STRATA_MAIN = """
    // The underside where it has shrunk to nothing (under the falls): not
    // there at all.
    if (UnderDepth < 1.0) discard;
    vec3 p = WallPos;
    vec2 hp = p.xz;
    // Along the wall: x + z runs continuously round the world's corners.
    float s = p.x + p.z;
    float aa = max(max(fwidth(s), fwidth(p.y)), 1e-3);   // world units a pixel
    // Fine detail fades out where a pixel covers more than it can show.
    float detail = 1.0 - smoothstep(1.2, 4.0, aa);
    float depth = SurfaceY - p.y;
    float grain = vnoise(vec2(s, p.y) * 0.55) - 0.5;
    float grain2 = vnoise(vec2(s, p.y) * 2.3 + 7.0) - 0.5;
    vec3 col;

    // ---- soil horizons, following the surface --------------------------
    // The top layer is the ground's own colour: the lip exactly, the rest of
    // the topsoil a little darker with depth.
    float topsoil = (15.0 + 8.0 * vnoise(vec2(s / 45.0, 1.3))) * uSoil;
    float lip = topsoil * (0.3 + 0.15 * vnoise(vec2(s * 0.35, 3.0)));
    float subsoil = topsoil + (13.0 + 11.0 * vnoise(vec2(s / 140.0, 7.7))) * uSoil;
    // Bedrock reaches up into the subsoil in weathered, broken blocks.
    vec2 rubbleCell;
    vec3 rv = voronoi(vec2(s, p.y) / (6.0 * uSoil), rubbleCell);
    float rockhead = subsoil + (vnoise(vec2(s / 60.0, 2.2)) - 0.5) * 10.0 * uSoil;
    float rubble = step(hash12(rubbleCell), 0.55) * step(rv.x, 0.42)
                 * smoothstep(rockhead - 10.0 * uSoil, rockhead, depth);

    // ---- bedrock --------------------------------------------------------
    // Beds were laid flat and have since been folded: a bed's level is the
    // height minus a broad and a tighter fold.
    float fold = (fbm(hp / 1600.0) - 0.5) * min(uBand * 10.0, 520.0)
               + (fbm(hp / 420.0 + 5.3) - 0.5) * min(uBand * 2.4, 110.0);
    float g = p.y - fold;
    float u = g / uBand;
    u += 1.25 * vnoise(vec2(u * 0.2, 3.7)) + 0.3 * vnoise(vec2(u * 0.9, 8.1));   // uneven beds
    float id = floor(u);
    float f = fract(u);
    float uaa = max(fwidth(u), 1e-4);
    int kind = int(hash11(id * 1.37 + 11.0) * 8.0);
    vec3 rock = bedColour(kind) * (0.88 + 0.22 * hash11(id * 7.13 + 2.0));
    float bedPx = uBand;                                // a bed's thickness in units
    // Each kind's own texture.
    if (kind == 0 || kind == 5) {
        // Sandstone: grain and slanted cross-bedding.
        float dir = hash11(id * 3.1) < 0.5 ? 1.0 : -1.0;
        float cross = fract((g + dir * s * 0.45) / (bedPx * 0.16));
        rock *= 1.0 - 0.10 * lineAA(cross - 0.5, 0.06, uaa * 6.0) * detail;
        rock *= 1.0 + 0.16 * grain * detail;
    } else if (kind == 1 || kind == 6) {
        // Limestone: blocks with mortar-like joints, two courses a bed.
        float rowv = f * 2.0;
        float row = floor(rowv);
        float jx = s / (bedPx * 1.25) + hash11(id * 5.0 + row * 1.7) * 7.0;
        float vj = 1.0 - smoothstep(0.0, max(fwidth(jx) * 1.5, 0.015), min(fract(jx), 1.0 - fract(jx)));
        float hj = 1.0 - smoothstep(0.0, max(fwidth(rowv) * 1.5, 0.02), min(fract(rowv), 1.0 - fract(rowv)));
        float block = hash12(vec2(floor(jx), id * 2.0 + row));
        rock *= 0.92 + 0.14 * block;
        rock *= 1.0 - 0.38 * max(vj, hj) * detail;
        rock *= 1.0 + 0.10 * grain2 * detail;
    } else if (kind == 2 || kind == 3) {
        // Shale and mudstone: tight laminations.
        float lam = sin(g * 1.9 + vnoise(vec2(s * 0.02, g * 0.1)) * 4.0);
        rock *= 1.0 + 0.09 * lam * detail;
        rock *= 1.0 + 0.08 * grain * detail;
    } else if (kind == 4) {
        float lam = sin(g * 0.9 + grain * 2.0);
        rock *= 1.0 + 0.07 * lam * detail;
        rock *= 1.0 + 0.10 * grain2 * detail;
    } else {
        // Chalk with a line of dark flint nodules.
        vec2 fc = vec2(s / 9.0, id);
        float fh = hash12(floor(fc));
        float fx = fract(fc.x) - 0.5;
        float fy = (f - (0.3 + 0.4 * hash11(id * 9.0))) * bedPx / 9.0;
        float nodule = step(fh, 0.45) * (1.0 - smoothstep(0.18, 0.18 + aa / 9.0, length(vec2(fx, fy * 1.6))));
        rock = mix(rock * (1.0 + 0.06 * grain), vec3(0.20, 0.21, 0.24), nodule * detail);
    }
    // A coal seam at the foot of some beds.
    float coal = step(0.86, hash11(id * 3.33 + 1.0)) * (1.0 - smoothstep(0.10, 0.10 + uaa, f));
    rock = mix(rock, vec3(0.08, 0.08, 0.09) + 0.05 * grain2, coal);
    // The contact between beds: a fine dark parting.
    float contact = 1.0 - smoothstep(0.0, uaa * 1.5, min(f, 1.0 - f) - 0.008);
    rock = mix(rock, rock * 0.5, contact * 0.7);
    // Weathering: blotchy stains, a little longer than they are wide.
    rock *= 1.0 - 0.07 * smoothstep(0.55, 0.9, fbm(vec2(s / 26.0, p.y / 48.0) + 2.0));

    // Fossils, in the sedimentary beds only.
    float C = max(30.0, uBand * 0.85);
    vec2 fpos = vec2(s, g);
    vec2 cell = floor(fpos / C);
    if (hash12(cell + 0.5) < 0.07 && detail > 0.0) {
        vec2 jit = hash22(cell);
        vec2 centre = (cell + 0.25 + 0.5 * jit) * C;
        float R = C * (0.20 + 0.12 * hash12(cell + 3.7));
        vec2 q = fpos - centre;
        float ang = (hash12(cell + 9.1) - 0.5) * 1.2;
        q = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * q;
        vec4 fo = fossil(q, R, hash12(cell + 1.9), aa);
        rock = mix(rock, fo.rgb, fo.a * detail);
    }
    // Ore: rare gold nuggets.
    float O = max(22.0, uBand * 0.65);
    vec2 ocell = floor(vec2(s, g) / O);
    if (hash12(ocell + 4.2) < 0.02) {
        vec2 oc = (ocell + 0.3 + 0.4 * hash22(ocell + 2.0)) * O;
        vec2 q = vec2(s, g) - oc;
        float a = hash12(ocell) * 3.14159;
        vec2 rq = mat2(cos(a), -sin(a), sin(a), cos(a)) * q;
        float r = (2.2 + 1.6 * hash12(ocell + 8.0)) * O / 22.0;
        float d = abs(rq.x) * 0.9 + abs(rq.y) * 1.35 + 0.35 * abs(rq.x + rq.y);
        float nug = 1.0 - smoothstep(r - aa, r + aa, d);
        float rim = 1.0 - smoothstep(r * 0.7 - aa, r * 0.7 + aa, d);
        vec3 gold = mix(vec3(0.55, 0.38, 0.08), vec3(0.98, 0.78, 0.22) * (0.9 + 0.2 * grain2), rim);
        rock = mix(rock, gold, nug);
    }
    // ---- folded metamorphic band and the crystalline basement ---------
    float baseTop = uBasement + (fbm(vec2(s / 500.0, 9.0)) - 0.5) * 90.0;
    float metaTop = uMeta + (fbm(vec2(s / 650.0, 5.0)) - 0.5) * 110.0;
    if (p.y < metaTop) {
        // Schist: tight, swirling folds in reds and browns.
        float sw = p.y * 0.22 + (fbm(vec2(s, p.y) / 70.0) - 0.5) * 9.0
                 + (fbm(vec2(s, p.y) / 22.0 + 3.0) - 0.5) * 2.5;
        float band = 0.5 + 0.5 * sin(sw);
        vec3 schist = mix(vec3(0.44, 0.20, 0.16), vec3(0.62, 0.32, 0.24), band);
        schist = mix(schist, vec3(0.30, 0.14, 0.11), lineAA(fract(sw / 6.2831853) - 0.5, 0.035, fwidth(sw) / 6.2831853) * detail * 0.7);
        schist *= 1.0 + 0.10 * grain2 * detail;
        float unconf = 1.0 - smoothstep(0.0, aa * 1.5, abs(p.y - metaTop) - 0.6);
        rock = mix(schist, vec3(0.12, 0.10, 0.09), unconf * 0.85);
    }
    if (p.y < baseTop) {
        // Granite / basalt: dark angular blocks with lighter fractures.
        vec2 bc;
        vec2 warp = vec2(fbm(vec2(s, p.y) / 90.0), fbm(vec2(s, p.y) / 90.0 + 4.0)) - 0.5;
        vec3 v = voronoi(vec2(s, p.y) / 26.0 + warp * 1.4, bc);
        float tone = hash12(bc);
        vec3 crystal = mix(vec3(0.17, 0.18, 0.21), vec3(0.34, 0.35, 0.38), tone);
        crystal *= 0.85 + 0.3 * smoothstep(0.0, 0.6, v.x);
        float crack = 1.0 - smoothstep(0.0, max(aa / 26.0 * 1.5, 0.015), v.y - v.x - 0.03);
        crystal = mix(crystal, vec3(0.07, 0.07, 0.08), crack * 0.9);
        crystal *= 1.0 + 0.12 * grain2 * detail;
        // Pale feldspar and quartz grains.
        crystal = mix(crystal, vec3(0.62, 0.60, 0.58), step(0.93, hash12(floor(vec2(s, p.y) * 0.8))) * 0.5 * detail);
        float unconf = 1.0 - smoothstep(0.0, aa * 1.5, abs(p.y - baseTop) - 0.8);
        rock = mix(crystal, vec3(0.06, 0.06, 0.07), unconf * 0.9);
    }

    // ---- soil over rock -------------------------------------------------
    if (depth < rockhead && rubble < 0.5) {
        float t = clamp((depth - topsoil) / max(subsoil - topsoil, 1e-3), 0.0, 1.0);
        vec3 sub = mix(vec3(0.60, 0.44, 0.27), vec3(0.74, 0.60, 0.40), t);
        // Pebbles in the subsoil.
        vec2 pc;
        vec3 pv = voronoi(vec2(s, p.y) / (3.2 * uSoil), pc);
        float pebble = step(hash12(pc + 1.3), 0.22) * (1.0 - smoothstep(0.26, 0.26 + aa / (3.2 * uSoil), pv.x));
        sub = mix(sub, vec3(0.55, 0.52, 0.48) * (0.8 + 0.4 * hash12(pc)), pebble * detail);
        sub *= 1.0 + 0.16 * grain * detail;
        sub = mix(sub, ground * 0.8, 0.2);
        // The topsoil is the ground's own colour, a little darker with depth.
        vec3 top = ground * mix(1.0, 0.86, clamp(depth / max(topsoil, 1e-3), 0.0, 1.0))
                 * (1.0 + 0.08 * grain2 * detail);
        float soilEdge = smoothstep(-1.2 * uSoil - aa, 1.2 * uSoil + aa,
                                    depth - topsoil + (vnoise(vec2(s * 0.3, 5.0)) - 0.5) * 3.0 * uSoil);
        col = mix(top, sub, soilEdge);
        // Roots hanging down from the surface.
        float cw = 9.0 * uSoil;
        float ci = floor(s / cw);
        for (int k = -1; k <= 1; ++k) {
            float c = ci + float(k);
            if (hash11(c * 1.7 + 0.3) > 0.6) continue;
            float len = topsoil * (0.8 + 1.8 * hash11(c + 3.1));
            float along = clamp(depth / len, 0.0, 1.0);
            float rx = (c + 0.2 + 0.6 * hash11(c)) * cw
                     + sin(depth * 0.45 / uSoil + c) * 1.4 * uSoil * along
                     + (hash11(c + 5.0) - 0.5) * depth * 0.6;
            float w = 0.55 * uSoil * (1.0 - along) + 0.1;
            float root = lineAA(s - rx, w, aa) * step(depth, len);
            col = mix(col, vec3(0.13, 0.09, 0.06), root * detail);
        }
        // The rock head: a dark line where the soil meets the rock.
        col = mix(col, col * 0.55, (1.0 - smoothstep(0.0, aa * 1.5, abs(depth - rockhead) - 0.25)) * 0.7);
    } else {
        col = rock;
    }
    // The lip is the ground itself, coloured exactly as the terrain is at
    // the rim (terrain.frag's material, run on the rim point).
    float onLip = 1.0 - smoothstep(lip - aa, lip + aa, depth);
    col = mix(col, ground, onLip);
    // A dark foot, so the block reads as a cut -- unless the wall goes on
    // below it, mirrored (terrain_under.vert), where there is no foot.
    float footDark = 1.0 - smoothstep(0.0, 40.0, FootMirror);
    col *= mix(mix(0.35, 1.0, smoothstep(uFloor, uFloor + 14.0, p.y)), 1.0, 1.0 - footDark);

    // ---- light, as terrain.frag lights the ground -----------------------
    // The top layer is lit as open ground is, so it is the land's colour on
    // screen too; below it the light turns to the face.
    float seam = 1.0 - smoothstep(topsoil, topsoil + 0.6 * (subsoil - topsoil), depth);
    vec3 norm = normalize(mix(normalize(WallNormal), vec3(0.0, 1.0, 0.0), seam));
    vec3 skyColor = vec3(0.6, 0.75, 0.9);
    vec3 groundColor = vec3(0.3, 0.25, 0.2);
    float skyFactor = (norm.y + 1.0) * 0.5;
    vec3 result = (mix(groundColor, skyColor, skyFactor) * 0.3 + uAmbient) * col;
    vec3 sunDir = normalize(vec3(0.4, 0.7, 0.3));
    float sunDiff = max(dot(norm, sunDir), 0.0);
    float wrappedDiff = (sunDiff + 0.3) / 1.3;
    if (uLightSteps > 0) {
        float steps = float(uLightSteps);
        wrappedDiff = floor(wrappedDiff * steps + 0.5) / steps;
    }
    result += wrappedDiff * vec3(1.0, 0.95, 0.85) * 0.7 * col;
    vec3 fillDir = normalize(vec3(-0.3, 0.2, -0.4));
    result += max(dot(norm, fillDir), 0.0) * 0.2 * skyColor * col;
    float gray = dot(result, vec3(0.299, 0.587, 0.114));
    result = mix(vec3(gray), result, 1.15);
    result = applyFog(result, WallPos);
    if (uDither > 0) {
        float levels = float(uDither);
        result = floor(clamp(result, 0.0, 1.0) * levels + bayer4(gl_FragCoord.xy)) / levels;
    }
    FragColor = vec4(result, 1.0);
"""


# Where the underside hangs (shared by terrain_under.vert and, for the
# wall's foot, terrain_skirt.vert): only round the shores where land meets
# a fall at the world's edge, fading out along the edge either way.
_UNDER_COMMON = """
uniform highp float uReach;     // how far in the reflected land rises to the foot
uniform highp float uShore;     // over how much height above a fall it grows back
uniform highp float uShoreRun;  // how far along the edge from a shore it reaches
uniform int uFallCount;
uniform highp vec4 uFall[8];    // the falls: side, along lo, along hi, top
uniform int uShoreCount;
uniform highp vec4 uShorePt[8]; // the shores: side, along, -, -

// How far in from the world's nearest edge a point is.
highp float inFromEdge(vec2 xz) {
    return min(min(xz.x - uEdge.x, uEdge.y - xz.x), min(xz.y - uEdge.z, uEdge.w - xz.y));
}

highp float inFromSide(vec2 xz, int side) {
    return side == 0 ? xz.x - uEdge.x : side == 1 ? uEdge.y - xz.x
         : side == 2 ? xz.y - uEdge.z : uEdge.w - xz.y;
}

// 1 under land, falling to 0 where a fall pours over the edge: the ground
// comes down to the water's surface (within uShore above it) along the
// stretch of edge the fall covers.
float overLand(vec2 xz, highp float h) {
    float f = 1.0;
    for (int i = 0; i < uFallCount && i < 8; ++i) {
        int side = int(uFall[i].x + 0.5);
        highp float a = side < 2 ? xz.y : xz.x;
        if (a < uFall[i].y || a > uFall[i].z) continue;
        f = min(f, smoothstep(uFall[i].w, uFall[i].w + uShore, h));
    }
    return f;
}

// 1 by a shore where land meets a fall, fading to 0 along the edge.
float nearShore(vec2 xz) {
    float w = 0.0;
    for (int i = 0; i < uShoreCount && i < 8; ++i) {
        int side = int(uShorePt[i].x + 0.5);
        if (inFromSide(xz, side) > uReach) continue;
        highp float a = side < 2 ? xz.y : xz.x;
        w = max(w, 1.0 - smoothstep(0.35 * uShoreRun, uShoreRun, abs(a - uShorePt[i].y)));
    }
    return w;
}

// How far below the foot the reflection reaches under a point of the land.
highp float mirrorDepth(vec2 xz, highp float h) {
    if (uShoreCount == 0) return 0.0;
    highp float taper = 1.0 - smoothstep(0.0, uReach, inFromEdge(xz));
    return max(h - uFloor, 0.0) * taper * overLand(xz, h) * nearShore(xz);
}
"""

def _terrain_skirt_sources():
    """``terrain_skirt.vert`` and ``terrain_skirt.frag``: the terrain's
    shaders with the wall added (see above)."""
    head, marker, _ = DEFAULT_SHADERS['terrain.vert'].partition('void main() {')
    assert marker, 'terrain.vert: main() not found'
    vert = head + _SKIRT_VERT_DECLS + _UNDER_COMMON + _SKIRT_VERT_MAIN
    fhead, marker, fbody = DEFAULT_SHADERS['terrain.frag'].partition('void main() {')
    assert marker, 'terrain.frag: main() not found'
    material, marker, _ = fbody.partition('    // ---- Lighting')
    assert marker, 'terrain.frag: the lighting section was not found'
    frag = (fhead + _SKIRT_FRAG_DECLS + _SKIRT_STRATA_HELPERS + 'void main() {\n'
            + '    // The ground at the rim: terrain.frag\'s material, unlit.\n'
            + '    vec3 ground;\n    {' + material + '        ground = texColor;\n    }\n'
            + _SKIRT_STRATA_MAIN + '}\n')
    return vert, frag


(DEFAULT_SHADERS['terrain_skirt.vert'],
 DEFAULT_SHADERS['terrain_skirt.frag']) = _terrain_skirt_sources()


# ==============================================================================
# The world's underside: the edge land mirrored below the strata wall
# ==============================================================================
# Below the strata wall's foot the land goes on, upside down: the wall
# reflected in its foot (leaning back in as the wall leans out), then the
# edge land itself reflected under that, rising back to the foot further in,
# so the world's rim hangs over the void in rocky outcrops that are the
# mountains above turned over. Only under land: where a fall pours over the
# edge (a water brush reaching it, over ground below its surface) the
# reflection shrinks away to nothing as the land at the edge comes down to
# the water, and none hangs behind the falls.
#
# Drawn by TerrainGL._draw_underside with terrain_skirt.frag, the wall's own
# shading: the reflected wall shows the wall's own beds, mirrored in its
# foot (the two share their foot vertices and their rock there, so they meet
# without a line), and the reflected land the bedrock it would have cut
# through. uPart 0 draws a side's reflected wall (a strip, as the wall is),
# 1 a chunk's reflected land (6 vertices a quad, no buffers).
_UNDER_VERT_DECLS = """
uniform int uPart;              // 0: the reflected wall; 1: the reflected land
uniform int uSide;              // 0: -x, 1: +x, 2: -z, 3: +z
uniform highp float uFloor;     // the wall's foot, world y
uniform highp vec4 uEdge;       // the terrain's min x, max x, min z, max z
uniform float uLean;
out highp vec3 WallPos;
out highp float SurfaceY;
flat out vec3 WallNormal;
out highp float UnderDepth;
out highp float FootMirror;
"""

_UNDER_VERT_MAIN = """void main() {
    int res = uChunkI.x;
    highp vec3 p;
    highp vec3 mat;
    highp vec3 rim;
    ivec2 g;
    if (uPart == 0) {
        int j = gl_VertexID / 2;
        bool atFoot = (gl_VertexID & 1) == 0;
        g = uSide == 0 ? ivec2(0, j)
          : uSide == 1 ? ivec2(res, j)
          : uSide == 2 ? ivec2(j, 0)
          :              ivec2(j, res);
        rim = gridPoint(g);
        highp float h = rim.y;
        vec2 out2 = uSide == 0 ? vec2(-1.0, 0.0)
                  : uSide == 1 ? vec2( 1.0, 0.0)
                  : uSide == 2 ? vec2(0.0, -1.0)
                  :              vec2(0.0,  1.0);
        vec2 along = vec2(abs(out2.y), abs(out2.x));
        highp float foot = min(uFloor, h - 1.0);
        // Mitred at the world's corners, exactly as the wall's foot is.
        highp float eps = uChunkX.z * 0.01;
        highp float a = dot(rim.xz, along);
        highp float lo = uSide < 2 ? uEdge.z : uEdge.x;
        highp float hi = uSide < 2 ? uEdge.w : uEdge.y;
        float mitre = a <= lo + eps ? -1.0 : (a >= hi - eps ? 1.0 : 0.0);
        vec2 outward = out2 + along * mitre;
        highp float D = mirrorDepth(rim.xz, h);
        UnderDepth = D;
        // The wall at height foot + D lies this far out; its reflection at
        // foot - D the same, so the reflected wall leans back in.
        highp float upY = atFoot ? foot : foot + D;
        vec2 xz = rim.xz + outward * (h - upY) * uLean;
        p = vec3(xz.x, atFoot ? foot : foot - D, xz.y);
        mat = vec3(xz.x, upY, xz.y);
        WallNormal = normalize(vec3(out2.x, -uLean, out2.y));
    } else {
        int quad = gl_VertexID / 6;
        int corner = gl_VertexID - quad * 6;
        int col = quad % res;
        int row = quad / res;
        // (0,0) (1,0) (0,1)  (1,0) (1,1) (0,1)
        int dc = (corner == 1 || corner == 3 || corner == 4) ? 1 : 0;
        int dr = (corner == 2 || corner == 4 || corner == 5) ? 1 : 0;
        g = ivec2(col + dc, row + dr);
        rim = gridPoint(g);
        highp float D = mirrorDepth(rim.xz, rim.y);
        UnderDepth = D;
        p = vec3(rim.x, uFloor - D, rim.z);
        mat = vec3(rim.x, uFloor + D, rim.z);
        // Facing down: the reflected surface's slope, from the grid's
        // neighbours (the ring round the chunk supplies those at its edge).
        highp float step2 = 2.0 * uChunkX.z;
        vec3 px = gridPoint(g + ivec2(1, 0));
        vec3 nx = gridPoint(g - ivec2(1, 0));
        vec3 pz = gridPoint(g + ivec2(0, 1));
        vec3 nz = gridPoint(g - ivec2(0, 1));
        highp float fx = (mirrorDepth(nx.xz, nx.y) - mirrorDepth(px.xz, px.y)) / step2;
        highp float fz = (mirrorDepth(nz.xz, nz.y) - mirrorDepth(pz.xz, pz.y)) / step2;
        WallNormal = normalize(vec3(fx, -1.0, fz));
    }
    // Shaded as the wall's bedrock, never its soil: the surface is taken
    // to lie well above every point of the reflection, which has no foot.
    SurfaceY = rim.y + 400.0;
    FootMirror = 1.0e6;
    WallPos = mat;
    SmoothNormal = vec3(0.0, 1.0, 0.0);
    Normal = SmoothNormal;
    if (uFlatMode != 0) {
        VertexColor = vec3(0.7);
    } else {
        float norm = clamp((rim.y - uHeightRange.x)
                           / max(uHeightRange.y - uHeightRange.x, 1e-3), 0.0, 1.0);
        VertexColor = gradientColour(norm);
    }
    TexCoords = rim.xz / uTiling;
    PaintCoords = vec2(float(g.x), float(g.y)) / float(max(res, 1));
    FragPos = rim;
    gl_Position = projection * view * vec4(p, 1.0);
}
"""


def _terrain_under_source():
    """``terrain_under.vert``: terrain.vert's head with the reflection
    added (see above); drawn with terrain_skirt.frag."""
    head, marker, _ = DEFAULT_SHADERS['terrain.vert'].partition('void main() {')
    assert marker, 'terrain.vert: main() not found'
    return head + _UNDER_VERT_DECLS + _UNDER_COMMON + _UNDER_VERT_MAIN


DEFAULT_SHADERS['terrain_under.vert'] = _terrain_under_source()


# ==============================================================================
# Waterfalls off the edge of the world
# ==============================================================================
# Where a body of water reaches the terrain's edge it spills over it, and the
# sea and its fall are one sheet of water: a "tongue" lying on the surface
# fades in from nothing over the last stretch before the brink, quickening
# towards it; at the brink it bends over (the surface was pinned flat at the
# brush's edge, water.vert, so the two meet exactly), arcs out, hugs the
# strata wall where the wall leans out past it, and falls on past the wall's
# foot without end, into haze. One grid of quads a chunk side, drawn by
# TerrainGL.draw_falls after the water, along the stretches of the edge a
# water brush covers and only where the ground at the edge lies below that
# water's surface (there the fall thins to ribbons and stops).
#
# The pattern runs on a perimeter coordinate that is continuous round the
# world's corners and wraps exactly once round it (the noise is periodic in
# it), so neither a corner nor the start of the perimeter shows a seam.
DEFAULT_SHADERS['terrain_falls.vert'] = """#version 330 core
precision highp float;
precision highp int;
uniform mat4 projection;
uniform mat4 view;
// The chunk's height grid, as terrain.vert reads it.
uniform highp sampler2DArray uHeights;
uniform ivec2 uChunkI;          // (quads per side, texture layer)
uniform vec3  uChunkX;          // (world x, world z, grid step)
uniform int uSide;              // 0: -x, 1: +x, 2: -z, 3: +z
uniform highp vec4 uEdge;       // the terrain's min x, max x, min z, max z
uniform float uLean;            // the strata wall's lean per unit of drop
uniform highp float uFloor;     // the strata wall's foot
uniform highp float uTop;       // the water's surface: the brink
uniform highp float uBottom;    // far below, where the fall has faded out
uniform int uTongueRows;        // quads on the surface before the brink
uniform int uRows;              // quads from the brink down
uniform highp float uTongue;    // how far in from the edge the tongue starts
// The water surface the tongue lies on, exactly as water.vert raises it:
// a grid of uWaterCells cells a side over the brush's rectangle uBrush
// (min x, min z, max x, max z), each corner lifted by the waves (pinned
// flat at the brush's edge), straight across the two triangles of a cell.
uniform int uWaterCells;
uniform highp vec4 uBrush;
uniform float uWaveAmp;
uniform float uWaveSpread;
uniform highp vec2 uFlowOffset;
uniform highp float uWaterTime;
out highp vec3 FallPos;         // world position
out highp vec2 FallUV;          // (perimeter coordinate, path: <0 on the tongue)
out highp float LipDepth;       // water over the brink: uTop - ground
out highp float WallGap;        // how far the curtain is out from the wall
out highp float CornerNear;     // 1 at a world corner, 0 well along an edge
flat out vec3 FallOut;          // the edge's outward direction
flat out vec3 FallSide;         // the outward direction of the nearer corner's other edge

float heightAt(int i, int k) {
    return texelFetch(uHeights, ivec3(k + 1, i + 1, uChunkI.y), 0).r;
}

// Rounded max / min over k (plain max / min at k = 0): the curtain's path
// bends smoothly where it starts hugging the wall and where it leaves the
// wall's foot, with no kink to show as a line across it.
highp float smax(highp float a, highp float b, highp float k) {
    if (k <= 0.0) return max(a, b);
    highp float h = max(k - abs(a - b), 0.0) / k;
    return max(a, b) + h * h * k * 0.25;
}
highp float smin(highp float a, highp float b, highp float k) {
    if (k <= 0.0) return min(a, b);
    highp float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}

""" + WAVE_VARIATION_GLSL + """
// One of water.vert's Gerstner waves: its height only.
float waveHeight(vec2 dir, float wavelength, float amp, float speed, highp vec2 p, float w) {
    vec2 v = waveVariation(p, w);
    float k = 6.2831853 / wavelength;
    return amp * v.y * sin(k * dot(dir, p) + speed * uWaterTime + v.x);
}

// The water surface's rise at a corner of its grid, as water.vert has it.
highp float cornerRise(highp vec2 xz) {
    highp vec2 size = uBrush.zw - uBrush.xy;
    highp float edgeWorld = min(min(xz.x - uBrush.x, uBrush.z - xz.x),
                                min(xz.y - uBrush.y, uBrush.w - xz.y));
    float fadeW = clamp(min(size.x, size.y) * 0.25, 4.0, 48.0);
    float amp = uWaveAmp * smoothstep(0.0, fadeW, edgeWorld);
    if (amp <= 0.001) return 0.0;
    float longer = mix(1.0, 2.2, clamp(uWaveSpread, 0.0, 1.0));
    float slower = inversesqrt(longer);
    highp vec2 p = xz - uFlowOffset;
    return waveHeight(vec2( 0.788,  0.616), 190.0 * longer, amp * 0.42, 1.05 * slower, p, 0.0)
         + waveHeight(vec2(-0.552,  0.834), 118.0 * longer, amp * 0.28, 1.45 * slower, p, 1.0)
         + waveHeight(vec2( 0.943, -0.333),  74.0 * longer, amp * 0.19, 1.95 * slower, p, 2.0)
         + waveHeight(vec2(-0.673, -0.740),  38.0 * longer, amp * 0.11, 2.70 * slower, p, 3.0);
}

// The water surface's rise above its still level at a point, as drawn:
// the grid's corners, straight across the cell's triangle the point is in
// (the cell is split from its (+x, -z) corner to its (-x, +z) one).
highp float surfaceRise(highp vec2 xz) {
    if (uWaveAmp <= 0.001) return 0.0;
    highp vec2 size = max(uBrush.zw - uBrush.xy, vec2(1.0));
    float n = float(max(uWaterCells, 1));
    highp vec2 g = clamp((xz - uBrush.xy) / size * n, vec2(0.0), vec2(n - 1e-3));
    highp vec2 i = floor(g);
    vec2 f = g - i;
    highp vec2 cell = size / n;
    highp vec2 c00 = uBrush.xy + i * cell;
    highp float h00 = cornerRise(c00);
    highp float h10 = cornerRise(c00 + vec2(cell.x, 0.0));
    highp float h01 = cornerRise(c00 + vec2(0.0, cell.y));
    if (f.x + f.y <= 1.0)
        return h00 + f.x * (h10 - h00) + f.y * (h01 - h00);
    highp float h11 = cornerRise(c00 + cell);
    return h11 + (1.0 - f.x) * (h01 - h11) + (1.0 - f.y) * (h10 - h11);
}

// Along the perimeter, counter-clockwise from the (min x, min z) corner.
highp float perimeter(vec2 p) {
    highp float w = uEdge.y - uEdge.x;
    highp float d = uEdge.w - uEdge.z;
    if (uSide == 2) return p.x - uEdge.x;
    if (uSide == 1) return w + (p.y - uEdge.z);
    if (uSide == 3) return w + d + (uEdge.y - p.x);
    return 2.0 * w + d + (uEdge.w - p.y);
}

void main() {
    int res = uChunkI.x;
    int quad = gl_VertexID / 6;
    int corner = gl_VertexID - quad * 6;
    int col = quad % res;
    int row = quad / res;
    // (0,0) (1,0) (0,1)  (1,0) (1,1) (0,1)
    int dc = (corner == 1 || corner == 3 || corner == 4) ? 1 : 0;
    int dr = (corner == 2 || corner == 4 || corner == 5) ? 1 : 0;
    int j = col + dc;
    int r = row + dr;
    ivec2 g = uSide == 0 ? ivec2(0, j)
            : uSide == 1 ? ivec2(res, j)
            : uSide == 2 ? ivec2(j, 0)
            :              ivec2(j, res);
    highp vec3 rim = vec3(uChunkX.x + float(g.x) * uChunkX.z,
                          heightAt(g.x, g.y),
                          uChunkX.y + float(g.y) * uChunkX.z);
    highp float h = rim.y;
    vec2 out2 = uSide == 0 ? vec2(-1.0, 0.0)
              : uSide == 1 ? vec2( 1.0, 0.0)
              : uSide == 2 ? vec2(0.0, -1.0)
              :              vec2(0.0,  1.0);
    vec2 along = vec2(abs(out2.y), abs(out2.x));
    highp float a = dot(rim.xz, along);
    highp float lo = uSide < 2 ? uEdge.z : uEdge.x;
    highp float hi = uSide < 2 ? uEdge.w : uEdge.y;
    highp float lip = max(uTop - h, 0.0);
    // A hair above the surface, so the sheet lies over the water drawn
    // under it (the surface's edge row is exactly uTop).
    highp float lift = 1.5;
    highp vec3 p;
    highp float path;
    highp float reach = 0.0;
    highp float wall = 0.0;
    if (r < uTongueRows) {
        // On the surface, d in from the edge; rows crowd towards the brink.
        float u = 1.0 - float(r) / float(max(uTongueRows, 1));
        highp float d = uTongue * u * u;
        // Mitred at the corners: columns within d of one fold onto the
        // diagonal, where the next side's tongue begins.
        highp float aa = clamp(a, lo + d, hi - d);
        p = vec3(0.0, 0.0, 0.0);
        p.xz = rim.xz + along * (aa - a) - out2 * d;
        // On the water's surface as it is drawn, waves and all (they are
        // pinned flat at the brink, where the tongue meets the fall), a hair
        // above it -- and a little more where the waves move the surface's
        // corners sideways, which this does not follow.
        p.y = uTop + lift + surfaceRise(p.xz) + 0.15 * uWaveAmp * min(d / 48.0, 1.0);
        path = -d;
    } else {
        float t = float(r - uTongueRows) / float(max(uRows, 1));
        highp float total = max(uTop - uBottom, 1.0);
        highp float drop = total * pow(t, 2.4);
        highp float y = uTop + lift - drop;
        // Barely thrown off the brink: the sheet leaves it and goes down the
        // rock face at once. (Seen from above, water thrown out showed as a
        // band along the sea's edge, between the water and the curtain.)
        // Every column follows the same path, so the sheet stays smooth
        // however the sea floor varies along the edge.
        highp float head = 1.5;
        highp float arc = sqrt(2.0 * drop * head);
        // The wall below the rim leans out; the curtain follows it down at
        // the same angle, past its foot too (on into the haze), never passing
        // into it, and a little spray holds it off the rock.
        highp float below = max(h - y, 0.0);
        wall = uLean * below;
        highp float gap = min(below, 6.0) + 0.035 * min(below, 2000.0);
        // Exactly the brink at the top (it meets the tongue there), rounded
        // further down.
        reach = smax(arc, wall + gap, min(80.0, drop * 0.5));
        // Mitred at the world's corners, as the wall's foot is, so the falls
        // on two sides meet along the diagonal.
        highp float eps = uChunkX.z * 0.01;
        float mitre = a <= lo + eps ? -1.0 : (a >= hi - eps ? 1.0 : 0.0);
        p = vec3(rim.x, y, rim.z);
        p.xz += (out2 + along * mitre) * reach;
        path = drop;
    }
    // The corner this column is nearer, and its other edge's outward way.
    bool lowEnd = a - lo < hi - a;
    highp float toCorner = lowEnd ? a - lo : hi - a;
    vec2 other = uSide < 2 ? vec2(0.0, lowEnd ? -1.0 : 1.0)
                           : vec2(lowEnd ? -1.0 : 1.0, 0.0);

    FallPos = p;
    FallUV = vec2(perimeter(rim.xz), path);
    LipDepth = uTop - h;
    WallGap = reach - wall;
    CornerNear = 1.0 - smoothstep(0.0, 900.0, toCorner);
    FallOut = vec3(out2.x, 0.0, out2.y);
    FallSide = vec3(other.x, 0.0, other.y);
    gl_Position = projection * view * vec4(p, 1.0);
}
"""

DEFAULT_SHADERS['terrain_falls.frag'] = """#version 330 core
precision highp float;
in highp vec3 FallPos;
in highp vec2 FallUV;
in highp float LipDepth;
in highp float WallGap;
in highp float CornerNear;
flat in vec3 FallOut;
flat in vec3 FallSide;
out vec4 FragColor;

uniform highp float uTop;
uniform highp float uFloor;
uniform highp float uBottom;
uniform highp float uTongue;
uniform highp vec4 uEdge;       // the terrain's min x, max x, min z, max z
uniform highp float uPerimeter; // once round the world's edge
uniform highp vec2 uSpan;       // the stretch of edge this water covers (perimeter)
uniform vec3 uTint;             // the water's tint, as water.frag has it
uniform float uOpacity;         // the water's opacity
uniform float uReflectivity;    // the water's reflectivity
uniform float uTime;
uniform highp vec3 uCamPos;
uniform vec4 uSkyState;         // night, cloud cover, gloom, dusk (water.frag)
uniform int uLightSteps;
uniform int uDither;

uniform int   uFogEnabled;
uniform vec3  uFogColor;
uniform float uFogStart;
uniform float uFogEnd;
uniform float uFogDensity;
uniform highp vec3 uFogCamPos;
uniform vec3  uAmbient;

const vec3 SUN_DIR   = vec3(0.4767, 0.6555, 0.5859);   // as water.frag
const vec3 SUN_COLOR = vec3(1.00, 0.95, 0.82);

float fogFactor(highp vec3 fragPos) {
    if (uFogEnabled == 0) return 0.0;
    highp float d = length(fragPos - uFogCamPos);
    float band = max(uFogEnd - uFogStart, 1e-4);
    float f = clamp((d - uFogStart) / band, 0.0, 1.0);
    if (uFogDensity > 0.0) {
        float e = uFogDensity * max(d - uFogStart, 0.0);
        f = max(f, clamp(1.0 - exp(-e * e), 0.0, 1.0));
    }
    return f;
}

float bayer4(vec2 p) {
    ivec2 q = ivec2(mod(p, 4.0));
    int i = q.x + q.y * 4;
    int m[16] = int[](0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5);
    return (float(m[i]) + 0.5) / 16.0;
}

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
// Value noise whose x repeats every n cells (n a whole number): laid along
// the perimeter with n cells once round it, it closes on itself exactly.
float pnoise(highp vec2 p, highp float n) {
    highp vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    highp float i0 = mod(i.x, n);
    highp float i1 = mod(i.x + 1.0, n);
    return mix(mix(hash12(vec2(i0, i.y)), hash12(vec2(i1, i.y)), u.x),
               mix(hash12(vec2(i0, i.y + 1.0)), hash12(vec2(i1, i.y + 1.0)), u.x), u.y);
}
// Fractal noise along the perimeter: *scale* world units a cell (rounded so
// a whole number fit once round), *y* the other coordinate.
float pfbm(highp float s, highp float y, float scale) {
    highp float n = max(floor(uPerimeter / scale + 0.5), 1.0);
    highp vec2 p = vec2(s / uPerimeter * n, y);
    float a = 0.5;
    float sum = 0.0;
    for (int i = 0; i < 4; ++i) {
        sum += a * pnoise(p, n);
        p = vec2(p.x * 2.0, p.y * 2.07 + 13.7);
        n *= 2.0;
        a *= 0.5;
    }
    return sum / 0.9375;
}
float pnoise1(highp float s, highp float y, float scale) {
    highp float n = max(floor(uPerimeter / scale + 0.5), 1.0);
    return pnoise(vec2(s / uPerimeter * n, y), n);
}

// The sky the water reflects, as water.frag's procedural sky (no clouds).
vec3 skyColour(vec3 dir) {
    float night = clamp(uSkyState.x, 0.0, 1.0);
    float gloom = clamp(uSkyState.z, 0.0, 1.0);
    float dusk = clamp(uSkyState.w, 0.0, 1.0);
    float h = clamp(dir.y, 0.0, 1.0);
    vec3 top = mix(vec3(0.19, 0.38, 0.66), vec3(0.03, 0.07, 0.19), night);
    vec3 horizon = mix(mix(vec3(0.66, 0.76, 0.83), vec3(0.09, 0.14, 0.27), night),
                       vec3(0.96, 0.56, 0.34), dusk);
    vec3 sky = mix(horizon, top, pow(h, 0.55));
    return mix(sky, mix(vec3(0.56, 0.59, 0.63), vec3(0.03, 0.04, 0.07), night), gloom * 0.8);
}

void main() {
    highp float s = FallUV.x;          // round the perimeter, world units
    highp float path = FallUV.y;       // < 0: in from the brink; > 0: fallen
    highp float drop = max(path, 0.0);
    highp float lip = max(LipDepth, 0.0);
    // Dry ground at the edge: nothing pours over it.
    if (LipDepth <= 0.0) discard;
    // Only along this water's stretch of the edge.
    float span = smoothstep(uSpan.x - 4.0, uSpan.x + 12.0, s)
               * (1.0 - smoothstep(uSpan.y - 12.0, uSpan.y + 4.0, s));
    if (span <= 0.0) discard;

    float aa = max(max(fwidth(s), fwidth(path)), 1e-3);
    // How long the water has been on its way, which is what the pattern
    // scrolls in: on the surface it quickens towards the brink; over it, it
    // falls freely, from v0 at the brink gathering speed with the drop --
    // streaks short and slow at the brink, long and fast below. Continuous
    // in value and in rate across the brink.
    float g = 900.0;
    float v0 = 70.0 + 2.5 * lip;
    float tau;
    if (path < 0.0) {
        float d = -path;
        tau = -(d + d * d / 120.0) / v0;
    } else {
        tau = (sqrt(v0 * v0 + 2.0 * g * drop) - v0) / g;
    }
    float flow = tau - uTime;
    // Ropes of water side by side across the curtain, each falling at its
    // own pace, and the white water breaking out of them.
    float ropes = pfbm(s, flow * 1.6, 22.0);
    float streak = pfbm(s + ropes * 15.0, flow * 7.0, 5.0);
    float fine = pnoise1(s + streak * 3.6, flow * 26.0, 1.8);
    // Beyond a world corner, in the square where the two edges' sheets meet
    // (the curtain keeps the corner's right angle), the ropes come apart
    // into an even spray: every pattern here is laid along the edge, and
    // smeared across that square it would draw lines out from the corner.
    highp float offX = max(uEdge.x - FallPos.x, FallPos.x - uEdge.y);
    highp float offZ = max(uEdge.z - FallPos.z, FallPos.z - uEdge.w);
    float wedge = smoothstep(0.0, 800.0, min(offX, offZ));
    // Over the brink: seen from above (the game's only view), the water
    // thrown off the brink shows as a band beside it, and past that the
    // sheer curtain. The water's look turns from the surface's to the
    // curtain's across that band -- from the border's at the brink to the
    // curtain's white where it meets the fall -- so neither of its edges
    // shows as a line. (Deeper water is thrown further: a wider band.)
    float away = path > 0.0 ? smoothstep(0.0, 24.0 + 0.12 * lip, drop) : 0.0;
    // Where two edges' surfaces meet at a corner their streaks run two ways;
    // they fade out there, so no crease shows along the diagonal.
    float meet = path < 0.0 ? CornerNear : 0.0;
    ropes = mix(ropes, 0.5, max(meet, wedge));
    // Seen from above, the first of the fall is crowded into a thin band
    // beside the brink: the streaks come up gradually, from in on the
    // surface, through the brink, to well down the fall, so the water's look
    // runs on into the curtain's with no line between them.
    float settle = path < 0.0 ? 0.5 * smoothstep(-uTongue, 0.0, path) : 0.5 + 0.5 * away;
    float detail = (1.0 - smoothstep(2.0, 9.0, aa)) * (1.0 - wedge) * (1.0 - meet) * settle;
    streak = mix(0.5, streak, detail);
    fine = mix(0.5, fine, detail);

    // How much water comes over here: thin by the shore, where the side of
    // the fall frays, tearing further in the further it has fallen.
    float fray = mix(pfbm(s, drop / 160.0 + flow * 0.4, 30.0), 0.5, max(meet, wedge));
    float thick = smoothstep(0.12, 0.55, LipDepth / 70.0 + (fray - 0.5) * 0.5
                                         - 0.35 * smoothstep(0.0, 1500.0, drop));
    if (thick <= 0.0) discard;

    // ---- the surface's own look ------------------------------------------
    // The sheet bends from the surface (up) over the brink to the fall
    // (outward). Near a world corner the two edges' outward ways blend, so
    // the corner reads as one rounded fall, not two sheets meeting.
    vec3 outward = normalize(FallOut + FallSide * CornerNear);
    // Over a long drop: seen from above, the top of the fall keeps the
    // surface's look and turns to the curtain's gradually, a feathered band
    // rather than one with edges.
    // (Eased in, so the water whitens as it goes over before it turns from
    // the sky: no darker strip between the surface and the white.)
    float bend = away * away;
    vec3 up = vec3(0.0, 1.0, 0.0);
    vec3 across = normalize(vec3(outward.z, 0.0, -outward.x));
    float ripple = (streak - 0.5) * detail;
    vec3 N = normalize(mix(up, outward, bend)
                       + across * ripple * mix(0.12, 0.9, bend)
                       + outward * (ropes - 0.5) * 0.15 * (1.0 - bend));
    vec3 viewDir = normalize(uCamPos - FallPos);
    float NdV = max(dot(N, viewDir), 0.0);
    vec3 deepCol = uTint * 0.55;
    vec3 shallowCol = uTint * 1.25 + vec3(0.02, 0.10, 0.09);
    vec3 bodyCol = mix(deepCol, shallowCol, pow(1.0 - NdV, 1.5) * 0.7 + 0.15);
    bodyCol *= 0.45 + 0.55 * max(dot(N, SUN_DIR), 0.0);
    float f0 = 0.020373;
    float fresnel = f0 + (1.0 - f0) * pow(1.0 - NdV, 5.0);
    float reflW = max(max(fresnel, clamp(uReflectivity, 0.0, 1.0) * 0.5), 0.35 * (1.0 - bend));
    vec3 sky = skyColour(reflect(-viewDir, normalize(mix(up, N, 0.35))));
    vec3 water = mix(bodyCol, sky, reflW);

    // ---- white water ------------------------------------------------------
    // A border in from the brink, on the surface: the water quickens and
    // starts to break white before it goes over, its inner edge ragged and
    // drifting, so the sea runs into the fall with no line at the brink and
    // no hard corner where two edges meet. Over the brink it whitens on as
    // it falls.
    float rag = mix(pfbm(s, flow * 0.25 + 3.1, 260.0), 0.5, meet);
    // (Ragged within, never at the brink: there the border meets the fall
    // exactly, so nothing changes across the line where the water goes over.)
    float atBrink = smoothstep(-uTongue * 0.45, 0.0, min(path, 0.0));
    float ragged = (rag - 0.5) * (1.0 - atBrink);
    float border = path < 0.0
        ? smoothstep(-uTongue, 0.0, path + ragged * uTongue * 0.6) : 1.0;
    border = border * border * border * (0.7 + 0.3 * streak);
    // (The throw's white no brighter than the curtain beyond it: no crest
    // drawn along the fold.)
    float aer = max(away * mix(1.0, 0.72, smoothstep(0.0, 400.0, drop) < 1.0 ? 1.0 - smoothstep(0.0, 400.0, drop) : 0.0), 0.55 * border);
    float brink = smoothstep(-uTongue * 0.35, 0.0, path) * (1.0 - smoothstep(0.0, 24.0, drop));
    // (Not at the brink itself, where the curtain leaves the rock's top:
    // that would draw a white line round the water.)
    float churn = (1.0 - smoothstep(6.0, 160.0, WallGap)) * away;
    vec3 foam = vec3(0.97, 0.985, 1.0);
    float white = clamp(aer * (0.70 + 0.50 * streak) + churn * 0.35, 0.0, 1.0);
    vec3 col = mix(water, foam, white);
    // Denser channels of water between the white ropes: darker, bluer.
    float channel = pow(1.0 - streak, 3.0) * aer;
    col = mix(col, water * 1.15, clamp(channel * 1.3, 0.0, 0.7));
    col *= mix(1.0, 0.82 + 0.30 * ropes, max(aer, brink * 0.5));
    col *= 1.0 + (fine - 0.5) * 0.18 * max(aer, brink);

    // ---- how much of it there is ----------------------------------------
    // On the surface: nothing at the tongue's far end, all of it by the
    // brink, so the sea flows into the fall without an edge.
    float onSurface = 1.0 - smoothstep(0.0, uTongue, -path - ragged * uTongue * 0.4);
    float alpha = path < 0.0 ? onSurface * onSurface * (3.0 - 2.0 * onSurface) : 1.0;
    // Over the brink the curtain is solid, then thins and tears as it falls.
    float wallDrop = max(uTop - uFloor, 1.0);
    float fallen = clamp(drop / wallDrop, 0.0, 1.0);
    float tear = smoothstep(0.10 + 0.22 * fallen, 0.30 + 0.25 * fallen,
                            streak * 0.65 + fine * 0.35);
    // Wholly solid in front of the cliff (nothing of the rock shows through
    // it, so its foot draws no line across the fall); it tears only below.
    highp float pastFoot = max(drop - wallDrop, 0.0) / wallDrop;
    alpha *= mix(1.0, mix(0.82, 1.0, tear), smoothstep(0.0, 0.8, pastFoot));
    // And on without end: past the wall it falls on into the void, the
    // ropes drawing apart into spray and the spray thinning into the air
    // the further down it goes, so the eye loses it and no bottom is ever
    // seen.
    highp float deep = max(drop - wallDrop, 0.0);
    float haze = 1.0 - exp(-deep / 6000.0);
    float veil = mix(pfbm(s - uTime * 3.0, FallPos.y / 160.0 + uTime * 0.35, 80.0), 0.5, wedge);
    vec3 hazeCol = uFogEnabled != 0 ? uFogColor : vec3(0.86, 0.90, 0.94);
    col = mix(col, hazeCol * (0.94 + 0.10 * veil), haze * 0.6);
    float ropesApart = mix(1.0, smoothstep(0.25, 0.75, ropes * 0.7 + veil * 0.3), haze);
    alpha *= exp(-deep / 10400.0) * ropesApart;
    col = mix(col, foam * 0.97, wedge * 0.25);
    alpha *= 1.0 - smoothstep(0.45, 1.0, drop / max(uTop - uBottom, 1.0));
    // A thin flow (the shallows by the shore) falls as separate ribbons.
    float ribbons = smoothstep(0.55 - 0.55 * thick, 0.85 - 0.5 * thick,
                               pnoise1(s, 0.5, 7.0) * 0.8 + 0.2 * ropes);
    alpha *= thick * mix(ribbons, 1.0, thick * thick) * span;
    // Behind the water: seen from above the sea, over the brink, a part of
    // the fall whose view ray crosses the edge below the surface lies behind
    // the water (which writes no depth), and is hidden by it -- exactly up
    // to the water's own edge on screen.
    if (path > 0.0 && uCamPos.y > uTop) {
        vec2 o2 = FallOut.xz;
        vec2 al = vec2(abs(o2.y), abs(o2.x));
        highp float E = o2.x > 0.5 ? uEdge.y : o2.x < -0.5 ? -uEdge.x
                      : o2.y > 0.5 ? uEdge.w : -uEdge.z;
        highp float co = dot(uCamPos.xz, o2);
        highp float po = dot(FallPos.xz, o2);
        if (co < E && po > E) {
            highp float t = (E - co) / (po - co);
            highp vec3 hit = mix(uCamPos, FallPos, t);
            highp float a = dot(hit.xz, al);
            highp float lo = abs(o2.x) > 0.5 ? uEdge.z : uEdge.x;
            highp float hi = abs(o2.x) > 0.5 ? uEdge.w : uEdge.y;
            if (a > lo && a < hi) {
                float px = max(fwidth(hit.y), 1e-3);
                // (Not at the brink itself, which the surface covers: a
                // hairline there would show as a line round the water.)
                alpha *= 1.0 - smoothstep(-px, px, uTop - hit.y) * smoothstep(4.0, 30.0, drop);
            }
        }
    }
    if (alpha < 0.003) discard;

    // ---- light ------------------------------------------------------------
    vec3 skyAmb = vec3(0.6, 0.75, 0.9);
    vec3 groundAmb = vec3(0.3, 0.25, 0.2);
    vec3 lit = (mix(groundAmb, skyAmb, (N.y + 1.0) * 0.5) * 0.45 + uAmbient);
    float wrapped = (max(dot(N, SUN_DIR), 0.0) + 0.45) / 1.45;
    if (uLightSteps > 0) {
        float steps = float(uLightSteps);
        wrapped = floor(wrapped * steps + 0.5) / steps;
    }
    lit += wrapped * vec3(1.0, 0.95, 0.85) * 0.62;
    // The water's own colour already carries its light (water.frag lights
    // its body by the sun and reflects the sky); the foam takes the light.
    vec3 result = mix(col, col * min(lit * 1.25, vec3(1.15)), white * (1.0 - haze * 0.6));
    // Sun glints on the glassy water, as on the surface.
    vec3 Hs = normalize(SUN_DIR + viewDir);
    float spec = pow(max(dot(N, Hs), 0.0), mix(320.0, 40.0, bend));
    result += SUN_COLOR * spec * mix(2.2, 0.5, bend) * (1.0 - white * 0.8)
            * (0.35 + 0.65 * clamp(uReflectivity, 0.0, 1.0));
    result = mix(result, uFogColor, fogFactor(FallPos));
    if (uDither > 0) {
        float levels = float(uDither);
        result = floor(clamp(result, 0.0, 1.0) * levels + bayer4(gl_FragCoord.xy)) / levels;
    }
    FragColor = vec4(result, clamp(alpha, 0.0, 1.0));
}
"""


# The optional 360-degree void panorama, used by renderers which support a
# camera-oriented background image. Kept in the central registry so the
# shader portability suite compiles it with every other GLSL 3.30 shader.
DEFAULT_SHADERS['void_background.vert'] = """#version 330 core
// The sky: a full-screen triangle at the far plane. The view ray is linear
// across the screen, so each vertex works out its world direction and the
// rasteriser interpolates it exactly; a pixel only reads the cube map.
uniform mat4 u_inverse_projection;
uniform mat4 u_inverse_view;
out vec3 v_direction;
void main() {
    vec2 p;
    if (gl_VertexID == 0) {
        p = vec2(-1.0, -1.0);
    } else if (gl_VertexID == 1) {
        p = vec2(3.0, -1.0);
    } else {
        p = vec2(-1.0, 3.0);
    }
    vec4 view_h = u_inverse_projection * vec4(p, 1.0, 1.0);
    v_direction = mat3(u_inverse_view) * (view_h.xyz / view_h.w);
    gl_Position = vec4(p, 1.0, 1.0);
}
"""
DEFAULT_SHADERS['void_background.frag'] = """#version 330 core
in vec3 v_direction;
out vec4 frag_colour;
// The panorama as a cube map (sky_cube.frag made it once, at load): one
// read a pixel, no trigonometry.
uniform samplerCube u_sky;
void main() {
    frag_colour = vec4(texture(u_sky, v_direction).rgb, 1.0);
}
"""

def _edge_sky_source():
    """``edge_sky.frag``: the sky behind the world with ``[Renderer]
    skystyle`` 1, 2 or 3 (engine/renderer/forward/edge_sky.py).

    Its sky is the map's panorama when it has one, else the game's own sky
    -- the very code water.frag reflects (gradient, sun, clouds and weather,
    the moon and stars), taken from it so the two always agree. Near the
    world's edge space (the Space panorama) comes in: on the walls of the
    sky with the clouds kept overhead, blending down the walls (style 1), or
    over the whole sky (style 2). Style 3 is space everywhere, always."""
    water = DEFAULT_SHADERS['water.frag']
    start, end = water.index('uniform vec4 skyState;'), water.index('void main()')
    sky = water[start:end]
    return """#version 330 core
in vec3 v_direction;
out vec4 frag_colour;
uniform samplerCube u_sky;        // the map's panorama (u_panorama 1)
uniform int u_panorama;
uniform samplerCube u_space;      // the Space panorama
uniform float u_edge;             // 0 inland .. 1 at the world's edge
uniform int u_mode;               // 1: space on the walls; 2 and 3: the whole sky
uniform highp vec3 u_eye;
uniform highp float time;
// What water.frag's sky reads that is water.frag's own.
const int reflectSky = 0;
uniform sampler2D skyPanorama;
const vec2 SkyUV = vec2(0.0);
const vec3 SUN_DIR   = vec3(0.4767, 0.6555, 0.5859);
const vec3 SUN_COLOR = vec3(1.00, 0.95, 0.82);
""" + sky + """
void main() {
    vec3 d = normalize(v_direction);
    vec3 base = u_panorama == 1 ? texture(u_sky, d).rgb
                                : skyColor(d, u_eye) + skyLights(d, u_eye);
    float w = u_edge;
    if (u_mode == 1) {
        // Space on the walls and below; the sky overhead; the blend runs
        // down the walls.
        w *= 1.0 - smoothstep(0.05, 0.6, d.y);
    }
    vec3 space = texture(u_space, d).rgb;
    frag_colour = vec4(mix(base, space, smoothstep(0.0, 1.0, w)), 1.0);
}
"""


DEFAULT_SHADERS['edge_sky.frag'] = _edge_sky_source()

# Made once when a panorama loads: each face of the sky's cube map drawn
# from the equirectangular image, by the mapping the water reflects it with
# (panoramaUV), so the sky and its reflection agree.
DEFAULT_SHADERS['sky_cube.vert'] = """#version 330 core
out vec2 v_uv;
void main() {
    vec2 p;
    if (gl_VertexID == 0) {
        p = vec2(-1.0, -1.0);
    } else if (gl_VertexID == 1) {
        p = vec2(3.0, -1.0);
    } else {
        p = vec2(-1.0, 3.0);
    }
    v_uv = p * 0.5 + 0.5;
    gl_Position = vec4(p, 0.0, 1.0);
}
"""
# A reflection probe's snapshot (ForwardRenderer._capture_reflection_probe):
# its cube map drawn out as an equirectangular image, the inverse of
# panoramaUV, so water reads it exactly as it reads the sky panorama.
DEFAULT_SHADERS['probe_equirect.frag'] = """#version 330 core
in vec2 v_uv;
out vec4 frag_colour;
uniform samplerCube u_cube;
void main() {
    // Texel row 0 is straight up, as in an uploaded panorama (panoramaUV).
    float yaw = (v_uv.x - 0.5) * 6.28318531;
    float pitch = (0.5 - v_uv.y) * 3.14159265;
    float across = cos(pitch);
    // Mirrored about the horizon: the water reads this, and a reflection
    // looks up -- one a wave tips below the horizon finds the walls just
    // above it, not the floor and the pool itself.
    vec3 d = vec3(across * sin(yaw), abs(sin(pitch)), -across * cos(yaw));
    frag_colour = vec4(texture(u_cube, d).rgb, 1.0);
}
"""
DEFAULT_SHADERS['sky_cube.frag'] = """#version 330 core
in vec2 v_uv;
out vec4 frag_colour;
uniform sampler2D u_panorama;
uniform int u_face;       // GL_TEXTURE_CUBE_MAP_POSITIVE_X + u_face
""" + PANORAMA_GLSL + """
void main() {
    // The face's texel to its direction (the GL cube map convention).
    vec2 st = v_uv * 2.0 - 1.0;
    vec3 d;
    if (u_face == 0)      d = vec3( 1.0, -st.y, -st.x);
    else if (u_face == 1) d = vec3(-1.0, -st.y,  st.x);
    else if (u_face == 2) d = vec3( st.x,  1.0,  st.y);
    else if (u_face == 3) d = vec3( st.x, -1.0, -st.y);
    else if (u_face == 4) d = vec3( st.x, -st.y,  1.0);
    else                  d = vec3(-st.x, -st.y, -1.0);
    frag_colour = vec4(textureLod(u_panorama, panoramaUV(normalize(d)), 0.0).rgb, 1.0);
}
"""

# ==============================================================================
# EXPLOSION (the Effect's one-shot fireball)
#
# One instance row per playing (or previewed) explosion. The row is authored
# data only -- where, how big, when it started -- and the shader works out the
# playback position from the render clock (uTime), so a row is re-uploaded
# only when an explosion starts, stops or moves, not every frame.
#
# EXPLOSION_INSTANCE_LAYOUT is the row's single definition: the attribute
# declarations in effect.vert are generated from it, and the renderer fills
# columns by these names (EXPLOSION_COLUMNS). Column numbers are never
# written out by hand.
# ==============================================================================
from .effect_entity import (                                    # noqa: E402
    EXPLOSION_CELL_UV, EXPLOSION_FRAME_COUNT, EXPLOSION_PREVIEW_T,
    EXPLOSION_SHEET_COLUMNS, EXPLOSION_SHEET_TOP_UV)

#: (attribute, its four components) per vec4 of an explosion instance row,
#: from attribute location 1 (location 0 is the quad corner).
EXPLOSION_INSTANCE_LAYOUT = (
    ('iPosStart', ('x', 'y', 'z', 'start')),
    ('iSize', ('width', 'height', 'intensity', 'lifetime')),
    ('iMeta', ('seed', 'preview', 'skip', 'spare_meta_w')),
    ('iColor', ('r', 'g', 'b', 'spare_color_w')),
)
#: Column of each component in a row: EXPLOSION_COLUMNS['height'] is 5.
EXPLOSION_COLUMNS = {
    name: 4 * vec + comp
    for vec, (_, names) in enumerate(EXPLOSION_INSTANCE_LAYOUT)
    for comp, name in enumerate(names)
}
EXPLOSION_INSTANCE_FLOATS = 4 * len(EXPLOSION_INSTANCE_LAYOUT)

#: The render clock wraps at this many seconds (as the particles' does), so
#: float32 keeps millisecond precision however long the session runs.
EXPLOSION_TIME_WRAP = 4096.0


def _explosion_attribute_glsl():
    return "\n".join(
        "layout (location = %d) in vec4 %s;   // %s"
        % (vec + 1, attribute, ", ".join(names))
        for vec, (attribute, names) in enumerate(EXPLOSION_INSTANCE_LAYOUT))


DEFAULT_SHADERS['effect.vert'] = """#version 330 core
precision highp float;

layout (location = 0) in vec2 aPos;
""" + _explosion_attribute_glsl() + """

uniform mat4 projection;
uniform mat4 view;
uniform highp float uTime;      // render clock, wrapped like iPosStart.w

out highp vec2 vUV;
out highp vec3 vWorldPos;
out highp float vDepth;         // view depth, for the soft edge
out highp float vSoftRange;
out highp float vT;             // playback position 0..1
out vec3 vColor;
out float vIntensity;

const float TIME_WRAP = %(wrap).1f;
const float PREVIEW_T = %(preview_t).9f;

void main() {
    float width = max(iSize.x, 0.01);
    float height = max(iSize.y, 0.01);
    float lifetime = max(iSize.w, 0.001);
    float t;
    if (iMeta.y > 0.5) {
        // The editor's Preview: one frame, whole and still.
        t = PREVIEW_T;
    } else {
        float elapsed = uTime - iPosStart.w;
        if (elapsed < 0.0) elapsed += TIME_WRAP;
        // Playback may start partway in (iMeta.z, explosion_skip): opening
        // on a fireball already grown and bright, which hides whatever it
        // replaces -- an exploding barrel's model.
        float skip = clamp(iMeta.z, 0.0, 0.9);
        t = skip + (1.0 - skip) * clamp(elapsed / lifetime, 0.0, 1.0);
    }
    float growth = mix(1.0, 3.0, smoothstep(0.0, 0.28, t));
    float w = width * growth;
    float h = height * growth;

    // Faces the camera from every angle (a fireball is round), centred half
    // its height above the origin: from eye level its bottom edge stays on
    // the origin and it rises as it grows, as before; from above it is a
    // full fireball rather than an edge-on card.
    vec3 right = normalize(vec3(view[0][0], view[1][0], view[2][0]));
    vec3 up = normalize(vec3(view[0][1], view[1][1], view[2][1]));
    vec3 centre = iPosStart.xyz + vec3(0.0, 0.5 * h, 0.0);
    vec3 worldPos = centre + right * (aPos.x * w) + up * (aPos.y * h);
    vec4 viewPos = view * vec4(worldPos, 1.0);
    gl_Position = projection * viewPos;

    vUV = aPos + 0.5;
    vWorldPos = worldPos;
    vDepth = -viewPos.z;
    vSoftRange = max(0.25 * min(w, h), 1.0);
    vT = t;
    vColor = iColor.rgb;
    vIntensity = iSize.z;
}
""" % {'wrap': EXPLOSION_TIME_WRAP, 'preview_t': EXPLOSION_PREVIEW_T}

DEFAULT_SHADERS['effect.frag'] = """#version 330 core
precision mediump float;

out vec4 FragColor;

in highp vec2 vUV;
in highp vec3 vWorldPos;
in highp float vDepth;
in highp float vSoftRange;
in highp float vT;
in vec3 vColor;
in float vIntensity;

uniform sampler2D explosion_texture;
uniform highp sampler2D uSceneDepth;
uniform int uSoft;
uniform highp vec4 uViewport;
uniform highp vec2 uDepthParams;   // projection[3][2], projection[2][2]
""" + FOG_GLSL + """
const float SHEET_COLUMNS = %(columns).1f;
const float FRAME_COUNT = %(frames).1f;
const vec2 CELL = vec2(%(cell_u).6f, %(cell_v).6f);   // one frame, in UV
const float SHEET_TOP = %(top).6f;   // sheet top edge to the first row, in UV

vec2 atlasUV(vec2 localUV, float frame) {
    float column = mod(frame, SHEET_COLUMNS);
    float row = floor(frame / SHEET_COLUMNS);            // from the top
    // The image's top edge is v = 1.
    float cellTop = 1.0 - SHEET_TOP - row * CELL.y;
    return vec2((column + localUV.x) * CELL.x,
                cellTop - (1.0 - localUV.y) * CELL.y);
}

void main() {
    if (vIntensity <= 0.0) discard;
    float t = vT;

    // Every frame, each blended into the next: frame n is whole at
    // (n + 0.5) / FRAME_COUNT. Blended premultiplied, so a frame's clear
    // texels add no colour to the other's.
    float p = clamp(t * FRAME_COUNT - 0.5, 0.0, FRAME_COUNT - 1.0);
    float f0 = floor(p);
    float k = p - f0;
    vec4 a = texture(explosion_texture, atlasUV(vUV, f0));
    vec4 b = texture(explosion_texture, atlasUV(vUV, min(f0 + 1.0, FRAME_COUNT - 1.0)));
    float sheetAlpha = mix(a.a, b.a, k);
    if (sheetAlpha < 0.02) discard;
    vec3 sheetRGB = mix(a.rgb * a.a, b.rgb * b.a, k) / sheetAlpha;

    float envelope = 1.0 - smoothstep(0.70, 1.0, t);
    float flash = exp(-t * t * 48.0);
    float burst = 1.0 + flash * 2.2;
    vec3 tint = mix(vec3(1.0), max(vColor, vec3(0.001)), 0.35);
    vec3 rgb = sheetRGB * tint * vIntensity * burst;
    float alpha = sheetAlpha * envelope;

    if (uSoft != 0) {
        // Soft edge: fade where the scene is just behind the fireball, so a
        // floor or wall it passes through leaves no hard line.
        highp vec2 uv = (gl_FragCoord.xy - uViewport.xy) / uViewport.zw;
        highp float d = texture(uSceneDepth, uv).r * 2.0 - 1.0;
        highp float sceneDepth = uDepthParams.x / (d + uDepthParams.y);
        alpha *= clamp((sceneDepth - vDepth) / vSoftRange, 0.0, 1.0);
    }
    if (alpha < 0.01) discard;
    FragColor = vec4(applyFog(rgb, vWorldPos), alpha);
}
""" % {'columns': EXPLOSION_SHEET_COLUMNS, 'frames': EXPLOSION_FRAME_COUNT,
       'cell_u': EXPLOSION_CELL_UV[0], 'cell_v': EXPLOSION_CELL_UV[1],
       'top': EXPLOSION_SHEET_TOP_UV}


# ==============================================================================
# STATELESS GPU PARTICLES (an Effect's emitter)
#
# No particle has CPU state. One instance row per emitter feeds
# PARTICLES_PER_EMITTER instances (glVertexAttribDivisor), and the vertex
# shader derives particle i of emitter e from (seed, i, time) alone:
#
#   t     = elapsed + phase + i / count * life     (looping)
#   cycle = floor(t / life), age = t - cycle * life
#   hash(seed, i, cycle) -> fresh randoms each time the particle respawns
#
# A burst (an EXPLOSION's emitter) does not wrap: age = elapsed - jitter, and
# the particle is gone once age passes its life.
# ==============================================================================
from .effect_entity import EMITTER_MAX_PARTICLES as PARTICLES_PER_EMITTER  # noqa: E402
from .effect_entity import EMITTER_PRESETS as _EMITTER_PRESETS             # noqa: E402

#: The render clock the particle shader runs on wraps at this many seconds, so
#: float32 keeps millisecond precision however long the session runs. A
#: looping emitter reshuffles its particles once per wrap (about 68 minutes).
PARTICLE_TIME_WRAP = 4096.0

#: vec4s per preset in the shader's ``uPresets`` table.
PARTICLE_PRESET_VEC4S = 6

#: Preset parameters, world units and seconds. Per preset:
#:   life, speed, spread (cone half-angle as a fraction of pi), drag (1/s)
#:   gravity (+ rises), turbulence, start size, end size
#:   colour rgb, opacity (1 = alpha blended, 0 = additive)
#:   peak alpha, fade-in (fraction of life), fade-out start, lit (0 emissive)
#:   shape (0 disc, 1 line along the width), spin (rad/s), streak (s), noise
#:   glow from the Effect's light near the base, hardness, -, -
PARTICLE_PRESETS = {
    'SMOKE': ((3.0, 28.0, 0.22, 0.45),
              (14.0, 10.0, 12.0, 48.0),
              (0.42, 0.42, 0.42, 1.0),
              (0.42, 0.12, 0.35, 1.0),
              (0.0, 0.6, 0.0, 1.0),
              (0.55, 0.0, 0.0, 0.0)),
    'STEAM': ((1.2, 95.0, 0.16, 1.6),
              (24.0, 14.0, 6.0, 44.0),
              (0.95, 0.96, 0.98, 1.0),
              (0.32, 0.08, 0.25, 1.0),
              (0.0, 1.0, 0.0, 0.8),
              (0.2, 0.0, 0.0, 0.0)),
    'SPARKS': ((0.8, 180.0, 0.32, 0.7),
               (-420.0, 4.0, 3.2, 1.2),
               (1.0, 0.55, 0.16, 0.0),
               (1.0, 0.02, 0.45, 0.0),
               (0.0, 0.0, 0.035, 0.0),
               (0.0, 0.8, 0.0, 0.0)),
    'SPLASH': ((0.7, 200.0, 0.22, 0.6),
               (-480.0, 6.0, 4.0, 16.0),
               (0.90, 0.94, 1.0, 0.8),
               (0.6, 0.05, 0.4, 1.0),
               (1.0, 1.5, 0.02, 0.2),
               (0.0, 0.6, 0.0, 0.0)),
    'MIST': ((4.0, 6.0, 1.0, 0.3),
             (2.0, 8.0, 40.0, 80.0),
             (0.85, 0.88, 0.92, 1.0),
             (0.16, 0.3, 0.5, 1.0),
             (0.0, 0.15, 0.0, 1.0),
             (0.0, 0.0, 0.0, 0.0)),
}


def particle_preset_table():
    """The ``uPresets`` uniform: PARTICLE_PRESET_VEC4S vec4s per preset id,
    in EMITTER_PRESETS order (NONE's rows are zero)."""
    import numpy as _np
    table = _np.zeros((len(_EMITTER_PRESETS) * PARTICLE_PRESET_VEC4S, 4),
                      dtype=_np.float32)
    for index, name in enumerate(_EMITTER_PRESETS):
        rows = PARTICLE_PRESETS.get(name)
        if rows is not None:
            base = index * PARTICLE_PRESET_VEC4S
            table[base:base + PARTICLE_PRESET_VEC4S] = rows
    return table


def particle_preset_lives():
    """Each preset id's particle life, seconds (0 for NONE)."""
    import numpy as _np
    return _np.asarray([PARTICLE_PRESETS.get(name, ((0.0,),))[0][0]
                        for name in _EMITTER_PRESETS], dtype=_np.float64)


_PARTICLE_CONSTANTS = """
const int PARTICLES_PER_EMITTER = %d;
const int PARTICLE_PRESET_COUNT = %d;
const int PARTICLE_PRESET_VEC4S = %d;
const float PARTICLE_TIME_WRAP = %.1f;
""" % (PARTICLES_PER_EMITTER, len(_EMITTER_PRESETS), PARTICLE_PRESET_VEC4S,
       PARTICLE_TIME_WRAP)

DEFAULT_SHADERS['particle.vert'] = """#version 330 core
precision highp float;
""" + _PARTICLE_CONSTANTS + """
layout (location = 0) in vec2 aPos;
// One row per emitter; glVertexAttribDivisor(loc, PARTICLES_PER_EMITTER).
layout (location = 1) in vec4 iPosSeed;   // position, seed
layout (location = 2) in vec4 iEmit;      // preset id, count, scale, mode
layout (location = 3) in vec4 iExtent;    // width, height, start, host lift
layout (location = 4) in vec4 iTint;      // tint rgb, light glow on/off
layout (location = 5) in vec4 iLight;     // the Effect's light colour, -

uniform mat4 projection;
uniform mat4 view;
uniform float uTime;                       // render clock, wrapped
uniform vec4 uPresets[PARTICLE_PRESET_COUNT * PARTICLE_PRESET_VEC4S];
uniform float uMaxScreen;                  // largest particle, fraction of view height
uniform vec2 uNearFade;                    // view depth: invisible .. full

out vec2 vUV;
out vec4 vColor;      // base rgb, lit amount
out vec4 vGlow;       // additive light rgb, opacity
out vec4 vShape;      // alpha, hardness, noise, soft range
out vec3 vWorldPos;
out float vDepth;
out vec2 vNoiseOffset;

const float TAU = 6.28318530718;
const float PI = 3.14159265359;

uint hashU(uint x) {
    x ^= x >> 16u;
    x *= 0x7feb352du;
    x ^= x >> 15u;
    x *= 0x846ca68bu;
    x ^= x >> 16u;
    return x;
}

vec4 rand4(uint seed, uint index, uint cycle, uint salt) {
    uint h = hashU(seed ^ hashU(index * 0x9E3779B9u
                                ^ hashU(cycle * 0x85EBCA6Bu + salt)));
    uint a = hashU(h);
    uint b = hashU(a ^ 0x68E31DA4u);
    uint c = hashU(b ^ 0xB5297A4Du);
    uint d = hashU(c ^ 0x1B56C4E9u);
    return vec4(uvec4(a, b, c, d)) * (1.0 / 4294967295.0);
}

void collapse() {
    // All four corners at the origin with w = 0: clipped, nothing rasterised.
    gl_Position = vec4(0.0);
    vUV = vec2(0.0);
    vColor = vec4(0.0);
    vGlow = vec4(0.0);
    vShape = vec4(0.0);
    vWorldPos = vec3(0.0);
    vDepth = 0.0;
    vNoiseOffset = vec2(0.0);
}

void main() {
    int i = gl_InstanceID % PARTICLES_PER_EMITTER;
    int preset = int(iEmit.x + 0.5);
    int count = int(iEmit.y + 0.5);
    if (i >= count || preset <= 0 || preset >= PARTICLE_PRESET_COUNT) {
        collapse();
        return;
    }
    int b = preset * PARTICLE_PRESET_VEC4S;
    vec4 p0 = uPresets[b];
    vec4 p1 = uPresets[b + 1];
    vec4 p2 = uPresets[b + 2];
    vec4 p3 = uPresets[b + 3];
    vec4 p4 = uPresets[b + 4];
    vec4 p5 = uPresets[b + 5];

    float scale = iEmit.z;
    float mode = iEmit.w;                 // 0 loop, 1 burst, 2 frozen burst
    float life = max(p0.x, 0.05);
    uint seed = uint(iPosSeed.w);
    uint index = uint(i);

    float elapsed = uTime - iExtent.z;
    if (elapsed < 0.0) elapsed += PARTICLE_TIME_WRAP;

    float age;
    uint cycle;
    if (mode < 0.5) {
        float phase = rand4(seed, 0xFFFFu, 0u, 7u).x * life;
        float t = elapsed + phase + float(i) / float(count) * life;
        float c = floor(t / life);
        age = t - c * life;
        cycle = uint(c);
    } else {
        cycle = 0u;
        age = mode > 1.5 ? life * 0.35 : elapsed;
    }
    vec4 r0 = rand4(seed, index, cycle, 0u);
    vec4 r1 = rand4(seed, index, cycle, 1u);
    vec4 r2 = rand4(seed, index, cycle, 2u);
    if (mode > 0.5) {
        age -= r1.w * life * 0.15;        // a burst is not one frame
    }
    float particleLife = life * (0.7 + 0.3 * r0.w);
    if (age < 0.0 || age > particleLife) {
        collapse();
        return;
    }
    float a = age / particleLife;

    // Spawn across the extent: a disc (or a line along the width) as wide as
    // the Effect and as tall as its height, centred on it -- or, above a
    // flame or explosion (host lift > 0), a smaller patch at its crown.
    float w = iExtent.x;
    float h = iExtent.y;
    vec3 offset;
    if (p4.x > 0.5) {
        offset = vec3((r0.x - 0.5) * w, (r0.y - 0.5) * h,
                      (r0.z - 0.5) * min(w * 0.05, 8.0));
    } else {
        float radius = sqrt(r0.x) * 0.5 * w;
        float angle = r0.y * TAU;
        offset = vec3(cos(angle) * radius, (r0.z - 0.5) * h,
                      sin(angle) * radius);
    }
    if (iExtent.w > 0.0) {
        offset *= vec3(0.45, 0.15, 0.45);
        offset.y += h * iExtent.w;
    }

    // Motion: a cone about +Y, drag in closed form, gravity, turbulence.
    float cosT = 1.0 - r1.x * (1.0 - cos(p0.z * PI));
    float sinT = sqrt(max(0.0, 1.0 - cosT * cosT));
    float phi = r1.y * TAU;
    vec3 dir = vec3(cos(phi) * sinT, cosT, sin(phi) * sinT);
    float speed = p0.y * (0.6 + 0.8 * r1.z) * scale;
    float drag = max(p0.w, 1e-3);
    float decay = exp(-drag * age);
    float gravity = p1.x * scale;
    vec3 pos = iPosSeed.xyz + offset
             + dir * speed * (1.0 - decay) / drag
             + vec3(0.0, 0.5 * gravity * age * age, 0.0);
    vec3 vel = dir * speed * decay + vec3(0.0, gravity * age, 0.0);
    float turbulence = p1.y * scale;
    vec3 ph = r2.xyz * TAU;
    pos += turbulence * age * vec3(sin(age * 1.7 + ph.x),
                                   0.35 * sin(age * 2.3 + ph.y),
                                   cos(age * 1.3 + ph.z));

    float grow = 1.0 - (1.0 - a) * (1.0 - a);
    float size = mix(p1.z, p1.w, grow) * (0.7 + 0.6 * r2.w) * scale;
    float alpha = p3.x * smoothstep(0.0, max(p3.y, 1e-3), a)
                * (1.0 - smoothstep(p3.z, 1.0, a));

    vec4 centre = view * vec4(pos, 1.0);
    float depth = -centre.z;
    // Fade out at the near plane rather than fill the screen with one puff.
    alpha *= smoothstep(uNearFade.x, uNearFade.y, depth);
    if (alpha < 0.002 || depth <= 0.0) {
        collapse();
        return;
    }
    // No particle grows past uMaxScreen of the view's height (overdraw).
    float maxSize = uMaxScreen * 2.0 * depth / max(projection[1][1], 1e-4);

    float rotation = r1.w * TAU + (r2.x - 0.5) * 2.0 * p4.y * age;
    vec2 axisX = vec2(cos(rotation), sin(rotation));
    vec2 axisY = vec2(-axisX.y, axisX.x);
    float sizeX = size;
    float sizeY = size;
    if (p4.z > 0.0) {
        // Streak along the velocity seen on screen (sparks, droplets).
        vec2 v = (mat3(view) * vel).xy;
        float speedOnScreen = length(v);
        if (speedOnScreen > 1e-3) {
            axisY = v / speedOnScreen;
            axisX = vec2(axisY.y, -axisY.x);
            sizeY = size + speedOnScreen * p4.z;
        }
    }
    sizeX = min(sizeX, maxSize);
    sizeY = min(sizeY, maxSize);
    vec2 corner = axisX * aPos.x * sizeX + axisY * aPos.y * sizeY;
    gl_Position = projection * (centre + vec4(corner, 0.0, 0.0));

    vUV = aPos * 2.0;
    vColor = vec4(p2.rgb * iTint.rgb, p3.w);
    float glow = p5.x * iTint.w * (1.0 - a) * (1.0 - a) * (1.0 - a);
    vGlow = vec4(iLight.rgb * glow, p2.w);
    vShape = vec4(alpha, p5.y, p4.w, max(min(sizeX, sizeY) * 0.5, 1.0));
    vWorldPos = pos;
    vDepth = depth;
    vNoiseOffset = r2.yz * 37.0;
}
"""

DEFAULT_SHADERS['particle.frag'] = """#version 330 core
precision mediump float;

out vec4 FragColor;

in highp vec2 vUV;
in vec4 vColor;
in vec4 vGlow;
in highp vec4 vShape;
in highp vec3 vWorldPos;
in highp float vDepth;
in highp vec2 vNoiseOffset;

uniform highp sampler2D uSceneDepth;
uniform int uSoft;
uniform highp vec4 uViewport;
uniform highp vec2 uDepthParams;   // projection[3][2], projection[2][2]
""" + FOG_GLSL + """
// Ambient the particle catches before the map's global ambient is added; the
// world's lit shaders bake 0.1, but a puff of smoke is mostly lit from all
// round, so it starts brighter.
const vec3 PARTICLE_BASE_LIGHT = vec3(0.75);

highp float hash12(highp vec2 p) {
    highp vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

highp float valueNoise(highp vec2 p) {
    highp vec2 i = floor(p);
    highp vec2 f = fract(p);
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x),
               mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x),
               u.y);
}

void main() {
    highp float r2 = dot(vUV, vUV);
    if (r2 >= 1.0) discard;

    // Procedural sprite: radial falloff times a little value noise.
    float hardness = vShape.y;
    float falloff = pow(1.0 - r2, 1.0 + 2.0 * hardness);
    highp vec2 q = vUV * 1.7 + vNoiseOffset;
    float n = 0.65 * valueNoise(q) + 0.35 * valueNoise(q * 2.3 + 11.0);
    float mask = falloff * mix(1.0, clamp(n * 1.6 - 0.15, 0.0, 1.0), vShape.z);
    float alpha = vShape.x * mask;

    if (uSoft != 0) {
        // Soft particles: fade where the scene is just behind the particle.
        highp vec2 uv = (gl_FragCoord.xy - uViewport.xy) / uViewport.zw;
        highp float d = texture(uSceneDepth, uv).r * 2.0 - 1.0;
        highp float sceneDepth = uDepthParams.x / (d + uDepthParams.y);
        alpha *= clamp((sceneDepth - vDepth) / vShape.w, 0.0, 1.0);
    }
    if (alpha < 0.003) discard;

    vec3 light = mix(vec3(1.0), min(PARTICLE_BASE_LIGHT + uAmbient, vec3(1.5)),
                     vColor.a);
    vec3 rgb = vColor.rgb * light + vGlow.rgb;
    float opacity = vGlow.a;
    // Alpha-blended particles fade into the fog colour; additive ones fade out.
    float fog = fogFactor(vWorldPos);
    rgb = mix(rgb * (1.0 - fog), mix(rgb, uFogColor, fog), opacity);
    // Premultiplied: opacity 1 blends like alpha, 0 adds.
    FragColor = vec4(rgb * alpha, alpha * opacity);
}
"""


# Central Registry: (Shader Name) -> (Vertex Filename, Fragment Filename)
SHADER_MAP = {
    'simple':        ('simple.vert',         'simple.frag'),
    'lit':           ('lit.vert',            'lit.frag'),
    'textured':      ('textured.vert',       'textured.frag'),
    'sprite':        ('sprite.vert',         'sprite.frag'),
    'depth_cube':    ('depth_cube.vert',     'depth_cube.frag'),
    'fog':           ('fog.vert',            'fog.frag'),
    'water':         ('water.vert',          'water.frag'),
    'glass':         ('glass.vert',          'glass.frag'),
    'terrain':       ('terrain_indexed.vert', 'terrain_flat.frag'),
}
