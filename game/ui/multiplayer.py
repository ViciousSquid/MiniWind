"""Opt-in launcher browser and pre-game character/appearance lobby."""

from __future__ import annotations

import configparser
import time
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..multiplayer.lobby import LobbyController, prepare
from ..multiplayer.model import LobbyError
from ..multiplayer.transport import GAME_PORT
from ..rpg import birthsigns, classes, heads, races


class MultiplayerDialog(QDialog):
    def __init__(self, root, settings_path=None, parent=None, controller=None):
        super().__init__(parent)
        self.root = Path(root)
        cfg = configparser.ConfigParser()
        cfg.read(settings_path or self.root / "settings.ini")
        name = cfg.get("Startup", "default_map", fallback="maps/miniwind_world.json")
        self.controller = controller or LobbyController(root, name)
        self.handed_off = False
        self._shown = False
        self._revision = -1
        self._loaded_player = None
        self._last_search = 0.0
        self.setWindowTitle("MiniWind — Multiplayer")
        self.resize(820, 720)
        self.setMinimumSize(620, 540)
        self.setStyleSheet(
            (parent.styleSheet() if parent is not None else "")
            + """
            QListWidget, QScrollArea, QWidget#multiplayerCharacterForm {
                background-color: #202229; color: #dedee5;
                border: 1px solid #41444e;
            }
            QWidget#multiplayerCharacterForm { border: none; }
            QLineEdit, QSpinBox {
                background-color: #252830; color: #eeeeef;
                border: 1px solid #4a4d58; padding: 5px;
            }
            QLabel { color: #dedee5; background: transparent; }
            """
        )
        outer = QVBoxLayout(self)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        self.status = QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        back = QPushButton("Back to launcher")
        back.clicked.connect(self.reject)
        outer.addWidget(back)
        self._build_browser()
        self._build_lobby()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)

    def _build_browser(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Find a party or play with AI companions")
        layout.addWidget(title)
        self.games = QListWidget()
        self.games.itemDoubleClicked.connect(lambda _: self._join_selected())
        layout.addWidget(self.games)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh LAN games")
        refresh.clicked.connect(lambda: self._try(self.controller.network.search))
        row.addWidget(refresh)
        join = QPushButton("Join selected game")
        join.clicked.connect(self._join_selected)
        row.addWidget(join)
        layout.addLayout(row)
        direct = QFormLayout()
        self.address = QLineEdit()
        self.address.setPlaceholderText("Host IP address or hostname")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(GAME_PORT)
        direct.addRow("Direct join", self.address)
        direct.addRow("Port", self.port)
        layout.addLayout(direct)
        direct_join = QPushButton("Join by address")
        direct_join.clicked.connect(
            lambda: self._join(self.address.text().strip(), self.port.value())
        )
        layout.addWidget(direct_join)
        self.party_name = QLineEdit("MiniWind party")
        layout.addWidget(self.party_name)
        row = QHBoxLayout()
        host = QPushButton("Host LAN / Internet game")
        host.clicked.connect(lambda: self._host(False))
        row.addWidget(host)
        local = QPushButton("Local co-op / AI companions")
        local.clicked.connect(lambda: self._host(True))
        row.addWidget(local)
        layout.addLayout(row)
        note = QLabel(
            "Internet hosts need a reachable TCP port (or a VPN). LAN discovery uses UDP. "
            "Up to four characters can share a party across any mix of computers and controllers."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.pages.addWidget(page)

    def _build_lobby(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.lobby_title = QLabel("Party lobby")
        layout.addWidget(self.lobby_title)
        self.members = QListWidget()
        self.members.setMaximumHeight(145)
        self.members.currentRowChanged.connect(self._select_member)
        layout.addWidget(self.members)
        self.resume_button = QPushButton("Resume a co-op campaign / copy a solo save")
        self.resume_button.clicked.connect(self._resume)
        layout.addWidget(self.resume_button)
        form_widget = QWidget()
        form_widget.setObjectName("multiplayerCharacterForm")
        form = QFormLayout(form_widget)
        self.name = QLineEdit("Adventurer")
        self.head = QComboBox()
        self.head.setIconSize(QSize(36, 36))
        for head in heads.HEAD_IDS:
            self.head.addItem(QIcon(str(self.root / heads.head_path(head))), head, head)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(80)
        self.head.currentIndexChanged.connect(self._preview)
        self.race = QComboBox()
        for value in races.RACES.values():
            self.race.addItem(value.label, value.id)
        self.klass = QComboBox()
        for value in classes.CLASSES.values():
            self.klass.addItem(value.label, value.id)
        self.sign = QComboBox()
        for value in birthsigns.BIRTHSIGNS.values():
            self.sign.addItem(value.label, value.id)
        self.sign.setCurrentIndex(self.sign.findData("none"))
        self.device = QComboBox()
        self.device.addItem("Keyboard and mouse", "keyboard")
        self.handed = QComboBox()
        self.handed.addItem("Right-handed", "right")
        self.handed.addItem("Left-handed", "left")
        self.gender = QComboBox()
        self.gender.addItem("Male", "male")
        self.gender.addItem("Female", "female")
        form.addRow("Name", self.name)
        form.addRow("Appearance", self.head)
        form.addRow("", self.preview)
        form.addRow("Race", self.race)
        form.addRow("Class", self.klass)
        form.addRow("Birthsign", self.sign)
        form.addRow("Controls", self.device)
        refresh = QPushButton("Refresh controllers")
        refresh.clicked.connect(self._refresh_devices)
        form.addRow("", refresh)
        form.addRow("Handedness", self.handed)
        form.addRow("Gender", self.gender)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add local player")
        self.add_button.clicked.connect(
            lambda: self._try(
                lambda: self.controller.request("add", profile=self._profile())
            )
        )
        row.addWidget(self.add_button)
        self.update_button = QPushButton("Apply changes")
        self.update_button.clicked.connect(self._update_member)
        row.addWidget(self.update_button)
        self.remove_button = QPushButton("Remove local player")
        self.remove_button.clicked.connect(lambda: self._member_request("remove"))
        row.addWidget(self.remove_button)
        layout.addLayout(row)
        self.bot_button = QPushButton("Add AI companion")
        self.bot_button.clicked.connect(self._add_bot)
        layout.addWidget(self.bot_button)
        row = QHBoxLayout()
        self.ready_button = QPushButton("Ready")
        self.ready_button.clicked.connect(self._ready)
        row.addWidget(self.ready_button)
        self.start_button = QPushButton("Start adventure")
        self.start_button.clicked.connect(
            lambda: self._try(lambda: self.controller.request("start"))
        )
        row.addWidget(self.start_button)
        layout.addLayout(row)
        self.pages.addWidget(page)
        self._preview()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            # The first socket and controller enumeration happen only after
            # the multiplayer section is visible, never in Launcher.__init__.
            QTimer.singleShot(0, self._open)

    def _open(self):
        if not self.isVisible():
            return
        if not self._try(self.controller.open):
            return
        self._refresh_devices()
        self.timer.start(50)
        self.status.setText("Searching for LAN games…")

    def _refresh_devices(self):
        from ..multiplayer.devices import available_pads

        current = self.device.currentData()
        self.device.clear()
        self.device.addItem("Keyboard and mouse", "keyboard")
        for device, label in available_pads():
            self.device.addItem(label, device)
        if str(current).startswith("bot:"):
            self.device.addItem("AI companion (host controlled)", current)
        if self.device.findData(current) >= 0:
            self.device.setCurrentIndex(self.device.findData(current))

    def _profile(self):
        return dict(
            name=self.name.text(),
            head=self.head.currentData(),
            race=self.race.currentData(),
            **{"class": self.klass.currentData()},
            birthsign=self.sign.currentData(),
            device=self.device.currentData(),
            handed=self.handed.currentData(),
            gender=self.gender.currentData(),
        )

    def _preview(self, *_):
        head = self.head.currentData()
        if head:
            pixmap = QPixmap(str(self.root / heads.head_path(head)))
            self.preview.setPixmap(
                pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def _try(self, action):
        try:
            action()
            return True
        except (OSError, LobbyError, ValueError) as exc:
            self.status.setText(str(exc))
            return False

    def _host(self, local):
        if self._try(
            lambda: self.controller.host(
                self.party_name.text(), local_only=local, port=self.port.value()
            )
        ):
            self.pages.setCurrentIndex(1)
            self.status.setText(
                (
                    "Local party. "
                    if local
                    else f"Hosting on TCP port {self.controller.network.port}. Share your IP address and port to invite friends. "
                )
                + "Choose your head here, add each local player and ready up."
            )
            self._render_lobby()

    def _resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a campaign",
            str(self.root / "saves"),
            "Fio saves (*.fiosave);;All files (*)",
        )
        if path:
            self._try(lambda: self.controller.resume_campaign(path))

    def _add_bot(self):
        state = self.controller.state or {}
        members = state.get("members", [])
        selected = self._profile()
        used = {m["profile"]["head"] for m in members}
        if selected["head"] in used:
            selected["head"] = next(
                (h for h in heads.HEAD_IDS if h not in used), selected["head"]
            )
        if selected["name"] == "Adventurer" or any(
            m["profile"]["name"] == selected["name"] for m in members
        ):
            selected["name"] = (
                f"Companion {1 + sum(bool(m.get('bot')) for m in members)}"
            )
        if self._try(lambda: self.controller.request("add_bot", profile=selected)):
            self._render_lobby()
            self.members.setCurrentRow(self.members.count() - 1)
            self.status.setText(
                "AI companion added. Choose its head and class here; AI needs no control device. Bots ready automatically."
            )

    def _join_selected(self):
        item = self.games.currentItem()
        if item is not None:
            value = item.data(Qt.UserRole)
            self._join(value["address"], value["port"])

    def _join(self, address, port):
        if not address:
            self.status.setText("Enter the host's address or select a LAN game.")
            return
        if self._try(lambda: self.controller.join(address, port)):
            self.status.setText("Connecting…")

    def _selected(self):
        item = self.members.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _select_member(self, *_):
        member = self._selected()
        own = member is not None and member["owner"] == self.controller.owner
        self.device.setEnabled(not bool(member and member.get("bot")))
        self.remove_button.setText(
            "Remove AI companion"
            if member and member.get("bot")
            else "Remove local player"
        )
        self.update_button.setEnabled(own)
        self.remove_button.setEnabled(
            own or (member is not None and self.controller.lobby is not None)
        )
        if own and member["player_id"] != self._loaded_player:
            self._loaded_player = member["player_id"]
            profile = member["profile"]
            self.name.setText(profile["name"])
            if member.get("bot") and self.device.findData(profile["device"]) < 0:
                self.device.addItem("AI companion (host controlled)", profile["device"])
            if self.klass.findData(profile["class"]) < 0:
                self.klass.addItem("Saved custom class", profile["class"])
            for combo, key in (
                (self.head, "head"),
                (self.race, "race"),
                (self.klass, "class"),
                (self.sign, "birthsign"),
                (self.device, "device"),
                (self.handed, "handed"),
                (self.gender, "gender"),
            ):
                index = combo.findData(profile[key])
                if index >= 0:
                    combo.setCurrentIndex(index)

    def _member_request(self, op, **args):
        member = self._selected()
        if member is not None:
            self._try(
                lambda: self.controller.request(
                    op, player_id=member["player_id"], **args
                )
            )

    def _update_member(self):
        self._member_request("update", profile=self._profile())

    def _ready(self):
        state = self.controller.state or {}
        owned = [
            m
            for m in state.get("members", [])
            if m["owner"] == self.controller.owner and not m.get("bot")
        ]
        self._try(
            lambda: self.controller.request(
                "ready", ready=not bool(owned and all(m["ready"] for m in owned))
            )
        )

    def _render_lobby(self):
        state = self.controller.state
        if state is None:
            return
        self.pages.setCurrentIndex(1)
        previous = self._selected()
        selected = previous["player_id"] if previous else None
        self.members.blockSignals(True)
        self.members.clear()
        owned = []
        for member in state["members"]:
            own = member["owner"] == self.controller.owner
            if own and not member.get("bot"):
                owned.append(member)
            profile = member["profile"]
            status = (
                "Disconnected"
                if not member["connected"]
                else "Ready"
                if member["ready"]
                else "Choosing"
            )
            item = QListWidgetItem(
                QIcon(str(self.root / heads.head_path(profile["head"]))),
                f"{profile['name']}  ·  {profile['class'].title()}  ·  {status}"
                + (
                    "  (AI companion)"
                    if member.get("bot")
                    else "  (this computer)"
                    if own
                    else ""
                ),
            )
            item.setData(Qt.UserRole, member)
            self.members.addItem(item)
            if member["player_id"] == selected:
                self.members.setCurrentItem(item)
        self.members.blockSignals(False)
        self.lobby_title.setText(f"{state['name']} — {len(state['members'])}/4 players")
        self.start_button.setVisible(self.controller.lobby is not None)
        self.resume_button.setVisible(self.controller.lobby is not None)
        self.resume_button.setEnabled(not state["members"])
        connected = [m for m in state["members"] if m["connected"]]
        self.start_button.setEnabled(
            any(m["owner"] == state["host"] and not m.get("bot") for m in connected)
            and all(m["ready"] for m in connected)
        )
        self.add_button.setEnabled(len(state["members"]) < 4)
        self.bot_button.setVisible(self.controller.lobby is not None)
        self.bot_button.setEnabled(len(state["members"]) < 4)
        self.ready_button.setEnabled(bool(owned))
        self.ready_button.setText(
            "Not ready" if owned and all(m["ready"] for m in owned) else "Ready"
        )
        self._select_member()

    def _poll(self):
        if not self.isVisible():
            return
        self.controller.poll()
        if self.controller.errors:
            self.status.setText(self.controller.errors.pop(0))
        if self.controller.state is not None:
            revision = self.controller.state.get("revision", 0)
            if revision != self._revision:
                self._revision = revision
                self._render_lobby()
        elif time.monotonic() - self._last_search > 2:
            self._last_search = time.monotonic()
            self._try(self.controller.network.search)
            selected = self.games.currentRow()
            self.games.clear()
            for game in self.controller.network.found_games():
                item = QListWidgetItem(
                    f"{game.get('name', 'MiniWind')} — {game.get('players', 0)}/4  ·  {game['address']}:{game['port']}"
                )
                item.setData(Qt.UserRole, game)
                self.games.addItem(item)
            if selected >= 0:
                self.games.setCurrentRow(min(selected, self.games.count() - 1))
        if self.controller.started:
            prepare(self.controller)
            self.handed_off = True
            self.accept()

    def done(self, result):
        self.timer.stop()
        if not self.handed_off:
            self.controller.close()
        super().done(result)

    def hideEvent(self, event):
        self.timer.stop()
        if not self.handed_off:
            self.controller.close()
        super().hideEvent(event)
