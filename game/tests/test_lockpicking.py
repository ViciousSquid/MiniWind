"""Authored locks, mouse-lifted tumblers, visible breakage, and ownership."""

import copy
import random
from types import SimpleNamespace

import pytest

from ..rpg import inventory as inv, items
from ..rpg.lockpicking import Lockpick
from ..sim import ownership
from .test_corpse_loot import _Thing, _session


def _locked(picks=3, **props):
    chest = _Thing("Ironbound chest", (40, 0, 0), type="container", locked=True,
                   inventory=[items.make("potion_heal_minor", 2)], **props)
    session = _session(chest)
    session.game.character.inventory = [items.make("lockpick", picks)] if picks else []
    return session, chest


def _set_current(session):
    session.lockpick_action("lift")
    session.tick_lockpicking(session.lockpicking.pins[session.lockpicking.selected].rise + 1e-5)
    session.lockpick_action("set")


@pytest.mark.parametrize("level,count", [(0, 1), (20, 1), (25, 2), (60, 3), (80, 4), (200, 5)])
def test_difficulty_controls_the_number_of_tumblers(level, count):
    attempt = Lockpick(level, 20, random.Random(3))
    assert len(attempt.pins) == count


def test_top_contact_is_the_setting_window_and_a_missed_pin_falls():
    attempt = Lockpick(20, 0, random.Random(3))
    assert attempt.lift()
    pin = attempt.pins[0]
    assert attempt.update(pin.rise / 2) == 0
    assert 0 < pin.height < 1 and not attempt.can_set
    assert attempt.update(pin.rise / 2 + 1e-5) == 1
    assert pin.height == 1 and attempt.can_set
    assert "Click" in attempt.message
    assert attempt.update(pin.hold + 1e-4) == 0
    assert pin.phase == "fall" and not attempt.can_set
    attempt.update(1)
    assert pin.phase == "rest" and not attempt.broken
    assert attempt.set_pin() == "broken"  # missing alone never breaks a pick


def test_security_and_a_slow_stroke_give_a_longer_contact_pause():
    novice = Lockpick(80, 0, random.Random(3))
    skilled = Lockpick(80, 70, random.Random(3))
    novice.lift()
    skilled.lift()
    assert skilled.pins[0].hold > novice.pins[0].hold
    quick_hold = novice.pins[0].hold
    for _ in range(2):
        novice.update(2)
        novice.lift()
    assert novice.pins[0].hold > quick_hold


@pytest.mark.parametrize("security,retained", [(0, 0), (30, 1), (60, 2), (80, 3)])
def test_skill_protects_set_tumblers_when_a_pick_snaps(security, retained):
    attempt = Lockpick(80, security, random.Random(3))
    for i in range(3):
        attempt.select(i)
        attempt.lift()
        attempt.update(attempt.pins[i].rise + 1e-5)
        assert attempt.set_pin() == "set"
    attempt.select(3)
    assert attempt.set_pin() == "broken"
    assert sum(p.latched for p in attempt.pins) == retained


def test_break_animation_prevents_repeat_breaks_and_requires_a_fresh_lift():
    attempt = Lockpick(20, 0, random.Random(3))
    assert attempt.set_pin() == "broken"
    assert attempt.breaking
    assert attempt.set_pin() is None and not attempt.lift()
    attempt.update(attempt.BREAK_DURATION + 1)
    assert attempt.broken and not attempt.breaking
    assert attempt.set_pin() is None
    assert attempt.lift() and not attempt.broken


@pytest.mark.parametrize("seed", [1, 5, 22])
def test_breaks_vary_the_style_and_flight_without_consecutive_repeats(seed):
    attempt = Lockpick(20, 0, random.Random(seed))
    styles, flights = [], []
    for _ in range(24):
        assert attempt.set_pin() == "broken"
        styles.append(attempt.break_style)
        flights.append(tuple(attempt.break_motion.values()))
        attempt.update(attempt.BREAK_DURATION)
        attempt.lift()
        attempt.update(2)  # let this pin drop, then deliberately miss again
    assert set(styles) == set(Lockpick.BREAK_STYLES)
    assert all(a != b for a, b in zip(styles, styles[1:]))
    assert len(set(flights)) == len(flights)


