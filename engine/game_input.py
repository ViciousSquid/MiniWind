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
