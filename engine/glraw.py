"""Native GL entry points for the calls a frame makes most, without PyOpenGL's
Python wrapper.

Every call through ``OpenGL.GL`` runs several Python functions before the C
function is reached (argument conversion, the error checker, the context
bookkeeping); for a ``glBindTexture`` that is the whole cost. A frame makes
hundreds of these calls, so the wrapper was most of the Python a frame ran.

:func:`fn` returns the entry point PyOpenGL itself resolved (``load()`` on its
own raw function object: its calling convention, its argument and return
types -- see :mod:`engine.renderer.core.uniform_rows` for why that is the
safe way to make the native call), for functions whose arguments are all
scalars, so nothing is converted that PyOpenGL would have converted
differently. ``FIO_GL_DEBUG=1``, PyOpenGL's error checking left on, or an
entry point that does not resolve gives the ordinary checked wrapper instead.
Call these only with a current context, as the wrappers.

:func:`get_integer` reads a single-integer ``glGetIntegerv`` into a ctypes
int the same way.
"""

from __future__ import annotations

import ctypes
import os

import OpenGL
import OpenGL.GL as gl

_GL_DEBUG = os.environ.get("FIO_GL_DEBUG") == "1"

#: PyOpenGL's raw modules, searched in order for a function's entry point.
_RAW_MODULES = ("GL_1_0", "GL_1_1", "GL_1_3", "GL_1_4", "GL_1_5", "GL_2_0",
                "GL_3_0", "GL_3_1", "GL_3_2", "GL_3_3", "GL_4_0", "GL_4_2")

_resolved = {}


def enabled() -> bool:
    """Whether native calls are used (not when every call is to be checked)."""
    return not _GL_DEBUG and not getattr(OpenGL, "ERROR_CHECKING", True)


def _native(name):
    import importlib
    for module in _RAW_MODULES:
        try:
            raw = getattr(importlib.import_module("OpenGL.raw.GL.VERSION." + module),
                          name, None)
        except ImportError:
            continue
        if raw is None:
            continue
        try:
            loaded = raw.load()
        except Exception:
            return None
        if loaded is None or not ctypes.cast(loaded, ctypes.c_void_p).value:
            return None
        if not all(isinstance(t, type) and issubclass(t, ctypes._SimpleCData)
                   and t._type_ not in "zZPOX" for t in (loaded.argtypes or ())):
            return None           # pointer and array arguments stay with the wrapper
        return loaded
    return None


def fn(name):
    """The native entry point for GL function *name*, else PyOpenGL's wrapper
    (or None when PyOpenGL has neither -- an extension the driver lacks)."""
    if name in _resolved:
        return _resolved[name]
    native = _native(name) if enabled() else None
    if native is None:
        wrapper = getattr(gl, name, None)
        native = wrapper if wrapper is not None and bool(wrapper) else None
    _resolved[name] = native
    return native


def available(name) -> bool:
    """Whether the driver provides GL function *name* at all."""
    return fn(name) is not None


_get_integerv = None


def get_integer(pname) -> int:
    """``glGetIntegerv`` of one integer, read without the wrapper."""
    global _get_integerv
    if _get_integerv is None:
        native = None
        if enabled():
            try:
                from OpenGL.raw.GL.VERSION import GL_1_0
                loaded = GL_1_0.glGetIntegerv.load()
                if loaded is not None and ctypes.cast(loaded, ctypes.c_void_p).value:
                    native = type(loaded)(ctypes.cast(loaded, ctypes.c_void_p).value)
                    native.argtypes = (loaded.argtypes[0], ctypes.c_void_p)
                    native.restype = loaded.restype
            except Exception:
                native = None
        _get_integerv = native or False
    if _get_integerv:
        # Room for the largest single query answer, though one int is asked.
        out = (ctypes.c_int * 16)()
        _get_integerv(int(pname), ctypes.addressof(out))
        return int(out[0])
    return int(gl.glGetIntegerv(pname))


