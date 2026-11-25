"""Per-row brush uniforms go up through raw entry points, byte for byte.

``engine.renderer.core.uniform_rows`` replaces PyOpenGL's wrapped
``glUniformMatrix4fv`` / ``glUniformMatrix3fv`` / ``glUniform3fv`` in the
brush passes' per-row loops (6.3 -> 0.9 us a call).  These tests hold it to
two things: the values GL ends up holding are exactly the wrappers', and a
real frame of Fio's showcase map (``tests/fixtures/maps/_SHOWCASE.json``) --
lit, textured angled, glow, water, glass and fog brushes -- sends none of
those rows through the wrappers any more, and draws the same pixels either way.
"""

import ctypes
import sys

import numpy as np
import pytest

pytest.importorskip("PyQt5")

from tests.helpers import gl as glh                              # noqa: E402

pytestmark = [pytest.mark.gl, pytest.mark.integration]

_VERTEX = """#version 330 core
uniform mat4 model; uniform mat3 nm; uniform vec3 col;
layout(location = 0) in vec3 p; out vec3 c;
void main() { c = nm * col; gl_Position = model * vec4(p, 1.0); }
"""
_FRAGMENT = """#version 330 core
in vec3 c; out vec4 o; void main() { o = vec4(c, 1.0); }
"""


def _read_uniform(program, location, width):
    values = (ctypes.c_float * width)()
    import OpenGL.GL as gl
    gl.glGetUniformfv(program, location, values)
    return np.frombuffer(values, dtype=np.float32).copy()


def _freeze_paint_clock(monkeypatch):
    import time
    import types
    import engine.qt_game_view
    import engine.renderer.forward.passes
    frozen = types.SimpleNamespace(**{name: getattr(time, name)
                                      for name in dir(time) if not name.startswith("__")})
    now = time.perf_counter()
    frozen.perf_counter = lambda: now
    monkeypatch.setattr(engine.qt_game_view, "time", frozen)
    monkeypatch.setattr(engine.renderer.forward.passes, "time", frozen)


def test_raw_rows_hold_exactly_what_the_wrappers_sent(monkeypatch):
    import OpenGL.GL as gl
    from OpenGL.GL import shaders
    from engine.renderer.core import uniform_rows as ur

    with glh.GLTestContext(16, 16):
        program = shaders.compileProgram(
            shaders.compileShader(_VERTEX, gl.GL_VERTEX_SHADER),
            shaders.compileShader(_FRAGMENT, gl.GL_FRAGMENT_SHADER))
        gl.glUseProgram(program)
        rng = np.random.default_rng(7)
        # A grown scratch buffer's view, a gathered column, and a row slice
        # that is not contiguous (it must be copied, not read in place).
        cases = [
            ('mat4', 'model', 16, rng.standard_normal((40, 16)).astype(np.float32)[:23]),
            ('mat3', 'nm', 9, rng.standard_normal((9, 9)).astype(np.float32)),
            ('vec3', 'col', 3, rng.standard_normal((6, 5)).astype(np.float32)[:, 1:4]),
        ]
        try:
            for kind, name, width, rows in cases:
                location = gl.glGetUniformLocation(program, name)
                assert location != -1, name
                for index in range(len(rows)):
                    monkeypatch.setattr(ur, "raw_uploads_enabled", lambda: False)
                    ur.uniform_rows(kind, rows)(location, index)
                    wrapped = _read_uniform(program, location, width)
                    monkeypatch.setattr(ur, "raw_uploads_enabled", lambda: True)
                    # Clear the uniform so a raw upload that sent nothing
                    # cannot pass by leaving the wrapper's value behind.
                    zero = np.zeros((1, width), dtype=np.float32)
                    ur.uniform_rows(kind, zero)(location, 0)
                    ur.uniform_rows(kind, rows)(location, index)
                    raw = _read_uniform(program, location, width)
                    assert raw.tobytes() == wrapped.tobytes(), (kind, index)
                    assert raw.tobytes() == np.ascontiguousarray(rows[index]).tobytes()
            for kind, *_ in cases:
                name = ur._KINDS[kind][0]
                assert ur._raw_entry(name) is not None, (
                    "%s did not resolve; the test ran the wrapper twice" % name)
                # The first raw upload checked itself; a failed check would
                # have fallen back to the wrapper and passed the test above.
                assert ur._verified.get(name) is True, name
        finally:
            gl.glUseProgram(0)
            gl.glDeleteProgram(program)


