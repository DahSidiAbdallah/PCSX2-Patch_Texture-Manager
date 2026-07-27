"""Test-suite-only environment setup.

QtWebEngine (Chromium) needs its sandbox/GPU process, and importing main.py
now pulls in ps2_ui.py -> QtWebEngineWidgets as a side effect for every test
that imports main, even tests that never touch the web-based UI directly.
This dev sandbox's restricted container permissions make Chromium's
sandboxed/GPU subprocess crash intermittently (confirmed via repeated runs on
a clean baseline vs. with the WebEngine import: 4/4 clean without it, ~3/4
crashing with it, and 4/4 clean again once these flags are set) -- a well
documented category of "QtWebEngine inside a container/CI runner" issue, not
a bug in the app's own code.

These flags are intentionally NOT set in the shipped app (main.py) -- turning
off Chromium's sandbox is a real security trade-off that's only appropriate
here, in a disposable, isolated test run, not for the actual running app on a
user's machine, where the normal OS-level sandbox should stay on.

Must be set before anything imports PySide6.QtWebEngineWidgets (that means
before `import main` in any test module), so this lives in conftest.py,
which pytest loads ahead of test collection.
"""
import os

os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --no-sandbox --disable-software-rasterizer",
)
