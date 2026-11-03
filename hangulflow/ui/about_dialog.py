"""About HangulFlow: version, developer and links."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .. import AUTHOR_AFFILIATION, AUTHOR_URL, PROJECT_URL, __author__, __version__


class AboutDialog(QDialog):
    def __init__(self, word_count: int) -> None:
        super().__init__(None)
        self.setObjectName("aboutDialog")
        self.setWindowTitle("About HangulFlow")
        self.setMinimumWidth(380)

        text = QLabel(
            f"<h2 style='margin-bottom:0'>HangulFlow 한글플로</h2>"
            f"<p style='margin-top:2px'>Version {__version__}</p>"
            f"<p>Learn Korean vocabulary while you work, with meanings in English and Urdu "
            f"and spaced repetition. {word_count:,} words, from beginner to advanced.</p>"
            f"<p><b>Developed by {__author__}</b><br>"
            f"{AUTHOR_AFFILIATION}<br>"
            f"<a href='{AUTHOR_URL}'>{AUTHOR_URL.removeprefix('https://')}</a></p>"
            f"<p>Source code, updates and bug reports:<br>"
            f"<a href='{PROJECT_URL}'>{PROJECT_URL.removeprefix('https://')}</a></p>"
            f"<p style='color:gray'>© 2026 {__author__} · MIT License</p>"
        )
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.addWidget(text)
        layout.addWidget(buttons)
