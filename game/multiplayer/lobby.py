"""Lobby protocol and launcher-to-game ownership transfer."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from pathlib import Path

from . import PROTOCOL_VERSION
from .compatibility import text_bytes
from .model import Lobby, LobbyError, content_signature, map_path
from .transport import GAME_PORT, NetworkService


def local_identity(root):
    """Opaque reconnect proof, kept outside shared saves and public snapshots."""
    path = Path(root) / "saves" / ".multiplayer-identity"
    try:
        value = path.read_text().strip()
        if len(value) == 64 and all(c in "0123456789abcdef" for c in value):
            return value
    except OSError:
        pass
    value = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Another launcher may have finished creating it, or an interrupted
        # write left an invalid proof. Keep a valid one; replace only corruption.
        existing = path.read_text().strip()
        if len(existing) == 64 and all(c in "0123456789abcdef" for c in existing):
            return existing
        fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)
    return value


class LobbyController:
    def __init__(self, root, map_name, network=None, identity=None):
        self.root = Path(root)
        self.map_name = map_name
        self.network = network or NetworkService()
        self.identity = identity  # disk and hashing are also deferred until open()
        self.signature = ""
        self.owner = "host"
        self.lobby = None
        self.state = None
        self.peers = {}  # socket ID -> authenticated, stable owner
        self.errors = []
        self.started = False
        self.local_only = False
        self.opened = False
        self._requests = {}
        self._pending_peers = {}
        self._last_revision = -1
        self._verified_maps = set()
        self.resume_path = None
        self.travelling = False
        self.solo_copy = False

    def open(self):
        if self.opened:
            return
        self.identity = self.identity or local_identity(self.root)
        self.signature = content_signature(self.root)
        try:
            self.network.start_browser()
        except OSError as exc:
            self.network.stop_browser()
            self.errors.append(
                f"LAN discovery is unavailable ({exc}). Local/AI parties and direct joining are still available."
            )
        self.opened = True

    def host(self, name="MiniWind party", *, local_only=False, port=GAME_PORT):
        if not self.opened:
            raise LobbyError("Open Multiplayer before hosting.")
        path = map_path(self.root, self.map_name)
        if self.lobby is not None:
            raise LobbyError("A party is already open.")
        if not local_only:
            self.network.host(port)
        self.local_only = local_only
        self.owner = "host"
        self.lobby = Lobby(signature=self.signature, name=name, map_name=self.map_name)
        self.lobby.map_hash = hashlib.sha256(text_bytes(path)).hexdigest()
        self.network.stop_browser()
        self._publish()

    def resume_campaign(self, path):
        """Load a co-op roster, or explicitly copy a solo save into this party."""
        if self.lobby is None or self.lobby.members or self.started:
            raise LobbyError("Choose a save before adding characters to the lobby.")
        from engine import savegame

        data = savegame.read(str(path))
        name = "maps/" + Path(str(data.get("map", ""))).name
        map_path(self.root, name)
        self.map_name = self.lobby.map_name = name
        self.lobby.map_hash = hashlib.sha256(
            text_bytes(map_path(self.root, name))
        ).hexdigest()
        campaign = data.get("coop")
        if campaign:
            if (
                campaign.get("version") != 1
                or not 1 <= len(campaign.get("members", [])) <= 4
            ):
                raise LobbyError("Invalid co-op campaign save.")
            try:
                campaign_id = campaign["campaign_id"]
                if str(uuid.UUID(campaign_id)) != campaign_id:
                    raise ValueError("Non-canonical campaign identity")
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                raise LobbyError("Invalid campaign identity in this save.") from exc
            # This identity is also part of the campaign's save filename.
            self.lobby.campaign_id = campaign_id
            self.campaign_state = campaign
            for member in campaign["members"]:
                char = campaign["players"][member["player_id"]]["character"]
                added = self.lobby.add(
                    member["owner"],
                    member["profile"],
                    player_id=member["player_id"],
                    character=char,
                    bot=bool(member.get("bot", False)),
                )
                added.connected = member["owner"] == self.owner
        else:
            values = data.get("miniwind", {}).get("values", {})
            self.solo_copy = True
            raw = values.get("_character")
            if not raw:
                raise LobbyError("This save does not contain a MiniWind character.")
            char = json.loads(raw) if isinstance(raw, str) else raw
            from ..rpg import heads

            profile = dict(
                name=char.get("name", "Adventurer"),
                head=char.get("head") or heads.HEAD_IDS[0],
                race=char.get("race", char.get("race_id", "imperial")),
                **{"class": char.get("class", char.get("class_id", "warrior"))},
                birthsign=char.get("birthsign", char.get("birthsign_id", "none")),
                gender=char.get("gender", "male"),
                handed=char.get("handed", "right"),
                device="keyboard",
            )
            added = self.lobby.add(self.owner, profile, character=char)
            from ..rpg import quest_files, quests
            from .quests import PlayerStore

            quests.load_definitions(quest_files.load_quest_defs(str(self.root)))
            scoped = PlayerStore(None, added.player_id)
            values = {scoped.key(k): v for k, v in values.items()}
            position = data.get("player", {}).get("pos", [0, 0, 0])
            self.campaign_state = {
                "version": 1,
                "campaign_id": self.lobby.campaign_id,
                "world": values,
                "members": [added.public()],
                "players": {
                    added.player_id: {
                        "character": char,
                        "position": position,
                        "angle": 0,
                    }
                },
            }
        self.resume_path = str(Path(path).resolve())
        self._publish()

    def join(self, address, port=GAME_PORT):
        if not self.opened:
            raise LobbyError("Open Multiplayer before joining.")
        self.owner = hashlib.sha256(self.identity.encode()).hexdigest()
        self.network.join(address, port)

    def request(self, op, **args):
        message = dict(type="lobby_request", op=op, **args)
        if self.lobby is not None:
            self._request(self.owner, message)
            self._publish()
        elif not self.network.send("host", message):
            raise LobbyError("The host is not connected.")

    def _request(self, owner, message):
        op = message.get("op")
        if op == "add":
            self.lobby.add(owner, message.get("profile"))
        elif op == "add_bot":
            self.lobby.add(owner, message.get("profile"), bot=True)
        elif op == "update":
            self.lobby.update(owner, message.get("player_id"), message.get("profile"))
        elif op == "remove":
            self.lobby.remove(owner, message.get("player_id"))
        elif op == "ready":
            self.lobby.ready(owner, message.get("ready"))
        elif op == "start":
            self.lobby.start(owner)
            self.started = True
            self.network.advertisement = None
            self.network.broadcast(
                {"type": "start", "state": self.lobby.snapshot()}, peers=self.peers
            )
        else:
            raise LobbyError("Unknown lobby action.")

    def _publish(self):
        self.state = self.lobby.snapshot()
        self.network.advertisement = (
            None
            if self.started
            else {
                "name": self.lobby.name,
                "players": len(self.lobby.members),
                "maximum": 4,
                "signature": self.signature,
                "map": self.map_name,
            }
        )
        self.network.broadcast({"type": "lobby", "state": self.state}, peers=self.peers)

    def handle(self, peer, message):
        """Return True for lobby/lifecycle messages, False for gameplay."""
        kind = message.get("type")
        try:
            if kind == "connected":
                if self.lobby is None:
                    self.network.send(
                        "host",
                        {
                            "type": "hello",
                            "protocol": PROTOCOL_VERSION,
                            "signature": self.signature,
                            "identity": self.identity,
                        },
                    )
                else:
                    self._pending_peers[peer] = time.monotonic()
                return True
            if kind == "hello" and self.lobby is not None:
                if peer not in self._pending_peers:
                    raise LobbyError("Handshake already completed.")
                if (
                    message.get("protocol") != PROTOCOL_VERSION
                    or message.get("signature") != self.signature
                ):
                    raise LobbyError(
                        "Game versions or installed quest content do not match."
                    )
                identity = message.get("identity")
                if (
                    not isinstance(identity, str)
                    or len(identity) != 64
                    or any(c not in "0123456789abcdef" for c in identity)
                ):
                    raise LobbyError("Invalid reconnect identity.")
                owner = hashlib.sha256(identity.encode()).hexdigest()
                if owner in self.peers.values():
                    raise LobbyError("This player is already connected.")
                if (
                    self.started
                    and not self.lobby.owned(owner)
                    and len(self.lobby.members) >= 4
                ):
                    raise LobbyError("The party is full.")
                self.peers[peer] = owner
                self._pending_peers.pop(peer, None)
                for member in self.lobby.owned(owner):
                    member.connected = True
                self.lobby.revision += 1
                self._publish()
                if self.started and self.lobby.owned(owner):
                    self.network.send(
                        peer, {"type": "start", "state": self.lobby.snapshot()}
                    )
                return True
            if kind == "lobby_request" and self.lobby is not None:
                owner = self.peers.get(peer)
                if owner is None:
                    raise LobbyError("Complete the connection handshake first.")
                self._rate_limit(peer, 30)
                self._request(owner, message)
                self._publish()
                if (
                    self.started
                    and message.get("op") == "ready"
                    and message.get("ready")
                ):
                    self.network.send(
                        peer, {"type": "start", "state": self.lobby.snapshot()}
                    )
                return True
            if kind in ("lobby", "start") and self.lobby is None and peer == "host":
                state = message.get("state")
                if (
                    not isinstance(state, dict)
                    or state.get("protocol") != PROTOCOL_VERSION
                ):
                    raise LobbyError("Invalid lobby state.")
                if state.get("signature") != self.signature:
                    raise LobbyError("Game content does not match the host.")
                path = map_path(self.root, state.get("map"))
                expected = state.get("map_hash", "")
                if expected and (str(path), expected) not in self._verified_maps:
                    if hashlib.sha256(text_bytes(path)).hexdigest() != expected:
                        raise LobbyError(
                            "The installed map differs from the host's map."
                        )
                    self._verified_maps.add((str(path), expected))
                self.state = state
                self.map_name = state["map"]
                self.network.stop_browser()
                if kind == "start":
                    self.started = True
                return True
            if kind in ("error", "connection_error"):
                self.errors.append(str(message.get("message", "Connection failed.")))
                return True
            if kind == "disconnected":
                self._pending_peers.pop(peer, None)
                self._requests.pop(peer, None)
                if self.lobby is None:
                    self.disconnected = True
                    self.errors.append(
                        "The host disconnected. Progress is kept in the host's campaign save."
                    )
                else:
                    owner = self.peers.pop(peer, None)
                    for member in self.lobby.owned(owner):
                        member.connected = False
                        member.ready = False
                    self.lobby.revision += 1
                    self._publish()
                return True
            if kind == "closed":
                self.disconnected = True
                self.errors.append("The host closed the party.")
                return True
        except (LobbyError, ValueError, TypeError, KeyError) as exc:
            if self.lobby is not None:
                self.network.send(peer, {"type": "error", "message": str(exc)})
            else:
                self.errors.append(str(exc))
            return True
        return False

    def _rate_limit(self, peer, maximum=120):
        now = time.monotonic()
        start, count = self._requests.get(peer, (now, 0))
        if now - start >= 1:
            start, count = now, 0
        count += 1
        self._requests[peer] = start, count
        if count > maximum:
            raise LobbyError("Too many player actions.")

    def poll(self):
        for peer, message in self.network.poll():
            self.handle(peer, message)
        self.maintenance()

    def maintenance(self):
        """Also run during gameplay, when the game owns the network queue."""
        for peer, started in list(self._pending_peers.items()):
            if time.monotonic() - started > 5:
                self.network.disconnect(peer)
                self._pending_peers.pop(peer, None)

    def close(self):
        if self.lobby is not None:
            self.network.broadcast({"type": "closed"}, peers=self.peers)
        self.network.close()
        self.opened = False


_active = None


def prepare(controller):
    global _active
    if not controller.started:
        raise LobbyError("The party has not started.")
    if _active is not None and _active is not controller:
        _active.close()
    controller.network.stop_browser()
    _active = controller


def active():
    return _active


def finish():
    global _active
    if _active is not None:
        _active.close()
    _active = None
