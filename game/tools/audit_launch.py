"""Launch audit: the game started as a player starts it, and every hitch.

    LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a -s "-screen 0 1600x900x24" \\
        python game/tools/audit_launch.py [--map maps/miniwind_world.json]
            [--seconds 60] [--route millbrook|country|still] [--sprint]
            [--continue] [--size 960x540] [--json OUT] [--no-sampler]

Runs ``main.py`` itself, unchanged, with the launcher answering PLAY the
moment it has painted, so what is timed is the shipped path:

* **cold start to menu** -- interpreter start to the launcher's first paint;
* **menu to in-world** -- PLAY to the first frame painted in the world (the
  character-creation screen of a new game), with every loading-bar stage
  (``LoadingOverlay.step``) and its time;
* **new character to play** -- the character made (``begin_new_character``)
  and the screen closed, to the first gameplay frame;
* ``--continue``: after the opening, an autosave is written and loaded
  through the pause menu's own action (``PauseActions.load_named``), timed
  from the request to the first frame painted after it;
* **play** -- *seconds* of play driven along a route (``millbrook``: the
  village streets on foot; ``country``: out of Millbrook into open country;
  ``--sprint`` holds Shift), painted by Qt's own frame loop.

Every frame is logged. A **hitch** is a frame whose interval exceeds the
run's median interval by more than one 60 Hz frame (16.7 ms): under software
GL every frame is ~100 ms of llvmpipe, so "over 16.7 ms" would be all of
them; the excess over the median is the part a real GPU would also show.
Each hitch is attributed from

* named spans (shader compiles, texture / model / sound loads, terrain chunk
  and grass builds, paint uploads, the world-map picture, sprite sheets),
  timed on whichever thread ran them; and
* a stack sampler (``sys._current_frames`` every ``--sample-ms``) on the
  main and logic threads, its samples in the frame classified by the same
  categories, so work no span names still shows up (by function);
* the garbage collector's own callbacks.

Logic ticks over 16.7 ms are logged too, attributed the same way. Counts and
bytes (textures uploaded, chunks built, draw calls) are reported for the
first second in the world and for the whole run, as they carry over to real
GPUs where the software-GL timings do not. ``settings.ini`` is restored.
"""

import argparse
import collections
import gc
import json
import math
import os
import runpy
import statistics
import sys
import threading
import time

T0 = time.perf_counter()
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument('--map', default='maps/miniwind_world.json')
ap.add_argument('--seconds', type=float, default=60.0)
ap.add_argument('--route', default='millbrook', choices=('millbrook', 'country', 'still'))
ap.add_argument('--sprint', action='store_true')
ap.add_argument('--continue', dest='cont', action='store_true')
ap.add_argument('--launch-continue', action='store_true',
                help="answer the launcher's CONTINUE (the newest save) instead of PLAY")
ap.add_argument('--noclip', action='store_true',
                help="the player's physics off (the console's noclip): the route is followed through "
                     "walls and fences, for streaming and drawing costs; tick costs are then not representative")
ap.add_argument('--size', default='960x540')
ap.add_argument('--travel', action='append', default=[], metavar='MAP',
                help='after the opening, travel to MAP as a LevelChanger does (repeatable, in order), timed to its first frame')
ap.add_argument('--json')
ap.add_argument('--sample-ms', type=float, default=2.0)
ap.add_argument('--no-sampler', action='store_true')
ap.add_argument('--capture-play', metavar='PNG',
                help='save a picture of the window 3 s into the measured play')
ap.add_argument('--capture-loading', metavar='DIR',
                help='save a picture of the window at every loading-bar stage (perturbs timing)')
ap.add_argument('--trace-tuples', action='store_true',
                help='with --gc-census: where the tuples surviving into the oldest generation were allocated (tracemalloc from play on; slows everything)')
ap.add_argument('--gc-census', action='store_true',
                help='every 5 s of play: unfrozen objects tracked, and which types grew (perturbs timing)')
ap.add_argument('--tree', default=os.path.join(HERE, '..', '..'))
args = ap.parse_args()
tree = os.path.abspath(args.tree)
os.chdir(tree)
sys.path[:0] = [tree]
os.environ.setdefault('PYOPENGL_ERROR_CHECKING', '0')
os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
SETTINGS = os.path.join(tree, 'settings.ini')
SAVED_SETTINGS = open(SETTINGS, 'rb').read()
WIDTH, HEIGHT = (int(v) for v in args.size.lower().split('x'))
BUDGET_MS = 1000.0 / 60.0


def rss_mb():
    with open('/proc/self/statm') as f:
        return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 2**20


def now_ms():
    return (time.perf_counter() - T0) * 1e3


# --------------------------------------------------------------- settings
# Windowed at --size, the default map, no launcher skip: everything else is
# the user's settings.ini as shipped. Restored at exit.
import configparser                                           # noqa: E402
_cfg = configparser.ConfigParser()
_cfg.optionxform = str
_cfg.read(SETTINGS)
_cfg.setdefault('Kiosk', {})
_cfg['Kiosk']['window_mode'] = 'Windowed'
_cfg['Kiosk']['res_width'] = str(WIDTH)
_cfg['Kiosk']['res_height'] = str(HEIGHT)
_cfg['Startup']['default_map'] = args.map
_cfg['Startup']['show_launcher'] = 'True'
with open(SETTINGS, 'w') as f:
    _cfg.write(f)