def test_the_native_call_is_pyopengls_own_prototype():
    """Same function type (calling convention), scalars and return type as
    the entry point PyOpenGL calls itself; only the data pointer differs."""
    import ctypes
    from OpenGL.raw.GL.VERSION import GL_2_0
    from engine.renderer.core import uniform_rows as ur

    with glh.GLTestContext(16, 16):
        for name, has_transpose, _width in ur._KINDS.values():
            fn = ur._raw_entry(name)
            loaded = getattr(GL_2_0, name).load()
            assert fn is not None and loaded is not None, name
            assert type(fn) is type(loaded), name
            assert fn.argtypes[:-1] == tuple(loaded.argtypes[:-1]), name
            assert len(fn.argtypes) == (4 if has_transpose else 3), name
            assert fn.argtypes[-1] is ctypes.c_void_p, name
            assert fn.restype is loaded.restype, name
            assert (ctypes.cast(fn, ctypes.c_void_p).value
                    == ctypes.cast(loaded, ctypes.c_void_p).value), name


def test_a_raw_upload_that_does_not_read_back_falls_back_to_the_wrapper(
        monkeypatch, capsys):
    import OpenGL.GL as gl
    from OpenGL.GL import shaders
    from engine.renderer.core import uniform_rows as ur

    sent_nothing = lambda *args: None                   # noqa: E731
    monkeypatch.setattr(ur, "_resolved", {"glUniformMatrix4fv": sent_nothing})
    monkeypatch.setattr(ur, "_verified", {})
    wrapped = []
    real = gl.glUniformMatrix4fv
    monkeypatch.setattr(gl, "glUniformMatrix4fv",
                        lambda *args: (wrapped.append(1), real(*args)))
    rows = np.arange(32, dtype=np.float32).reshape(2, 16) + 1.0

    with glh.GLTestContext(16, 16):
        program = shaders.compileProgram(
            shaders.compileShader(_VERTEX, gl.GL_VERTEX_SHADER),
            shaders.compileShader(_FRAGMENT, gl.GL_FRAGMENT_SHADER))
        gl.glUseProgram(program)
        try:
            location = gl.glGetUniformLocation(program, "model")
            ur.uniform_rows("mat4", rows)(location, 1)
            # The check caught it, and the row was re-sent through the wrapper.
            assert ur._verified["glUniformMatrix4fv"] is False
            assert _read_uniform(program, location, 16).tobytes() == rows[1].tobytes()
            assert "did not read back" in capsys.readouterr().out
            # From now on that kind goes through the wrapper.
            wrapped.clear()
            ur.uniform_rows("mat4", rows)(location, 0)
            assert wrapped == [1]
            assert _read_uniform(program, location, 16).tobytes() == rows[0].tobytes()
        finally:
            gl.glUseProgram(0)
            gl.glDeleteProgram(program)


def test_no_index_outside_the_rows_reaches_gl(monkeypatch):
    """An out-of-range row raises before any address is formed, on both
    paths and while the first upload is still being verified."""
    from engine.renderer.core import uniform_rows as ur

    calls = []
    monkeypatch.setattr(ur, "_resolved", {"glUniformMatrix4fv": lambda *a: calls.append(a)})
    rows = np.zeros((3, 16), dtype=np.float32)
    for verified in (None, True):
        monkeypatch.setattr(ur, "_verified", {} if verified is None
                            else {"glUniformMatrix4fv": True})
        upload = ur.uniform_rows("mat4", rows)
        for index in (3, -1, 10**9):
            with pytest.raises(IndexError):
                upload(0, index)
    monkeypatch.setattr(ur, "raw_uploads_enabled", lambda: False)
    with pytest.raises(IndexError):
        ur.uniform_rows("mat4", rows)(0, -1)
    assert calls == []


