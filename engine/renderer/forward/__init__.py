"""Fio's built-in forward renderer.

Keep the package light when callers import a pure pass or helper. Constructing
the renderer pulls in Qt and the full OpenGL resource stack, so load it only
when the public ForwardRenderer export is actually requested.
"""

__all__ = ['ForwardRenderer']


def __getattr__(name):
    if name == "ForwardRenderer":
        from .renderer import ForwardRenderer

        globals()["ForwardRenderer"] = ForwardRenderer
        return ForwardRenderer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
