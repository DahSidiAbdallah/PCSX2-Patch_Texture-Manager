try:
    import PySide6
    print('PySide6 imported')
except Exception as e:
    import traceback, sys
    print('import-error', type(e).__name__, str(e))
    traceback.print_exc()
