"""Add-ons to the numbered character-head pool."""
from game.rpg import heads


def test_original_head_ids_are_stable():
    assert heads.HEAD_IDS[:162] == [f"head{n:02d}" for n in range(162)]
    assert heads.HEAD_COUNT == len(heads.HEAD_IDS)
    assert heads.HEAD_LAST == int(heads.HEAD_IDS[-1][4:])


def test_additional_numbered_pngs_are_discovered(tmp_path):
    for name in ("head162.png", "head316.png", "head017.png",
                 "headhigher.png", "head317.jpg", "guard27.png"):
        (tmp_path / name).write_bytes(b"names only; no image decoding")
    ids = heads._numbered_head_ids(tmp_path)
    assert len(ids) == 164
    assert ids[:162] == [f"head{n:02d}" for n in range(162)]
    assert ids[162:] == ["head162", "head316"]
    assert ids.count("head17") == 1


def test_missing_directory_keeps_original_pool(tmp_path):
    assert heads._numbered_head_ids(tmp_path / "missing") == [
        f"head{n:02d}" for n in range(162)
    ]
