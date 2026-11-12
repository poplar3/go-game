"""График шансов на победу по ходу партии."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class WinrateGraph(QWidget):
    move_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values: dict[int, float] = {}  # номер хода -> шанс чёрных 0..1
        self.marks: dict[int, str] = {}  # номер хода -> знак ошибки
        self.total = 0
        self.current = 0
        self.setMinimumHeight(90)
        self.setToolTip("Шансы чёрных на победу по оценке ИИ. Щёлкните, чтобы перейти к ходу.")

    def set_data(self, values: dict[int, float], total: int, marks: dict[int, str]) -> None:
        self.values = values
        self.total = total
        self.marks = marks
        self.update()

    def set_current(self, n: int) -> None:
        self.current = n
        self.update()

    def _x(self, n: int) -> float:
        w = self.width() - 10
        return 5 + (n / max(1, self.total)) * w

    def _y(self, v: float) -> float:
        h = self.height() - 10
        return 5 + (1 - v) * h

    def mousePressEvent(self, e):
        if self.total:
            n = round((e.position().x() - 5) / max(1, self.width() - 10) * self.total)
            self.move_selected.emit(max(0, min(self.total, n)))

    def paintEvent(self, e):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.fillRect(self.rect(), QColor("#f4f1ea"))
        qp.setPen(QPen(QColor("#bbb"), 1, Qt.DashLine))
        qp.drawLine(QPointF(5, self._y(0.5)), QPointF(self.width() - 5, self._y(0.5)))
        if not self.values:
            qp.setPen(QColor("#888"))
            qp.drawText(self.rect(), Qt.AlignCenter, "Здесь появится график после разбора партии")
            return
        pts = sorted(self.values.items())
        path = QPainterPath()
        path.moveTo(self._x(pts[0][0]), self._y(0))
        for n, v in pts:
            path.lineTo(self._x(n), self._y(v))
        path.lineTo(self._x(pts[-1][0]), self._y(0))
        path.closeSubpath()
        qp.fillPath(path, QColor(40, 40, 40, 160))
        for n, mark in self.marks.items():
            if mark in ("?", "??"):
                col = QColor("#d33") if mark == "??" else QColor("#e90")
                qp.setPen(QPen(col, 2))
                qp.drawLine(QPointF(self._x(n), 5), QPointF(self._x(n), self.height() - 5))
        qp.setPen(QPen(QColor("#2a7"), 2))
        qp.drawLine(QPointF(self._x(self.current), 0), QPointF(self._x(self.current), self.height()))
        qp.setPen(QColor("#333"))
        qp.drawText(QRectF(6, 2, 200, 16), Qt.AlignLeft, "чёрные")
        qp.drawText(QRectF(6, self.height() - 18, 200, 16), Qt.AlignLeft, "белые")
