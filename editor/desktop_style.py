"""The editor's Windows layout rules, shared on every desktop platform."""

from pathlib import Path
import os

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPalette
from PyQt5.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDialogButtonBox,
                             QFileDialog, QFileIconProvider,
                             QFormLayout, QHeaderView, QLabel, QProxyStyle, QStyle, QStyleFactory,
                             QTabWidget, QToolTip, QWidget)

UI_FONT = "Fio UI"
MONO_FONT = "IBM Plex Mono"
ICON_DIRECTORY = Path(__file__).resolve().parents[1] / 'assets' / 'ui' / 'controls'


def prepare_qt(high_dpi=True):
    """Call before QApplication: points and menus use the Windows convention.

    Keep device-pixel-ratio scaling enabled. Only point-to-logical-pixel text
    conversion is fixed at 96 DPI; Retina still renders at its native density.
    """
    if QApplication.instance() is None:
        # Stylesheet point sizes use the screen DPI too; AA_Use96Dpi alone
        # only normalizes standalone QFont instances on some Qt 5 backends.
        os.environ["QT_FONT_DPI"] = "96"
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, high_dpi)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        QApplication.setAttribute(Qt.AA_Use96Dpi, True)
        QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, True)
        QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


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
            QStyle.SH_DialogButtonBox_ButtonsHaveIcons: 0,
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

    def standardIcon(self, icon, option=None, widget=None):
        files = {
            QStyle.SP_ArrowLeft: 'left', QStyle.SP_ArrowRight: 'right',
            QStyle.SP_ArrowUp: 'up', QStyle.SP_ArrowDown: 'down',
            QStyle.SP_ArrowBack: 'left', QStyle.SP_ArrowForward: 'right',
            QStyle.SP_DialogOkButton: 'check', QStyle.SP_DialogApplyButton: 'check',
            QStyle.SP_DialogCancelButton: 'close', QStyle.SP_DialogCloseButton: 'close',
            QStyle.SP_DialogOpenButton: 'folder', QStyle.SP_DialogSaveButton: 'save',
            QStyle.SP_TitleBarCloseButton: 'close', QStyle.SP_TitleBarMinButton: 'minus',
            QStyle.SP_TitleBarMaxButton: 'maximize', QStyle.SP_TitleBarNormalButton: 'restore',
            QStyle.SP_DirIcon: 'folder', QStyle.SP_DirOpenIcon: 'folder',
            QStyle.SP_DirClosedIcon: 'folder', QStyle.SP_DirLinkIcon: 'folder',
            QStyle.SP_FileIcon: 'file', QStyle.SP_FileLinkIcon: 'file',
            QStyle.SP_FileDialogToParent: 'up', QStyle.SP_FileDialogBack: 'left',
            QStyle.SP_FileDialogNewFolder: 'new-folder',
            QStyle.SP_FileDialogDetailedView: 'list', QStyle.SP_FileDialogListView: 'list',
            QStyle.SP_MessageBoxInformation: 'info', QStyle.SP_MessageBoxWarning: 'warning',
            QStyle.SP_MessageBoxCritical: 'error', QStyle.SP_MessageBoxQuestion: 'question',
        }
        if icon in files:
            return QIcon(str(ICON_DIRECTORY / (files[icon] + '.svg')))
        return super().standardIcon(icon, option, widget)


class EditorFileIcons(QFileIconProvider):
    def icon(self, value):
        folder = value.isDir() if hasattr(value, 'isDir') else value == QFileIconProvider.Folder
        return QIcon(str(ICON_DIRECTORY / ('folder.svg' if folder else 'file.svg')))


class EditorLayoutRules(QObject):
    """Assign layout properties to actual widgets, including deferred pages."""

    def eventFilter(self, obj, event):
        if not isinstance(obj, QWidget):
            return False
        if event.type() in (QEvent.Polish, QEvent.FontChange) and isinstance(obj, QLabel):
            if obj.text() and obj.maximumHeight() == 16777215:
                previous = obj.property('_fio_label_height')
                floor = obj.property('_fio_label_floor')
                if previous is None or obj.minimumHeight() != previous:
                    floor = obj.minimumHeight()
                height = max(floor or 0, obj.fontMetrics().height())
                obj.setProperty('_fio_label_floor', floor or 0)
                obj.setProperty('_fio_label_height', height)
                obj.setMinimumHeight(height)
        if event.type() != QEvent.Polish:
            return False
        if isinstance(obj, QTabWidget):
            obj.setUsesScrollButtons(True)
            obj.setElideMode(Qt.ElideRight)
            obj.tabBar().setExpanding(False)
        if isinstance(obj, QDialogButtonBox):
            obj.setCenterButtons(False)
        if isinstance(obj, QFileDialog):
            obj.setOption(QFileDialog.DontUseNativeDialog, True)
            obj.setOption(QFileDialog.DontUseCustomDirectoryIcons, True)
            obj.setIconProvider(QApplication.instance()._fio_file_icons)
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
    palette = QPalette()
    colours = {
        QPalette.Window: '#2b2b2b', QPalette.WindowText: '#e0e0e0',
        QPalette.Base: '#303234', QPalette.AlternateBase: '#2b2b2b',
        QPalette.ToolTipBase: '#333333', QPalette.ToolTipText: '#eeeeee',
        QPalette.Text: '#e0e0e0', QPalette.Button: '#3c3f41', QPalette.ButtonText: '#e0e0e0',
        QPalette.Highlight: '#425f5d', QPalette.HighlightedText: '#ffffff',
        QPalette.Link: '#f08000', QPalette.LinkVisited: '#c07bc2', QPalette.BrightText: '#ffffff',
        QPalette.Light: '#707579', QPalette.Midlight: '#55595d', QPalette.Mid: '#44484b',
        QPalette.Dark: '#202224', QPalette.Shadow: '#17191b', QPalette.PlaceholderText: '#888888',
    }
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role, colour in colours.items():
            palette.setColor(group, role, QColor(colour))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.PlaceholderText):
        palette.setColor(QPalette.Disabled, role, QColor('#858585'))
    for role in (QPalette.Base, QPalette.Button):
        palette.setColor(QPalette.Disabled, role, QColor('#333333'))
    app.setPalette(palette)
    app._fio_file_icons = EditorFileIcons()
    app.setLayoutDirection(Qt.LeftToRight)
    app._fio_layout_rules = EditorLayoutRules(app)
    app.installEventFilter(app._fio_layout_rules)
    set_editor_font_size(app, 11)
    app._fio_editor_style_installed = True


def set_editor_font_size(app, size):
    font = QFont(UI_FONT, int(size))
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    for widget_class in ('QMenu', 'QMenuBar', 'QMessageBox'):
        app.setFont(font, widget_class)
    QToolTip.setFont(font)