def test_break_style_history_carries_between_closed_lockpick_windows():
    session, chest = _locked(picks=12)
    previous = None
    for _ in range(12):
        session.open_container(chest)
        session.lockpick_action("set")
        assert session.lockpicking.break_style != previous
        previous = session.lockpicking.break_style
        session.cancel_lockpicking()
    assert session.lockpick_count() == 0 and chest.properties["locked"]


def test_locked_contents_cannot_be_taken_or_stored_without_unlocking():
    session, chest = _locked(picks=0)
    assert not session.open_container(chest)
    assert session.open_screen is None
    session.container_thing = chest  # a stale/direct loot call cannot bypass the lock
    assert not session.container_inventory()
    assert not session.take_from_container(0)
    assert not session.store_in_container(0)
    assert chest.properties["inventory"]


def test_a_key_opens_a_key_only_lock_without_being_consumed():
    session, chest = _locked(picks=0, pickable=False, key_id="iron_shortsword")
    assert not session.open_container(chest)
    inv.add_item(session.game.character.inventory, items.make("iron_shortsword"))
    assert session.open_container(chest)
    assert session.open_screen == "container" and not chest.properties["locked"]
    assert inv.has_item(session.game.character.inventory, "iron_shortsword")
    assert session.lockpicking is None


def test_key_cannot_unlock_a_container_out_of_reach():
    session, chest = _locked(key_id="lockpick")
    chest.pos = [400, 0, 0]
    assert not session.open_container(chest)
    assert chest.properties["locked"]


def test_a_complete_mouse_timing_attempt_unlocks_and_trains_security_once():
    session, chest = _locked(lock_difficulty=40)
    xp = dict(session.game.character._skill_xp)
    assert session.open_container(chest)
    assert session.open_screen == "lockpick" and session.container_thing is None
    _set_current(session)
    assert session.open_screen == "lockpick" and chest.properties["locked"]
    session.lockpick_action("select", 1)
    _set_current(session)
    assert session.open_screen == "container" and not chest.properties["locked"]
    assert session.container_inventory() == chest.properties["inventory"]
    assert session.lockpick_count() == 3 and session.lockpicking is None
    assert session.game.character._skill_xp != xp
    trained = dict(session.game.character._skill_xp)
    session.open_container(chest)
    session.lockpick_action("set")
    assert session.game.character._skill_xp == trained


def test_last_pick_break_stays_visible_until_the_player_leaves(monkeypatch):
    session, chest = _locked(picks=1)
    sounds = []
    monkeypatch.setattr(session, "play_ui_sound", lambda name, volume=1: sounds.append(name))
    session.open_container(chest)
    session.lockpick_action("set")
    attempt = session.lockpicking
    assert attempt.breaking and session.lockpick_count() == 0
    assert "Last lockpick broken" in attempt.message
    assert "lock_break.wav" in sounds
    for _ in range(3):
        session.tick_lockpicking(1)
        session.lockpick_action("set")
    assert session.open_screen == "lockpick" and session.lockpicking is attempt
    assert chest.properties["locked"]
    assert not attempt.breaking and attempt.broken
    session.cancel_lockpicking()
    assert session.open_screen is None


@pytest.mark.parametrize("invalidate", ["distance", "removed", "death"])
def test_invalid_target_or_dead_player_cancels_without_spending_a_pick(invalidate):
    session, chest = _locked()
    session.open_container(chest)
    if invalidate == "distance":
        chest.pos = [1000, 0, 0]
    elif invalidate == "removed":
        session.logic.things.remove(chest)
    else:
        session.game.character.health = 0
    session.tick_lockpicking(0.1)
    assert session.lockpicking is None and session.open_screen is None
    assert session.lockpick_count() == 3 and chest.properties["locked"]


