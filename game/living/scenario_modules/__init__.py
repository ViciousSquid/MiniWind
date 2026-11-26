"""Reusable world-scenario implementations."""

from .ambush import AmbushScenario
from .avenger import AvengerScenario
from .cult_rite import CultRiteScenario
from .gratitude import GratitudeScenario
from .patrol import PatrolScenario
from .procession import ProcessionScenario
from .reckoning import ReckoningScenario
from .waylaid import WaylaidScenario

MODULE_TYPES = {
    "waylaid": WaylaidScenario,
    "avenger": AvengerScenario,
    "reckoning": ReckoningScenario,
    "gratitude": GratitudeScenario,
    "patrol": PatrolScenario,
    "ambush": AmbushScenario,
    "procession": ProcessionScenario,
    "cult_rite": CultRiteScenario,
}


def create_modules():
    """Create independent module instances for one ScenarioDirector."""
    return {kind: scenario_type() for kind, scenario_type in MODULE_TYPES.items()}


def dialogue_module(kind):
    """Return a stateless scenario module for scene-derived presentation."""
    scenario_type = MODULE_TYPES.get(kind)
    return scenario_type() if scenario_type is not None else None
