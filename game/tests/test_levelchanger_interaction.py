"""MiniWind's custom HUD preserves the engine's use prompt and target."""

from types import SimpleNamespace

import pytest

from game.host import MiniwindGame
from plugins.api import TickContext


@pytest.mark.parametrize('use_pressed', [False, True])
def test_core_cave_prompt_is_visible_and_does_not_open_another_interaction(use_pressed):
    prompt = '[E] Enter Wolfmaw Cave'
    logic = SimpleNamespace(interaction_runtime=SimpleNamespace(current_hud_message=prompt))
    # A core-owned interaction should return before querying actors/containers.
    session = SimpleNamespace(interact_prompt='old prompt')
    context = TickContext(logic=logic, use_pressed=use_pressed, interaction_consumed=True)

    MiniwindGame()._handle_interaction(logic, context, session, {'e'})

    assert session.interact_prompt == prompt
    assert logic.interaction_runtime.current_hud_message == prompt


def test_core_prompt_is_cleared_when_the_player_leaves_the_changer():
    session = SimpleNamespace(interact_prompt='[E] Enter Wolfmaw Cave')
    logic = SimpleNamespace(interaction_runtime=SimpleNamespace(current_hud_message=''))

    MiniwindGame()._handle_interaction(logic, TickContext(logic=logic), session)

    assert session.interact_prompt == ''
