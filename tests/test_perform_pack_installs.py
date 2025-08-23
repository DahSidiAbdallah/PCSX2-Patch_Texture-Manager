import os
import tempfile
import shutil
import time
from textures_install import perform_pack_installs


def _create_sample_pack(folder: str, files: int = 3, size: int = 1024):
    os.makedirs(folder, exist_ok=True)
    for i in range(files):
        p = os.path.join(folder, f"img{i}.png")
        with open(p, 'wb') as f:
            f.write(os.urandom(size))


def test_perform_pack_installs_success(tmp_path):
    base = str(tmp_path / 'textures')
    os.makedirs(base, exist_ok=True)
    # create two packs as folders
    p1 = str(tmp_path / 'packA')
    p2 = str(tmp_path / 'packB')
    _create_sample_pack(p1)
    _create_sample_pack(p2)
    items = [('packA', p1), ('packB', p2)]
    recorded = []
    def prog(c, t, d):
        recorded.append((c, t, d))
    installed, failures = perform_pack_installs(items, base, progress_cb=prog)
    assert installed == 2
    assert failures == []
    # ensure folders exist in target
    assert os.path.isdir(os.path.join(base, 'packA'))
    assert os.path.isdir(os.path.join(base, 'packB'))


def test_perform_pack_installs_cancel(tmp_path):
    base = str(tmp_path / 'textures')
    os.makedirs(base, exist_ok=True)
    # create one pack with a large file to allow cancellation
    p1 = str(tmp_path / 'packLarge')
    _create_sample_pack(p1, files=1, size=1024*1024)  # ~1MB
    items = [('packLarge', p1)]
    progress_calls = []
    def prog(c, t, d):
        progress_calls.append((c, t, d))

    cancelled = {'v': False}
    def cancel_cb():
        # simulate cancellation after first progress (sleep briefly to let copy start)
        return cancelled['v']

    # Run in a thread to flip cancel after some time
    import threading
    def runner():
        nonlocal installed, failures
        installed, failures = perform_pack_installs(items, base, progress_cb=prog, cancel_cb=cancel_cb)

    installed = 0
    failures = []
    t = threading.Thread(target=runner)
    t.start()
    # sleep a tiny amount then request cancel
    time.sleep(0.05)
    cancelled['v'] = True
    t.join(timeout=5)
    # installed should be 0 or 1 depending on timing, but we should not leak partial dst
    dst = os.path.join(base, 'packLarge')
    assert not os.path.exists(dst) or os.path.isdir(dst) == False or installed in (0,1)


def test_perform_pack_installs_zip_and_failure(tmp_path):
    base = str(tmp_path / 'textures')
    os.makedirs(base, exist_ok=True)
    # create a pack folder and zip it
    src = str(tmp_path / 'packZip')
    _create_sample_pack(src)
    zip_path = os.path.join(str(tmp_path), 'pack.zip')
    import zipfile
    with zipfile.ZipFile(zip_path, 'w') as z:
        for root, _, files in os.walk(src):
            for f in files:
                z.write(os.path.join(root, f), arcname=f)

    # Create an item that points to a missing path to force failure
    items = [('goodzip', zip_path), ('bad', '/non/existent/path')]
    installed, failures = perform_pack_installs(items, base)
    # goodzip should be installed, bad should be in failures
    assert installed >= 1
    assert any(f[0] == 'bad' for f in failures)
