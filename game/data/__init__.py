"""
MiniWind game **content** — human-editable data, kept out of the game *rules*.

This package is the moddable data boundary (task §20). Game *rules* — combat
maths, stat derivation, the schedule planner, the autonomy state machine — stay
in code under :mod:`game.rpg`. Game *content* — which creatures exist, what
items are worth, how factions feel about each other, what an NPC's day looks
like, and how the starter settlement is laid out — lives here as plain JSON:

    game/data/
        bestiary.json     creature & NPC role templates
        factions.json     cross-faction relationships
        schedules.json    per-role daily schedules
        items.json        the item database
        settlement.json   the starter living settlement (markers + NPCs)

Every file is human-readable, diffable and version-controllable. To extend the
world a community member edits a file here, or ships a **mod**: a folder under
``game/data/mods/<modname>/`` containing files of the same names. A mod's
entries are merged over the base content (a dict updates/adds entries by id; a
list is appended), so a mod can add a new creature, retune an item, or drop in a
whole second village without touching a line of Python.

The loader is deliberately tiny — this is a clean boundary, not a modding SDK.
A malformed mod file is skipped with a warning rather than crashing the game.
"""

from __future__ import annotations

import json
import os
from typing import Any

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_MODS_DIR = os.path.join(_DATA_DIR, "mods")


def data_dir() -> str:
    """Absolute path to the base content directory."""
    return _DATA_DIR


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _merge(base: Any, overlay: Any) -> Any:
    """Merge *overlay* onto *base*: dicts update by key, lists concatenate."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, value in overlay.items():
            out[key] = _merge(out[key], value) if key in out else value
        return out
    if isinstance(base, list) and isinstance(overlay, list):
        return base + overlay
    return overlay


def _mod_files(name: str):
    """Yield every ``mods/*/<name>.json`` path, in stable mod-name order."""
    if not os.path.isdir(_MODS_DIR):
        return
    for mod in sorted(os.listdir(_MODS_DIR)):
        path = os.path.join(_MODS_DIR, mod, f"{name}.json")
        if os.path.isfile(path):
            yield mod, path


def load(name: str, default: Any = None) -> Any:
    """Load content file ``<name>.json``, merged with any mod overlays.

    Returns the merged content (usually a dict keyed by id). If the base file is
    absent, mod content (if any) is returned alone, else *default* (or ``{}``).
    Mod files that fail to parse are skipped with a printed warning.
    """
    base_path = os.path.join(_DATA_DIR, f"{name}.json")
    content: Any = default if default is not None else {}
    if os.path.isfile(base_path):
        content = _read_json(base_path)
    for mod, path in _mod_files(name):
        try:
            content = _merge(content, _read_json(path))
        except Exception as exc:  # pragma: no cover - defensive against bad mods
            print(f"[MiniWind] skipping malformed mod data '{mod}/{name}.json': {exc}")
    return content
