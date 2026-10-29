"""The editor's Windows layout rules, shared on every desktop platform."""

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QFormLayout, QProxyStyle, QStyle, QStyleFactory

UI_FONT = "Selawik"
MONO_FONT = "IBM Plex Mono"


def prepare_qt():
    """Call before QApplication: points and menus use the Windows convention.

    Keep device-pixel-ratio scaling enabled. Only point-to-logical-pixel text
    conversion is fixed at 96 DPI; Retina still renders at its native density.
    """
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.AA_Use96Dpi, True)
        QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, True)


class EditorStyle(QProxyStyle):
    def __init__(self):
        base = QStyleFactory.create("Windows")
        if base is None:
            raise RuntimeError("Qt's shared Windows widget style is unavailable")
        super().__init__(base)
        self.setObjectName("FioWindows")

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        rules = {
            QStyle.SH_TabBar_Alignment: int(Qt.AlignLeft),
            QStyle.SH_FormLayoutFormAlignment: int(Qt.AlignLeft | Qt.AlignTop),
            QStyle.SH_FormLayoutLabelAlignment: int(Qt.AlignLeft | Qt.AlignVCenter),
            QStyle.SH_FormLayoutFieldGrowthPolicy: QFormLayout.AllNonFixedFieldsGrow,
            QStyle.SH_FormLayoutWrapPolicy: QFormLayout.WrapLongRows,
            QStyle.SH_DialogButtonLayout: QDialogButtonBox.WinLayout,
        }
        if hint in rules:
            return rules[hint]
        return super().styleHint(hint, option, widget, returnData)


def install_editor_style(app):
    """Install once, before building any editor or launcher widgets."""
    if getattr(app, "_fio_editor_style_installed", False):
        return
    directory = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "editor"
    for path in sorted(directory.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            raise RuntimeError("Could not load editor font: " + str(path))
    families = set(QFontDatabase().families())
    if not {UI_FONT, MONO_FONT}.issubset(families):
        raise RuntimeError("The bundled editor fonts are missing")
    app.setStyle(EditorStyle())
    font = QFont(UI_FONT, 11)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    app._fio_editor_style_installed = True
