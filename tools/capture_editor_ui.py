"""Capture the real editor and loading UI for a chosen checkout.

Used by macos-editor.yml to compare identical maps and camera positions with
native Cocoa Qt widgets. Run each checkout in its own process and settings
directory so global registries, cached pages and saved layouts cannot leak.
"""

import argparse
import configparser
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--map', default='maps/village_walled_source.json')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    runtime = output.parent / ('runtime-' + output.stem)
    runtime.mkdir(exist_ok=True)
    for name in ('assets', 'maps', 'quests', 'cutscenes'):
        target = runtime / name
        if not target.exists():
            target.symlink_to(source / name, target_is_directory=True)
    shutil.copy(source / 'settings.ini', runtime / 'settings.ini')
    os.chdir(runtime)
    sys.path.insert(0, str(source))

    from PyQt5.QtCore import Qt, QTimer, QPointF
    from PyQt5.QtGui import QSurfaceFormat
    from PyQt5.QtWidgets import QApplication

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication([])
    from main import dark_stylesheet
    app.setStyleSheet(dark_stylesheet)
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    config = configparser.ConfigParser()
    config.read(source / 'settings.ini')
    game_module = config.get('Startup', 'game_module', fallback='').strip()
    if game_module:
        importlib.import_module(game_module).install()
    from editor.main_window import MainWindow
    window = MainWindow(str(source))
    window.resize(1440, 900)
    window.show()
    completed = []
    metrics = {'platform': sys.platform, 'qt_platform': app.platformName()}

    def prepare():
        try:
            started = time.perf_counter()
            if not window.load_level_file(str(source / args.map)):
                raise RuntimeError('map load failed')
            metrics['load_seconds'] = time.perf_counter() - started
            metrics['resident_brushes'] = len(window.state.brushes)
            metrics['resident_entities'] = len(window.state.things)
            book = next(t for t in window.state.things if 'book_last_ferryman' in t.name)
            window.set_selected_objects([book])
            window.properties_tab_widget.setCurrentIndex(0)
            tabs = window.property_editor.tab_widget
            for i in range(tabs.count()):
                if 'Ownership' in tabs.tabText(i):
                    tabs.setCurrentIndex(i)
                    break
            window.view_top.pan_offset = QPointF(0, -80)
            window.view_top.zoom_factor = 1.35
            window.view_top.update()
            window.scene_hierarchy.tree.expandAll()
            window.scene_hierarchy.tree.scrollToTop()
            window.resizeDocks([window.right_dock, window.properties_dock], [410, 410], Qt.Vertical)
            QTimer.singleShot(2000, capture)
        except Exception:
            import traceback
            traceback.print_exc()
            app.exit(1)

    def capture():
        try:
            # Flush the native stacked-widget transition before grabbing a
            # window containing a QOpenGLWidget (Cocoa can retain the previous
            # console backing store until its next paint).
            window.properties_tab_widget.setCurrentWidget(window.property_editor)
            window.debug_console.hide()
            window.property_editor.show()
            app.processEvents()
            window.property_editor.repaint()
            window.properties_tab_widget.repaint()
            metrics['properties_tab'] = window.properties_tab_widget.currentIndex()
            metrics['properties_visible'] = window.property_editor.isVisible()
            window.grab().save(str(output))
            metrics['paint_ms'] = window.view_3d.paint_ms
            overlay = window.loading_overlay
            overlay.begin('Loading village_walled_source', 'Building terrain', 50)
            overlay.grab().save(str(output.with_name(output.stem + '-loading.png')))
            metrics['progress_bar_height'] = overlay.bar.height()
            overlay.end()
            output.with_suffix('.json').write_text(json.dumps(metrics, indent=2))
            completed.append(True)
            print(json.dumps(metrics), flush=True)
            window.unsaved_changes = False
            window.close()
            app.quit()
        except Exception:
            import traceback
            traceback.print_exc()
            app.exit(1)

    QTimer.singleShot(300, prepare)
    QTimer.singleShot(600000, lambda: app.exit(2))
    code = app.exec_()
    return code if completed else 1


if __name__ == '__main__':
    raise SystemExit(main())
