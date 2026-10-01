# Fio — Liminal World Editor & Procedural Engine
#    https://github.com/ViciousSquid/Fio

import sys
import os


os.environ["QT_PLUGIN_PATH"] = ""
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ""

# PyOpenGL calls glGetError after every GL call unless told not to, which on a
# frame of a few hundred calls is a measurable share of the paint. It must be
# decided before anything imports OpenGL.GL. FIO_GL_DEBUG=1 keeps the checks
# (the test suite never comes through here, so it always runs with them).
if os.environ.get("FIO_GL_DEBUG") != "1":
    os.environ.setdefault("PYOPENGL_ERROR_CHECKING", "0")

# Fio runs the UI/renderer, the logic thread and the monster AI as Python
# threads. Whenever one releases the GIL (every GL call, every large NumPy
# operation) and another takes it, the first waits up to the switch interval to
# get it back -- 5 ms by default, a third of a frame. Measured on a 24k-brush
# map, 1 ms cuts the logic thread's p95 frame preparation from ~59 to ~25 ms.
sys.setswitchinterval(0.001)


# Dark theme
dark_stylesheet = """
    QMainWindow {
        background-color: #2b2b2b;
    }
    QWidget {
        background-color: #2b2b2b;
        color: #e0e0e0;
        font-family: "Segoe UI", Arial, sans-serif;
    }
    QPushButton {
        background-color: #3c3f41;
        border: 1px solid #555;
        padding: 5px;
        min-width: 60px;
    }
    QPushButton:hover {
        background-color: #4b4d4d;
    }
    QPushButton:pressed {
        background-color: #2b2b2b;
    }
    QLineEdit, QTextEdit, QSpinBox, QComboBox {
        background-color: #3c3f41;
        border: 1px solid #555;
        color: #e0e0e0;
        padding: 2px;
    }
    QMenuBar {
        background-color: #3c3f41;
        color: #e0e0e0;
    }
    QMenuBar::item:selected {
        background-color: #4b4d4d;
    }
    QMenu {
        background-color: #3c3f41;
        color: #e0e0e0;
        border: 1px solid #555;
    }
    QMenu::item:selected {
        background-color: #4b4d4d;
    }
    QDockWidget {
        titlebar-close-icon: url(assets/close.png);
        titlebar-normal-icon: url(assets/undock.png);
    }
    QDockWidget::title {
        background-color: #3c3f41;
        padding-left: 10px;
        padding-top: 4px;
    }
    QScrollBar:vertical {
        border: none;
        background: #2b2b2b;
        width: 12px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #4b4d4d;
        min-height: 20px;
        border-radius: 6px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QTabWidget::pane {
        border: 1px solid #555;
    }
    QTabBar::tab {
        background-color: #3c3f41;
        padding: 8px 12px;
        border-right: 1px solid #555;
    }
    QTabBar::tab:selected {
        background-color: #2b2b2b;
        border-bottom: 2px solid #007acc;
    }
    QStatusBar {
        background-color: #3c3f41;
        color: #e0e0e0;
    }
    QProgressBar {
        border: 1px solid #555;
        border-radius: 3px;
        text-align: center;
    }
    QProgressBar::chunk {
        background-color: #2b6132;
    }
    QFrame {
        border: 1px solid #555;
    }
"""

def _missing_mandatory_plugins(config):
    """Names in ``[Plugins] mandatory`` that discovery did not find.

    A build that lists a plugin as mandatory is made of it: it is enabled
    here, whatever ``[Plugins] disabled`` says, and its absence stops the
    launch with one clear message rather than surfacing later as unknown
    entities halfway into a map.
    """
    names = [n.strip() for n in config.get('Plugins', 'mandatory', fallback='').split(',')
             if n.strip()]
    if not names:
        return []
    from plugins.manager import get_manager, load_plugins
    load_plugins()
    manager = get_manager()
    missing = []
    for name in names:
        plugin = manager.find_plugin(name)
        if plugin is None:
            missing.append(name)
        else:
            manager.set_enabled(plugin, True)
    return missing


