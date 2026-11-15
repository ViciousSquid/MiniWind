"""Portable asset discovery for map-authored image dependencies."""

from engine.package_assets import map_assets


def test_map_assets_collects_player_start_sky_image():
    level = {
        "things": [{
            "type": "player_start",
            "properties": {"sky_image": "assets/backgrounds/space.webp"},
        }]
    }

    assert map_assets(level) == {"assets/backgrounds/space.webp"}


def test_map_assets_collects_legacy_game_settings_void_background():
    level = {
        "things": [{
            "type": "miniwind_settings",
            "properties": {"void_background": "assets/backgrounds/old-sky.jpg"},
        }]
    }

    assert map_assets(level) == {"assets/backgrounds/old-sky.jpg"}
