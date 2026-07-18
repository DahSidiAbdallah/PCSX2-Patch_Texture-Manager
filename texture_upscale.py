"""AI texture upscaling for games with no available texture-replacement pack.

Uses Real-ESRGAN's ncnn-vulkan portable build (github.com/xinntao/Real-ESRGAN-ncnn-vulkan)
to batch-upscale whatever PCSX2 has already dumped for a game via its own
"Dump Textures" graphics option into a texture-replacement pack it can load
directly. This is not live/real-time upscaling of gameplay -- it only has
something to work with once you've played the game at least once with
dumping enabled. The ncnn-vulkan build has no Python/CUDA dependency; it's a
portable .exe with bundled models that runs via Vulkan on any GPU.

Folder layout (confirmed against PCSX2's own GSTextureReplacements.cpp):
  <textures_dir>/<serial>/dumps/         -- PCSX2 writes original textures here
  <textures_dir>/<serial>/replacements/  -- PCSX2 loads replacement textures from here
"""
import os
import zipfile
from typing import Callable, Optional, Tuple

try:
    import requests
except Exception:
    requests = None

REALESRGAN_REPO = "xinntao/Real-ESRGAN-ncnn-vulkan"
REALESRGAN_MODEL = "realesrgan-x4plus"
TEXTURE_DUMP_SUBDIR = "dumps"
TEXTURE_REPLACEMENT_SUBDIR = "replacements"
BIN_DIR_NAME = "realesrgan-ncnn-vulkan"

_IMAGE_EXTS = ('.png', '.bmp', '.dds', '.tga', '.jpg', '.jpeg')


def dumped_textures_dir(textures_dir: str, serial: str) -> str:
    return os.path.join(textures_dir, serial, TEXTURE_DUMP_SUBDIR)


def replacement_textures_dir(textures_dir: str, serial: str) -> str:
    return os.path.join(textures_dir, serial, TEXTURE_REPLACEMENT_SUBDIR)


def has_dumped_textures(textures_dir: str, serial: str) -> bool:
    d = dumped_textures_dir(textures_dir, serial)
    if not os.path.isdir(d):
        return False
    for _root, _dirs, files in os.walk(d):
        if any(f.lower().endswith(_IMAGE_EXTS) for f in files):
            return True
    return False


def _binary_path(install_dir: str) -> str:
    exe = "realesrgan-ncnn-vulkan.exe" if os.name == 'nt' else "realesrgan-ncnn-vulkan"
    return os.path.join(install_dir, BIN_DIR_NAME, exe)


def ensure_realesrgan_binary(install_dir: str, progress_cb: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Download+extract the ncnn-vulkan portable build on first use. Cached
    under install_dir so later calls are a no-op. Returns the exe path, or
    None if it couldn't be obtained (no internet, no matching release asset,
    etc.) -- callers should treat that as "AI upscale unavailable right now"
    rather than a hard error."""
    exe_path = _binary_path(install_dir)
    if os.path.isfile(exe_path):
        return exe_path
    if requests is None:
        return None

    progress_cb = progress_cb or (lambda _msg: None)
    try:
        resp = requests.get(
            f'https://api.github.com/repos/{REALESRGAN_REPO}/releases/latest',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PCSX2-Manager/1.0'},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        assets = resp.json().get('assets', [])
        asset_url = None
        want = 'windows' if os.name == 'nt' else 'ubuntu'
        for asset in assets:
            name = asset.get('name', '').lower()
            if want in name and name.endswith('.zip'):
                asset_url = asset.get('browser_download_url')
                break
        if not asset_url:
            return None

        progress_cb("Downloading Real-ESRGAN…")
        target_dir = os.path.join(install_dir, BIN_DIR_NAME)
        os.makedirs(target_dir, exist_ok=True)
        zip_path = os.path.join(install_dir, "_realesrgan_dl.zip")
        with requests.get(asset_url, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

        progress_cb("Extracting…")
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(target_dir)
        try:
            os.remove(zip_path)
        except Exception:
            pass

        return exe_path if os.path.isfile(exe_path) else None
    except Exception:
        return None


def upscale_textures(exe_path: str, src_dir: str, dst_dir: str, scale: int = 4,
                      model: str = REALESRGAN_MODEL) -> Tuple[bool, str]:
    """Batch-upscale every dumped texture in src_dir into dst_dir using the
    ncnn-vulkan CLI's own folder mode (it walks src_dir itself; no per-file
    looping needed here). Returns (success, message)."""
    import subprocess

    if not os.path.isfile(exe_path):
        return False, "Real-ESRGAN binary not found."
    if not os.path.isdir(src_dir):
        return False, "No dumped textures found for this game."
    os.makedirs(dst_dir, exist_ok=True)
    try:
        result = subprocess.run(
            [exe_path, '-i', src_dir, '-o', dst_dir, '-s', str(scale), '-n', model],
            cwd=os.path.dirname(exe_path),
            capture_output=True, text=True, timeout=1800,
        )
        count = 0
        for _root, _dirs, files in os.walk(dst_dir):
            count += len(files)
        if result.returncode != 0 and count == 0:
            stderr = (result.stderr or '').strip()[:300]
            return False, f"Upscale failed: {stderr or 'unknown error'}"
        if count == 0:
            return False, "Upscale ran but produced no output files."
        return True, f"Upscaled {count} texture(s)."
    except subprocess.TimeoutExpired:
        return False, "Upscale timed out (30 min limit)."
    except Exception as e:
        return False, f"Upscale error: {e}"