def test_an_unresolvable_entry_point_is_never_called(monkeypatch):
    from OpenGL.raw.GL.VERSION import GL_2_0
    from engine.renderer.core import uniform_rows as ur

    monkeypatch.setattr(ur, "_resolved", {})
    monkeypatch.setattr(GL_2_0.glUniform3fv, "load", lambda: None, raising=False)
    assert ur._raw_entry("glUniform3fv") is None
    wrapped = []
    import OpenGL.GL as gl
    monkeypatch.setattr(gl, "glUniform3fv", lambda *a: wrapped.append(a))
    ur.uniform_rows("vec3", np.ones((2, 3), dtype=np.float32))(4, 1)
    assert len(wrapped) == 1


# The child runs main.py's own start-up decision (it imports main before
# OpenGL), plays 20 ticks of Fio's showcase map (a test fixture) on a stepped
# clock, and paints one frame: reports which path the uploads took and saves
# the pixels.
_CHILD = r"""
import json, os, random, sys, time, types
sys.path.insert(0, os.getcwd())
import main                                   # main.py's environment decision
import numpy as np
import OpenGL
import OpenGL.GL as gl
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from tests.helpers.session import FioTestSession
from engine.renderer.core import uniform_rows as ur
random.seed(5); np.random.seed(5)
session = FioTestSession(app, "tests/fixtures/maps/_SHOWCASE.json")
session.view.sysmon.set_active(False)
session.view.editor.config.set("Display", "show_fps", "False")
# One clock for both processes: the effect clock's origin plus whole ticks
# (perf_counter's own value differs between any two processes).
import engine.entity_table
origin = engine.entity_table._CLOCK_ORIGIN
clock = [origin + 100.0]
time.perf_counter = lambda: clock[0]
session.view.start_time = origin
session.start_play()
for _ in range(20):
    clock[0] += 1.0 / 60.0
    session.step(1)
session.publish()
session.paint()                               # the shadow maps' first draw
wrapped = []
for name in ("glUniformMatrix4fv", "glUniformMatrix3fv", "glUniform3fv"):
    real = getattr(gl, name)
    def recording(*args, _real=real):
        if isinstance(args[-1], np.ndarray):
            wrapped.append(1)
        return _real(*args)
    setattr(gl, name, recording)
pixels = session.paint()
np.save(sys.argv[1], pixels)
print("RESULT " + json.dumps({
    "error_checking": bool(OpenGL.ERROR_CHECKING),
    "raw_enabled": ur.raw_uploads_enabled(),
    "wrapped": len(wrapped),
    "verified": {k: bool(v) for k, v in ur._verified.items()},
}))
sys.stdout.flush()
os._exit(0)
"""


def _run_child(tmp_path, tag, **env_overrides):
    import json
    import os
    import subprocess
    from tests.helpers.paths import REPO_ROOT

    env = dict(os.environ)
    # The two modes run in separate processes. Keep Python's hash-seed stable
    # as well as random/NumPy seeds so set-backed render collections cannot
    # produce a different draw order between the parity captures.
    env["PYTHONHASHSEED"] = "5"
    for key in ("FIO_GL_DEBUG", "PYOPENGL_ERROR_CHECKING"):
        env.pop(key, None)
    env.update(env_overrides)
    out = tmp_path / ("%s.npy" % tag)
    done = subprocess.run([sys.executable, "-c", _CHILD, str(out)], cwd=REPO_ROOT,
                          env=env, capture_output=True, text=True, timeout=300)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, "child failed:\n%s\n%s" % (done.stdout[-2000:], done.stderr[-4000:])
    return json.loads(lines[-1][len("RESULT "):]), np.load(out)


