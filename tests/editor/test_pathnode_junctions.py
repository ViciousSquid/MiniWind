"""A PathNode's next_node may list several nodes (a road junction)."""

import pytest

pytest.importorskip("PyQt5")

from editor.io_system import validate_all_scene_connections
from editor.things import Thing

pytestmark = pytest.mark.qt


def _node(name, next_node=""):
    return Thing.from_dict({"type": "path_node", "pos": [0, 0, 0],
                            "properties": {"type": "path_node", "name": name,
                                           "next_node": next_node}})


def test_every_name_in_a_junction_is_checked():
    things = [_node("A", "B, C"), _node("B"), _node("C", "A,Ghost"),
              Thing.from_dict({"type": "light", "pos": [0, 0, 0],
                               "properties": {"type": "light", "name": "Lamp"}}),
              _node("D", "Lamp")]
    report = validate_all_scene_connections([], things)
    kinds = sorted((p[1], p[2]) for p in report["problems"])
    assert kinds == [("Ghost", "missing_pathnode_target"),
                     ("Lamp", "invalid_pathnode_target")]