# ------------------------------------------------------------ the record
marks = []            # (name, ms since T0, rss MB)
stages = []           # loading-bar steps: (ms, stage, percent)
spans = collections.defaultdict(list)   # label -> [(start_ms, dur_ms, thread)]
gc_events = []        # (start_ms, dur_ms, generation)
frames = []           # (start_ms, paint_ms)
ticks = []            # (start_ms, dur_ms)
# The stack samples, in columns the collector never walks: sample time (ms),
# thread (0 main, 1 logic) and the index of its stack in `stacks`. Kept as
# tuples they were ~1000 objects a second surviving into the oldest
# generation -- the audit's own, inflating every full collection it timed.
import array                                                  # noqa: E402
sample_ms = array.array('d')
sample_thread = array.array('b')
sample_stack = array.array('i')
stacks = []           # each distinct stack once: tuple of (file, func)
stack_ids = {}
THREAD_KEYS = ('main', 'logic')


def samples():
    """``(ms, thread key, stack)`` of every sample."""
    for t, key, index in zip(sample_ms, sample_thread, sample_stack):
        yield t, THREAD_KEYS[key], stacks[index]
counters = collections.Counter()
slow_calls = []       # (ms, label, first str arg, dur ms): span calls over 2 ms


def mark(name):
    marks.append((name, round(now_ms(), 1), round(rss_mb(), 1)))
    print(f'[audit] {now_ms():9.1f} ms  {name}', flush=True)


def span(owner, name, label, count_bytes=None):
    """Time every call of ``owner.name`` under *label* (any thread)."""
    real = getattr(owner, name)

    def timed(*a, **k):
        started = time.perf_counter()
        try:
            return real(*a, **k)
        finally:
            end = time.perf_counter()
            spans[label].append(((started - T0) * 1e3, (end - started) * 1e3,
                                 threading.current_thread().name))
            if end - started > 0.002:
                # Which one: the first string argument of a slow call, and
                # who asked for it (three callers up).
                what = next((x for x in a if isinstance(x, str)), '')
                callers, frame = [], sys._getframe(1)
                while frame is not None and len(callers) < 3:
                    callers.append(f'{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}')
                    frame = frame.f_back
                slow_calls.append((round((started - T0) * 1e3, 1), label, what[-60:],
                                   round((end - started) * 1e3, 1), ' < '.join(callers)))

    timed.__wrapped__ = real
    setattr(owner, name, timed)


def gc_watch(phase, info):
    if phase == 'start':
        gc_watch.t = time.perf_counter()
    elif getattr(gc_watch, 't', None) is not None:
        gc_events.append(((gc_watch.t - T0) * 1e3,
                          (time.perf_counter() - gc_watch.t) * 1e3, info['generation']))
        gc_watch.t = None


gc.callbacks.append(gc_watch)

# --------------------------------------------------------------- sampler
# Categories, most specific first: the first one found anywhere in a stack
# (innermost frame first) names the sample.
CATEGORIES = [
    ('shader compile', ('compileShader', 'compileProgram', '_compile_program', 'glLinkProgram')),
    ('GC', ()),
    ('world-map picture', ('worldmap.py', 'map_page.py')),
    ('paint upload', ('_upload_paint_chunk', '_upload_paint', 'paint_upload')),
    ('grass build', ('_build_grass', '_generate_grass_blades', 'meadow.py')),
    ('terrain chunk build/upload', ('_build_chunk', '_chunk_heights', '_collect_built', '_store_heights',
                                    '_stream_chunks', '_upload_heightfield', '_upload_block_mesh',
                                    '_upload_grass_chunk', '_ensure_height_page', 'terrain_table.py')),
    ('model first use', ('glb_loader.py', 'obj_loader.py', 'load_model', 'entity_models.py')),
    ('texture first use', ('load_texture', 'textures.py', 'decal_textures.py', 'glTexImage2D',
                           'glTexSubImage2D', 'item_icons.py', 'asset_qt.py')),
    ('sprite/atlas build', ('sprite_layers.py', 'overhead_sprite.py', 'atlas', 'heads')),
    ('audio load', ('view_audio.py', 'speaker_audio.py', 'music.py', 'audio_archives.py', 'mixer')),
    ('UI paint (HUD, panels, fonts)', ('game/ui/', 'view_hud.py', 'paint_cache.py', 'floating_windows.py')),
    ('nav / roads', ('navigation.py', 'road_nav.py', 'pathfinding', 'flour_roads.py', 'world_index.py')),
    ('AI', ('monster_ai.py', 'faction_ai.py', 'npc_', 'living/', 'schedule.py', 'combat_tactics.py')),
    ('game sim (runtime.py)', ('game/runtime.py', 'game/sim/', 'game/host.py')),
    ('renderer (draw)', ('engine/renderer/', 'qt_game_view.py', 'logic_render.py', 'render_', 'glraw.py')),
    ('logic (engine)', ('engine/logic_', 'engine/physics.py', 'engine/player.py', 'spatial.py')),
    ('Qt / other', ()),
]


