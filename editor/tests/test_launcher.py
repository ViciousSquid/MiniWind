"""
Tests for the startup launcher (:mod:`editor.launcher`).

Qt-dependent, so the module skips where PyQt5 is not installed and the rest of
the suite stays headless. Where Qt is available these run offscreen and need no
display.

The settings tests all work on a copy of ``settings.ini`` in a tmp dir, so they
prove the round-trip — launcher writes, Settings window reads — without ever
touching the real file.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import configparser
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt5.QtCore")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from editor import launcher as lx   # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def ini(tmp_path):
    """A copy of the project's real settings.ini, so the tests exercise the
    actual file shape rather than an idealised one."""
    path = tmp_path / "settings.ini"
    with open(os.path.join(ROOT, "settings.ini")) as src:
        path.write_text(src.read())
    return str(path)


@pytest.fixture
def ui(app, ini):
    dialog = lx.Launcher(ROOT, ini)
    dialog.show()
    app.processEvents()
    yield dialog
    dialog.close()


def _read(path, section, option):
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg.get(section, option)


# --- settings round-trip ---------------------------------------------------
def test_it_reads_the_display_settings_already_in_the_file(ini):
    cfg = configparser.ConfigParser()
    cfg.read(ini)
    cfg.set("Kiosk", "window_mode", "Windowed")
    cfg.set("Kiosk", "res_width", "1920")
    cfg.set("Kiosk", "res_height", "1080")
    cfg.set("Display", "vsync", "False")
    with open(ini, "w") as f:
        cfg.write(f)

    s = lx.DisplaySettings(ini)
    assert s.mode == "Windowed"
    assert s.resolution == (1920, 1080)
    assert s.vsync is False


def test_an_unrecognised_mode_falls_back_rather_than_breaking(ini):
    cfg = configparser.ConfigParser()
    cfg.read(ini)
    cfg.set("Kiosk", "window_mode", "Hologram")
    with open(ini, "w") as f:
        cfg.write(f)
    assert lx.DisplaySettings(ini).mode == lx.DEFAULTS["window_mode"]


def test_saving_writes_the_same_keys_the_settings_window_uses(ini):
    lx.DisplaySettings(ini).save("Borderless", 2560, 1440, False)
    assert _read(ini, "Kiosk", "window_mode") == "Borderless"
    assert _read(ini, "Kiosk", "res_width") == "2560"
    assert _read(ini, "Display", "vsync") == "False"


def test_saving_leaves_every_other_setting_alone(ini):
    before = _read(ini, "Shortcuts", "key_play_mode")
    lx.DisplaySettings(ini).save("Windowed", 1280, 720, True)
    assert _read(ini, "Shortcuts", "key_play_mode") == before
    assert _read(ini, "Kiosk", "launch_in_editor") == "False"


def test_high_dpi_round_trips_through_the_same_key_the_editor_reads(ini):
    lx.DisplaySettings(ini).save("Fullscreen", 1280, 720, True, high_dpi=True)
    assert _read(ini, "Display", "high_dpi_scaling") == "True"
    assert lx.DisplaySettings(ini).high_dpi is True


def test_reset_restores_the_documented_defaults(ini):
    s = lx.DisplaySettings(ini)
    s.save("Windowed", 3840, 2160, False)
    s.reset()
    assert _read(ini, "Kiosk", "window_mode") == lx.DEFAULTS["window_mode"]
    assert _read(ini, "Kiosk", "res_width") == str(lx.DEFAULTS["res_width"])
    assert _read(ini, "Display", "vsync") == str(lx.DEFAULTS["vsync"])
    assert (_read(ini, "Display", "high_dpi_scaling")
            == str(lx.DEFAULTS["high_dpi_scaling"]))


# --- the launcher itself ---------------------------------------------------
def test_it_opens_showing_what_is_in_the_file(ui, ini):
    assert ui.current_mode() == lx.DisplaySettings(ini).mode
    assert ui.current_resolution() == lx.DisplaySettings(ini).resolution


def test_a_saved_resolution_is_never_silently_reset(app, ini):
    """The launcher must not quietly change a setting just by being opened."""
    lx.DisplaySettings(ini).save("Windowed", 1920, 1080, True)
    dialog = lx.Launcher(ROOT, ini)
    assert dialog.current_resolution() == (1920, 1080)
    assert _read(ini, "Kiosk", "res_width") == "1920"
    dialog.close()


def test_changing_a_control_writes_through_immediately(ui, ini):
    ui.mode_combo.setCurrentIndex(ui.mode_combo.findData("Windowed"))
    assert _read(ini, "Kiosk", "window_mode") == "Windowed"
    ui.vsync_check.setChecked(False)
    assert _read(ini, "Display", "vsync") == "False"


def test_toggling_high_dpi_writes_through_and_warns_it_needs_a_restart(ui, ini):
    """Qt must be told before it starts, so the change cannot apply now."""
    assert not ui.high_dpi_note.isVisible()
    ui.high_dpi_check.setChecked(not ui.high_dpi_check.isChecked())
    assert _read(ini, "Display", "high_dpi_scaling") == str(
        ui.high_dpi_check.isChecked())
    assert ui.high_dpi_note.isVisible()
    ui.high_dpi_check.setChecked(not ui.high_dpi_check.isChecked())
    assert not ui.high_dpi_note.isVisible(), "back to what is running: no warning"


def test_it_shows_the_version_from_the_version_file(ui):
    with open(os.path.join(ROOT, "editor", "version.txt")) as f:
        assert ui.version_label.text() == f.read().strip()


def test_a_missing_version_file_is_not_an_error(tmp_path):
    assert lx.read_version(str(tmp_path)) == ""


def test_it_links_to_the_project(ui):
    assert lx.PROJECT_URL in ui.project_link.text()
    assert ui.project_link.openExternalLinks()


def test_resolution_only_applies_to_a_real_window(ui):
    ui.mode_combo.setCurrentIndex(ui.mode_combo.findData("Windowed"))
    assert ui.res_combo.isEnabled()
    ui.mode_combo.setCurrentIndex(ui.mode_combo.findData("Fullscreen"))
    assert not ui.res_combo.isEnabled(), "a fullscreen size is not a choice"
    ui.mode_combo.setCurrentIndex(ui.mode_combo.findData("Borderless"))
    assert not ui.res_combo.isEnabled()


def test_every_mode_explains_itself(ui):
    for value, _label, _help in lx.MODES:
        ui.mode_combo.setCurrentIndex(ui.mode_combo.findData(value))
        assert ui.mode_help.text().strip()


def test_reset_button_puts_the_controls_back_too(ui, ini):
    ui.mode_combo.setCurrentIndex(ui.mode_combo.findData("Windowed"))
    ui.vsync_check.setChecked(False)
    ui._reset()
    assert ui.current_mode() == lx.DEFAULTS["window_mode"]
    assert ui.vsync_check.isChecked() is lx.DEFAULTS["vsync"]
    assert _read(ini, "Kiosk", "window_mode") == lx.DEFAULTS["window_mode"]


def test_play_and_edit_report_the_choice(app, ini):
    play = lx.Launcher(ROOT, ini)
    play.play_button.click()
    assert play.choice == lx.PLAY

    edit = lx.Launcher(ROOT, ini)
    edit.edit_button.click()
    assert edit.choice == lx.EDIT


def test_escape_and_dismissal_mean_the_editor(ui):
    assert ui.choice == lx.EDIT, "the safe answer before anything is chosen"
    ui.keyPressEvent(_key(QtCore.Qt.Key_Escape))
    assert ui.choice == lx.EDIT


def test_the_ui_says_the_display_settings_are_the_games(ui):
    """Play mode runs in the editor's own window, so the launcher has to be
    explicit that a resolution set here does not resize the editor."""
    assert "PLAY MODE" in ui.section_label.text().upper()
    assert "editor" in ui.scope_note.text().lower()
    for value, _label, help_text in lx.MODES:
        ui.mode_combo.setCurrentIndex(ui.mode_combo.findData(value))
        assert "game" in ui.mode_help.text().lower()


def test_it_writes_no_editor_geometry(ini):
    """The launcher must not touch the editor's remembered window layout."""
    cfg = configparser.ConfigParser()
    cfg.read(ini)
    if not cfg.has_section("Layout"):
        cfg.add_section("Layout")
    cfg.set("Layout", "geometry", "deadbeef")
    with open(ini, "w") as f:
        cfg.write(f)

    lx.DisplaySettings(ini).save("Windowed", 3840, 2160, False, high_dpi=True)
    assert _read(ini, "Layout", "geometry") == "deadbeef"


