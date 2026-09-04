"""
External, human-readable quest storage — the ``quests/`` folder of ``.quest`` files.

A quest is authored content, not per-map state, so it lives in its own file
rather than baked into the map's ``GameSettings`` entity. Each quest is one
``<id>.quest`` file under a top-level ``quests/`` folder, written as pretty,
readable JSON (the same shape :func:`game.rpg.quests.quest_from_dict` already
understands), so a designer can open, diff, hand-edit or version-control quests
directly, and the editor and the running game read the exact same files.

This module is deliberately Qt-free and dependency-free so the headless player
loads quests through it just as the editor saves them through it.

File shape (``quests/lost_amulet.quest``)::

    {
      "id": "lost_amulet",
      "name": "The Lost Amulet",
      "giver": "Elowen",
      "faction": "town",
      "desc": "Elowen lost her grandmother's amulet somewhere in the woods.",
      "xp": 15,
      "rewards": {"gold": 40, "items": [["potion_heal", 2]], "rep": ["town", 5]},
      "stages": [
        {"index": 0, "journal": "...", "objective": "Find the silver amulet",
         "finishes": false, "condition": {"kind": "fetch", "target": "silver_amulet", "count": 1}},
        {"index": 10, "journal": "...", "finishes": true,
         "condition": {"kind": "talk", "target": "Elowen", "count": 1}}
      ]
    }
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

#: Name of the folder (relative to the project root) that holds ``.quest`` files.
QUESTS_DIRNAME = "quests"
#: File extension for a single quest definition.
QUEST_EXT = ".quest"


def project_root() -> str:
    """Absolute path of the repository root (…/MiniWind).

    Resolved from this file's location (``<root>/game/rpg/quest_files.py``) so it
    is correct no matter what the current working directory is when the editor or
    the player runs.
    """
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def quests_dir(root: Optional[str] = None) -> str:
    """Absolute path of the ``quests/`` folder (not guaranteed to exist yet)."""
    return os.path.join(root or project_root(), QUESTS_DIRNAME)


def ensure_dir(root: Optional[str] = None) -> str:
    """Create the ``quests/`` folder if needed and return its path."""
    path = quests_dir(root)
    os.makedirs(path, exist_ok=True)
    return path


def _slug(text: str) -> str:
    """A safe file stem from a quest id (letters/digits/_/-, lower-cased)."""
    out = []
    for ch in str(text).strip().lower():
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        elif ch in " .":
            out.append("_")
    stem = "".join(out).strip("_")
    return stem or "quest"


def quest_path(qid: str, root: Optional[str] = None) -> str:
    """Absolute path of the file a quest with id *qid* is stored in."""
    return os.path.join(quests_dir(root), _slug(qid) + QUEST_EXT)


def list_quest_files(root: Optional[str] = None) -> List[str]:
    """Absolute paths of every ``*.quest`` file, sorted for a stable order."""
    directory = quests_dir(root)
    if not os.path.isdir(directory):
        return []
    files = [os.path.join(directory, n) for n in os.listdir(directory)
             if n.lower().endswith(QUEST_EXT)]
    return sorted(files)


def load_quest_defs(root: Optional[str] = None) -> List[Dict]:
    """Read every ``.quest`` file into a list of plain quest dicts.

    Files that are missing an ``id`` or are not valid JSON are skipped rather
    than raising, so one bad file can never stop the rest (or a play session)
    from loading. The list is ordered by filename for determinism.
    """
    out: List[Dict] = []
    for path in list_quest_files(root):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("id"):
            out.append(data)
    return out


def save_quest_def(quest: Dict, root: Optional[str] = None) -> Optional[str]:
    """Write one quest dict to ``quests/<id>.quest`` (pretty JSON). Returns the
    path written, or ``None`` if the quest has no id."""
    qid = str((quest or {}).get("id", "")).strip()
    if not qid:
        return None
    ensure_dir(root)
    path = quest_path(qid, root)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(quest, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def delete_quest_file(qid: str, root: Optional[str] = None) -> bool:
    """Remove ``quests/<id>.quest`` if present. Returns whether a file was removed."""
    path = quest_path(qid, root)
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def sync_quest_files(quests: List[Dict], root: Optional[str] = None) -> List[str]:
    """Make the ``quests/`` folder match *quests* exactly.

    Writes every quest to its ``<id>.quest`` file and deletes any existing
    ``.quest`` file whose id is no longer present, so editing quests in the
    editor (adding, renaming, removing) leaves a clean folder. Returns the list
    of quest ids written.
    """
    quests = [q for q in (quests or []) if isinstance(q, dict) and q.get("id")]
    wanted = {_slug(q["id"]) for q in quests}
    # Remove files for quests that no longer exist.
    for path in list_quest_files(root):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem not in wanted:
            try:
                os.remove(path)
            except OSError:
                pass
    written = []
    for q in quests:
        if save_quest_def(q, root):
            written.append(str(q["id"]))
    return written
