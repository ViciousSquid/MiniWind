"""Import rendered inventory icons without losing the previous artwork.

Run ``python -m game.tools.import_item_art /path/to/rendered/icons``.
All sources are validated before replacement. An archive manifest records the
exact previous file bytes and original paths. Images are copied unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = ROOT / "assets/sprites/items"
ARCHIVE = ROOT / "archive/inventory-icons/2026-10-22"


def archive_existing(icon_dir=ICON_DIR, archive=ARCHIVE):
    archive.mkdir(parents=True, exist_ok=True)
    manifest_path = archive / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = []
    for source in sorted(icon_dir.glob("*.png")):
        destination = archive / source.name
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Refusing to overwrite a different archived icon: {destination.name}")
        shutil.copy2(source, destination)
        entries.append({"original_path": f"assets/sprites/items/{source.name}",
                        "archived_file": source.name, "sha256": digest})
    result = {"version": 1, "description": "Original inventory icons before realistic artwork replacement",
              "files": entries}
    manifest_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def import_icons(source_dir, icon_dir=ICON_DIR, expected_ids=None):
    """Validate the complete batch before atomically replacing each PNG."""
    files = sorted(Path(source_dir).glob("*.png"))
    ids = {source.stem for source in files}
    if not files or (expected_ids is not None and ids != set(expected_ids)):
        raise ValueError("The rendered batch does not contain every expected item")
    for source in files:
        iid = source.stem
        if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in iid):
            raise ValueError(f"Invalid item id: {iid!r}")
        with Image.open(source) as image:
            image.load()
            if image.mode != "RGBA" or min(image.size) < 128:
                raise ValueError(f"Expected a transparent high-resolution PNG: {iid}")
            low, high = image.getchannel("A").getextrema()
            if high < 64 or low > 32:
                raise ValueError(f"Missing item or transparent background: {iid}")
    icon_dir.mkdir(parents=True, exist_ok=True)
    for source in files:
        destination = icon_dir / source.name
        temporary = destination.with_suffix(".png.tmp")
        shutil.copyfile(source, temporary)
        temporary.chmod(0o644)
        temporary.replace(destination)
    return sorted(ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    db = json.loads((ROOT / "game/data/items.json").read_text(encoding="utf-8"))
    expected = set(db) | {"arrow", "_ammo", "_armor", "_armour", "_book", "_gold",
                          "_ingredient", "_misc", "_potion", "_weapon"}
    archived = archive_existing()
    imported = import_icons(args.source, expected_ids=expected)
    print(f"Archived {len(archived['files'])} originals; imported {len(imported)} realistic icons")


if __name__ == "__main__":
    main()
