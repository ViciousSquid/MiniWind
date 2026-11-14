# Fio — Liminal World Editor & Procedural Engine
#    https://github.com/ViciousSquid/Fio

import sys
import os

from python_runtime import require_supported_python


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

# NumPy's BLAS would otherwise start a worker per core for every matrix
# product. Fio's products are small (frustum tests over a few thousand
# boxes), so the workers buy nothing, and they compete with the logic, AI and
# render threads: under load a single frustum test stalled for over a second.
# Set before anything imports NumPy; an explicit setting still wins.
for _blas_threads in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_blas_threads, "1")


# Dark theme
dark_stylesheet = """
    QMainWindow {
        background-color: #2b2b2b;
    }
    QWidget {
        background-color: #2b2b2b;
        color: #e0e0e0;
        font-family: "Fio UI";
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
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
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
        background-color: #2b2b2b;
        color: #e0e0e0;
        border: 1px solid #555;
    }
    /* Qt 5 on macOS can leave the bottom pixel of an old hover highlight
       behind if the unselected action is drawn transparently. Every normal
       item must repaint its entire rectangle with an opaque background. */
    QMenu::item {
        background-color: #2b2b2b;
    }
    QMenu::item:selected {
        background-color: #F08000;
    }
    QMenu::separator {
        height: 1px;
        background-color: #555;
        margin: 6px 8px;
    }
    QDockWidget {
        titlebar-close-icon: url(assets/close.png);
        titlebar-normal-icon: url(assets/undock.png);
    }
    QToolBar {
        background-color: #2b2b2b;
        border: none;
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
    QTabWidget::tab-bar {
        alignment: left;
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

from editor_styles import CONTROL_STYLESHEET
dark_stylesheet += CONTROL_STYLESHEET

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
    require_supported_python()

    from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QProgressBar
    from PyQt5.QtGui import QPixmap, QSurfaceFormat, QIcon
    from PyQt5.QtCore import Qt
    from editor.main_window import MainWindow
    # Terrain height grids are built on a background thread, not in the
    # frame (engine/terrain.py: Terrain.advance).
    from engine.terrain import Terrain
    Terrain.BACKGROUND_BUILDS = True

    # ---------------------------------------------------------
    # PATH RESOLUTION
    # ---------------------------------------------------------
    if getattr(sys, 'frozen', False) or "__compiled__" in globals():
        root_directory = os.path.dirname(sys.executable)
    else:
        root_directory = os.path.dirname(os.path.abspath(__file__))

    os.chdir(root_directory)

    # Errors go to logs/miniwind.log, the console and the screen from here on
    # (engine/error_report.py), including crashes and exceptions on any thread.
    from engine import error_report
    log_file = error_report.configure(os.path.join(root_directory, 'logs'))
    if log_file:
        print(f"       Logging to {log_file}")
    # Index the asset archives before Qt asks for the splash or icons.
    from engine.asset_archives import asset_exists, prepare_asset_archives
    from engine.asset_qt import load_icon, load_pixmap
    prepare_asset_archives(root_directory)
    
    # Set the application ID for Windows taskbar (required for Windows 7+)
    if sys.platform == 'win32':
        try:
            import ctypes
            myappid = 'fio.editor.v1'  # arbitrary string
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
    # The macOS menu bar names the app after the running bundle: Python's,
    # for a source run. A built Fio.app is named by its own Info.plist.
    if sys.platform == 'darwin' and not (
            getattr(sys, 'frozen', False) or "__compiled__" in globals()):
        from macos_app import set_process_app_name
        set_process_app_name("Fio")
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

    import configparser
    config = configparser.ConfigParser()
    from editor.user_paths import settings_path
    config.read(settings_path(root_directory))
    vsync = config.getboolean('Display', 'vsync', fallback=True)
    fmt.setSwapInterval(1 if vsync else 0)

    QSurfaceFormat.setDefaultFormat(fmt)

    # Qt reads the UI scale only when the QApplication is created.
    from editor.ui_scale import apply_ui_scale
    apply_ui_scale(config)
    # ---------------------------------------------------------

    # Splash class defined AFTER Qt import
    class ProgressSplashScreen(QWidget):
        def __init__(self, pixmap_path):
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

            pixmap = load_pixmap(pixmap_path)

            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(layout)

            self.image_label = QLabel()
            self.image_label.setPixmap(pixmap)
            layout.addWidget(self.image_label)

            self.progress_bar = QProgressBar()
            # The same thin bar as the editor's loading overlay, with the
            # stage written beneath it.
            from editor.loading_overlay import BAR_HEIGHT
            self.progress_bar.setFixedHeight(BAR_HEIGHT)
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setAlignment(Qt.AlignCenter)
            self.progress_message = QLabel()
            self.progress_message.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.progress_bar)
            layout.addWidget(self.progress_message)

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
            self.progress_message.setText(f"{message} ({value}%)")
            QApplication.processEvents()

        def finish(self, main_window):
            self.close()

    from editor.desktop_style import prepare_qt, install_editor_style, set_editor_font_size
    prepare_qt(config.getboolean('Display', 'high_dpi_scaling', fallback=True))
    # Create app
    app = QApplication(sys.argv)
    # One Windows-based style, bundled fonts and icons on every platform, so
    # the editor looks the same on Windows and macOS (editor/desktop_style.py).
    install_editor_style(app)
    # Without this PyQt5 aborts the process on any exception escaping a Qt
    # callback, losing the open map.
    from editor.debug_console import install_excepthook
    install_excepthook()
    app.setStyleSheet(dark_stylesheet)

    # The user's font size, applied up front so the splash and a game's
    # launcher match the editor rather than only the main window honouring it.
    set_editor_font_size(app, config.getint('Display', 'font_size', fallback=11))

    # ---------------------------------------------------------
    # Built-in game layer ([Startup] game_module in settings.ini)
    # ---------------------------------------------------------
    # Loaded by name, before the main window builds its menus, so the editor
    # and engine never import a game. Its plugins must be present first.
    import importlib
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
    if asset_exists(icon_path):
        app_icon = load_icon(icon_path)
        app.setWindowIcon(app_icon)
    else:
        mac_icon_path = os.path.join(root_directory, 'assets', 'icon.icns')
        if asset_exists(mac_icon_path):
            app_icon = load_icon(mac_icon_path)
            app.setWindowIcon(app_icon)
        else:
            png_icon_path = os.path.join(root_directory, 'assets', 'icon.png')
            if asset_exists(png_icon_path):
                app_icon = load_icon(png_icon_path)
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

    # Freeze static worlds only for a game launch. The editor must still be
    # able to collect cycles as objects are edited, removed and undone.
    from engine import gc_control
    gc_control.set_freeze(launch_choice == "play")

    splash.set_progress(25, "Building editor UI...")

    # Straight into the game: the editor is built dormant (hidden, its panels
    # unfilled) and wakes only if the player leaves fullscreen.
    window = MainWindow(root_directory, dormant=launch_choice == "play")
    if launch_choice == "play":
        window.begin_dormant_launch()
    
    # Set icon on main window
    if 'app_icon' in locals():
        window.setWindowIcon(app_icon)
    
    splash.set_progress(100, "Ready.")

    window.showMaximized()
    splash.finish(window)

    # The map this build opens with ([Startup] default_map), loaded one
    # event-loop turn after the window is built.
    # Playing goes straight on from there, under the same loading bar, so
    # the scene has a Player Start to spawn at and the window never sits
    # frozen between the two.
    default_map = config.get('Startup', 'default_map', fallback='').strip()
    # A multiplayer party the game's launcher started opens its own map. Asked
    # of the game module loaded by name above: Fio never imports the game.
    launched_party = getattr(game_module, 'launched_party', None)
    party_lobby = launched_party() if callable(launched_party) else None
    if party_lobby is not None:
        default_map = party_lobby.map_name
        app.aboutToQuit.connect(game_module.close_party)
    default_map_path = os.path.join(root_directory, default_map) if default_map else ''

    def _open_default_map():
        try:
            _open_default_map_unguarded()
        except Exception as exc:
            # Reported on screen and in the log rather than leaving a window
            # that never shows the game.
            error_report.report_error("Could not start the game", exc)
        finally:
            # A dormant launch that did not reach the game wakes the editor
            # rather than leave a window with its controls hidden.
            if not window.is_kiosk_mode:
                window.wake_editor()

    def _open_default_map_unguarded():
        title = (f"Loading {os.path.splitext(os.path.basename(default_map))[0]}"
                 if default_map else "Starting the game")
        overlay = window.loading_overlay
        # A game may ask to carry on from a save chosen at launch (MiniWind's
        # CONTINUE): loaded once play has started, the way its own menus load
        # one.
        resume = getattr(game_module, 'launched_resume', None)
        resume_name = (resume() if callable(resume) and party_lobby is None
                       and launch_choice == "play" else None)
        # Opening the map, starting play on it and (CONTINUE) loading the
        # save: each fills its own share of the bar, in proportion to how
        # long each takes.
        if launch_choice != "play":
            shares = ((0, 100),)
        elif resume_name:
            shares = ((0, 25), (25, 50), (50, 100))
        else:
            shares = ((0, 45), (45, 100))
        with overlay.busy(title, "Reading the map"):
            if default_map_path and os.path.isfile(default_map_path):
                with overlay.share(*shares[0]):
                    window.load_level_file(default_map_path)
            if launch_choice == "play":
                overlay.step("Starting the game", shares[1][0])
                with overlay.share(*shares[1]):
                    window.enter_kiosk_mode()
                if resume_name:
                    overlay.step("Loading your last save", shares[2][0])
                    menu = getattr(window.view_3d, 'play_menu', None)
                    loader = getattr(getattr(menu, 'actions', None), 'load_named', None)
                    if loader is not None:
                        with overlay.share(*shares[2]):
                            loader(resume_name, "your last save")
                if party_lobby is not None and party_lobby.resume_path:
                    from engine import savegame
                    data=savegame.read(party_lobby.resume_path)
                    logic=window.view_3d.logic_thread
                    if logic is not None:
                        savegame.restore_auto(logic,data,current_map_name=os.path.basename(default_map))
                        coop=getattr(getattr(logic,"game_session",None),"coop",None)
                        if coop is not None:
                            coop.checkpoint()

    if (default_map_path and os.path.isfile(default_map_path)) or launch_choice == "play":
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, _open_default_map)

    sys.exit(app.exec_())
