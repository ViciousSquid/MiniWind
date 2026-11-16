"""Opt-in launcher browser and pre-game character/appearance lobby.

Two pages, each with one thing to press:

* **Play together** -- paste a friend's code (that alone joins), pick a game
  found on this network, or host. Nothing else is asked first.
* **The lobby** -- everyone arrives with a character already in the party
  (the one they used last time, with a head nobody else has). Changes to it
  apply as they are made. A joiner presses **Ready**; the host presses
  **Start adventure**. Everything rarer (a second player on this computer,
  AI companions, the party's rules, letting in a friend whose router keeps
  them out) is folded away under a heading until it is wanted.
"""

from __future__ import annotations

import configparser
import json
import time
from pathlib import Path

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..multiplayer import MAX_COMPANIONS, MAX_PLAYERS, friend_code
from ..multiplayer.lobby import LobbyController, prepare
from ..multiplayer.model import LobbyError, default_profile, start_blocker
from ..multiplayer.transport import GAME_PORT
from ..rpg import birthsigns, classes, heads, races

#: What of a character is remembered between sessions (not the device).
_REMEMBERED = ("name", "head", "race", "class", "birthsign", "handed", "gender")

_PRIMARY = (
    "QPushButton { background-color:#2E7D32; color:white; border:1px solid #1B5E20;"
    " font-weight:bold; padding:0.6em 1.4em; }"
    "QPushButton:hover { background-color:#388E3C; }"
    "QPushButton:pressed { background-color:#1B5E20; }"
    "QPushButton:disabled { background-color:#2f3a31; color:#8d968e; border-color:#2f3a31; }"
)
_FOLD = (
    "QPushButton { border:none; background:transparent; color:#b9bdc9; text-align:left;"
    " padding:2px 0; }"
    "QPushButton:hover { color:#ffffff; }"
)


