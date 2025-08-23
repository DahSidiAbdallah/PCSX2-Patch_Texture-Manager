import os
import shutil
import time
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar
from PySide6.QtTest import QTest
import pytest

import sys
sys.path.insert(0, os.getcwd())
from main import MainWindow


def _ensure_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_packinstallworker_signals(tmp_path):
    # create a valid pack and a missing pack to force a failure
    valid = tmp_path / 'pack_valid'
    os.makedirs(valid / 'replacements', exist_ok=True)
    with open(valid / 'replacements' / 'img.png', 'wb') as f:
        f.write(b'A' * 1024)

    items = [("Valid", str(valid)), ("Missing", str(tmp_path / 'nope'))]

    from main import TexturesTab

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


@pytest.mark.flaky(reruns=1)
def test_dialog_shows_and_updates(tmp_path):
    app = _ensure_app()
    win = MainWindow()
    win.show()

    base = str(tmp_path / 'textures')
    os.makedirs(base, exist_ok=True)
    imports_root = win.textures_tab._imports_root(base)
    shutil.rmtree(imports_root, ignore_errors=True)
    os.makedirs(imports_root, exist_ok=True)

    # create small pack
    p = os.path.join(imports_root, 'PackX')
    os.makedirs(os.path.join(p, 'replacements'), exist_ok=True)
    with open(os.path.join(p, 'replacements', 'img.png'), 'wb') as f:
        f.write(b'A' * 1024)

    win.textures_tab.textures_dir.setText(base)
    win.textures_tab.scan_installed_textures()

    # select items
    lst = win.textures_tab.packs_list
    for i in range(lst.topLevelItemCount()):
        it = lst.topLevelItem(i)
        it.setSelected(True)

    # trigger dialog
    win.textures_tab._install_selected_multiple()

    # find dialog among top-level widgets
    dlg = None
    for w in QApplication.topLevelWidgets():
        if w.windowTitle() == 'Installing Packs':
            dlg = w
            break
    assert dlg is not None

    # wait a bit for worker callbacks to update UI
    QTest.qWait(500)

    # find a QLabel that starts with 'Current:' and a progress bar
    per_label = None
    per_bar = None
    for child in dlg.findChildren(QLabel):
        if child.text().startswith('Current:'):
            per_label = child
            break
    for child in dlg.findChildren(QProgressBar):
        # find the per-pack bar which has range 0-100
        if child.minimum() == 0 and child.maximum() == 100:
            per_bar = child
            break

    assert per_label is not None
    assert per_bar is not None

    # wait for dialog to finish and close (max wait)
    timeout = time.time() + 5.0
    closed = False
    while time.time() < timeout:
        QTest.qWait(100)
        if not dlg.isVisible():
            closed = True
            break
    assert closed

    try:
        shutil.rmtree(base)
        shutil.rmtree(imports_root)
    except Exception:
        pass
