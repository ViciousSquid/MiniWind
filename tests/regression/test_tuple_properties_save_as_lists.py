"""A tuple in an entity's properties is saved as a JSON list, not as its
string form.

``Thing.to_dict`` kept JSON-native values and ``str()``-ed everything else
(meant for QColor). A tuple is not on that list, so ``(x, z)`` was saved as
the string ``"(x, z)"``; a game that read it back after loading a save got a
string where it had stored two numbers (MiniWind's roaming wildlife then
failed every tick).
"""

import json

import pytest

pytestmark = pytest.mark.qt


def test_a_tuple_property_round_trips_as_numbers():
    from editor.things import Thing
    thing = Thing(pos=[0.0, 0.0, 0.0], properties={"name": "t", "dest": (12.5, -3.0),
                                                     "_roam_dest": (1.0, 2.0)})
    props = json.loads(json.dumps(thing.to_dict()))["properties"]
    assert props["dest"] == [12.5, -3.0]
    assert props["_roam_dest"] == [1.0, 2.0]
