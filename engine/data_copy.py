"""A fast deep copy for map data: the JSON shapes levels are made of.

Level records (brushes, things, their properties, terrain data) are plain
``dict`` / ``list`` trees of strings, numbers, booleans and ``None``.
:func:`copy.deepcopy` handles any object graph, so it pays for a memo table,
a dispatch per value and reduce-protocol fallbacks on every node; for these
trees that is most of its cost. :func:`data_copy` walks only ``dict`` and
``list`` and returns immutable leaves as they are, which is about twice as
fast on the shipped world map.

Anything else in the tree (a tuple, a set, an object) is handed to
:func:`copy.deepcopy`, so the result is always a fully independent copy.
The one difference from ``deepcopy`` is aliasing: a list or dict that
appears twice inside the value is copied twice rather than once. Map data
never relies on two of its own entries being the same object.
"""

from __future__ import annotations

import copy

_ATOMIC = frozenset((str, int, float, bool, type(None), bytes, complex))


def data_copy(value):
    """An independent copy of *value*, a tree of dicts and lists."""
    cls = value.__class__
    if cls is dict:
        return {key: (item if item.__class__ in _ATOMIC else data_copy(item))
                for key, item in value.items()}
    if cls is list:
        return [item if item.__class__ in _ATOMIC else data_copy(item)
                for item in value]
    if cls in _ATOMIC:
        return value
    return copy.deepcopy(value)
