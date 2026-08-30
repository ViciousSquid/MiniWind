"""Compatibility imports for the integrated dice API."""

from .diceroll import (AnimationStyle, DiceColor, DiceNotationError, DiceRoller,
                       DiceType, dicerollAPI)
from .diceroll_anim import DiceAnimator

__all__ = [
    "AnimationStyle", "DiceColor", "DiceNotationError", "DiceRoller", "DiceType",
    "DiceAnimator", "dicerollAPI",
]
