"""Compatibility shim: gametime now lives in game.rpg.gametime."""
from .rpg.gametime import *  # noqa: F401,F403
from .rpg import gametime as _mod
import sys as _sys
_sys.modules[__name__].__dict__.update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith('__')})

