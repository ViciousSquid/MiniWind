"""
Gib splatter selection — which stain a gibbed actor becomes.

A gibbed actor (an overkill death, see :mod:`engine.gore`) is replaced by a
splatter sprite. Two kinds:

* **Physical** gibs (melee, arrows) leave a **blood stain** from
  ``assets/sprites/miniwind/blood_stains/``.
* **Magical** gibs *disintegrate* the target, leaving a special splatter from
  ``assets/sprites/miniwind/disintegrate/``.

Both folders are author-editable: drop image files in, and the files sorted by
name are treated as **mild → severe**. The stain is chosen by how far the
killing blow overshot the victim's max health, so a hit barely over the gib
threshold leaves the mildest splatter and a massive overkill the severest. Any
number of files works (the severity maps across however many are present); the
folders ship with placeholder art that can be replaced wholesale.

Qt-free and dependency-free so the headless runtime and tests can use it.
"""

from __future__ import annotations

import os
from typing import List, Optional

#: Folders (relative to the project root) holding the two splatter sets.
PHYSICAL_DIR_REL = "assets/sprites/miniwind/blood_stains"
MAGICAL_DIR_REL = "assets/sprites/miniwind/disintegrate"

_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

#: Overkill ratio (damage / max_health) at/above which the severest splatter is
#: used; the gib threshold itself (engine.gore.GIB_DAMAGE_FRACTION) is the mild
#: end. Everything between maps linearly across the available files.
SEVERE_RATIO = 3.0

try:  # keep the mild end in step with the gib rule
    from engine.gore import GIB_DAMAGE_FRACTION as _MILD_RATIO
except Exception:  # pragma: no cover
    _MILD_RATIO = 1.2


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def _dir_rel(magical: bool) -> str:
    return MAGICAL_DIR_REL if magical else PHYSICAL_DIR_REL


def stain_paths(magical: bool = False, root: Optional[str] = None) -> List[str]:
    """Splatter sprite paths for a gib kind, sorted by filename (mild → severe).

    Only regular image files are listed (any sub-folders are ignored), so a
    physical folder that contains the magical sub-folder is unaffected.
    """
    rel = _dir_rel(magical)
    directory = os.path.join(root or _project_root(), *rel.split("/"))
    try:
        names = sorted(n for n in os.listdir(directory)
                       if n.lower().endswith(_IMG_EXTS)
                       and os.path.isfile(os.path.join(directory, n)))
    except OSError:
        return []
    return [f"{rel}/{n}" for n in names]


def severity_fraction(damage, max_health) -> float:
    """0.0 (mildest) .. 1.0 (severest) from how far the blow overshot max health."""
    try:
        dmg = float(damage)
        mh = max(1.0, float(max_health))
    except (TypeError, ValueError):
        return 0.0
    ratio = dmg / mh
    if ratio <= _MILD_RATIO:
        return 0.0
    if ratio >= SEVERE_RATIO:
        return 1.0
    return (ratio - _MILD_RATIO) / (SEVERE_RATIO - _MILD_RATIO)


def stain_for(damage, max_health, magical: bool = False, root: Optional[str] = None) -> str:
    """The splatter sprite path for a gib, chosen by kind and overkill severity.

    Returns ``""`` when the relevant folder has no images (the caller then just
    leaves the actor flagged gibbed with no special sprite)."""
    paths = stain_paths(magical, root)
    if not paths:
        return ""
    frac = severity_fraction(damage, max_health)
    idx = int(round(frac * (len(paths) - 1)))
    idx = max(0, min(len(paths) - 1, idx))
    return paths[idx]
