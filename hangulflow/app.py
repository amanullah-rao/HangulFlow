"""Application start-up: logging, single instance, database, widget and tray."""

from __future__ import annotations

import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__, backup, paths
from .database import open_database
from .repository import VocabRepository
from .rotation import WordSession
from .settings import SettingsStore
from .single_instance import SingleInstance
from .ui import theme
from .ui.main_window import MainWindow
from .ui.tray import TrayIcon
from .ui.widget import VocabWidget
from .updater import WordUpdater

log = logging.getLogger("hangulflow")


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        paths.log_dir() / "hangulflow.log", maxBytes=512_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if sys.stderr is not None:  # None in a windowed (no console) build
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    def log_uncaught(exc_type, exc, tb) -> None:
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = log_uncaught
    # Native crashes (inside Qt or Windows) bypass excepthook; faulthandler still
    # writes their stack here, so a silent exit leaves a trace.
    global _crash_file
    _crash_file = open(paths.log_dir() / "crash.log", "a", encoding="utf-8")
    faulthandler.enable(_crash_file)


_crash_file = None


def main() -> int:
    setup_logging()
    log.info("Starting HangulFlow %s (data folder: %s)", __version__, paths.data_dir())

    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # the widget lives on in the tray

    if "--self-test" in sys.argv:
        from .selftest import run

        return run(app)

    guard = SingleInstance(paths.lock_path())
    if not guard.acquire():
        log.info("HangulFlow is already running; asked it to show the widget.")
        return 0

    log.info("Bundled fonts loaded: %s", ", ".join(theme.load_bundled_fonts(paths.fonts_dir())) or "none")
    fonts = theme.detect_fonts()
    log.info("Fonts: Korean=%s, Urdu=%s, icons=%s", fonts.korean, fonts.urdu, fonts.icons)
    icon = theme.app_icon(fonts.korean)
    app.setWindowIcon(icon)

    store = SettingsStore(paths.settings_path())
    settings = store.load()
    app.setStyleSheet(theme.stylesheet(fonts, theme.palette(settings.theme)))

    conn = open_database(paths.database_path())
    repo = VocabRepository(conn)
    repo.import_seed(paths.seed_vocabulary_path())
    log.info("Vocabulary words in database: %d", repo.count())
    backup.daily_backup(conn, paths.backup_dir())
    backup_timer = QTimer(app)  # the app may run for days; check every 6 hours
    backup_timer.setInterval(6 * 60 * 60 * 1000)
    backup_timer.timeout.connect(lambda: backup.daily_backup(conn, paths.backup_dir()))
    backup_timer.start()

    widget = VocabWidget(repo, WordSession(repo), settings, store, fonts)
    widget.quit_requested.connect(app.quit)
    guard.activation_requested.connect(widget.bring_to_front)

    library: list[MainWindow] = []  # created on first use to keep start-up light

    def open_library() -> None:
        if not library:
            window = MainWindow(repo, conn, widget, settings, fonts)
            window.setWindowIcon(icon)
            library.append(window)
        library[0].present()

    widget.library_requested.connect(open_library)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(widget, icon, settings, store)
        tray.show()

    updater = WordUpdater(repo)
    widget.set_updater(updater)
    if tray is not None:
        updater.finished.connect(
            lambda added, _error: added
            and tray.showMessage("HangulFlow", f"{added} new words were added to your list.", icon, 6000)
        )
    update_timer = QTimer(app)  # hourly tick; the updater itself limits real checks to once a day
    update_timer.setInterval(60 * 60 * 1000)
    update_timer.timeout.connect(lambda: settings.auto_update and updater.check())
    update_timer.start()
    QTimer.singleShot(60_000, lambda: settings.auto_update and updater.check())  # let start-up settle first

    def shutdown() -> None:
        widget.save_now()
        if tray is not None:
            tray.hide()
        conn.close()
        guard.release()
        log.info("HangulFlow closed cleanly.")

    def session_ending(_manager) -> None:
        # Windows is signing out or shutting down; it may end the process before
        # aboutToQuit runs, so save now.
        log.info("Windows session is ending; saving.")
        widget.save_now()

    app.aboutToQuit.connect(shutdown)
    app.commitDataRequest.connect(session_ending)
    widget.show()
    return app.exec()