def classify(stack):
    for name, needles in CATEGORIES:
        if not needles:
            continue
        for filename, func in stack:
            for needle in needles:
                if needle in func or needle in filename:
                    return name
    return 'Qt / other'


def where(stack):
    """The innermost frame of this tree's own code, as ``file:func``."""
    for filename, func in stack:
        if filename.startswith(tree) and '/tools/' not in filename:
            return f'{os.path.relpath(filename, tree)}:{func}'
    return f'{os.path.basename(stack[0][0])}:{stack[0][1]}' if stack else '?'


sampler_on = threading.Event()
thread_keys = {}


def sampler():
    period = args.sample_ms / 1e3
    getframes = sys._current_frames
    while True:
        time.sleep(period)
        if not sampler_on.is_set():
            continue
        t = now_ms()
        frames_now = getframes()
        for ident, key in list(thread_keys.items()):
            frame = frames_now.get(ident)
            stack = []
            while frame is not None and len(stack) < 40:
                code = frame.f_code
                stack.append((code.co_filename, code.co_name))
                frame = frame.f_back
            stack = tuple(stack)
            index = stack_ids.get(stack)
            if index is None:
                index = stack_ids[stack] = len(stacks)
                stacks.append(stack)
            sample_ms.append(t)
            sample_thread.append(THREAD_KEYS.index(key))
            sample_stack.append(index)


# --------------------------------------------------------------- the run
report = {'args': vars(args), 'software_gl': os.environ.get('LIBGL_ALWAYS_SOFTWARE') == '1'}


def finish(error=None):
    sampler_on.clear()
    try:
        report['error'] = error
        report['marks'] = marks
        report['loading_stages'] = stages
        if frames:
            summarise()
        # What ran between consecutive marks from the map load on (sampled
        # main thread, named spans, GC): where the opening's time went.
        report['between_marks'] = []
        for (n0, t0, _r0), (n1, t1, _r1) in zip(marks, marks[1:]):
            if t1 - t0 < 50:
                continue
            named, cats, funcs = attribute(t0, t1, 'main', top=8)
            report['between_marks'].append({'from': n0, 'to': n1, 'ms': round(t1 - t0, 1),
                                            'spans': named, 'sampled': cats, 'where': funcs})
        report['slow_calls'] = slow_calls
        report['frames'] = [[round(a, 1), round(b, 1)] for a, b in frames]
        report['ticks'] = [[round(a, 1), round(b, 2)] for a, b in ticks]
        report['gc_events'] = [[round(a, 1), round(b, 2), g] for a, b, g in gc_events]
        text = json.dumps(report, indent=1, default=str)
        print(text[:6000])
        if args.json:
            with open(args.json, 'w') as f:
                f.write(text)
    finally:
        with open(SETTINGS, 'wb') as f:
            f.write(SAVED_SETTINGS)
        os._exit(0 if error is None else 1)


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 2) if values else 0.0


def in_window(rows, a, b):
    return [r for r in rows if a <= r[0] < b or (r[0] < a and r[0] + r[1] > a)]


def attribute(a, b, thread_key, top=4):
    """What ran in [a, b): named spans, GC, and the sampled categories."""
    named = collections.defaultdict(float)
    for label, rows in spans.items():
        for start, dur, _thread in in_window(rows, a, b):
            named[label] += min(b, start + dur) - max(a, start)
    for start, dur, gen in in_window(gc_events, a, b):
        named[f'GC gen{gen}'] += dur
    cats, funcs = collections.Counter(), collections.Counter()
    for t, key, stack in samples():
        if a <= t < b and key == thread_key:
            cats[classify(stack)] += args.sample_ms
            funcs[where(stack)] += args.sample_ms
    return ({k: round(v, 1) for k, v in sorted(named.items(), key=lambda kv: -kv[1]) if v >= 0.5},
            dict(cats.most_common(top)), dict(funcs.most_common(top)))


