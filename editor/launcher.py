"""
The MiniWind launcher — the first window after the splash screen.

MiniWind is both a game and the editor that builds it, so launch asks which one
you came for, and lets you set up the display before either starts. It is
deliberately small: a banner, three display controls, and two buttons.

Everything it changes is written straight back to ``settings.ini`` — the same
file, the same keys, the same section names the Settings window uses — so the
launcher and Settings ▸ Display never disagree, and a choice made here is still
there next launch.

* **PLAY** starts the game fullscreen (or however the display mode says),
  hiding the editor UI — the existing kiosk mode.
* **EDIT** opens the editor exactly as it always did.

Dismissing the launcher any other way means Edit: the editor is the safe answer
to a question nobody answered.
"""

from __future__ import annotations

import configparser
import os

from PyQt5.QtCore import QPoint, QRectF, QSize, Qt
from PyQt5.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient,
                         QPainter, QPen, QPixmap)
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QFormLayout, QFrame, QHBoxLayout, QLabel,
                             QPushButton, QSizePolicy, QVBoxLayout, QWidget)

PLAY = "play"
EDIT = "edit"
QUIT = "quit"

#: Display modes, as ``(settings.ini value, label, explanation)``. The stored
#: values are the ones ``[Kiosk] window_mode`` already used, so an existing
#: settings.ini keeps working and the Settings window agrees.
MODES = [
    ("Fullscreen", "Fullscreen",
     "The game takes over the whole screen."),
    ("Borderless", "Fullscreen borderless",
     "The game fills the screen with no frame — easy to alt-tab out of."),
    ("Windowed", "Windowed",
     "The game runs in a normal window at the resolution above."),
]

#: Offered window sizes. Anything larger than the current screen is filtered
#: out at build time, and whatever is already in settings.ini is always offered
#: even if it is not on this list.
RESOLUTIONS = [
    (1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440),
    (3440, 1440), (3840, 2160),
]

#: What "Reset to defaults" restores. These match the fallbacks every reader of
#: settings.ini already uses, so resetting is the same as never having set them.
DEFAULTS = {
    "window_mode": "Fullscreen",
    "res_width": 1280,
    "res_height": 720,
    "vsync": True,
    "high_dpi_scaling": False,
}

#: Where the project lives, linked from the launcher footer.
PROJECT_URL = "https://github.com/ViciousSquid/MiniWind"

_ACCENT = "#C41E3A"
_PLAY_GREEN = "#2E7D32"

# --- sizing ---------------------------------------------------------------
# Every dimension in the launcher is a multiple of one text line, measured from
# the application font. That is what makes it DPI-aware the same way the rest of
# the editor is (see the note above WIZARD_STYLE in editor/logic_wizard.py):
# there is no font-size in pixels anywhere, so the launcher grows with the OS's
# display scaling *and* with the user's own font_size setting, instead of
# turning into a postage stamp on a 4K panel.
_BANNER_LINES = 9.0        # banner height, in text lines
_WIDTH_LINES = 31.0        # launcher width, in text lines
_BUTTON_W_LINES = 7.3
_BUTTON_H_LINES = 2.3
_TITLE_SCALE = 2.6         # banner title, relative to the base font
_SMALL_SCALE = 0.85        # captions and section headings


def text_unit(widget) -> float:
    """One line of the widget's font, in device-independent pixels."""
    return max(1.0, QFontMetricsF(widget.font()).height())


def read_version(root_dir: str = ".") -> str:
    """The build string from ``editor/version.txt``, or ``""`` if unreadable.

    The file is the single source of truth the splash's version print already
    uses, so the launcher never carries a version of its own to fall behind."""
    try:
        with open(os.path.join(root_dir, "editor", "version.txt")) as f:
            return f.read().strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# settings.ini
