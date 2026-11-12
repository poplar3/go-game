"""Виджет доски: рисует сетку, камни, метки и обрабатывает щелчки."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..board import BLACK, EMPTY, GTP_LETTERS, Board, Point, star_points

WOOD = QColor("#dcb35c")
WOOD_DARK = QColor("#c99f45")


class BoardWidget(QWidget):
    clicked = Signal(int, int)
    right_clicked = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.board = Board(19)
        self.last_move: Optional[Point] = None
        self.hover: Optional[Point] = None
        self.ghost_color: Optional[int] = BLACK  # цвет полупрозрачного камня под курсором
        self.interactive = True
        # Метки: точка -> (текст, цвет)
        self.labels: dict[Point, tuple[str, QColor]] = {}
        # Кружки-подсказки (лучший ход и др.): точка -> цвет
        self.circles: dict[Point, QColor] = {}
        # Режим подсчёта: мёртвые камни и владение пунктами
        self.dead: set[Point] = set()
        self.territory: dict[Point, int] = {}
        # Карта влияния/владения от ИИ (-1..1), показывается полупрозрачно
        self.ownership: Optional[list[float]] = None
        # Отмеченные камни (цель задачи)
        self.marked: set[Point] = set()
        # Показываемая часть доски (x0, y0, x1, y1) или None — вся доска
        self.view: Optional[tuple[int, int, int, int]] = None
        self.setMouseTracking(True)
        self.setMinimumSize(320, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------- API
    def set_board(self, board: Board, last_move: Optional[Point] = None) -> None:
        self.board = board
        self.last_move = last_move
        self.update()

    def clear_marks(self) -> None:
        self.labels.clear()
        self.circles.clear()
        self.dead = set()
        self.territory = {}
        self.ownership = None
        self.marked = set()
        self.update()

    # ------------------------------------------------------------- геометрия
    def _bounds(self) -> tuple[int, int, int, int]:
        n = self.board.size
        if self.view is None:
            return 0, 0, n - 1, n - 1
        x0, y0, x1, y1 = self.view
        return max(0, x0), max(0, y0), min(n - 1, x1), min(n - 1, y1)

    def _geometry(self) -> tuple[float, float, float]:
        x0, y0, x1, y1 = self._bounds()
        cols, rows = x1 - x0 + 1, y1 - y0 + 1
        cell = min(self.width() / (cols + 1), self.height() / (rows + 1))
        ox = (self.width() - cell * (cols - 1)) / 2 - x0 * cell
        oy = (self.height() - cell * (rows - 1)) / 2 - y0 * cell
        return cell, ox, oy

    def _to_screen(self, p: Point) -> QPointF:
        cell, ox, oy = self._geometry()
        return QPointF(ox + p[0] * cell, oy + p[1] * cell)

    def _to_point(self, pos) -> Optional[Point]:
        cell, ox, oy = self._geometry()
        x = round((pos.x() - ox) / cell)
        y = round((pos.y() - oy) / cell)
        x0, y0, x1, y1 = self._bounds()
        if x0 <= x <= x1 and y0 <= y <= y1:
            return (x, y)
        return None

    # ------------------------------------------------------------- события
    def mouseMoveEvent(self, e):
        p = self._to_point(e.position())
        if p != self.hover:
            self.hover = p
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        p = self._to_point(e.position())
        if p is None:
            return
        if e.button() == Qt.LeftButton:
            self.clicked.emit(*p)
        elif e.button() == Qt.RightButton:
            self.right_clicked.emit(*p)

    # ------------------------------------------------------------- рисование
    def paintEvent(self, e):
        n = self.board.size
        cell, ox, oy = self._geometry()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)

        x0, y0, x1, y1 = self._bounds()
        tl = self._to_screen((x0, y0))
        br = self._to_screen((x1, y1))
        rect = QRectF(tl.x() - cell, tl.y() - cell, br.x() - tl.x() + 2 * cell, br.y() - tl.y() + 2 * cell)

        # Деревянный фон
        qp.fillRect(self.rect(), self.palette().window())
        qp.setPen(QPen(WOOD_DARK, 2))
        qp.setBrush(WOOD)
        qp.drawRoundedRect(rect, 6, 6)
        qp.setClipRect(rect)

        # Карта владения
        if self.ownership:
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    v = self.ownership[y * n + x]
                    if abs(v) < 0.15:
                        continue
                    c = QColor(0, 0, 0, int(140 * abs(v))) if v > 0 else QColor(255, 255, 255, int(170 * abs(v)))
                    pt = self._to_screen((x, y))
                    s = cell * 0.9
                    qp.fillRect(QRectF(pt.x() - s / 2, pt.y() - s / 2, s, s), c)

        # Сетка (если показана часть доски, линии уходят за край картинки)
        qp.setPen(QPen(QColor("#3b2a12"), max(1.0, cell / 30)))
        ext_l = 0 if x0 == 0 else 0.6
        ext_r = 0 if x1 == n - 1 else 0.6
        ext_t = 0 if y0 == 0 else 0.6
        ext_b = 0 if y1 == n - 1 else 0.6
        for i in range(x0, x1 + 1):
            a = self._to_screen((i, y0))
            b = self._to_screen((i, y1))
            qp.drawLine(QPointF(a.x(), a.y() - ext_t * cell), QPointF(b.x(), b.y() + ext_b * cell))
        for i in range(y0, y1 + 1):
            a = self._to_screen((x0, i))
            b = self._to_screen((x1, i))
            qp.drawLine(QPointF(a.x() - ext_l * cell, a.y()), QPointF(b.x() + ext_r * cell, b.y()))
        qp.setBrush(QColor("#3b2a12"))
        for p in star_points(n):
            if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                qp.drawEllipse(self._to_screen(p), cell * 0.1, cell * 0.1)

        # Координаты
        font = QFont()
        font.setPixelSize(max(8, int(cell * 0.32)))
        qp.setFont(font)
        qp.setPen(QColor("#4a3518"))
        for i in range(x0, x1 + 1):
            letter = GTP_LETTERS[i]
            top = self._to_screen((i, y0))
            bottom = self._to_screen((i, y1))
            qp.drawText(QRectF(top.x() - cell / 2, top.y() - cell * 0.95, cell, cell * 0.5), Qt.AlignCenter, letter)
            qp.drawText(QRectF(bottom.x() - cell / 2, bottom.y() + cell * 0.45, cell, cell * 0.5), Qt.AlignCenter, letter)
        for i in range(y0, y1 + 1):
            left = self._to_screen((x0, i))
            right = self._to_screen((x1, i))
            num = str(n - i)
            qp.drawText(QRectF(left.x() - cell * 0.98, left.y() - cell / 2, cell * 0.5, cell), Qt.AlignCenter, num)
            qp.drawText(QRectF(right.x() + cell * 0.48, right.y() - cell / 2, cell * 0.5, cell), Qt.AlignCenter, num)

        # Камни
        r = cell * 0.47
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                c = self.board.get((x, y))
                if c != EMPTY:
                    self._draw_stone(qp, (x, y), c, r, faded=(x, y) in self.dead)

        # Территория (режим подсчёта)
        for p, owner in self.territory.items():
            pt = self._to_screen(p)
            s = cell * 0.3
            qp.setPen(Qt.NoPen)
            qp.setBrush(QColor(20, 20, 20) if owner == BLACK else QColor(245, 245, 245))
            qp.drawRect(QRectF(pt.x() - s / 2, pt.y() - s / 2, s, s))

        # Отмеченные камни
        for p in self.marked:
            pt = self._to_screen(p)
            c = self.board.get(p)
            qp.setPen(QPen(QColor("#e03030"), max(2.0, cell / 14)))
            qp.setBrush(Qt.NoBrush)
            s = cell * 0.22
            qp.drawLine(QPointF(pt.x() - s, pt.y() - s), QPointF(pt.x() + s, pt.y() + s))
            qp.drawLine(QPointF(pt.x() - s, pt.y() + s), QPointF(pt.x() + s, pt.y() - s))

        # Последний ход
        if self.last_move is not None and self.board.get(self.last_move) != EMPTY:
            pt = self._to_screen(self.last_move)
            c = self.board.get(self.last_move)
            qp.setPen(QPen(QColor("white") if c == BLACK else QColor("black"), max(1.5, cell / 18)))
            qp.setBrush(Qt.NoBrush)
            qp.drawEllipse(pt, r * 0.45, r * 0.45)

        # Кружки-подсказки
        for p, col in self.circles.items():
            pt = self._to_screen(p)
            qp.setPen(QPen(col, max(2.5, cell / 10)))
            qp.setBrush(Qt.NoBrush)
            qp.drawEllipse(pt, r * 0.8, r * 0.8)

        # Текстовые метки
        bold = QFont()
        bold.setBold(True)
        bold.setPixelSize(max(9, int(cell * 0.42)))
        qp.setFont(bold)
        for p, (text, col) in self.labels.items():
            pt = self._to_screen(p)
            stone = self.board.get(p)
            if stone == EMPTY:
                qp.setPen(Qt.NoPen)
                qp.setBrush(WOOD)
                qp.drawEllipse(pt, r * 0.6, r * 0.6)
                qp.setPen(col)
            else:
                qp.setPen(QColor("white") if stone == BLACK else QColor("black"))
            qp.drawText(QRectF(pt.x() - cell / 2, pt.y() - cell / 2, cell, cell), Qt.AlignCenter, text)

        # Полупрозрачный камень под курсором
        if (self.interactive and self.hover is not None and self.ghost_color is not None
                and self.board.get(self.hover) == EMPTY):
            qp.setOpacity(0.45)
            self._draw_stone(qp, self.hover, self.ghost_color, r)
            qp.setOpacity(1.0)
        qp.end()

    def _draw_stone(self, qp: QPainter, p: Point, color: int, r: float, faded: bool = False) -> None:
        pt = self._to_screen(p)
        if faded:
            qp.setOpacity(0.35)
        g = QRadialGradient(pt.x() - r * 0.35, pt.y() - r * 0.35, r * 1.4)
        if color == BLACK:
            g.setColorAt(0, QColor("#666"))
            g.setColorAt(1, QColor("#0a0a0a"))
            qp.setPen(QPen(QColor("#000"), 1))
        else:
            g.setColorAt(0, QColor("#ffffff"))
            g.setColorAt(1, QColor("#cfcfcf"))
            qp.setPen(QPen(QColor("#777"), 1))
        qp.setBrush(QBrush(g))
        qp.drawEllipse(pt, r, r)
        if faded:
            qp.setOpacity(1.0)