def summarise():
    play_from = report.get('play_from_ms', frames[0][0])
    play_frames = [f for f in frames if f[0] >= play_from]
    starts = [f[0] for f in play_frames]
    intervals = [b - a for a, b in zip(starts, starts[1:])]
    med = statistics.median(intervals) if intervals else 0.0
    report['play'] = {
        'frames': len(play_frames),
        'fps': round(len(play_frames) / max(1e-6, (starts[-1] - starts[0]) / 1e3), 2) if len(starts) > 1 else 0,
        'interval_ms': {'p50': pct(intervals, .5), 'p95': pct(intervals, .95),
                        'p99': pct(intervals, .99), 'max': round(max(intervals, default=0), 1)},
        'paint_ms': {'p50': pct([f[1] for f in play_frames], .5),
                     'p95': pct([f[1] for f in play_frames], .95)},
        'tick_ms': {'p50': pct([d for s, d in ticks if s >= play_from], .5),
                    'p99': pct([d for s, d in ticks if s >= play_from], .99),
                    'max': round(max((d for s, d in ticks if s >= play_from), default=0), 2)},
    }
    hitches = []
    for (a, _), (b, _) in zip(play_frames, play_frames[1:]):
        excess = (b - a) - med
        if excess > BUDGET_MS:
            named, cats, funcs = attribute(a, b, 'main')
            hitches.append({'at_s': round((a - play_from) / 1e3, 2), 'interval_ms': round(b - a, 1),
                            'excess_ms': round(excess, 1), 'spans': named,
                            'sampled': cats, 'where': funcs})
    report['hitches'] = hitches
    tick_spikes = []
    for s, d in ticks:
        if s >= play_from and d > BUDGET_MS:
            named, cats, funcs = attribute(s, s + d, 'logic')
            tick_spikes.append({'at_s': round((s - play_from) / 1e3, 2), 'tick_ms': round(d, 1),
                                'spans': named, 'sampled': cats, 'where': funcs})
    report['tick_spikes'] = tick_spikes
    # Ranked causes: the excess of every hitch, split by what ran in it.
    causes = collections.defaultdict(lambda: [0, 0.0])
    for h in hitches + [dict(t, excess_ms=t['tick_ms'] - BUDGET_MS) for t in tick_spikes]:
        share = h['spans'] or h['sampled']
        total = sum(share.values()) or 1.0
        for k, v in share.items():
            causes[k][0] += 1
            causes[k][1] += h['excess_ms'] * v / total
    report['hitch_causes_ranked'] = [{'cause': k, 'hitches': n, 'excess_ms': round(ms, 1)}
                                     for k, (n, ms) in sorted(causes.items(), key=lambda kv: -kv[1][1])]
    # Totals of the named spans: in the opening (before play_from), in the
    # first second of play, and over the whole run.
    first_s = play_from + 1000.0
    report['spans'] = {
        label: {'calls_loading': sum(1 for r in rows if r[0] < play_from),
                'ms_loading': round(sum(r[1] for r in rows if r[0] < play_from), 1),
                'calls_first_s': sum(1 for r in rows if play_from <= r[0] < first_s),
                'ms_first_s': round(sum(r[1] for r in rows if play_from <= r[0] < first_s), 1),
                'calls_play': sum(1 for r in rows if r[0] >= play_from),
                'ms_play': round(sum(r[1] for r in rows if r[0] >= play_from), 1),
                'max_ms': round(max((r[1] for r in rows), default=0), 1),
                'threads': sorted({r[2] for r in rows})}
        for label, rows in sorted(spans.items())}
    report['gc'] = {
        'loading': {g: [sum(1 for s, d, x in gc_events if x == g and s < play_from),
                        round(max((d for s, d, x in gc_events if x == g and s < play_from), default=0), 1)]
                    for g in (0, 1, 2)},
        'play': {g: [sum(1 for s, d, x in gc_events if x == g and s >= play_from),
                     round(max((d for s, d, x in gc_events if x == g and s >= play_from), default=0), 1)]
                 for g in (0, 1, 2)}}
    report['counters'] = dict(counters)
    # Sampled main-thread time by category over the whole play window.
    main = collections.Counter()
    for t, key, stack in samples():
        if key == 'main' and t >= play_from:
            main[classify(stack)] += args.sample_ms
    report['main_thread_sampled_ms_by_category'] = dict(main.most_common())


SPANS = (
    ('engine.renderer.core.resources', 'ShaderLoader.compile_shader_program', 'shader compile'),
    ('engine.renderer.core.resources', 'ShaderLoader.compile_from_source', 'shader compile'),
    ('engine.renderer.core.resources', 'ResourcesMixin.load_texture', 'texture load'),
    ('engine.renderer.core.resources', 'ResourcesMixin.load_model', 'model load'),
    ('engine.renderer.core.resources', 'ResourcesMixin.ensure_effect_frames', 'effect frames (fire gifs)'),
    ('engine.qt_game_view', 'QtGameView.preload_level_textures', 'preload_level_textures'),
    ('engine.qt_game_view', 'QtGameView.load_all_sprite_textures', 'load_all_sprite_textures'),
    ('engine.glb_loader', 'GLBLoader.load', 'GLB parse'),
    ('engine.terrain', 'Terrain._build_chunk', 'terrain chunk build'),
    ('engine.terrain', 'Terrain._build_grass', 'grass build'),
    ('engine.renderer.core.terrain_gl', 'TerrainGL._upload_heightfield', 'terrain heightfield upload'),
    ('engine.renderer.core.terrain_gl', 'TerrainGL._upload_paint_chunk', 'paint upload'),
    ('engine.renderer.core.terrain_gl', 'TerrainGL._upload_block_mesh', 'terrain mesh upload'),
    ('engine.renderer.core.terrain_gl', 'TerrainGL._upload_grass_chunk', 'grass upload'),
    ('engine.view_audio', 'ViewAudio.preload_sounds', 'preload_sounds'),
    ('engine.view_audio', 'ViewAudio._load_sound_to_cache', 'sound load'),
    ('engine.view_audio', 'ViewAudio._load_sound_bytes_to_cache', 'sound load'),
    ('game.ui.worldmap', 'WorldMap._build', 'world-map picture'),
    ('game.ui.worldmap', 'WorldMap._load_cache', 'world-map cache read'),
    ('game.ui.worldmap', 'ensure_for', 'world-map ensure_for (map JSON read)'),
    ('engine.renderer.core.terrain_gl', 'TerrainGL._init_grass_shader', 'shader compile (grass)'),
    ('engine.overhead_sprite', 'OverheadSpriteRenderer._init_gl', 'shader compile (overhead sprite)'),
    ('engine.renderer.forward.decals', 'DecalsMixin._decal_program', 'shader compile (decals)'),
    ('engine.renderer.forward.decals', 'DecalsMixin._decal_texture_array', 'decal texture array'),
    ('engine.renderer.forward.shaders', 'ShadersMixin._ensure_terrain_textures', 'terrain textures'),
    ('engine.renderer.forward.shaders', 'ShadersMixin._sprite_layer_array', 'sprite layer array'),
    ('game.ui.magic_gl', '_init', 'shader compile (magic)'),
    ('engine.sprite_layers', 'SpriteLayers._import', 'sprite layer import'),
    ('engine.view_audio', 'ViewAudio._get_sound_instance', 'sound first play (get instance)'),
    ('engine.view_audio', 'ViewAudio.preload_combat_sounds', 'combat sounds preloaded'),
    ('game.music', 'MusicPlayer._load_track', 'music track load'),
    ('game.navigation', 'Navigator.find_path', 'nav find_path'),
    ('game.ui.hud_frame', '_layers', 'HUD frame layers'),
    ('game.runtime', 'MiniwindSession.begin_new_character', 'begin_new_character'),
    ('game.runtime', 'MiniwindSession.install', 'MiniwindSession.install'),
    ('game.host', 'MiniwindGame.on_play_start', 'on_play_start'),
    ('game.meadow', 'apply', 'meadow.apply'),
    ('engine.qt_game_view', 'QtGameView.toggle_play_mode', 'toggle_play_mode'),
    ('editor.main_window', 'MainWindow._start_play', '_start_play'),
    ('engine.gc_policy', 'settle', 'gc_policy.settle'),
)

