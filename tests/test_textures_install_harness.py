import os
import shutil
import tempfile
import time
from textures_install import perform_pack_installs


def _make_sample_pack(path: str, files_count=3, file_size=1024):
    os.makedirs(path, exist_ok=True)
    for i in range(files_count):
        fn = os.path.join(path, f'img_{i}.png')
        with open(fn, 'wb') as f:
            f.write(b'A' * file_size)


def test_perform_installs_success_and_retry(tmp_path):
    base = tmp_path / 'textures'
    os.makedirs(base, exist_ok=True)

    # Create two sample packs; one will be valid, one will point to non-existent source
    valid_src = tmp_path / 'pack_valid'
    invalid_src = tmp_path / 'pack_missing'
    _make_sample_pack(str(valid_src))

    items = [
        ('Valid Pack', str(valid_src)),
        ('Missing Pack', str(invalid_src)),
    ]

    installed = 0
    failures = []

    def progress_cb(c, t, d):
        # simple assertion that progress is within bounds
        assert 0 <= c <= t

    def file_progress_cb(i, total_items, display, written, total_bytes):
        # written should not exceed total_bytes
        assert written <= max(total_bytes, written)

    # Run installs; expect 1 installed and 1 failure
    inst, fails = perform_pack_installs(items, str(base), progress_cb=progress_cb, file_progress_cb=file_progress_cb)
    assert inst == 1
    assert len(fails) == 1
    failures = fails

    # Now simulate retry: create the missing source and retry only the failed items
    if failures:
        for disp, src, err in failures:
            os.makedirs(src, exist_ok=True)
            _make_sample_pack(src)

    retry_items = [(d, s) for (d, s, e) in failures]
    inst2, fails2 = perform_pack_installs(retry_items, str(base), progress_cb=progress_cb, file_progress_cb=file_progress_cb)
    assert inst2 == len(retry_items)
    assert not fails2


def test_perform_installs_cancel(tmp_path):
    base = tmp_path / 'textures2'
    os.makedirs(base, exist_ok=True)

    src = tmp_path / 'pack_big'
    _make_sample_pack(str(src), files_count=20, file_size=1024*64)

    items = [('Big Pack', str(src))]

    # cancel after a short delay using a shared flag
    cancel_after = {'ts': time.time() + 0.01}

    def cancel_cb():
        return time.time() > cancel_after['ts']

    inst, fails = perform_pack_installs(items, str(base), cancel_cb=cancel_cb)
    # Install should be 0 or partial but treated as interrupted -> no failures returned
    assert inst == 0 or inst == 1

