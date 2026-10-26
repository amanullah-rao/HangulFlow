"""The always-on-top floating vocabulary card."""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import paths, presence, srs, startup
from ..repository import Vocab, VocabRepository
from ..rotation import WordSession
from ..settings import (
    DAILY_GOAL_CHOICES,
    INTERVAL_CHOICES,
    LEVEL_NAMES,
    MAX_WIDTH,
    MIN_WIDTH,
    MIXED_REVERSE_SHARE,
    Settings,
    SettingsStore,
)
from . import desktop_layer, theme
from .word_dialog import WordDialog
from .speech import INSTALL_HINT, KoreanSpeaker
from .stats_dialog import StatsDialog

RATING_BUTTONS = (  # (rating, label, key)
    (srs.UNKNOWN, "Unknown", "1"),
    (srs.DIFFICULT, "Difficult", "2"),
    (srs.KNOWN, "Known", "3"),
)
RATING_OBJECT_NAMES = {srs.UNKNOWN: "rateUnknown", srs.DIFFICULT: "rateDifficult", srs.KNOWN: "rateKnown"}

OPACITY_CHOICES = (1.0, 0.95, 0.9, 0.8, 0.7, 0.6)
PRESENCE_CHECK_MS = 10_000
AWAY_STATUS = {
    presence.LOCKED: "Paused · PC locked",
    presence.AWAY: "Paused · you're away",
    presence.FULLSCREEN: "Paused · fullscreen app",
}
CORNER_RADIUS = 14
RESIZE_HANDLE_WIDTH = 6


class _ResizeHandle(QWidget):
    """Invisible strip on the left/right edge that starts a native horizontal resize."""

    def __init__(self, parent: QWidget, edge: Qt.Edge) -> None:
        super().__init__(parent)
        self._edge = edge
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self._edge)
            event.accept()


