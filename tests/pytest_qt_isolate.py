import os
import sys
import subprocess
import pytest


def _is_gui_test(item):
    # heuristics: file name contains 'gui' or item uses QApplication in its source
    path = str(item.fspath)
    if 'gui' in os.path.basename(path).lower():
        return True
    try:
        src = open(path, 'r', encoding='utf-8', errors='ignore').read()
        if 'QApplication' in src or 'QtTest' in src:
            return True
    except Exception:
        pass
    return False


def pytest_collection_modifyitems(config, items):
    # Move GUI tests to be run in subprocesses. We will replace each such test
    # with a wrapper that runs the test nodeid in a subprocess and reports its result.
    new_items = []
    for item in list(items):
        if _is_gui_test(item):
            nodeid = item.nodeid

            def make_runner(nodeid):
                def runner():
                    # Run the single nodeid in a subprocess with an isolated interpreter
                    env = os.environ.copy()
                    # Ensure Qt uses appropriate platform plugin for subprocess
                    env.setdefault('QT_QPA_PLATFORM', 'offscreen')
                    cmd = [sys.executable, '-m', 'pytest', '-q', nodeid]
                    res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                    out = res.stdout.decode('utf-8', errors='replace')
                    if res.returncode != 0:
                        pytest.fail(f"GUI test subprocess failed for {nodeid}\n--- OUTPUT:\n{out}\n---")
                return runner

            new_item = pytest.Function.from_parent(item.parent, name=item.name, callobj=make_runner(nodeid))
            new_items.append(new_item)
        else:
            new_items.append(item)
    items[:] = new_items
