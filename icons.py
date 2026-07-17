"""A tiny set of tab icons drawn with QPainter instead of loading image files.

Rationale: PySide6's SVG icon support depends on the optional QtSvg plugin,
which isn't guaranteed to be present in every install (this app only depends
on base PySide6, not PySide6-Addons). Drawing directly with QPainter/QPixmap
uses only core Qt APIs, so it always renders regardless of what optional Qt
modules happen to be installed, with zero added pip dependency.
"""

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor

_STROKE = QColor("#c9c9cf")
_SIZE = 22


def _painter(pm: QPixmap) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(_STROKE)
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    return p


def _blank_pixmap() -> QPixmap:
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    return pm


def _cheats_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    body = QRectF(3, 7, 16, 9)
    p.drawRoundedRect(body, 4, 4)
    p.drawLine(QPointF(7, 9.5), QPointF(7, 13.5))
    p.drawLine(QPointF(5, 11.5), QPointF(9, 11.5))
    p.setBrush(_STROKE)
    p.drawEllipse(QPointF(14.5, 10.5), 0.9, 0.9)
    p.drawEllipse(QPointF(16.5, 12.5), 0.9, 0.9)
    p.end()
    return pm


def _textures_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawRoundedRect(QRectF(3.5, 4, 15, 14), 2, 2)
    p.setBrush(_STROKE)
    p.drawEllipse(QPointF(8, 8.5), 1.4, 1.4)
    p.setBrush(Qt.NoBrush)
    p.drawPolyline([
        QPointF(3.5, 14.5), QPointF(8, 10.5), QPointF(12, 14), QPointF(14.5, 11.5), QPointF(18.5, 15.5),
    ])
    p.end()
    return pm


def _scan_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawEllipse(QPointF(9.5, 9.5), 6, 6)
    p.drawLine(QPointF(14, 14), QPointF(19, 19))
    p.drawLine(QPointF(9.5, 6.5), QPointF(9.5, 12.5))
    p.drawLine(QPointF(6.5, 9.5), QPointF(12.5, 9.5))
    p.end()
    return pm


def _settings_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    center = QPointF(11, 11)
    p.drawEllipse(center, 2.6, 2.6)
    import math
    for i in range(8):
        angle = i * (math.pi / 4)
        x1 = center.x() + 4.2 * math.cos(angle)
        y1 = center.y() + 4.2 * math.sin(angle)
        x2 = center.x() + 6.4 * math.cos(angle)
        y2 = center.y() + 6.4 * math.sin(angle)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    p.end()
    return pm


_BUILDERS = {
    "cheats": _cheats_pixmap,
    "textures": _textures_pixmap,
    "scan": _scan_pixmap,
    "settings": _settings_pixmap,
}


def tab_icon(name: str) -> QIcon:
    """Return a QIcon for one of the known tab names ('cheats', 'textures', 'scan', 'settings')."""
    builder = _BUILDERS.get(name)
    if builder is None:
        return QIcon()
    return QIcon(builder())
