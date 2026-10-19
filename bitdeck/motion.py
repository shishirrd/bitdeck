"""Small compositor animations that honor Windows' client animation setting."""
import os
import sys
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QAbstractAnimation
from PySide6.QtWidgets import QApplication


def motion_enabled():
    if os.environ.get("BITDECK_REDUCED_MOTION", "").lower() in {"1", "true", "yes"}:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        enabled = wintypes.BOOL(True)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    return True


def show_gently(widget):
    if widget.isVisible():
        widget.show()
        return
    animate = not widget.isVisible() and motion_enabled() and QApplication.platformName() != "offscreen"
    if animate:
        widget.setWindowOpacity(0)
    else:
        widget.setWindowOpacity(1)
    widget.show()
    if animate:
        animation = QPropertyAnimation(widget, b"windowOpacity", widget)
        animation.setDuration(140)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start(QAbstractAnimation.DeleteWhenStopped)
