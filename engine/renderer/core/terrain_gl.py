"""The terrain's GL side, owned by the renderer (M5: tables all the way to GL).

A :class:`TerrainGL` holds every GL name the terrain is drawn with -- the
programs, the height and paint texture pages, the index arrays, the grass
and block-mesh buffers -- and draws one published
:class:`engine.terrain_frame.TerrainFrame`: the dense ``TerrainTable``, the
per-slot products and paint maps beside it, and that frame's appearance. It
never sees the ``Terrain`` object, and nothing here computes a height: a row
is uploaded when the version it holds differs from the published one.

The draw code is the terrain's own, moved here unchanged from
``engine/terrain.py``; the CPU upkeep it used to do first -- streaming, LOD
scheduling, building chunks -- is the terrain's ``advance`` step, which the
host runs before the frame.
"""

import ctypes
import sys
import time

import glm
import numpy as np
import OpenGL.GL as gl
from engine import glraw
from OpenGL.GL.shaders import compileProgram, compileShader

from engine import shaders
from engine.renderer.core import grass_wind
from engine.terrain_frame import grass_vertex_count, heightfield_indices
from engine.terrain_table import GRID_BORDER, STORED_GRID


def _no_current_gl_context():
    """True only when macOS reports that no GL context is current.

    A Terrain is built before any view's context exists (map load, the terrain
    panel). Calling into GL then raises elsewhere, which _compile_program
    handles, but crashes the process on macOS, so ask CGL first. Other
    platforms may mix GLX and EGL, where the query could miss Qt's context.
    """
    if sys.platform != 'darwin':
        return False
    try:
        from OpenGL import platform as gl_platform
        return not gl_platform.PLATFORM.GetCurrentContext()
    except Exception:
        return False


#: EXT/ARB_texture_filter_anisotropic (not in PyOpenGL's core namespace).
_TEXTURE_MAX_ANISOTROPY = 0x84FE
_MAX_TEXTURE_MAX_ANISOTROPY = 0x84FF

#: About how wide a grass cell is (world units). A chunk's blades are
#: uploaded sorted into cells (Morton order, so a block of neighbouring cells
#: is mostly one run of the buffer) and only the cells inside the view are
#: drawn: no blade outside the camera's frustum is sent through.
GRASS_CELL_SIZE = 128.0
#: At most this many cells a side (the Morton code holds 4 bits a side).
GRASS_CELLS_MAX = 16


def grass_cells_for(size):
    """Cells a side for a chunk *size* units wide: a power of two, ~128 units each."""
    n = 1
    while n < GRASS_CELLS_MAX and size / (n * 2) >= GRASS_CELL_SIZE * 0.75:
        n *= 2
    return n


def _morton(ix, iz):
    """Interleave the bits of two small cell coordinates (Z-order)."""
    out = np.zeros_like(ix)
    for bit in range(4):
        out |= ((ix >> bit) & 1) << (2 * bit)
        out |= ((iz >> bit) & 1) << (2 * bit + 1)
    return out


def _sort_grass_cells(data, x0, z0, size):
    """*data*'s blades sorted by cell, and the cells that hold any:
    ``(data, starts, counts, boxes)`` with ``boxes`` (k, 7) float64 of
    ``min x, max x, min root y, max root y, max size, min z, max z``."""
    n = grass_cells_for(size)
    ix = np.clip(((data[:, 0] - x0) * (n / size)).astype(np.int64), 0, n - 1)
    iz = np.clip(((data[:, 2] - z0) * (n / size)).astype(np.int64), 0, n - 1)
    cell = _morton(ix, iz)
    order = np.argsort(cell, kind='stable')
    data = np.ascontiguousarray(data[order])
    cell = cell[order]
    edges = np.flatnonzero(np.diff(cell)) + 1
    starts = np.concatenate(([0], edges)).astype(np.int64)
    counts = np.diff(np.concatenate((starts, [len(data)]))).astype(np.int64)
    cols = data[:, (0, 1, 2, 3)].astype(np.float64)
    lo = np.minimum.reduceat(cols, starts, axis=0)
    hi = np.maximum.reduceat(cols, starts, axis=0)
    boxes = np.stack((lo[:, 0], hi[:, 0], lo[:, 1], hi[:, 1], hi[:, 3],
                      lo[:, 2], hi[:, 2]), axis=1)
    return data, starts, counts, boxes


def _visible_cells(boxes, planes, blade_height, blade_width):
    """Which cells' blades can reach into the frustum (*planes*, (p, 4)).

    A blade stands at most 1.3 x its size x the blade height and leans at
    most its own length, so each cell's box grows by that much sideways and
    upward (and its width): conservative, never culling a blade in view."""
    reach = boxes[:, 4] * (blade_height * 1.3) + blade_width * 2.0 + 1.0
    x0, x1 = boxes[:, 0] - reach, boxes[:, 1] + reach
    z0, z1 = boxes[:, 5] - reach, boxes[:, 6] + reach
    y0, y1 = boxes[:, 2] - 1.0, boxes[:, 3] + reach
    a, b, c, d = planes[:, 0], planes[:, 1], planes[:, 2], planes[:, 3]
    px = np.where(a >= 0, x1[:, None], x0[:, None])
    py = np.where(b >= 0, y1[:, None], y0[:, None])
    pz = np.where(c >= 0, z1[:, None], z0[:, None])
    return ~((a * px + b * py + c * pz + d) < 0).any(axis=1)


#: A run of fewer blades than this is folded into the run it touches: the
#: draw call it would cost is dearer than drawing its blades the costlier way
#: (detailed, or with the parting loop), which is always correct. Measured on
#: llvmpipe: a draw ~25 us, a blade's parting loop ~0.2 us.
GRASS_MERGE_RUN = 128


def _merge_small_runs(runs):
    """*runs* (``(start, count, detailed, pushed)``, in buffer order) with
    every small run joined to an adjoining one, taking the costlier way of
    each. Runs with out-of-view cells between them stay apart."""
    if len(runs) < 2:
        return runs
    out = [list(runs[0])]
    for start, count, detailed, pushed in runs[1:]:
        last = out[-1]
        if last[0] + last[1] == start and (
                count < GRASS_MERGE_RUN or last[1] < GRASS_MERGE_RUN
                or (detailed, pushed) == (last[2], last[3])):
            last[1] += count
            last[2] = last[2] or detailed
            last[3] = last[3] or pushed
        else:
            out.append([start, count, detailed, pushed])
    return [tuple(run) for run in out]


