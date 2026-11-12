"""The overhead view's actors as a game draws them: the player's head (one
still image a game may choose), what the player and every nearby actor holds,
and a co-op party's held items -- batched into one draw per depth state
(``OverheadSpriteRenderer.begin``). Held by the view as ``view.overhead``;
its state stays on the view (the overhead sprite renderer and controller).

A game session (``logic.game_session``) drives it through duck-typed hooks:
``overhead_pose() -> (armed, attacking)``, ``overhead_player_flash() ->
seconds``, ``overhead_player_weapon() -> (weapon_id, handed)`` or a list of
``(weapon_id, handed[, attacking[, facing_offset[, block]]])``,
``overhead_actor_weapons() -> [(pos, facing, item, handed, attacking,
size[, block])]`` and ``overhead_weapon_kind(weapon_id) -> "melee" | "bow" |
"staff"``. With no game session, Fio's stock player sprite is drawn instead
(:meth:`QtGameView._draw_overhead_sprite`).
"""

import os
import time

from editor.debug_console import debug_log

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ViewOverhead:
    #: weapon id -> its overhead icon path ("" for none); the files are
    #: shipped assets, looked up once per id rather than once per frame.
    _WEAPON_ASSET_PATHS = {}

    def __init__(self, view):
        self.view = view

    def draw(self, render_state) -> bool:
        """Draw the frame's overhead actors as the game describes them; False
        (nothing drawn) when no game drives them."""
        view = self.view
        lt = view.logic_thread
        session = getattr(lt, "game_session", None)
        head_rel = getattr(lt, "player_head_sprite", None)
        if session is None and not head_rel:
            return False
        from engine.overhead_sprite import SpriteController, OverheadSpriteRenderer
        coop = getattr(session, "coop", None)
        # A game can replace the player's look with one still image
        # (``logic.player_head_sprite``, a repo-relative path): every frame maps
        # to it, and the renderer is rebuilt whenever it changes.
        if coop is None and head_rel and head_rel != getattr(view, "_overhead_head", None):
            head_abs = os.path.join(_ROOT, head_rel)
            frames = {k: head_abs for k in (
                SpriteController.IDLE, SpriteController.WALK_A, SpriteController.WALK_B,
                SpriteController.IDLE_G, SpriteController.WALK_A_G,
                SpriteController.WALK_B_G, SpriteController.SHOOT)}
            view._overhead_sprite_renderer = OverheadSpriteRenderer(
                frame_files=frames, size=float(view.overhead_sprite_size),
                facing_offset_deg=float(view.overhead_sprite_facing_offset))
            view._overhead_head = head_rel
        if view._overhead_sprite_renderer is None:
            view._overhead_sprite_renderer = OverheadSpriteRenderer(
                size=float(view.overhead_sprite_size),
                facing_offset_deg=float(view.overhead_sprite_facing_offset))
        # Every head, weapon and torch of the frame goes to the GPU together.
        renderer = view._overhead_sprite_renderer
        begin = getattr(renderer, "begin", None)    # a stand-in may not batch
        batching = bool(begin) and begin(view.projection_matrix, view.view_matrix)
        try:
            self._draw_actors(render_state, session, coop)
        finally:
            if batching:
                renderer.end()
        return True

    def _draw_actors(self, render_state, sess, coop):
        from engine.overhead_sprite import SpriteController
        view = self.view
        if coop is not None:
            # Co-op heads already use published actor sprites. Their held
            # equipment still needs the same overlay used in solo play.
            self._draw_actor_weapons(sess)
            return
        if view._overhead_sprite_ctrl is None:
            view._overhead_sprite_ctrl = SpriteController(walk_fps=float(view.overhead_walk_fps))
        pos = render_state.player_pos
        if pos is None:
            return
        try:
            gpos = (float(pos.x), float(pos.y), float(pos.z))
        except AttributeError:
            gpos = (float(pos[0]), float(pos[1]), float(pos[2]))
        angle = float(render_state.player_angle)
        armed = bool(render_state.active_weapon)
        shooting = bool(render_state.muzzle_flash_active)
        pose = getattr(sess, "overhead_pose", None)
        if pose is not None:
            try:
                armed, shooting = pose()
            except Exception:
                pass
        ctrl = view._overhead_sprite_ctrl
        ctrl.update(gpos, angle, time.perf_counter(), armed=armed, shooting=shooting)
        flash = 0.0
        flash_fn = getattr(sess, "overhead_player_flash", None)
        if flash_fn is not None:
            try:
                flash = float(flash_fn() or 0.0)
            except Exception:
                flash = 0.0
        tint = (1.0, 0.15, 0.1, min(0.8, flash * 4.0)) if flash > 0 else (0.0, 0.0, 0.0, 0.0)
        renderer = view._overhead_sprite_renderer
        renderer.draw(view.projection_matrix, view.view_matrix, gpos,
                      ctrl.facing, ctrl.frame(), tint=tint)
        held = getattr(sess, "overhead_player_weapon", None)
        if held is None:
            return
        try:
            in_hands = held()
            if in_hands and isinstance(in_hands[0], str):
                in_hands = [in_hands]
        except Exception as exc:
            debug_log("Error", f"overhead_player_weapon failed: {exc}")
            return
        now = time.perf_counter()
        for entry in in_hands or ():
            weapon_id, handed = entry[0], entry[1]
            weapon_path = self.weapon_asset_path(weapon_id)
            if not weapon_path:
                continue
            facing = ctrl.facing
            if len(entry) > 3:
                facing += float(entry[3] or 0.0)
            renderer.draw_weapon(
                view.projection_matrix, view.view_matrix, gpos, facing, weapon_path,
                now, attacking=bool(entry[2]) if len(entry) > 2 else shooting,
                weapon_kind=self.weapon_kind(weapon_id, sess), handed=handed,
                block=float(entry[4] or 0.0) if len(entry) > 4 else 0.0)
        self._draw_actor_weapons(sess)

    def _draw_actor_weapons(self, sess):
        """Nearby actors' held items, every co-op character's included."""
        others = getattr(sess, "overhead_actor_weapons", None)
        if others is None:
            return
        try:
            held_list = others() or ()
        except Exception as exc:
            debug_log("Error", f"overhead_actor_weapons failed: {exc}")
            return
        view = self.view
        renderer = view._overhead_sprite_renderer
        now = time.perf_counter()
        player_size = max(1.0, float(view.overhead_sprite_size))
        for entry in held_list:
            a_pos, a_facing, a_weapon, a_handed, a_attacking, a_size = entry[:6]
            path = self.weapon_asset_path(a_weapon)
            if not path:
                continue
            renderer.draw_weapon(
                view.projection_matrix, view.view_matrix, a_pos, a_facing, path,
                now, attacking=a_attacking,
                weapon_kind=self.weapon_kind(a_weapon, sess),
                size=player_size * 0.55 * (a_size / player_size),
                handed=a_handed,
                block=float(entry[6] or 0.0) if len(entry) > 6 else 0.0)

    @classmethod
    def weapon_asset_path(cls, weapon_id):
        """A held weapon's transparent overhead icon: assets/sprites/items/<id>.png."""
        if not weapon_id:
            return ""
        cached = cls._WEAPON_ASSET_PATHS.get(weapon_id)
        if cached is None:
            path = os.path.join(_ROOT, "assets", "sprites", "items", f"{weapon_id}.png")
            cached = cls._WEAPON_ASSET_PATHS[weapon_id] = (
                path if os.path.isfile(path) else "")
        return cached

    @staticmethod
    def weapon_kind(weapon_id, session=None):
        """``"melee"``, ``"bow"`` or ``"staff"``, for the weapon's attack animation.

        The game session's ``overhead_weapon_kind`` answers first; for an id it
        does not know, or with no game, a name heuristic keeps it sensible.
        """
        kind_fn = getattr(session, "overhead_weapon_kind", None)
        if kind_fn is not None:
            try:
                kind = kind_fn(weapon_id)
                if kind in ("melee", "bow", "staff"):
                    return kind
            except Exception:
                pass
        wid = str(weapon_id or "").lower()
        if "bow" in wid:
            return "bow"
        if "staff" in wid or "wand" in wid:
            return "staff"
        return "melee"
