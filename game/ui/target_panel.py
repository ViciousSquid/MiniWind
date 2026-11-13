"""
The target panel: who you are fighting, bottom right of the screen.

It shows the enemy you last attacked, or the one attacking you: a portrait,
the name, their Armour Class and your chance to hit, and one thin bar -- red
health, blue armour (AC above 10, display only), and a gold sliver for the
damage just done, draining away. It fades in when a fight starts, and fades
out when the enemy is killed (after a moment of SLAIN), runs away, or there
has been no fighting for a while.

It shares the bottom row with the shortcut bar and never overlaps it or
stacks above it: it narrows to fit beside the bar, moves to the bar's other
side when the bar has been dragged into its corner, and only when even its
narrowest will not fit does the bar make room (:func:`bar_nudge`).

EVERY NUMBER TO TWEAK IS IN THE BLOCK BELOW.
"""

from __future__ import annotations

import math
import os
import time
from typing import Optional

# ============================================================== tweak these
# -- timing (seconds) --
FADE_IN_SECONDS = 1.0        # appearing when a fight starts
FADE_OUT_SECONDS = 1.0       # disappearing
SWAP_SECONDS = 0.25          # changing to another enemy while shown
IDLE_TIMEOUT = 6.0           # no fighting this long -> fade out
SLAIN_HOLD = 1.0             # "SLAIN" shows this long before fading
SWITCH_QUIET_SECONDS = 2.0   # your target quiet this long before an attacker takes over
DAMAGE_DRAIN_SECONDS = 0.5   # the gold damage sliver drains away
DAMAGE_DRAIN_DELAY = 0.2     # ... after holding this long
# -- running away --
FLED_DISTANCE = 1500.0       # this far from you (world units) -> they ran
# -- size and place (pixels) --
PANEL_WIDTH = 300            # full width
PANEL_MIN_WIDTH = 180        # narrowest with the name shown
PANEL_COMPACT_WIDTH = 120    # narrowest at all (portrait, odds and bar)
PANEL_HEIGHT = 54
PANEL_MARGIN = 18            # from the screen's edges
BAR_SPACING = 12             # gap between it and the shortcut bar
SCREEN_EDGE = 16             # the shortcut bar never pushed closer than this
HEALTH_BAR_HEIGHT = 6
PORTRAIT = 42
NAME_PX = 15                 # the enemy's name (MedievalSharp)
INFO_PX = 12                 # AC and chance to hit (Texturina Light, never under 11)
# -- the bar --
ARMOUR_PER_AC = 0.03         # blue: share of the bar per AC point above 10 ...
ARMOUR_MAX_SHARE = 0.30      # ... up to this much
# -- colours (r, g, b[, a]) --
BACKGROUND = (16, 15, 24, 228)
EDGE = (150, 122, 64, 230)
NAME_INK = (238, 104, 88)
INFO_INK = (170, 166, 184)
HEALTH = ((228, 84, 72), (156, 40, 36))       # top, bottom of the gradient
ARMOUR = ((110, 160, 235), (52, 92, 170))
DAMAGE = (240, 200, 120)
BAR_BACK = (38, 20, 22)
# ===========================================================================


def _now() -> float:
    return time.monotonic()


def _health(props):
    try:
        hp = float(props.get("health", 0) or 0)
    except (TypeError, ValueError):
        hp = 0.0
    try:
        top = float(props.get("_max_health") or props.get("max_health") or 0)
    except (TypeError, ValueError):
        top = 0.0
    return hp, max(top, hp, 1.0)


def _dead(props) -> bool:
    return bool(props.get("dead")) or _health(props)[0] <= 0