# ---------------------------------------------------------------------------
class DisplaySettings:
    """The launcher's slice of ``settings.ini``, read and written in place.

    Only the four keys the launcher shows are touched; every other section and
    value in the file is preserved exactly as configparser found it, so the
    launcher can never clobber a setting it does not know about."""

    def __init__(self, path: str = "settings.ini"):
        self.path = path
        self.config = configparser.ConfigParser()
        self.config.read(path)

    # -- read ------------------------------------------------------------
    @property
    def mode(self) -> str:
        value = str(self.config.get("Kiosk", "window_mode",
                                    fallback=DEFAULTS["window_mode"])).strip()
        known = {v.lower(): v for v, _l, _h in MODES}
        return known.get(value.lower(), DEFAULTS["window_mode"])

    @property
    def resolution(self):
        try:
            return (self.config.getint("Kiosk", "res_width",
                                       fallback=DEFAULTS["res_width"]),
                    self.config.getint("Kiosk", "res_height",
                                       fallback=DEFAULTS["res_height"]))
        except ValueError:
            return DEFAULTS["res_width"], DEFAULTS["res_height"]

    @property
    def vsync(self) -> bool:
        try:
            return self.config.getboolean("Display", "vsync",
                                          fallback=DEFAULTS["vsync"])
        except ValueError:
            return DEFAULTS["vsync"]

    @property
    def high_dpi(self) -> bool:
        try:
            return self.config.getboolean(
                "Display", "high_dpi_scaling",
                fallback=DEFAULTS["high_dpi_scaling"])
        except ValueError:
            return DEFAULTS["high_dpi_scaling"]

    # -- write -----------------------------------------------------------
    def save(self, mode: str, width: int, height: int, vsync: bool,
             high_dpi: bool = None) -> None:
        for section in ("Kiosk", "Display"):
            if not self.config.has_section(section):
                self.config.add_section(section)
        self.config.set("Kiosk", "window_mode", str(mode))
        self.config.set("Kiosk", "res_width", str(int(width)))
        self.config.set("Kiosk", "res_height", str(int(height)))
        self.config.set("Display", "vsync", str(bool(vsync)))
        if high_dpi is not None:
            self.config.set("Display", "high_dpi_scaling", str(bool(high_dpi)))
        with open(self.path, "w") as f:
            self.config.write(f)

    def reset(self) -> None:
        self.save(DEFAULTS["window_mode"], DEFAULTS["res_width"],
                  DEFAULTS["res_height"], DEFAULTS["vsync"],
                  DEFAULTS["high_dpi_scaling"])


