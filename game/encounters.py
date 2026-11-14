"""
Encounters: the fights worth remembering, with where everyone came from.

An **encounter** opens with the first blow between the player and anyone,
and closes once :data:`QUIET_SECONDS` of the world's time pass with no blow,
roll or kill in it, when the player falls, or when the player leaves the map.
While it runs it scores how *interesting* it is:

=====================================  ======
Each foe in it                           +1
A named foe (not just "Wolf")            +2
A chief, a wraith, a dragon, a queen      +4
A foe sent by a vendetta or an order     +6
The player under half health             +2
The player under a quarter               +4
The player falling                       +8
A critical hit, either way (up to 4)     +1
The fate die (LUCK! / UNLUCKY!)          +3
Each kill                                +1
Lasting 30 s / 90 s                      +1 / +2
=====================================  ======

A foe is *named* when it goes by a name of its own ("Smuggler Captain
Wrexa", "Nils the Brigand"): never a kind's name from the bestiary, and never
one another actor in the world answers to -- four "Smuggler"s or a raid of
"Greenskin Raider"s are what they are, not who.

A foe is a *boss* by its kind (:data:`BOSS_ROLES`), or when it has a name of
its own and :data:`BOSS_TOUGHNESS` times its kind's health: the Spider Queen
is a "monster", the Ashen Hierophant a "cultist", the Den Mother a "wolf".

Once the score reaches the threshold (``[GAME] encounter_threshold``,
default :data:`THRESHOLD`) the encounter is *interesting*: it joins the
session's chronicle -- what happened, who was there and the
:mod:`game.provenance` of each -- whether or not anything is written.

The chronicle rides in the session's store (:data:`STORE_KEY`), as the
storyteller and the law do: a cave, a save and a load keep it, and restoring
an autosave brings back the chronicle as it stood then.

**Recording is optional** (``[GAME] record_encounters``, off by default; the
pause menu's OPTIONS ▸ Advanced). Recorded, an interesting encounter is
written to ``saves/encounters/<when>-<place>/``: ``encounter.json`` (the
record, provenance included) and screenshots taken as it became interesting,
at the player's lowest health, and at the end. The screenshots are taken by
the host on the UI thread (:meth:`game.host.MiniwindGame._serve_capture`),
as the autosave is; nothing here touches Qt.

It only watches. It creates no events, rolls no dice and changes nothing in
the world.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, List, Optional

from . import provenance

#: Seconds without a blow, roll or kill before an encounter closes.
QUIET_SECONDS = 8.0
#: The score at which an encounter is interesting (``[GAME] encounter_threshold``).
THRESHOLD = 10
#: How many interesting encounters the chronicle keeps.
CHRONICLE_SIZE = 20
#: The session store key the chronicle is kept under.
STORE_KEY = "encounters.chronicle"
#: Roles that are a fight in themselves.
BOSS_ROLES = ("bandit_chief", "wraith", "dragon", "bear")
#: A named foe with this many times its kind's health is a boss too.
BOSS_TOUGHNESS = 1.75
#: Journey kinds that came *for* the player (game/living/journeys.KINDS):
#: bounty hunters, and a faction's raid (which always carries its cause).
SENT_KINDS = ("hunters", "faction_raid")

WEIGHTS = {"foe": 1, "named": 2, "boss": 4, "sent": 6, "half": 2, "quarter": 4,
           "fell": 8, "crit": 1, "fate": 3, "kill": 1, "long": 1, "longer": 2}


class Encounter:
    def __init__(self, now: float, place: str, hour: float, day: int):
        self.started = now
        self.last = now
        self.place = place
        self.when = {"day": int(day), "hour": round(float(hour), 2)}
        self.foes: Dict[str, Dict] = {}      # actor's id -> provenance
        self.events: List[Dict] = []
        self.score = 0
        self.reasons: Dict[str, int] = {}
        self.crits = 0
        self.lowest = 1.0
        self.fell = False
        self.kills: List[str] = []
        self.interesting_at: Optional[float] = None
        self.shots: List[str] = []

    def add(self, reason: str, weight: Optional[int] = None) -> None:
        w = WEIGHTS[reason] if weight is None else weight
        self.score += w
        self.reasons[reason] = self.reasons.get(reason, 0) + w

    def summary(self) -> str:
        names = ", ".join(sorted({f["who"] for f in self.foes.values()})) or "no one"
        # Won only with every foe dead: a dragon left alive in its cave (the
        # player walked out) was "won" too.
        outcome = "won" if self.foes and len(self.kills) >= len(self.foes) else "came away"
        how = "fell" if self.fell else f"{outcome}, down to {int(self.lowest * 100)}% health"
        where = f"At {self.place}" if self.place else "In the wilds"
        return f"{where}: {names}. The player {how}."

    def record(self) -> Dict:
        return {"place": self.place, "when": self.when, "score": self.score,
                "why": self.reasons, "summary": self.summary(),
                "seconds": round(self.last - self.started, 1),
                "lowest_health": round(self.lowest, 3), "fell": self.fell,
                "kills": list(self.kills), "crits": self.crits,
                "foes": list(self.foes.values()),
                "provenance": [provenance.sentence(f) for f in self.foes.values()],
                "events": self.events[-60:], "screenshots": list(self.shots)}


class EncounterRecorder:
    """One per session: watches, scores, keeps the chronicle, asks for shots."""

    def __init__(self, session, clock=time.monotonic):
        self.session = session
        self._clock = clock
        self.current: Optional[Encounter] = None
        self.chronicle: List[Dict] = []
        #: ``(path, why)`` of a screenshot the host should take now, or None.
        self.capture_due = None
        #: Set by the host: ``<the game's root>/saves``.
        self.saves_root = None
        self._folder = None

    # -- persistence --------------------------------------------------------
    def persist(self) -> None:
        """Write the chronicle into the session's store (only when it grows:
        a record is a few kilobytes, too much to dump every second)."""
        store = getattr(self.session, "store", None)
        if store is not None:
            store.set(STORE_KEY, json.dumps(self.chronicle, default=str))

    def restore(self) -> None:
        """Read the chronicle back from the session's store (a new map's
        session, a loaded save)."""
        store = getattr(self.session, "store", None)
        raw = store.get(STORE_KEY, "") if store is not None else ""
        try:
            data = json.loads(raw) if raw and raw != "false" else []
        except (TypeError, ValueError):
            data = []
        if not isinstance(data, list):
            data = []
        self.chronicle = [r for r in data if isinstance(r, dict)][-CHRONICLE_SIZE:]

    # -- settings -----------------------------------------------------------
    def _option(self, key, default):
        config = None
        try:
            config = self.session._editor_config()
        except Exception:
            config = None
        try:
            if config is None:
                return default
            if isinstance(default, bool):
                return config.getboolean("GAME", key, fallback=default)
            return config.getint("GAME", key, fallback=default)
        except Exception:
            return default

    def recording(self) -> bool:
        return bool(self._option("record_encounters", False))

    def threshold(self) -> int:
        return int(self._option("encounter_threshold", THRESHOLD))

    # -- what happened ------------------------------------------------------
    def _player_down(self) -> bool:
        c = getattr(getattr(self.session, "game", None), "character", None)
        return bool(getattr(c, "is_dead", False))

    def _open(self) -> Encounter:
        now = self._clock()
        if self.current is None:
            s = self.session
            ppos = s._player_pos() if hasattr(s, "_player_pos") else None
            place = provenance._place(s, ppos)
            self.current = Encounter(now, place, s.clock.hour, s.clock.day)
        self.current.last = now
        return self.current

    def engage(self, foe) -> None:
        """A blow between the player and *foe*, either way."""
        if foe is None or getattr(foe, "properties", None) is None:
            return
        if self._player_down():
            # Blows landing on the fallen (the rest of the pack, the same
            # monster pass) are the fight that just ended, not a new one.
            return
        enc = self._open()
        key = str(foe.properties.get("id") or id(foe))
        if key in enc.foes:
            return
        prov = provenance.of(self.session, foe)
        enc.foes[key] = prov
        enc.add("foe")
        named = _named(self.session, foe, prov["who"])
        if named:
            enc.add("named")
        if prov.get("role") in BOSS_ROLES or (named and _towers(foe, prov.get("role"))):
            enc.add("boss")
        if prov.get("kind") == "journey" and (prov.get("journey_kind") in SENT_KINDS
                                              or prov.get("cause")):
            enc.add("sent")
        enc.events.append({"t": round(enc.last - enc.started, 2), "what": "engaged",
                           "who": prov["who"], "from": provenance.sentence(prov)})
        self._check()

    def crit(self, by_player: bool) -> None:
        if self._player_down():
            return
        enc = self._open()
        if enc.crits < 4:
            enc.add("crit")
        enc.crits += 1
        enc.events.append({"t": round(enc.last - enc.started, 2),
                           "what": "crit dealt" if by_player else "crit taken"})
        self._check()

    def fate(self, word: str) -> None:
        if self._player_down():
            return
        enc = self._open()
        enc.add("fate")
        enc.events.append({"t": round(enc.last - enc.started, 2), "what": str(word)})
        self._check()

    def kill(self, target) -> None:
        if self.current is None:
            return
        enc = self._open()
        props = getattr(target, "properties", {}) or {}
        who = str(props.get("display_name") or props.get("name") or "something")
        enc.kills.append(who)
        enc.add("kill")
        enc.events.append({"t": round(enc.last - enc.started, 2), "what": "killed", "who": who})
        self._check()

    def health(self, fraction: float) -> None:
        """The player's health, as a share of the most it can be, after a blow."""
        enc = self.current
        if enc is None:
            return
        fraction = max(0.0, float(fraction))
        if fraction < enc.lowest:
            before = enc.lowest
            enc.lowest = fraction
            if before >= 0.5 > fraction:
                enc.add("half")
            if before >= 0.25 > fraction:
                enc.add("quarter")
            if enc.interesting_at is not None:
                self._shoot("lowest")
            self._check()

    def fell(self) -> None:
        enc = self.current
        if enc is None or enc.fell:
            return
        self.health(0.0)
        enc.fell = True
        enc.add("fell")
        enc.events.append({"t": round(self._clock() - enc.started, 2), "what": "the player fell"})
        self._check()
        self._close()

    def tick(self) -> None:
        enc = self.current
        if enc is None:
            return
        length = self._clock() - enc.started
        if length > 30 and "long" not in enc.reasons:
            enc.add("long")
        if length > 90 and "longer" not in enc.reasons:
            enc.add("longer")
        self._check()
        if self._clock() - enc.last > QUIET_SECONDS:
            self._close()

    def close(self) -> None:
        """End the encounter under way, if any (the player leaves the map):
        an interesting one joins the chronicle as it stands."""
        self._close()

    # -- interesting --------------------------------------------------------
    def _check(self) -> None:
        enc = self.current
        if enc is None or enc.interesting_at is not None or enc.score < self.threshold():
            return
        enc.interesting_at = self._clock()
        enc.events.append({"t": round(enc.interesting_at - enc.started, 2),
                           "what": f"became interesting (score {enc.score})"})
        self._shoot("interesting")

    def _shoot(self, why: str) -> None:
        if not self.recording() or self.current is None:
            return
        folder = self._ensure_folder()
        if folder is None:
            return
        shots = self.current.shots
        # One picture of the lowest moment, taken again at each new low (every
        # blow can be one): not a numbered file per blow, most of which the
        # single pending capture would never get to before the next replaced it.
        lowest = next((n for n in shots if n.endswith("-lowest.png")), None) \
            if why == "lowest" else None
        if lowest is None:
            lowest = f"{len(shots) + 1:02d}-{why}.png"
            shots.append(lowest)
        self.capture_due = (os.path.join(folder, lowest), why)

    def _ensure_folder(self):
        if self._folder is None and self.current is not None:
            root = self._saves_root()
            if root is None:
                return None
            stamp = time.strftime("%Y%m%d-%H%M%S")
            place = re.sub(r"[^A-Za-z0-9]+", "-", self.current.place or "wilds").strip("-")
            self._folder = os.path.join(root, "encounters", f"{stamp}-{place}")
            try:
                os.makedirs(self._folder, exist_ok=True)
            except OSError:
                self._folder = None
        return self._folder

    def _saves_root(self):
        """The game's saves folder: the host tells the recorder (it knows the
        window's root); without one, ``saves/`` under the working directory."""
        return self.saves_root or os.path.join(os.getcwd(), "saves")

    def _close(self) -> None:
        enc, self.current = self.current, None
        folder, self._folder = self._folder, None
        if enc is None or enc.interesting_at is None:
            return
        record = enc.record()
        self.chronicle.append(record)
        del self.chronicle[:-CHRONICLE_SIZE]
        if self.recording() and folder is not None:
            path = os.path.join(folder, "encounter.json")
            end_shot = os.path.join(folder, f"{len(enc.shots) + 1:02d}-end.png")
            record["screenshots"].append(os.path.basename(end_shot))
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(record, fh, indent=2)
            except OSError:
                pass
            self.capture_due = (end_shot, "end")
        self.persist()


def _towers(foe, role) -> bool:
    """Whether *foe* has :data:`BOSS_TOUGHNESS` times its kind's health."""
    try:
        from .rpg import bestiary
        tmpl = bestiary.get(str(role or ""))
        props = foe.properties
        health = float(props.get("max_health") or props.get("health") or 0)
    except Exception:
        return False
    return tmpl is not None and health >= BOSS_TOUGHNESS * float(tmpl.health)


def _named(session, foe, who: str) -> bool:
    """Whether *who* is *foe*'s own name rather than what it is (see the
    module's note): checked once per foe per encounter, so a scan is fine."""
    if not who:
        return False
    try:
        from .rpg import bestiary
        if any(tmpl.name == who for tmpl in bestiary.BESTIARY.values()):
            return False
    except Exception:
        pass
    things_of_type = getattr(session, "_things_of_type", None)
    if things_of_type is not None:
        for kind in ("creature", "npc"):
            for other in things_of_type(kind):
                if other is not foe and provenance._name(
                        getattr(other, "properties", {}) or {}) == who:
                    return False
    return True
