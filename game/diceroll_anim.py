"""Animation timing shared by callers that use the supplied dice API.

The actual rendering is performed by ``game.ui.hud`` so the dice presentation
uses the engine's existing QPainter overlay rather than HTML or Flask.
"""

from __future__ import annotations

from .diceroll import AnimationStyle


SHAKE_DURATION = 0.75
ROLL_DURATION = 1.0
FADE_DURATION = 1.25


class DiceAnimator:
    """Describe a dice animation for the native Miniwind HUD."""

    def __init__(self, dice_image_path="assets/dice_imgs"):
        self.dice_image_path = dice_image_path
        self.animation_style = AnimationStyle.SHAKE

    def animation_timing(self):
        """Return the supplied animation timing in seconds."""
        return {
            "shake": SHAKE_DURATION,
            "roll": ROLL_DURATION,
            "fade": FADE_DURATION,
        }


__all__ = ["DiceAnimator", "SHAKE_DURATION", "ROLL_DURATION", "FADE_DURATION"]
