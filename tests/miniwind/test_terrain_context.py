"""macOS must not call shader entry points before a GL context exists.

The terrain's programs are the renderer's since Fio 3.5
(``engine/renderer/core/terrain_gl.py``): the check lives there, and asks
CGL only on macOS (elsewhere GLX and EGL may be mixed, and the query could
miss Qt's context; a missing context raises there, which is handled).
"""

from types import SimpleNamespace

import pytest

pytest.importorskip('OpenGL')
from engine.renderer.core import terrain_gl

pytestmark = pytest.mark.qt


def test_terrain_shader_compilation_defers_and_can_retry_after_a_context_arrives(monkeypatch):
    current = [True]                     # "no context is current"
    monkeypatch.setattr(terrain_gl, '_no_current_gl_context', lambda: current[0])
    calls = []
    monkeypatch.setattr(terrain_gl, 'compileShader',
                        lambda code, kind: calls.append(kind) or 11)
    monkeypatch.setattr(terrain_gl, 'compileProgram', lambda *args, **kwargs: 77)
    monkeypatch.setattr(terrain_gl, 'gl', SimpleNamespace(
        GL_VERTEX_SHADER=1, GL_FRAGMENT_SHADER=2, GL_INVALID_INDEX=0xFFFFFFFF,
        glGetUniformBlockIndex=lambda *args: 0xFFFFFFFF))
    held = terrain_gl.TerrainGL()
    assert held._compile_program('terrain_indexed.vert') == 0
    held._init_shader()
    assert calls == []
    assert held._failed_programs == set()
    assert held.shader_program == 0 and held.grass_shader_program == 0
    current[0] = False
    assert held._compile_program('terrain_indexed.vert') == 77
    assert calls == [1, 2]


def test_the_macos_query_reports_a_missing_context(monkeypatch):
    from OpenGL import platform as gl_platform
    monkeypatch.setattr(terrain_gl.sys, 'platform', 'darwin')
    monkeypatch.setattr(gl_platform, 'PLATFORM', SimpleNamespace(
        GetCurrentContext=lambda: None))
    assert terrain_gl._no_current_gl_context() is True
    monkeypatch.setattr(gl_platform, 'PLATFORM', SimpleNamespace(
        GetCurrentContext=lambda: 1))
    assert terrain_gl._no_current_gl_context() is False
    monkeypatch.setattr(terrain_gl.sys, 'platform', 'linux')
    assert terrain_gl._no_current_gl_context() is False
