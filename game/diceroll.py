"""Engine-native dice rolling with the public diceroll compatibility surface.

The rules are headless and accept an injected ``random.Random`` instance, so the
RPG session can keep rolls reproducible in tests and can share its normal game
random stream. UI animation is intentionally separate from this module.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple


MAX_DICE_PER_TERM = 1000
MAX_DIE_SIDES = 10000
HISTORY_LIMIT = 5
MAX_PROBABILITY_CELLS = 100000
DICE_TYPES = (4, 6, 8, 10, 12, 20)


class DiceColor:
    """Named colour values retained for callers of the supplied API."""

    RED = "red"
    BLUE = "blue"
    BLACK = "black"
    WHITE = "white"
    GREEN = "green"


class AnimationStyle:
    """Animation names understood by the native HUD."""

    SHAKE = "shake"
    TUMBLE = "tumble"
    SPIN = "spin"


class DiceType:
    """Canonical notation constants for supported tabletop dice."""

    D4 = "d4"
    D6 = "d6"
    D8 = "d8"
    D10 = "d10"
    D12 = "d12"
    D20 = "d20"


class DiceNotationError(ValueError):
    """Raised when a dice expression cannot be parsed safely."""


@dataclass(frozen=True)
class DiceTerm:
    """One signed dice term or numeric modifier in a parsed expression."""

    sign: int
    count: int
    sides: int
    modifier: int = 0

    @property
    def notation(self) -> str:
        """Return the canonical notation for this term."""
        if self.sides:
            return f"{self.count}d{self.sides}"
        return str(abs(self.modifier))


def parse_dice_notation(dice_notation: str) -> Tuple[List[DiceTerm], str]:
    """Parse ``NdM`` expressions with optional signed dice and modifiers.

    Examples include ``d20``, ``1d20+2d6+3`` and ``2d8 - 1``. At least one
    dice term is required; each die is bounded to prevent malformed content from
    allocating excessive memory or consuming the game loop.
    """
    source = str(dice_notation or "").strip()
    if not source:
        raise DiceNotationError("Dice notation cannot be empty")

    terms: List[DiceTerm] = []
    index = 0
    expect_term = True
    has_dice = False
    length = len(source)

    while index < length:
        while index < length and source[index].isspace():
            index += 1
        if index >= length:
            break

        sign = 1
        if source[index] in "+-":
            sign = -1 if source[index] == "-" else 1
            index += 1
            while index < length and source[index].isspace():
                index += 1
        elif not expect_term:
            raise DiceNotationError(f"Expected '+' or '-' near: {source[index:]}")

        start = index
        while index < length and source[index].isdigit():
            index += 1
        digits = source[start:index]
        while index < length and source[index].isspace():
            index += 1

        if index < length and source[index].lower() == "d":
            count = int(digits) if digits else 1
            index += 1
            while index < length and source[index].isspace():
                index += 1
            face_start = index
            while index < length and source[index].isdigit():
                index += 1
            if face_start == index:
                raise DiceNotationError("A dice term needs a number of sides")
            sides = int(source[face_start:index])
            if count < 1 or count > MAX_DICE_PER_TERM:
                raise DiceNotationError(f"Dice count must be between 1 and {MAX_DICE_PER_TERM}")
            if sides < 2 or sides > MAX_DIE_SIDES:
                raise DiceNotationError(f"Die sides must be between 2 and {MAX_DIE_SIDES}")
            terms.append(DiceTerm(sign=sign, count=count, sides=sides))
            has_dice = True
        elif digits:
            modifier = int(digits)
            if modifier == 0:
                raise DiceNotationError("A zero modifier is not useful in dice notation")
            terms.append(DiceTerm(sign=sign, count=0, sides=0, modifier=modifier))
        else:
            raise DiceNotationError(f"Invalid dice notation near: {source[start:]}")

        expect_term = False
        while index < length and source[index].isspace():
            index += 1
        if index < length and source[index] not in "+-":
            raise DiceNotationError(f"Invalid dice notation near: {source[index:]}")

    if not has_dice:
        raise DiceNotationError("Dice notation must contain at least one die")
    return terms, source


class DiceRoller:
    """Roll and inspect tabletop dice while retaining the last five results."""

    def __init__(self, save_rolls: bool = False, save_format: str = "json",
                 rng: Optional[random.Random] = None):
        self.last_roll_total: Optional[int] = None
        self.last_roll_details: Optional[List[int]] = None
        self.last_5_rolls: List[Dict] = []
        self.save_rolls = bool(save_rolls)
        self.roll_history: List[Dict] = []
        self.save_format = str(save_format)
        self.rng = rng or random.Random()
        self._roll_listeners: List[Callable] = []

    def add_roll_listener(self, listener: Callable) -> None:
        """Subscribe to ``(result, source, context)`` notifications for each roll."""
        if listener not in self._roll_listeners:
            self._roll_listeners.append(listener)

    def remove_roll_listener(self, listener: Callable) -> None:
        """Stop sending roll notifications to *listener*."""
        if listener in self._roll_listeners:
            self._roll_listeners.remove(listener)

    def request_roll(self, dice_notation: str, target: Optional[int] = None,
                     source: str = "gameplay", context: Optional[Dict] = None) -> Dict:
        """Request a roll through the engine channel and return its result."""
        return self.roll_dice(dice_notation, target=target, source=source,
                              context=context)

    def _publish_roll(self, result: Dict, source: str, context: Optional[Dict]) -> None:
        """Notify roll subscribers without allowing one listener to break gameplay."""
        for listener in tuple(self._roll_listeners):
            try:
                listener(result, source, context or {})
            except Exception:
                continue

    def roll_dice(self, dice_notation: str, target: Optional[int] = None,
                  success_outcome=None, failure_outcome=None,
                  source: str = "gameplay", context: Optional[Dict] = None) -> Dict:
        """Roll an expression, publish it, and return the supplied API's result."""
        terms, notation_source = parse_dice_notation(dice_notation)
        details: List[int] = []
        components: List[Dict] = []
        total = 0
        modifier_total = 0

        for term in terms:
            if term.sides:
                values = [self.rng.randint(1, term.sides) for _ in range(term.count)]
                signed_values = [term.sign * value for value in values]
                details.extend(values)
                component_total = sum(signed_values)
                components.append({
                    "notation": f"{term.count}d{term.sides}",
                    "roll_details": values,
                    "roll_result": component_total,
                })
                total += component_total
            else:
                signed_modifier = term.sign * term.modifier
                modifier_total += signed_modifier
                total += signed_modifier
                components.append({
                    "notation": ("-" if term.sign < 0 else "+") + str(term.modifier),
                    "roll_details": [],
                    "roll_result": signed_modifier,
                })

        result = {
            "dice_notation": notation_source,
            "roll_result": total,
            "roll_details": details,
            "components": components,
            "modifier": modifier_total,
        }
        if target is not None:
            result["target"] = int(target)
            result["success"] = total >= int(target)
            if success_outcome is not None and failure_outcome is not None:
                chosen = success_outcome if result["success"] else failure_outcome
                result["outcome"] = dict(chosen) if isinstance(chosen, dict) else chosen
                if isinstance(result["outcome"], dict):
                    result["outcome"]["roll_result"] = total

        self.last_roll_total = total
        self.last_roll_details = list(details)
        self.last_5_rolls = (self.last_5_rolls + [result])[-HISTORY_LIMIT:]
        if self.save_rolls:
            self.roll_history.append(result)
        self._publish_roll(result, str(source or "gameplay"), context)
        return result

    def roll_single_dice(self, dice_type: str, dice_color: str = DiceColor.WHITE) -> Dict:
        """Roll one die using ``d4``/``d6``/… notation."""
        return self.roll_dice(self._normalise_single(dice_type))

    def roll_multiple_dice_of_same_type(self, dice_type: str, num_dice: int,
                                        dice_color: str = DiceColor.WHITE) -> Dict:
        """Roll multiple dice of one type."""
        return self.roll_dice(f"{int(num_dice)}{self._normalise_single(dice_type)}")

    def roll_multiple_dice(self, dice_notations: Sequence[str], dice_colors=None,
                           target_values=None) -> List[Dict]:
        """Roll a sequence of independent expressions."""
        targets = list(target_values) if target_values is not None else [None] * len(dice_notations)
        if len(targets) != len(dice_notations):
            raise ValueError("target_values must match dice_notations")
        return [self.roll_dice(notation, target=targets[i])
                for i, notation in enumerate(dice_notations)]

    def roll_with_advantage(self, dice_notation: str, dice_colour: str = DiceColor.BLUE,
                            animate: bool = True) -> Dict:
        """Roll twice and return the higher total."""
        first = self.roll_dice(dice_notation)
        second = self.roll_dice(dice_notation)
        return first if first["roll_result"] >= second["roll_result"] else second

    def roll_with_disadvantage(self, dice_notation: str, dice_colour: str = DiceColor.BLUE,
                               animate: bool = True) -> Dict:
        """Roll twice and return the lower total."""
        first = self.roll_dice(dice_notation)
        second = self.roll_dice(dice_notation)
        return first if first["roll_result"] <= second["roll_result"] else second

    def roll_saving_throw(self, dice_type: str = DiceType.D20,
                          dice_color: str = DiceColor.WHITE,
                          target_value: Optional[int] = None,
                          success_threshold: Optional[int] = None) -> Optional[Dict]:
        """Roll a saving throw and mark whether the threshold was met."""
        threshold = success_threshold if success_threshold is not None else target_value
        result = self.roll_single_dice(dice_type, dice_color)
        if threshold is not None:
            result["success"] = result["roll_result"] >= int(threshold)
        return result

    def get_roll_statistics(self, dice_notation: str, num_rolls: int) -> Dict:
        """Return average, range and frequency for repeated rolls."""
        count = int(num_rolls)
        if count < 1:
            raise ValueError("num_rolls must be at least 1")
        values = [self.roll_dice(dice_notation)["roll_result"] for _ in range(count)]
        return {
            "dice_notation": str(dice_notation),
            "num_rolls": count,
            "average": sum(values) / count,
            "min": min(values),
            "max": max(values),
            "frequency": self.calculate_frequency(values),
        }

    @staticmethod
    def calculate_frequency(roll_results: Sequence[int]) -> Dict[int, int]:
        """Count each total in a sequence of rolls."""
        frequency = defaultdict(int)
        for result in roll_results:
            frequency[int(result)] += 1
        return dict(frequency)

    def get_dice_probabilities(self, dice_notation: str) -> Dict[int, float]:
        """Return exact probabilities for one homogeneous ``NdM`` expression."""
        terms, _source = parse_dice_notation(dice_notation)
        if len(terms) != 1 or not terms[0].sides or terms[0].sign != 1:
            raise DiceNotationError("Probabilities require one positive NdM term")
        term = terms[0]
        if term.count * term.sides > MAX_PROBABILITY_CELLS:
            raise DiceNotationError("Probability request is too large")
        counts = {0: 1}
        for _ in range(term.count):
            next_counts = defaultdict(int)
            for subtotal, ways in counts.items():
                for face in range(1, term.sides + 1):
                    next_counts[subtotal + face] += ways
            counts = dict(next_counts)
        total_ways = term.sides ** term.count
        return {total: ways / total_ways for total, ways in sorted(counts.items())}

    def get_last_roll_total(self):
        """Return the latest total, or ``None`` before the first roll."""
        return self.last_roll_total

    def get_last_roll_details(self):
        """Return a copy of the latest individual die results."""
        return list(self.last_roll_details or [])

    def get_last_5_rolls(self):
        """Return a copy of the recent roll buffer."""
        return list(self.last_5_rolls)

    def get_roll_history(self):
        """Return the full in-memory history when saving is enabled."""
        return list(self.roll_history)

    def set_roll_history(self, roll_history):
        """Replace the in-memory history with JSON-compatible roll records."""
        self.roll_history = list(roll_history or [])

    def save_last_5_rolls(self, file_path: str):
        """Save the recent buffer as JSON or plain text."""
        if str(self.save_format).lower() == "txt":
            with open(file_path, "w", encoding="utf-8") as output:
                for index, roll in enumerate(self.last_5_rolls, 1):
                    output.write(f"Result {index}:\n")
                    output.write(f"  Dice Notation: {roll['dice_notation']}\n")
                    output.write(f"  Roll Result: {roll['roll_result']}\n")
                    output.write(f"  Roll Details: {roll['roll_details']}\n\n")
        else:
            with open(file_path, "w", encoding="utf-8") as output:
                json.dump(self.last_5_rolls, output, indent=2)

    @staticmethod
    def _normalise_single(dice_type: str) -> str:
        notation = str(dice_type).strip().lower()
        return notation if notation.startswith("d") else "d" + notation