class MultiplayerDialog(QDialog):
    def __init__(self, root, settings_path=None, parent=None, controller=None,
                 profile_path=None):
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
        #: Where this computer's last character is kept (None: not kept).
        self.profile_path = Path(profile_path) if profile_path else None
        self.handed_off = False
        self._shown = False
        self._revision = None
        self._loaded_player = None
        self._known_players = None
        self._last_search = 0.0
        self._knock_started = 0.0
        self._joining = ""
        self.setWindowTitle("MiniWind — Multiplayer")
        self.resize(860, 720)
        self.setMinimumSize(640, 520)
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
        self.back = QPushButton("Back to launcher")
        self.back.clicked.connect(self.reject)
        outer.addWidget(self.back)
        self._build_browser()
        self._build_lobby()
        self._load_remembered()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        # Changes to a character apply by themselves, a moment after the last one.
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(450)
        self._apply_timer.timeout.connect(self._apply_edit)

    # -- pages -------------------------------------------------------------------
    def _fold(self, title, body, layout, open_=False):
        """A heading that shows or hides *body*: rarely needed controls stay
        out of the way until asked for."""
        toggle = QPushButton()
        toggle.setCheckable(True)
        toggle.setFlat(True)
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setStyleSheet(_FOLD)

        def show(opened):
            toggle.setText(("▾  " if opened else "▸  ") + title)
            body.setVisible(opened)

        toggle.toggled.connect(show)
        toggle.toggled.connect(lambda _: QTimer.singleShot(0, self._fit))
        toggle.setChecked(open_)
        show(open_)
        layout.addWidget(toggle)
        layout.addWidget(body)
        return toggle

    def _fit(self):
        """Grow the window when an opened heading needs the room, so nothing
        is squeezed."""
        need = self.minimumSizeHint().height()
        screen = self.screen().availableGeometry().height() if self.screen() else need
        if self.height() < need:
            self.resize(self.width(), min(need, screen))

    def _build_browser(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("<b>Play together</b> — up to four players, and AI companions besides")
        layout.addWidget(title)
        # Join: paste the code and you are in the lobby.
        join_box = QGroupBox("Join a friend")
        join_frame = QVBoxLayout(join_box)
        join_layout = QHBoxLayout()
        self.code_entry = QLineEdit()
        self.code_entry.setObjectName("friendCodeEntry")
        self.code_entry.setPlaceholderText("Paste your friend's code — e.g. 7K2QD-M4XA9-0RT3V")
        self.code_entry.returnPressed.connect(self._join_code)
        self.code_entry.textChanged.connect(self._code_typed)
        join_layout.addWidget(self.code_entry, 1)
        self.join_button = QPushButton("Join")
        self.join_button.setObjectName("joinWithCode")
        self.join_button.setStyleSheet(_PRIMARY)
        self.join_button.clicked.connect(self._join_code)
        join_layout.addWidget(self.join_button)
        join_frame.addLayout(join_layout)
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
        join_frame.addWidget(self.reply_box)
        layout.addWidget(join_box)
        # Games found on this network: shown only when there are any; one
        # click joins.
        self.lan_box = QGroupBox("Games on this network — click one to join")
        lan_layout = QVBoxLayout(self.lan_box)
        self.games = QListWidget()
        self.games.setMaximumHeight(110)
        self.games.itemClicked.connect(lambda _: self._join_selected())
        self.games.itemActivated.connect(lambda _: self._join_selected())
        lan_layout.addWidget(self.games)
        self.lan_box.setVisible(False)
        layout.addWidget(self.lan_box)
        # Host: one press, and the code is in the lobby to copy.
        host_box = QGroupBox("Host a party")
        host_layout = QVBoxLayout(host_box)
        self.host_button = QPushButton("Host a game")
        self.host_button.setObjectName("hostWithCode")
        self.host_button.setStyleSheet(_PRIMARY)
        self.host_button.setToolTip("Open a party and get a friend code to send to up to three friends.")
        self.host_button.clicked.connect(lambda: self._host(False))
        host_layout.addWidget(self.host_button)
        self.local_button = QPushButton("Play on this computer")
        self.local_button.setToolTip("Local co-op on shared controllers, or a party of AI companions. "
                                     "Opens no network connection.")
        self.local_button.clicked.connect(lambda: self._host(True))
        host_layout.addWidget(self.local_button)
        layout.addWidget(host_box)
        # Rarely needed.
        more = QWidget()
        more_layout = QFormLayout(more)
        more_layout.setContentsMargins(18, 0, 0, 0)
        self.party_name = QLineEdit("MiniWind party")
        more_layout.addRow("Party name", self.party_name)
        self.join_tcp = QCheckBox("Join over TCP instead (the host forwards TCP port 39745)")
        self.join_tcp.setObjectName("joinOverTcp")
        self.join_tcp.setToolTip("Friend codes normally connect over UDP, which gets through home "
                                 "routers. TCP needs the host's router to forward the port.")
        more_layout.addRow(self.join_tcp)
        self.more_toggle = self._fold("More options", more, layout)
        layout.addStretch(1)
        note = QLabel(
            "A friend code holds the host's Internet address: share it only with friends."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9a9eab;")
        layout.addWidget(note)
        self.pages.addWidget(page)

    def _build_lobby(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.lobby_title = QLabel("Party lobby")
        self.lobby_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.lobby_title)
        self.code_box = QGroupBox("Your friend code — send it to your friends")
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
        code_layout.addLayout(row)
        self.code_note = QLabel()
        self.code_note.setWordWrap(True)
        code_layout.addWidget(self.code_note)
        # A friend whose knocking does not get through sends a reply code.
        help_body = QWidget()
        help_row = QHBoxLayout(help_body)
        help_row.setContentsMargins(18, 0, 0, 0)
        self.reply_entry = QLineEdit()
        self.reply_entry.setObjectName("replyCodeEntry")
        self.reply_entry.setPlaceholderText("Paste the reply code your friend was shown")
        self.reply_entry.returnPressed.connect(self._let_in)
        help_row.addWidget(self.reply_entry, 1)
        let_in = QPushButton("Let in")
        let_in.setObjectName("letInFriend")
        let_in.clicked.connect(self._let_in)
        help_row.addWidget(let_in)
        self.new_code_button = QPushButton("New code")
        self.new_code_button.setToolTip("Make a fresh code: the old one stops working; "
                                        "friends already here stay.")
        self.new_code_button.clicked.connect(self._new_code)
        help_row.addWidget(self.new_code_button)
        self.help_toggle = self._fold("A friend can't get in?", help_body, code_layout)
        self.code_box.setVisible(False)
        layout.addWidget(self.code_box)
        self.members = QListWidget()
        self.members.setIconSize(QSize(28, 28))
        self.members.setWordWrap(True)
        self.members.setMinimumHeight(150)
        self.members.currentRowChanged.connect(self._select_member)
        # The party on the left, this computer's character beside it.
        middle = QHBoxLayout()
        middle.addWidget(self.members, 2)
        # The character: the selected one of this computer's.
        self.form_box = QGroupBox("Your character")
        form_layout = QVBoxLayout(self.form_box)
        form_widget = QWidget()
        form_widget.setObjectName("multiplayerCharacterForm")
        form = QFormLayout(form_widget)
        self.name = QLineEdit("Adventurer")
        self.name.setMaxLength(32)
        self.head = QComboBox()
        self.head.setIconSize(QSize(44, 44))
        for head in heads.HEAD_IDS:
            self.head.addItem(QIcon(str(self.root / heads.head_path(head))), head, head)
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
        form.addRow("Race", self.race)
        form.addRow("Class", self.klass)
        form.addRow("Birthsign", self.sign)
        form.addRow("Controls", self.device)
        form.addRow("Handedness", self.handed)
        form.addRow("Gender", self.gender)
        self.name.textEdited.connect(self._edited)
        for combo in (self.head, self.race, self.klass, self.sign, self.device,
                      self.handed, self.gender):
            combo.currentIndexChanged.connect(self._edited)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        form_layout.addWidget(scroll)
        middle.addWidget(self.form_box, 3)
        layout.addLayout(middle, 1)
        # Everything rarer, folded away.
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(18, 0, 0, 0)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add a player on this computer")
        self.add_button.setToolTip("Another person on this computer: each needs a controller of their own.")
        self.add_button.clicked.connect(self._add_local)
        row.addWidget(self.add_button)
        self.bot_button = QPushButton("Add AI companion")
        self.bot_button.clicked.connect(self._add_bot)
        row.addWidget(self.bot_button)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Remove the character selected in the list above.")
        self.remove_button.clicked.connect(lambda: self._member_request("remove"))
        row.addWidget(self.remove_button)
        options_layout.addLayout(row)
        row = QHBoxLayout()
        self.refresh_button = QPushButton("Find controllers")
        self.refresh_button.setToolTip("Look again for gamepads plugged in since this window opened.")
        self.refresh_button.clicked.connect(self._refresh_devices)
        row.addWidget(self.refresh_button)
        row.addStretch(1)
        options_layout.addLayout(row)
        self.respawn_at_village = QCheckBox("Respawn at village")
        self.respawn_at_village.setToolTip(
            "Dead AI companions return to the starting location, then follow roads back to the party."
        )
        self.respawn_at_village.toggled.connect(
            lambda enabled: self._try(
                lambda: self.controller.request("respawn_at_village", enabled=enabled)
            )
        )
        options_layout.addWidget(self.respawn_at_village)
        self.late_arrival = QCheckBox("Allow late arrivals (players may join after the game starts)")
        self.late_arrival.setObjectName("lateArrival")
        self.late_arrival.setToolTip(
            "On: friends can join the party during play, while there is room. "
            "Off: players can only join here in the lobby, before Start."
        )
        self.late_arrival.toggled.connect(
            lambda enabled: self._try(lambda: self.controller.request("late_arrival", enabled=enabled))
        )
        options_layout.addWidget(self.late_arrival)
        self.options_toggle = self._fold("More players and party options", options, layout)
        # What is being waited for, and the one button to press.
        self.wait_label = QLabel()
        self.wait_label.setWordWrap(True)
        self.wait_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.wait_label)
        self.ready_button = QPushButton("Ready")
        self.ready_button.setObjectName("readyUp")
        self.ready_button.setStyleSheet(_PRIMARY)
        self.ready_button.clicked.connect(self._ready)
        layout.addWidget(self.ready_button)
        self.start_button = QPushButton("Start adventure")
        self.start_button.setObjectName("startAdventure")
        self.start_button.setStyleSheet(_PRIMARY)
        self.start_button.clicked.connect(self._start)
        layout.addWidget(self.start_button)
        self.pages.addWidget(page)

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
        self._say("")
        self.code_entry.setFocus()

    def _say(self, text, error=False):
        self.status.setStyleSheet("color:#ffb4a2; font-weight:bold;" if error and text else "")
        self.status.setText(text)

    def _refresh_devices(self):
        from ..multiplayer.devices import available_pads

        current = self.device.currentData()
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItem("Keyboard and mouse", "keyboard")
        for device, label in available_pads():
            self.device.addItem(label, device)
        if str(current).startswith("bot:"):
            self.device.addItem("AI companion (host controlled)", current)
        if self.device.findData(current) >= 0:
            self.device.setCurrentIndex(self.device.findData(current))
        self.device.blockSignals(False)

    # -- this computer's character -------------------------------------------------
    def _profile(self):
        return dict(
            name=self.name.text().strip() or "Adventurer",
            head=self.head.currentData(),
            race=self.race.currentData(),
            **{"class": self.klass.currentData()},
            birthsign=self.sign.currentData(),
            device=self.device.currentData(),
            handed=self.handed.currentData(),
            gender=self.gender.currentData(),
        )

    def _show_profile(self, profile):
        """Put *profile* in the form, without that counting as an edit."""
        widgets = (self.name, self.head, self.race, self.klass, self.sign, self.device,
                   self.handed, self.gender)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            if "name" in profile:
                self.name.setText(str(profile["name"]))
            for combo, key in (
                (self.head, "head"),
                (self.race, "race"),
                (self.klass, "class"),
                (self.sign, "birthsign"),
                (self.device, "device"),
                (self.handed, "handed"),
                (self.gender, "gender"),
            ):
                index = combo.findData(profile.get(key))
                if index >= 0:
                    combo.setCurrentIndex(index)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _load_remembered(self):
        """The character this computer last played with, so a returning
        player goes from the code to Ready without choosing anything."""
        if self.profile_path is None:
            return
        try:
            saved = json.loads(self.profile_path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(saved, dict):
            self._show_profile({k: saved[k] for k in _REMEMBERED if k in saved})

    def _remember(self):
        mine = self._mine()
        if self.profile_path is None or not mine:
            return
        profile = mine[0]["profile"]
        if mine[0]["player_id"] == self._loaded_player:
            profile = self._profile()       # as just edited, before the host's word of it
        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(
                json.dumps({k: profile[k] for k in _REMEMBERED}, indent=1))
        except OSError:
            pass

    def _try(self, action):
        try:
            action()
            return True
        except (OSError, LobbyError, ValueError) as exc:
            self._say(str(exc), error=True)
            return False

    # -- hosting -----------------------------------------------------------------
    def _host(self, local):
        if not self._try(
            lambda: self.controller.host(
                self.party_name.text(), local_only=local, port=self.game_port
            )
        ):
            return
        self._say("")
        if not self._mine():
            # The host is in its own party from the start.
            self._try(lambda: self.controller.request("add", profile=self._profile()))
        if not local:
            self.code_box.setVisible(True)
            self.controller.find_code()
            self._show_code()
        self.options_toggle.setChecked(bool(local))
        self._render_lobby()

    # -- friend codes ------------------------------------------------------------
    _CODE_NOTES = {
        "router": "Your router opened the way: friends can join with this code from anywhere.",
        "stun": "Friends join with this code. If one can't get in, see below.",
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
        self.reply_entry.setToolTip(
            f"A friend who cannot get in is shown a reply code after a few seconds: paste it "
            f"here. Forwarding UDP port {port} on your router also lets everyone in.")

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
            self._say("Letting your friend in: they should be in the party in a moment.")

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

    # -- joining -----------------------------------------------------------------
    def _entering(self):
        """What this computer brings to a party it joins: its character."""
        self.controller.profile = dict(self._profile(), device="keyboard")

    def _code_typed(self, text):
        """A whole, valid friend code in the box joins by itself -- pasting
        the code is all there is to do."""
        text = text.strip()
        if not text or text == self._joining or self.controller.state is not None:
            return
        if "." in text or ":" in text:
            return                      # a typed address: wait for Join
        try:
            _address, _port, invitation = friend_code.decode(text)
        except friend_code.FriendCodeError:
            return
        if invitation:
            self._join_code()

    def _join_code(self):
        text = self.code_entry.text().strip()
        if not text:
            self._say("Paste the friend code your host sent you.", error=True)
            return
        if text == self._joining:
            return                      # already on its way in with this code
        tcp = self.join_tcp.isChecked()
        self._joining = text
        self._entering()
        if self._try(lambda: self.controller.join_code(text, tcp=tcp)):
            self._knock_started = time.monotonic()
            self._say("Joining your friend's party…")
        else:
            self._joining = ""

    def _join_selected(self):
        item = self.games.currentItem()
        if item is not None:
            value = item.data(Qt.UserRole)
            self._join(value["address"], value["port"])

    def _join(self, address, port):
        if not address:
            self._say("Paste a friend code or pick a game on this network.", error=True)
            return
        self._entering()
        if self._try(lambda: self.controller.join(address, port)):
            self._say("Joining the party…")

    # -- the lobby ---------------------------------------------------------------
    def _is_host(self):
        return self.controller.lobby is not None

    def _members(self):
        return (self.controller.state or {}).get("members", [])

    def _mine(self):
        """This computer's own human characters."""
        return [m for m in self._members()
                if m["owner"] == self.controller.owner and not m.get("bot")]

    def _selected(self):
        item = self.members.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _editing(self):
        """The character the form shows and changes: the selected one if it
        is this computer's (the host's AI companions are), else this
        computer's first; None when it has none yet."""
        selected = self._selected()
        if selected is not None and selected["owner"] == self.controller.owner:
            return selected
        mine = self._mine()
        return mine[0] if mine else None

    def _free_head(self, wanted, excluding=None):
        taken = {m["profile"]["head"] for m in self._members() if m["player_id"] != excluding}
        if wanted not in taken:
            return wanted
        return next((h for h in heads.HEAD_IDS if h not in taken), wanted)

    def _add_local(self):
        """Another person on this computer: a new character on a control
        device nobody here uses yet."""
        mine = self._mine()
        used = {m["profile"]["device"] for m in mine}
        devices = [self.device.itemData(i) for i in range(self.device.count())]
        device = next((d for d in devices
                       if d not in used and not str(d).startswith("bot:")), None)
        if device is None:
            self._say("Each player on this computer needs their own controller: plug one in, "
                      "then press Find controllers.", error=True)
            return
        profile = dict(default_profile(f"Player {len(mine) + 1}"), device=device)
        self._known_players = {m["player_id"] for m in self._members()}
        if self._try(lambda: self.controller.request("add", profile=profile)):
            self._say("Player added: choose their character above.")
            self._render_lobby()

    def _add_bot(self):
        members = self._members()
        profile = default_profile(f"Companion {1 + sum(bool(m.get('bot')) for m in members)}")
        self._known_players = {m["player_id"] for m in members}
        if self._try(lambda: self.controller.request("add_bot", profile=profile)):
            self._render_lobby()
            self._say("AI companion added: choose its look and class above. "
                      "Companions are always ready.")

    def _select_member(self, *_):
        self._show_editing()
        self._show_buttons()

    def _show_editing(self):
        """Point the form at the character being edited."""
        target = self._editing()
        state = self.controller.state or {}
        started = bool(state.get("started"))
        if target is None:
            self.form_box.setTitle("Choose your character")
            self._loaded_player = None
            self.device.setEnabled(True)
            taken = {m["profile"]["head"] for m in self._members()}
            if self.head.currentData() in taken:
                free = self._free_head(self.head.currentData())
                self._show_profile({"head": free})
        else:
            bot = bool(target.get("bot"))
            self.form_box.setTitle(
                "AI companion" if bot
                else "Your character" if len(self._mine()) <= 1
                else f"Your character — {target['profile']['name']}")
            self.device.setEnabled(not bot)
            if target["player_id"] != self._loaded_player:
                self._apply_timer.stop()
                self._loaded_player = target["player_id"]
                profile = target["profile"]
                if bot and self.device.findData(profile["device"]) < 0:
                    self.device.addItem("AI companion (host controlled)", profile["device"])
                if self.klass.findData(profile["class"]) < 0:
                    self.klass.addItem("Saved custom class", profile["class"])
                self._show_profile(profile)
        # Heads somebody else wears cannot be picked.
        excluding = target["player_id"] if target is not None else None
        taken = {m["profile"]["head"] for m in self._members() if m["player_id"] != excluding}
        model = self.head.model()
        for i in range(self.head.count()):
            item = model.item(i)
            free = self.head.itemData(i) not in taken
            if item.isEnabled() != free:
                item.setEnabled(free)
        # A character in a game already running is fixed.
        self.form_box.setEnabled(not (started and target is not None))

    def _edited(self, *_):
        """The form changed: apply it to the character shortly."""
        if self._editing() is not None:
            self._apply_timer.start()

    def _apply_edit(self):
        target = self._editing()
        state = self.controller.state or {}
        if target is None or state.get("started") or target["player_id"] != self._loaded_player:
            return
        profile = self._profile()
        if target.get("bot"):
            profile["device"] = target["profile"]["device"]
        if all(profile[k] == target["profile"].get(k) for k in profile):
            return
        if self._try(lambda: self.controller.request(
                "update", player_id=target["player_id"], profile=profile)):
            if self.status.styleSheet():
                self._say("")
            if self._is_host():
                self._render_lobby()

    def _member_request(self, op, **args):
        member = self._selected()
        if member is not None:
            if self._try(
                lambda: self.controller.request(
                    op, player_id=member["player_id"], **args
                )
            ) and self._is_host():
                self._render_lobby()

    def _ready(self):
        """A joiner's one button: Ready -- or, with no character in the
        party yet, join with the one in the form."""
        self._apply_timer.stop()
        mine = self._mine()
        state = self.controller.state or {}
        if not mine:
            if self._try(lambda: self.controller.request("add", profile=self._profile())):
                if state.get("started"):
                    self._try(lambda: self.controller.request("ready", ready=True))
                    self._say("Joining the adventure…")
                if self._is_host():
                    self._render_lobby()
            return
        self._apply_edit()
        ready = not all(m["ready"] for m in mine)
        if self._try(lambda: self.controller.request("ready", ready=ready)):
            self._remember()
            if self._is_host():
                self._render_lobby()

    def _start(self):
        self._apply_timer.stop()
        self._apply_edit()
        if self._try(lambda: self.controller.request("start")):
            self._remember()

    def _waiting(self, text, go=False):
        """The line over the button: what the party is waiting for -- large,
        and green once this computer has nothing left to do but go."""
        self.wait_label.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #7CD992; padding: 6px 0;" if go
            else "font-size: 16px; color: #e8d9b0; padding: 4px 0;")
        self.wait_label.setText(text)

    def _show_buttons(self):
        state = self.controller.state
        if state is None:
            return
        host = self._is_host()
        started = bool(state.get("started"))
        members = state["members"]
        mine = self._mine()
        humans = [m for m in members if not m.get("bot")]
        companions = len(members) - len(humans)
        selected = self._selected()
        own = selected is not None and selected["owner"] == self.controller.owner
        self.add_button.setEnabled(bool(mine) and len(humans) < MAX_PLAYERS and not started)
        self.bot_button.setVisible(host)
        self.bot_button.setEnabled(companions < MAX_COMPANIONS and not started)
        # Nobody removes their own last character (they would be in the
        # party with nobody to play); the host may remove anyone else's.
        last = bool(own and not selected.get("bot") and len(mine) <= 1)
        self.remove_button.setEnabled(
            selected is not None and not started and not last and (own or host))
        self.remove_button.setText(
            "Remove AI companion" if selected and selected.get("bot") else "Remove")
        self.respawn_at_village.blockSignals(True)
        self.respawn_at_village.setChecked(bool(state.get("respawn_at_village", False)))
        self.respawn_at_village.blockSignals(False)
        self.respawn_at_village.setVisible(host)
        self.late_arrival.blockSignals(True)
        self.late_arrival.setChecked(bool(state.get("late_arrival", True)))
        self.late_arrival.blockSignals(False)
        self.late_arrival.setVisible(host)
        self.late_arrival.setEnabled(not started)
        self.start_button.setVisible(host)
        self.ready_button.setVisible(not host)
        if host:
            blocker = start_blocker(state)
            self.start_button.setEnabled(not blocker)
            others = [m for m in humans if m["owner"] != state["host"] and m["connected"]]
            self._waiting(
                blocker
                or ("Everyone is ready!" if others
                    else "Send the code to your friends — or start on your own."
                    if self.code_box.isVisible()
                    else "Add players or AI companions below, or start on your own."),
                go=bool(others) and not blocker)
        elif not mine:
            self.ready_button.setEnabled(len(humans) < MAX_PLAYERS)
            self.ready_button.setText("Join the adventure" if started else "Join the party")
            self._waiting(
                "The party is full." if len(humans) >= MAX_PLAYERS
                else "The adventure is under way: choose your character and join it."
                if started else "Choose your character and join the party.")
        else:
            ready = all(m["ready"] for m in mine)
            self.ready_button.setEnabled(True)
            self.ready_button.setText("Not ready" if ready else "Ready")
            self._waiting(
                "You are ready! Waiting for the host to start the adventure."
                if ready else "Set up your character, then press Ready.", go=ready)

    def _render_lobby(self):
        state = self.controller.state
        if state is None:
            return
        if self.pages.currentIndex() != 1:
            self.pages.setCurrentIndex(1)
            self.back.setText("Leave party")
            self.reply_box.setVisible(False)
            if not self.status.styleSheet():
                self._say("")               # "Joining…" is over: we are in
        previous = self._selected()
        selected = previous["player_id"] if previous else None
        if self._known_players is not None:
            # A character this computer just added: select it, to set it up.
            new = [m["player_id"] for m in state["members"]
                   if m["player_id"] not in self._known_players
                   and m["owner"] == self.controller.owner]
            if new:
                selected, self._known_players = new[-1], None
        self.members.blockSignals(True)
        self.members.clear()
        for member in state["members"]:
            own = member["owner"] == self.controller.owner
            profile = member["profile"]
            status = (
                "Away"
                if not member["connected"]
                else "Host"
                if member["owner"] == state["host"] and not member.get("bot")
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
                    else "  (you)"
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
            f"{state['name']} — {len(humans)}/{MAX_PLAYERS} players"
            + (f" + {companions} AI companion{'s' if companions != 1 else ''}" if companions else ""))
        self._select_member()

    def _poll(self):
        if not self.isVisible():
            return
        self.controller.poll()
        if self.code_box.isVisible():
            self._show_code()
        self._show_reply()
        if self.controller.errors:
            self._say(self.controller.errors.pop(0), error=True)
            self._joining = ""
        if self.controller.state is not None:
            state = self.controller.state
            revision = (state.get("revision", 0), bool(state.get("started")))
            if revision != self._revision:
                self._revision = revision
                self._render_lobby()
        elif time.monotonic() - self._last_search > 2:
            self._last_search = time.monotonic()
            self._try(self.controller.network.search)
            self.games.clear()
            for game in self.controller.network.found_games():
                item = QListWidgetItem(
                    f"{game.get('name', 'MiniWind')} — {game.get('players', 0)}/{MAX_PLAYERS} players"
                    f"  ·  {game['address']}:{game['port']}"
                )
                item.setData(Qt.UserRole, game)
                self.games.addItem(item)
            self.lan_box.setVisible(self.games.count() > 0)
        if self.controller.started:
            self._remember()
            prepare(self.controller)
            self.handed_off = True
            self.accept()

    def done(self, result):
        self.timer.stop()
        self._apply_timer.stop()
        if not self.handed_off:
            self.controller.close()
        super().done(result)

    def hideEvent(self, event):
        self.timer.stop()
        self._apply_timer.stop()
        if not self.handed_off:
            self.controller.close()
        super().hideEvent(event)