class TargetTracker:
    """Who the panel shows and how visible it is. The game tells it of every
    blow between the player and anyone (:meth:`note`); the HUD asks it what to
    draw (:meth:`view`)."""

    def __init__(self):
        self.target = None
        self.shown_at = None        # when it began fading in (or swapping)
        self.swapped = False        # the last change was a swap, not a fade-in
        self.last_combat = None     # the last blow between you and anyone
        self.last_exchange = None   # the last blow between you and the target
        self.ended_at = None        # when its fade-out began
        self.killed_at = None
        self._ghost = None          # (from_health, since)
        self._seen_health = None

    def note(self, thing, by_player: bool, now: Optional[float] = None) -> None:
        """A blow between the player and *thing* -- *by_player* when the
        player struck (or swung at) it, else it struck the player. Your own
        attack always takes the panel; an attacker takes it only when there
        is no target or yours has been quiet for SWITCH_QUIET_SECONDS."""
        props = getattr(thing, "properties", None)
        if not isinstance(props, dict):
            return
        now = _now() if now is None else now
        self.last_combat = now
        showing = self.target is not None and self.ended_at is None
        if thing is self.target:
            self.last_exchange = now
            return
        quiet = (self.last_exchange is None
                 or now - self.last_exchange >= SWITCH_QUIET_SECONDS)
        if by_player or not showing or quiet:
            self.swapped = showing
            self.target = thing
            self.shown_at = now
            self.last_exchange = now
            self.ended_at = self.killed_at = None
            self._ghost = None
            self._seen_health = _health(props)[0]

    def clear(self) -> None:
        self.__init__()

    def view(self, player_pos=None, now: Optional[float] = None):
        """What to draw now, or None: ``{"thing", "alpha", "slain", "health",
        "top", "ghost"}`` -- alpha 0..1."""
        if self.target is None:
            return None
        now = _now() if now is None else now
        props = getattr(self.target, "properties", None) or {}
        hp, top = _health(props)
        slain = _dead(props)
        if self.ended_at is None:
            if slain:
                if self.killed_at is None:
                    self.killed_at = now
                if now - self.killed_at >= SLAIN_HOLD:
                    self.ended_at = self.killed_at + SLAIN_HOLD
            elif self.last_combat is not None and now - self.last_combat >= IDLE_TIMEOUT:
                self.ended_at = self.last_combat + IDLE_TIMEOUT
            elif player_pos is not None and self._far(player_pos):
                self.ended_at = now
        alpha = 1.0
        if self.shown_at is not None:
            rise = SWAP_SECONDS if self.swapped else FADE_IN_SECONDS
            alpha = min(1.0, (now - self.shown_at) / max(0.01, rise))
        if self.ended_at is not None:
            fall = 1.0 - (now - self.ended_at) / max(0.01, FADE_OUT_SECONDS)
            if fall <= 0.0:
                self.target = None
                return None
            alpha = min(alpha, fall)
        # The gold sliver: health lost holds, then drains away.
        if self._seen_health is not None and hp < self._seen_health:
            start = self._seen_health if self._ghost is None else self._ghost_value(now)
            self._ghost = (start, now)
        self._seen_health = hp
        ghost = self._ghost_value(now) if self._ghost is not None else hp
        if ghost <= hp:
            self._ghost = None
            ghost = hp
        return {"thing": self.target, "alpha": max(0.0, alpha), "slain": slain,
                "health": max(0.0, hp), "top": top, "ghost": max(0.0, ghost)}

    def _ghost_value(self, now):
        start, since = self._ghost
        hp = _health(getattr(self.target, "properties", None) or {})[0]
        t = now - since - DAMAGE_DRAIN_DELAY
        if t <= 0:
            return start
        p = min(1.0, t / max(0.01, DAMAGE_DRAIN_SECONDS))
        return start + (hp - start) * p

    def _far(self, player_pos) -> bool:
        pos = getattr(self.target, "pos", None)
        if pos is None:
            return False
        return math.hypot(float(pos[0]) - float(player_pos[0]),
                          float(pos[2]) - float(player_pos[2])) > FLED_DISTANCE


