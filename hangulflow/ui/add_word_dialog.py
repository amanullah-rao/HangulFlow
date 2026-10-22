"""Quick form for adding your own word (e.g. one you just met in a lecture or article)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

PARTS_OF_SPEECH = ("", "noun", "verb", "adjective", "adverb", "expression", "grammar")


class AddWordDialog(QDialog):
    def __init__(self, urdu_font: str) -> None:
        super().__init__(None)
        self.setObjectName("statsDialog")  # same themed background as the statistics window
        self.setWindowTitle("HangulFlow - Add my own word")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        hint = QLabel("Fields marked * are required. The word is saved to “My Words” and starred.")
        hint.setObjectName("statLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.korean = QLineEdit(placeholderText="e.g. 눈치")
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

        form.addRow("Korean *", self.korean)
        form.addRow("English meaning *", self.meaning_en)
        form.addRow("Urdu meaning", self.meaning_ur)
        form.addRow("Romanization", self.romanization)
        form.addRow("Part of speech", self.part_of_speech)
        form.addRow("Example (Korean)", self.example_ko)
        form.addRow("Example (English)", self.example_en)
        form.addRow("Example (Urdu)", self.example_ur)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)

        self.error = QLabel(objectName="statLabel")
        self.error.setStyleSheet("color: #E5484D;")
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _urdu(edit: QLineEdit, font_family: str) -> QLineEdit:
        edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        edit.setStyleSheet(f'font-family: "{font_family}"; font-size: 12pt;')
        return edit

    def _try_accept(self) -> None:
        if not self.korean.text().strip() or not self.meaning_en.text().strip():
            self.error.setText("Please enter the Korean word and its English meaning.")
            return
        self.accept()

    def values(self) -> dict[str, str]:
        return {
            "korean": self.korean.text(),
            "meaning_en": self.meaning_en.text(),
            "meaning_ur": self.meaning_ur.text(),
            "romanization": self.romanization.text(),
            "part_of_speech": self.part_of_speech.currentText(),
            "example_ko": self.example_ko.text(),
            "example_en": self.example_en.text(),
            "example_ur": self.example_ur.text(),
            "notes": self.notes.text(),
        }
