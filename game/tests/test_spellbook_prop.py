"""The spellbook is a Prop: the Tidy book model by default, its cover sprite
when billboarded, and a cover change reaches the renderer through the change
journal (property writes are not journalled on their own)."""

import os

import pytest

pytest.importorskip("PyQt5", reason="Prop is an editor-tier Thing")

from engine.change_journal import JOURNAL                 # noqa: E402
from engine.prop_entity import Prop                       # noqa: E402

from .. import entities                                   # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_a_spellbook_is_a_prop_showing_the_book_model():
    book = entities.Spellbook([0, 0, 0], {"spell": "firebolt", "cover": "green"})
    p = book.properties
    assert isinstance(book, Prop)
    assert p["render_mode"] == "model"
    assert p["model_path"] == entities.SPELLBOOK_MODEL
    assert p["texture"] == "spellbook/cover_green.png"
    assert p["sprite_path"].endswith("spellbook_green.png")
    assert "custom_idle" not in p


def test_the_book_model_and_every_cover_ship():
    assert os.path.exists(os.path.join(ROOT, entities.SPELLBOOK_MODEL))
    for cover in entities.SPELLBOOK_COVERS:
        assert os.path.exists(os.path.join(ROOT, "assets", "textures",
                                           entities.spellbook_texture(cover)))
        assert os.path.exists(os.path.join(ROOT, entities.spellbook_sprite(cover)))


def test_a_map_can_choose_the_sprite_and_keeps_its_own_transform():
    book = entities.Spellbook([0, 0, 0], {"render_mode": "billboard",
                                          "rotation": [0, 45, 0]})
    assert book.properties["render_mode"] == "billboard"
    assert book.properties["rotation"] == [0, 45, 0]


def test_an_unknown_cover_falls_back_to_red():
    book = entities.Spellbook([0, 0, 0], {"cover": "tartan"})
    assert book.properties["texture"] == "spellbook/cover_red.png"


class _Subscriber:
    """A render table stand-in: the journal holds subscribers weakly."""


def test_a_cover_change_is_journalled_for_the_renderer():
    book = entities.Spellbook([0, 0, 0], {"cover": "red"})
    sub = _Subscriber()
    JOURNAL.drain(sub)                       # register; start from nothing
    book.properties["cover"] = "purple"
    assert entities.sync_spellbook_cover(book) is True
    assert id(book) in JOURNAL.drain(sub)
    assert entities.sync_spellbook_cover(book) is False
