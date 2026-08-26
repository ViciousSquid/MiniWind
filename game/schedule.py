"""Compatibility shim: schedule now lives in game.rpg.schedule."""
from .rpg.schedule import *  # noqa: F401,F403
from .rpg import schedule as _mod
import sys as _sys
_sys.modules[__name__].__dict__.update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith('__')})

