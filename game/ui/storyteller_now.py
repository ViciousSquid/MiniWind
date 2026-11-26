"""The "Storyteller — what it's doing" window; console ``storyteller``.

A desktop window of its own (a real top-level Qt window: move it to another
monitor, resize it, minimise it) showing :mod:`game.storyteller_report` live:
a badge with the pacing state, then two tabs.

* **Story** -- what the storyteller is doing in plain words: labelled rows
  (Time, State, Why, Sensing, Roads, Weather, Recent); in Dynamic game mode a
  **Dynamic director** section with what the director is doing and every
  decision it took, with its reasons; then the Activity feed (state changes,
  population caps, Studio edits, biased journeys), newest first.
* **Raw** -- the data behind it: the storyteller's ``summary()`` and, in
  Dynamic mode, the director's ``raw()`` (numbers, weights, rejections,
  journey ids), as a key / value table you can select and copy.

The strip along the top collapses the window to just itself (the arrow) and
keeps it above other windows (the drawing pin; :mod:`game.ui.window_strip`).
**Open Studio** opens the full Storyteller Studio for editing. Refreshing it
never samples the storyteller, appraises an actor or draws a random number.
"""

from __future__ import annotations

import html

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                             QTextBrowser, QVBoxLayout, QWidget)

from .. import storyteller_report as report
from .window_strip import WindowStrip

TITLE = "Storyteller — what it's doing"
#: How often the window re-reads the storyteller (milliseconds).
REFRESH_MS = 500

_STYLE = """
QWidget { background: #14171d; color: #e4e6ec; font-size: 10pt; }
QTabWidget::pane { border: 1px solid #2c3340; }
QTabBar::tab { background: #2d323c; color: #e4e6ec; padding: 5px 18px; margin-right: 2px; }
QTabBar::tab:selected { background: #415f7d; }
QTextBrowser, QTableWidget { background: #101318; border: none; }
QHeaderView::section { background: #28303c; color: #96cde1; border: none; padding: 4px; }
QTableWidget { gridline-color: #232a35; selection-background-color: #34506b; }
QPushButton { background: #37414f; border: 1px solid #4a5566; padding: 4px 14px; }
QPushButton:hover { background: #435064; }
"""

_open = []


