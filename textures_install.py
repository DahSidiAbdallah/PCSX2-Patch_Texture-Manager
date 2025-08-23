import os
import shutil
import zipfile
from typing import List, Tuple, Callable, Optional
import re

# Pure helper functions for installing texture packs without GUI dependencies.
# These are intentionally free of PySide6 imports so tests can import them headlessly.

def _folder_contains_images(folder: str) -> bool:
    exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
    try:
        for _, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(exts):
                    return True
    except Exception:
        return False
    return False


def _find_replacements(root: str) -> Optional[str]:
    # Prefer an explicit 'replacements' child that contains images
    try:
        for p, dirs, files in os.walk(root):
            if 'replacements' in dirs:
                cand = os.path.join(p, 'replacements')
                if _folder_contains_images(cand):
                    return cand
        # fallback: return first folder that contains images
        for p, dirs, files in os.walk(root):
            if _folder_contains_images(p):
                return p
    except Exception:
        return None
    return None


def _stream_copy_file(src: str, dst: str, cancel_cb: Callable[[], bool], file_progress_cb: Optional[Callable[[int,int], None]] = None, chunk_size: int = 16*1024):
    # Copy a file in chunks and check cancel callback between chunks
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    total = 0
    try:
        total = os.path.getsize(src)
    except Exception:
        total = 0
    written = 0
    with open(src, 'rb') as inf, open(dst, 'wb') as outf:
        while True:
            if cancel_cb():
                raise InterruptedError('Cancelled')
            chunk = inf.read(chunk_size)
            if not chunk:
                break
            outf.write(chunk)
            written += len(chunk)
            if file_progress_cb:
                try:
                    file_progress_cb(written, total)
                except Exception:
                    pass
    try:
        shutil.copystat(src, dst)
    except Exception:
        pass


def _copytree_stream(src: str, dst: str, cancel_cb: Callable[[], bool], file_progress_cb: Optional[Callable[[int,int], None]] = None):
    # Recursively copy directory src -> dst using streaming file copies to allow interruption
    if os.path.exists(dst):
        raise FileExistsError(dst)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = os.path.join(dst, rel) if rel != '.' else dst
        os.makedirs(target_root, exist_ok=True)
        for d in dirs:
            try:
                os.makedirs(os.path.join(target_root, d), exist_ok=True)
            except Exception:
                pass
        for f in files:
            s = os.path.join(root, f)
            t = os.path.join(target_root, f)
            if cancel_cb():
                raise InterruptedError('Cancelled')
            _stream_copy_file(s, t, cancel_cb, file_progress_cb=file_progress_cb)


def perform_pack_installs(
    items: List[Tuple[str, str]],
    base: str,
    target_hint: str = '',
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    file_progress_cb: Optional[Callable[[int, int, str, int, int], None]] = None,
) -> Tuple[int, List[Tuple[str, str, str]]]:
    """Install multiple packs into base. Returns (installed_count, failures).
    progress_cb(current, total, display) and file_progress_cb(idx, total_items, display, written, total_bytes)
    are optional callbacks for UI updates. cancel_cb should return True to request cancellation.
    """
    installed = 0
    failures: List[Tuple[str, str, str]] = []
    total = len(items)
    cancel_cb = cancel_cb or (lambda: False)
    progress_cb = progress_cb or (lambda c, t, d: None)
    file_progress_cb = file_progress_cb or (lambda idx, total_items, display, written, total_bytes: None)

    def _install_one(idx: int, display: str, src: str) -> Tuple[int, Optional[Tuple[str, str, str]]]:
        temp_dir = None
        try:
            if not os.path.exists(src):
                return 0, (display, src, 'Source path not found')

            # unzip if needed
            if os.path.isfile(src) and src.lower().endswith('.zip'):
                temp_dir = os.path.join(os.path.expanduser('~'), '.pcsx2_manager_tmp', f"unzip_{idx}")
                if os.path.exists(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass
                os.makedirs(temp_dir, exist_ok=True)
                with zipfile.ZipFile(src, 'r') as z:
                    z.extractall(temp_dir)
                src_folder = temp_dir
            else:
                src_folder = src

            repl = os.path.join(src_folder, 'replacements')
            if os.path.isdir(repl):
                chosen = _find_replacements(repl) or repl
            else:
                chosen = _find_replacements(src_folder) or src_folder

            if not chosen:
                return 0, None

            # infer dst name
            serial_candidate = None
            try:
                # Use a local SERIAL_RE to avoid importing the GUI module from a worker thread
                SERIAL_RE = re.compile(r"\b(SCUS|SLUS|SLES|SCES|SLPS|SLPM|SCPS|SCAJ|SLKA|ULUS|UCUS|PBPX|PAPX|TCUS|TCES)[-_ ]?\d{3,6}\b", re.IGNORECASE)
                m = SERIAL_RE.search(display or '')
                if m:
                    serial_candidate = m.group(0).upper()
            except Exception:
                serial_candidate = None

            if target_hint:
                target_name = target_hint
            elif serial_candidate:
                target_name = serial_candidate
            else:
                target_name = os.path.basename(display) or os.path.basename(chosen)
            target_name = os.path.basename(target_name)
            dst = os.path.join(base, target_name)

            if os.path.exists(dst):
                try:
                    shutil.rmtree(dst)
                except Exception as e:
                    return 0, (display, src, f"Unable to remove existing target: {e}")

            # compute total bytes for this pack
            total_bytes = 0
            for r, _, fs in os.walk(chosen):
                for fn in fs:
                    try:
                        total_bytes += os.path.getsize(os.path.join(r, fn))
                    except Exception:
                        pass

            # create file progress callback bound to this item
            def make_file_progress(i, t_items, disp, tb):
                def _file_progress(written, _file_total):
                    if cancel_cb():
                        return
                    try:
                        file_progress_cb(i, t_items, disp, written, tb)
                    except Exception:
                        pass

                return _file_progress

            try:
                _copytree_stream(chosen, dst, cancel_cb, file_progress_cb=make_file_progress(idx, total, display, total_bytes))
            except InterruptedError:
                try:
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                except Exception:
                    pass
                return 0, None
            return 1, None
        except Exception as e:
            return 0, (display, src, str(e))
        finally:
            try:
                if temp_dir and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except Exception:
                pass

    for idx, (display, src) in enumerate(items, start=1):
        if cancel_cb():
            break
        cnt, fail = _install_one(idx, display, src)
        installed += cnt
        if fail:
            failures.append(fail)
        progress_cb(idx, total, display)

    return installed, failures

