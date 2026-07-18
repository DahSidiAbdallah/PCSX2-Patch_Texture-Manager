"""Icon set for the app, backed by qtawesome (bundles Material Design Icons,
Font Awesome, etc. as vector icon fonts -- crisp at any size, no per-icon
artwork to maintain). Falls back to the earlier hand-drawn QPainter icons if
qtawesome isn't installed, so the app still runs without the dependency.
"""

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor

try:
    import qtawesome as qta
except Exception:
    qta = None

_STROKE = "#c9c9cf"
_SIZE = 22

# Maps our internal icon names to Material Design Icons 6 glyph names.
_MDI_NAMES = {
    "cheats": "mdi6.gamepad-variant",
    "textures": "mdi6.image-multiple",
    "scan": "mdi6.magnify",
    "settings": "mdi6.cog",
    "minimize": "mdi6.window-minimize",
    "maximize": "mdi6.window-maximize",
    "restore": "mdi6.window-restore",
    "close": "mdi6.close",
    "add": "mdi6.plus",
    "sync": "mdi6.sync",
    "menu": "mdi6.menu",
    "disc": "mdi6.disc",
    "view_list": "mdi6.view-list",
    "view_grid": "mdi6.view-grid",
    "remove": "mdi6.delete-outline",
    "folder": "mdi6.folder-open-outline",
    "star": "mdi6.star",
    "star_outline": "mdi6.star-outline",
    "check": "mdi6.check-circle",
    "warning": "mdi6.alert-circle-outline",
    "download": "mdi6.download",
    "refresh": "mdi6.refresh",
    "chevron_down": "mdi6.chevron-down",
}


def _painter(pm: QPixmap) -> QPainter:
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(_STROKE))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    return p


def _blank_pixmap() -> QPixmap:
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    return pm


# ---- Hand-drawn fallbacks (used only if qtawesome is unavailable) ----

def _cheats_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    body = QRectF(3, 7, 16, 9)
    p.drawRoundedRect(body, 4, 4)
    p.drawLine(QPointF(7, 9.5), QPointF(7, 13.5))
    p.drawLine(QPointF(5, 11.5), QPointF(9, 11.5))
    p.setBrush(QColor(_STROKE))
    p.drawEllipse(QPointF(14.5, 10.5), 0.9, 0.9)
    p.drawEllipse(QPointF(16.5, 12.5), 0.9, 0.9)
    p.end()
    return pm


def _textures_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawRoundedRect(QRectF(3.5, 4, 15, 14), 2, 2)
    p.setBrush(QColor(_STROKE))
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


def _minimize_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawLine(QPointF(6, 15), QPointF(16, 15))
    p.end()
    return pm


def _maximize_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawRoundedRect(QRectF(6, 6, 10, 10), 1.5, 1.5)
    p.end()
    return pm


def _restore_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawRoundedRect(QRectF(8.5, 5.5, 8, 8), 1.5, 1.5)
    p.drawRoundedRect(QRectF(5.5, 8.5, 8, 8), 1.5, 1.5)
    p.end()
    return pm


def _close_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawLine(QPointF(6, 6), QPointF(16, 16))
    p.drawLine(QPointF(16, 6), QPointF(6, 16))
    p.end()
    return pm


def _add_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawLine(QPointF(11, 5), QPointF(11, 17))
    p.drawLine(QPointF(5, 11), QPointF(17, 11))
    p.end()
    return pm


def _sync_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawArc(QRectF(4.5, 4.5, 13, 13), 40 * 16, 260 * 16)
    p.setBrush(QColor(_STROKE))
    p.drawEllipse(QPointF(16.5, 6.5), 1.4, 1.4)
    p.end()
    return pm


def _menu_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawLine(QPointF(5, 7.5), QPointF(17, 7.5))
    p.drawLine(QPointF(5, 11), QPointF(17, 11))
    p.drawLine(QPointF(5, 14.5), QPointF(17, 14.5))
    p.end()
    return pm


def _disc_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    p.drawEllipse(QPointF(11, 11), 8, 8)
    p.drawEllipse(QPointF(11, 11), 2.4, 2.4)
    p.end()
    return pm


def _view_list_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    for y in (6, 11, 16):
        p.drawLine(QPointF(4, y), QPointF(6, y))
        p.drawLine(QPointF(9, y), QPointF(18, y))
    p.end()
    return pm


def _view_grid_pixmap() -> QPixmap:
    pm = _blank_pixmap()
    p = _painter(pm)
    for x, y in ((4, 4), (12.5, 4), (4, 12.5), (12.5, 12.5)):
        p.drawRoundedRect(QRectF(x, y, 6.5, 6.5), 1, 1)
    p.end()
    return pm


_FALLBACK_BUILDERS = {
    "cheats": _cheats_pixmap,
    "textures": _textures_pixmap,
    "scan": _scan_pixmap,
    "settings": _settings_pixmap,
    "minimize": _minimize_pixmap,
    "maximize": _maximize_pixmap,
    "restore": _restore_pixmap,
    "close": _close_pixmap,
    "add": _add_pixmap,
    "sync": _sync_pixmap,
    "menu": _menu_pixmap,
    "disc": _disc_pixmap,
    "view_list": _view_list_pixmap,
    "view_grid": _view_grid_pixmap,
}

_qta_cache = {}


def tab_icon(name: str, color: str = _STROKE) -> QIcon:
    """Return a QIcon for one of the known icon names (see _MDI_NAMES /
    _FALLBACK_BUILDERS). Uses qtawesome's vector icon fonts when available
    (crisp at any size); falls back to the hand-drawn QPainter icons if
    qtawesome couldn't be imported."""
    if qta is not None:
        mdi_name = _MDI_NAMES.get(name)
        if mdi_name:
            cache_key = (mdi_name, color)
            icon = _qta_cache.get(cache_key)
            if icon is None:
                try:
                    icon = qta.icon(mdi_name, color=color)
                    _qta_cache[cache_key] = icon
                except Exception:
                    icon = None
            if icon is not None:
                return icon

    builder = _FALLBACK_BUILDERS.get(name)
    if builder is None:
        return QIcon()
    return QIcon(builder())
