"""
External MiniWind cutscene storage.

Cutscenes are authored as standalone, human-readable JSON files in the
top-level ``cutscenes/`` folder. Maps contain only a cutscene trigger/reference
entity, so the cinematic can be versioned, diffed and edited independently of
the map.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

CUTSCENES_DIRNAME = "cutscenes"
CUTSCENE_EXT = ".json"

def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def cutscenes_dir(root: Optional[str] = None) -> str:
    return os.path.join(root or project_root(), CUTSCENES_DIRNAME)

def ensure_dir(root: Optional[str] = None) -> str:
    directory = cutscenes_dir(root)
    os.makedirs(directory, exist_ok=True)
    return directory

def slug(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "_", value).strip("_")
    return value or "cutscene"

def cutscene_path(filename: str, root: Optional[str] = None) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    if not name:
        name = "cutscene.json"
    if not name.lower().endswith(CUTSCENE_EXT):
        name += CUTSCENE_EXT
    return os.path.join(cutscenes_dir(root), name)

def list_cutscene_files(root: Optional[str] = None) -> List[str]:
    directory = cutscenes_dir(root)
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.lower().endswith(CUTSCENE_EXT)
        and os.path.isfile(os.path.join(directory, name))
    )

def load_cutscene(filename: str, root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = cutscene_path(filename, root)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None

def save_cutscene(data: Dict[str, Any], filename: str, root: Optional[str] = None) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    ensure_dir(root)
    name = os.path.basename(str(filename or "").strip())
    if not name:
        name = slug(data.get("name", "cutscene"))
    if not name.lower().endswith(CUTSCENE_EXT):
        name += CUTSCENE_EXT
    path = cutscene_path(name, root)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path