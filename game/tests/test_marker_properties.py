"""The editor's Properties tab shows the fields the game registers for its
entities -- a Marker's kind, place name and discover radius among them --
even for classes that list no EDITOR_PRIMARY_PROPERTIES (they used to show
a blank tab)."""

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")
pytestmark = pytest.mark.qt


class _Editor(SimpleNamespace):
    """The editor's attributes the panel reads; any hook it calls is a no-op."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Editor()

    def __call__(self, *args, **kwargs):
        return None


def _panel(thing):
    import configparser
    import game
    from PyQt5.QtWidgets import QComboBox, QLabel
    from editor.property_editor import PropertyEditor
    game.install()
    state = _Editor(brushes=[], things=[thing], selected_object=None, selected_objects=[],
                    undo_stack=[])
    editor = _Editor(state=state, config=configparser.ConfigParser(), view_3d=_Editor(),
                     view_2d=_Editor())
    pe = PropertyEditor(editor)
    pe.set_object(thing)
    labels = [w.text() for w in pe.findChildren(QLabel)]
    return pe, labels, pe.findChildren(QComboBox)


def test_a_marker_shows_its_kind_place_name_and_discover_radius(qt_app):
    from game.entities import Marker
    m = Marker(pos=[0, 0, 0], properties={"name": "loc_Ashby", "marker_kind": "location",
                                         "place_name": "Ashby"})
    _pe, labels, combos = _panel(m)
    for label in ("Marker kind:", "Place name:", "Discover radius:", "Hidden during play:"):
        assert label in labels
    kind = next(c for c in combos if c.currentText() == "Location (discovery)")
    items = [kind.itemText(i) for i in range(kind.count())]
    assert {"Home", "Work", "Jail", "Location (discovery)"} <= set(items)
    kind.setCurrentIndex(items.index("Jail"))
    assert m.properties["marker_kind"] == "prison"            # shown Jail, stored prison
    kind.setCurrentIndex(items.index("Home"))
    assert m.properties["marker_kind"] == "home"


@pytest.mark.parametrize("cls, label", [("ItemPickup", "Item:"), ("CreatureSpawn", "Count:"),
                                        ("MiniwindTrigger", "Trigger radius:"),
                                        ("Container", "Use radius:")])
def test_the_other_blank_tabs_show_their_fields_too(qt_app, cls, label):
    import game.entities as E
    _pe, labels, _combos = _panel(getattr(E, cls)(pos=[0, 0, 0], properties={}))
    assert label in labels
