"""Queries for optional input-ownership capabilities on a running game session.

This module is intentionally independent of Qt so routing policy can be tested
without creating a renderer or a QApplication.
"""


def modal_input_active(logic) -> bool:
    """Whether the current game session claims keys for a modal screen.

    Sessions that implement the modal_input_active method may reserve input
    for dialogue or another game-owned screen. When the capability is absent,
    Fio keeps its normal shortcut handling.
    """
    session = getattr(logic, "game_session", None)
    query = getattr(session, "modal_input_active", None)
    return bool(query()) if callable(query) else False


def owns_number_keys(logic) -> bool:
    """Whether the running game reads the number keys itself.

    Fio maps 1-4 to its own weapon slots (gun1, gun2, custom1, custom2). A
    game with its own slot bar sets ``owns_number_keys`` on its session, and
    the keys then reach it as ordinary key presses instead.
    """
    session = getattr(logic, "game_session", None)
    return bool(getattr(session, "owns_number_keys", False))


def modal_escape_active(logic) -> bool:
    """Whether the running game wants Escape routed to its own modal UI.

    The editor's MainWindow already forwards Escape to sessions that implement
    escape_closes_modal(). This query lets a child viewport avoid opening
    Fio's pause menu before that parent-level routing can happen.
    """
    session = getattr(logic, "game_session", None)
    query = getattr(session, "escape_closes_modal", None)
    if not callable(query):
        return False
    try:
        return bool(query())
    except Exception:
        return False