_pending_patches = collections.defaultdict(list)


class _PatchFinder:
    """Runs the patches waiting for a module right after it is executed, so
    the audit never changes what main.py imports, or when."""

    def find_spec(self, name, path=None, target=None):
        if name not in _pending_patches:
            return None
        import importlib.util
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(name)
        finally:
            sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None:
            return spec
        real_exec = spec.loader.exec_module

        def exec_module(module):
            real_exec(module)
            for fn in _pending_patches.pop(name, ()):
                try:
                    fn(module)
                except Exception as exc:                      # pragma: no cover
                    print(f'[audit] patch for {name} failed: {exc}')
        spec.loader.exec_module = exec_module
        return spec


def after_import(name, fn):
    if name in sys.modules:
        fn(sys.modules[name])
    else:
        _pending_patches[name].append(fn)


def span_path(module, path, label):
    owner = module
    *owners, method = path.split('.')
    for part in owners:
        owner = getattr(owner, part)
    if hasattr(owner, method):
        span(owner, method, label)
    else:
        print(f'[audit] no {module.__name__}:{path}')


def install_hooks():
    """Spans and per-frame logging, installed as main.py imports each module."""
    sys.meta_path.insert(0, _PatchFinder())
    after_import('engine.qt_game_view', _patch_view)
    after_import('engine.logic_thread', _patch_logic)
    after_import('editor.loading_overlay', _patch_overlay)
    after_import('game.ui.launcher', lambda m: patch_launcher())
    after_import('editor.main_window', lambda m: patch_window())


def _patch_view(module):
    QtGameView = module.QtGameView
    real_paint = QtGameView.paintGL

    def paintGL(self):
        started = time.perf_counter()
        try:
            return real_paint(self)
        finally:
            if getattr(self, 'play_mode', False):
                frames.append(((started - T0) * 1e3, (time.perf_counter() - started) * 1e3))
                if driver.first_frame_cb is not None:
                    cb, driver.first_frame_cb = driver.first_frame_cb, None
                    cb()

    QtGameView.paintGL = paintGL
    real_update_loop = QtGameView.update_loop

    def update_loop(self):
        real_update_loop(self)
        if driver.driving:
            driver.steer(self)

    QtGameView.update_loop = update_loop


def _patch_logic(lt):
    real_tick = lt.LogicThread._tick

    def _tick(self, delta):
        if 'logic' not in thread_keys.values():
            thread_keys[threading.get_ident()] = 'logic'
        started = time.perf_counter()
        try:
            return real_tick(self, delta)
        finally:
            ticks.append(((started - T0) * 1e3, (time.perf_counter() - started) * 1e3))

    lt.LogicThread._tick = _tick


def _patch_overlay(module):
    LoadingOverlay = module.LoadingOverlay
    real_step, real_begin = LoadingOverlay.step, LoadingOverlay.begin

    def step(self, stage, percent=None):
        stages.append((round(now_ms(), 1), stage, percent))
        result = real_step(self, stage, percent)
        if args.capture_loading and self.active:
            try:
                os.makedirs(args.capture_loading, exist_ok=True)
                safe = ''.join(c if c.isalnum() else '_' for c in str(stage))[:40]
                path = os.path.join(args.capture_loading,
                                    f'{len(stages):02d}_{self.value:02d}pct_{safe}.png')
                self.window().grab().save(path)
            except Exception as exc:                          # pragma: no cover
                print(f'[audit] capture failed: {exc}')
        return result

    def begin(self, title, stage='', percent=None):
        stages.append((round(now_ms(), 1), f'[{title}] {stage}', percent))
        return real_begin(self, title, stage, percent)

    LoadingOverlay.step, LoadingOverlay.begin = step, begin
    for module, path, label in SPANS:
        after_import(module, lambda m, path=path, label=label: span_path(m, path, label))

    after_import('pygame.mixer', _patch_sound)