if __name__ == "__main__":

    # ---------------------------------------------------------
    # Android / standalone player entry point.
    # Under python-for-android (ANDROID_ARGUMENT is set), or when FIO_PLAYER=1
    # on the desktop, launch the touch-first .fiopak player instead of the
    # PyQt5 editor. This branch runs before any PyQt import so the editor's
    # desktop-only dependencies are never touched on mobile.
    # ---------------------------------------------------------
    if os.environ.get("ANDROID_ARGUMENT") or os.environ.get("FIO_PLAYER"):
        from player.main import main as _player_main
        raise SystemExit(_player_main([]))

    from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QProgressBar
    import configparser
    import importlib
    from PyQt5.QtGui import QPixmap, QSurfaceFormat, QIcon
    from PyQt5.QtCore import Qt
    from editor.main_window import MainWindow

    # ---------------------------------------------------------
    # PATH RESOLUTION
    # ---------------------------------------------------------
    if getattr(sys, 'frozen', False) or "__compiled__" in globals():
        root_directory = os.path.dirname(sys.executable)
    else:
        root_directory = os.path.dirname(os.path.abspath(__file__))

    os.chdir(root_directory)
    
    # Set the application ID for Windows taskbar (required for Windows 7+)
    if sys.platform == 'win32':
        try:
            import ctypes
            myappid = 'fio.editor.v1'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
    # ---------------------------------------------------------

    # Version print
    try:
        with open(os.path.join(root_directory, 'editor/version.txt'), 'r') as f:
            print(f"")
            print(f"       +++ Fio {f.read().strip()}")
    except FileNotFoundError:
        print("Version file not found")

    # ---------------------------------------------------------
    # Configure OpenGL BEFORE QApplication is created
    # ---------------------------------------------------------
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)

    config = configparser.ConfigParser()
    config.read('settings.ini')
    vsync = config.getboolean('Display', 'vsync', fallback=True)
    fmt.setSwapInterval(1 if vsync else 0)

    QSurfaceFormat.setDefaultFormat(fmt)
    # ---------------------------------------------------------

    # Splash class defined AFTER Qt import
    class ProgressSplashScreen(QWidget):
        def __init__(self, pixmap_path):
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

            pixmap = QPixmap(pixmap_path)

            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(layout)

            self.image_label = QLabel()
            self.image_label.setPixmap(pixmap)
            layout.addWidget(self.image_label)

            self.progress_bar = QProgressBar()
            self.progress_bar.setFixedHeight(35)
            self.progress_bar.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.progress_bar)

            self.center_on_screen()

        def center_on_screen(self):
            screen = QApplication.primaryScreen()
            geo = screen.geometry()
            self.move(
                (geo.width() - self.width()) // 2,
                (geo.height() - self.height()) // 2
            )

        def set_progress(self, value, message):
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{message} ({value}%)")
            QApplication.processEvents()

        def finish(self, main_window):
            self.close()

    # Create app
    app = QApplication(sys.argv)
    # Without this PyQt5 aborts the process on any exception escaping a Qt
    # callback, losing the open map.
    from editor.debug_console import install_excepthook
    install_excepthook()
    app.setStyleSheet(dark_stylesheet)

    # The user's font size, applied up front so the splash and a game's
    # launcher match the editor rather than only the main window honouring it.
    app_font = app.font()
    app_font.setPointSize(config.getint('Display', 'font_size', fallback=11))
    app.setFont(app_font)

    # ---------------------------------------------------------
    # Built-in game layer ([Startup] game_module in settings.ini)
    # ---------------------------------------------------------
    # Loaded by name, before the main window builds its menus, so the editor
    # and engine never import a game. Its plugins must be present first.
    game_module = None
    game_name = config.get('Startup', 'game_module', fallback='').strip()
    if game_name:
        missing = _missing_mandatory_plugins(config)
        if missing:
            message = (f"{missing[0].capitalize()} plugin is mandatory: "
                       f"could not be located")
            print(f"\nerror: {message}", file=sys.stderr)
            try:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.critical(None, "Cannot start", message)
            except Exception:
                pass
            sys.exit(1)
        game_module = importlib.import_module(game_name)
        game_module.install()

    # Set application icon
    icon_path = os.path.join(root_directory, 'assets', 'icon.ico')
    if os.path.exists(icon_path):
        app_icon = QIcon(icon_path)
        app.setWindowIcon(app_icon)
    else:
        mac_icon_path = os.path.join(root_directory, 'assets', 'icon.icns')
        if os.path.exists(mac_icon_path):
            app_icon = QIcon(mac_icon_path)
            app.setWindowIcon(app_icon)
        else:
            png_icon_path = os.path.join(root_directory, 'assets', 'icon.png')
            if os.path.exists(png_icon_path):
                app_icon = QIcon(png_icon_path)
                app.setWindowIcon(app_icon)

    splash = ProgressSplashScreen('assets/splash.png')
    splash.show()
    splash.set_progress(5, "Configuring OpenGL...")

    # A game may ask what this launch is for (play or edit) and let the
    # display be set up first. It writes settings.ini, so re-read the parts
    # that must be applied before the first OpenGL widget exists.
    launch_choice = "edit"
    show_launcher = getattr(game_module, 'show_launcher', None)
    if show_launcher is not None and config.getboolean(
            'Startup', 'show_launcher', fallback=True):
        splash.hide()
        QApplication.processEvents()
        launch_choice = show_launcher(root_directory,
                                      os.path.join(root_directory, 'settings.ini'))
        if launch_choice == "quit":
            sys.exit(0)
        config.read('settings.ini')
        fmt.setSwapInterval(
            1 if config.getboolean('Display', 'vsync', fallback=True) else 0)
        QSurfaceFormat.setDefaultFormat(fmt)
        splash.show()

    splash.set_progress(25, "Building editor UI...")

    window = MainWindow(root_directory)
    
    # Set icon on main window
    if 'app_icon' in locals():
        window.setWindowIcon(app_icon)
    
    # For macOS, set the dock icon explicitly
    if sys.platform == 'darwin':
        try:
            from Foundation import NSBundle
            bundle = NSBundle.mainBundle()
            icon_file = os.path.join(root_directory, 'assets', 'icon.icns')
            if os.path.exists(icon_file):
                bundle.setInfoDictionary_({'CFBundleIconFile': 'icon'})
        except Exception:
            pass

    splash.set_progress(100, "Ready.")

    window.show()
    splash.finish(window)

    # The map this build opens with ([Startup] default_map), loaded one
    # event-loop turn after the window is built.
    default_map = config.get('Startup', 'default_map', fallback='').strip()
    if default_map:
        default_map_path = os.path.join(root_directory, default_map)
        if os.path.isfile(default_map_path):
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: window.load_level_file(default_map_path))

    if launch_choice == "play":
        # One event-loop turn later, so the default map the main window queues
        # has loaded and the scene has a Player Start to spawn at.
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, window.enter_kiosk_mode)

    sys.exit(app.exec_())