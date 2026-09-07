"""
Shared pytest setup.

Several test modules exercise code that lives behind the render stack —
``editor.main_window``, ``engine.qt_game_view`` — on machines with no OpenGL
driver, where PyOpenGL cannot even be imported. They stub the GL modules for the
import, and :func:`install_gl_stubs` is the one correct way to do it.

Doing it with ``mock.patch.dict(sys.modules, ...)`` is a trap: on exit the patch
removes *everything* imported inside the block, which includes heavy transitive
imports like numpy. numpy's C extension cannot be imported twice in one process,
so the next test module that imports it dies with "cannot load module more than
once per process" — and the failure lands on an innocent module, several files
later. The stubs installed here are permanent and only ever fill a genuine gap:
where PyOpenGL really is installed, nothing is replaced.
"""

from __future__ import annotations

import sys

#: The GL modules the render stack imports at module scope.
_GL_MODULES = (
    "OpenGL",
    "OpenGL.GL",
    "OpenGL.GLU",
    "OpenGL.GLUT",
    "OpenGL.GL.shaders",
    "OpenGL.arrays",
    "OpenGL.arrays.vbo",
)


def install_gl_stubs():
    """Make ``import OpenGL...`` succeed on a machine with no GL driver.

    A no-op where PyOpenGL imports for real. Returns True if any stub was
    installed, so a test can say why it is running against a fake.
    """
    from unittest import mock

    try:
        import OpenGL.GL  # noqa: F401
        return False
    except Exception:
        pass

    installed = False
    for name in _GL_MODULES:
        if name not in sys.modules:
            sys.modules[name] = mock.MagicMock(name=name)
            installed = True
    return installed
