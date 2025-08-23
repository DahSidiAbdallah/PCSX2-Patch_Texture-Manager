"""
Capture real screenshots from the running application.

Run this locally after installing dependencies (PySide6). It will create PNG files
under the `screenshots/` folder: `real_cheats.png`, `real_textures.png`, `real_bulk.png`.

PowerShell example:

    python -m venv .venv; .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    pip install PySide6
    python capture_screenshots.py

The script attempts to populate a minimal sample cheats folder so the Cheats tab shows entries.
"""
import os
import sys
import tempfile
import shutil

def main():
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
    except Exception as e:
        print('PySide6 is not installed or cannot be imported:', e)
        sys.exit(2)

    # Ensure screenshot output folder exists
    out_dir = os.path.join(os.path.dirname(__file__), 'screenshots')
    os.makedirs(out_dir, exist_ok=True)

    app = QApplication(sys.argv)

    # Import the main window
    import main as appmod

    # Prepare a temporary cheats folder with one sample .pnach
    tmp = tempfile.mkdtemp(prefix='pcsx2_screenshots_')
    sample_path = os.path.join(tmp, 'DEADBEEF.pnach')
    with open(sample_path, 'w', encoding='utf-8') as f:
        f.write('gametitle=Test Game\n// serials: SLUS-21234\n// CRC: 0xDEADBEEF\npatch=1,EE,00200000,extended,00000001\n')

    w = appmod.MainWindow()
    # Point Cheats tab to tmp folder and refresh list so UI shows data
    try:
        w.cheats_tab.cheats_dir.setText(tmp)
        w.cheats_tab.refresh_list()
    except Exception:
        pass

    # Show the window briefly (needed so widgets render correctly)
    w.show()

    # Process events a bit to let layouts settle
    for _ in range(10):
        app.processEvents()

    # Helper to capture a widget to a PNG file
    def capture_widget(widget, fname):
        try:
            # Ensure widget updates
            widget.repaint()
            app.processEvents()
            pix = widget.grab()
            out = os.path.join(out_dir, fname)
            pix.save(out)
            print('Wrote', out)
        except Exception as e:
            print('Failed to capture', widget, e)

    # Capture cheats tab
    try:
        capture_widget(w.cheats_tab, 'real_cheats.png')
    except Exception as e:
        print('Cheats capture failed:', e)

    # Capture textures tab
    try:
        capture_widget(w.textures_tab, 'real_textures.png')
    except Exception as e:
        print('Textures capture failed:', e)

    # Capture bulk tab
    try:
        capture_widget(w.bulk_tab, 'real_bulk.png')
    except Exception as e:
        print('Bulk capture failed:', e)

    # Clean up: do not remove tmp so you can inspect it if needed
    # shutil.rmtree(tmp)

    # Quit the app
    QTimer.singleShot(200, app.quit)
    app.exec()


if __name__ == '__main__':
    main()