def _patch_sound(mixer):
    real_sound = mixer.Sound

    class Sound(real_sound):
        def __init__(self, *a, **k):
            started = time.perf_counter()
            try:
                super().__init__(*a, **k)
            finally:
                spans['pygame Sound decode'].append(((started - T0) * 1e3,
                                                     (time.perf_counter() - started) * 1e3,
                                                     threading.current_thread().name))
    mixer.Sound = Sound


# ------------------------------------------------------------- the driver
ROUTES = {
    # Millbrook's streets on foot from the spawn, round and round (the
    # village's path nodes and road).
    'millbrook': [(192, 0), (400, 96), (1280, 96), (1280, 688), (416, 672),
                  (-122, 366), (192, 0), (0, -96)],
    # Out of Millbrook along the north road, then east by road across open
    # country towards the next village and beyond (the map's ROAD nodes).
    'country': [(192, 0), (-122, 366), (-584, 809), (-925, 1326), (-730, 1909),
                (-952, 2452), (-59, 2376), (375, 2845), (669, 3395), (1190, 3731),
                (1748, 3998), (2321, 4114), (2878, 4330), (3388, 4711), (3792, 5206),
                (4204, 5693), (4833, 5780), (5372, 6095), (6012, 6101), (6633, 6137),
                (7208, 6391), (7823, 6450), (8432, 6560), (8645, 6049), (9147, 5653),
                (9606, 5207), (10063, 4759), (10515, 4306), (10953, 3839), (11481, 3511),
                (11924, 3052), (12341, 2567), (12779, 2101), (13038, 1530), (13587, 1225),
                (13888, 741), (13915, 134)],
    'still': [],
}


class Driver:
    first_frame_cb = None
    driving = False

    def __init__(self):
        self.window = None
        self.route = list(ROUTES[args.route])
        self.leg = 0
        self.progress = None
        self.unstick = 0
        self.strafe_until = 0.0
        self.strafe_key = 0x41
        self.last = None
        self.distance = 0.0

    def steer(self, view):
        logic = view.logic_thread
        player = getattr(getattr(logic, 'player_runtime', None), 'player', None)
        if player is None or not self.route:
            view.editor.keys_pressed = set()
            return
        x, z = float(player.pos[0]), float(player.pos[2])
        tx, tz = self.route[self.leg % len(self.route)]
        t = time.perf_counter()
        strafe = None
        if self.progress is None or math.hypot(x - self.progress[0], z - self.progress[1]) > 48.0:
            self.progress = (x, z, t)
            self.unstick = 0
        elif t < self.strafe_until:
            strafe = self.strafe_key
        elif t - self.progress[2] > 1.5:
            # Blocked (a fence, a cart, a villager): side-step for a second,
            # the other way each time; give the waypoint up after four tries.
            self.unstick += 1
            counters['route side-steps (blocked)'] += 1
            if self.unstick > 4:
                counters['route legs skipped (stuck)'] += 1
                self.leg += 1
                self.unstick = 0
                tx, tz = self.route[self.leg % len(self.route)]
            self.strafe_key = 0x41 if self.unstick % 2 else 0x44
            self.strafe_until = t + 1.0
            self.progress = (x, z, t + 1.0)
            strafe = self.strafe_key
        self.distance += math.hypot(x - self.last[0], z - self.last[1]) if self.last else 0.0
        self.last = (x, z)
        counters['distance travelled'] = round(self.distance)
        if math.hypot(tx - x, tz - z) < 120.0:
            self.leg += 1
            counters['route legs reached'] += 1
            tx, tz = self.route[self.leg % len(self.route)]
        yaw = math.atan2(tx - x, tz - z)
        view.game_state.set_aim(yaw=yaw)
        keys = {0x57}
        if strafe is not None:
            keys.add(strafe)
        if args.sprint:
            keys.add(0x01000020)
        view.editor.keys_pressed = keys


driver = Driver()


def after(ms, fn):
    from PyQt5.QtCore import QTimer
    QTimer.singleShot(int(ms), fn)


def wait_for(predicate, then, timeout_s=120.0, what='condition'):
    deadline = time.perf_counter() + timeout_s

    def poll():
        try:
            ok = predicate()
        except Exception:
            ok = False
        if ok:
            then()
        elif time.perf_counter() > deadline:
            finish(f'timed out waiting for {what}')
        else:
            after(10, poll)
    poll()


def session_of(window):
    logic = window.view_3d.logic_thread
    return getattr(logic, 'game_session', None) if logic is not None else None


def on_kiosk_ready(window):
    """The map is loaded and play started: wait for the first world frame."""
    mark('play started (enter_kiosk_mode returned)')
    label = ('first in-world frame (CONTINUE: the save loaded)' if args.launch_continue
             else 'first in-world frame (new game: character creation)')
    driver.first_frame_cb = lambda: (mark(label), after(500, lambda: make_character(window)))


