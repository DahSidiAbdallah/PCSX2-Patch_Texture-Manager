import os, sys, tempfile, json
from PySide6.QtWidgets import QApplication
import main
from cheat_online import fetch_and_cache_cheats

print('Using python:', sys.executable)
app = QApplication([])

# Prepare a temporary cheats folder with one .pnach file
tmp = tempfile.mkdtemp(prefix='pcsx2_test_')
sample_path = os.path.join(tmp, 'DEADBEEF.pnach')
with open(sample_path, 'w', encoding='utf-8') as f:
    f.write('gametitle=Test Game\n// serials: SLUS-21234\n// CRC: 0xDEADBEEF\npatch=1,EE,00200000,extended,00000001\n')

w = main.MainWindow()
# Point Cheats tab to tmp folder and refresh
w.cheats_tab.cheats_dir.setText(tmp)
w.cheats_tab.refresh_list()
count = w.cheats_tab.list.count()
print('Installed PNACH list count:', count)
for i in range(count):
    print(' -', w.cheats_tab.list.item(i).text())

# Test fetcher directly for a sample CRC and serial
keys = ['DEADBEEF', 'SLUS-21234']
for k in keys:
    print('\nFetch for key:', k)
    try:
        res = fetch_and_cache_cheats(k)
        print(' -> type:', type(res), 'len:', len(res))
        if res:
            print('   sample:', json.dumps(res[0], ensure_ascii=False)[:100])
    except Exception as e:
        print(' -> fetch error:', e)

print('\nHeadless test finished.')

# Clean up (do not delete tmp to allow inspection)
# import shutil; shutil.rmtree(tmp)

# Quit the app cleanly
app.quit()