# ------------------------------------------------------------------ layout
def bar_nudge(view_w, bar_x, bar_w) -> int:
    """How far left the shortcut bar must move so the panel fits beside it at
    its narrowest: 0 when it already does (it never moves for the panel
    otherwise), and never closer than SCREEN_EDGE to the left edge."""
    room = view_w - PANEL_MARGIN - BAR_SPACING - (bar_x + bar_w)
    if room >= PANEL_MIN_WIDTH:
        return 0
    return int(min(bar_x - SCREEN_EDGE, PANEL_MIN_WIDTH - room))


def place(view_w, view_h, bar=None):
    """The panel's ``(x, y, width, compact)`` on the bottom row: right of the
    shortcut bar *bar* ``(x, y, w, h)`` if its narrowest fits there, else left
    of it, else the roomier side in compact form; with no bar on the bottom
    row, bottom right at full width."""
    y = view_h - PANEL_MARGIN - PANEL_HEIGHT
    if bar is None or bar[1] + bar[3] < y:
        return view_w - PANEL_MARGIN - PANEL_WIDTH, y, PANEL_WIDTH, False
    bx, _by, bw, _bh = bar
    right = view_w - PANEL_MARGIN - BAR_SPACING - (bx + bw)
    left = bx - BAR_SPACING - PANEL_MARGIN
    if right >= PANEL_MIN_WIDTH:
        w = min(PANEL_WIDTH, right)
        return view_w - PANEL_MARGIN - w, y, w, False
    if left >= PANEL_MIN_WIDTH:
        return PANEL_MARGIN, y, min(PANEL_WIDTH, left), False
    if right >= left:
        w = max(PANEL_COMPACT_WIDTH, right)
        return view_w - PANEL_MARGIN - w, y, w, True
    return PANEL_MARGIN, y, max(PANEL_COMPACT_WIDTH, left), True


def odds_text(character, props) -> str:
    """Your chance against the target: "To hit: 8+ (65%)", or "To cast: ..."
    for a readied spell; "" when there is nothing to roll."""
    try:
        import game.rpg.combat as combat
        import game.rpg.magic as magic
        import game.rpg.items as items
        from ..diceroll import check_target
        kind = getattr(character, "active_weapon_kind", "")
        if kind == "spell":
            spell = magic.get(getattr(character, "active_spell", "") or "")
            if spell is None or spell.base_cost <= 0:
                return ""
            chance = magic.cast_chance(character, spell)
            return f"To cast: {check_target(chance)}+ ({chance * 100:.0f}%)"
        if kind == items.KIND_STAFF:
            return ""
        odds = combat.attack_odds(character, props)
        return f"To hit: {odds['hit_target']}+ ({odds['hit_chance'] * 100:.0f}%)"
    except Exception:
        return ""


# ----------------------------------------------------------------- drawing
_portraits = {}


def _portrait(props, size):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap
    path = props.get("custom_idle") or ""
    if not path:
        try:
            import game.rpg.heads as heads
            head = props.get("head") or ""
            path = heads.any_head_path(head) if head else ""
        except Exception:
            path = ""
    key = (path, size)
    if key not in _portraits:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pm = QPixmap(os.path.join(root, path)) if path else QPixmap()
        _portraits[key] = (pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                           if not pm.isNull() else None)
    return _portraits[key]


