"""Form for adding your own word or editing an existing one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ..repository import Vocab

PARTS_OF_SPEECH = ("", "noun", "verb", "adjective", "adverb", "expression", "grammar")


class WordDialog(QDialog):
    def __init__(self, urdu_font: str, categories: list[str] | None = None, vocab: Vocab | None = None) -> None:
        super().__init__(None)
        self.setObjectName("statsDialog")  # same themed background as the statistics window
        self.setWindowTitle("HangulFlow - Edit word" if vocab else "HangulFlow - Add my own word")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        hint = QLabel(
            "Fields marked * are required."
            if vocab
            else "Fields marked * are required. New words are saved to “My Words” and starred."
        )
        hint.setObjectName("statLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.korean = QLineEdit(placeholderText="e.g. 눈치")
        self.hanja = QLineEdit(placeholderText="optional, e.g. 努力")
        self.meaning_en = QLineEdit(placeholderText="e.g. tact, reading the room")
        self.meaning_ur = self._urdu(QLineEdit(placeholderText="مثلاً: سمجھ بوجھ"), urdu_font)
        self.romanization = QLineEdit(placeholderText="optional, e.g. nunchi")
        self.part_of_speech = QComboBox()
        self.part_of_speech.addItems(PARTS_OF_SPEECH)
        self.part_of_speech.setEditable(True)
        self.example_ko = QLineEdit(placeholderText="optional Korean example sentence")
        self.example_en = QLineEdit(placeholderText="optional English translation")
        self.example_ur = self._urdu(QLineEdit(placeholderText="اختیاری اردو ترجمہ"), urdu_font)
        self.notes = QLineEdit(placeholderText="optional notes, collocations…")
        self.synonyms = QLineEdit(placeholderText="optional, comma-separated, e.g. 애쓰다")
        self.antonyms = QLineEdit(placeholderText="optional, comma-separated, e.g. 게으르다")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(sorted(set(categories or []) | {"My Words"}))
        self.category.setCurrentText("My Words")
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 3)
        self.difficulty.setValue(2)
        self.difficulty.setToolTip("1 = beginner, 2 = intermediate, 3 = advanced (your own estimate)")

        form.addRow("Korean *", self.korean)
        form.addRow("Hanja", self.hanja)
        form.addRow("English meaning *", self.meaning_en)
        form.addRow("Urdu meaning", self.meaning_ur)
        form.addRow("Romanization", self.romanization)
        form.addRow("Part of speech", self.part_of_speech)
        form.addRow("Example (Korean)", self.example_ko)
        form.addRow("Example (English)", self.example_en)
        form.addRow("Example (Urdu)", self.example_ur)
        form.addRow("Notes", self.notes)
        form.addRow("Similar words", self.synonyms)
        form.addRow("Opposites", self.antonyms)
        form.addRow("Category", self.category)
        form.addRow("Level (1-3)", self.difficulty)
        layout.addLayout(form)

        self.error = QLabel(objectName="statLabel")
        self.error.setStyleSheet("color: #E5484D;")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if vocab is not None:
            self._fill(vocab)

    def _fill(self, v: Vocab) -> None:
        for name in ("korean", "hanja", "meaning_en", "meaning_ur", "romanization", "example_ko",
                     "example_en", "example_ur", "notes", "synonyms", "antonyms"):
            getattr(self, name).setText(getattr(v, name))
        self.part_of_speech.setCurrentText(v.part_of_speech)
        self.category.setCurrentText(v.category)
        self.difficulty.setValue(v.difficulty)

    @staticmethod
    def _urdu(edit: QLineEdit, font_family: str) -> QLineEdit:
        edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        edit.setStyleSheet(f'font-family: "{font_family}"; font-size: 12pt;')
        return edit

    def show_error(self, text: str) -> None:
        self.error.setText(text)

    def _try_accept(self) -> None:
        if not self.korean.text().strip() or not self.meaning_en.text().strip():
            self.show_error("Please enter the Korean word and its English meaning.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "korean": self.korean.text(),
            "hanja": self.hanja.text(),
            "meaning_en": self.meaning_en.text(),
            "meaning_ur": self.meaning_ur.text(),
            "romanization": self.romanization.text(),
            "part_of_speech": self.part_of_speech.currentText(),
            "example_ko": self.example_ko.text(),
            "example_en": self.example_en.text(),
            "example_ur": self.example_ur.text(),
            "notes": self.notes.text(),
            "synonyms": self.synonyms.text(),
            "antonyms": self.antonyms.text(),
            "category": self.category.currentText(),
            "difficulty": self.difficulty.value(),
        }
