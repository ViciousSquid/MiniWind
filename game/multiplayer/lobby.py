"""Lobby protocol and launcher-to-game ownership transfer."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path

from . import MAX_PARTY, MAX_PLAYERS, PROTOCOL_VERSION
from . import friend_code
from .compatibility import map_hash
from .model import LATE_ARRIVAL_CLOSED, Lobby, LobbyError, content_signature, map_path
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
        #: settings.ini, for [Multiplayer] stun_server / upnp (set by the UI).
        self.config = None
        # Friend codes (game/multiplayer/friend_code.py): the host's
        # invitation and code, and the invitation a joiner shows.
        self.invitation = 0
        self.code = ""
        self.code_how = ""          # "router" | "stun" | "local" | "" while finding
        self.public_ip = ""
        self.mapping = None
        self.join_invitation = 0
        self.public_port = 0
        self.reply = ""                 # a joiner's reply code, once found
        self._wrong_invitations = []    # (time, invitation)
        self._code_thread = None

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
            self.invitation = friend_code.new_invitation()
        self.local_only = local_only
        self.owner = "host"
        self.lobby = Lobby(signature=self.signature, name=name, map_name=self.map_name)
        self.lobby.map_hash = map_hash(path)
        self.network.stop_browser()
        self._publish()

    # -- friend codes ------------------------------------------------------------
    def find_code(self, finder=None, wait=False):
        """Work out where friends can reach this party, and the code for it,
        on a thread of its own (it asks the router, then a STUN server)."""
        if self.lobby is None or self.local_only or not self.invitation:
            return
        port = int(getattr(self.network, "port", GAME_PORT))
        finder = finder or (lambda: friend_code.find_public_address(
            port, self.config, stun=self._stun_from_game_socket))
        self.code, self.code_how = "", ""

        def work():
            try:
                ip, code_port, how, mapping = finder()
            except Exception:
                ip, code_port, how, mapping = friend_code.local_address(), port, "local", None
            if self.lobby is None:            # left while it was finding
                if mapping is not None:
                    mapping.close()
                return
            if self.mapping is not None and self.mapping is not mapping:
                self.mapping.close()
            self.mapping = mapping
            self.public_ip, self.public_port = ip, int(code_port)
            self.code = friend_code.encode(ip, self.public_port, self.invitation)
            self.code_how = how

        self._code_thread = threading.Thread(target=work, name="MiniWind friend code", daemon=True)
        self._code_thread.start()
        if wait:
            self._code_thread.join(10)

    def new_code(self):
        """A fresh invitation: the old code stops working; friends already
        in the party stay in."""
        if self.lobby is None or self.local_only:
            return
        self.invitation = friend_code.new_invitation()
        self._wrong_invitations.clear()
        if self.public_ip:
            self.code = friend_code.encode(self.public_ip, self.public_port, self.invitation)

    def _stun_from_game_socket(self, server):
        """Ask the STUN server from the game's own UDP socket, so the port it
        reports is the one the router maps for the game."""
        udp = getattr(self.network, "udp", None)
        return udp.stun(server) if udp is not None else friend_code.stun_lookup(server)

    def join_code(self, text, tcp=False):
        """Join the party a friend code points at -- over UDP, which gets
        through home routers, or over TCP with *tcp* (the host must have its
        TCP port forwarded) -- or a typed address, over TCP."""
        try:
            address, port, invitation = friend_code.parse(text)
        except friend_code.FriendCodeError as exc:
            raise LobbyError(str(exc)) from exc
        typed = not friend_code.looks_like_code(text)
        if not typed and not invitation:
            raise LobbyError("That is a reply code: give it to your host, who lets you in with it.")
        self.join_invitation = invitation
        if typed or tcp:
            self.join(address, port)
            return
        if not self.opened:
            raise LobbyError("Open Multiplayer before joining.")
        self.owner = hashlib.sha256(self.identity.encode()).hexdigest()
        self.network.join_udp(address, port)
        self.find_reply_code()

    def find_reply_code(self, finder=None):
        """While knocking, work out this computer's reply code (its public
        address, from the game's UDP socket) in case the host's router keeps
        it out: the host can then let it in (:meth:`let_in`)."""
        self.reply = ""
        server = friend_code.stun_server(self.config)
        if finder is None and server is None:
            return

        def work():
            try:
                found = finder() if finder is not None else self._stun_from_game_socket(server)
            except Exception:
                found = None
            if found and found[1]:
                self.reply = friend_code.reply_code(found[0], int(found[1]))

        threading.Thread(target=work, name="MiniWind reply code", daemon=True).start()

    def let_in(self, text):
        """The host lets in a friend whose router -- or this one -- keeps
        them out: *text* is the friend's reply code."""
        if self.lobby is None or self.local_only:
            raise LobbyError("Host a party first.")
        try:
            address, port, invitation = friend_code.decode(text)
        except friend_code.FriendCodeError as exc:
            raise LobbyError(str(exc)) from exc
        if invitation:
            raise LobbyError("That is a friend code for joining a party, not a reply code.")
        let = getattr(self.network, "let_in", None)
        if let is None:
            raise LobbyError("This party cannot let players in that way.")
        let(address, port)

    def _admit(self, peer, owner, invitation):
        """Whether a joiner may in: anyone on the host's own network; a
        member already in the party (a reconnect); else only with this
        party's invitation -- and not while someone is guessing."""
        if self.local_only or not self.invitation:
            return
        address = getattr(self.network, "peer_address", lambda _p: "")(peer)
        if friend_code.trusted_address(address) or self.lobby.owned(owner):
            return
        now = time.monotonic()
        self._wrong_invitations = [(t, i) for t, i in self._wrong_invitations
                                   if now - t < friend_code.WRONG_WINDOW]
        guessing = len({i for _t, i in self._wrong_invitations}) >= friend_code.WRONG_ALLOWED
        if guessing:
            raise LobbyError("The party is not taking new players for a minute. Try again shortly.")
        if not invitation:
            raise LobbyError("From outside the host's network, join with the host's friend code.")
        if invitation != self.invitation:
            self._wrong_invitations.append((now, invitation))
            raise LobbyError("That friend code is out of date: ask the host for the new one.")

    def resume_campaign(self, path):
        """Load a co-op roster, or explicitly copy a solo save into this party."""
        if self.lobby is None or self.lobby.members or self.started:
            raise LobbyError("Choose a save before adding characters to the lobby.")
        from engine import savegame

        data = savegame.read(str(path))
        name = "maps/" + Path(str(data.get("map", ""))).name
        map_path(self.root, name)
        self.map_name = self.lobby.map_name = name
        self.lobby.map_hash = map_hash(map_path(self.root, name))
        campaign = data.get("coop")
        if campaign:
            if (
                campaign.get("version") != 1
                or not 1 <= len(campaign.get("members", [])) <= MAX_PARTY
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
            self.lobby.respawn_at_village = bool(campaign.get("respawn_at_village", False))
            self.lobby.late_arrival = bool(campaign.get("late_arrival", True))
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
            import game.rpg.heads as heads

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
            import game.rpg.quest_files as quest_files
            import game.rpg.quests as quests
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
        elif op == "late_arrival":
            self.lobby.set_late_arrival(owner, message.get("enabled"))
        elif op == "respawn_at_village":
            self.lobby.set_respawn_at_village(owner, message.get("enabled"))
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
                "players": self.lobby.humans(),
                "maximum": MAX_PLAYERS,
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
                            "invite": int(self.join_invitation or 0),
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
                invite = message.get("invite", 0)
                self._admit(peer, owner, invite if isinstance(invite, int) else -1)
                if self.started and not self.lobby.owned(owner):
                    if not self.lobby.late_arrival:
                        raise LobbyError(LATE_ARRIVAL_CLOSED)
                    if self.lobby.humans() >= MAX_PLAYERS:
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
                    if map_hash(path) != expected:
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
        if self.mapping is not None:
            mapping, self.mapping = self.mapping, None
            threading.Thread(target=mapping.close, name="MiniWind unmap", daemon=True).start()


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
