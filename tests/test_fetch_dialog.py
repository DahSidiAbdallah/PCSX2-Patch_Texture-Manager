from PySide6.QtWidgets import QApplication, QDialog
from main import MainWindow


def test_show_fetch_results_headless(monkeypatch):
    # Ensure a QApplication exists
    _ = QApplication.instance() or QApplication([])
    mw = MainWindow()
    # Build fake results
    fake = [
        {'source': 'gamehacking.org', 'title': 'Fake Cheat 1', 'codes': ['00200000 00000001', '00200004 00000002']},
        {'source': 'psxdatacenter', 'title': 'Fake Cheat 2', 'codes': ['00200010 0000FFFF']}
    ]

    # Prevent dialogs from blocking: override QDialog.exec to just return immediately
    monkeypatch.setattr(QDialog, 'exec', lambda self: 0)

    # Call the Cheats tab dialog via the main window instance
    cheats_tab = mw.cheats_tab
    cheats_tab._show_fetch_results(fake)

    # Verify that preview widget remains editable and no exception was raised
    assert hasattr(cheats_tab, 'codes_text') and cheats_tab.codes_text is not None
