"""A small statistics window: today, totals and the last 7 days."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

from ..repository import Stats
from . import theme


class _WeekChart(QWidget):
    """Seven bars, one per day; the goal is drawn as a dashed line."""

    def __init__(self, days: list[tuple[date, int]], goal: int, palette: theme.Palette, font_family: str) -> None:
        super().__init__()
        self._days, self._goal, self._p, self._font = days, goal, palette, font_family
        self.setMinimumHeight(130)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        label_h, top = 18, 16
        chart_h = h - label_h - top
        peak = max([self._goal] + [n for _, n in self._days]) or 1
        slot = w / len(self._days)
        font = QFont(self._font)
        font.setPixelSize(11)
        p.setFont(font)

        goal_y = top + chart_h * (1 - self._goal / peak)
        pen = p.pen()
        pen.setColor(QColor(self._p.faint))
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(0, int(goal_y), w, int(goal_y))

        for i, (day, count) in enumerate(self._days):
            x = i * slot + slot * 0.22
            bar_w = slot * 0.56
            bar_h = chart_h * count / peak
            color = QColor(self._p.accent)
            if count < self._goal:
                color.setAlpha(150)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, top + chart_h - bar_h, bar_w, max(bar_h, 2)), 3, 3)
            p.setPen(QColor(self._p.muted))
            if count:
                p.drawText(QRectF(x - 6, top + chart_h - bar_h - 15, bar_w + 12, 14), Qt.AlignmentFlag.AlignCenter, str(count))
            label = "Today" if i == len(self._days) - 1 else day.strftime("%a")
            p.drawText(QRectF(i * slot, h - label_h, slot, label_h), Qt.AlignmentFlag.AlignCenter, label)
        p.end()


class StatsDialog(QDialog):
    def __init__(self, stats: Stats, goal: int, palette: theme.Palette, fonts: theme.Fonts) -> None:
        super().__init__(None)
        self.setObjectName("statsDialog")
        self.setWindowTitle("HangulFlow - Statistics")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        def section(title: str) -> None:
            label = QLabel(title.upper(), objectName="statTitle")
            layout.addSpacing(4)
            layout.addWidget(label)

        def grid(items: list[tuple[str, str]]) -> None:
            g = QGridLayout()
            g.setHorizontalSpacing(18)
            g.setVerticalSpacing(0)
            for col, (value, text) in enumerate(items):
                g.addWidget(QLabel(value, objectName="statValue"), 0, col)
                g.addWidget(QLabel(text, objectName="statLabel"), 1, col)
            layout.addLayout(g)

        section("Today")
        grid([
            (f"{stats.rated_today}/{goal}", "words rated"),
            (str(stats.viewed_today), "words seen"),
            (f"{stats.streak_days}", "day streak" if stats.streak_days == 1 else "days streak"),
        ])
        section("All words")
        grid([
            (str(stats.new), "new"),
            (str(stats.learning), "learning"),
            (str(stats.learned), "learned"),
            (str(stats.due_now), "due now"),
        ])
        section("Last 7 days (words rated)")
        layout.addWidget(_WeekChart(stats.last_7_days, goal, palette, fonts.ui))
