"""game/storyteller_normal.ini and storyteller_dynamic.ini: tuning from plain text."""

import copy

import pytest

from ..living import scenarios
from ..sim import storyteller, tuning_ini


@pytest.fixture
def restore_tuning():
    saved = copy.deepcopy(storyteller.TUNING)
    yield
    storyteller.TUNING.clear()
    storyteller.TUNING.update(saved)
    scenarios.retune(copy.deepcopy(scenarios.DEFAULTS))


def test_both_files_live_in_the_game_folder_and_ship_the_values_the_game_already_uses():
    for path in (tuning_ini.NORMAL_PATH, tuning_ini.DYNAMIC_PATH):
        assert path.parent.name == "game" and path.exists()
    assert not (tuning_ini.GAME_DIR / "storyteller.ini").exists()
    problems = []
    with_ini = storyteller.load_tuning(problems=problems)
    assert problems == []
    assert with_ini == storyteller.load_tuning(use_ini=False)   # nothing changes as shipped
    values, problems = tuning_ini.director_values(scenarios.DEFAULTS)
    assert problems == []
    merged = copy.deepcopy(scenarios.DEFAULTS)
    for table, rows in values.items():
        merged[table].update(rows)
    assert merged == scenarios.DEFAULTS


def test_the_shipped_files_are_what_write_default_makes(tmp_path):
    normal, dynamic = tuning_ini.write_default(tmp_path / "n.ini", tmp_path / "d.ini")
    assert normal.read_text(encoding="utf-8") == tuning_ini.NORMAL_PATH.read_text(encoding="utf-8")
    assert dynamic.read_text(encoding="utf-8") == tuning_ini.DYNAMIC_PATH.read_text(encoding="utf-8")


def _ini(tmp_path, text):
    path = tmp_path / "storyteller.ini"
    path.write_text(text, encoding="utf-8")
    return path


def test_edits_reach_the_storyteller(tmp_path):
    path = _ini(tmp_path, """
[storyteller]
healthy = 0.6
enabled = false
[justified journeys]
gratitude = 0
[CALM]
population = 40
max_hours = 12
weight.bandits = 7
weight.trader = 0.5
hours.bandits = 19-4
[RESPITE]
max_hours = none
""")
    tuning = storyteller.load_tuning(use_ini=False)
    problems = tuning_ini.apply_storyteller(tuning, path)
    assert problems == []
    assert tuning["healthy"] == 0.6 and tuning["enabled"] is False
    assert tuning["justified_journeys"]["gratitude"] == 0
    calm = tuning["states"]["CALM"]
    assert calm["levers"]["population"] == 40 and calm["max_hours"] == 12
    assert calm["levers"]["kind_weights"]["bandits"] == 7
    assert calm["levers"]["kind_weights"]["trader"] == 0.5
    assert calm["levers"]["kind_hours"]["bandits"] == [19, 4]
    assert "max_hours" not in tuning["states"]["RESPITE"]


def test_edits_reach_the_dynamic_director(tmp_path, restore_tuning):
    path = _ini(tmp_path, """
[director]
peak = 0.6
build_gap = 20-30
max_scenes = 3
[scene weights]
ambush = 9
[storyteller states]
gap.PEAK = 0.5
hostile.RESPITE = 0
[learning]
step = 0.2
enabled = false
""")
    assert scenarios.load_ini(path) == []
    assert scenarios.PEAK == 0.6 and scenarios.BUILD_GAP == (20.0, 30.0)
    assert scenarios.MAX_SCENES == 3 and scenarios.SCENE_WEIGHTS["ambush"] == 9
    assert scenarios.STATE_GAP["PEAK"] == 0.5 and scenarios.STATE_HOSTILE["RESPITE"] == 0
    assert scenarios.LEARNING["step"] == 0.2 and scenarios.LEARNING["enabled"] is False
    # Reading the shipped file again puts everything back.
    assert scenarios.load_ini() == []
    assert scenarios.tuning() == scenarios.DEFAULTS


def test_bad_values_and_unknown_keys_are_skipped_and_reported(tmp_path):
    path = _ini(tmp_path, """
[storyteller]
healthy = lots
made_up = 3
[CALM]
population = -5
weight.dragons = 2
hours.bandits = 30-4
market_chance = 3
[director]
peak = high
""")
    tuning = storyteller.load_tuning(use_ini=False)
    before = copy.deepcopy(tuning)
    problems = tuning_ini.apply_storyteller(tuning, path)
    text = "\n".join(problems)
    for bit in ("healthy = lots", "made_up", "population = -5", "weight.dragons",
                "hours.bandits", "market_chance"):
        assert bit in text
    assert tuning["healthy"] == before["healthy"]
    assert tuning["states"]["CALM"]["levers"]["population"] == before["states"]["CALM"]["levers"]["population"]
    assert tuning["states"]["CALM"]["levers"]["market_chance"] == 1.0
    values, problems = tuning_ini.director_values(scenarios.DEFAULTS, path)
    assert values["dynamic"] == {} and "peak = high" in problems[0]


def test_a_broken_file_changes_nothing(tmp_path):
    path = _ini(tmp_path, "this is not [an ini\n= file")
    tuning = storyteller.load_tuning(use_ini=False)
    before = copy.deepcopy(tuning)
    problems = tuning_ini.apply_storyteller(tuning, path)
    assert tuning == before and problems


def test_reload_applies_to_the_running_storyteller(tmp_path, monkeypatch, restore_tuning):
    from .test_storyteller import setup
    story, _director, _hooks, _store = setup()
    calm = storyteller.TUNING["states"]["CALM"]["levers"]["population"]
    assert story.levers["population"] == calm
    path = _ini(tmp_path, "[CALM]\npopulation = 33\n")
    monkeypatch.setattr(tuning_ini, "NORMAL_PATH", path)
    assert storyteller.reload_tuning() == []
    story.retune()
    assert story.levers["population"] == 33
    assert story.activity[0]["text"].startswith("Tuning reloaded")


def test_as_shipped_every_setting_is_switched_off_and_deleting_the_semicolon_switches_it_on(tmp_path):
    for path in (tuning_ini.NORMAL_PATH, tuning_ini.DYNAMIC_PATH):
        lines = path.read_text(encoding="utf-8").splitlines()
        settings = [line for line in lines if "=" in line and not line.startswith("#")]
        assert settings and all(line.startswith(";") for line in settings)
    shipped = tuning_ini.NORMAL_PATH.read_text(encoding="utf-8")
    calm = shipped.index("[CALM]")
    edited = shipped[:calm] + shipped[calm:].replace(";population = 26", "population = 40", 1)
    path = _ini(tmp_path, edited)
    tuning = storyteller.load_tuning(use_ini=False)
    assert tuning_ini.apply_storyteller(tuning, path) == []
    expected = storyteller.load_tuning(use_ini=False)
    expected["states"]["CALM"]["levers"]["population"] = 40
    assert tuning == expected                       # that one line, nothing else


def test_mods_and_storyteller_json_still_count_under_the_shipped_file():
    # The shipped file switches nothing on, so the layers below it still apply.
    assert storyteller.load_tuning() == storyteller.load_tuning(use_ini=False)
