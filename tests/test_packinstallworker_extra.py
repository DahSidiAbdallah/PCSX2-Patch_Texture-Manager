import os
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import pytest

import sys
sys.path.insert(0, os.getcwd())
from main import TexturesTab


def _ensure_no_app(monkeypatch):
    # Force QApplication.instance() to return None to exercise the start() fallback
    class DummyApp:
        @staticmethod
        def instance():
            return None
    monkeypatch.setattr('PySide6.QtWidgets.QApplication.instance', lambda: None)


def test_packinstallworker_start_run_fallback(monkeypatch, tmp_path):
    # Ensure start() runs inline when QApplication.instance() is None
    monkeypatch.setattr('PySide6.QtWidgets.QApplication.instance', lambda: None)

    # create a tiny pack
    valid = tmp_path / 'pack_valid'
    os.makedirs(valid / 'replacements', exist_ok=True)
    with open(valid / 'replacements' / 'img.png', 'wb') as f:
        f.write(b'A' * 64)

    items = [("Valid", str(valid))]
    worker = TexturesTab.PackInstallWorker(items, str(tmp_path))

    results = {}

    def on_finished(installed, failures):
        results['installed'] = installed
        results['failures'] = failures

    worker.finished.connect(on_finished)
    # call start which should call run inline because QApplication.instance() was monkeypatched to None
    worker.start()

    # since run is inline we should have results immediately
    assert 'installed' in results
    assert results['installed'] == 1
    assert results['failures'] == []


def test_packinstallworker_retry_reporting(tmp_path):
    # Create one valid pack and one missing pack so there will be a failure reported
    valid = tmp_path / 'pack_valid'
    os.makedirs(valid / 'replacements', exist_ok=True)
    with open(valid / 'replacements' / 'img.png', 'wb') as f:
        f.write(b'A' * 128)

    missing = tmp_path / 'nope'
    items = [("Valid", str(valid)), ("Missing", str(missing))]

    worker = TexturesTab.PackInstallWorker(items, str(tmp_path))

    results = {}

    def on_finished(installed, failures):
        results['installed'] = installed
        results['failures'] = failures

    worker.finished.connect(on_finished)
    worker.start()

    # wait for worker to finish (timeout)
    deadline = time.time() + 5.0
    while 'installed' not in results and time.time() < deadline:
        QTest.qWait(50)

    assert 'installed' in results
    assert results['installed'] == 1
    assert isinstance(results['failures'], list)
    assert len(results['failures']) == 1

    # The failures item should be a tuple-like (display, src, message)
    f = results['failures'][0]
    assert len(f) >= 2
    assert f[0] == 'Missing'
    # Re-run PackInstallWorker with the failed items (simulate retry path)
    retry_items = [(d, s) for (d, s, *rest) in results['failures']]
    retry_worker = TexturesTab.PackInstallWorker(retry_items, str(tmp_path))
    rres = {}

    def on_finished2(installed, failures):
        rres['installed'] = installed
        rres['failures'] = failures

    retry_worker.finished.connect(on_finished2)
    retry_worker.start()

    # wait
    deadline = time.time() + 5.0
    while 'installed' not in rres and time.time() < deadline:
        QTest.qWait(50)

    assert 'installed' in rres
    # since retry item was missing, installed should be 0 and failures length 1
    assert rres['installed'] == 0
    assert len(rres['failures']) == 1
