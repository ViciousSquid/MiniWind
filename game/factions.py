"""Compatibility shim: factions now lives in game.rpg.factions."""
from .rpg.factions import *  # noqa: F401,F403
from .rpg import factions as _mod
import sys as _sys
_sys.modules[__name__].__dict__.update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith('__')})

