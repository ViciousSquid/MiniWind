"""
The look of fire: one for every fire in the game.

Burning bodies, a Flare's fire on the ground, grass fire and a dragon's
breath are all the engine's FIRE Effect, and all use the same one of its
animations, chosen here. It is a developer option, not a player one:
``fire_style`` under ``[GAME]`` in ``settings.ini`` (1..4, the engine's
``fire01`` .. ``fire04``), else :data:`DEFAULT_STYLE`. The console's
``dragonfire N`` changes it for the session.
"""

from __future__ import annotations

#: The engine's FIRE animations that carry a light colour of their own
#: (engine/entity_table.py), so a fire lights the ground its own colour.
STYLES = 4
#: Fire, unless settings.ini says otherwise.
DEFAULT_STYLE = 2

_override = None


def texture_for(style: int) -> str:
    return f"assets/textures/effects/fire{int(style):02d}.gif"


def style(config=None) -> int:
    """The fire style in use (1..:data:`STYLES`)."""
    if _override is not None:
        return _override
    if config is None:
        try:
            from . import runtime
            config = runtime._editor_config
        except Exception:
            config = None
    try:
        value = config.getint("GAME", "fire_style", fallback=DEFAULT_STYLE) if config else DEFAULT_STYLE
    except (AttributeError, TypeError, ValueError):
        value = DEFAULT_STYLE
    return value if 1 <= value <= STYLES else DEFAULT_STYLE


def texture(config=None) -> str:
    """The FIRE animation every fire is made of."""
    return texture_for(style(config))


def set_for_session(value) -> bool:
    """Use fire style *value* until the game is closed (the console)."""
    global _override
    try:
        value = int(value)
    except (TypeError, ValueError):
        return False
    if not 1 <= value <= STYLES:
        return False
    _override = value
    return True