def test_launch_never_raises(monkeypatch):
    monkeypatch.setattr(lx, "Launcher",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert lx.launch() == lx.EDIT


# --- DPI awareness ---------------------------------------------------------
def test_no_pixel_font_sizes_anywhere():
    """The repo's rule (see editor/logic_wizard.py): text inherits the
    application font so it honours font_size and OS display scaling."""
    with open(os.path.join(ROOT, "editor", "launcher.py")) as f:
        source = f.read()
    assert "font-size:" not in source
    assert "setPixelSize" not in source


def test_everything_scales_with_the_application_font(app, ini):
    """The launcher must grow on a high-DPI display, not stay postage-stamp."""
    base = app.font()

    def _measure(points):
        font = QtGui.QFont(base)
        font.setPointSize(points)
        app.setFont(font)
        dialog = lx.Launcher(ROOT, ini)
        # Measured before the next font change, because a live launcher
        # re-measures itself when the application font moves under it.
        got = (dialog.width(), dialog.banner.height(),
               dialog.play_button.minimumSize().height())
        dialog.close()
        return got

    try:
        small = _measure(9)
        big = _measure(18)
    finally:
        app.setFont(base)
    for a, b in zip(small, big):
        assert b > a * 1.5, f"{b} should be far larger than {a}"


def test_a_live_launcher_follows_a_font_change(app, ini):
    """Changing the font size in Settings must not leave it half-sized."""
    base = app.font()
    dialog = lx.Launcher(ROOT, ini)
    before = (dialog.width(), dialog.banner.height())
    try:
        bigger = QtGui.QFont(base)
        bigger.setPointSize(base.pointSize() * 2)
        app.setFont(bigger)
        assert dialog.width() > before[0]
        assert dialog.banner.height() > before[1]
    finally:
        app.setFont(base)
        dialog.close()


def test_the_banner_falls_back_to_a_placeholder(app, tmp_path):
    """No art yet is not a broken launcher — it says where the art goes."""
    assert lx.Banner._load(str(tmp_path)) is None
    banner = lx.Banner(str(tmp_path))
    assert banner.height() > 0


# -- helpers ---------------------------------------------------------------
QtGui = pytest.importorskip("PyQt5.QtGui")


class _KeyEvent:
    def __init__(self, code):
        self._code = code

    def key(self):
        return self._code


def _key(code):
    return _KeyEvent(code)