class TerrainGL:
    """GL state for one published terrain (``TerrainFrame.key``)."""

    #: Every uniform the terrain programs are driven through, less the
    #: appearance uniforms a frame names itself.
    UNIFORM_NAMES = (
        'projection', 'view', 'active_lights', 'use_textures', 'lod_level',
        'texGrass', 'texRock', 'texSand', 'texSnow',
        'terrainPaintMap', 'uPaintLayer', 'uPaintEnabled',
        'uHeights', 'uChunkI', 'uChunkX', 'uChunkY', 'uTiling', 'uFlatMode',
        'uGradCount', 'uGradH', 'uGradC', 'uGradW', 'uGradD',
        'uBiomeMap', 'uBiomeEnabled', 'uBiomeBounds',
    )
    #: Texture unit of the regional biome map (``uBiomeMap``). Above the
    #: shadow cube-maps (4..11), the height and paint pages (12, 13) and the
    #: forward renderer's transform texture (14); GL 3.3 guarantees 16 units
    #: to a fragment shader.
    BIOME_TEXTURE_UNIT = 15

    def __init__(self):
        #: The frame being drawn; set for the length of :meth:`render`.
        self.frame = None
        self.shader_program = 0
        self.uniforms = {}
        self.block_program = 0
        self.block_uniforms = {}
        self.grass_shader_program = 0
        self.grass_uniforms = {}
        #: Programs compiled here (a renderer may hand in its own instead).
        self._own_programs = set()
        self._failed_programs = set()
        self.grass_tex = self.rock_tex = self.sand_tex = self.snow_tex = 0
        self.grass_time = 0.0
        #: The wind the grass sways in this frame (a renderer's
        #: ``grass_wind``, set for the length of :meth:`render`), and how far
        #: its gust field has rolled (core/grass_wind.py).
        self.grass_wind = None
        self.grass_scroll = (0.0, 0.0)
        self._height_pages = []
        self._page_layers = 0
        self._paint_pages = []
        self._paint_page_layers = 0
        # Paint layers go to painted chunks only: slot -> layer number across
        # the pages, and the numbers given back by slots that lost theirs.
        self._paint_layer = {}
        self._paint_layers_free = []
        self._paint_layers_used = 0
        self._paint_anisotropy_limit = None
        self._paint_epoch = None
        # One transparent texel, bound where a chunk has no paint, so the
        # paint sampler is never left on an incomplete texture.
        self._empty_paint_texture = 0
        # The regional biome map (frame.biome_map) and the version uploaded.
        self._biome_tex = 0
        self._biome_gpu_version = None
        self._index_vaos = {}          # resolution -> (vertex array, index buffer)
        self._placeholder_cubemap = 0
        self._sync_gl_columns_reset()
        #: What the last frame drew, for the host (SysMon, the terrain
        #: editor, Debug Tables).
        self.visible_chunks = 0
        self.culled_chunks = 0
        self.total_triangles = 0
        self.drawn_slots = np.empty(0, dtype=np.intp)
        #: slot -> (starts, counts, boxes) of its grass cells (_sort_grass_cells).
        self._grass_cells = {}
        #: Grass instances and draws the last frame sent (tests, SysMon).
        self.grass_instances_drawn = 0
        self.grass_draws = 0
        self._base_instance = None

    def _sync_gl_columns_reset(self):
        for name in ('_grass_vao', '_grass_vbo', '_grass_count', '_gpu_version',
                     '_paint_gpu_version', '_block_vao', '_block_vbo', '_block_count',
                     '_grass_version', '_block_version', '_slot_order'):
            setattr(self, name, np.zeros(0, dtype=np.int64))

    def _compile_program(self, vertex_name):
        """Compile the terrain fragment shader against *vertex_name*.

        Returns the program, or 0 when there is no GL context yet (harmless:
        the next frame recompiles, with the context current) or the
        compile genuinely failed (reported).
        """
        if gl is None or compileProgram is None or compileShader is None:
            return 0
        if _no_current_gl_context():
            return 0
        if vertex_name in self._failed_programs:
            return 0
        try:
            vertex_code = shaders.DEFAULT_SHADERS[vertex_name]
            # The heightfield draws with flat face outputs; the block mesh
            # keeps the smooth-input fragment shader (engine/shaders.py).
            fragment_name = ('terrain_flat.frag' if vertex_name == 'terrain_indexed.vert'
                             else 'terrain.frag')
            fragment_code = shaders.light_ubo_source(
                shaders.DEFAULT_SHADERS[fragment_name])
            vertex_shader = compileShader(vertex_code, gl.GL_VERTEX_SHADER)
            fragment_shader = compileShader(fragment_code, gl.GL_FRAGMENT_SHADER)
            program = compileProgram(vertex_shader, fragment_shader, validate=False)
            if not program:
                print("ERROR: Failed to compile terrain shader program!")
                self._failed_programs.add(vertex_name)
                return 0
        except Exception as e:
            msg = str(e)
            # The Terrain can be constructed before the view's GL context is
            # current (e.g. during map load), so glCreateShader isn't bound yet.
            # Stay quiet then; only a genuine compile failure is worth reporting.
            if ("glCreateShader" in msg or "undefined alternate function" in msg
                    or "context" in msg.lower()):
                return 0
            print(f"ERROR: Exception during terrain shader compilation: {e}")
            self._failed_programs.add(vertex_name)
            return 0
        block_index = gl.glGetUniformBlockIndex(program, 'FioLightBlock')
        invalid = getattr(gl, 'GL_INVALID_INDEX', 0xFFFFFFFF)
        if block_index != invalid:
            gl.glUniformBlockBinding(program, block_index, shaders.LIGHT_UBO_BINDING)
        return program

    def _init_shader(self):
        self.shader_program = self._compile_program('terrain_indexed.vert')
        if not self.shader_program:
            return
        self._own_programs.add(int(self.shader_program))
        self._init_grass_shader()
        self.uniforms = {}

    def _init_grass_shader(self):
        try:
            vertex_code = shaders.DEFAULT_SHADERS['grass.vert']
            fragment_code = shaders.DEFAULT_SHADERS['grass.frag']
            vertex_shader = compileShader(vertex_code, gl.GL_VERTEX_SHADER)
            fragment_shader = compileShader(fragment_code, gl.GL_FRAGMENT_SHADER)
            self.grass_shader_program = compileProgram(
                vertex_shader, fragment_shader, validate=False)
        except Exception as e:
            msg = str(e)
            if ("glCreateShader" in msg or "undefined alternate function" in msg
                    or "context" in msg.lower()):
                self.grass_shader_program = 0
                return
            print(f"ERROR: Exception during grass shader compilation: {e}")
            self.grass_shader_program = 0
            return

        self.grass_uniforms = {
            'projection': gl.glGetUniformLocation(self.grass_shader_program, 'projection'),
            'view': gl.glGetUniformLocation(self.grass_shader_program, 'view'),
            'time': gl.glGetUniformLocation(self.grass_shader_program, 'time'),
            'grassColor': gl.glGetUniformLocation(self.grass_shader_program, 'grassColor'),
            'cameraPos': gl.glGetUniformLocation(self.grass_shader_program, 'cameraPos'),
            'windStrength': gl.glGetUniformLocation(self.grass_shader_program, 'windStrength'),
            'uWindDir': gl.glGetUniformLocation(self.grass_shader_program, 'uWindDir'),
            'uWindScroll': gl.glGetUniformLocation(self.grass_shader_program, 'uWindScroll'),
            'uFogEnabled': gl.glGetUniformLocation(self.grass_shader_program, 'uFogEnabled'),
            'uFogColor': gl.glGetUniformLocation(self.grass_shader_program, 'uFogColor'),
            'uFogStart': gl.glGetUniformLocation(self.grass_shader_program, 'uFogStart'),
            'uFogEnd': gl.glGetUniformLocation(self.grass_shader_program, 'uFogEnd'),
            'uFogDensity': gl.glGetUniformLocation(self.grass_shader_program, 'uFogDensity'),
            'uFogCamPos': gl.glGetUniformLocation(self.grass_shader_program, 'uFogCamPos'),
            'uAmbient': gl.glGetUniformLocation(self.grass_shader_program, 'uAmbient'),
        }
        for name in ('grassTipColor', 'uMatchGround', 'uTipAuto', 'uSegments', 'uLodStart', 'uLodEnd',
                     'uFadeStart', 'uFadeEnd', 'uBladeHeight', 'uBladeWidth',
                     'uPushers', 'uPusherCount'):
            self.grass_uniforms[name] = gl.glGetUniformLocation(
                self.grass_shader_program, name)

    def _upload_appearance_uniforms(self, u):
        for name, value in self.frame.appearance.items():
            loc = u.get(name, -1)
            if loc is None or loc == -1:
                continue
            if name == 'uPalette':
                gl.glUniform3fv(loc, len(value), np.ascontiguousarray(value, dtype=np.float32))
            elif isinstance(value, int):
                gl.glUniform1i(loc, value)
            elif isinstance(value, float):
                gl.glUniform1f(loc, value)
            elif len(value) == 2:
                gl.glUniform2f(loc, *value)
            else:
                gl.glUniform3f(loc, *value)

    def _bind_biome_map(self, u, unit):
        """Upload (when its version changed) and bind the frame's regional
        biome map; tell the program whether there is one."""
        frame = self.frame
        biome = getattr(frame, 'biome_map', None)
        enabled_loc = u.get('uBiomeEnabled', -1)
        sampler_loc = u.get('uBiomeMap', -1)
        if biome is None or frame.flat_mode:
            if enabled_loc is not None and enabled_loc != -1:
                gl.glUniform1i(enabled_loc, 0)
            # Unsampled; unit 0 holds a complete sampler2D texture.
            if sampler_loc is not None and sampler_loc != -1:
                gl.glUniform1i(sampler_loc, 0)
            return
        if not self._biome_tex:
            self._biome_tex = int(gl.glGenTextures(1))
            self._biome_gpu_version = None
        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._biome_tex)
        if self._biome_gpu_version != frame.biome_version:
            h, w = biome.shape[:2]
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
            gl.glPixelStorei(gl.GL_UNPACK_ROW_LENGTH, 0)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE,
                            np.ascontiguousarray(biome[..., :4], dtype=np.uint8))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
            self._biome_gpu_version = frame.biome_version
        loc = u.get('uBiomeBounds', -1)
        if loc is not None and loc != -1:
            gl.glUniform4f(loc, *(float(v) for v in frame.biome_bounds))
        if sampler_loc is not None and sampler_loc != -1:
            gl.glUniform1i(sampler_loc, unit)
        if enabled_loc is not None and enabled_loc != -1:
            gl.glUniform1i(enabled_loc, 1)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def _bind_empty_paint(self, unit: int):
        """Keep the paint sampler complete even when no chunk has paint.

        Drivers validate active samplers even behind uPaintEnabled == 0.
        Texture zero is incomplete and can trigger macOS GLD unloadable-array
        warnings (or a failed draw). A single transparent texel is sufficient.
        """
        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
        if not self._empty_paint_texture:
            self._empty_paint_texture = int(gl.glGenTextures(1))
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self._empty_paint_texture)
            gl.glTexImage3D(gl.GL_TEXTURE_2D_ARRAY, 0, gl.GL_RGBA8, 1, 1, 1, 0,
                            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, bytes(4))
            for pname, value in (
                    (gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                    (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                    (gl.GL_TEXTURE_MAX_LEVEL, 0),
                    (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                    (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, pname, value)
        else:
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self._empty_paint_texture)

    def _sync_gl_columns(self):
        """Grow the per-slot GL arrays to the table's capacity."""
        cap = self.frame.table.capacity
        if len(getattr(self, '_grass_count', ())) >= cap:
            return
        for name in ('_grass_vao', '_grass_vbo', '_grass_count', '_gpu_version',
                     '_paint_gpu_version', '_block_vao', '_block_vbo', '_block_count',
                     '_grass_version', '_block_version', '_slot_order'):
            old = getattr(self, name, np.zeros(0, dtype=np.int64))
            new = np.zeros(cap, dtype=np.int64)
            new[:len(old)] = old
            setattr(self, name, new)

    def _ensure_block_program(self) -> int:
        if not self.block_program:
            self.block_program = self._compile_program('terrain_mesh.vert')
            self.block_uniforms = {}
            if self.block_program:
                self._own_programs.add(int(self.block_program))
        return self.block_program

    def draw_block_slots(self, slots) -> int:
        """Draw built *slots* from their block meshes (the program is current)."""
        triangles = 0
        for slot in slots:
            slot = int(slot)
            if not self._block_vao[slot] or self._block_count[slot] <= 0:
                continue
            gl.glBindVertexArray(int(self._block_vao[slot]))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, int(self._block_count[slot]))
            triangles += int(self._block_count[slot]) // 3
        gl.glBindVertexArray(0)
        return triangles

    def _ensure_height_page(self, page: int) -> int:
        """The texture array holding height-grid page *page*, created on demand.

        One layer per table slot (slot = page * layers + layer), R32F, every
        layer the bordered LOD-0 grid size; a lower LOD uses the top-left
        corner.
        """
        if not self._page_layers:
            limit = int(gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS))
            self._page_layers = max(1, min(self.frame.height_page_layers, limit))
        while len(self._height_pages) <= page:
            tex = int(gl.glGenTextures(1))
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, tex)
            gl.glTexImage3D(gl.GL_TEXTURE_2D_ARRAY, 0, gl.GL_R32F,
                            STORED_GRID, STORED_GRID, self._page_layers, 0,
                            gl.GL_RED, gl.GL_FLOAT, None)
            for pname, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST),
                                 (gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST),
                                 (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                                 (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, pname, value)
            self._height_pages.append(tex)
        return self._height_pages[page]

    def _upload_heightfield(self, slot: int):
        """Copy a slot's height grid into its texture layer."""
        table = self.frame.table
        self._sync_gl_columns()
        if not self._page_layers:
            self._ensure_height_page(0)
        page, layer = divmod(int(slot), self._page_layers)
        tex = self._ensure_height_page(page)
        n = int(table.grid_res[slot]) + 1 + 2 * GRID_BORDER
        # Stored row i is texel row y = i, column k is x = k; the drawn grid
        # starts GRID_BORDER texels in (terrain.vert offsets by the same).
        data = np.ascontiguousarray(table.heights[slot, :n, :n], dtype=np.float32)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
        gl.glPixelStorei(gl.GL_UNPACK_ROW_LENGTH, 0)
        gl.glTexSubImage3D(gl.GL_TEXTURE_2D_ARRAY, 0, 0, 0, layer, n, n, 1,
                           gl.GL_RED, gl.GL_FLOAT, data)
        self._gpu_version[slot] = table.version[slot]

    def chunk_uniforms(self, slots):
        """``(uChunkI, uChunkX, uChunkY)`` for each of *slots*, in order.

        Python ints and floats, the floats rounded to the float32 the shader
        receives. One set of column operations for a whole draw, rather than
        a dozen NumPy scalar reads per chunk.
        """
        table = self.frame.table
        slots = np.asarray(slots, dtype=np.intp)
        res = table.grid_res[slots].astype(np.int64)
        layer = (slots % self._page_layers if self._page_layers
                 else np.zeros(len(slots), dtype=np.intp))
        lo = table.min_y[slots]
        hi = table.max_y[slots]
        cx = np.empty((len(slots), 3), dtype=np.float32)
        cx[:, :2] = table.world[slots]
        cx[:, 2] = table.size[slots] / res
        cy = np.empty((len(slots), 2), dtype=np.float32)
        cy[:, 0] = lo
        cy[:, 1] = np.where(hi > lo, hi - lo, 1.0)
        return list(zip(zip(res.tolist(), layer.tolist()),
                        cx.tolist(), cy.tolist()))

    def set_heightfield_frame_uniforms(self, u, unit):
        """Per-frame heightfield uniforms: sampler unit, tiling, gradient."""
        count, H, C, W, D = self.frame.gradient
        limit = self.frame.max_gradient_stops
        gl.glUniform1i(u['uHeights'], unit)
        gl.glUniform1f(u['uTiling'], float(np.float32(self.frame.tiling)))
        gl.glUniform1i(u['uFlatMode'], 1 if self.frame.flat_mode else 0)
        gl.glUniform1i(u['uGradCount'], count)
        gl.glUniform1fv(u['uGradH'], limit, H)
        gl.glUniform3fv(u['uGradC'], limit, C)
        gl.glUniform1fv(u['uGradW'], limit, W)
        gl.glUniform3fv(u['uGradD'], limit, D)
        # The whole terrain's height range: the vertex colour reads the
        # gradient against it (one colour per height on every chunk).
        loc = u.get('uHeightRange', -1)
        if loc != -1:
            lo, hi = (self.frame.appearance or {}).get('uHeightRange', (0.0, 1.0))
            gl.glUniform2f(loc, float(lo), float(hi))

    def _index_vao(self, res: int) -> int:
        """The vertex array a chunk of *res* quads a side is drawn with: no
        attributes (the vertex shader reads the height grid), only the index
        list of :func:`heightfield_indices`. One per resolution, made on
        first use, in the context the terrain draws in."""
        entry = self._index_vaos.get(res)
        if entry is None:
            vao = int(gl.glGenVertexArrays(1))
            buffer = int(gl.glGenBuffers(1))
            indices = heightfield_indices(res)
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, buffer)
            gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices,
                            gl.GL_STATIC_DRAW)
            entry = self._index_vaos[res] = (vao, buffer)
        return entry[0]

    def draw_heightfield_slots(self, u, slots, unit, lod_level_loc=-1,
                               paint_unit=None):
        """Draw built terrain chunks with their baked material paint."""
        table = self.frame.table
        stale = slots[self._gpu_version[slots] != table.version[slots]]
        for slot in stale:
            self._upload_heightfield(int(slot))
        order = slots.tolist()
        # Each slot's paint version, 0 where it has none; None when the map
        # has no paint, which is most maps. Uploads happen here, before the
        # loop binds any height page: an upload binds the paint page on the
        # active unit.
        paint = None
        versions = self.frame.paint_versions
        if paint_unit is not None and versions:
            paint = [versions.get(tuple(coord), 0)
                     for coord in table.coord[slots].tolist()]
            gpu_version = self._paint_gpu_version
            for slot, version in zip(order, paint):
                if version and gpu_version[slot] != version:
                    self._upload_paint_chunk(slot)
            # A version with no pixels behind it (the chunk's paint went
            # between publication and here) has no layer: draw it unpainted.
            layers = self._paint_layer
            paint = [version if slot in layers else 0
                     for slot, version in zip(order, paint)]
        bound_res = -1
        if paint_unit is not None:
            # Complete until a painted chunk binds its page over it.
            self._bind_empty_paint(paint_unit)
        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
        lods = table.lod[slots].tolist() if lod_level_loc != -1 else None
        loc_chunk_i, loc_chunk_x, loc_chunk_y = (
            u['uChunkI'], u['uChunkX'], u['uChunkY'])
        page_layers = self._page_layers
        bound_page = -1
        bound_paint_page = -1
        # The program keeps a uniform's value between draws, so uPaintEnabled
        # is sent when it changes, starting with the first chunk.
        paint_enabled = None
        triangles = 0
        for i, ((res, layer), cx, cy) in enumerate(self.chunk_uniforms(slots)):
            slot = order[i]
            page = slot // page_layers
            if page != bound_page:
                gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, self._height_pages[page])
                bound_page = page
            if paint_unit is not None:
                if paint is not None and paint[i]:
                    paint_page, paint_layer = divmod(
                        self._paint_layer[slot], self._paint_page_layers)
                    if paint_page != bound_paint_page:
                        gl.glActiveTexture(gl.GL_TEXTURE0 + paint_unit)
                        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY,
                                         self._paint_pages[paint_page])
                        bound_paint_page = paint_page
                        gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
                    if paint_enabled != 1:
                        gl.glUniform1i(u['uPaintEnabled'], 1)
                        paint_enabled = 1
                    gl.glUniform1i(u['uPaintLayer'], paint_layer)
                elif paint_enabled != 0:
                    gl.glUniform1i(u['uPaintEnabled'], 0)
                    paint_enabled = 0
            if lods is not None:
                gl.glUniform1i(lod_level_loc, lods[i])
            gl.glUniform2i(loc_chunk_i, res, layer)
            gl.glUniform3f(loc_chunk_x, *cx)
            gl.glUniform2f(loc_chunk_y, *cy)
            if res != bound_res:
                gl.glBindVertexArray(self._index_vao(res))
                bound_res = res
            glraw.draw_elements(gl, gl.GL_TRIANGLES, 6 * res * res,
                              gl.GL_UNSIGNED_INT, None)
            triangles += 2 * res * res
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindVertexArray(0)
        return triangles

    def _draw_grass(self, visible_slots, projection, view, camera_pos, env_uniforms,
                    frustum_planes=None):
        self.grass_instances_drawn = 0
        self.grass_draws = 0
        if not self.frame.grass_enabled or not self.grass_shader_program:
            return
        # A monotonic frame clock keeps wind speed independent of actual FPS.
        import time
        now = time.perf_counter()
        last = getattr(self, '_grass_last_time', now)
        step = max(0.0, min(now - last, 0.1))
        self.grass_time = (self.grass_time + step) % 100000.0
        self._grass_last_time = now
        wind_dir, wind_strength = grass_wind.resolve(self.grass_wind)
        self.grass_scroll = grass_wind.advance_scroll(
            self.grass_scroll, wind_dir, wind_strength, step)
        gl.glUseProgram(self.grass_shader_program)
        u = self.grass_uniforms
        glraw.uniform_matrix4fv(gl, u['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        glraw.uniform_matrix4fv(gl, u['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform1f(u['time'], self.grass_time)
        gl.glUniform3f(u['grassColor'], *self.frame.grass_color)
        gl.glUniform3f(u['cameraPos'], float(camera_pos.x), float(camera_pos.y), float(camera_pos.z))
        gl.glUniform1f(u['windStrength'], wind_strength)
        if u.get('uWindDir', -1) != -1:
            gl.glUniform2f(u['uWindDir'], *wind_dir)
        if u.get('uWindScroll', -1) != -1:
            gl.glUniform2f(u['uWindScroll'], *self.grass_scroll)
        gl.glUniform3f(u['grassTipColor'], *self.frame.grass_tip_colour)
        gl.glUniform1i(u['uMatchGround'], 1 if self.frame.grass_match_ground else 0)
        gl.glUniform1i(u['uTipAuto'], 1 if self.frame.grass_tip_auto else 0)
        gl.glUniform1f(u['uLodStart'], self.frame.grass_lod_start)
        gl.glUniform1f(u['uLodEnd'], self.frame.grass_lod_distance)
        gl.glUniform1f(u['uFadeStart'], min(self.frame.grass_fade_start, self.frame.grass_max_distance))
        gl.glUniform1f(u['uFadeEnd'], self.frame.grass_max_distance)
        gl.glUniform1f(u['uBladeHeight'], self.frame.grass_height)
        gl.glUniform1f(u['uBladeWidth'], self.frame.grass_blade_width)
        # Actors parting the grass (TerrainFrame.grass_pushers).
        pushers = getattr(self.frame, 'grass_pushers', None)
        count_loc = u.get('uPusherCount', -1)
        n_pushers = 0
        if count_loc is not None and count_loc != -1:
            n_pushers = 0 if pushers is None else min(len(pushers), 32)
            gl.glUniform1i(count_loc, n_pushers)
            loc = u.get('uPushers', -1)
            if n_pushers and loc is not None and loc != -1:
                gl.glUniform4fv(loc, n_pushers, np.ascontiguousarray(
                    pushers[:n_pushers], dtype=np.float32))

        if env_uniforms:
            for name, value in env_uniforms.items():
                loc = u.get(name, -1)
                if loc == -1:
                    continue
                if isinstance(value, int):
                    gl.glUniform1i(loc, value)
                elif isinstance(value, float):
                    gl.glUniform1f(loc, value)
                else:
                    gl.glUniform3f(loc, *value)

        # Opaque tapered blades. Explicitly restore the depth state here:
        # grass must test against the already-rendered terrain, not inherit
        # depth state from a preceding renderer pass.
        gl.glDisable(gl.GL_BLEND)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glDepthMask(gl.GL_TRUE)
        cull_was = bool(gl.glIsEnabled(gl.GL_CULL_FACE))
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        dist_sq = self.frame.table.nearest_dist_sq(
            visible_slots, float(camera_pos.x), float(camera_pos.z))
        max_sq = self.frame.grass_max_distance * self.frame.grass_max_distance
        planes = (None if frustum_planes is None
                  else np.asarray(frustum_planes, dtype=np.float64).reshape(-1, 4))
        blade_height = float(self.frame.grass_height)
        blade_width = float(self.frame.grass_blade_width)
        lod_sq = self.frame.grass_lod_distance * self.frame.grass_lod_distance
        if self._base_instance is None:
            self._base_instance = bool(glraw.has_base_instance())
        last_segments = None
        near = (float(camera_pos.x), float(camera_pos.z),
                float(self.frame.grass_lod_distance))
        # Where actors part the grass: (x, z, radius). A run of cells none
        # of them reaches draws with no pushers, so its vertices skip the
        # shader's per-actor loop -- the costliest part of a far blade.
        push_circles = (np.asarray(pushers[:n_pushers], dtype=np.float64)[:, :3]
                        if n_pushers else None)
        pushers_on = n_pushers
        for slot, d in zip(visible_slots, dist_sq):
            if self._grass_count[slot] <= 0 or not self._grass_vao[slot]:
                continue
            if d > max_sq:
                continue
            # Cells (or, without them, whole chunks) swap between detailed
            # and single-triangle blades. The shader has already morphed every
            # blade past GRASS_LOD_DISTANCE onto the far shape, and a cell's
            # nearest point is never further than any of its blades, so the
            # swap cannot be seen.
            runs = self._grass_runs(int(slot), planes, blade_height, blade_width,
                                    near, d < lod_sq, push_circles)
            if not runs:
                continue
            gl.glBindVertexArray(int(self._grass_vao[slot]))
            for start, count, detailed, pushed in runs:
                segments = self.frame.grass_segments if detailed else 1
                if segments != last_segments:
                    gl.glUniform1i(u['uSegments'], segments)
                    last_segments = segments
                wanted = n_pushers if pushed else 0
                if wanted != pushers_on:
                    gl.glUniform1i(count_loc, wanted)
                    pushers_on = wanted
                self._draw_grass_run(slot, grass_vertex_count(segments), start, count)
                self.grass_instances_drawn += count
                self.grass_draws += 1
        gl.glBindVertexArray(0)
        # Grass blades are double-sided. Put culling back the way it was
        # found -- the terrain pass runs with it off. Forcing it on leaked
        # into Qt's overlay painter, which then culled the SysMon panel.
        if cull_was:
            gl.glEnable(gl.GL_CULL_FACE)

    def _ensure_placeholder_cubemap(self) -> int:
        """Lazily create a 1x1 complete cube-map used for shadow sampler units
        that have no real depth cube-map (shadows off, or fewer cube-maps than
        sampler slots).  A complete texture on every unit guarantees no
        samplerCube is left referencing texture unit 0 or an incomplete texture,
        either of which can make glDrawArrays raise GL_INVALID_OPERATION."""
        if self._placeholder_cubemap:
            return self._placeholder_cubemap
        tex = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, tex)
        black = (ctypes.c_ubyte * 4)(0, 0, 0, 255)
        for face in range(6):
            gl.glTexImage2D(gl.GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, 0, gl.GL_RGBA,
                            1, 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, black)
        gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_CUBE_MAP, gl.GL_TEXTURE_WRAP_R, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, 0)
        self._placeholder_cubemap = tex
        return self._placeholder_cubemap

    #: Mip levels a paint page has beyond the first. Enough that paint in
    #: the distance does not shimmer; few enough that a chunk's edge texels
    #: are not averaged far into its neighbour's missing ones.
    PAINT_MIP_LEVELS = 3

    def _ensure_paint_page(self, page: int) -> int:
        if not self._paint_page_layers:
            limit = int(gl.glGetIntegerv(gl.GL_MAX_ARRAY_TEXTURE_LAYERS))
            self._paint_page_layers = max(1, min(self.frame.paint_page_layers, limit))
        while len(self._paint_pages) <= page:
            tex = int(gl.glGenTextures(1))
            gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, tex)
            side = int(self.frame.paint_resolution)
            levels = 0
            for level in range(self.PAINT_MIP_LEVELS + 1):
                if side >> level < 1:
                    break
                gl.glTexImage3D(
                    gl.GL_TEXTURE_2D_ARRAY, level, gl.GL_RGBA8,
                    side >> level, side >> level,
                    self._paint_page_layers, 0,
                    gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
                levels = level
            for pname, value in (
                (gl.GL_TEXTURE_BASE_LEVEL, 0),
                (gl.GL_TEXTURE_MAX_LEVEL, levels),
                (gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR),
                (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
                gl.glTexParameteri(gl.GL_TEXTURE_2D_ARRAY, pname, value)
            # Seen at a grazing angle -- which the ground mostly is -- plain
            # trilinear filtering picks a mip for the squashed axis and blurs
            # the other: bias it back a level (core GL), and filter along
            # the squash where the driver can (an extension nearly all have).
            gl.glTexParameterf(gl.GL_TEXTURE_2D_ARRAY, gl.GL_TEXTURE_LOD_BIAS,
                               self.PAINT_LOD_BIAS)
            anisotropy = self._paint_anisotropy()
            if anisotropy > 1.0:
                gl.glTexParameterf(gl.GL_TEXTURE_2D_ARRAY,
                                   _TEXTURE_MAX_ANISOTROPY, anisotropy)
            self._paint_pages.append(tex)
        return self._paint_pages[page]

    PAINT_LOD_BIAS = -1.0
    PAINT_ANISOTROPY = 4.0

    def _paint_anisotropy(self):
        """Anisotropic samples for paint pages, 1.0 where unsupported."""
        if self._paint_anisotropy_limit is None:
            limit = 1.0
            try:
                count = int(gl.glGetIntegerv(gl.GL_NUM_EXTENSIONS))
                names = {gl.glGetStringi(gl.GL_EXTENSIONS, i).decode('ascii', 'replace')
                         for i in range(count)}
                if ('GL_EXT_texture_filter_anisotropic' in names
                        or 'GL_ARB_texture_filter_anisotropic' in names):
                    limit = float(gl.glGetFloatv(_MAX_TEXTURE_MAX_ANISOTROPY))
            except Exception:
                limit = 1.0
            self._paint_anisotropy_limit = limit
        return max(1.0, min(self.PAINT_ANISOTROPY, self._paint_anisotropy_limit))

    def _release_paint_layer(self, slot: int):
        layer = self._paint_layer.pop(int(slot), None)
        if layer is not None:
            self._paint_layers_free.append(layer)

    def _release_paint_layers(self):
        """Every paint layer back: the paint was replaced wholesale."""
        self._paint_layer.clear()
        self._paint_layers_free = []
        self._paint_layers_used = 0

    @staticmethod
    def _paint_mip(paint):
        """*paint* (n, n, 4 uint8) at half the side, colour weighted by alpha
        (an unpainted texel is black, and must not darken its neighbours)."""
        n = paint.shape[0] // 2
        blocks = paint[:n * 2, :n * 2].reshape(n, 2, n, 2, 4).astype(np.float32)
        alpha = blocks[..., 3:4]
        weight = alpha.sum(axis=(1, 3))
        colour = (blocks[..., :3] * alpha).sum(axis=(1, 3))
        np.divide(colour, weight, out=colour, where=weight > 0.0)
        out = np.empty((n, n, 4), dtype=np.uint8)
        out[..., :3] = np.clip(colour + 0.5, 0, 255)
        out[..., 3:4] = np.clip(weight * 0.25 + 0.5, 0, 255)
        return out

    def _upload_paint_chunk(self, slot: int):
        table = self.frame.table
        self._sync_gl_columns()
        slot = int(slot)
        coord = (int(table.coord[slot, 0]), int(table.coord[slot, 1]))
        paint = self.frame.paint_display.get(coord)
        if paint is None:
            paint = self.frame.paint_maps.get(coord)
        if paint is None:
            self._paint_gpu_version[slot] = 0
            self._release_paint_layer(slot)
            return
        if not self._paint_page_layers:
            self._ensure_paint_page(0)
        number = self._paint_layer.get(slot)
        if number is None:
            if self._paint_layers_free:
                number = self._paint_layers_free.pop()
            else:
                number = self._paint_layers_used
                self._paint_layers_used += 1
            self._paint_layer[slot] = number
        page, layer = divmod(number, self._paint_page_layers)
        tex = self._ensure_paint_page(page)
        data = np.ascontiguousarray(paint, dtype=np.uint8)
        gl.glBindTexture(gl.GL_TEXTURE_2D_ARRAY, tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
        gl.glPixelStorei(gl.GL_UNPACK_ROW_LENGTH, 0)
        side = int(self.frame.paint_resolution)
        for level in range(self.PAINT_MIP_LEVELS + 1):
            if side >> level < 1:
                break
            if level:
                data = np.ascontiguousarray(self._paint_mip(data))
            gl.glTexSubImage3D(
                gl.GL_TEXTURE_2D_ARRAY, level, 0, 0, layer,
                side >> level, side >> level, 1,
                gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)
        self._paint_gpu_version[slot] = self.frame.paint_versions.get(coord, 0)

    # -- slots ------------------------------------------------------------

    def _adopt(self, table):
        """Match the per-slot GL columns to the published table: a slot that
        was freed, or freed and given to another chunk (its allocation
        ``order`` moved), loses the grass, block mesh and paint it held."""
        self._sync_gl_columns()
        n = min(len(self._slot_order), table.capacity)
        if not n:
            return
        current = np.where(table.live[:n], table.order[:n], -1)
        changed = np.flatnonzero(self._slot_order[:n] != current)
        if len(changed):
            self._free_slots(changed)
            self._slot_order[changed] = current[changed]

    def _free_grass(self, slots):
        """Delete the grass buffers of *slots*."""
        for slot in slots:
            slot = int(slot)
            if self._grass_vao[slot]:
                gl.glDeleteVertexArrays(1, [int(self._grass_vao[slot])])
            if self._grass_vbo[slot]:
                gl.glDeleteBuffers(1, [int(self._grass_vbo[slot])])
            self._grass_vao[slot] = self._grass_vbo[slot] = 0
            self._grass_count[slot] = 0
            self._grass_version[slot] = 0
            self._grass_cells.pop(slot, None)

    def _free_slots(self, slots):
        self._free_grass(slots)
        for slot in slots:
            slot = int(slot)
            if self._block_vao[slot]:
                gl.glDeleteVertexArrays(1, [int(self._block_vao[slot])])
            if self._block_vbo[slot]:
                gl.glDeleteBuffers(1, [int(self._block_vbo[slot])])
            self._block_vao[slot] = self._block_vbo[slot] = 0
            self._block_count[slot] = 0
            self._block_version[slot] = 0
            self._paint_gpu_version[slot] = 0
            self._release_paint_layer(slot)
            self._gpu_version[slot] = 0

    def _product(self, store, slot):
        """The published product of *slot* in *store*, if it was built for
        the chunk the slot holds now: ``(version, data)`` or None."""
        entry = store.get(int(slot))
        if entry is None or entry[1] != int(self.frame.table.order[slot]):
            return None
        return entry[0], entry[2]

    def _upload_block_mesh(self, slot: int):
        entry = self._product(self.frame.products.blocks, slot)
        if entry is None:
            return
        version, data = entry
        if not self._block_vao[slot]:
            self._block_vao[slot] = int(gl.glGenVertexArrays(1))
            self._block_vbo[slot] = int(gl.glGenBuffers(1))
        gl.glBindVertexArray(int(self._block_vao[slot]))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, int(self._block_vbo[slot]))
        gl.glBufferData(gl.GL_ARRAY_BUFFER, max(data.nbytes, 4),
                        data if data.nbytes else None, gl.GL_STATIC_DRAW)
        stride = 14 * 4
        for loc, size, offset in ((0, 3, 0), (1, 3, 12), (2, 3, 24), (3, 2, 36), (4, 3, 44)):
            gl.glVertexAttribPointer(loc, size, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                     ctypes.c_void_p(offset))
            gl.glEnableVertexAttribArray(loc)
        gl.glBindVertexArray(0)
        self._block_count[slot] = len(data)
        self._block_version[slot] = version

    def _grass_runs(self, slot, planes, blade_height, blade_width,
                    near=None, detailed=True, pushers=None):
        """``[(first instance, count, detailed, pushed)]`` of *slot*'s grass
        to draw: its cells inside the frustum, neighbouring ones merged into
        one run.

        *near* is ``(x, z, distance)``: a cell wholly further than *distance*
        from (x, z) -- the grass's detail distance from the camera point --
        draws its blades as single triangles, the shape the shader has
        already morphed them into there, so the change cannot be seen. A run
        never mixes the two. Without cells (or *near*) the run takes
        *detailed*.

        *pushers* are the ``(x, z, radius)`` of the actors parting the grass
        (or None): a run is *pushed* when one of them reaches a blade root in
        it; the rest need no parting."""
        total = int(self._grass_count[slot])
        cells = self._grass_cells.get(slot)
        anyone = pushers is not None and len(pushers) > 0
        if planes is None or cells is None:
            return [(0, total, detailed, anyone)]
        starts, counts, boxes = cells
        # 0: out of view; 1: in view, far; 2: in view, detailed.
        kind = _visible_cells(boxes, planes, blade_height, blade_width).astype(np.int8)
        if near is not None and detailed:
            x, z, reach = near
            dx = np.maximum(np.maximum(boxes[:, 0] - x, x - boxes[:, 1]), 0.0)
            dz = np.maximum(np.maximum(boxes[:, 5] - z, z - boxes[:, 6]), 0.0)
            kind *= np.where(dx * dx + dz * dz < reach * reach, 2, 1).astype(np.int8)
        elif detailed:
            kind *= 2
        if anyone:
            # A pusher reaches a cell when its circle meets the cell's roots.
            px, pz, pr = pushers[:, 0], pushers[:, 1], pushers[:, 2]
            gx = np.maximum(np.maximum(boxes[:, 0, None] - px, px - boxes[:, 1, None]), 0.0)
            gz = np.maximum(np.maximum(boxes[:, 5, None] - pz, pz - boxes[:, 6, None]), 0.0)
            pushed = (gx * gx + gz * gz < pr * pr).any(axis=1)
            kind = np.where(kind > 0, kind + 2 * pushed, 0).astype(np.int8)
        if not kind.any():
            return []
        # The occupied cells lie end to end in the buffer, so a stretch of
        # cells of one kind is one run.
        edges = np.flatnonzero(np.diff(kind)) + 1
        bounds = np.concatenate(([0], edges, [len(kind)]))
        runs = []
        for first, stop in zip(bounds[:-1], bounds[1:]):
            if kind[first]:
                begin = int(starts[first])
                k = int(kind[first])
                runs.append((begin, int(starts[stop - 1] + counts[stop - 1]) - begin,
                             k in (2, 4), k >= 3))
        return _merge_small_runs(runs)

    def _draw_grass_run(self, slot, vertices, start, count):
        """Draw *count* of *slot*'s blades from instance *start* (its VAO bound)."""
        if start == 0:
            gl.glDrawArraysInstanced(gl.GL_TRIANGLES, 0, vertices, count)
        elif self._base_instance:
            gl.glDrawArraysInstancedBaseInstance(gl.GL_TRIANGLES, 0, vertices, count, start)
        else:
            # No base instance (macOS's GL 4.1): point the instance
            # attributes at the run, draw, and point them back.
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, int(self._grass_vbo[slot]))
            self._grass_attributes(start * 9 * 4)
            gl.glDrawArraysInstanced(gl.GL_TRIANGLES, 0, vertices, count)
            self._grass_attributes(0)

    @staticmethod
    def _grass_attributes(base):
        stride = 9 * 4
        for loc, size, offset in ((6, 3, 24), (2, 3, 0), (3, 1, 12), (4, 1, 16), (5, 1, 20)):
            gl.glVertexAttribPointer(loc, size, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                     ctypes.c_void_p(base + offset))

    def _upload_grass_chunk(self, slot: int):
        """Upload a slot's published grass instances (``(n, 9)`` float32)."""
        entry = self._product(self.frame.products.grass, slot)
        if entry is None:
            return
        version, data = entry
        count = len(data)
        self._grass_version[slot] = version
        if count <= 0:
            self._grass_count[slot] = 0
            self._grass_cells.pop(slot, None)
            return
        table = self.frame.table
        data, starts, counts, boxes = _sort_grass_cells(
            data, float(table.world[slot, 0]), float(table.world[slot, 1]),
            float(table.size[slot]))
        self._grass_cells[slot] = (starts, counts, boxes)
        if not self._grass_vao[slot]:
            self._grass_vao[slot] = int(gl.glGenVertexArrays(1))
            self._grass_vbo[slot] = int(gl.glGenBuffers(1))
        gl.glBindVertexArray(int(self._grass_vao[slot]))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, int(self._grass_vbo[slot]))
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)
        self._grass_attributes(0)
        for loc in (6, 2, 3, 4, 5):
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribDivisor(loc, 1)
        gl.glBindVertexArray(0)
        self._grass_count[slot] = count

    def _stale(self, store, held, slots):
        """Those of *slots* whose published product in *store* is not the
        version *held* records."""
        table = self.frame.table
        out = []
        for slot in slots.tolist():
            entry = store.get(slot)
            if (entry is not None and entry[0] != held[slot]
                    and entry[1] == int(table.order[slot])):
                out.append(slot)
        return out

    # -- the frame --------------------------------------------------------

    def render(self, frame, projection, view, camera_pos, frustum_planes=None,
               active_lights_count=0, shadow_cubemaps=None, shadow_unit_base=4,
               env_uniforms=None, draw_grass=True, grass_wind=None):
        """Draw the published *frame* with the current GL context.

        ``draw_grass=False`` leaves the grass pass out whatever the frame
        asks for (the renderer's ``[Renderer] grass`` setting).
        *grass_wind* is ``(dir x, dir z, strength)`` for the grass to sway
        in (core/grass_wind.py), or None for the default breeze."""
        self.visible_chunks = 0
        self.culled_chunks = 0
        self.total_triangles = 0
        if frame is None or not frame.enabled:
            return
        self.frame = frame
        self.grass_wind = grass_wind
        try:
            self._render(projection, view, camera_pos, frustum_planes,
                         active_lights_count, shadow_cubemaps, shadow_unit_base,
                         env_uniforms, draw_grass)
        finally:
            self.frame = None

    def _render(self, projection, view, camera_pos, frustum_planes,
                active_lights_count, shadow_cubemaps, shadow_unit_base,
                env_uniforms, draw_grass=True):
        frame = self.frame
        if not self.shader_program:
            self._init_shader()
        prog = self.shader_program
        if not prog:
            return
        u = self.uniforms
        # Blocks are drawn from per-chunk meshes by their own vertex shader;
        # everything else from the heightfield.
        blocks = frame.blocks and bool(self._ensure_block_program())
        if blocks:
            prog = self.block_program
            u = self.block_uniforms

        # The grass program is compiled when a context is first current.
        grass = bool(frame.grass_enabled and draw_grass)
        if grass and not self.grass_shader_program:
            self._init_grass_shader()

        # Re-resolve late-bound uniforms against the *current* program. A
        # renderer can hand in its own program whose uniform table covers a
        # subset of locations (ForwardRenderer.setup_terrain_shader), so any
        # sampler relied on must be looked up here or it stays unbound: an
        # unassigned ``samplerCube`` defaults to texture unit 0, collides
        # with the ``sampler2D`` terrain textures there, and makes the draw
        # raise GL_INVALID_OPERATION.
        names = self.UNIFORM_NAMES + tuple(frame.appearance) + tuple(env_uniforms or ())
        names += tuple(f'shadowMaps[{i}]' for i in range(shaders.MAX_SHADOW_LIGHTS))
        for name in names:
            if name not in u:
                u[name] = gl.glGetUniformLocation(prog, name)

        table = frame.table
        self._adopt(table)
        if self._paint_epoch != frame.paint_epoch:
            self._paint_gpu_version[:] = 0
            self._release_paint_layers()
            self._paint_epoch = frame.paint_epoch

        gl.glUseProgram(prog)
        glraw.uniform_matrix4fv(gl, u['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        glraw.uniform_matrix4fv(gl, u['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glActiveTexture(gl.GL_TEXTURE0); gl.glBindTexture(gl.GL_TEXTURE_2D, self.grass_tex); gl.glUniform1i(u['texGrass'], 0)
        gl.glActiveTexture(gl.GL_TEXTURE1); gl.glBindTexture(gl.GL_TEXTURE_2D, self.rock_tex);  gl.glUniform1i(u['texRock'],  1)
        gl.glActiveTexture(gl.GL_TEXTURE2); gl.glBindTexture(gl.GL_TEXTURE_2D, self.sand_tex);  gl.glUniform1i(u['texSand'],  2)
        gl.glActiveTexture(gl.GL_TEXTURE3); gl.glBindTexture(gl.GL_TEXTURE_2D, self.snow_tex);  gl.glUniform1i(u['texSnow'],  3)
        height_texture_unit = shadow_unit_base + shaders.MAX_SHADOW_LIGHTS
        paint_texture_unit = height_texture_unit + 1
        self._upload_appearance_uniforms(u)
        self._bind_biome_map(u, self.BIOME_TEXTURE_UNIT)
        loc = u.get('terrainPaintMap', -1)
        if loc != -1:
            gl.glUniform1i(loc, paint_texture_unit)

        # Textures off in flat mode, or while they are not loaded.
        textures_loaded = (self.grass_tex != 0 and self.rock_tex != 0
                           and self.sand_tex != 0 and self.snow_tex != 0)
        use_tex = 0 if frame.flat_mode or not textures_loaded else (1 if frame.use_textures else 0)
        gl.glUniform1i(u['use_textures'], use_tex)

        # Distance fog + global ambient (engine.shaders.FOG_GLSL): this
        # program has its own uniform table, so the renderer hands the
        # resolved values across rather than writing them itself.
        if env_uniforms:
            for name, value in env_uniforms.items():
                loc = u.get(name, -1)
                if loc is None or loc == -1:
                    continue
                if isinstance(value, int):
                    gl.glUniform1i(loc, value)
                elif isinstance(value, float):
                    gl.glUniform1f(loc, value)
                else:
                    gl.glUniform3f(loc, *value)

        # The renderer has already selected the terrain light subset and
        # packed it into the shared std140 light UBO.
        gl.glUniform1i(u['active_lights'], active_lights_count)

        # Every ``samplerCube shadowMaps[i]`` must point at its own reserved
        # unit, with a *complete* cube map bound there -- the real depth map,
        # or a 1x1 placeholder -- shadows on or off: samplers default to unit
        # 0, which holds a ``sampler2D``, and two sampler types on one unit
        # (or an incomplete texture on an active one) fail the next draw.
        shadow_cubemaps = shadow_cubemaps or []
        placeholder = self._ensure_placeholder_cubemap()
        for i in range(shaders.MAX_SHADOW_LIGHTS):
            loc = u.get(f'shadowMaps[{i}]', -1)
            if loc is None or loc == -1:
                continue
            cm = shadow_cubemaps[i] if (i < len(shadow_cubemaps) and shadow_cubemaps[i]) else placeholder
            gl.glActiveTexture(gl.GL_TEXTURE0 + shadow_unit_base + i)
            gl.glBindTexture(gl.GL_TEXTURE_CUBE_MAP, cm)
            gl.glUniform1i(loc, shadow_unit_base + i)
        gl.glActiveTexture(gl.GL_TEXTURE0)

        lod_level_loc = u.get('lod_level', -1)
        slots = table.live_slots()
        # The frustum (far plane included, so the view distance applies)
        # decides what is drawn; which chunks exist and at what detail was
        # decided by the terrain, before the frame.
        visible = table.visible(slots, frustum_planes)
        self.culled_chunks = int(len(slots) - np.count_nonzero(visible))

        if frame.wireframe: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        # The height grids live in texture units above the shadow cube-maps.
        unit = height_texture_unit
        drawn = slots[visible & table.built[slots]]
        if blocks:
            for slot in self._stale(frame.products.blocks, self._block_version, drawn):
                self._upload_block_mesh(slot)
            # Block meshes carry no paint; the sampler still needs a
            # complete texture behind it.
            self._bind_empty_paint(paint_texture_unit)
            loc = u.get('uPaintEnabled', -1)
            if loc is not None and loc != -1:
                gl.glUniform1i(loc, 0)
            gl.glActiveTexture(gl.GL_TEXTURE0)
            self.total_triangles = self.draw_block_slots(drawn)
        else:
            self.set_heightfield_frame_uniforms(u, unit)
            self.total_triangles = self.draw_heightfield_slots(
                u, drawn, unit, lod_level_loc, paint_texture_unit)
        self.visible_chunks = int(len(drawn))
        #: The slots drawn this frame, in draw order (tests, Debug Tables).
        self.drawn_slots = drawn
        if frame.wireframe: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        if grass and self.grass_shader_program:
            built = slots[table.built[slots]]
            # Grass the terrain gave back (a chunk far out of view, the
            # store cleared): its buffers go; it is uploaded again when the
            # terrain regrows it.
            published = frame.products.grass
            held = np.flatnonzero(self._grass_version)
            if len(held):
                self._free_grass([slot for slot in held.tolist()
                                  if slot not in published])
            for slot in self._stale(published, self._grass_version, built):
                self._upload_grass_chunk(slot)
            candidates = built[self._grass_count[built] > 0]
            visible_grass = candidates[table.visible(candidates, frustum_planes)]
            self._draw_grass(visible_grass, projection, view, camera_pos, env_uniforms,
                             frustum_planes)

    # -- lifetime ---------------------------------------------------------

    def adopt_program(self, program, uniforms):
        """Draw the heightfield with a renderer's own *program* from now on."""
        self.shader_program = program
        self.uniforms = uniforms

    def cleanup(self):
        """Delete every GL name held (the owning context is current)."""
        self._free_slots(range(len(self._grass_vao)))
        for program in sorted(self._own_programs):
            try:
                gl.glDeleteProgram(program)
            except Exception:
                pass
        self._own_programs.clear()
        if self.grass_shader_program:
            try:
                gl.glDeleteProgram(self.grass_shader_program)
            except Exception:
                pass
        self.shader_program = self.block_program = self.grass_shader_program = 0
        self.uniforms, self.block_uniforms, self.grass_uniforms = {}, {}, {}
        for pages in (self._paint_pages, self._height_pages):
            if pages:
                try:
                    gl.glDeleteTextures(len(pages), pages)
                except Exception:
                    pass
        self._paint_pages, self._height_pages = [], []
        self._paint_page_layers = 0
        self._release_paint_layers()
        for vao, buffer in self._index_vaos.values():
            gl.glDeleteVertexArrays(1, [vao])
            gl.glDeleteBuffers(1, [buffer])
        self._index_vaos = {}
        if self._placeholder_cubemap:
            gl.glDeleteTextures(1, [self._placeholder_cubemap])
            self._placeholder_cubemap = 0
        for name in ('_empty_paint_texture', '_biome_tex'):
            if getattr(self, name):
                try:
                    gl.glDeleteTextures(1, [getattr(self, name)])
                except Exception:
                    pass
                setattr(self, name, 0)
        self._biome_gpu_version = None
        self.grass_tex = self.rock_tex = self.sand_tex = self.snow_tex = 0
        self._sync_gl_columns_reset()