def make_character(window):
    session = session_of(window)
    if session is None:
        return finish('no game session')
    report['needs_char_creation'] = bool(session.needs_char_creation)
    if not session.needs_char_creation:
        return after_opening(window)
    mark('character created (begin_new_character)')
    if session.needs_char_creation:
        session.begin_new_character('Audit', 'human', 'warrior')
        from game import fio
        from game.host import SCREEN_PAUSE
        fio.set_world_paused(session.logic, SCREEN_PAUSE, False)
    driver.first_frame_cb = lambda: (mark('first gameplay frame'),
                                     after(0, lambda: after_opening(window)))


def after_opening(window):
    if args.travel:
        return after(2000, lambda: travel(window, list(args.travel)))
    if args.cont:
        return do_continue(window)
    start_play(window)


def travel(window, maps):
    if not maps:
        return do_continue(window) if args.cont else start_play(window)
    path = maps.pop(0)
    name = os.path.basename(path)
    mark(f'travel to {name}: requested (open_level_file from_game)')
    started = len(frames)
    ok = window.open_level_file(os.path.join(tree, path), None, from_game=True)
    mark(f'travel to {name}: open_level_file returned {ok}')
    wait_for(lambda: len(frames) > started,
             lambda: (mark(f'travel to {name}: first frame'),
                      after(3000, lambda: travel(window, maps))),
             what=f'first frame in {name}')


def do_continue(window):
    from game.ui.pause_actions import PauseActions
    view = window.view_3d
    menu = getattr(view, 'play_menu', None)
    actions = getattr(menu, 'actions', None) or PauseActions(view)
    after(3000, lambda: _save_then_load(window, actions))


def _save_then_load(window, actions):
    from game.autosave import AUTOSAVE_NAME
    done = actions.save_named(AUTOSAVE_NAME)
    if done is not True:
        return finish(f'autosave failed: {done}')
    mark('Continue: load requested (PauseActions.load_named autosave)')
    started = len(frames)
    actions.load_named(AUTOSAVE_NAME, 'the last autosave')
    mark('Continue: load_named returned')
    wait_for(lambda: len(frames) > started, lambda: (mark('Continue: first in-world frame'),
                                                    start_play(window)), what='Continue frame')