@pytest.mark.slow
def test_fio_gl_debug_checks_every_upload_and_the_app_takes_the_raw_path(tmp_path):
    """``FIO_GL_DEBUG=1`` keeps PyOpenGL's checks and the wrappers; the app's
    normal start-up (error checking off) takes the raw path; same frame."""
    debug, debug_pixels = _run_child(tmp_path, "debug", FIO_GL_DEBUG="1")
    shipped, shipped_pixels = _run_child(tmp_path, "shipped")

    assert debug["error_checking"] is True
    assert debug["raw_enabled"] is False
    assert debug["wrapped"] > 0, "the debug frame sent no row through the wrappers"
    assert debug["verified"] == {}

    assert shipped["error_checking"] is False
    assert shipped["raw_enabled"] is True
    assert shipped["wrapped"] == 0
    assert shipped["verified"] == {"glUniformMatrix4fv": True,
                                   "glUniformMatrix3fv": True,
                                   "glUniform3fv": True}
    assert shipped_pixels.max() > 0
    different = np.any(debug_pixels != shipped_pixels, axis=2)
    if different.any():
        coordinates = np.argwhere(different)
        sample = [
            (tuple(int(v) for v in xy),
             debug_pixels[tuple(xy)].tolist(),
             shipped_pixels[tuple(xy)].tolist())
            for xy in coordinates[:8]
        ]
        maximum = int(np.abs(debug_pixels.astype(np.int16)
                             - shipped_pixels.astype(np.int16)).max())
        pytest.fail(
            "%d pixels differ (maximum channel delta %d); samples %s"
            % (len(coordinates), maximum, sample))


def test_a_showcase_frame_sends_no_row_uniform_through_the_wrappers(
        fio_session, monkeypatch):
    """Fails before the change: 149 wrapped array uploads on this frame (it
    also refreshes the shadow maps; ~47 a steady-state showcase frame)."""
    import OpenGL.GL as gl
    from engine.renderer.core import uniform_rows as ur

    session = fio_session("tests/fixtures/maps/_SHOWCASE.json")
    # The repository's settings.ini shows SysMon at launch; its live figures
    # (the last frame's draws, VRAM) differ from one paint to the next, so it
    # made this pixel comparison flaky. The renderer is what is compared.
    session.view.sysmon.set_active(False)
    # MiniWind's water sky reads clouds baked on a thread of their own: both
    # paints must find them baked, or the first is cloudless.
    from engine import sky_clouds
    assert sky_clouds.wait(60) is not None
    session.start_play()
    session.step(20)
    session.publish()
    # The view and the effect pass animate on perf_counter(); hold it still
    # so two paints of one published frame are comparable pixel for pixel.
    _freeze_paint_clock(monkeypatch)

    wrapped = []
    for name in ("glUniformMatrix4fv", "glUniformMatrix3fv", "glUniform3fv"):
        real = getattr(gl, name)

        def recording(*args, _real=real, _name=name):
            if isinstance(args[-1], np.ndarray):
                wrapped.append((_name, sys._getframe(1).f_code.co_name))
            return _real(*args)
        monkeypatch.setattr(gl, name, recording)

    raw = session.paint()
    raw_stats = _stats(session)
    assert not wrapped, "%d row uniforms still went through the wrappers: %s" % (
        len(wrapped), sorted(set(wrapped)))

    monkeypatch.setattr(ur, "raw_uploads_enabled", lambda: False)
    through_wrappers = session.paint()
    wrapped_stats = _stats(session)
    assert wrapped, "the wrapper path sent nothing: the frame drew no row-uploading pass"
    monkeypatch.setattr(ur, "raw_uploads_enabled", lambda: True)
    assert raw.max() > 0, "the frame is blank"
    if not np.array_equal(raw, through_wrappers):
        # Which differs: the upload path, or the first paint from the ones
        # after it? A third paint, raw again, says.
        again = session.paint()
        renderer = session.view.renderer
        # A frame that re-renders the shadow maps, not the first one: does it
        # come out as the first did?
        renderer._shadow_slot_sig = [None] * len(renderer._shadow_slot_sig)
        rerendered = session.paint()
        # And with the driver made to finish the shadow pass before the lit
        # passes read it?
        import OpenGL.GL as gl_finish
        real_shadows = type(renderer).render_shadow_maps

        def finished(self, *args, **kwargs):
            result = real_shadows(self, *args, **kwargs)
            gl_finish.glFinish()
            return result
        renderer._shadow_slot_sig = [None] * len(renderer._shadow_slot_sig)
        type(renderer).render_shadow_maps = finished
        try:
            finished_frame = session.paint()
        finally:
            type(renderer).render_shadow_maps = real_shadows

        def which(frame):
            return ("the first" if np.array_equal(frame, raw) else
                    "the later ones" if np.array_equal(frame, through_wrappers)
                    else "neither")
        message = _frames_differ(raw, through_wrappers)
        message += ("; a frame re-rendering the shadows matches %s; with glFinish "
                    "after the shadow pass, %s" % (which(rerendered), which(finished_frame)))
        # What only the first frame does: build the model instance streams and
        # their vertex arrays, load the textures, load the models. Each made to
        # happen again, in turn: the one whose frame matches the first is it.
        renderer.__dict__.pop('_model_instance_streams', None)
        fresh_streams = session.paint()
        renderer.texture_manager.clear()
        fresh_textures = session.paint()
        renderer.loaded_models.clear()
        fresh_models = session.paint()
        message += ("; fresh model streams: %s; then fresh textures: %s; then "
                    "fresh models: %s" % (which(fresh_streams), which(fresh_textures),
                                          which(fresh_models)))
        message += ("; a third paint (raw again) %s; render stats that differ, "
                    "raw -> wrapped: %s" % (
                        "matches the raw one" if np.array_equal(again, raw) else
                        "matches the wrapped one" if np.array_equal(again, through_wrappers)
                        else "matches neither",
                        {k: (raw_stats.get(k), wrapped_stats.get(k))
                         for k in sorted(set(raw_stats) | set(wrapped_stats))
                         if raw_stats.get(k) != wrapped_stats.get(k)}))
        raise AssertionError(message)