def test_unlocking_and_looking_are_free_but_taking_owned_contents_is_theft():
    from .test_law import _scene
    chest = _Thing("Wick's chest", (40, 0, 0), type="container", locked=True,
                   lock_difficulty=20, owner="wick",
                   inventory=[items.make("potion_heal_minor", 2)])
    session, witness, guard = _scene(chest)
    guard.pos = [200, 0, 0]
    inv.add_item(session.game.character.inventory, items.make("lockpick", 2))
    session.open_container(chest)
    _set_current(session)
    assert not session.director.bus.history
    assert session.law.total == 0
    session.container_inventory()
    assert not session.director.bus.history
    value = chest.properties["inventory"][0]["value"] * 2
    assert session.take_from_container(0)
    assert session.director.bus.history[-1].kind == "theft"
    assert session.director.bus.history[-1].data["value"] == value
    assert any(ownership.is_stolen(s) for s in session.game.character.inventory)
    assert any(n["text"] == "Someone witnessed your crime." for n in session.notifications)
    session.director.resolve_reports(session._sim_actors())
    assert session.law.total == 25 + value


@pytest.mark.parametrize("owner", [None, "None", " none ", "(None)", "player"])
def test_none_and_player_owned_contents_are_free_to_take_even_in_front_of_a_guard(owner):
    from .test_law import _scene
    chest = _Thing("Supply chest", (40, 0, 0), type="container", owner=owner,
                   owner_faction="guards", inventory=[items.make("potion_heal_minor")])
    session, witness, guard = _scene(chest)
    guard.pos = [100, 0, 0]
    session.open_container(chest)
    assert session.take_from_container(0)
    assert session.director.bus.history[-1].kind == "pickup"
    session.director.resolve_reports(session._sim_actors())
    assert session.law.total == 0
    assert not any(ownership.is_stolen(s) for s in session.game.character.inventory)


def test_unlocked_state_survives_the_existing_save_overlay():
    from engine.savegame import compute_delta_level, _overlay_entities
    session, chest = _locked(lock_difficulty=20, owner="wick", id="chest-uuid")
    base = {"things": [{"pos": list(chest.pos), "properties": copy.deepcopy(chest.properties)}]}
    session.open_container(chest)
    _set_current(session)
    live = {"things": [{"pos": list(chest.pos), "properties": copy.deepcopy(chest.properties)}]}
    delta = compute_delta_level(base, live)
    restored = _Thing("Chest", type="container", locked=True, id="chest-uuid")
    logic = SimpleNamespace(editor_state=SimpleNamespace(things=[restored], brushes=[]),
                            prop_runtime=None)
    _overlay_entities(logic, delta, complete=True)
    assert restored.properties["locked"] is False
    assert restored.properties["owner"] == "wick"
    assert restored.properties["inventory"] == chest.properties["inventory"]


