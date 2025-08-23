import sys
import types
import pytest

# Provide light-weight PySide6 stubs so tests can import main.py without GUI deps
if 'PySide6' not in sys.modules:
    fake = types.SimpleNamespace()
    # minimal nested modules used by main.py
    # Create simple modules with the required names so 'from PySide6.QtWidgets import QApplication, ...' succeeds
    qw = types.SimpleNamespace()
    # Define dummy classes/objects referenced in main.py (they won't be instantiated in tests)
    for name in ['QApplication','QMainWindow','QWidget','QFileDialog','QTabWidget','QVBoxLayout','QHBoxLayout','QFormLayout','QLineEdit','QTextEdit','QPushButton','QLabel','QHeaderView','QMessageBox','QListWidget','QProgressBar','QGroupBox','QComboBox','QCheckBox','QDialog','QListWidgetItem','QAbstractItemView','QRadioButton','QTreeWidget','QTreeWidgetItem','QMenu','QInputDialog']:
        setattr(qw, name, type(name, (), {}))
    qc = types.SimpleNamespace()
    # Provide a Signal callable that accepts args and returns a dummy object
    class _Signal:
        def __init__(self, *args, **kwargs):
            pass
        def connect(self, *a, **k):
            pass
        def emit(self, *a, **k):
            pass
    for name in ['Qt','QThread','QSize','QSettings','QTimer']:
        setattr(qc, name, type(name, (), {}))
    setattr(qc, 'Signal', _Signal)
    qg = types.SimpleNamespace()
    for name in ['QIcon','QPixmap','QDragEnterEvent','QDropEvent','QAction']:
        setattr(qg, name, type(name, (), {}))
    fake.QtWidgets = qw
    fake.QtCore = qc
    fake.QtGui = qg
    sys.modules['PySide6'] = fake
    sys.modules['PySide6.QtWidgets'] = qw
    sys.modules['PySide6.QtCore'] = qc
    sys.modules['PySide6.QtGui'] = qg

from main import parse_pnach_text, build_pnach


def test_preserve_bracket_header_verbatim():
    text = "[Cheats/8-bit Patch]\npatch=1,EE,00123456,extended,00FF00FF\n"
    pd = parse_pnach_text(text)
    out = build_pnach(pd)
    assert "[Cheats/8-bit Patch]" in out


def test_split_header_with_remainder():
    text = "[50/60 FPS] author-asasega\npatch=1,EE,00999999,extended,00000001\n"
    pd = parse_pnach_text(text)
    # comments should include the bracket header as its own line and the remainder as separate comment
    assert "[50/60 FPS]" in pd.comments
    assert any("author-asasega" in c for c in pd.comments)
    out = build_pnach(pd)
    assert "[50/60 FPS]" in out
    assert "author-asasega" in out


def test_split_three_merged_cheats_by_hints_and_prefixes():
    # Three distinct patches, no blank lines, each with different addresses and inline hints
    text = (
        "// first hint\n"
        "patch=1,EE,20AAAAAA,extended,00000001\n"
        "// second hint\n"
        "patch=1,EE,10BBBBBB,extended,00000002\n"
        "// third hint\n"
        "patch=1,EE,00CCCCCC,extended,00000003\n"
    )
    pd = parse_pnach_text(text)
    out = build_pnach(pd)
    # Expect multiple [Cheats/...] sections in output
    cheats_headers = [ln for ln in out.splitlines() if ln.startswith("[Cheats/")]
    assert len(cheats_headers) >= 2
    # ensure each hint text is present somewhere in the output
    assert "first hint" in out
    assert "second hint" in out
    assert "third hint" in out


def test_single_line_inline_hint_splitting():
    # single inline hint on one patch line should be recognized
    text = (
        "patch=1,EE,20AAAAAA,extended,00000001 // speed up\n"
        "patch=1,EE,20AAAAAB,extended,00000002 // speed up\n"
        "patch=1,EE,20AAAAAC,extended,00000003 // different\n"
    )
    pd = parse_pnach_text(text)
    out = build_pnach(pd)
    assert "speed up" in out
    assert "different" in out


def test_nested_bracket_headers_and_mixed_comments():
    text = (
        "[Group A]\n"
        "// note: start\n"
        "patch=1,EE,20AAA001,extended,00000001\n"
        "[Subgroup] author=dev\n"
        "; semicolon comment\n"
        "patch=1,EE,20AAA002,extended,00000002\n"
    )
    pd = parse_pnach_text(text)
    out = build_pnach(pd)
    # ensure both bracket headers are preserved
    assert "[Group A]" in out
    assert "[Subgroup]" in out
    # ensure semicolon comment is preserved somewhere
    assert any('semicolon' in ln for ln in out.splitlines())
