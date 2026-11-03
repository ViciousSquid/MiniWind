"""Validated lobby and persistent campaign identities (no Qt or sockets)."""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import MAX_PLAYERS, PROTOCOL_VERSION


class LobbyError(ValueError):
    pass


def content_signature(root):
    """Compare gameplay, including between source and frozen desktop builds."""
    from .compatibility import gameplay_signature

    return gameplay_signature(root, PROTOCOL_VERSION)


def map_path(root, name):
    """Network map names are project-relative paths; never arbitrary host paths."""
    root = Path(root).resolve()
    path = (root / str(name)).resolve()
    if not path.is_relative_to(root / "maps") or path.suffix.lower() != ".json":
        raise LobbyError("Choose a map inside the game's maps folder.")
    if not path.is_file():
        raise LobbyError(f"Map is not installed: {name}")
    return path


def validate_profile(data, *, saved_class=None, allow_bot=False):
    from ..rpg import birthsigns, classes, heads, races

    if not isinstance(data, dict):
        raise LobbyError("Invalid character selection.")
    raw_name = str(data.get("name", "Adventurer"))
    name = raw_name.strip()
    if not name or len(name) > 32 or any(ord(c) < 32 for c in raw_name):
        raise LobbyError("Names must contain 1–32 printable characters.")
    head = str(data.get("head", ""))
    if not heads.is_head(head):
        raise LobbyError("Choose a head before readying up.")
    race = str(data.get("race", ""))
    klass = str(data.get("class", ""))
    sign = str(data.get("birthsign", "none"))
    if race not in races.RACES or (
        klass not in classes.CLASSES and klass != saved_class
    ):
        raise LobbyError("Choose a valid race and class.")
    if sign not in birthsigns.BIRTHSIGNS:
        raise LobbyError("Choose a valid birthsign.")
    gender = str(data.get("gender", "male"))
    if gender not in ("male", "female"):
        raise LobbyError("Invalid character selection.")
    device = str(data.get("device", "keyboard"))
    if (
        device != "keyboard"
        and not device.startswith("pad:")
        and not (allow_bot and device.startswith("bot:"))
    ):
        raise LobbyError("Choose a keyboard or gamepad.")
    return dict(
        name=name,
        head=head,
        race=race,
        **{"class": klass},
        birthsign=sign,
        gender=gender,
        device=device,
        handed="left" if data.get("handed") == "left" else "right",
    )


@dataclass
class Member:
    player_id: str
    owner: str
    profile: dict
    ready: bool = False
    connected: bool = True
    character: dict | None = None
    bot: bool = False

    def public(self):
        return {
            "player_id": self.player_id,
            "owner": self.owner,
            "profile": copy.deepcopy(self.profile),
            "ready": self.ready,
            "connected": self.connected,
            "bot": self.bot,
        }