class VocabWidget(QWidget):
    hidden_by_user = Signal()
    pause_changed = Signal(bool)
    quit_requested = Signal()
    library_requested = Signal()
    data_changed = Signal()  # the widget changed words (e.g. added one); the library should refresh

    def __init__(
        self,
        repo: VocabRepository,
        session: WordSession,
        settings: Settings,
        store: SettingsStore,
        fonts: theme.Fonts,
    ) -> None:
        super().__init__(None)
        self._repo = repo
        self._session = session
        self._settings = settings
        self._store = store
        self._fonts = fonts
        self._vocab: Vocab | None = None
        self._revealed = settings.reveal_mode == "shown"
        self._fitting = False
        self._remaining_s = float(settings.interval_minutes * 60)
        self._deadline = 0.0
        self._away: str | None = None  # why the learner isn't looking (see presence.py)
        self._auto_hidden = False  # hidden by us for a fullscreen app, not by the user
        self._desktop_pin = desktop_layer.DesktopPin()
        self._flash_text = ""
        self._flash_until = 0.0  # status line shows _flash_text until then (e.g. "Copied ✓")
        self._reverse = False  # current card shows the meaning first
        self._rng = random.Random()
        self._speaker = KoreanSpeaker(self)

        self.setWindowTitle("HangulFlow")
        self.setWindowFlags(self._window_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setWindowOpacity(settings.opacity)
        self.setMinimumWidth(MIN_WIDTH)
        self.setMaximumWidth(MAX_WIDTH)

        self._build_ui()
        self._updater = None  # WordUpdater, attached by the app via set_updater()
        self._manual_word_check = False
        self._menu = self._build_menu()
        self._more_button.setMenu(self._menu)

        self._rotate_timer = QTimer(self)
        self._rotate_timer.setSingleShot(True)
        self._rotate_timer.timeout.connect(self._on_rotate)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._update_countdown)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save_now)
        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(PRESENCE_CHECK_MS)
        self._presence_timer.timeout.connect(self._check_presence)
        self._presence_timer.start()

        self._refresh_pause_button()
        self._refresh_goal()
        self._show_vocab(self._session.start(settings.current_vocab_id), animate=False)
        self._restore_geometry()
        self._update_countdown()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self._text_labels: list[QLabel] = []
        self._last_selected: QLabel | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 12, 12)
        root.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(2)
        self._category = QLabel(objectName="category")
        header.addWidget(self._category, 1)
        self._star_button = self._icon_button("star", "Save to favourites", self.toggle_star)
        header.addWidget(self._star_button)
        self._compact_button = self._icon_button("compact", "Compact mode", lambda: self._act_compact.toggle())
        self._hide_button = self._icon_button("hide", "Hide to tray (HangulFlow keeps running)", self.hide_to_tray)
        self._more_button = self._icon_button("more", "Settings", None)
        self._more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        for button in (self._compact_button, self._hide_button, self._more_button):
            header.addWidget(button)
        root.addLayout(header)

        # Everything that changes per word lives in `_content`, so it can fade in.
        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 6, 0)
        content.setSpacing(4)

        self._korean = self._label("korean")
        self._hanja = self._selectable(QLabel(objectName="hanja"))
        self._hanja.setToolTip("Hanja (Chinese characters). Words sharing a character often share meaning.")
        self._romanization = self._label("romanization")
        self._meaning_en = self._label("meaningEn")
        self._meaning_ur = self._label("meaningUr", rtl=True)
        self._divider = QFrame(objectName="divider")
        self._example_ko = self._label("exampleKo")
        self._example_en = self._label("exampleEn")
        self._example_ur = self._label("exampleUr", rtl=True)
        self._notes = self._label("notes")

        word_row = QHBoxLayout()
        word_row.setSpacing(10)
        word_row.addWidget(self._korean)
        word_row.addWidget(self._hanja, 0, Qt.AlignmentFlag.AlignBottom)
        word_row.addStretch(1)
        self._speak_word_button = self._icon_button("speak", "Listen to the word (S)", self.speak_word)
        word_row.addWidget(self._speak_word_button, 0, Qt.AlignmentFlag.AlignVCenter)
        content.addLayout(word_row)
        content.addWidget(self._romanization)
        content.addSpacing(4)
        content.addWidget(self._meaning_en)
        content.addWidget(self._meaning_ur)
        content.addSpacing(2)
        content.addWidget(self._divider)
        content.addSpacing(2)
        example_row = QHBoxLayout()
        example_row.setSpacing(4)
        example_row.addWidget(self._example_ko, 1)
        self._speak_example_button = self._icon_button("speak", "Listen to the example sentence", self.speak_example)
        example_row.addWidget(self._speak_example_button, 0, Qt.AlignmentFlag.AlignTop)
        content.addLayout(example_row)
        content.addWidget(self._example_en)
        content.addWidget(self._example_ur)
        content.addWidget(self._notes)

        self._reveal_button = QPushButton("Reveal meaning", objectName="revealButton")
        self._reveal_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reveal_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._reveal_button.setToolTip("Show the English and Urdu meanings (Space)")
        self._reveal_button.clicked.connect(self.reveal)
        reveal_row = QHBoxLayout()
        reveal_row.setContentsMargins(0, 4, 0, 0)
        reveal_row.addWidget(self._reveal_button)
        reveal_row.addStretch(1)
        content.addLayout(reveal_row)

        # Shown once the meaning is visible: how well did you know it?
        self._rating_row = QWidget()
        rating_layout = QHBoxLayout(self._rating_row)
        rating_layout.setContentsMargins(0, 6, 0, 0)
        rating_layout.setSpacing(6)
        self._rating_buttons: dict[str, QPushButton] = {}
        for rating, text, key in RATING_BUTTONS:
            button = QPushButton(text, objectName=RATING_OBJECT_NAMES[rating])
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, r=rating: self.rate(r))
            rating_layout.addWidget(button, 1)
            self._rating_buttons[rating] = button
        content.addWidget(self._rating_row)

        self._fade = QGraphicsOpacityEffect(self._content)
        self._fade.setOpacity(1.0)
        self._content.setGraphicsEffect(self._fade)
        self._fade_anim = QPropertyAnimation(self._fade, b"opacity", self)
        self._fade_anim.setDuration(240)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        root.addWidget(self._content)

        root.addSpacing(4)
        self._countdown = QProgressBar(objectName="countdown")
        self._countdown.setRange(0, 1000)
        self._countdown.setTextVisible(False)
        self._countdown.setFixedHeight(3)
        root.addWidget(self._countdown)

        footer = QHBoxLayout()
        footer.setSpacing(2)
        self._prev_button = self._icon_button("prev", "Previous word (←)", self.go_previous)
        self._pause_button = self._icon_button("pause", "Pause automatic rotation (P)", self.toggle_pause)
        self._next_button = self._icon_button("next", "Next word (→)", self.go_next)
        footer.addWidget(self._prev_button)
        footer.addWidget(self._pause_button)
        footer.addWidget(self._next_button)
        footer.addStretch(1)
        self._goal = QLabel(objectName="goal")
        self._goal.setToolTip("Words rated today / daily goal")
        footer.addWidget(self._goal)
        self._status = QLabel(objectName="status")
        footer.addWidget(self._status)
        root.addLayout(footer)

        self._left_handle = _ResizeHandle(self, Qt.Edge.LeftEdge)
        self._right_handle = _ResizeHandle(self, Qt.Edge.RightEdge)

    def _selectable(self, label: QLabel) -> QLabel:
        """Let the user highlight text with the mouse and copy it (Ctrl+C)."""
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # Right-click goes to the card's own menu (which has Copy entries) instead
        # of QLabel's built-in one.
        label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        label.installEventFilter(self)
        self._text_labels.append(label)
        return label

    def eventFilter(self, obj, event) -> bool:
        # Starting a selection in one line clears the highlight in the others, so
        # "Copy selected text" always copies what the user selected last.
        if event.type() == QEvent.Type.MouseButtonPress and obj in self._text_labels:
            for label in self._text_labels:
                if label is not obj and label.hasSelectedText():
                    label.setSelection(0, 0)
            self._last_selected = obj
        # A plain click (not a text selection) on the card's text reveals the answer.
        elif (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and obj in self._text_labels
            and not self._revealed
            and not obj.hasSelectedText()
        ):
            QTimer.singleShot(0, self.reveal)
        return super().eventFilter(obj, event)

    def _label(self, name: str, rtl: bool = False) -> QLabel:
        label = self._selectable(QLabel(objectName=name))
        label.setWordWrap(True)
        if rtl:
            label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _icon_button(self, glyph: str, tooltip: str, slot) -> QToolButton:
        button = QToolButton(objectName="iconButton")
        button.setText(self._fonts.glyph(glyph))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if slot is not None:
            button.clicked.connect(slot)
        return button

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        # "\t" shows the hint on the right; Ctrl+C itself is handled by the labels.
        self._act_copy_selection = menu.addAction("Copy selected text\tCtrl+C", self.copy_selection)
        menu.addAction("Copy word", self.copy_word)
        menu.addAction("Copy whole card", self.copy_card)
        menu.aboutToShow.connect(lambda: self._act_copy_selection.setEnabled(self._selected_text() != ""))
        menu.addSeparator()

        menu.addAction("Open library (all words, search, import/export)…", self.library_requested.emit)
        menu.addAction("Add my own word…", self.add_word)
        menu.addAction("Mark as learned (skip for 2 months)", self.mark_learned)
        menu.addAction("Statistics…", self.show_statistics)
        goal_menu = menu.addMenu("Daily goal")
        goal_group = QActionGroup(self)
        for goal in DAILY_GOAL_CHOICES:
            action = goal_menu.addAction(f"{goal} words")
            action.setCheckable(True)
            action.setChecked(goal == self._settings.daily_goal)
            action.triggered.connect(lambda _checked=False, g=goal: self.set_daily_goal(g))
            goal_group.addAction(action)
        menu.addSeparator()

        interval_menu = menu.addMenu("Change word every")
        interval_group = QActionGroup(self)
        for minutes in INTERVAL_CHOICES:
            action = interval_menu.addAction(f"{minutes} minute" + ("" if minutes == 1 else "s"))
            action.setCheckable(True)
            action.setChecked(minutes == self._settings.interval_minutes)
            action.triggered.connect(lambda _checked=False, m=minutes: self.set_interval(m))
            interval_group.addAction(action)

        theme_menu = menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        for p in theme.PALETTES.values():
            action = theme_menu.addAction(p.name)
            action.setCheckable(True)
            action.setChecked(p.key == self._settings.theme)
            action.triggered.connect(lambda _checked=False, k=p.key: self.set_theme(k))
            theme_group.addAction(action)

        opacity_menu = menu.addMenu("Opacity")
        opacity_group = QActionGroup(self)
        for value in OPACITY_CHOICES:
            action = opacity_menu.addAction(f"{round(value * 100)}%")
            action.setCheckable(True)
            action.setChecked(abs(value - self._settings.opacity) < 0.001)
            action.triggered.connect(lambda _checked=False, v=value: self.set_opacity(v))
            opacity_group.addAction(action)

        menu.addSeparator()
        level_menu = menu.addMenu("Levels to study")
        for level, name in LEVEL_NAMES.items():
            action = level_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(level in self._settings.levels)
            action.toggled.connect(lambda on, n=level: self.set_level(n, on))
        direction_menu = menu.addMenu("Card direction")
        direction_group = QActionGroup(self)
        for key, label in (
            ("korean", "Korean first (recognise the meaning)"),
            ("meaning", "Meaning first (recall the Korean)"),
            ("mixed", "Mixed (about 3 in 10 reversed)"),
        ):
            action = direction_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == self._settings.card_direction)
            action.triggered.connect(lambda _checked=False, k=key: self.set_card_direction(k))
            direction_group.addAction(action)
        self._act_show_meanings = self._check_action(
            menu, "Show meanings immediately", self._settings.reveal_mode == "shown", self.set_show_meanings
        )
        self._act_compact = self._check_action(menu, "Compact mode", self._settings.compact, self.set_compact)
        layer_menu = menu.addMenu("Window position")
        layer_group = QActionGroup(self)
        for key, label in (
            ("desktop", "On desktop only (behind other windows)"),
            ("normal", "Normal window"),
            ("top", "Always on top"),
        ):
            action = layer_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == self._settings.layer)
            action.triggered.connect(lambda _checked=False, k=key: self.set_layer(k))
            layer_group.addAction(action)
        self._act_auto_pause = self._check_action(
            menu, "Pause when away, locked or fullscreen", self._settings.auto_pause, self.set_auto_pause
        )
        self._act_startup = self._check_action(menu, "Start with Windows", startup.is_enabled(), self.set_start_with_windows)
        self._check_action(menu, "Get new words online (daily)", self._settings.auto_update, self.set_auto_update)
        menu.addAction("Check for new words now", self.check_for_words)
        menu.addAction("Open data folder (backups, logs)", self.open_data_folder)

        menu.addSeparator()
        menu.addAction("Hide to tray", self.hide_to_tray)
        menu.addAction("Quit HangulFlow", self.quit_requested.emit)
        return menu

    def rebuild_menu(self) -> None:
        """Re-create the menu so its check marks match settings changed elsewhere (the library window)."""
        old = self._menu
        self._menu = self._build_menu()
        self._more_button.setMenu(self._menu)
        old.deleteLater()

    def _check_action(self, menu: QMenu, text: str, checked: bool, slot) -> QAction:
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(checked)
        action.toggled.connect(slot)
        return action

    # ------------------------------------------------------------- content

    def _show_vocab(self, vocab_id: int | None, animate: bool = True) -> None:
        self._vocab = self._repo.get(vocab_id) if vocab_id is not None else None
        v = self._vocab
        if v is None:
            self._category.setText("")
            self._korean.setText("단어 없음")
            self._hanja.setText("")
            self._romanization.setText("No vocabulary in the database yet.")
            for label in self._answer_labels():
                label.setText("")
        else:
            level = "●" * v.difficulty + "○" * max(0, 3 - v.difficulty)
            self._category.setText(f"{v.category.upper()}   {level}")
            self._category.setToolTip(
                f"{LEVEL_NAMES.get(v.difficulty, 'Level')} (curated estimate, not an official TOPIK level)"
            )
            self._korean.setText(v.korean)
            self._hanja.setText(v.hanja)
            self._romanization.setText(" · ".join(p for p in (v.romanization, v.part_of_speech) if p))
            self._meaning_en.setText(v.meaning_en)
            self._meaning_ur.setText(v.meaning_ur)
            example_ko, example_en, example_ur = v.example_for_display()
            self._example_ko.setText(example_ko)
            self._example_en.setText(example_en)
            self._example_ur.setText(example_ur)
            self._notes.setText(v.notes)

        direction = self._settings.card_direction
        self._reverse = v is not None and v.part_of_speech != "grammar" and (
            direction == "meaning" or (direction == "mixed" and self._rng.random() < MIXED_REVERSE_SHARE)
        )
        # A reversed card always starts hidden, otherwise there is nothing to recall.
        self._revealed = self._settings.reveal_mode == "shown" and not self._reverse
        self._refresh_star()
        self._prev_button.setEnabled(self._session.can_go_back)
        self._settings.current_vocab_id = v.id if v else None
        self._update_visibility()
        self._schedule_save()

        if animate:
            self._fade_anim.stop()
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()

    def _answer_labels(self) -> list[QLabel]:
        return [self._meaning_en, self._meaning_ur, self._example_ko, self._example_en, self._example_ur, self._notes]

    def _update_visibility(self) -> None:
        compact = self._settings.compact
        v = self._vocab
        show = self._revealed and v is not None
        # Reversed card, not yet revealed: show the meaning, hide everything that gives the Korean away.
        hide_korean = self._reverse and not self._revealed and v is not None
        if v is not None:
            self._korean.setText("?" if hide_korean else v.korean)
        show_meaning = (show or hide_korean)
        self._meaning_en.setVisible(show_meaning and bool(self._meaning_en.text()))
        self._meaning_ur.setVisible(show_meaning and bool(self._meaning_ur.text()))
        details = [self._example_ko, self._example_en, self._example_ur, self._notes]
        for label in details:
            label.setVisible(show and not compact and bool(label.text()))
        self._divider.setVisible(any(not label.isHidden() for label in details))
        self._romanization.setVisible(bool(self._romanization.text()) and not hide_korean)
        self._reveal_button.setVisible(v is not None and not self._revealed)
        reveal_text = "Show Korean word" if self._reverse else "Reveal meaning"
        if self._reveal_button.text() != reveal_text:
            self._reveal_button.setText(reveal_text)
            self._reveal_button.setMinimumWidth(self._reveal_button.sizeHint().width())
        self._speak_word_button.setVisible(v is not None and not hide_korean)
        self._speak_example_button.setVisible(not self._example_ko.isHidden())
        self._star_button.setVisible(v is not None)
        self._rating_row.setVisible(show)
        if show:
            state = self._repo.card_state(self._vocab.id)
            now = datetime.now(timezone.utc)
            for rating, text, key in RATING_BUTTONS:
                after = srs.schedule(state, rating, now)
                self._rating_buttons[rating].setToolTip(f"{text} ({key}) · back in {srs.describe_interval(after.interval_days)}")

        self._hanja.setVisible(bool(self._hanja.text()) and not hide_korean)
        self._korean.setProperty("placeholder", hide_korean)
        for label in (self._korean, self._hanja):
            label.setProperty("compact", compact)
            label.style().unpolish(label)
            label.style().polish(label)
        self._compact_button.setText(self._fonts.glyph("expand" if compact else "compact"))
        self._compact_button.setToolTip("Detailed mode" if compact else "Compact mode")
        self._fit_height()
        # Newly shown labels are re-polished by the event loop, which can change
        # their size hints; fit once more after that has happened.
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self) -> None:
        """Height always follows the content; the user controls only the width."""
        if self._fitting:
            return
        self._fitting = True
        try:
            layout = self.layout()
            layout.invalidate()
            layout.activate()
            height = self.heightForWidth(self.width()) if self.hasHeightForWidth() else -1
            if height <= 0:
                height = layout.sizeHint().height()
            # Widen the allowed range in the right order so min never exceeds max,
            # otherwise Windows rejects the geometry (QWindowsWindow::setGeometry warning).
            if height > self.maximumHeight():
                self.setMaximumHeight(height)
                self.setMinimumHeight(height)
            else:
                self.setMinimumHeight(height)
                self.setMaximumHeight(height)
        finally:
            self._fitting = False

    # ------------------------------------------------------------- actions

    def reveal(self) -> None:
        if not self._revealed:
            self._revealed = True
            self._update_visibility()

    def _selected_text(self) -> str:
        for label in (self._last_selected, QApplication.focusWidget()):
            if label in self._text_labels and label.hasSelectedText():
                return label.selectedText()
        return next((label.selectedText() for label in self._text_labels if label.hasSelectedText()), "")

    def _copy(self, text: str, what: str) -> None:
        if text:
            QApplication.clipboard().setText(text)
            self._flash_status(f"Copied {what} ✓")

    def copy_selection(self) -> None:
        self._copy(self._selected_text(), "selection")

    def copy_word(self) -> None:
        if self._vocab:
            self._copy(self._vocab.korean, "word")

    def copy_card(self) -> None:
        """Everything on the card as plain text, e.g. for notes or a chat."""
        v = self._vocab
        if v is None:
            return
        heading = f"{v.korean} ({v.hanja})" if v.hanja else v.korean
        lines = [
            heading,
            " · ".join(p for p in (v.romanization, v.part_of_speech) if p),
            f"English: {v.meaning_en}",
            f"Urdu: {v.meaning_ur}" if v.meaning_ur else "",
            "",
            *v.example_for_display(),
            "",
            f"Notes: {v.notes}" if v.notes else "",
        ]
        text = "\n".join(lines).strip()
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        self._copy(text, "card")

    def _flash_status(self, text: str, seconds: float = 1.5) -> None:
        self._flash_text = text
        self._flash_until = time.monotonic() + seconds
        self._update_countdown()
        QTimer.singleShot(int(seconds * 1000) + 50, self._update_countdown)

    def rate(self, rating: str) -> None:
        """Save how well the learner knew this word, then move on."""
        if self._vocab is None or not self._revealed:
            return
        after = self._repo.rate(self._vocab.id, rating)
        label = dict((r, t) for r, t, _ in RATING_BUTTONS)[rating]
        self.go_next()
        self._flash_status(f"{label} · back in {srs.describe_interval(after.interval_days)}", seconds=3)

    def mark_learned(self) -> None:
        if self._vocab is None:
            return
        self._repo.mark_learned(self._vocab.id)
        self.go_next()
        self._flash_status("Marked as learned ✓", seconds=3)

    def speak_word(self) -> None:
        if self._vocab is not None and (self._revealed or not self._reverse):
            self._speak(self._vocab.korean)

    def speak_example(self) -> None:
        if self._vocab is not None:
            self._speak(self._example_ko.text())

    def _speak(self, text: str) -> None:
        if not self._speaker.speak(text):
            self._flash_status("No Korean voice installed", seconds=4)
            self._speak_word_button.setToolTip(INSTALL_HINT)

    def toggle_star(self) -> None:
        if self._vocab is None:
            return
        starred = not self._vocab.starred
        self._repo.set_starred(self._vocab.id, starred)
        self._vocab = self._repo.get(self._vocab.id)
        self._refresh_star()
        self._flash_status("Saved to favourites ★" if starred else "Removed from favourites")

    def _refresh_star(self) -> None:
        starred = bool(self._vocab and self._vocab.starred)
        self._star_button.setText(self._fonts.glyph("starred" if starred else "star"))
        self._star_button.setToolTip("Remove from favourites" if starred else "Save to favourites")
        if self._star_button.property("active") != starred:
            self._star_button.setProperty("active", starred)
            self._star_button.style().unpolish(self._star_button)
            self._star_button.style().polish(self._star_button)

    def add_word(self) -> None:
        dialog = WordDialog(self._fonts.urdu, self._repo.categories())
        dialog.setWindowIcon(self.windowIcon())
        if dialog.exec() != WordDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        existing = self._repo.find(values["korean"], values["meaning_en"])
        if existing is not None:  # don't crash on the UNIQUE rule - just show the word
            self._repo.set_starred(existing, True)
            self.show_word(existing)
            self._flash_status("Already in your words - starred ★", seconds=3)
            return
        self.show_word(self._repo.add_word(**values))
        self.data_changed.emit()
        self._flash_status("Word added to My Words ★", seconds=3)

    def show_word(self, vocab_id: int) -> None:
        """Put a specific word on the card (e.g. chosen in the library)."""
        self._show_vocab(self._session.show(vocab_id))
        self._restart_cycle()
        if not self.isVisible():
            self.bring_to_front()

    def refresh_current(self) -> None:
        """Re-read the current word after the library edited, deleted or restored data."""
        current = self._vocab.id if self._vocab else None
        if current is not None and self._repo.get(current) is not None:
            self._show_vocab(current, animate=False)
        else:
            self._show_vocab(self._session.next(), animate=False)
        self._refresh_goal()

    def set_card_direction(self, direction: str) -> None:
        self._settings.card_direction = direction
        self._schedule_save()
        if self._vocab is not None:
            self._show_vocab(self._vocab.id, animate=False)  # re-apply to the current card

    def set_level(self, level: int, enabled: bool) -> None:
        levels = set(self._settings.levels)
        levels.add(level) if enabled else levels.discard(level)
        if not levels:  # at least one level must stay on
            self._flash_status("Keep at least one level", seconds=3)
            QTimer.singleShot(0, self.rebuild_menu)
            return
        self._settings.levels = sorted(levels)
        self._repo.study_levels = tuple(self._settings.levels)
        self._schedule_save()

    def set_daily_goal(self, goal: int) -> None:
        self._settings.daily_goal = goal
        self._refresh_goal()
        self._schedule_save()

    def _refresh_goal(self) -> None:
        done = self._repo.stats().rated_today
        goal = self._settings.daily_goal
        reached = done >= goal
        self._goal.setText(f"{'✓' if reached else '●'} {done}/{goal}")
        if self._goal.property("done") != reached:
            self._goal.setProperty("done", reached)
            self._goal.style().unpolish(self._goal)
            self._goal.style().polish(self._goal)

    def show_statistics(self) -> None:
        dialog = StatsDialog(self._repo.stats(), self._settings.daily_goal, theme.palette(self._settings.theme), self._fonts)
        dialog.setWindowIcon(self.windowIcon())
        dialog.exec()

    def go_next(self) -> None:
        self._show_vocab(self._session.next())
        self._refresh_goal()
        self._restart_cycle()

    def go_previous(self) -> None:
        if self._session.can_go_back:
            self._show_vocab(self._session.previous())
            self._restart_cycle()

    def toggle_pause(self) -> None:
        self._settings.paused = not self._settings.paused
        self._refresh_pause_button()
        self._sync_timers()
        self._schedule_save()
        self.pause_changed.emit(self._settings.paused)

    def _refresh_pause_button(self) -> None:
        paused = self._settings.paused
        self._pause_button.setText(self._fonts.glyph("play" if paused else "pause"))
        self._pause_button.setToolTip("Resume automatic rotation (P)" if paused else "Pause automatic rotation (P)")

    @property
    def is_paused(self) -> bool:
        return self._settings.paused

    def set_interval(self, minutes: int) -> None:
        self._settings.interval_minutes = minutes
        self._restart_cycle()
        self._schedule_save()

    def set_theme(self, key: str) -> None:
        self._settings.theme = key
        QApplication.instance().setStyleSheet(theme.stylesheet(self._fonts, theme.palette(key)))
        self.update()  # repaint the card background
        QTimer.singleShot(0, self._fit_height)
        self._schedule_save()

    def set_opacity(self, value: float) -> None:
        self._settings.opacity = value
        self.setWindowOpacity(value)
        self._schedule_save()

    def set_show_meanings(self, shown: bool) -> None:
        self._settings.reveal_mode = "shown" if shown else "hidden"
        self._revealed = shown or self._revealed
        self._update_visibility()
        self._schedule_save()

    def set_compact(self, compact: bool) -> None:
        self._settings.compact = compact
        self._update_visibility()
        self._schedule_save()

    def set_layer(self, layer: str) -> None:
        self._settings.layer = layer
        visible = self.isVisible()
        self.setWindowFlags(self._window_flags())  # changing flags hides the window
        if visible:
            self.show()
        self._schedule_save()

    @property
    def _on_desktop(self) -> bool:
        return self._settings.layer == "desktop" and desktop_layer.supported()

    def set_start_with_windows(self, enabled: bool) -> None:
        if startup.set_enabled(enabled):
            self._flash_status("Starts with Windows ✓" if enabled else "Won't start with Windows", seconds=3)
        else:
            self._act_startup.blockSignals(True)
            self._act_startup.setChecked(startup.is_enabled())
            self._act_startup.blockSignals(False)
            self._flash_status("Couldn't change the startup setting", seconds=4)

    def set_updater(self, updater) -> None:
        self._updater = updater
        updater.finished.connect(self._on_words_checked)

    def set_auto_update(self, enabled: bool) -> None:
        self._settings.auto_update = enabled
        self._schedule_save()
        if enabled and self._updater is not None:
            self._updater.check()

    def check_for_words(self) -> None:
        if self._updater is None:
            return
        self._manual_word_check = True
        self._updater.check(force=True)
        self._flash_status("Checking for new words…", seconds=5)

    def _on_words_checked(self, added: int, error: str) -> None:
        manual, self._manual_word_check = self._manual_word_check, False
        if added:
            self.data_changed.emit()
            self._flash_status(f"{added} new words downloaded", seconds=5)
        elif manual:
            self._flash_status(error or "Your word list is up to date", seconds=5)

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))

    def set_auto_pause(self, enabled: bool) -> None:
        self._settings.auto_pause = enabled
        self._check_presence()
        self._schedule_save()

    def _check_presence(self) -> None:
        reason = presence.current_away_reason() if self._settings.auto_pause else None
        if reason == self._away:
            return
        previous, self._away = self._away, reason
        # Only an always-on-top widget would cover a fullscreen video, so only it hides.
        if reason == presence.FULLSCREEN and self.isVisible() and self._settings.layer == "top":
            self._auto_hidden = True
            self.hide()
        elif previous == presence.FULLSCREEN and self._auto_hidden:
            self._auto_hidden = False
            self.show()
        self._sync_timers()

    def hide_to_tray(self) -> None:
        self.hide()
        self.hidden_by_user.emit()

    def toggle_visible(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.bring_to_front()

    def bring_to_front(self) -> None:
        self._auto_hidden = False  # the user asked for it, even during fullscreen
        self.show()
        if not self._on_desktop:
            self.raise_()

    def _window_flags(self) -> Qt.WindowType:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self._settings.layer == "top":
            flags |= Qt.WindowType.WindowStaysOnTopHint
        # "desktop" deliberately has no Qt flag: Qt's WindowStaysOnBottomHint forces
        # HWND_BOTTOM (below the desktop itself). DesktopPin manages the z-order instead.
        return flags

    # -------------------------------------------------------------- timers

    def _interval_s(self) -> float:
        return float(self._settings.interval_minutes * 60)

    def _on_rotate(self) -> None:
        self._show_vocab(self._session.next())
        self._restart_cycle()

    def _restart_cycle(self) -> None:
        self._rotate_timer.stop()
        self._tick_timer.stop()
        self._remaining_s = self._interval_s()
        self._sync_timers()

    def _sync_timers(self) -> None:
        """Run the countdown only while visible and not paused (no wasted CPU, no unseen words)."""
        should_run = self.isVisible() and not self._settings.paused and self._away is None
        if should_run and not self._rotate_timer.isActive():
            self._deadline = time.monotonic() + self._remaining_s
            self._rotate_timer.start(max(1000, int(self._remaining_s * 1000)))
            self._tick_timer.start()
        elif not should_run and self._rotate_timer.isActive():
            self._remaining_s = max(1.0, self._deadline - time.monotonic())
            self._rotate_timer.stop()
            self._tick_timer.stop()
        self._update_countdown()

    def _update_countdown(self) -> None:
        running = self._rotate_timer.isActive()
        remaining = max(0.0, self._deadline - time.monotonic()) if running else self._remaining_s
        total = self._interval_s()
        self._countdown.setValue(int(1000 * (1 - remaining / total)) if total else 0)

        paused = self._settings.paused or self._away is not None
        if self._countdown.property("paused") != paused:
            self._countdown.setProperty("paused", paused)
            self._countdown.style().unpolish(self._countdown)
            self._countdown.style().polish(self._countdown)
        if time.monotonic() < self._flash_until:
            self._status.setText(self._flash_text)
        elif self._settings.paused:
            self._status.setText("Paused")
        elif self._away is not None:
            self._status.setText(AWAY_STATUS[self._away])
        elif remaining >= 60:
            self._status.setText(f"Next in {math.ceil(remaining / 60)} min")
        else:
            self._status.setText(f"Next in {math.ceil(remaining)} s")

    # ------------------------------------------------------ geometry/state

    def _restore_geometry(self) -> None:
        self.resize(self._settings.width, self.height())
        self._fit_height()
        x, y = self._settings.x, self._settings.y
        if x is not None and y is not None and QGuiApplication.screenAt(QPoint(x + 40, y + 20)) is not None:
            self.move(x, y)
        else:
            area = QGuiApplication.primaryScreen().availableGeometry()
            self.move(area.right() - self.width() - 24, area.top() + 96)

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def save_now(self) -> None:
        self._save_timer.stop()
        self._settings.x = self.x()
        self._settings.y = self.y()
        self._settings.width = self.width()
        self._store.save(self._settings)

    # ---------------------------------------------------------------- events

    def nativeEvent(self, event_type, message):
        if self._desktop_pin.active and event_type == b"windows_generic_MSG":
            self._desktop_pin.filter_native_event(int(message))
        return super().nativeEvent(event_type, message)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._on_desktop:
            self._desktop_pin.enable(int(self.winId()))  # winId may change after setWindowFlags
        else:
            self._desktop_pin.disable()
        self._sync_timers()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._desktop_pin.disable()
        self._sync_timers()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self.isVisible():
            self._schedule_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        h = self.height()
        self._left_handle.setGeometry(0, CORNER_RADIUS, RESIZE_HANDLE_WIDTH, max(0, h - 2 * CORNER_RADIUS))
        self._right_handle.setGeometry(
            self.width() - RESIZE_HANDLE_WIDTH, CORNER_RADIUS, RESIZE_HANDLE_WIDTH, max(0, h - 2 * CORNER_RADIUS)
        )
        self._left_handle.raise_()
        self._right_handle.raise_()
        if event.oldSize().width() != event.size().width():
            QTimer.singleShot(0, self._fit_height)
            if self.isVisible():
                self._schedule_save()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()  # native drag, supports multi-monitor
            event.accept()
        else:
            super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self._menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if event.matches(QKeySequence.StandardKey.Copy):  # Ctrl+C when no label has focus
            self.copy_selection()
        elif key == Qt.Key.Key_Right:
            self.go_next()
        elif key == Qt.Key.Key_Left:
            self.go_previous()
        elif key == Qt.Key.Key_Space:
            self.reveal()
        elif key == Qt.Key.Key_P:
            self.toggle_pause()
        elif key == Qt.Key.Key_S:
            self.speak_word()
        elif key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.rate(RATING_BUTTONS[key - Qt.Key.Key_1][0])
        elif key == Qt.Key.Key_Escape:
            self.hide_to_tray()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, CORNER_RADIUS, CORNER_RADIUS)
        top, bottom, border = theme.card_colors(theme.palette(self._settings.theme))
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)