class StorytellerNowWindow(QWidget):
    """The storyteller's live report in a top-level window (module docstring)."""

    TABS = ("Story", "Raw")

    def __init__(self, view, parent=None):
        super().__init__(parent, Qt.Window)
        self.view = view
        self.setWindowTitle(TITLE)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(_STYLE)
        self.resize(720, 640)
        self.setMinimumSize(420, 300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)
        self.body = QWidget()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(4, 0, 4, 4)
        # The strip: collapse arrow, the state badge and title, the pin.
        self.strip = WindowStrip(self, self.body)
        self.badge = QLabel("—")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(110, 26)
        self.badge.setFont(QFont(self.font().family(), 11, QFont.Bold))
        self.title = QLabel("STORYTELLER")
        self.title.setFont(QFont(self.font().family(), 11, QFont.Bold))
        self.title.setStyleSheet("background: transparent;")
        self.strip.add(self.badge)
        self.strip.add(self.title, 1)
        outer.addWidget(self.strip)
        outer.addWidget(self.body, 1)

        self.tabs = QTabWidget()
        self.story = QTextBrowser()
        self.story.setOpenLinks(False)
        self.raw = QTableWidget(0, 2)
        self.raw.setHorizontalHeaderLabels(["Key", "Value"])
        self.raw.verticalHeader().setVisible(False)
        self.raw.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.raw.horizontalHeader().setStretchLastSection(True)
        self.raw.setColumnWidth(0, 220)
        self.raw.setWordWrap(True)
        self.raw.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.raw.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tabs.addTab(self.story, "Story")
        self.tabs.addTab(self.raw, "Raw")
        self.tabs.currentChanged.connect(lambda _i: self.refresh(force=True))
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.studio_button = QPushButton("Open Studio")
        self.studio_button.clicked.connect(self.open_studio)
        self.note = QLabel("Read-only · live")
        self.note.setStyleSheet("color: #aaafb9;")
        bottom.addWidget(self.studio_button)
        bottom.addWidget(self.note, 1)
        layout.addLayout(bottom)

        self._shown = {}                 # tab -> the content last put up
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_MS)
        self.refresh(force=True)

    # -- what it reads -------------------------------------------------------
    def _session(self):
        return getattr(getattr(self.view, "logic_thread", None), "_miniwind", None)

    def _storyteller(self):
        return getattr(self._session(), "storyteller", None)

    @property
    def tab(self) -> str:
        return self.TABS[self.tabs.currentIndex()]

    @tab.setter
    def tab(self, name):
        self.tabs.setCurrentIndex(self.TABS.index(name))

    def rows(self, tab=None):
        """``(label, text, heading)`` rows of *tab* (the one showing)."""
        story, session = self._storyteller(), self._session()
        if (tab or self.tab) == "Raw":
            return [("", heading, True) if heading else (key, value, False)
                    for heading, key, value in report.raw_rows(story, session)]
        out = [(label, text, False) for label, text in report.rows(story, session, report.SECTIONS[:-1])]
        dynamic = report.dynamic_rows(session)
        if dynamic:
            out.append(("", "Dynamic director · what it decided and why, newest first", True))
            out += [(label, text, False) for label, text in dynamic]
        if story is not None:
            out.append(("", "Activity · newest first", True))
            out += [(label, text, False) for label, text in report.rows(story, session, "activity")]
        return out

    # -- showing it ----------------------------------------------------------
    def refresh(self, force=False):
        story = self._storyteller()
        state = getattr(story, "state", None)
        r, g, b = report.STATE_COLOURS.get(state, (120, 125, 135))
        self.badge.setText(state or "—")
        self.badge.setStyleSheet(f"background: rgb({r},{g},{b}); color: #14161c;")
        self.title.setText("STORYTELLER" if story is None else (
            "STORYTELLER · pacing ON" if story.enabled else "STORYTELLER · pacing OFF (pristine)"))
        tab = self.tab
        rows = self.rows(tab)
        if not force and self._shown.get(tab) == rows:
            return                      # unchanged: keep the reader's place
        self._shown[tab] = rows
        if tab == "Raw":
            self._fill_raw(rows)
        else:
            self._fill_story(rows)

    def _fill_story(self, rows):
        bar = self.story.verticalScrollBar()
        at = bar.value()
        parts = ['<table cellspacing="0" cellpadding="3" width="100%">']
        for label, text, heading in rows:
            if heading:
                parts.append('<tr><td colspan="2" style="background:#28303c; color:#96cde1; '
                             f'font-weight:bold; padding:5px">{html.escape(text)}</td></tr>')
                continue
            dim = label[:4] == "Day " or label == "-"
            colour = "#aaafb9" if dim else "#96cde1"
            parts.append(f'<tr><td valign="top" width="1%" style="color:{colour}; font-weight:bold; '
                         f'white-space:nowrap; padding-right:10px">{html.escape(label)}</td>'
                         f'<td valign="top">{html.escape(text)}</td></tr>')
        parts.append("</table>")
        self.story.setHtml("".join(parts))
        bar.setValue(at)

    def _fill_raw(self, rows):
        bar = self.raw.verticalScrollBar()
        at = bar.value()
        self.raw.clearSpans()
        self.raw.setRowCount(len(rows))
        head_bg, head_fg = QColor(40, 48, 60), QColor(150, 205, 225)
        for i, (key, value, heading) in enumerate(rows):
            if heading:
                item = QTableWidgetItem(value)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setBackground(head_bg)
                item.setForeground(head_fg)
                self.raw.setItem(i, 0, item)
                self.raw.setItem(i, 1, QTableWidgetItem(""))
                self.raw.setSpan(i, 0, 1, 2)
                continue
            k = QTableWidgetItem(key)
            k.setForeground(head_fg)
            self.raw.setItem(i, 0, k)
            self.raw.setItem(i, 1, QTableWidgetItem(value))
        self.raw.resizeRowsToContents()
        bar.setValue(at)

    # -- buttons -------------------------------------------------------------
    def open_studio(self):
        from . import storyteller_window
        storyteller_window.open_storyteller(self.view)

    def closeEvent(self, event):
        self._timer.stop()
        if self in _open:
            _open.remove(self)
        super().closeEvent(event)


def open_now(view, parent=None):
    """Open the window for *view*'s session, or bring the open one forward."""
    session = getattr(getattr(view, "logic_thread", None), "_miniwind", None)
    if getattr(session, "storyteller", None) is None:
        return None
    for win in list(_open):
        try:
            if win.view is view:
                win.show()
                win.raise_()
                win.activateWindow()
                return win
        except RuntimeError:            # deleted on close
            _open.remove(win)
    if not isinstance(parent, QWidget):
        try:
            parent = view.window() if hasattr(view, "window") else None
        except Exception:
            parent = None
    if not isinstance(parent, QWidget):
        parent = None
    win = StorytellerNowWindow(view, parent)
    _open.append(win)
    win.show()
    return win