def start_play(window):
    view = window.view_3d
    driver.driving = True
    if args.noclip and getattr(view, 'player', None) is not None:
        view.player.physics_enabled = False
    thread_keys[threading.main_thread().ident] = 'main'
    report['play_from_ms'] = now_ms()
    mark(f'measured play begins ({args.route}{", sprint" if args.sprint else ""}, {args.seconds:.0f} s)')
    sampler_on.set()
    report['rss_timeline_mb'] = []
    for i in range(1, int(args.seconds // 5) + 1):
        after(i * 5000, lambda: report['rss_timeline_mb'].append(round(rss_mb(), 1)))
    if args.trace_tuples:
        import tracemalloc
        tracemalloc.start(12)
    if args.gc_census:
        report['gc_census'] = []
        base = census()
        report['gc_census_start'] = {'tracked': sum(base.values()), 'frozen': gc.get_freeze_count()}

        def take(base=base):
            counts = census()
            grew = {k: counts[k] - base.get(k, 0) for k in counts}
            # What the long-lived young tuples are: their length and the
            # types they hold (the full collections walk these).
            shapes = collections.Counter(
                (len(o), tuple(type(x).__name__ for x in o[:4]))
                for o in gc.get_objects(generation=2) if type(o) is tuple)
            sites = None
            if args.trace_tuples:
                import tracemalloc
                sites = collections.Counter()
                for o in gc.get_objects(generation=2):
                    if type(o) is not tuple:
                        continue
                    tb = tracemalloc.get_object_traceback(o)
                    if tb is None:
                        continue
                    own = [f for f in tb if f.filename.startswith(tree) and '/tools/' not in f.filename]
                    if not own:
                        continue
                    first = own[0]
                    caller = own[1] if len(own) > 1 else None
                    sites[f'{os.path.relpath(first.filename, tree)}:{first.lineno}'
                          + (f' < {os.path.relpath(caller.filename, tree)}:{caller.lineno}' if caller else '')] += 1
                sites = sites.most_common(15)
            samples3 = None
            if args.trace_tuples:
                found = [o for o in gc.get_objects(generation=2)
                         if type(o) is tuple and len(o) == 3 and type(o[0]) is float
                         and type(o[1]) is str and type(o[2]) is tuple][-400:]
                holders = collections.Counter()
                for o in found[::40]:
                    for r in gc.get_referrers(o):
                        if r is found:
                            continue
                        holders[f'{type(r).__name__} len={len(r) if hasattr(r, "__len__") else "?"}'] += 1
                samples3 = {'examples': [repr(o)[:160] for o in found[-5:]],
                            'holders': holders.most_common(6)}
            report['gc_census'].append({
                'gen2_tuple_samples': samples3,
                'gen2_tuple_sites': sites,
                's': round((now_ms() - report['play_from_ms']) / 1e3, 1),
                'tracked': sum(counts.values()), 'frozen': gc.get_freeze_count(),
                'gen2_tuple_shapes': [[n, list(k)] for k, n in shapes.most_common(8)],
                'grew': dict(sorted(((k, v) for k, v in grew.items() if v > 0),
                                    key=lambda kv: -kv[1])[:12])})
        for i in range(1, int(args.seconds // 10) + 1):
            after(i * 10000 - 50, take)
    if args.capture_play:
        after(3000, lambda: window.grab().save(args.capture_play))
    after(args.seconds * 1000, lambda: end_play(window))


def census():
    counts = collections.Counter(type(o).__name__ for o in gc.get_objects())
    return counts


def end_play(window):
    view = window.view_3d
    logic = view.logic_thread
    player = getattr(getattr(logic, 'player_runtime', None), 'player', None)
    if player is not None:
        report['player_end_pos'] = [round(float(c), 1) for c in player.pos]
    report['rss_end_mb'] = round(rss_mb(), 1)
    # Every sprite-layer array alive: its layer size, layers allocated and in
    # use, and what that costs in texture memory (RGBA8, with mips if any).
    from engine.sprite_layers import SpriteLayers
    report['sprite_layers'] = [
        {'owner': type(o).__qualname__, 'size': o.size, 'capacity': o.capacity, 'count': o.count,
         'mb': round(o.size * o.size * 4 * o.capacity * (1.0 if o._levels() <= 1 or 'Overhead' in type(o).__qualname__
                                                          else 4 / 3) / 2**20, 1)}
        for o in [getattr(view.renderer, '_sprite_layers', None)] + gc.get_objects()
        if isinstance(o, SpriteLayers) and o.texture]
    for row, o in zip(report['sprite_layers'],
                      [o for o in [getattr(view.renderer, '_sprite_layers', None)] + gc.get_objects()
                       if isinstance(o, SpriteLayers) and o.texture]):
        row['readbacks'] = getattr(o, 'readbacks', None)
    report['sprite_layer_imports'] = counters.get('sprite layer imports', 0)
    try:
        report['textures_resident'] = len(view.renderer.texture_manager)
    except Exception:
        pass
    terrain = getattr(getattr(logic, 'world_runtime', None), 'terrain', None)
    if terrain is not None:
        # Paint held in memory: unpacked arrays (every distinct one) and
        # packed streams, over both paint dicts (they share).
        arrays, packed = {}, {}
        for paints in (getattr(terrain, 'texture_paint_maps', {}), getattr(terrain, 'texture_paint_base', {})):
            for value in dict.values(paints):
                array = getattr(value, 'array', value) if hasattr(value, 'data') else value
                if hasattr(value, 'data'):
                    packed[id(value)] = len(value.data)
                if array is not None and hasattr(array, 'nbytes'):
                    arrays[id(array)] = array.nbytes
        report['paint_memory'] = {'chunks': len(dict.keys(getattr(terrain, 'texture_paint_maps', {}))),
                                  'unpacked': len(arrays), 'unpacked_mb': round(sum(arrays.values()) / 2**20, 1),
                                  'packed_mb': round(sum(packed.values()) / 2**20, 1)}
        report['terrain'] = {k: getattr(terrain, k) for k in ('chunk_size',) if hasattr(terrain, k)}
    finish()


def patch_launcher():
    """The launcher, painted, then PLAY."""
    import game.ui.launcher as launcher
    from PyQt5.QtWidgets import QApplication

    def launch(root_dir='.', settings_path=None, parent=None):
        dialog = launcher.Launcher(root_dir, settings_path, parent)
        dialog.show()
        for _ in range(5):
            QApplication.processEvents()
        dialog.repaint()
        mark('menu: launcher painted')
        dialog.close()
        if args.launch_continue:
            found = launcher.resume_save(root_dir) if hasattr(launcher, 'resume_save') else None
            if not found:
                finish('--launch-continue: there is no save to continue')
            launcher._resume = found[0]
            report['launch_continue'] = found[0]
        return launcher.PLAY

    launcher.launch = launch


def patch_window():
    from editor.main_window import MainWindow
    real_kiosk = MainWindow.enter_kiosk_mode
    real_init = MainWindow.__init__

    def __init__(self, *a, **k):
        mark('PLAY chosen: building MainWindow')
        real_init(self, *a, **k)
        driver.window = self
        mark('MainWindow built')

    def enter_kiosk_mode(self):
        real_kiosk(self)
        after(0, lambda: on_kiosk_ready(self))

    MainWindow.__init__ = __init__
    MainWindow.enter_kiosk_mode = enter_kiosk_mode
    real_load = MainWindow.load_level_file

    def load_level_file(self, *a, **k):
        mark(f'load_level_file {os.path.basename(str(a[0]))}')
        started = now_ms()
        try:
            return real_load(self, *a, **k)
        finally:
            report.setdefault('load_level_file_ms', []).append(round(now_ms() - started, 1))
            mark('load_level_file returned')
    MainWindow.load_level_file = load_level_file


if not args.no_sampler:
    threading.Thread(target=sampler, name='audit-sampler', daemon=True).start()
thread_keys[threading.main_thread().ident] = 'main'
mark('interpreter to script')
try:
    install_hooks()
    sampler_on.set()      # sample the opening too (main thread only until play)
    sys.argv = [os.path.join(tree, 'main.py')]
    runpy.run_path(os.path.join(tree, 'main.py'), run_name='__main__')
except SystemExit:
    finish('main.py exited before the audit finished')
except BaseException as exc:                                  # pragma: no cover
    import traceback
    traceback.print_exc()
    finish(repr(exc))