def test_mouse_motion_and_clicks_reach_the_tumblers_through_the_window_manager(qt_app):
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QPainter, QPixmap
    from engine.floating_windows import WindowManager
    from ..host import MiniwindGame
    from ..ui import hits, screens
    from ..ui.lockpick_window import LockpickWindow
    session, chest = _locked(lock_difficulty=40)
    session.open_container(chest)
    wm = WindowManager()
    host = MiniwindGame.__new__(MiniwindGame)
    host._sync_overlay_windows(session, SimpleNamespace(window_manager=wm), 1280, 800)
    win = session._overlay_win
    assert isinstance(win, LockpickWindow) and win.wants_cursor
    assert "Medieval" in win.title_font.family()
    pixmap = QPixmap(1280, 800)
    painter = QPainter(pixmap)
    hits.begin()
    wm.draw_all(painter)
    hits.end()
    painter.end()
    assert screens.animating(session)
    assert {"Lift tumbler", "Set tumbler", "Leave [Esc]"} <= {lab for _, lab in hits.targets()}
    field, xs, _ = win._geometry()

    def move(x, y):
        event = QMouseEvent(QEvent.MouseMove, QPointF(x, y), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        assert wm.handle_mouse_move(event, 1280, 800)
        hits.run_clicks(session)

    move(xs[1], field.bottom() - 10)
    move(xs[1], field.bottom() - 40)
    assert session.lockpicking.selected == 1
    assert session.lockpicking.pins[1].phase == "rise"
    # The modal tick advances pins while the world clock stays paused.
    hour = session.clock.hour
    host._handle_screen_input(session, frozenset(),
                              SimpleNamespace(delta=session.lockpicking.pins[1].rise + 1e-5))
    assert session.lockpicking.can_set and session.clock.hour == hour
    event = QMouseEvent(QEvent.MouseButtonPress, QPointF(xs[1], field.bottom() - 40),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    assert wm.handle_mouse_press(event)
    hits.run_clicks(session)
    assert session.lockpicking.pins[1].latched
    # A stale window's mouse callback cannot affect a newly started attempt.
    move(xs[0], field.bottom() - 10)
    wm.handle_mouse_move(QMouseEvent(QEvent.MouseMove, QPointF(xs[0], field.bottom() - 40),
                                    Qt.NoButton, Qt.NoButton, Qt.NoModifier), 1280, 800)
    session.cancel_lockpicking()
    session.open_container(chest)
    hits.run_clicks(session)
    assert session.lockpicking.pins[0].phase == "rest"
    host._sync_overlay_windows(session, SimpleNamespace(window_manager=wm), 1280, 800)
    assert win.attempt is session.lockpicking
    move(xs[0], field.bottom() - 10)
    move(xs[0], field.bottom() - 40)
    assert session.lockpicking.pins[0].phase == "rise"
    session.tick_lockpicking(2)
    # Smooth small downward events must rearm the next upward stroke too.
    for offset in range(1, 7):
        move(xs[0], field.bottom() - 40 + offset)
    for offset in range(1, 11):
        move(xs[0], field.bottom() - 34 - offset * 2)
    assert session.lockpicking.pins[0].phase == "rise"
    hits.clear()


def test_breakage_is_drawn_and_last_pick_buttons_are_disabled(qt_app):
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import hits
    from ..ui.lockpick_window import draw_lock
    session, chest = _locked(picks=1)
    session.open_container(chest)

    def frame():
        image = QImage(620, 520, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        hits.begin()
        draw_lock(painter, session, 0, 0, 620, 520)
        hits.end()
        painter.end()
        return image

    intact = frame()
    session.lockpick_action("set")
    snapped = frame()
    session.tick_lockpicking(0.4)
    falling = frame()
    assert intact != snapped and snapped != falling
    assert [lab for _, lab in hits.targets()] == ["Leave [Esc]"]
    hits.clear()


def test_all_fracture_styles_draw_distinct_stable_falling_pieces(qt_app):
    from PyQt5.QtCore import QRect
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import hits
    from ..ui.lockpick_window import draw_lock
    session, chest = _locked(picks=30)
    session.rng = random.Random(5)
    session.open_container(chest)
    seen = {}

    def lock_field():
        image = QImage(620, 520, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        draw_lock(painter, session, 0, 0, 620, 520)
        painter.end()
        # Compare the object itself, excluding changing counts and messages.
        return image.copy(QRect(60, 90, 500, 260))

    for _ in range(24):
        session.lockpick_action("set")
        attempt = session.lockpicking
        session.tick_lockpicking(0.4)
        image = lock_field()
        assert lock_field() == image  # painting never resamples flight or spin
        if attempt.break_style not in seen:
            assert all(other != image for other in seen.values())
            seen[attempt.break_style] = image
        session.tick_lockpicking(1)
        session.lockpick_action("lift")
        session.tick_lockpicking(2)
        if len(seen) == len(Lockpick.BREAK_STYLES):
            break
    assert set(seen) == set(Lockpick.BREAK_STYLES)
    hits.clear()
