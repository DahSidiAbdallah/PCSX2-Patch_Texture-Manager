from uncompyle6.main import decompile_file
in_pyc = r"c:\Users\DAH\Downloads\PCSX2 Patch_Texture Manager\__pycache__\main.cpython-313.pyc"
out_py = r"c:\Users\DAH\Downloads\PCSX2 Patch_Texture Manager\main_recovered.py"
with open(out_py, 'w', encoding='utf-8') as out:
    decompile_file(in_pyc, out)
print('DECOMPILE_OK')
