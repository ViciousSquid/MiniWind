"""Container locks use existing inventory and save paths; looking is free."""

from . import fio
from .rpg import inventory as inv
from .rpg import lockpicking
from engine.change_journal import touch


class ContainerLocks:
    def lockpick_count(self):
        return inv.quantity(self.game.character.inventory, "lockpick")

    def open_locked_container(self, thing):
        props = thing.properties
        if self._dist2d(self._player_pos(), thing.pos) > float(props.get("use_radius", 120.0)):
            self.notify("Move closer to the lock.")
            return False
        key = str(props.get("key_id", "") or "").strip()
        if key and inv.has_item(self.game.character.inventory, key):
            self._unlock_container(thing)
            self.notify("You unlock it with the key.")
            return self.open_container(thing)
        if not props.get("pickable", True):
            self.notify("This lock requires its key." if key else "This lock cannot be picked.")
            return False
        if not self.lockpick_count():
            self.notify("Locked. You need a lockpick" + (" or the key." if key else "."))
            return False
        if self.lockpick_target is thing and self.lockpicking is not None:
            return True
        self.cancel_lockpicking()
        self.container_thing = None
        self.lockpick_target = thing
        self.lockpicking = lockpicking.Lockpick(
            props.get("lock_difficulty", 25), self.game.character.skill("security"), self.rng,
            getattr(self, "_last_lockpick_break_style", None))
        self.open_screen = "lockpick"
        return True

    @staticmethod
    def _unlock_container(thing):
        thing.properties["locked"] = False
        touch(thing)

    def _lockpick_valid(self):
        target = self.lockpick_target
        return (target is not None and not self.game.character.is_dead
                and target in fio.things(self.logic)
                and self._dist2d(self._player_pos(), target.pos) <=
                float(target.properties.get("use_radius", 120.0)))

    def tick_lockpicking(self, seconds):
        attempt, target = self.lockpicking, self.lockpick_target
        if attempt is None or self.open_screen != "lockpick":
            return
        if not self._lockpick_valid():
            self.cancel_lockpicking()
            return
        if not target.properties.get("locked"):
            self.cancel_lockpicking()
            self.open_container(target)
            return
        if self.lockpick_count() <= 0 and not attempt.broken:
            self.notify("You have no lockpicks left.")
            self.cancel_lockpicking()
            return
        if attempt.update(seconds):
            self.play_ui_sound("lock_pin.wav", 0.4)

    def lockpick_action(self, action, index=None, height=None):
        attempt = self.lockpicking
        if attempt is None or self.open_screen != "lockpick":
            return
        if not self._lockpick_valid():
            self.cancel_lockpicking()
            return
        if self.lockpick_count() <= 0:
            return
        if not self.lockpick_target.properties.get("locked"):
            target = self.lockpick_target
            self.cancel_lockpicking()
            self.open_container(target)
            return
        if action == "select":
            attempt.select(index, height)
        elif action == "lift":
            attempt.lift()
        elif action == "set":
            result = attempt.set_pin()
            if result == "broken":
                self._last_lockpick_break_style = attempt.break_style
                inv.remove_item(self.game.character.inventory, "lockpick", 1)
                self.play_ui_sound("lock_break.wav", 0.45)
                if self.lockpick_count():
                    self.notify("Your lockpick snapped.")
                else:
                    self.notify("Your last lockpick snapped.")
                    attempt.message = "Last lockpick broken. Find more lockpicks to continue."
            elif result == "opened":
                target = self.lockpick_target
                self._unlock_container(target)
                self.game.character.use_skill("security", 1.0 + attempt.difficulty / 25.0)
                self.cancel_lockpicking()
                self.open_container(target)
                self.notify("The lock yields.")
                self.play_ui_sound("lock_set.wav", 0.55)
            elif result == "set":
                self.play_ui_sound("lock_set.wav", 0.4)

    def cancel_lockpicking(self):
        self.lockpicking = None
        self.lockpick_target = None
        if self.open_screen == "lockpick":
            self.open_screen = None
