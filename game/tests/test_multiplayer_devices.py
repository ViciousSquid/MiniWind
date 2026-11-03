"""Independent controllers and unplugging never synthesize shared key presses."""

import math
from types import SimpleNamespace

from game.gamepad import PadState
from game.multiplayer.devices import LocalDevices
from game.multiplayer.model import InputFrame


class Pad:
    def __init__(self, instance, state):
        self.instance, self.state = instance, state

    def read(self, reserved=()):
        return self.state


def devices():
    players = [
        SimpleNamespace(
            player_id=str(i),
            profile={"device": f"pad:{i}"},
            session=SimpleNamespace(open_screen=None, dialogue=None),
        )
        for i in (1, 2)
    ]
    sent = []
    coop = SimpleNamespace(
        local_players=players,
        heading=math.pi,
        local_input=lambda *value: sent.append(value),
    )
    view = SimpleNamespace(
        play_mode=True, window=lambda: SimpleNamespace(isActiveWindow=lambda: True)
    )
    reader = LocalDevices(coop, view)
    reader.pads = {
        "pad:1": Pad("pad:1", PadState(["a"], {"lx": 1})),
        "pad:2": Pad("pad:2", PadState(["b"], {"ly": -1})),
    }
    return reader, sent


def test_two_pads_move_aim_and_act_for_their_own_characters(monkeypatch):
    from game import keybinds

    monkeypatch.setattr(keybinds, "PAD", dict(keybinds.PAD_DEFAULTS))
    reader, sent = devices()
    reader.poll()
    first, second = sent
    assert first[0] == "1" and first[1].move_x > 0.9
    assert first[2] == [("interact", [])]
    assert second[0] == "2" and second[1].move_z < -0.9
    assert "block" in second[1].held and not second[2]
    sent.clear()
    reader.poll()
    assert all(not actions for _, _, actions in sent), (
        "Held buttons must not repeat edge actions"
    )


def test_unplugging_one_pad_zeros_only_its_owner():
    reader, sent = devices()
    reader.pads["pad:1"].state = None
    reader.poll()
    assert sent[0][0] == "1" and sent[0][1] == InputFrame()
    assert sent[1][0] == "2" and sent[1][1].move_z < -0.9


def test_inactive_window_releases_both_players():
    reader, sent = devices()
    reader.view.window = lambda: SimpleNamespace(isActiveWindow=lambda: False)
    reader.poll()
    assert all(frame == InputFrame() and not actions for _, frame, actions in sent)


def test_menu_confirm_uses_inventory_windows_return_action():
    reader, sent = devices()
    received = []
    reader.coop.local_players[0].session.open_screen = "inventory"
    reader.coop.local_players[0].session._overlay_win = SimpleNamespace(
        handle_gamepad=lambda key: received.append(key) or True
    )
    reader.poll()
    assert received == ["return"]
    assert sent[0][1] == InputFrame()
    assert not sent[0][2]


def test_start_opens_only_local_menu_and_does_not_request_party_pause():
    reader, sent = devices()
    opened = []
    reader.view.open_pause_menu = lambda: opened.append(True)
    reader.pads["pad:1"].state = PadState(["start"])
    reader.poll()
    assert opened == [True] and reader.menu_owner == "1"
    assert sent[0][1] == InputFrame() and not sent[0][2]
    assert sent[1][1].move_z < -0.9


def test_real_mouse_aimed_spell_belongs_to_keyboard_character():
    from PyQt5.QtCore import Qt
    from game.ui.hits import GamePointer

    reader, sent = devices()
    keyboard = reader.coop.local_players[1]
    keyboard.profile["device"] = "keyboard"
    keyboard.session.spell_aiming = True
    keyboard.physics = SimpleNamespace(pos=[0, 30, 0])
    keyboard.frame = InputFrame()
    pointer = GamePointer.__new__(GamePointer)
    pointer.view = SimpleNamespace(update=lambda: None)
    pointer._actor_at = lambda x, y: None
    pointer.ground_point = lambda x, y, feet: [12, feet[1] + 48, 24]
    event = SimpleNamespace(button=lambda: Qt.LeftButton, x=lambda: 10, y=lambda: 20)
    pointer.party_world_press(event, reader.coop)
    assert sent == [
        (keyboard.player_id, InputFrame(), [("cast_at", [[12, 78, 24], None])])
    ]


def test_local_game_menu_keeps_mouse_when_controller_panel_is_behind_it(qt_app):
    from engine.qt_game_view import QtGameView
    from PyQt5.QtCore import Qt

    selected = SimpleNamespace(
        player_id="pad-player", open_screen="inventory", dialogue=None
    )
    coop = SimpleNamespace(
        ui_session=selected,
        players={"pad-player": SimpleNamespace(profile={"device": "pad:1"})},
    )
    received = []
    view = SimpleNamespace(
        logic_thread=SimpleNamespace(game_session=SimpleNamespace(coop=coop)),
        play_mode=True,
        pause_menu=None,
        console_overlay_active=False,
        play_menu=SimpleNamespace(active=True, handle_mouse_press=received.append),
        game_pointer=SimpleNamespace(
            party_world_press=lambda *args: (_ for _ in ()).throw(
                AssertionError("gameplay click leaked through the menu")
            )
        ),
    )
    event = SimpleNamespace(button=lambda: Qt.LeftButton)
    QtGameView.mousePressEvent(view, event)
    assert received == [event]
