"""macOS must not call shader entry points before a GL context exists."""

from types import SimpleNamespace

import pytest

pytest.importorskip('OpenGL')
from engine import terrain

pytestmark = pytest.mark.qt


def test_terrain_shader_compilation_defers_and_can_retry_after_a_context_arrives(monkeypatch):
    current = [None]
    monkeypatch.setattr(terrain, 'gl_platform', SimpleNamespace(
        PLATFORM=SimpleNamespace(GetCurrentContext=lambda: current[0])))
    calls = []
    monkeypatch.setattr(terrain, 'compileShader', lambda code, kind: calls.append(kind) or 11)
    monkeypatch.setattr(terrain, 'compileProgram', lambda *args, **kwargs: 77)
    monkeypatch.setattr(terrain, 'gl', SimpleNamespace(
        GL_VERTEX_SHADER=1, GL_FRAGMENT_SHADER=2, GL_INVALID_INDEX=0xFFFFFFFF,
        glGetUniformBlockIndex=lambda *args: 0xFFFFFFFF))
    obj = terrain.Terrain.__new__(terrain.Terrain)
    obj._failed_programs = set()
    assert obj._compile_program('terrain.vert') == 0
    obj._init_grass_shader()
    assert calls == []
    assert obj._failed_programs == set()
    current[0] = 1
    assert obj._compile_program('terrain.vert') == 77
    assert calls == [1, 2]
