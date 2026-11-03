"""System tray icon: the way back to the widget after hiding it."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..settings import Settings, SettingsStore
from .widget import VocabWidget


class TrayIcon(QSystemTrayIcon):
    def __init__(self, widget: VocabWidget, icon: QIcon, settings: Settings, store: SettingsStore) -> None:
        super().__init__(icon, widget)
        self._widget = widget
        self._settings = settings
        self._store = store
        self.setToolTip("HangulFlow")

        menu = QMenu()
        self._toggle_action = menu.addAction("Hide widget", widget.toggle_visible)
        menu.addAction("Next word", widget.go_next)
        self._pause_action = menu.addAction("Pause rotation", widget.toggle_pause)
        menu.addSeparator()
        menu.addAction("Open library…", widget.library_requested.emit)
        menu.addAction("Add my own word…", widget.add_word)
        menu.addAction("Statistics…", widget.show_statistics)
        menu.addSeparator()
        menu.addAction("About HangulFlow…", widget.show_about)
        menu.addAction("Quit HangulFlow", widget.quit_requested.emit)
        menu.aboutToShow.connect(self._refresh_menu)
        self._menu = menu  # keep a reference; the tray does not own its menu
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        widget.hidden_by_user.connect(self._show_hint_once)

    def _refresh_menu(self) -> None:
        self._toggle_action.setText("Hide widget" if self._widget.isVisible() else "Show widget")
        self._pause_action.setText("Resume rotation" if self._widget.is_paused else "Pause rotation")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._widget.toggle_visible()

    def _show_hint_once(self) -> None:
        if self._settings.tray_hint_shown:
            return
        self._settings.tray_hint_shown = True
        self._store.save(self._settings)
        self.showMessage(
            "HangulFlow is still running",
            "Click the 한 icon in the system tray to bring the widget back.",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )
