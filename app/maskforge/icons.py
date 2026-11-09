"""左侧功能栏的线条图标（矢量绘制，跟随主题颜色）。坐标按 24×24 设计。"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _pen(color: QColor, w: float = 1.7) -> QPen:
    p = QPen(color, w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def _draw(name: str, p: QPainter, c: QColor):
    p.setPen(_pen(c))
    p.setBrush(Qt.BrushStyle.NoBrush)
    soft = QColor(c)
    soft.setAlphaF(0.22)
    if name == "assets":  # 叠在一起的照片
        p.drawRoundedRect(QRectF(7, 3.5, 13.5, 11), 2.2, 2.2)
        p.drawRoundedRect(QRectF(3.5, 8, 13.5, 12.5), 2.2, 2.2)
        path = QPainterPath(QPointF(5.5, 18.5))
        path.lineTo(9.3, 14.2)
        path.lineTo(12, 16.8)
        path.lineTo(13.6, 15.2)
        path.lineTo(15.2, 17)
        p.drawPath(path)
        p.drawEllipse(QPointF(12.6, 11.6), 1.2, 1.2)
    elif name == "mask":  # 马赛克格子
        p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 3, 3)
        p.setPen(Qt.PenStyle.NoPen)
        cells = [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)]
        for x, y in cells:
            p.setBrush(c)
            p.drawRoundedRect(QRectF(6.6 + x * 3.9, 6.6 + y * 3.9, 3.2, 3.2), 0.8, 0.8)
        p.setBrush(soft)
        for x, y in [(1, 0), (0, 1), (2, 1), (1, 2)]:
            p.drawRoundedRect(QRectF(6.6 + x * 3.9, 6.6 + y * 3.9, 3.2, 3.2), 0.8, 0.8)
    elif name == "main":  # 正方形取景框 + 人像
        for (x, y, dx, dy) in [(3.5, 3.5, 1, 1), (20.5, 3.5, -1, 1), (3.5, 20.5, 1, -1), (20.5, 20.5, -1, -1)]:
            path = QPainterPath(QPointF(x, y + 4.5 * dy))
            path.lineTo(x, y)
            path.lineTo(x + 4.5 * dx, y)
            p.drawPath(path)
        p.drawEllipse(QPointF(12, 9.6), 2.4, 2.4)
        path = QPainterPath(QPointF(7.6, 17.2))
        path.cubicTo(8.4, 14.2, 15.6, 14.2, 16.4, 17.2)
        p.drawPath(path)
    elif name == "spec":  # 吊牌
        path = QPainterPath(QPointF(11.2, 3.5))
        path.lineTo(19, 3.5)
        path.quadTo(20.5, 3.5, 20.5, 5)
        path.lineTo(20.5, 12.8)
        path.lineTo(12.4, 20.9)
        path.quadTo(11.3, 22, 10.2, 20.9)
        path.lineTo(3.1, 13.8)
        path.quadTo(2, 12.7, 3.1, 11.6)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QPointF(16.2, 7.8), 1.6, 1.6)
        p.drawLine(QPointF(8.4, 12.6), QPointF(11.6, 15.8))
    elif name == "detail":  # 长页面
        p.drawRoundedRect(QRectF(5, 2.5, 14, 19), 2.4, 2.4)
        p.setBrush(soft)
        p.drawRoundedRect(QRectF(7.6, 5.2, 8.8, 6), 1.2, 1.2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(7.8, 14.4), QPointF(16.2, 14.4))
        p.drawLine(QPointF(7.8, 17.6), QPointF(13.4, 17.6))
    elif name == "watermark":  # 水滴
        path = QPainterPath(QPointF(12, 3))
        path.cubicTo(12, 3, 5.5, 10.4, 5.5, 14.4)
        path.cubicTo(5.5, 18.2, 8.4, 21, 12, 21)
        path.cubicTo(15.6, 21, 18.5, 18.2, 18.5, 14.4)
        path.cubicTo(18.5, 10.4, 12, 3, 12, 3)
        p.drawPath(path)
        arc = QPainterPath(QPointF(9, 15))
        arc.cubicTo(9, 16.8, 10.3, 18, 12, 18)
        p.drawPath(arc)
    elif name == "templates":  # 三层叠放
        top = QPainterPath(QPointF(12, 3.5))
        top.lineTo(20.5, 8)
        top.lineTo(12, 12.5)
        top.lineTo(3.5, 8)
        top.closeSubpath()
        p.setBrush(soft)
        p.drawPath(top)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for y in (12, 16):
            path = QPainterPath(QPointF(3.5, y))
            path.lineTo(12, y + 4.5)
            path.lineTo(20.5, y)
            p.drawPath(path)
    elif name == "theme":  # 调色盘
        path = QPainterPath(QPointF(12, 3.5))
        path.cubicTo(7.3, 3.5, 3.5, 7.2, 3.5, 11.8)
        path.cubicTo(3.5, 16.6, 7.4, 20.5, 12.2, 20.5)
        path.cubicTo(13.6, 20.5, 14.3, 19.6, 14, 18.4)
        path.cubicTo(13.6, 16.9, 14.6, 15.6, 16.2, 15.6)
        path.lineTo(17.6, 15.6)
        path.cubicTo(19.3, 15.6, 20.5, 14.3, 20.5, 12.4)
        path.cubicTo(20.5, 7.4, 16.7, 3.5, 12, 3.5)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        for x, y in [(8, 10.8), (11, 7.4), (15.4, 8.4)]:
            p.drawEllipse(QPointF(x, y), 1.25, 1.25)
    elif name == "settings":  # 调节滑杆
        for y, kx in ((6.5, 15), (12, 8.5), (17.5, 13)):
            p.drawLine(QPointF(4, y), QPointF(20, y))
            p.setBrush(QColor(0, 0, 0, 0))
            p.save()
            p.setPen(_pen(c, 1.7))
            p.setBrush(c)
            p.drawEllipse(QPointF(kx, y), 2.1, 2.1)
            p.restore()


def make_icon(name: str, normal: str, active: str, size: int = 26) -> QIcon:
    """normal：未选中时的颜色；active：选中时的颜色。"""
    icon = QIcon()
    for color, state in ((normal, QIcon.State.Off), (active, QIcon.State.On)):
        for scale in (1, 2):
            pm = QPixmap(size * scale, size * scale)
            pm.setDevicePixelRatio(scale)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(size / 24, size / 24)
            _draw(name, p, QColor(color))
            p.end()
            icon.addPixmap(pm, QIcon.Mode.Normal, state)
            icon.addPixmap(pm, QIcon.Mode.Active, state)
    return icon


NAMES = ["assets", "mask", "main", "spec", "detail", "watermark", "templates", "theme", "settings"]
