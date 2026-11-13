"""Compact party status, independent from the selected character's RPG UI."""

from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPixmap

from ..rpg import heads
from ..ui import hud_frame, theme

#: Each party member's own colour, by party order: four players and up to
#: four AI companions.
COLOURS = ("#69b6ff", "#ffbf69", "#b1e17d", "#d89fff",
           "#ff8f8f", "#6fe0d0", "#f2e36b", "#c4c4cc")
#: Card height and spacing: roomy for up to four, compact beyond.
CARD_H, CARD_STEP = 52, 56
COMPACT_H, COMPACT_STEP = 38, 41
#: A party card's width (px): head, name, health and who plays it.
CARD_WIDTH = 172


def colour_for(coop, player_id):
    """A party member's own colour, ``(r, g, b)`` -- their card's border,
    and their roll boxes' -- or None for anyone not in the party. By party
    order, so every computer gives each player the same colour."""
    for index, pid in enumerate(coop.players):
        if pid == player_id:
            colour = QColor(COLOURS[index % len(COLOURS)])
            return colour.red(), colour.green(), colour.blue()
    return None


def party_rects(width, height, count):
    """A compact left column immediately below the minimap's bronze ring."""
    frame = hud_frame.layout(width, height)
    top = frame.cy + frame.R + 8
    card_width = max(1, min(CARD_WIDTH, width - 24))
    tall, step = (CARD_H, CARD_STEP) if count <= 4 else (COMPACT_H, COMPACT_STEP)
    return [QRectF(12, top + index * step, card_width, tall) for index in range(count)]


def draw_party(event, coop):
    painter = event.get("painter")
    if painter is None:
        return
    view = event.get("viewport")
    if view is not None and not coop._devices_installed:
        from .devices import install

        install(coop, view)
        coop._devices_installed = True
    width = float(event.get("width", 800))
    height = float(event.get("height", 600))
    cards = party_rects(width, height, len(coop.players))
    painter.save()
    painter.setFont(theme.font(9))
    metrics = QFontMetrics(painter.font())
    compact = len(cards) > 4
    for index, context in enumerate(coop.players.values()):
        rect = cards[index]
        x, y, card = rect.x(), rect.y(), rect.width()
        c = context.session.game.character
        painter.setPen(QColor(COLOURS[index % len(COLOURS)]))
        painter.setBrush(QColor(20, 22, 28, 220))
        painter.drawRoundedRect(rect, 5, 5)
        face = 28 if compact else 34
        pix = QPixmap(heads.head_path(context.profile["head"]))
        painter.drawPixmap(int(x + 5), int(y + (rect.height() - face) / 2), face, face, pix)
        tx = x + face + 11
        room = card - (face + 17)
        painter.drawText(
            QRectF(tx, y + 2, room, 17),
            Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(context.profile["name"], Qt.ElideRight, int(room)),
        )
        status = (
            "Disconnected"
            if not context.connected
            else "Down — interact to revive"
            if c.is_dead
            else f"HP {int(c.health)}/{int(c.max_health)}"
        )
        who = (
            context.task or "AI companion"
            if context.bot
            else "This computer"
            if context.owner == coop.lobby.owner
            else "Network player"
        )
        if context.player_id == coop._ui_owner:
            who += " · UI"
        if compact:
            # Two lines: the name, then health and (for AI) who it is.
            status += "  · AI" if context.bot else ""
        painter.setPen(QColor("#eeeeee"))
        painter.drawText(
            QRectF(tx, y + 18, room, 16), Qt.AlignLeft | Qt.AlignVCenter,
            metrics.elidedText(status, Qt.ElideRight, int(room)),
        )
        if not compact:
            painter.setPen(QColor("#adb4c3"))
            painter.drawText(
                QRectF(tx, y + 33, room, 16), Qt.AlignLeft | Qt.AlignVCenter,
                metrics.elidedText(who, Qt.ElideRight, int(room)),
            )
    if coop.paused:
        painter.setPen(QColor("#ffde95"))
        painter.drawText(
            QRectF(0, 90, width, 30), Qt.AlignCenter, "Party paused by host"
        )
    if coop.disconnected:
        painter.setPen(QColor("#ffbf69"))
        painter.setBrush(QColor(15, 18, 25, 235))
        painter.drawRoundedRect(QRectF(width * 0.15, 110, width * 0.7, 100), 6, 6)
        painter.drawText(
            QRectF(width * 0.18, 120, width * 0.64, 80),
            Qt.AlignCenter | Qt.TextWordWrap,
            "The host disconnected. This session has ended. Your character is kept in the host's campaign save. Press Esc to leave.",
        )
    if coop.travel is not None:
        painter.setPen(QColor("#ffde95"))
        painter.drawText(
            QRectF(0, 120, width, 28),
            Qt.AlignCenter,
            "Party travel — press interact when ready",
        )
    pouch = coop.party_quests.pouch()
    if pouch:
        painter.setPen(QColor("#e7d6a2"))
        contents = ", ".join(
            f"{s.get('qty', 1)} {s.get('name') or s.get('id', 'item')}" for s in pouch
        )
        painter.drawText(
            QRectF(12, cards[-1].bottom() + 6 if cards else 84, width - 24, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Party quest pouch: " + contents,
        )
    painter.restore()