# ---------------------------------------------------------------------------
# The banner
# ---------------------------------------------------------------------------
class Banner(QWidget):
    """The strip along the top.

    Uses ``assets/banner.png`` when there is one; otherwise it paints a
    placeholder so the launcher is complete and legible before any art exists —
    and so it is obvious where the art goes. It also doubles as the drag handle,
    since the launcher has no title bar."""

    def __init__(self, root_dir: str = ".", parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._pixmap = self._load(root_dir)
        self._drag_from = None
        self.refresh_metrics()

    def refresh_metrics(self, unit: float = None):
        """Re-derive the banner height from one line of text.

        *unit* lets the parent pass its own measurement: Qt delivers FontChange
        to each widget separately, so when the launcher re-measures on a font
        change the banner has not necessarily been told yet, and measuring its
        own font there would use the old one."""
        if unit is None:
            unit = text_unit(self)
        self.setFixedHeight(int(round(float(unit) * _BANNER_LINES)))

    def changeEvent(self, event):
        # The application font can change under us (Settings ▸ font size, or a
        # display-scale change); the banner re-measures rather than keeping a
        # height that was right once.
        super().changeEvent(event)
        if event.type() == event.FontChange:
            self.refresh_metrics()

    @staticmethod
    def _load(root_dir: str):
        for name in ("banner.png", "banner.jpg"):
            path = os.path.join(root_dir, "assets", name)
            if os.path.isfile(path):
                pix = QPixmap(path)
                if not pix.isNull():
                    return pix
        return None

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = self.rect()
        if self._pixmap is not None:
            scaled = self._pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding,
                                         Qt.SmoothTransformation)
            x = (scaled.width() - rect.width()) // 2
            y = (scaled.height() - rect.height()) // 2
            painter.drawPixmap(rect, scaled, scaled.rect().adjusted(
                x, y, -x, -y))
            painter.end()
            return

        # --- placeholder ---
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0.0, QColor(28, 30, 38))
        gradient.setColorAt(1.0, QColor(16, 17, 22))
        painter.fillRect(rect, gradient)
        painter.setPen(QPen(QColor(_ACCENT), 2))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        base = self.font()
        title = QFont(base)
        title.setPointSizeF(max(8.0, base.pointSizeF() * _TITLE_SCALE))
        title.setLetterSpacing(QFont.PercentageSpacing, 106)
        painter.setFont(title)
        painter.setPen(QPen(QColor(232, 232, 236)))
        painter.drawText(QRectF(0, rect.height() * 0.26, rect.width(),
                                rect.height() * 0.34),
                         Qt.AlignHCenter | Qt.AlignVCenter, "MiniWind")

        sub = QFont(base)
        sub.setPointSizeF(max(6.0, base.pointSizeF() * _SMALL_SCALE))
        painter.setFont(sub)
        painter.setPen(QPen(QColor(130, 132, 140)))
        painter.drawText(QRectF(0, rect.height() * 0.60, rect.width(),
                                rect.height() * 0.20),
                         Qt.AlignHCenter | Qt.AlignVCenter,
                         "banner placeholder — drop assets/banner.png here")
        painter.end()

    # -- dragging (there is no title bar to grab) -------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPos() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPos() - self._drag_from)

    def mouseReleaseEvent(self, _event):
        self._drag_from = None


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------
class Launcher(QDialog):
    """Choose Play or Edit, and set up the display first."""

    def __init__(self, root_dir: str = ".", settings_path: str = None,
                 parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setWindowTitle("MiniWind")
        self.setModal(True)
        self.settings = DisplaySettings(
            settings_path or os.path.join(root_dir, "settings.ini"))
        self.choice = EDIT
        self._loading = True
        #: What high DPI was set to when the launcher opened — the note only
        #: appears when the choice actually differs from the running session.
        self._initial_high_dpi = self.settings.high_dpi

        # No font-size in pixels anywhere: every size is in em (relative to the
        # inherited application font), so the launcher honours OS display
        # scaling and the user's own font_size setting — the same rule the
        # logic wizard's stylesheet follows.
        self.setStyleSheet("""
            QDialog { background-color: #17181d; border: 1px solid #34363f; }
            QLabel { color: #d8d8dc; }
            QLabel#section { color: #8a8c96; }
            QComboBox { background-color: #23252c; border: 1px solid #3a3d47;
                        padding: 0.3em 0.5em; color: #e4e4e8; }
            QComboBox:disabled { color: #6a6c74; }
            QCheckBox { color: #d8d8dc; }
            QPushButton { background-color: #2a2d35; border: 1px solid #3a3d47;
                          padding: 0.4em 0.9em; color: #e4e4e8; }
            QPushButton:hover { background-color: #343841; }
        """)

        unit = text_unit(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.banner = Banner(root_dir, self)
        outer.addWidget(self.banner)

        body = QVBoxLayout()
        body.setContentsMargins(int(unit * 1.5), int(unit * 1.1),
                                int(unit * 1.5), int(unit * 1.2))
        body.setSpacing(int(unit * 0.8))
        outer.addLayout(body)

        self.section_label = QLabel("PLAY MODE DISPLAY")
        self.section_label.setObjectName("section")
        body.addWidget(self.section_label)

        form = QFormLayout()
        form.setSpacing(int(unit * 0.5))
        self.mode_combo = QComboBox()
        for value, label, _help in MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("Mode", self.mode_combo)

        self.res_combo = QComboBox()
        form.addRow("Resolution", self.res_combo)
        self.res_combo.currentIndexChanged.connect(self._save)
        body.addLayout(form)

        self.mode_help = QLabel()
        self.mode_help.setWordWrap(True)
        self.mode_help.setStyleSheet("color:#7d7f88;")
        body.addWidget(self.mode_help)

        # Say plainly what these two do *not* touch. Play mode is presented in
        # the editor's own window, so it would be a fair guess that setting a
        # resolution here resizes the editor. It does not: the editor keeps its
        # own size, position and layout, and gets them back on the way out.
        self.scope_note = QLabel(
            "Applies to the game only — the editor keeps its own window size "
            "and layout.")
        self.scope_note.setWordWrap(True)
        self.scope_note.setStyleSheet("color:#61636b;")
        body.addWidget(self.scope_note)

        self.app_section_label = QLabel("APPLICATION")
        self.app_section_label.setObjectName("section")
        body.addWidget(self.app_section_label)

        self.vsync_check = QCheckBox("Vertical sync")
        self.vsync_check.setToolTip(
            "Match the display's refresh rate. Smoother, at a little latency.\n"
            "Applies to the whole application — Qt is told once, at startup.")
        self.vsync_check.toggled.connect(self._save)
        body.addWidget(self.vsync_check)

        self.high_dpi_check = QCheckBox("High DPI scaling")
        self.high_dpi_check.setToolTip(
            "Scale the interface by the display's own scale factor, so the\n"
            "editor stays readable on a high-resolution screen. Qt has to be\n"
            "told this before it starts, so it takes effect next launch.")
        self.high_dpi_check.toggled.connect(self._on_high_dpi_toggled)
        body.addWidget(self.high_dpi_check)

        self.high_dpi_note = QLabel("Takes effect next launch.")
        self.high_dpi_note.setStyleSheet("color:#8a7c3f;")
        self.high_dpi_note.setVisible(False)
        body.addWidget(self.high_dpi_note)

        rule = QFrame()
        rule.setFrameShape(QFrame.HLine)
        rule.setStyleSheet("color:#2a2c33;")
        body.addWidget(rule)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.reset_button = QPushButton("Reset to defaults")
        self.reset_button.setToolTip(
            f"Back to {DEFAULTS['window_mode']}, "
            f"{DEFAULTS['res_width']}×{DEFAULTS['res_height']}, vsync on.")
        self.reset_button.clicked.connect(self._reset)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)

        self.play_button = QPushButton("PLAY")
        self.play_button.setDefault(True)
        self.play_button.setStyleSheet(
            f"QPushButton {{ background-color:{_PLAY_GREEN}; color:white;"
            f" border:1px solid #1B5E20; font-weight:bold; letter-spacing:1px; }}"
            f"QPushButton:hover {{ background-color:#388E3C; }}"
            f"QPushButton:pressed {{ background-color:#1B5E20; }}")
        self.play_button.clicked.connect(lambda: self._finish(PLAY))
        buttons.addWidget(self.play_button)

        self.edit_button = QPushButton("EDIT")
        self.edit_button.setStyleSheet(
            "QPushButton { font-weight:bold; letter-spacing:1px; }"
            "QPushButton:hover { background-color:#343841; }")
        self.edit_button.clicked.connect(lambda: self._finish(EDIT))
        buttons.addWidget(self.edit_button)
        body.addLayout(buttons)

        footer = QHBoxLayout()
        footer.setSpacing(int(unit * 0.7))

        self.version_label = QLabel(read_version(root_dir) or "")
        self.version_label.setStyleSheet("color:#5f6169;")
        self.version_label.setToolTip("From editor/version.txt")
        footer.addWidget(self.version_label)

        self.project_link = QLabel(
            f'<a href="{PROJECT_URL}" style="color:#7d8fa8; '
            f'text-decoration:none;">github.com/ViciousSquid/MiniWind</a>')
        self.project_link.setOpenExternalLinks(True)
        self.project_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.project_link.setToolTip(PROJECT_URL)
        self.project_link.setCursor(Qt.PointingHandCursor)
        footer.addWidget(self.project_link)

        footer.addStretch(1)
        quit_link = QPushButton("Quit")
        quit_link.setFlat(True)
        quit_link.setStyleSheet(
            "QPushButton { border:none; background:transparent; color:#6f7179;"
            " padding:0.15em 0.3em; }"
            "QPushButton:hover { color:#c8c9cf; }")
        quit_link.clicked.connect(lambda: self._finish(QUIT))
        footer.addWidget(quit_link)
        body.addLayout(footer)

        self._populate_resolutions()
        self._load()
        self._loading = False
        self._apply_metrics()
        self.play_button.setFocus()

    # -- DPI-aware sizing --------------------------------------------------
    def _apply_metrics(self):
        """Re-derive every dimension from the current font.

        Called once at construction and again whenever the application font
        changes — a font-size change in Settings, or the display scale changing
        under a window that has already been created. Doing it in one place is
        what keeps the width, the buttons and the banner from drifting apart."""
        unit = text_unit(self)
        self.setFixedWidth(int(round(unit * _WIDTH_LINES)))
        small = self._small_font()
        for label in (self.section_label, self.app_section_label,
                      self.mode_help, self.scope_note, self.high_dpi_note,
                      self.version_label, self.project_link):
            label.setFont(small)
        size = self._button_size()
        self.play_button.setMinimumSize(size)
        self.edit_button.setMinimumSize(size)
        self.banner.refresh_metrics(unit)
        self.adjustSize()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.FontChange:
            self._apply_metrics()

    def _small_font(self) -> QFont:
        """The caption font: a fraction of the inherited font, never a pixel size."""
        font = QFont(self.font())
        font.setPointSizeF(max(6.0, font.pointSizeF() * _SMALL_SCALE))
        font.setLetterSpacing(QFont.PercentageSpacing, 108)
        return font

    def _button_size(self) -> QSize:
        """PLAY / EDIT, sized in text lines so they stay prominent at any scale."""
        unit = text_unit(self)
        return QSize(int(round(unit * _BUTTON_W_LINES)),
                     int(round(unit * _BUTTON_H_LINES)))

    # -- loading / saving --------------------------------------------------
    def _populate_resolutions(self):
        """Offer the sizes that fit this screen, plus whatever is already set."""
        screen = QApplication.primaryScreen()
        geo = screen.geometry() if screen is not None else None
        sizes = [wh for wh in RESOLUTIONS
                 if geo is None or (wh[0] <= geo.width() and wh[1] <= geo.height())]
        if geo is not None and (geo.width(), geo.height()) not in sizes:
            sizes.append((geo.width(), geo.height()))
        current = self.settings.resolution
        if current not in sizes:
            sizes.append(current)
        for w, h in sorted(set(sizes)):
            label = f"{w} × {h}"
            if geo is not None and (w, h) == (geo.width(), geo.height()):
                label += "   (desktop)"
            self.res_combo.addItem(label, (w, h))

    def _load(self):
        mode_index = self.mode_combo.findData(self.settings.mode)
        self.mode_combo.setCurrentIndex(max(0, mode_index))
        self.res_combo.setCurrentIndex(max(0, self._res_index(
            self.settings.resolution)))
        self.vsync_check.setChecked(self.settings.vsync)
        self.high_dpi_check.setChecked(self.settings.high_dpi)
        self.high_dpi_note.setVisible(False)
        self._update_mode_help()

    def _res_index(self, resolution) -> int:
        """Index of a ``(width, height)`` in the resolution list, or -1.

        ``QComboBox.findData`` does not reliably match a Python tuple through
        QVariant, and silently returning -1 there would quietly reset somebody's
        saved resolution — so the comparison is done here instead."""
        want = (int(resolution[0]), int(resolution[1]))
        for i in range(self.res_combo.count()):
            data = self.res_combo.itemData(i)
            if data is not None and (int(data[0]), int(data[1])) == want:
                return i
        return -1

    def current_mode(self) -> str:
        return self.mode_combo.currentData() or DEFAULTS["window_mode"]

    def current_resolution(self):
        return self.res_combo.currentData() or (DEFAULTS["res_width"],
                                                DEFAULTS["res_height"])

    def _on_mode_changed(self, *_):
        self._update_mode_help()
        self._save()

    def _update_mode_help(self):
        """Resolution only means anything for a real window, so say so and grey
        it out rather than letting someone set a size that is ignored."""
        mode = self.current_mode()
        for value, _label, help_text in MODES:
            if value == mode:
                self.mode_help.setText(help_text)
                break
        self.res_combo.setEnabled(mode == "Windowed")

    def _on_high_dpi_toggled(self, checked):
        # The attribute has to be set before the QApplication exists, so a
        # change here cannot apply to the session that is about to start. Say
        # so plainly rather than letting it look broken.
        if not self._loading:
            self.high_dpi_note.setVisible(checked != self._initial_high_dpi)
        self._save()

    def _save(self, *_):
        if self._loading:
            return
        width, height = self.current_resolution()
        self.settings.save(self.current_mode(), width, height,
                           self.vsync_check.isChecked(),
                           self.high_dpi_check.isChecked())

    def _reset(self):
        self.settings.reset()
        self._loading = True
        self._load()
        self._loading = False

    # -- finishing ---------------------------------------------------------
    def _finish(self, choice: str):
        self.choice = choice
        self._save()
        self.accept() if choice != QUIT else self.reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.choice = EDIT
            self.reject()
            return
        super().keyPressEvent(event)


def launch(root_dir: str = ".", settings_path: str = None, parent=None) -> str:
    """Show the launcher; return :data:`PLAY`, :data:`EDIT` or :data:`QUIT`.

    Never raises: if the launcher cannot be shown, the answer is Edit, so a
    launch problem can never leave someone unable to reach the editor."""
    try:
        dialog = Launcher(root_dir, settings_path, parent)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec_()
        return dialog.choice
    except Exception:
        return EDIT