class dicerollAPI:
    """Compatibility facade matching the uploaded ``diceroll_api.py`` name."""

    def __init__(self, save_rolls: bool = False, log_console=None,
                 rng: Optional[random.Random] = None):
        self.dice_roller = DiceRoller(save_rolls=save_rolls, rng=rng)
        try:
            from .diceroll_anim import DiceAnimator
            self.dice_animator = DiceAnimator()
        except ImportError:
            self.dice_animator = None
        self.log_console = bool(log_console) if log_console is not None else False
        self.animation_style = AnimationStyle.SHAKE

    def request_roll(self, dice_notation: str, target: Optional[int] = None,
                     source: str = "gameplay", context: Optional[Dict] = None) -> Dict:
        """Request a roll and publish it through the compatibility facade."""
        return self.dice_roller.request_roll(dice_notation, target=target,
                                              source=source, context=context)

    def add_roll_listener(self, listener: Callable) -> None:
        """Subscribe to rolls produced by the compatibility facade."""
        self.dice_roller.add_roll_listener(listener)

    def remove_roll_listener(self, listener: Callable) -> None:
        """Remove a compatibility-facade roll listener."""
        self.dice_roller.remove_roll_listener(listener)

    def roll_single_dice(self, dice_type: str, dice_color: str = DiceColor.WHITE) -> Dict:
        """Roll a single canonical die."""
        return self.dice_roller.roll_single_dice(dice_type, dice_color)

    def roll_multiple_dice_of_same_type(self, dice_type: str, num_dice: int,
                                        dice_color: str = DiceColor.WHITE) -> Dict:
        """Roll multiple dice of the same canonical type."""
        return self.dice_roller.roll_multiple_dice_of_same_type(dice_type, num_dice, dice_color)

    def roll_multiple_dice(self, dice_notations, dice_colors=None, target_values=None) -> List[Dict]:
        """Roll multiple expressions."""
        return self.dice_roller.roll_multiple_dice(dice_notations, dice_colors, target_values)

    def set_dice_image_path(self, path="assets/dice_imgs"):
        """Retain a legacy image path without coupling the engine to HTML assets."""
        self.dice_image_path = str(path)
        if self.dice_animator is not None:
            self.dice_animator.dice_image_path = self.dice_image_path

    def get_roll_history(self):
        """Return the full in-memory roll history."""
        return self.dice_roller.get_roll_history()

    def set_roll_history(self, roll_history):
        """Replace the full in-memory roll history."""
        self.dice_roller.set_roll_history(roll_history)

    def get_dice_probabilities(self, dice_notation: str) -> Dict[int, float]:
        """Return exact probabilities for a homogeneous dice expression."""
        return self.dice_roller.get_dice_probabilities(dice_notation)

    def calculate_frequency(self, roll_results: Sequence[int]) -> Dict[int, int]:
        """Count totals in a sequence of roll results."""
        return self.dice_roller.calculate_frequency(roll_results)


    def get_roll_sum(self, roll_result: Dict) -> int:
        """Return a result total."""
        return int(roll_result["roll_result"])

    def get_roll_average(self, roll_result: Dict) -> float:
        """Return the average of the individual dice in a result."""
        details = roll_result.get("roll_details", [])
        return sum(details) / len(details) if details else 0.0

    def get_roll_max(self, roll_result: Dict) -> int:
        """Return the largest individual die result."""
        return max(roll_result.get("roll_details", [0]))

    def get_roll_min(self, roll_result: Dict) -> int:
        """Return the smallest individual die result."""
        return min(roll_result.get("roll_details", [0]))

    def get_roll_statistics(self, dice_notation: str, num_rolls: int) -> Dict:
        """Return repeated-roll statistics."""
        return self.dice_roller.get_roll_statistics(dice_notation, num_rolls)

    def get_last_roll_total(self):
        """Return the latest total."""
        return self.dice_roller.get_last_roll_total()

    def get_last_roll_details(self):
        """Return the latest individual dice."""
        return self.dice_roller.get_last_roll_details()

    def get_last_5_rolls(self):
        """Return the recent roll buffer."""
        return self.dice_roller.get_last_5_rolls()

    def get_available_dice_colors(self):
        """Return the named compatibility colours."""
        return [DiceColor.RED, DiceColor.BLUE, DiceColor.BLACK, DiceColor.WHITE, DiceColor.GREEN]

    def set_animation_style(self, style: str = AnimationStyle.SHAKE):
        """Retain the requested style for callers that supply one."""
        self.animation_style = style
        if self.dice_animator is not None:
            self.dice_animator.animation_style = style

    def roll_saving_throw(self, dice_type: str = DiceType.D20,
                          dice_color: str = DiceColor.WHITE,
                          target_value: Optional[int] = None,
                          success_threshold: Optional[int] = None) -> Optional[Dict]:
        """Roll and mark a saving throw."""
        return self.dice_roller.roll_saving_throw(
            dice_type, dice_color, target_value, success_threshold
        )

    def roll_multiple_saving_throws(self, num_throws: int, dice_type: str = DiceType.D20,
                                     dice_color: str = DiceColor.WHITE,
                                     target_values=None, success_thresholds=None) -> List[Dict]:
        """Roll and mark a batch of saving throws."""
        targets = list(target_values) if target_values is not None else [None] * int(num_throws)
        thresholds = (list(success_thresholds) if success_thresholds is not None
                      else targets)
        if len(targets) != int(num_throws) or len(thresholds) != int(num_throws):
            raise ValueError("saving-throw target arrays must match num_throws")
        return [self.dice_roller.roll_saving_throw(
                    dice_type, dice_color, targets[index], thresholds[index])
                for index in range(int(num_throws))]

    def enable_console_logging(self):
        """Keep the legacy flag without redirecting the engine's stdout."""
        self.log_console = True

    def disable_console_logging(self):
        """Disable legacy console logging."""
        self.log_console = False


    def enable_roll_saving(self):
        """Enable in-memory full roll history."""
        self.dice_roller.save_rolls = True

    def disable_roll_saving(self):
        """Disable in-memory full roll history."""
        self.dice_roller.save_rolls = False

    def save_roll_history_to_file(self, file_path: str):
        """Save the full roll history as JSON."""
        with open(file_path, "w", encoding="utf-8") as output:
            json.dump(self.dice_roller.get_roll_history(), output, indent=2)

    def load_roll_history_from_file(self, file_path: str):
        """Load full roll history from JSON."""
        with open(file_path, "r", encoding="utf-8") as source:
            history = json.load(source)
        self.dice_roller.set_roll_history(history)
        return history


__all__ = [
    "AnimationStyle", "DiceColor", "DiceNotationError", "DiceRoller", "DiceTerm",
    "DiceType", "dicerollAPI", "parse_dice_notation",
]
