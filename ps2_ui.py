"""Python side of the PS2-style navigation: real Three.js/WebGL scenes (ring
boot menu, game carousel, boot splash -- see web/*.html) embedded via
QWebEngineView, driven from small QObject bridge classes over QWebChannel.
This module holds no business logic -- LibraryView adapts its own data into
the plain types here and reacts to the signals these widgets emit, so all the
existing install/scan/cover-cache logic stays completely untouched.

Why Three.js/QWebEngineView instead of QtQuick3D (tried first): QtQuick3D
rendering couldn't be verified at all in the dev sandbox used to build this
(no GPU behind its offscreen Qt platform), which directly caused two real
shipped bugs -- a ring whose 3D dots were positioned in world space while
their connecting arc was a separate, never-verified 2D overlay, and input
that silently never reached the 3D content. Three.js runs in a browser,
which this environment *can* actually load, screenshot, and click-test before
any of it touches the app -- every scene here was verified rendering and
responding to real clicks in an actual browser before being wired in.
"""
import json
import os
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def _cover_url(path: str) -> str:
    """A file:// URL QWebEngine can load as an <img>/texture source, or ''
    if there's no cover yet (the page falls back to a drawn placeholder)."""
    return QUrl.fromLocalFile(path).toString() if path and os.path.isfile(path) else ""


@dataclass
class CarouselItem:
    """Plain data shape fed to web/carousel.html via JSON -- deliberately not
    GameEntry, so this module has zero dependency on LibraryView internals."""
    serial: str
    title: str
    region: str
    cover_path: str
    cheats_installed: bool = False
    textures_installed: bool = False

    def to_json_dict(self) -> dict:
        return {
            "serial": self.serial,
            "title": self.title,
            "region": self.region,
            "coverSource": _cover_url(self.cover_path),
            "cheatsInstalled": self.cheats_installed,
            "texturesInstalled": self.textures_installed,
        }


class RingBridge(QObject):
    """Backs web/ring.html. optionChosen is what main.py connects to; chooseOption
    is the Qt slot the page's JS actually calls (QWebChannel exposes registered
    signals to JS as connectable events, not as callable functions -- JS has to
    invoke a slot to make something happen on the Python side)."""

    optionChosen = Signal(str)

    @Slot(str)
    def chooseOption(self, key: str):
        self.optionChosen.emit(key)


class RingMenuWidget(QWebEngineView):
    """The boot ring menu, wrapped as an ordinary widget with a plain-Qt
    signal API so main.py doesn't need to know anything about the web page
    or QWebChannel underneath."""

    optionChosen = Signal(str)

    def __init__(self, options: Optional[List[tuple]] = None, parent=None):
        super().__init__(parent)
        self._options = options or [("library", "Library"), ("settings", "Settings")]
        self.bridge = RingBridge(self)
        self.bridge.optionChosen.connect(self.optionChosen.emit)

        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.loadFinished.connect(self._on_load_finished)
        self.setUrl(QUrl.fromLocalFile(os.path.join(_WEB_DIR, "ring.html")))

    def _on_load_finished(self, ok: bool):
        if not ok:
            return
        options_json = json.dumps([{"key": k, "label": label} for k, label in self._options])
        self.page().runJavaScript(f"window.setOptions({options_json});")


class BootBridge(QObject):
    finished = Signal()

    @Slot()
    def notifyFinished(self):
        self.finished.emit()


class BootScreenWidget(QWebEngineView):
    """An original splash screen shown before the ring menu -- this app's own
    branding/shapes and an AI-composed, PS2-inspired startup sound (not a
    reproduction of Sony's copyrighted boot animation/sound). Auto-advances
    once the audio finishes, or immediately on any key/click (handled in
    web/boot.html)."""

    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = BootBridge(self)
        self.bridge.finished.connect(self.finished.emit)

        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        # This page autoplays its own bundled startup sound (not third-party
        # content), so it's reasonable to lift Chromium's default "no sound
        # without a prior user gesture" restriction just for this widget.
        self.page().settings().setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False
        )
        self.setUrl(QUrl.fromLocalFile(os.path.join(_WEB_DIR, "boot.html")))