def pointer_fn(name):
    """The native entry point for *name* with its pointer arguments taken as
    plain ``void *`` integers (an offset into a bound buffer), else None.

    For calls like ``glVertexAttribPointer(..., offset)`` whose pointer is an
    integer offset: PyOpenGL's array handler would only turn it back into the
    same address. Like :mod:`engine.renderer.core.uniform_rows`, only the
    declared type of the pointer arguments changes."""
    key = ("ptr", name)
    if key in _resolved:
        return _resolved[key]
    native = None
    if enabled():
        import importlib
        for module in _RAW_MODULES:
            try:
                raw = getattr(importlib.import_module("OpenGL.raw.GL.VERSION." + module),
                              name, None)
            except ImportError:
                continue
            if raw is None:
                continue
            try:
                loaded = raw.load()
                address = ctypes.cast(loaded, ctypes.c_void_p).value if loaded is not None else None
                if address:
                    native = type(loaded)(address)
                    native.argtypes = tuple(
                        t if isinstance(t, type) and issubclass(t, ctypes._SimpleCData)
                        and t._type_ not in "zZPOX" else ctypes.c_void_p
                        for t in loaded.argtypes)
                    native.restype = loaded.restype
            except Exception:
                native = None
            break
    _resolved[key] = native
    return native


def has_base_instance() -> bool:
    """Whether the current context draws from a base instance (GL 4.2, or
    ``GL_ARB_base_instance``): asked of the context, not of the entry point,
    which a driver may export whatever the context's version."""
    try:
        major = get_integer(gl.GL_MAJOR_VERSION)
        minor = get_integer(gl.GL_MINOR_VERSION)
        if (major, minor) >= (4, 2):
            return available("glDrawArraysInstancedBaseInstance")
        count = get_integer(gl.GL_NUM_EXTENSIONS)
        for i in range(count):
            ext = gl.glGetStringi(gl.GL_EXTENSIONS, i)
            if ext in (b"GL_ARB_base_instance", "GL_ARB_base_instance"):
                return available("glDrawArraysInstancedBaseInstance")
    except Exception:
        return False
    return False


# -- the array-argument calls a frame makes most -------------------------------
#
# Each still honours a replacement of the ``OpenGL.GL`` function (a test that
# counts draws patches ``gl.glDrawElements``): the native entry point is used
# only while the module attribute is PyOpenGL's own.

_ORIGINAL_U4 = getattr(gl, "glUniformMatrix4fv", None)
_ORIGINAL_DRAW = getattr(gl, "glDrawElements", None)
#: [native entry point], resolved on first use with a context current
#: (False: none; use the wrapper).
_U4 = [None]
_DRAW = [None]


def uniform_matrix4fv(via, location, count, transpose, value):
    """``via.glUniformMatrix4fv`` for a ``glm.value_ptr`` (or any ctypes
    pointer): *via* is the caller's ``gl`` module, so a stand-in a test put
    there still sees the call."""
    current = via.glUniformMatrix4fv
    if current is _ORIGINAL_U4:
        native = _U4[0]
        if native is None:
            native = _U4[0] = pointer_fn("glUniformMatrix4fv") or False
        if native:
            try:
                native(location, count, transpose, value)
                return
            except (TypeError, ctypes.ArgumentError):
                pass              # an array type ctypes cannot take: the wrapper
    current(location, count, transpose, value)


def draw_elements(via, mode, count, kind, indices):
    """``via.glDrawElements`` with *indices* an offset into the bound element
    buffer (*via* as for :func:`uniform_matrix4fv`)."""
    current = via.glDrawElements
    if current is _ORIGINAL_DRAW and (indices is None or isinstance(
            indices, (int, ctypes.c_void_p))):
        native = _DRAW[0]
        if native is None:
            native = _DRAW[0] = pointer_fn("glDrawElements") or False
        if native:
            native(mode, count, kind,
                   0 if indices is None else getattr(indices, "value", indices) or 0)
            return
    current(mode, count, kind, indices)
