"""Player-facing typography uses the bundled reading face; debug stays sans."""

import pytest

pytest.importorskip("PyQt5")
from PyQt5.QtGui import QFontInfo

from ..ui import fonts, theme

pytestmark = pytest.mark.qt


def test_game_text_resolves_to_medievalsharp_from_any_working_directory(
        qt_app, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fonts, "_families", None)
    samples = [fonts.dialogue_font(12), fonts.dialogue_font_px(15),
               theme.font(12), theme.fancy_font(18)]
    samples.extend(theme.font(12, family=family)
                   for family in ("Georgia", "Arial", "Segoe UI", "sans-serif"))
    assert all(QFontInfo(font).family() == "MedievalSharp" for font in samples)


def test_game_windows_use_medieval_text_and_inspector_remains_sans(qt_app):
    from .test_inventory_window import _session
    from ..ui.inventory_window import InventoryWindow
    from ..ui.loadout_window import LoadoutWindow
    from ..ui.inventory_strip import InventoryStrip
    from ..ui.inspector import ui_font

    session = _session("iron_longsword")
    inventory = InventoryWindow(session)
    loadout = LoadoutWindow(session)
    strip = InventoryStrip(session)
    samples = [inventory.f_body, inventory.f_small, inventory.f_count,
               inventory.f_title, inventory.f_name, inventory.f_button,
               inventory.title_font, loadout.body_font, loadout.small_font,
               loadout.title_font, strip.f_count, strip.f_name, strip.f_number]
    assert all(QFontInfo(font).family() == "MedievalSharp" for font in samples)
    assert QFontInfo(ui_font(11)).family() != "MedievalSharp"