def _stats(session):
    """The renderer's per-frame counters after a paint (flattened)."""
    stats = getattr(session.view.renderer, 'render_stats', None)
    names = getattr(type(stats), '__slots__', ()) if stats is not None else ()
    items = {name: getattr(stats, name, None) for name in names
             if name not in ('details', 'pass_ms')}      # (timings always differ)
    flat = {}
    for key, value in items.items():
        if isinstance(value, dict):
            for inner, item in value.items():
                flat['%s.%s' % (key, inner)] = item
        else:
            flat[key] = value
    return flat


def _frames_differ(a, b):
    """What a mismatch looks like: how many pixels, where (the box holding
    them, in a frame of ``height x width``), and by how much. With
    ``FIO_TEST_ARTIFACTS`` set the two frames are saved there as PNGs (CI
    uploads them), so a difference seen only on another machine can be
    looked at."""
    import os
    differ = np.any(a != b, axis=2)
    ys, xs = np.nonzero(differ)
    message = ("raw and wrapped uploads drew different frames (%d pixels differ, "
               "in x %d..%d, y %d..%d of %dx%d; largest channel difference %d)"
               % (int(differ.sum()), xs.min(), xs.max(), ys.min(), ys.max(),
                  a.shape[1], a.shape[0],
                  int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max())))
    folder = os.environ.get("FIO_TEST_ARTIFACTS")
    if folder:
        from PIL import Image
        os.makedirs(folder, exist_ok=True)
        Image.fromarray(a).save(os.path.join(folder, "raw_uploads.png"))
        Image.fromarray(b).save(os.path.join(folder, "wrapped_uploads.png"))
        message += "; frames saved in " + folder
    return message
