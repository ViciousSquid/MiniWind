"""Party quest transactions with stable participant and reward identities."""

from __future__ import annotations

import copy
import json
import threading

from ..rpg import inventory, quests
from ..rpg.character import Character
from ..rpg.game_state import GameState


class QuestError(ValueError):
    pass


def slug(value):
    return "".join(c if c.isalnum() else "_" for c in str(value).lower()).strip("_")


class PlayerStore:
    """Character-local counters, writs and dialogue scratch over one world KV.

    Authored quest.* keys continue to work; personal quest keys resolve for the
    actor speaking. Shared simulation facts stay in the campaign's root store.
    """

    PERSONAL = (
        "kills.",
        "talked.",
        "talk.",
        "disposition.",
        "npc.",
        "law.",
        "writ.",
        "fortune.",
        "resurrect.",
        "killed_by_player.",
        "_character",
        "player_head",
    )

    def __init__(self, store, player_id):
        self.world = store
        self.player_id = player_id

    def key(self, key):
        key = str(key)
        personal = key.startswith(self.PERSONAL)
        if key.startswith("quest."):
            qid = key.split(".", 2)[1]
            q = quests.get(qid)
            personal = q is not None and q.coop_scope == "personal"
        return f"players.{self.player_id}.{key}" if personal else key

    def get(self, key, default="false"):
        return self.world.get(self.key(key), default)

    def set(self, key, value):
        self.world.set(self.key(key), value)

    def all(self):
        return self.world.all()

    @property
    def _name(self):
        return getattr(self.world, "_name", "miniwind")


class PartyQuestLog(quests.QuestLog):
    def __init__(self, service, player_id, store):
        super().__init__(store)
        self.service, self.player_id = service, player_id

    def start(self, qid):
        return self.service.start(qid, self.player_id)

    def complete(self, qid):
        return self.service.complete(qid, self.player_id)

    def set_stage(self, qid, index):
        return self.service.set_stage(qid, index, self.player_id)


class CoopGameState(GameState):
    def __init__(self, service, player_id, character=None, rng=None):
        super().__init__(PlayerStore(service.store, player_id), character, rng)
        self.party_quests = service
        self.player_id = player_id
        self.quests = PartyQuestLog(service, player_id, self.store)

    def complete_quest(self, qid):
        self.party_quests.complete(qid, self.player_id)

    def _count_kill(self, role):
        # Runtime.record_kill supplies an entity identity. Do not also run the
        # single-player's cumulative role counter / hard-coded wolves shortcut.
        pass

    def resolve_spell_on_creature(self, spell, target_props):
        if target_props.get("multiplayer_player"):
            return {"damage": 0.0, "killed": False}
        return super().resolve_spell_on_creature(spell, target_props)


