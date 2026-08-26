"""Compatibility shim: inventory now lives in game.rpg.inventory."""
from .rpg.inventory import *  # noqa: F401,F403
from .rpg import inventory as _mod
import sys as _sys
_sys.modules[__name__].__dict__.update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith('__')})

