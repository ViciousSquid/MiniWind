"""Every inventory item has replacement art; the originals remain intact."""
import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "archive/inventory-icons/2026-10-22"


def test_every_item_has_its_own_readable_transparent_icon():
    db = json.loads((ROOT / "game/data/items.json").read_text())
    for iid in db:
        path = ROOT / f"assets/sprites/items/{iid}.png"
        assert path.is_file(), iid
        with Image.open(path) as image:
            assert image.mode == "RGBA", iid
            assert min(image.size) >= 128, iid
            alpha = image.getchannel("A")
            assert alpha.getextrema()[0] == 0 and alpha.getextrema()[1] >= 240, iid
            bbox = alpha.getbbox()
            assert bbox and bbox[0] > 0 and bbox[1] > 0, iid
            assert bbox[2] < image.width and bbox[3] < image.height, iid


def test_original_icons_are_archived_exactly_and_all_live_versions_are_replaced():
    manifest = json.loads((ARCHIVE / "manifest.json").read_text())
    assert len(manifest["files"]) == 108
    for entry in manifest["files"]:
        original = (ARCHIVE / entry["archived_file"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == entry["sha256"]
        assert (ROOT / entry["original_path"]).read_bytes() != original