class PartyQuests:
    def __init__(self, store):
        self.store = store
        self.players = {}
        self.lock = threading.RLock()

    def attach(self, player_id, game):
        self.players[player_id] = game
        # A joining player enrols only in currently active shared adventures.
        log = quests.QuestLog(self.store)
        for q in log.active_quests():
            if q.coop_scope == "party":
                self._enrol(q.id, [player_id])

    def import_legacy_progress(self):
        """Retain the active objective's partial progress when copying a solo save."""
        for game in self.players.values():
            for q in game.quests.active_quests():
                stage = q.stage(game.quests.stage_of(q.id))
                if stage is None:
                    continue
                kind = stage.condition_kind()
                prefix = {"kill": "kills.", "talk": "talked.", "visit": "visited."}.get(
                    kind
                )
                if prefix is None:
                    continue
                raw = game.store.get(prefix + slug(stage.condition_target()), "0")
                try:
                    count = int(raw)
                except (ValueError, TypeError):
                    count = int(str(raw).lower() == "true")
                key = f"party.events.{q.id}.{stage.index}"
                if q.coop_scope == "personal":
                    key += "." + game.player_id
                if self.store.get(key, None) is None:
                    self.store.set(
                        key,
                        json.dumps(
                            [
                                f"legacy:{i}"
                                for i in range(
                                    min(stage.condition_count(), max(0, count))
                                )
                            ]
                        ),
                    )

    def _log(self, qid, player_id):
        q = quests.get(qid)
        if q is None:
            raise QuestError("Unknown quest.")
        store = (
            PlayerStore(self.store, player_id)
            if q.coop_scope == "personal"
            else self.store
        )
        return q, quests.QuestLog(store)

    def _members(self, qid):
        try:
            return list(json.loads(self.store.get(f"party.quest.{qid}.members", "[]")))
        except (ValueError, TypeError):
            return []

    def _enrol(self, qid, players):
        self.store.set(
            f"party.quest.{qid}.members",
            json.dumps(sorted(set(self._members(qid)) | set(players))),
        )

    def start(self, qid, player_id):
        with self.lock:
            q, log = self._log(qid, player_id)
            if log.state_of(qid):
                return False
            log.start(qid)
            self._enrol(
                qid, [player_id] if q.coop_scope == "personal" else self.players
            )
            return True

    def set_stage(self, qid, index, player_id):
        with self.lock:
            q, log = self._log(qid, player_id)
            stage = q.stage(int(index))
            if stage is None or not log.is_active(qid):
                return False
            log.store.set(log._key(qid, "stage"), stage.index)
            if stage.finishes:
                self.complete(qid, player_id)
            return True

    def complete(self, qid, player_id):
        with self.lock:
            q, log = self._log(qid, player_id)
            # Never complete an unaccepted quest by replaying a dialogue action.
            if log.state_of(qid) not in ("active", "complete"):
                return False
            members = [player_id] if q.coop_scope == "personal" else self._members(qid)
            if not members:
                return False
            pending = [
                pid
                for pid in members
                if str(self.store.get(self._receipt(qid, pid), "")) != "1"
            ]
            # Persist an entitlement for disconnected campaign characters too;
            # their GameState is retained by the host until the campaign ends.
            for pid in pending:
                game = self.players.get(pid)
                if game is not None:
                    game.grant_quest_rewards(q)
                    self.store.set(self._receipt(qid, pid), "1")
            log.complete(qid)
            return bool(pending)

    @staticmethod
    def _receipt(qid, player_id):
        return f"party.reward.{qid}.{player_id}"

    def record(self, kind, names, event_id, player_id):
        """A unique kill/talk/visit contributes to each relevant active stage."""
        names = {slug(name) for name in names if name}
        with self.lock:
            for q in quests.QUESTS.values():
                if q.coop_scope == "personal":
                    owners = [player_id]
                else:
                    owners = [player_id]  # the one shared log, once per event
                for owner in owners:
                    _, log = self._log(q.id, owner)
                    stage = q.stage(log.stage_of(q.id))
                    if not log.is_active(q.id) or stage is None:
                        continue
                    if (
                        stage.condition_kind() != kind
                        or slug(stage.condition_target()) not in names
                    ):
                        continue
                    key = f"party.events.{q.id}.{stage.index}"
                    if q.coop_scope == "personal":
                        key += f".{owner}"
                    try:
                        seen = set(json.loads(self.store.get(key, "[]")))
                    except (ValueError, TypeError):
                        seen = set()
                    seen.add(str(event_id))
                    self.store.set(key, json.dumps(sorted(seen)))

    def quantity(self, item_id, player_id=None):
        games = (
            [self.players[player_id]]
            if player_id is not None
            else self.players.values()
        )
        carried = sum(inventory.quantity(g.character.inventory, item_id) for g in games)
        return carried + (
            inventory.quantity(self.pouch(), item_id) if player_id is None else 0
        )

    def pouch(self):
        try:
            return json.loads(self.store.get("party.quest_pouch", "[]"))
        except (ValueError, TypeError):
            return []

    def collect_shared_items(self):
        shared = {
            iid
            for q in quests.QUESTS.values()
            if q.coop_scope == "party"
            for iid in q.coop_shared_items
        }
        pouch = self.pouch()
        changed = False
        for game in self.players.values():
            for stack in list(game.character.inventory):
                if stack.get("id") in shared:
                    inventory.add_item(pouch, copy.deepcopy(stack))
                    game.character.inventory.remove(stack)
                    changed = True
        if changed:
            self.store.set("party.quest_pouch", json.dumps(pouch))

    def take(self, item_id, count, player_id=None):
        count = int(count)
        with self.lock:
            if count < 1 or self.quantity(item_id, player_id) < count:
                raise QuestError("The party no longer has all the required items.")
            games = (
                [self.players[player_id]]
                if player_id is not None
                else self.players.values()
            )
            left = count
            if player_id is None:
                pouch = self.pouch()
                left -= inventory.remove_item(pouch, item_id, left)
                self.store.set("party.quest_pouch", json.dumps(pouch))
            for game in games:
                if not left:
                    break
                left -= inventory.remove_item(game.character.inventory, item_id, left)
                if not left:
                    break
            return True

    def condition_met(self, q, stage, player_id):
        kind = stage.condition_kind()
        if kind == quests.COND_FETCH:
            owner = player_id if q.coop_scope == "personal" else None
            return (
                self.quantity(stage.condition_target(), owner)
                >= stage.condition_count()
            )
        if kind == quests.COND_ROLL:
            game = self.players[player_id]
            saved = game.quests.last_roll(q.id)
            if not saved or saved.get("stage") != stage.index:
                return False
            result = saved.get("result") or {}
            if result.get("dice_notation") != stage.condition_notation():
                return False
            target = stage.condition_target_value()
            return (
                bool(result.get("success"))
                if target is None
                else float(result.get("roll_result", 0)) >= target
            )
        if kind not in (quests.COND_KILL, quests.COND_TALK, quests.COND_VISIT):
            return False
        key = f"party.events.{q.id}.{stage.index}"
        if q.coop_scope == "personal":
            key += f".{player_id}"
        try:
            return len(json.loads(self.store.get(key, "[]"))) >= stage.condition_count()
        except (ValueError, TypeError):
            return False

    def tick(self):
        with self.lock:
            done = set()
            for pid, game in self.players.items():
                for q in list(game.quests.active_quests()):
                    if not self._members(q.id):
                        self._enrol(
                            q.id, [pid] if q.coop_scope == "personal" else self.players
                        )
                    key = (q.id, pid if q.coop_scope == "personal" else "party")
                    if key in done:
                        continue
                    done.add(key)
                    stage = q.stage(game.quests.stage_of(q.id))
                    if stage is not None and stage.finishes:
                        self.complete(q.id, pid)
                        continue
                    if stage is None or not self.condition_met(q, stage, pid):
                        continue
                    following = next(
                        (
                            s
                            for s in sorted(q.stages, key=lambda s: s.index)
                            if s.index > stage.index
                        ),
                        None,
                    )
                    if following is None:
                        self.complete(q.id, pid)
                    else:
                        self.set_stage(q.id, following.index, pid)
                for q in game.quests.completed_quests():
                    if self._members(q.id):
                        self.complete(q.id, pid)

    def transaction(self, action):
        """Rollback a failed compound hand-in, including items and receipts."""
        with self.lock:
            before = copy.deepcopy(self.store.all())
            characters = {
                pid: copy.deepcopy(g.character.to_dict())
                for pid, g in self.players.items()
            }
            try:
                return action()
            except Exception:
                current = self.store.all()
                for key in current.keys() - before.keys():
                    # StateStore has no delete surface; an empty value is its
                    # normal representation of a missing authored flag.
                    self.store.set(key, "")
                for key, value in before.items():
                    self.store.set(key, value)
                for pid, data in characters.items():
                    self.players[pid].character = Character.from_dict(data)
                raise
