"""The HangulFlow library window: browse, search, edit, history, statistics, data and settings.

It shares the database connection and settings with the desktop widget, so
everything changed here shows up on the card straight away (and vice versa).
Closing this window only hides it; HangulFlow keeps running in the tray.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import backup, paths, srs, startup, transfer
from ..repository import LibraryRow, VocabRepository
from ..settings import CARD_DIRECTIONS, DAILY_GOAL_CHOICES, INTERVAL_CHOICES, LAYERS, LEVEL_NAMES, Settings
from . import theme
from .stats_dialog import StatsPanel
from .widget import VocabWidget
from .word_dialog import WordDialog

log = logging.getLogger(__name__)

STATUS_FILTERS = (  # (label, value passed to VocabRepository.library)
    ("All words", None),
    ("New", srs.NEW),
    ("Learning", srs.LEARNING),
    ("Reviewing", srs.REVIEW),
    ("Learned", srs.LEARNED),
    ("Due now", "due"),
    ("★ Favourites", "starred"),
    ("My own words", "mine"),
)
STATUS_NAMES = {srs.NEW: "New", srs.LEARNING: "Learning", srs.REVIEW: "Reviewing", srs.LEARNED: "Learned"}
RATING_NAMES = {srs.KNOWN: "Known", srs.DIFFICULT: "Difficult", srs.UNKNOWN: "Unknown"}
COLUMNS = ("★", "Korean", "Hanja", "English", "Urdu", "Category", "Lv", "Status", "Next review")
LAYER_NAMES = {"desktop": "On desktop only (behind windows)", "normal": "Normal window", "top": "Always on top"}
DIRECTION_NAMES = {"korean": "Korean first", "meaning": "Meaning first (recall Korean)", "mixed": "Mixed"}


def _item(text: str, data=None, align: Qt.AlignmentFlag | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if align is not None:
        item.setTextAlignment(align)
    return item


def _next_review(row: LibraryRow, now: datetime) -> str:
    if row.due_at is None:
        return "—"
    if row.due_at <= now:
        return "due now"
    return "in " + srs.describe_interval((row.due_at - now).total_seconds() / 86400)


class MainWindow(QMainWindow):
    def __init__(
        self,
        repo: VocabRepository,
        conn: sqlite3.Connection,
        widget: VocabWidget,
        settings: Settings,
        fonts: theme.Fonts,
    ) -> None:
        super().__init__(None)
        self.setObjectName("libraryWindow")
        self.setWindowTitle("HangulFlow - Library")
        self.resize(1060, 660)
        self._repo, self._conn, self._widget, self._settings, self._fonts = repo, conn, widget, settings, fonts

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_library_tab(), "Library")
        self._tabs.addTab(self._build_history_tab(), "Review history")
        self._stats_holder = QWidget()
        QVBoxLayout(self._stats_holder).setContentsMargins(0, 0, 0, 0)
        self._tabs.addTab(self._stats_holder, "Statistics")
        self._tabs.addTab(self._build_data_tab(), "Import && backup")  # "&&" shows a literal "&"
        self._settings_tab = self._build_settings_tab()
        self._tabs.addTab(self._settings_tab, "Settings")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        page = QWidget(objectName="page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(self._tabs)
        self.setCentralWidget(page)

        widget.data_changed.connect(self.refresh_all)

    # ------------------------------------------------------------ library tab

    def _build_library_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        filters = QHBoxLayout()
        self._search = QLineEdit(placeholderText="Search Korean, Hanja, romanization, English or Urdu…")
        self._search.setClearButtonEnabled(True)
        self._category_filter = QComboBox()
        self._status_filter = QComboBox()
        for label, value in STATUS_FILTERS:
            self._status_filter.addItem(label, value)
        self._difficulty_filter = QComboBox()
        self._difficulty_filter.addItem("Any level", None)
        for level in (1, 2, 3):
            self._difficulty_filter.addItem(LEVEL_NAMES[level], level)
        filters.addWidget(self._search, 3)
        filters.addWidget(self._category_filter, 2)
        filters.addWidget(self._status_filter, 1)
        filters.addWidget(self._difficulty_filter, 1)
        layout.addLayout(filters)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, width in enumerate((34, 130, 90, 220, 170, 170, 56, 86, 110)):
            self._table.setColumnWidth(col, width)
        header.setStretchLastSection(True)
        self._table.itemDoubleClicked.connect(lambda _item: self.edit_selected())
        self._table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._table, 1)

        actions = QHBoxLayout()
        self._count = QLabel(objectName="statLabel")
        actions.addWidget(self._count, 1)
        self._btn_show = self._button("Show on widget", self.show_selected_on_widget, "Put this word on the desktop card")
        self._btn_star = self._button("★ Favourite", self.toggle_star_selected, "Add to / remove from favourites")
        self._btn_edit = self._button("Edit…", self.edit_selected, "Edit the selected word (or double-click it)")
        self._btn_delete = self._button("Delete…", self.delete_selected, "Delete the selected words and their history")
        add = self._button("Add word…", self.add_word, "Add your own word")
        for button in (self._btn_show, self._btn_star, self._btn_edit, self._btn_delete, add):
            actions.addWidget(button)
        layout.addLayout(actions)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self.refresh_library)
        self._search.textChanged.connect(lambda _t: self._search_timer.start())
        for combo in (self._category_filter, self._status_filter, self._difficulty_filter):
            combo.currentIndexChanged.connect(lambda _i: self.refresh_library())
        return tab

    def _button(self, text: str, slot, tooltip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.clicked.connect(slot)
        return button

    def _reload_categories(self) -> None:
        current = self._category_filter.currentData()
        self._category_filter.blockSignals(True)
        self._category_filter.clear()
        self._category_filter.addItem("All categories", None)
        for category in self._repo.categories():
            self._category_filter.addItem(category, category)
        index = self._category_filter.findData(current)
        self._category_filter.setCurrentIndex(max(0, index))
        self._category_filter.blockSignals(False)

    def refresh_library(self) -> None:
        rows = self._repo.library(
            self._search.text(),
            self._category_filter.currentData(),
            self._status_filter.currentData(),
            self._difficulty_filter.currentData(),
        )
        now = datetime.now(timezone.utc)
        urdu_font = self.font()
        urdu_font.setFamily(self._fonts.urdu)
        urdu_font.setPointSize(11)
        korean_font = self.font()
        korean_font.setFamily(self._fonts.korean)
        korean_font.setPointSize(11)
        korean_font.setWeight(korean_font.Weight.DemiBold)
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        center = Qt.AlignmentFlag.AlignCenter

        self._table.setUpdatesEnabled(False)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            star = _item("★" if r.starred else "", r.id, center)
            star.setForeground(QColor(theme.palette(self._settings.theme).accent))
            korean = _item(r.korean, r.id)
            korean.setFont(korean_font)
            urdu = _item(r.meaning_ur, r.id, right)
            urdu.setFont(urdu_font)
            status = _item(STATUS_NAMES.get(r.status, r.status), r.id)
            if r.lapses:
                status.setToolTip(f"Forgotten {r.lapses} time(s) after learning it")
            cells = (
                star, korean, _item(r.hanja, r.id), _item(r.meaning_en, r.id), urdu, _item(r.category, r.id),
                _item("●" * min(r.difficulty, 3), r.id, center), status, _item(_next_review(r, now), r.id),
            )
            for col, cell in enumerate(cells):
                self._table.setItem(i, col, cell)
        self._table.setSortingEnabled(True)
        self._table.setUpdatesEnabled(True)
        total = self._repo.count()
        self._count.setText(f"{len(rows)} of {total} words" if len(rows) != total else f"{total} words")
        self._update_buttons()

    def _selected_ids(self) -> list[int]:
        ids = {self._table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
               for index in self._table.selectionModel().selectedRows()}
        return sorted(ids)

    def _update_buttons(self) -> None:
        count = len(self._selected_ids())
        self._btn_show.setEnabled(count == 1)
        self._btn_edit.setEnabled(count == 1)
        self._btn_star.setEnabled(count >= 1)
        self._btn_delete.setEnabled(count >= 1)
        self._btn_delete.setText(f"Delete {count}…" if count > 1 else "Delete…")

    def show_selected_on_widget(self) -> None:
        ids = self._selected_ids()
        if len(ids) == 1:
            self._widget.show_word(ids[0])

    def toggle_star_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        make_starred = not all(self._repo.get(i).starred for i in ids)
        for vocab_id in ids:
            self._repo.set_starred(vocab_id, make_starred)
        self._after_change()

    def add_word(self) -> None:
        self._edit(None)

    def edit_selected(self) -> None:
        ids = self._selected_ids()
        if len(ids) == 1:
            self._edit(ids[0])

    def _edit(self, vocab_id: int | None) -> None:
        vocab = self._repo.get(vocab_id) if vocab_id is not None else None
        dialog = WordDialog(self._fonts.urdu, self._repo.categories(), vocab)
        dialog.setWindowIcon(self.windowIcon())
        while dialog.exec() == WordDialog.DialogCode.Accepted:
            try:
                if vocab is None:
                    existing = self._repo.find(dialog.values()["korean"], dialog.values()["meaning_en"])
                    if existing is not None:
                        raise ValueError("This word (same Korean and English meaning) is already in your library.")
                    self._repo.add_word(**dialog.values())
                else:
                    self._repo.update_word(vocab.id, **dialog.values())
            except ValueError as exc:
                dialog.show_error(str(exc))  # keep the form open so nothing typed is lost
                continue
            self._after_change()
            return

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        names = ", ".join(self._repo.get(i).korean for i in ids[:5]) + (" …" if len(ids) > 5 else "")
        answer = QMessageBox.question(
            self,
            "Delete words",
            f"Delete {len(ids)} word(s): {names}?\n\nTheir review history is deleted too. "
            "Tip: daily backups are in the Import & backup tab.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for vocab_id in ids:
            self._repo.delete_word(vocab_id)
        self._after_change()

    def _after_change(self) -> None:
        self._reload_categories()
        self.refresh_library()
        self._widget.refresh_current()

    # ------------------------------------------------------------ history tab

    def _build_history_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        self._history = QTableWidget(0, 5)
        self._history.setHorizontalHeaderLabels(("When", "Korean", "Meaning", "Your rating", "Next review after"))
        self._history.verticalHeader().setVisible(False)
        self._history.setAlternatingRowColors(True)
        self._history.setShowGrid(False)
        self._history.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for col, width in enumerate((150, 140, 300, 110)):
            self._history.setColumnWidth(col, width)
        self._history.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._history)
        self._history_note = QLabel(objectName="statLabel")
        layout.addWidget(self._history_note)
        return tab

    def refresh_history(self) -> None:
        rows = self._repo.review_history()
        self._history.setRowCount(len(rows))
        for i, (when, korean, meaning, rating, interval) in enumerate(rows):
            cells = (
                when.astimezone().strftime("%Y-%m-%d %H:%M"), korean, meaning,
                RATING_NAMES.get(rating, rating), srs.describe_interval(interval),
            )
            for col, text in enumerate(cells):
                self._history.setItem(i, col, _item(text))
        self._history_note.setText(
            f"Showing the latest {len(rows)} ratings." if rows else "No ratings yet - rate words on the card."
        )

    # --------------------------------------------------------------- stats tab

    def refresh_stats(self) -> None:
        layout = self._stats_holder.layout()
        while layout.count():
            layout.takeAt(0).widget().deleteLater()
        layout.addWidget(StatsPanel(
            self._repo.stats(), self._settings.daily_goal, theme.palette(self._settings.theme), self._fonts
        ))
        layout.addStretch(1)

    # ---------------------------------------------------------------- data tab

    def _build_data_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)

        transfer_box = QGroupBox("Import / export words")
        t = QVBoxLayout(transfer_box)
        t.addWidget(QLabel(
            "CSV opens in Excel (UTF-8, Korean and Urdu included). JSON keeps the same format as the built-in list.\n"
            "Importing adds new words only; words already in your library (same Korean + English meaning) are skipped.",
            objectName="statLabel",
        ))
        row = QHBoxLayout()
        row.addWidget(self._button("Import words from CSV / JSON…", self.import_words))
        row.addWidget(self._button("Export all words…", self.export_words))
        row.addWidget(self._button("Check for new words online", self._widget.check_for_words))
        row.addStretch(1)
        t.addLayout(row)
        layout.addWidget(transfer_box)

        backup_box = QGroupBox("Backups of your progress")
        b = QVBoxLayout(backup_box)
        b.addWidget(QLabel(
            "A backup is made automatically every day (the last 14 are kept). Restoring replaces your current "
            "words and progress, but the current state is saved first, so you can always go back.",
            objectName="statLabel", wordWrap=True,
        ))
        self._backups = QListWidget()
        self._backups.itemSelectionChanged.connect(
            lambda: self._btn_restore.setEnabled(bool(self._backups.selectedItems()))
        )
        b.addWidget(self._backups, 1)
        row = QHBoxLayout()
        row.addWidget(self._button("Back up now", self.backup_now))
        self._btn_restore = self._button("Restore selected backup…", self.restore_selected)
        self._btn_restore.setEnabled(False)
        row.addWidget(self._btn_restore)
        row.addWidget(self._button("Open data folder", self._widget.open_data_folder))
        row.addStretch(1)
        b.addLayout(row)
        layout.addWidget(backup_box, 1)
        return tab

    def refresh_backups(self) -> None:
        self._backups.clear()
        for path in backup.list_backups(paths.backup_dir()):
            stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            item = QListWidgetItem(f"{stamp}    {path.name}    ({path.stat().st_size // 1024} KB)")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self._backups.addItem(item)

    def import_words(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Import words", str(Path.home()), "Word lists (*.csv *.json)")
        if not name:
            return
        try:
            entries = transfer.read_file(Path(name))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Import failed", f"Could not read the file:\n{exc}")
            return
        backup.manual_backup(self._conn, paths.backup_dir(), label="before-import")
        added, skipped, problems = self._repo.import_entries(entries)
        message = f"Added {added} new word(s). Skipped {skipped} already in your library."
        if problems:
            message += f"\n\n{len(problems)} row(s) could not be imported:\n" + "\n".join(problems[:10])
            if len(problems) > 10:
                message += f"\n… and {len(problems) - 10} more."
        QMessageBox.information(self, "Import finished", message)
        self._after_change()
        self.refresh_backups()

    def export_words(self) -> None:
        default = str(Path.home() / f"hangulflow-words-{datetime.now():%Y%m%d}.csv")
        name, _ = QFileDialog.getSaveFileName(self, "Export words", default, "CSV for Excel (*.csv);;JSON (*.json)")
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() not in (".csv", ".json"):
            path = path.with_suffix(".csv")
        try:
            entries = self._repo.export_entries()
            transfer.write_file(entries, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", f"Could not write the file:\n{exc}")
            return
        QMessageBox.information(self, "Export finished", f"Exported {len(entries)} words to:\n{path}")

    def backup_now(self) -> None:
        try:
            target = backup.manual_backup(self._conn, paths.backup_dir())
        except (sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        self.refresh_backups()
        QMessageBox.information(self, "Backup saved", f"Saved {target.name}")

    def restore_selected(self) -> None:
        items = self._backups.selectedItems()
        if not items:
            return
        source = Path(items[0].data(Qt.ItemDataRole.UserRole))
        answer = QMessageBox.question(
            self,
            "Restore backup",
            f"Replace your current words and progress with:\n{source.name}?\n\n"
            "Your current state is saved as a backup first.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            safety = backup.restore(self._conn, source, paths.backup_dir())
        except (sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Restore failed", f"Nothing was changed.\n\n{exc}")
            return
        self.refresh_all()
        self._widget.refresh_current()
        QMessageBox.information(self, "Restored", f"Restored {source.name}.\nThe previous state was saved as {safety.name}.")

    # ------------------------------------------------------------ settings tab

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(12, 12, 12, 12)
        box = QGroupBox("Desktop card")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        s, w = self._settings, self._widget

        def combo(items: list[tuple[str, object]], current, apply) -> QComboBox:
            c = QComboBox()
            for label, value in items:
                c.addItem(label, value)
            c.setCurrentIndex(max(0, c.findData(current)))
            c.currentIndexChanged.connect(lambda _i: (apply(c.currentData()), w.rebuild_menu()))
            return c

        def check(text: str, checked: bool, apply) -> QCheckBox:
            c = QCheckBox(text)
            c.setChecked(checked)
            c.toggled.connect(lambda on: (apply(on), w.rebuild_menu()))
            return c

        form.addRow("Theme", combo([(p.name, p.key) for p in theme.PALETTES.values()], s.theme, w.set_theme))
        form.addRow("New word every", combo([(f"{m} min", m) for m in INTERVAL_CHOICES], s.interval_minutes, w.set_interval))
        form.addRow("Daily goal", combo([(f"{g} words", g) for g in DAILY_GOAL_CHOICES], s.daily_goal, w.set_daily_goal))
        form.addRow("Card direction", combo([(DIRECTION_NAMES[d], d) for d in CARD_DIRECTIONS], s.card_direction, w.set_card_direction))
        form.addRow("Window position", combo([(LAYER_NAMES[l], l) for l in LAYERS], s.layer, w.set_layer))
        form.addRow("", check("Show meanings immediately (no Reveal step)", s.reveal_mode == "shown", w.set_show_meanings))
        form.addRow("", check("Compact card", s.compact, w.set_compact))
        form.addRow("", check("Pause when away, locked or a fullscreen app is running", s.auto_pause, w.set_auto_pause))
        form.addRow("", check("Start HangulFlow when I sign in to Windows", startup.is_enabled(), w.set_start_with_windows))
        form.addRow("", check("Download new words online once a day", s.auto_update, w.set_auto_update))
        levels = QHBoxLayout()
        for level, name in LEVEL_NAMES.items():
            levels.addWidget(check(name, level in s.levels, lambda on, n=level: w.set_level(n, on)))
        levels.addStretch(1)
        form.addRow("Levels to study", levels)
        outer.addWidget(box)
        outer.addWidget(QLabel(
            "These are the same options as the card's right-click menu. Changes apply immediately.",
            objectName="statLabel",
        ))
        outer.addStretch(1)
        return tab

    # ---------------------------------------------------------------- general

    def _on_tab_changed(self, index: int) -> None:
        refreshers = {1: self.refresh_history, 2: self.refresh_stats, 3: self.refresh_backups, 4: self.refresh_settings}
        if index in refreshers:
            refreshers[index]()

    def refresh_settings(self) -> None:
        """Rebuild the Settings tab so it reflects changes made from the card's menu."""
        index = self._tabs.indexOf(self._settings_tab)
        self._tabs.blockSignals(True)
        self._tabs.removeTab(index)
        self._settings_tab.deleteLater()
        self._settings_tab = self._build_settings_tab()
        self._tabs.insertTab(index, self._settings_tab, "Settings")
        self._tabs.setCurrentIndex(index)
        self._tabs.blockSignals(False)

    def refresh_all(self) -> None:
        self._reload_categories()
        self.refresh_library()
        self._on_tab_changed(self._tabs.currentIndex())

    def present(self) -> None:
        self.refresh_all()
        self.showNormal()
        self.raise_()
        self.activateWindow()
