"""The editor's Windows layout rules, shared on every desktop platform."""

from pathlib import Path
import os

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDialogButtonBox,
                             QFormLayout, QHeaderView, QProxyStyle, QStyle, QStyleFactory,
                             QTabWidget, QWidget)

UI_FONT = "Fio UI"
MONO_FONT = "IBM Plex Mono"


def prepare_qt():
    """Call before QApplication: points and menus use the Windows convention.

    Keep device-pixel-ratio scaling enabled. Only point-to-logical-pixel text
    conversion is fixed at 96 DPI; Retina still renders at its native density.
    """
    if QApplication.instance() is None:
        # Stylesheet point sizes use the screen DPI too; AA_Use96Dpi alone
        # only normalizes standalone QFont instances on some Qt 5 backends.
        os.environ["QT_FONT_DPI"] = "96"
        QApplication.setAttribute(Qt.AA_Use96Dpi, True)
        QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, True)
        QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)


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
            QStyle.SH_ComboBox_Popup: 0,
            QStyle.SH_ScrollBar_Transient: 0,
            QStyle.SH_Widget_Animate: 0,
            QStyle.SH_UnderlineShortcut: 0,
            QStyle.SH_TabBar_ElideMode: int(Qt.ElideRight),
        }
        if hint in rules:
            return rules[hint]
        return super().styleHint(hint, option, widget, returnData)

    def pixelMetric(self, metric, option=None, widget=None):
        # Explicit geometry, including controls that are not stylesheet drawn.
        metrics = {
            QStyle.PM_LayoutLeftMargin: 9, QStyle.PM_LayoutRightMargin: 9,
            QStyle.PM_LayoutTopMargin: 9, QStyle.PM_LayoutBottomMargin: 9,
            QStyle.PM_LayoutHorizontalSpacing: 6, QStyle.PM_LayoutVerticalSpacing: 6,
            QStyle.PM_DefaultFrameWidth: 1, QStyle.PM_SpinBoxFrameWidth: 1,
            QStyle.PM_ComboBoxFrameWidth: 1, QStyle.PM_ButtonMargin: 6,
            QStyle.PM_ButtonDefaultIndicator: 0, QStyle.PM_ButtonShiftHorizontal: 0,
            QStyle.PM_ButtonShiftVertical: 0, QStyle.PM_ScrollBarExtent: 12,
            QStyle.PM_ScrollBarSliderMin: 24, QStyle.PM_SliderThickness: 20,
            QStyle.PM_SliderLength: 14, QStyle.PM_SliderControlThickness: 14,
            QStyle.PM_IndicatorWidth: 16, QStyle.PM_IndicatorHeight: 16,
            QStyle.PM_ExclusiveIndicatorWidth: 16, QStyle.PM_ExclusiveIndicatorHeight: 16,
            QStyle.PM_CheckBoxLabelSpacing: 6, QStyle.PM_RadioButtonLabelSpacing: 6,
            QStyle.PM_TabBarTabHSpace: 20, QStyle.PM_TabBarTabVSpace: 10,
            QStyle.PM_TabBarBaseHeight: 1, QStyle.PM_TabBarBaseOverlap: 1,
            QStyle.PM_TabBarScrollButtonWidth: 16, QStyle.PM_TabBarIconSize: 16,
            QStyle.PM_ToolBarItemMargin: 2, QStyle.PM_ToolBarItemSpacing: 4,
            QStyle.PM_ToolBarFrameWidth: 0, QStyle.PM_ToolBarHandleExtent: 8,
            QStyle.PM_ToolBarSeparatorExtent: 8, QStyle.PM_ToolBarExtensionExtent: 16,
            QStyle.PM_DockWidgetFrameWidth: 1, QStyle.PM_DockWidgetTitleMargin: 4,
            QStyle.PM_DockWidgetSeparatorExtent: 4, QStyle.PM_SplitterWidth: 4,
            QStyle.PM_HeaderMargin: 4, QStyle.PM_HeaderMarkSize: 12,
            QStyle.PM_SmallIconSize: 16, QStyle.PM_LargeIconSize: 32,
            QStyle.PM_MenuPanelWidth: 1, QStyle.PM_MenuHMargin: 0,
            QStyle.PM_MenuVMargin: 2, QStyle.PM_MenuBarPanelWidth: 0,
            QStyle.PM_MenuBarHMargin: 0, QStyle.PM_MenuBarVMargin: 0,
            QStyle.PM_MenuBarItemSpacing: 0,
        }
        if metric in metrics:
            return metrics[metric]
        return super().pixelMetric(metric, option, widget)


class EditorLayoutRules(QObject):
    """Assign layout properties to actual widgets, including deferred pages."""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Polish or not isinstance(obj, QWidget):
            return False
        if isinstance(obj, QTabWidget):
            obj.setUsesScrollButtons(True)
            obj.setElideMode(Qt.ElideRight)
            obj.tabBar().setExpanding(False)
        if isinstance(obj, QDialogButtonBox):
            obj.setCenterButtons(False)
        if isinstance(obj, QHeaderView):
            obj.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if isinstance(obj, QAbstractSpinBox):
            obj.setAlignment(Qt.AlignLeft)
        if isinstance(obj, QComboBox):
            obj.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            obj.setMinimumContentsLength(12)
        for form in obj.findChildren(QFormLayout):
            form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        return False


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
    app.setLayoutDirection(Qt.LeftToRight)
    app._fio_layout_rules = EditorLayoutRules(app)
    app.installEventFilter(app._fio_layout_rules)
    font = QFont(UI_FONT, 11)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    app._fio_editor_style_installed = True