def draw(painter, session, width, height, bar_rect=None, now=None) -> None:
    """Draw the panel for *session*'s tracker, beside the shortcut bar at
    *bar_rect* (a QRect, or None when it is not on screen)."""
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainterPath, QPen
    tracker = getattr(session, "target_panel", None)
    if tracker is None:
        return
    try:
        ppos = session._player_pos()
    except Exception:
        ppos = None
    v = tracker.view(ppos, now)
    if v is None or v["alpha"] <= 0.0:
        return
    props = getattr(v["thing"], "properties", None) or {}
    bar = None
    if bar_rect is not None:
        bar = (bar_rect.x(), bar_rect.y(), bar_rect.width(), bar_rect.height())
    x, y, w, compact = place(width, height, bar)
    h = PANEL_HEIGHT
    painter.save()
    painter.setOpacity(v["alpha"])
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setPen(QPen(QColor(*EDGE), 1.5))
    painter.setBrush(QColor(*BACKGROUND))
    painter.drawRoundedRect(QRectF(x, y, w, h), 8, 8)
    # Portrait.
    p = PORTRAIT
    ring = QRectF(x + 7, y + (h - p) / 2.0, p, p)
    painter.setPen(QPen(QColor(90, 80, 60), 1))
    painter.setBrush(QColor(30, 28, 36))
    painter.drawEllipse(ring)
    pm = _portrait(props, p)
    if pm is not None:
        clip = QPainterPath()
        clip.addEllipse(ring)
        painter.save()
        painter.setClipPath(clip)
        painter.drawPixmap(int(ring.x() + (p - pm.width()) / 2),
                           int(ring.y() + (p - pm.height()) / 2), pm)
        painter.restore()
    tx, tw = x + p + 16, w - p - 28
    # Name (left) and Armour Class (right); compact: just the odds.
    try:
        import game.rpg.armour_class as ac_rules
        ac = ac_rules.of(props)
    except Exception:
        ac = 10
    odds = "" if v["slain"] else odds_text(session.game.character, props)
    from . import fonts
    small = fonts.small_font(INFO_PX, bold=True)      # Texturina Light, >= 11px
    if not compact:
        name = fonts.dialogue_font_px(NAME_PX)        # names in MedievalSharp
        painter.setFont(small)
        info = "SLAIN" if v["slain"] else f"AC {ac}"
        info_w = painter.fontMetrics().horizontalAdvance(info) + 6
        painter.setFont(name)
        painter.setPen(QColor(*NAME_INK))
        label = str(props.get("display_name") or props.get("name") or "Foe")
        label = painter.fontMetrics().elidedText(label, Qt.ElideRight, int(max(10, tw - info_w)))
        painter.drawText(QRectF(tx, y + 5, tw, 18), int(Qt.AlignLeft | Qt.AlignVCenter), label)
        painter.setFont(small)
        painter.setPen(QColor(*INFO_INK))
        painter.drawText(QRectF(tx, y + 5, tw, 18), int(Qt.AlignRight | Qt.AlignVCenter), info)
    # The bar: red health, blue armour, gold for damage just done.
    by = y + (27 if not compact else 20)
    bh = HEALTH_BAR_HEIGHT
    armour = min(ARMOUR_MAX_SHARE, max(0, ac - 10) * ARMOUR_PER_AC)
    hw = tw * (1.0 - armour)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(*BAR_BACK))
    painter.drawRoundedRect(QRectF(tx, by, tw, bh), 3, 3)
    top = v["top"]
    if v["ghost"] > v["health"]:
        painter.setBrush(QColor(*DAMAGE))
        painter.drawRect(QRectF(tx, by, hw * v["ghost"] / top, bh))
    if v["health"] > 0:
        g = QLinearGradient(0, by, 0, by + bh)
        g.setColorAt(0, QColor(*HEALTH[0]))
        g.setColorAt(1, QColor(*HEALTH[1]))
        painter.setBrush(QBrush(g))
        painter.drawRect(QRectF(tx, by, hw * v["health"] / top, bh))
    if armour > 0:
        g = QLinearGradient(0, by, 0, by + bh)
        g.setColorAt(0, QColor(*ARMOUR[0]))
        g.setColorAt(1, QColor(*ARMOUR[1]))
        painter.setBrush(QBrush(g))
        painter.drawRect(QRectF(tx + hw + 1, by, tw - hw - 1, bh))
    painter.setPen(QPen(QColor(0, 0, 0, 170), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRectF(tx, by, tw, bh), 3, 3)
    # Your chance, under the bar.
    if odds or (compact and v["slain"]):
        painter.setFont(small)
        painter.setPen(QColor(*INFO_INK))
        text = ("SLAIN" if v["slain"] else
                (f"AC {ac}  ·  {odds}" if compact else odds))
        painter.drawText(QRectF(tx, by + bh + 2, tw, 16),
                         int(Qt.AlignLeft | Qt.AlignVCenter), text)
    painter.restore()
