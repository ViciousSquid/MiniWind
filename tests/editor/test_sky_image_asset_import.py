"""Importing a sky image creates a project-owned portable asset."""

from editor import property_editor


def test_selected_sky_image_is_copied_into_project_backgrounds(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = tmp_path / "outside" / "nebula.webp"
    source.parent.mkdir()
    source.write_bytes(b"panorama data")
    monkeypatch.setattr(property_editor, "_project_root", lambda: str(project))

    relative = property_editor._store_sky_image_in_project(source)

    assert relative == "assets/backgrounds/nebula.webp"
    assert (project / relative).read_bytes() == b"panorama data"


def test_selecting_same_external_sky_image_reuses_existing_copy(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = tmp_path / "outside" / "nebula.webp"
    source.parent.mkdir()
    source.write_bytes(b"same panorama")
    backgrounds = project / "assets" / "backgrounds"
    backgrounds.mkdir(parents=True)
    (backgrounds / source.name).write_bytes(b"same panorama")
    monkeypatch.setattr(property_editor, "_project_root", lambda: str(project))

    relative = property_editor._store_sky_image_in_project(source)

    assert relative == "assets/backgrounds/nebula.webp"
    assert sorted(path.name for path in backgrounds.iterdir()) == ["nebula.webp"]