class Lobby:
    def __init__(self, host="host", name="MiniWind party", signature="", map_name=""):
        self.host = host
        self.name = str(name)[:64] or "MiniWind party"
        self.signature = signature
        self.map_name = map_name
        self.campaign_id = str(uuid.uuid4())
        self.members: list[Member] = []
        self.started = False
        self.revision = 0
        self.resume = None
        self.map_hash = ""
        self.respawn_at_village = False

    def _changed(self):
        self.revision += 1
        if not self.started:
            for member in self.members:
                member.ready = member.bot

    def owned(self, owner):
        return [p for p in self.members if p.owner == owner]

    def member(self, player_id, owner=None):
        found = next((p for p in self.members if p.player_id == player_id), None)
        if found is None or (owner is not None and found.owner != owner):
            raise LobbyError("That character does not belong to this connection.")
        return found

    def add(self, owner, profile, *, player_id=None, character=None, bot=False):
        if len(self.members) >= MAX_PLAYERS:
            raise LobbyError("The party is full (four players).")
        if bot:
            if owner != self.host or self.started:
                raise LobbyError("Only the host can add AI companions before starting.")
            profile = dict(
                profile or {}, device="bot:" + (player_id or str(uuid.uuid4()))
            )
        profile = validate_profile(
            profile, saved_class=(character or {}).get("class"), allow_bot=bot
        )
        self._check_selection(owner, profile)
        member = Member(
            player_id or str(uuid.uuid4()),
            owner,
            profile,
            character=copy.deepcopy(character),
            bot=bot,
        )
        if any(p.player_id == member.player_id for p in self.members):
            raise LobbyError("That character is already in the party.")
        self.members.append(member)
        self._changed()
        return member

    def _check_selection(self, owner, profile, excluding=None):
        for member in self.members:
            if member.player_id == excluding:
                continue
            if member.profile["head"] == profile["head"]:
                raise LobbyError("Another player has chosen that head.")
            if member.owner == owner and member.profile["device"] == profile["device"]:
                raise LobbyError("That control device is already assigned.")

    def update(self, owner, player_id, profile):
        member = self.member(player_id, owner)
        if self.started:
            raise LobbyError("Appearance is fixed once the adventure has started.")
        if member.bot:
            profile = dict(profile or {}, device=member.profile["device"])
        profile = validate_profile(
            profile,
            saved_class=(member.character or {}).get("class"),
            allow_bot=member.bot,
        )
        self._check_selection(owner, profile, player_id)
        if member.character is not None and any(
            profile[k] != member.profile[k] for k in ("race", "class", "birthsign")
        ):
            raise LobbyError("A saved character keeps its race, class and birthsign.")
        member.profile = profile
        self._changed()

    def remove(self, owner, player_id):
        if self.started:
            raise LobbyError("Leave the game to remove a character.")
        self.members.remove(
            self.member(player_id, None if owner == self.host else owner)
        )
        self._changed()

    def ready(self, owner, ready):
        if not isinstance(ready, bool) or not any(not p.bot for p in self.owned(owner)):
            raise LobbyError("Add a local character before readying up.")
        for member in self.owned(owner):
            member.ready = ready or member.bot
        self.revision += 1

    def set_respawn_at_village(self, owner, enabled):
        if owner != self.host or self.started:
            raise LobbyError("Only the host can change companion respawning before starting.")
        if not isinstance(enabled, bool):
            raise LobbyError("Invalid companion respawn setting.")
        if self.respawn_at_village != enabled:
            self.respawn_at_village = enabled
            self._changed()

    @property
    def can_start(self):
        connected = [p for p in self.members if p.connected]
        return any(p.owner == self.host and not p.bot for p in connected) and all(
            p.ready for p in connected
        )

    def start(self, owner):
        if owner != self.host or not self.can_start:
            raise LobbyError("Only the host can start, after every player is ready.")
        self.started = True
        self.revision += 1

    def snapshot(self):
        return {
            "protocol": PROTOCOL_VERSION,
            "name": self.name,
            "host": self.host,
            "signature": self.signature,
            "map": self.map_name,
            "campaign_id": self.campaign_id,
            "revision": self.revision,
            "started": self.started,
            "map_hash": self.map_hash,
            "respawn_at_village": self.respawn_at_village,
            "members": [p.public() for p in self.members],
        }


@dataclass(frozen=True)
class InputFrame:
    move_x: float = 0.0
    move_z: float = 0.0
    aim: float | None = None
    held: frozenset = field(default_factory=frozenset)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise LobbyError("Invalid player input.")

        def finite(value):
            value = float(value)
            if not math.isfinite(value):
                raise LobbyError("Invalid player input.")
            return value

        x, z = finite(data.get("move_x", 0)), finite(data.get("move_z", 0))
        length = max(1.0, math.hypot(x, z))
        aim = data.get("aim")
        aim = finite(aim) % math.tau if aim is not None else None
        held = data.get("held", [])
        allowed = {"sprint", "block", "left_hand", "right_hand", "interact"}
        if (
            not isinstance(held, list)
            or len(held) > len(allowed)
            or any(v not in allowed for v in held)
        ):
            raise LobbyError("Invalid held controls.")
        return cls(x / length, z / length, aim, frozenset(held))

    def to_dict(self):
        return {
            "move_x": self.move_x,
            "move_z": self.move_z,
            "aim": self.aim,
            "held": sorted(self.held),
        }
