import sys, os, time, tempfile, shutil
from PySide6.QtWidgets import QApplication
sys.path.insert(0, r'.')
from main import MainWindow

app = QApplication([])
win = MainWindow()
win.show()
# Prepare staging: create two sample packs under imports to be discovered by the UI
base = os.path.join(os.getcwd(), 'test_tmp_textures')
if os.path.exists(base):
    shutil.rmtree(base)
os.makedirs(base, exist_ok=True)
# create imports root
imports_root = win.textures_tab._imports_root(base)
shutil.rmtree(imports_root, ignore_errors=True)
os.makedirs(imports_root, exist_ok=True)
# pack1
p1 = os.path.join(imports_root, 'PackA')
os.makedirs(os.path.join(p1, 'replacements'), exist_ok=True)
with open(os.path.join(p1, 'replacements', 'img.png'), 'wb') as f:
    f.write(b'A'*1024)
# pack2
p2 = os.path.join(imports_root, 'PackB')
os.makedirs(os.path.join(p2, 'replacements'), exist_ok=True)
with open(os.path.join(p2, 'replacements', 'img2.png'), 'wb') as f:
    f.write(b'B'*1024)

# Point UI to base and import the staging packs
win.textures_tab.textures_dir.setText(base)
# call scan installed to pick up staged packs into UI
win.textures_tab.scan_installed_textures()
# select all packs in the list
lst = win.textures_tab.packs_list
for i in range(lst.topLevelItemCount()):
    it = lst.topLevelItem(i)
    it.setSelected(True)

# call the install action
win.textures_tab._install_selected_multiple()
# allow time for worker to run
for _ in range(20):
    app.processEvents()
    time.sleep(0.2)

# cleanup
try:
    shutil.rmtree(base)
    shutil.rmtree(imports_root)
except Exception:
    pass
print('Interactive GUI smoke script finished')
