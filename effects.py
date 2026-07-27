"""Shared animation/visual-effect helpers for a more premium, PS2-Browser-
inspired feel: an animated hover glow (drop shadow blur eased in/out) for
buttons and cards, and a fade-in transition for windows/dialogs opening.

Kept separate from theme.py (which only holds static QSS/colors) since these
are runtime behaviors, not stylesheet tokens.
"""
from PySide6.QtCore import QEvent, QObject, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget


class HoverGlow(QObject):
    """Event filter that eases a widget's drop-shadow glow in on hover and back
    out on leave. Parented to the widget so it's torn down with it, and stored
    as an attribute on the widget so it isn't garbage-collected early."""

    def __init__(self, widget: QWidget, color: str, max_blur: int, parent=None):
        super().__init__(parent or widget)
        self.widget = widget
        self.max_blur = max_blur
        self.effect = QGraphicsDropShadowEffect(widget)
        self.effect.setColor(QColor(color))
        self.effect.setOffset(0, 0)
        self.effect.setBlurRadius(0)
        widget.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"blurRadius", widget)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.widget:
            if event.type() == QEvent.Enter and self.widget.isEnabled():
                self._animate_to(self.max_blur)
            elif event.type() == QEvent.Leave:
                self._animate_to(0)
        return False

    def _animate_to(self, value):
        self.anim.stop()
        self.anim.setStartValue(self.effect.blurRadius())
        self.anim.setEndValue(value)
        self.anim.start()


def add_hover_glow(widget: QWidget, color: str = "#5ec8ff", max_blur: int = 22) -> HoverGlow:
    """Attach an animated hover glow to `widget`. Returns the HoverGlow so a
    caller can keep an explicit reference too, though it isn't required --
    the filter is already parented to the widget."""
    glow = HoverGlow(widget, color, max_blur)
    widget._hover_glow = glow  # extra safety net against GC in edge cases
    return glow


def fade_in(widget: QWidget, duration: int = 220):
    """Animate a top-level widget's windowOpacity from 0 to 1, e.g. on a
    dialog's first show(). Stores the animation on the widget so it survives
    until it completes."""
    widget.setWindowOpacity(0.0)
    anim = QPropertyAnimation(widget, b"windowOpacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    widget._fade_in_anim = anim
    anim.start()
    return anim
