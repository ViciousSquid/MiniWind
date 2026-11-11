"""Garbage-collector policy around level loads: MiniWind's name for
:mod:`engine.gc_policy`, which owns the one policy and its state."""

from .gc_policy import (  # noqa: F401
    SMALL_LEVEL_OBJECTS, LoadPolicy, _settings, level_load, release,
    set_freeze, settle,
)
