#!/usr/bin/env python3
"""Run tests isolating GUI tests into subprocesses to avoid Qt/COM crashes on Windows.

Behavior:
 - Collect all tests via pytest collection.
 - Run non-GUI tests in-process.
 - Run each GUI test (heuristic: file name contains 'gui' or source contains 'QApplication') in its own subprocess
   with QT_QPA_PLATFORM=offscreen and capture output.
 - Aggregate stdout/stderr into test_log.txt and return non-zero if any test failed.
"""
import os
import sys
import subprocess
import tempfile
import pytest


def is_gui_test(path):
    if 'gui' in os.path.basename(path).lower():
        return True
    try:
        src = open(path, 'r', encoding='utf-8', errors='ignore').read()
        if 'QApplication' in src or 'QtTest' in src:
            return True
    except Exception:
        pass
    return False


def collect_tests():
    # Use pytest's --collect-only via subprocess to list nodeids
    res = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = res.stdout.decode('utf-8', errors='replace')
    # Only lines containing '::' are test nodeids; ignore warnings/other lines
    nodeids = [line.strip() for line in out.splitlines() if line.strip() and '::' in line]
    return nodeids


def main():
    nodeids = collect_tests()
    gui = []
    non_gui = []
    for n in nodeids:
        # nodeid format: path::testname
        path = n.split('::', 1)[0]
        if is_gui_test(path):
            gui.append(n)
        else:
            non_gui.append(n)

    log_path = os.path.join(os.getcwd(), 'test_log.txt')
    failed = False
    with open(log_path, 'w', encoding='utf-8', errors='replace') as logf:
        if non_gui:
            logf.write('Running non-GUI tests (subprocess)\n')
            # Run non-GUI nodeids via subprocess so we capture stdout/stderr
            cmd = [sys.executable, '-m', 'pytest', '-q'] + non_gui
            p = subprocess.run(cmd, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            out = p.stdout.decode('utf-8', errors='replace')
            logf.write(out)
            logf.write(f'Non-GUI pytest exit: {p.returncode}\n')
            if p.returncode != 0:
                failed = True

        if gui:
            logf.write('\nRunning GUI tests in subprocesses\n')
            for nodeid in gui:
                env = os.environ.copy()
                env.setdefault('QT_QPA_PLATFORM', 'offscreen')
                cmd = [sys.executable, '-m', 'pytest', '-q', nodeid]
                p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                out = p.stdout.decode('utf-8', errors='replace')
                logf.write('\n--- GUI TEST: ' + nodeid + ' ---\n')
                logf.write(out)
                logf.write('\n--- END ---\n')
                if p.returncode != 0:
                    failed = True

    print('\nTest run complete. Log saved to', log_path)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
