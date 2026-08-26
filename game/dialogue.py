"""Compatibility shim: dialogue now lives in game.rpg.dialogue."""
from .rpg.dialogue import *  # noqa: F401,F403
from .rpg import dialogue as _mod
import sys as _sys
_sys.modules[__name__].__dict__.update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith('__')})

