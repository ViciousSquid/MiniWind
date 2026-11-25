"""Illuminated initials (game/ui/initials.py): the journal's drop caps and a
conversation's capital, in the chosen style -- the dark printing block."""
import pytest

pytest.importorskip("PyQt5")

pytestmark = pytest.mark.qt


def test_the_chosen_style_is_the_dark_block():
    from game.ui import initials
    assert initials.STYLE == "block"


@pytest.mark.parametrize("style", ["block", "manuscript", "foliate", "foliate_block"])
def test_every_style_draws_a_square_initial(qt_app, style):
    from game.ui import initials
    for px in (40, 160):                          # inline capital, drop cap
        img = initials.image("A", "red", False, px, style)
        assert (img.width(), img.height()) == (px, px)
        assert any(img.pixelColor(x, y).alpha() for x in range(0, px, 4) for y in range(0, px, 4))


def test_the_block_is_dark_and_the_capital_is_in_its_pigment(qt_app):
    from game.ui import initials
    img = initials.image("O", "red", False, 200, "block")
    corner = img.pixelColor(12, 12)
    assert corner.alpha() == 255 and max(corner.red(), corner.green(), corner.blue()) < 120
    reds = sum(1 for x in range(0, 200, 3) for y in range(0, 200, 3)
               if img.pixelColor(x, y).red() > 180 and img.pixelColor(x, y).green() < 120)
    assert reds > 40                               # the red capital


def test_grey_initials_have_no_colour(qt_app):
    from game.ui import initials
    img = initials.image("B", "green", True, 120, "block")
    for x in range(0, 120, 7):
        for y in range(0, 120, 7):
            c = img.pixelColor(x, y)
            if c.alpha() > 200:
                assert abs(c.red() - c.green()) <= 2 and abs(c.green() - c.blue()) <= 2


def test_a_conversation_opens_with_an_illuminated_capital(qt_app):
    from game.ui import dialogue_ui
    assert dialogue_ui._initial_of("Wolves again.") == ("W", "olves again.")
    assert dialogue_ui._initial_of("...well.") == ("", "...well.")
    from PyQt5.QtGui import QFontMetrics
    font = dialogue_ui._body_font()
    fm = QFontMetrics(font)
    side = dialogue_ui._initial_side(fm)
    assert fm.height() <= side <= fm.height() * 1.3   # the size of the text, not a big drop cap
    layout, h = dialogue_ui._flow("olves again, last night.", font, 400, side + 4)
    assert layout.lineAt(0).position().x() == pytest.approx(side + 4)   # room for it
