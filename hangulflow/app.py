"""Application start-up: logging, single instance, database, widget and tray."""

from __future__ import annotations

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
from .ui.tray import TrayIcon
from .ui.widget import VocabWidget

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


def main() -> int:
    setup_logging()
    log.info("Starting HangulFlow %s (data folder: %s)", __version__, paths.data_dir())

    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # the widget lives on in the tray

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

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(widget, icon, settings, store)
        tray.show()

    def shutdown() -> None:
        widget.save_now()
        if tray is not None:
            tray.hide()
        conn.close()
        guard.release()
        log.info("HangulFlow closed cleanly.")

    app.aboutToQuit.connect(shutdown)
    widget.show()
    return app.exec()
