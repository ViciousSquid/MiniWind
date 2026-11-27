"""MiniWind's game-owned console commands appear in the game's help section."""

from editor.debug_console import get_debug_logger


def _help_text(handler):
    logger = get_debug_logger()
    logger.clear_buffer()
    handler.handle_command("help")
    (category, text), = logger.get_buffer()
    assert category == "Info"
    return text


def test_the_built_in_games_commands_have_their_own_section_last(main_window):
    """Commands owned by game/console.py stay in the MiniWind help section."""
    import game
    from game import console

    game.install()
    handler = main_window.console_handler
    sections = handler.help_sections()
    title, _intro, entries = sections[-1]
    assert title == "MiniWind Commands"
    listed = [names for names, _usage in entries]
    for names, _handler, _help_text in console.COMMANDS:
        assert tuple(names) in listed, names
    assert len(listed) == len(console.COMMANDS)
    others = {n for _title, _intro, entries in sections[:-1]
              for names, _usage in entries for n in names}
    assert not others & {n for names, _handler, _help in console.COMMANDS for n in names}

    help_text = _help_text(handler)
    assert "=== MiniWind Commands ===" in help_text
    assert help_text.index("=== MiniWind Commands ===") > help_text.index("=== Debug ===")
    assert "diceroll</b>" in help_text and "dice</b>" in help_text
