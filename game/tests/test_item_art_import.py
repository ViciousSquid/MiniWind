"""Importing realistic artwork preserves every original and checks the batch."""
import hashlib

import pytest
from PIL import Image

from ..tools.import_item_art import archive_existing, import_icons


def _icon(path, size=128, mode="RGBA"):
    im = Image.new(mode, (size, size))
    im.paste((140, 70, 30, 255) if mode == "RGBA" else (140, 70, 30),
             (20, 20, size - 20, size - 20))
    im.save(path)


def test_archive_preserves_exact_originals_and_is_idempotent(tmp_path):
    icons, archive = tmp_path / "icons", tmp_path / "archive"
    icons.mkdir()
    original = b"original item icon bytes"
    (icons / "sword.png").write_bytes(original)
    saved = archive_existing(icons, archive)
    assert (archive / "sword.png").read_bytes() == original
    assert saved["files"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    (icons / "sword.png").write_bytes(b"replacement")
    assert archive_existing(icons, archive) == saved
    assert (archive / "sword.png").read_bytes() == original


def test_import_copies_rendered_images_without_changing_their_bytes(tmp_path):
    source, icons = tmp_path / "source", tmp_path / "icons"
    source.mkdir()
    _icon(source / "iron_sword.png")
    assert import_icons(source, icons, {"iron_sword"}) == ["iron_sword"]
    assert (source / "iron_sword.png").read_bytes() == (icons / "iron_sword.png").read_bytes()


@pytest.mark.parametrize("problem", ["incomplete", "invalid_name", "small", "opaque"])
def test_invalid_batch_does_not_partially_replace_existing_icons(tmp_path, problem):
    source, icons = tmp_path / "source", tmp_path / "icons"
    source.mkdir()
    icons.mkdir()
    (icons / "good.png").write_bytes(b"original")
    _icon(source / "good.png")
    if problem == "invalid_name":
        _icon(source / "bad.name.png")
    elif problem == "small":
        _icon(source / "other.png", size=64)
    elif problem == "opaque":
        _icon(source / "other.png", mode="RGB")
    with pytest.raises(ValueError):
        import_icons(source, icons, {"good", "other"} if problem == "incomplete" else None)
    assert (icons / "good.png").read_bytes() == b"original"
