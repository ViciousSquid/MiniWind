"""
Fill the expanded world's open land with places to find.

``expand_world`` made the Vale huge but left most of it empty: thirty places
in an 82 000-unit square. This adds about thirty more, spread over the open
lowland between them, each a reason to leave the road:

* **hamlets** -- a handful of cottages round a well, a market stall, a few
  folk who live and work there, sheep and hens;
* **farmsteads** -- a farmhouse and barn, a fenced paddock of cows or sheep,
  a farmer and a farmhand;
* **a wayside inn** -- an innkeeper who sells food and drink;
* **ruins and barrows** -- broken walls, the dead that guard them, a chest;
* **lairs** -- greenskin warrens, spider nests, a shroomling dell, brigand
  camps, each with its spoils;
* **shrines** -- standing stones and a lit altar.

Buildings are the map's own top-down house art on flat-topped brushes, each
seated on ground levelled under it (a sculpt, feathered into the
surroundings). People and creatures are copies of the map's own (a farmhand,
a merchant, a sheep, a skeleton), renamed, re-homed and given new ids. Every
place has a location marker, so it is named on discovery and on the map.

Run once on an expanded map (it refuses to run twice):

    python -m game.tools.populate_world [MAP] [--preview out.png]
"""

from __future__ import annotations

import argparse
import copy
import glob
import math
import os

import numpy as np

from .expand_world import (MAP, Expander, _heights, _load_heightmap, _props,
                           _smoothstep, _terrain, _uid, dump, preview)

#: (place name, kind), nearest first. Placed on open lowland, apart from
#: everything already there and from each other.
SITES = (
    ("Ashby", "hamlet"), ("Hayward's Farm", "farm"), ("The Wanderer's Rest", "inn"),
    ("Cairnmoor Barrow", "barrow"), ("Thornfield", "hamlet"), ("Coldharbour Farm", "farm"),
    ("Rotfang Warren", "greenskins"), ("Shrine of the Wayfarer", "shrine"),
    ("Kettlewick", "hamlet"), ("Silkhollow", "spiders"), ("Pennick Farm", "farm"),
    ("The Drowned Chapel", "ruin"), ("Cutthroat Ridge", "brigands"),
    ("Brackenford", "hamlet"), ("Mushroom Dell", "shrooms"), ("Marlow Steading", "farm"),
    ("Saint Aldric's Ruin", "ruin"), ("Moonwell", "shrine"), ("Elderbrook", "hamlet"),
    ("Snaggletooth Camp", "greenskins"), ("Gallows Crypt", "barrow"),
    ("Furrow End", "farm"), ("Raven's Roost", "brigands"), ("Wyndham Cross", "hamlet"),
    ("Webfall Hollow", "spiders"), ("The Pilgrim's Lantern", "inn"),
    ("Old Hob's Ruin", "ruin"), ("Greenmantle Shrine", "shrine"),
)

#: How far from the centre each kind may be: homes nearer, danger further.
REACH = {"hamlet": (5000, 26000), "farm": (4500, 24000), "inn": (6000, 22000),
         "shrine": (7000, 32000)}
DANGER_REACH = (9000, 33000)

#: Names for the folk who live in the new places.
FOLK = ("Aldous", "Berta", "Cedric", "Dorcas", "Edwin", "Freya", "Godric", "Hilda",
        "Ivo", "Joan", "Kenric", "Leofa", "Maud", "Nell", "Osric", "Prue", "Quill",