class CarouselBridge(QObject):
    selectionChanged = Signal(str)
    activated = Signal(str)
    removeRequested = Signal(str)
    backRequested = Signal()

    @Slot(str)
    def notifySelectionChanged(self, serial: str):
        self.selectionChanged.emit(serial)

    @Slot(str)
    def notifyActivated(self, serial: str):
        self.activated.emit(serial)

    @Slot(str)
    def notifyRemoveRequested(self, serial: str):
        self.removeRequested.emit(serial)

    @Slot()
    def notifyBackRequested(self):
        self.backRequested.emit()


class GameCarouselWidget(QWebEngineView):
    """The 3D game-browsing carousel, wrapped as an ordinary widget with a
    plain-Qt signal API -- main.py's LibraryView reacts to these signals with
    its existing, unmodified business logic (scan/install/cover-cache/etc.)."""

    selectionChanged = Signal(str)
    activated = Signal(str)
    removeRequested = Signal(str)
    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: List[CarouselItem] = []
        self._current_serial: Optional[str] = None

        self.bridge = CarouselBridge(self)
        self.bridge.selectionChanged.connect(self._on_selection_changed)
        self.bridge.selectionChanged.connect(self.selectionChanged.emit)
        self.bridge.activated.connect(self.activated.emit)
        self.bridge.removeRequested.connect(self.removeRequested.emit)
        self.bridge.backRequested.connect(self.backRequested.emit)

        self.channel = QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self._loaded = False
        self._pending_items: Optional[List[CarouselItem]] = None
        self.loadFinished.connect(self._on_load_finished)
        self.setUrl(QUrl.fromLocalFile(os.path.join(_WEB_DIR, "carousel.html")))

    def _on_load_finished(self, ok: bool):
        # setUrl() being called doesn't mean the page has actually finished
        # loading/executing its module script -- page().url() is set the
        # instant setUrl() runs, well before loadFinished fires, so it was
        # never a reliable "is window.setGames defined yet" signal. Track the
        # real load-finished state instead.
        self._loaded = bool(ok)
        if self._loaded and self._pending_items is not None:
            self._push_items(self._pending_items)
            self._pending_items = None

    def _on_selection_changed(self, serial: str):
        self._current_serial = serial

    def _push_items(self, items: List[CarouselItem]):
        self._items = list(items)
        # runJavaScript() interpolates this as a literal JS expression, not a
        # string -- window.setGames() takes an already-parsed array directly
        # (no JSON.parse() on the JS side), since the data arrives as a real
        # JS array here, not text that still needs parsing.
        data = json.dumps([item.to_json_dict() for item in self._items])
        self.page().runJavaScript(f"window.setGames({data});")
        if self._items and self._current_serial is None:
            self._current_serial = self._items[0].serial

    def set_items(self, items: List[CarouselItem]):
        if not self._loaded:
            self._pending_items = list(items)
            return
        self._push_items(items)

    def update_status(self, serial: str, cheats_installed: bool, textures_installed: bool):
        for item in self._items:
            if item.serial == serial:
                item.cheats_installed = cheats_installed
                item.textures_installed = textures_installed
                break
        js_bool = lambda b: "true" if b else "false"
        self.page().runJavaScript(
            f"window.updateGameStatus({json.dumps(serial)}, {js_bool(cheats_installed)}, {js_bool(textures_installed)});"
        )

    def update_cover(self, serial: str, cover_path: str):
        for item in self._items:
            if item.serial == serial:
                item.cover_path = cover_path
                break
        self.page().runJavaScript(
            f"window.updateGameCover({json.dumps(serial)}, {json.dumps(_cover_url(cover_path))});"
        )

    def select_serial(self, serial: str):
        self._current_serial = serial
        self.page().runJavaScript(f"window.selectGameSerial({json.dumps(serial)});")

    def current_serial(self) -> Optional[str]:
        return self._current_serial
