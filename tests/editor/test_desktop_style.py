"""Platform themes must not change editor alignment, fonts or button order."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontInfo
from PyQt5.QtWidgets import QDialogButtonBox, QFormLayout, QLabel, QStyle, QTabWidget, QWidget

from editor.desktop_style import MONO_FONT, UI_FONT
from main import dark_stylesheet

pytestmark = pytest.mark.qt


def test_tabs_stay_at_the_left_even_when_a_dialog_has_its_own_stylesheet(qt_app):
    old = qt_app.styleSheet()
    qt_app.setStyleSheet(dark_stylesheet)
    tabs = QTabWidget()
    tabs.setStyleSheet('QTabBar::tab { padding: 6px 10px; background: #425f5d; }')
    for name in ('General', 'Appearance', 'I/O'):
        tabs.addTab(QLabel(name), name)
    tabs.resize(700, 300)
    tabs.show()
    qt_app.processEvents()
    try:
        assert tabs.tabBar().geometry().left() <= 4
        assert tabs.tabBar().geometry().right() < tabs.width() - 100
    finally:
        tabs.close()
        tabs.deleteLater()
        qt_app.setStyleSheet(old)


def test_new_forms_and_button_boxes_use_windows_alignment(qt_app):
    form = QFormLayout()
    assert form.formAlignment() == Qt.AlignLeft | Qt.AlignTop
    assert form.labelAlignment() == Qt.AlignLeft | Qt.AlignVCenter
    assert qt_app.style().styleHint(QStyle.SH_DialogButtonLayout) == QDialogButtonBox.WinLayout
    for family in (UI_FONT, MONO_FONT):
        assert QFontInfo(QFont(family, 11)).family() == family


def test_deferred_pages_get_explicit_alignment_properties(qt_app):
    tabs = QTabWidget()
    page = QWidget()
    form = QFormLayout(page)
    form.addRow('Name', QLabel('Value'))
    form.setFormAlignment(Qt.AlignCenter)
    form.setLabelAlignment(Qt.AlignRight)
    tabs.addTab(page, 'Deferred page')
    tabs.show()
    qt_app.processEvents()
    try:
        assert form.formAlignment() == Qt.AlignLeft | Qt.AlignTop
        assert form.labelAlignment() == Qt.AlignLeft | Qt.AlignVCenter
        assert not tabs.tabBar().expanding()
    finally:
        tabs.close()
        tabs.deleteLater()


def test_spacing_and_indicator_metrics_are_explicit(qt_app):
    style = qt_app.style()
    assert style.pixelMetric(QStyle.PM_LayoutLeftMargin) == 9
    assert style.pixelMetric(QStyle.PM_LayoutHorizontalSpacing) == 6
    assert style.pixelMetric(QStyle.PM_IndicatorWidth) == 16
    assert style.pixelMetric(QStyle.PM_ScrollBarExtent) == 12


def test_label_height_tracks_font_changes_without_staying_enlarged(qt_app):
    label = QLabel('Label text')
    label.show()
    qt_app.processEvents()
    for size in (16, 11):
        font = label.font()
        font.setPointSize(size)
        label.setFont(font)
        qt_app.processEvents()
        assert label.minimumHeight() == label.fontMetrics().height()
    label.close()
    label.deleteLater()


def test_fresh_startup_converts_points_to_windows_logical_pixels():
    result = subprocess.run([sys.executable, '-c', '''
from editor.desktop_style import prepare_qt, install_editor_style
prepare_qt()
from PyQt5.QtWidgets import QApplication, QLabel
from PyQt5.QtGui import QFont, QFontInfo
app = QApplication([])
install_editor_style(app)
assert QFontInfo(QFont("Fio UI", 11)).pixelSize() == 15
assert QFontInfo(QFont("Fio UI", 16)).pixelSize() == 21
from main import dark_stylesheet
app.setStyleSheet(dark_stylesheet)
font = app.font()
font.setPointSize(16)
app.setFont(font)
label = QLabel("Styled text")
label.ensurePolished()
assert QFontInfo(label.font()).pixelSize() == 21
assert label.fontMetrics().height() == 28
'''], cwd=Path(__file__).resolve().parents[2], env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
