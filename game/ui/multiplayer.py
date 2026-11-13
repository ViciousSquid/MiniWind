"""Opt-in launcher browser and pre-game character/appearance lobby."""

from __future__ import annotations

import configparser
import time
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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
        self.controller.config = cfg
        try:
            self.game_port = cfg.getint("Multiplayer", "port", fallback=GAME_PORT)
        except ValueError:
            self.game_port = GAME_PORT
        self.handed_off = False
        self._shown = False
        self._revision = -1
        self._loaded_player = None
        self._last_search = 0.0
        self._knock_started = 0.0
        self.setWindowTitle("MiniWind — Multiplayer")
        self.resize(840, 800)
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
            QGroupBox {
                color: #e8d9b0; font-weight: bold; border: 1px solid #41444e;
                border-radius: 4px; margin-top: 14px; padding-top: 6px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
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
        title = QLabel("<b>Play together</b> — up to four players, and AI companions besides")
        layout.addWidget(title)
        # Join: one box, a friend code (or an address), and Join.
        join_box = QGroupBox("Join a friend")
        join_frame = QVBoxLayout(join_box)
        join_layout = QHBoxLayout()
        self.code_entry = QLineEdit()
        self.code_entry.setObjectName("friendCodeEntry")
        self.code_entry.setPlaceholderText("Paste a friend code — e.g. 7K2QD-M4XA9-0RT3V")
        self.code_entry.returnPressed.connect(self._join_code)
        join_layout.addWidget(self.code_entry, 1)
        join = QPushButton("Join")
        join.setObjectName("joinWithCode")
        join.clicked.connect(self._join_code)
        join_layout.addWidget(join)
        join_outer = join_frame
        join_outer.addLayout(join_layout)
        self.join_tcp = QCheckBox("Connect over TCP instead (the host forwards TCP port 39745)")
        self.join_tcp.setObjectName("joinOverTcp")
        self.join_tcp.setToolTip("Friend codes normally connect over UDP, which gets through home "
                                 "routers. TCP needs the host's router to forward the port.")
        join_outer.addWidget(self.join_tcp)
        layout.addWidget(join_box)
        # While knocking: this computer's reply code, for a host whose
        # router keeps it out.
        self.reply_box = QWidget()
        reply_row = QHBoxLayout(self.reply_box)
        reply_row.setContentsMargins(0, 0, 0, 0)
        self.reply_label = QLabel()
        self.reply_label.setWordWrap(True)
        reply_row.addWidget(self.reply_label, 1)
        self.reply_copy = QPushButton("Copy reply code")
        self.reply_copy.setObjectName("copyReplyCode")
        self.reply_copy.clicked.connect(self._copy_reply)
        reply_row.addWidget(self.reply_copy)
        self.reply_box.setVisible(False)
        layout.addWidget(self.reply_box)
        # Host: one press, and the code appears in the lobby to copy.
        host_box = QGroupBox("Start a party")
        host_layout = QVBoxLayout(host_box)
        self.party_name = QLineEdit("MiniWind party")
        host_layout.addWidget(self.party_name)
        row = QHBoxLayout()
        host = QPushButton("Host game (get a friend code)")
        host.setObjectName("hostWithCode")
        host.clicked.connect(lambda: self._host(False))
        row.addWidget(host)
        local = QPushButton("Local co-op / AI companions")
        local.clicked.connect(lambda: self._host(True))
        row.addWidget(local)
        host_layout.addLayout(row)
        layout.addWidget(host_box)
        lan = QGroupBox("Games on this network")
        lan_layout = QVBoxLayout(lan)
        self.games = QListWidget()
        self.games.itemDoubleClicked.connect(lambda _: self._join_selected())
        lan_layout.addWidget(self.games)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda: self._try(self.controller.network.search))
        row.addWidget(refresh)
        join_lan = QPushButton("Join selected game")
        join_lan.clicked.connect(self._join_selected)
        row.addWidget(join_lan)
        lan_layout.addLayout(row)
        layout.addWidget(lan, 1)
        note = QLabel(
            "Up to four characters can share a party across any mix of computers and controllers. "
            "The friend code holds the host's Internet address; share it only with friends."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.pages.addWidget(page)

    def _build_lobby(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.lobby_title = QLabel("Party lobby")
        layout.addWidget(self.lobby_title)
        self.code_box = QGroupBox("Your friend code")
        code_layout = QVBoxLayout(self.code_box)
        row = QHBoxLayout()
        self.code_view = QLineEdit()
        self.code_view.setObjectName("friendCode")
        self.code_view.setReadOnly(True)
        self.code_view.setAlignment(Qt.AlignCenter)
        self.code_view.setStyleSheet("font-size: 18px; font-weight: bold; letter-spacing: 2px;")
        row.addWidget(self.code_view, 1)
        self.copy_button = QPushButton("Copy code")
        self.copy_button.setObjectName("copyFriendCode")
        self.copy_button.clicked.connect(self._copy_code)
        row.addWidget(self.copy_button)
        self.new_code_button = QPushButton("New code")
        self.new_code_button.setToolTip("Make a fresh code: the old one stops working; "
                                        "friends already here stay.")
        self.new_code_button.clicked.connect(self._new_code)
        row.addWidget(self.new_code_button)
        code_layout.addLayout(row)
        self.code_note = QLabel()
        self.code_note.setWordWrap(True)
        code_layout.addWidget(self.code_note)
        # A friend whose knocking does not get through sends a reply code.
        row = QHBoxLayout()
        self.reply_entry = QLineEdit()
        self.reply_entry.setObjectName("replyCodeEntry")
        self.reply_entry.setPlaceholderText("A friend's reply code")
        self.reply_entry.returnPressed.connect(self._let_in)
        row.addWidget(self.reply_entry, 1)
        let_in = QPushButton("Let in")
        let_in.setObjectName("letInFriend")
        let_in.clicked.connect(self._let_in)
        row.addWidget(let_in)
        code_layout.addLayout(row)
        self.code_box.setVisible(False)
        layout.addWidget(self.code_box)
        self.members = QListWidget()
        self.members.setMaximumHeight(118)
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
        self.respawn_at_village = QCheckBox("Respawn at village")
        self.respawn_at_village.setToolTip(
            "Dead AI companions return to the starting location, then follow roads back to the party."
        )
        self.respawn_at_village.toggled.connect(
            lambda enabled: self._try(
                lambda: self.controller.request("respawn_at_village", enabled=enabled)
            )
        )
        layout.addWidget(self.respawn_at_village)
        self.late_arrival = QCheckBox("Allow late arrivals (players may join after the game starts)")
        self.late_arrival.setObjectName("lateArrival")
        self.late_arrival.setToolTip(
            "On: friends can join the party during play, while there is room. "
            "Off: players can only join here in the lobby, before Start."
        )
        self.late_arrival.toggled.connect(
            lambda enabled: self._try(lambda: self.controller.request("late_arrival", enabled=enabled))
        )
        layout.addWidget(self.late_arrival)
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
                self.party_name.text(), local_only=local, port=self.game_port
            )
        ):
            self.pages.setCurrentIndex(1)
            self.status.setText(
                ("Local party. " if local else "Party open. Send your friend code to up to three friends. ")
                + "Choose your head here, add each local player and ready up."
            )
            if not local:
                self.code_box.setVisible(True)
                self.controller.find_code()
                self._show_code()
            self._render_lobby()

    # -- friend codes ------------------------------------------------------------
    _CODE_NOTES = {
        "router": "Your router opened the way: friends can join with this code from anywhere.",
        "stun": "Friend can't get in? Paste their reply code below, or forward UDP port {port}.",
        "local": "No Internet address was found: this code works on your own network or a VPN.",
    }

    def _show_code(self):
        code = self.controller.code
        how = self.controller.code_how
        if self.code_view.text() != (code or "Finding your address…"):
            self.code_view.setText(code or "Finding your address…")
        self.copy_button.setEnabled(bool(code))
        self.new_code_button.setEnabled(bool(code))
        port = getattr(self.controller.network, "port", self.game_port)
        self.code_note.setText(self._CODE_NOTES.get(how, "").format(port=port))

    def _copy_code(self):
        code = self.controller.code
        if not code:
            return
        board = QApplication.clipboard()
        board.setText(code)
        if board.supportsSelection():
            board.setText(code, board.Selection)
        self.copy_button.setText("Copied")
        QTimer.singleShot(2000, lambda: self.copy_button.setText("Copy code"))

    def _new_code(self):
        self.controller.new_code()
        self._show_code()

    def _let_in(self):
        text = self.reply_entry.text().strip()
        if not text:
            return
        if self._try(lambda: self.controller.let_in(text)):
            self.reply_entry.clear()
            self.status.setText("Letting your friend in: they should be in the party in a moment.")

    def _copy_reply(self):
        code = getattr(self.controller, "reply", "")
        if not code:
            return
        board = QApplication.clipboard()
        board.setText(code)
        if board.supportsSelection():
            board.setText(code, board.Selection)
        self.reply_copy.setText("Copied")
        QTimer.singleShot(2000, lambda: self.reply_copy.setText("Copy reply code"))

    def _show_reply(self):
        """Still knocking after a few seconds: offer the reply code."""
        knocking = (self.controller.state is None and self._knock_started
                    and time.monotonic() - self._knock_started > 4.0)
        code = getattr(self.controller, "reply", "") if knocking else ""
        self.reply_box.setVisible(bool(code))
        if code:
            self.reply_label.setText(
                f"Still knocking… If your friend's router keeps you out, send them your reply "
                f"code and they can let you in:  <b>{code}</b>")

    def _join_code(self):
        text = self.code_entry.text().strip()
        if not text:
            self.status.setText("Paste the friend code your host sent you, or pick a game on this network.")
            return
        tcp = self.join_tcp.isChecked()
        if self._try(lambda: self.controller.join_code(text, tcp=tcp)):
            self._knock_started = time.monotonic()
            self.status.setText("Connecting…")

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
        humans = [m for m in state["members"] if not m.get("bot")]
        companions = len(state["members"]) - len(humans)
        self.lobby_title.setText(
            f"{state['name']} — {len(humans)}/4 players"
            + (f" + {companions} AI companion{'s' if companions != 1 else ''}" if companions else ""))
        self.start_button.setVisible(self.controller.lobby is not None)
        self.resume_button.setVisible(self.controller.lobby is not None)
        self.resume_button.setEnabled(not state["members"])
        connected = [m for m in state["members"] if m["connected"]]
        self.start_button.setEnabled(
            any(m["owner"] == state["host"] and not m.get("bot") for m in connected)
            and all(m["ready"] for m in connected)
        )
        self.add_button.setEnabled(len(humans) < 4)
        self.bot_button.setVisible(self.controller.lobby is not None)
        self.bot_button.setEnabled(companions < 4)
        self.respawn_at_village.blockSignals(True)
        self.respawn_at_village.setChecked(bool(state.get("respawn_at_village", False)))
        self.respawn_at_village.blockSignals(False)
        self.respawn_at_village.setEnabled(self.controller.lobby is not None)
        self.late_arrival.blockSignals(True)
        self.late_arrival.setChecked(bool(state.get("late_arrival", True)))
        self.late_arrival.blockSignals(False)
        self.late_arrival.setEnabled(self.controller.lobby is not None and not state.get("started"))
        self.ready_button.setEnabled(bool(owned))
        self.ready_button.setText(
            "Not ready" if owned and all(m["ready"] for m in owned) else "Ready"
        )
        self._select_member()

    def _poll(self):
        if not self.isVisible():
            return
        self.controller.poll()
        if self.code_box.isVisible():
            self._show_code()
        self._show_reply()
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
