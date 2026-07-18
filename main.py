#!/usr/bin/env python3

import os
import shutil
import zipfile
import subprocess
import tempfile

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout,
    QHBoxLayout, QFormLayout, QLineEdit, QTextEdit, QPushButton, QLabel, QHeaderView,
    QMessageBox, QListWidget, QProgressBar, QGroupBox, QComboBox, QCheckBox,
    QDialog, QListWidgetItem, QAbstractItemView, QRadioButton,
    QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog, QScrollArea,
)
from PySide6.QtWidgets import *
import re
import json
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from collections import deque
import time
import logging

from PySide6.QtCore import Qt, QThread, Signal, QSize, QSettings, QTimer, QCoreApplication, QPoint, QPointF, QRectF
import sys
from PySide6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent, QAction, QPainter, QColor, QPen
import concurrent.futures

# ---------------------------- Windows native window-chrome support ----------------------------
# Qt's Qt.FramelessWindowHint strips the window styles Windows' own Snap feature
# (drag-to-top-to-maximize, drag-to-edge-to-half-screen) checks for, so a purely
# Qt-frameless window never gets Snap regardless of window-flag combinations. The
# documented fix (used by e.g. Windows Terminal/VS Code) is the opposite approach:
# keep the window fully native (no FramelessWindowHint at all, so WS_CAPTION/
# WS_THICKFRAME/Snap/shadow/rounded-corners all keep working normally), then use
# WM_NCCALCSIZE to claim the whole window rect as client area (so nothing is
# visually drawn in the space a native title bar would occupy) and WM_NCHITTEST to
# redirect clicks on our custom TitleBar to behave like the native caption. Only
# engaged on win32; other platforms keep the simpler FramelessWindowHint approach.
IS_WINDOWS = sys.platform == 'win32'
if IS_WINDOWS:
    import ctypes

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", _RECT * 3), ("lppos", ctypes.c_void_p)]

    class _MSG(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                    ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                    ("time", ctypes.c_ulong), ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]

    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    SM_CXFRAME = 32
    SM_CXPADDEDBORDER = 92
    HT_CLIENT = 1
    HT_CAPTION = 2
    HT_LEFT = 10
    HT_RIGHT = 11
    HT_TOP = 12
    HT_TOPLEFT = 13
    HT_TOPRIGHT = 14
    HT_BOTTOM = 15
    HT_BOTTOMLEFT = 16
    HT_BOTTOMRIGHT = 17

# Registry to keep running QThread-based workers alive if callers don't hold a reference
_ACTIVE_WORKERS: list = []

# Ensure any remaining QThread workers are asked to quit and waited on at process exit to
# reduce "QThread: Destroyed while thread '' is still running" warnings and possible
# platform-specific crashes during interpreter shutdown.
import atexit

def _wait_active_workers(timeout_ms: int = 2000):
    for w in list(_ACTIVE_WORKERS):
        try:
            if isinstance(w, QThread):
                try:
                    w.quit()
                except Exception:
                    pass
                try:
                    w.wait(timeout_ms)
                except Exception:
                    pass
        except Exception:
            pass

atexit.register(_wait_active_workers)

# Optional for online features elsewhere; not required for offline resolver
try:
    import requests  # optional for certain lookups
except Exception:
    requests = None


# Online cheat database integration
import cheat_online
from cheat_online import fetch_and_cache_cheats
import theme
import icons
from bs4 import BeautifulSoup

# ---------------------------- Helpers / Model ----------------------------

# module logger for debug messages
logger = logging.getLogger("pcsx2_manager")
if not logger.handlers:
    # default to WARNING to reduce noisy logs; callers can enable INFO/DEBUG when needed
    logging.basicConfig(level=logging.WARNING)


def fmt_speed(bps: Optional[float]) -> str:
    if bps is None:
        return '--'
    try:
        if bps <= 0:
            return '0 B/s'
        if bps < 1024:
            return f"{bps:.0f} B/s"
        if bps < 1024 * 1024:
            return f"{bps/1024:.2f} KiB/s"
        if bps < 1024 * 1024 * 1024:
            return f"{bps/(1024*1024):.2f} MiB/s"
        return f"{bps/(1024*1024*1024):.2f} GiB/s"
    except Exception:
        return '--'


def fmt_eta(sec: Optional[float]) -> str:
    if sec is None or sec == float('inf'):
        return '--:--'
    try:
        s = int(max(0, int(sec)))
        if s >= 3600:
            hh = s // 3600
            mm = (s % 3600) // 60
            ss = s % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        mm = s // 60
        ss = s % 60
        return f"{mm:02d}:{ss:02d}"
    except Exception:
        return '--:--'

HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")
SERIAL_RE = re.compile(
    r"\b(SCUS|SLUS|SLES|SCES|SLPS|SLPM|SCPS|SCAJ|SLKA|ULUS|UCUS|PBPX|PAPX|TCUS|TCES)[-_ ]?\d{3,6}\b",
    re.IGNORECASE
)
PNACH_PATCH_LINE = re.compile(
    r"^\s*patch\s*=\s*\d+\s*,\s*EE\s*,\s*([0-9A-Fa-f]{8})\s*,\s*(extended|word|short|byte)\s*,\s*([0-9A-Fa-f]{1,8})",
    re.IGNORECASE
)
TITLE_LINE = re.compile(r"^\s*gametitle\s*=\s*(.+)$", re.IGNORECASE)
CRC_IN_TEXT = re.compile(r"\bCRC\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{8})\b")
INI_BOOL = re.compile(r"^(true|false|enabled|disabled|1|0)$", re.I)


@dataclass
class PnachData:
    crc: Optional[str] = None            # 8-hex uppercase
    serials: List[str] = None            # list of serial strings
    title: Optional[str] = None
    raw_pairs: List[Tuple[str, str]] = None  # [(addr, value)] both 8-hex uppercase
    comments: List[str] = None
    # items preserves original file ordering: a list of either comment strings or (addr,value) tuples
    items: List[Any] = None

    def __post_init__(self):
        if self.serials is None:
            self.serials = []
        if self.raw_pairs is None:
            self.raw_pairs = []
        if self.comments is None:
            self.comments = []
        if self.items is None:
            self.items = []


@dataclass
class GameEntry:
    """A single detected/selected game, shared across tabs via MainWindow.current_game_changed."""
    serial: str = ""
    title: str = ""
    crc: Optional[str] = None
    source_path: Optional[str] = None


@dataclass
class AppState:
    """Shared state published by MainWindow so tabs don't have to reach into each
    other directly for the current PCSX2 paths / selected game."""
    pcsx2_paths: Dict[str, str] = None
    current_game: Optional[GameEntry] = None

    def __post_init__(self):
        if self.pcsx2_paths is None:
            self.pcsx2_paths = {}


# Guess common PCSX2 user dir locations

def default_pcsx2_user_dirs() -> List[str]:
    candidates: List[str] = []
    home = os.path.expanduser("~")
    candidates += [
        os.path.join(home, "Documents", "PCSX2"),                 # Windows
        os.path.join(home, ".config", "PCSX2"),                   # Linux
        os.path.join(home, "Library", "Application Support", "PCSX2"),  # macOS
        os.path.abspath(os.path.join(os.getcwd(), "PCSX2")),       # portable
    ]
    return [p for p in candidates if os.path.isdir(p)]


def ensure_subdirs(base: str) -> dict:
    paths = {
        "cheats": os.path.join(base, "cheats"),
        "cheats_ws": os.path.join(base, "cheats_ws"),
        "textures": os.path.join(base, "textures"),
        "logs": os.path.join(base, "logs"),
        "inis": os.path.join(base, "inis"),
    }
    for p in paths.values():
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            pass
    return paths


def normalize_crc(crc: str) -> Optional[str]:
    if not crc:
        return None
    crc = crc.strip().upper()
    return crc if HEX8.match(crc) else None


# Worker to download cover images without blocking UI
class CoverFetchWorker(QThread):
    fetched = Signal(str)  # path to cached image
    fetch_failed = Signal()

    def __init__(self, url_or_urls, cache_path: str, parent=None):
        """Accept either a single URL string or an iterable/list of candidate URLs to try in order.
        cache_path is the path where the successful content will be written.
        """
        super().__init__(parent)
        # Normalize to list of urls
        if isinstance(url_or_urls, (list, tuple)):
            self.urls = list(url_or_urls)
        else:
            self.urls = [url_or_urls]
        self.cache_path = cache_path

    def run(self):
        # If the optional requests dependency is missing, fall back to urllib so
        # cover fetching still works. This mirrors the basic GET logic below but
        # without the HEAD optimization.
        if requests is None:
            try:
                from urllib.request import urlopen
            except Exception:
                urlopen = None
            if urlopen is None:
                logger.warning("[CoverFetchWorker] Neither requests nor urllib available; cannot fetch covers")
                self.fetch_failed.emit()
                return
            
            attempted = []
            for candidate in self.urls:
                if not candidate:
                    continue
                attempted.append(candidate)
                try:
                    logger.debug(f"[CoverFetchWorker] Trying: {candidate}")
                    with urlopen(candidate, timeout=12) as resp:
                        status = getattr(resp, 'status', 200)
                        content = resp.read() or b''
                    if status == 200 and content:
                        try:
                            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                            with open(self.cache_path, 'wb') as fh:
                                fh.write(content)
                            # Record successful URL in index
                            try:
                                idx_dir = os.path.dirname(self.cache_path)
                                idx_file = os.path.join(idx_dir, 'index.json')
                                key = os.path.splitext(os.path.basename(candidate))[0]
                                data = {}
                                if os.path.isfile(idx_file):
                                    with open(idx_file, 'r', encoding='utf-8') as inf:
                                        data = json.load(inf)
                                data[key] = candidate
                                with open(idx_file, 'w', encoding='utf-8') as outf:
                                    json.dump(data, outf)
                            except Exception as e:
                                logger.debug(f"[CoverFetchWorker] Could not update index: {e}")
                            
                            logger.info(f"[CoverFetchWorker] ✓ Cover found: {os.path.basename(candidate)}")
                            self.fetched.emit(self.cache_path)
                            return
                        except (IOError, OSError) as e:
                            logger.error(f"[CoverFetchWorker] Failed to save cover: {e}")
                            self.fetch_failed.emit()
                            return
                except Exception as e:
                    logger.debug(f"[CoverFetchWorker] Failed: {candidate} - {e}")
                    continue
            
            logger.info(f"[CoverFetchWorker] ✗ No cover found (tried {len(attempted)} URLs)")
            self.fetch_failed.emit()
            return

        # Try each candidate URL in order. Prefer GET directly because
        # GitHub raw endpoints often do not honour HEAD requests. Any
        # successful response will be cached.
        attempted = []
        for candidate in self.urls:
            if not candidate:
                continue
            attempted.append(candidate)
            try:
                logger.debug(f"[CoverFetchWorker] Trying: {candidate}")
                resp = requests.get(candidate, timeout=12)
                status = getattr(resp, 'status_code', None)
                content = getattr(resp, 'content', None) or b''
                clen = len(content)
                
                if status == 200 and content:
                    try:
                        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                        with open(self.cache_path, 'wb') as fh:
                            fh.write(content)
                        # Update index.json for caching
                        idx_dir = os.path.dirname(self.cache_path)
                        idx_file = os.path.join(idx_dir, 'index.json')
                        key = os.path.splitext(os.path.basename(candidate))[0]
                        data = {}
                        if os.path.isfile(idx_file):
                            with open(idx_file, 'r', encoding='utf-8') as inf:
                                data = json.load(inf)
                        data[key] = candidate
                        with open(idx_file, 'w', encoding='utf-8') as outf:
                            json.dump(data, outf)
                        
                        logger.info(f"[CoverFetchWorker] ✓ Cover found: {os.path.basename(candidate)} ({clen} bytes)")
                        self.fetched.emit(self.cache_path)
                        return
                    except (IOError, OSError) as e:
                        logger.error(f"[CoverFetchWorker] Failed to save cover: {e}")
                        self.fetch_failed.emit()
                        return
                else:
                    logger.debug(f"[CoverFetchWorker] Not found (status={status}): {candidate}")
            except requests.exceptions.RequestException as e:
                logger.debug(f"[CoverFetchWorker] Request error: {e}")
            except Exception as e:
                logger.debug(f"[CoverFetchWorker] Unexpected error: {e}")
                continue
        
        # All candidates failed
        logger.info(f"[CoverFetchWorker] ✗ No cover found (tried {len(attempted)} URLs)")
        self.fetch_failed.emit()


def norm_serial_key(s: str) -> str:
    return (s or "").upper().replace("-", "").replace("_", "").replace(" ", "")


_COVERS_REPO_BASE = "https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/default"


def build_cover_candidates(serial: str) -> List[str]:
    """Build candidate cover-art URLs to probe against the public xlenore/ps2-covers
    index (the same collection PCSX2's own built-in Cover Downloader points people
    at). Confirmed from the repo's own docs: filenames are the canonical dashed
    serial verbatim (e.g. "SLUS-20123.jpg"), so that exact form is tried first;
    a couple of normalized fallbacks follow in case of inconsistent entries."""
    raw = (serial or '').strip()
    sk = norm_serial_key(raw)
    variants = []
    if raw:
        variants.append(raw.upper())
    if sk:
        variants.append(sk.upper())
    variants.append(raw.replace('-', '').replace('_', '').replace(' ', '').lower())
    seen = set()
    uniq = []
    for v in variants:
        if not v or v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return [f"{_COVERS_REPO_BASE}/{v}.jpg" for v in uniq]


def create_cover_placeholder(serial: str = "", size: int = 420) -> QPixmap:
    """Create a placeholder pixmap for when no cover is available."""
    placeholder = QPixmap(size, size)
    placeholder.fill(Qt.lightGray)
    
    try:
        painter = QPainter(placeholder)
        if not painter.isActive():
            logger.warning("[Placeholder] QPainter not active")
            return placeholder
        
        painter.setPen(QColor(80, 80, 80))
        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        
        # Calculate text positioning
        y_offset = size // 3
        
        # Draw main message
        painter.drawText(20, y_offset, size - 40, 40, 
                        Qt.AlignCenter | Qt.TextWordWrap, 
                        "No cover available")
        
        # Draw serial if provided
        if serial:
            font.setPointSize(10)
            font.setBold(False)
            painter.setFont(font)
            painter.drawText(20, y_offset + 50, size - 40, 40,
                           Qt.AlignCenter | Qt.TextWordWrap,
                           f"for {serial}")
        
        # Draw hint
        font.setPointSize(9)
        font.setItalic(True)
        painter.setFont(font)
        painter.setPen(QColor(120, 120, 120))
        painter.drawText(20, size - 80, size - 40, 60,
                        Qt.AlignCenter | Qt.TextWordWrap,
                        "(Right-click to retry)")
        
        painter.end()
        logger.debug(f"[Placeholder] Created placeholder for {serial or 'unknown'}")
    except Exception as e:
        logger.error(f"[Placeholder] Failed to create placeholder: {e}")
    
    return placeholder


def create_library_cover_placeholder(serial: str = "", found: Optional[bool] = None) -> QPixmap:
    """Portrait, dark-themed placeholder cover for LibraryView's detail panel --
    distinct from create_cover_placeholder()'s square light-gray one (used by the
    older Cheats/Textures tab previews), which would look out of place against
    the dark bordered cover frame here.

    `found` distinguishes "haven't tried fetching yet" (None, generic) from
    "tried and there's genuinely no cover for this serial" (False, explicit) --
    the caller shows a separate loading overlay while a fetch is in flight, so
    this placeholder is never shown mid-fetch.
    """
    w, h = theme.COVER_WIDTH, theme.COVER_HEIGHT
    pm = QPixmap(w, h)
    pm.fill(QColor(theme.COLOR_SURFACE_ALT))
    try:
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.COLOR_BORDER_STRONG))
        pen.setWidthF(1.5)
        p.setPen(pen)
        cx, cy = w / 2, h / 2 - 16
        p.drawEllipse(QPointF(cx, cy), 30, 30)
        p.drawEllipse(QPointF(cx, cy), 9, 9)
        p.setPen(QColor(theme.COLOR_TEXT_MUTED))
        font = p.font()
        font.setPointSize(9)
        p.setFont(font)
        label = "No cover art found" if found is False else (serial or "No cover art")
        p.drawText(QRectF(10, cy + 42, w - 20, 50), Qt.AlignHCenter | Qt.TextWordWrap, label)
        p.end()
    except Exception as e:
        logger.debug(f"[create_library_cover_placeholder] {e}")
    return pm


def bundled_lookup_title(serial: str) -> Optional[str]:
    """Search local bundled PSXDataCenter HTML files for a serial and return the title if found."""
    if not serial:
        return None
    s_norm = serial.upper().strip()
    files = ['ulist2.html', 'plist2.html', 'jlist2.html']
    for fname in files:
        if not os.path.isfile(fname):
            continue
        try:
            with open(fname, 'r', encoding='utf-8', errors='replace') as fh:
                soup = BeautifulSoup(fh, 'html.parser')
        except Exception:
            try:
                with open(fname, 'r', encoding='windows-1252', errors='replace') as fh:
                    soup = BeautifulSoup(fh, 'html.parser')
            except Exception:
                continue
        # Look for a td that contains the serial string exactly (allow variants)
        for td in soup.find_all('td'):
            txt = td.get_text(' ', strip=True)
            txt_u = txt.upper()
            if not txt:
                continue
            # exact match or contains but tokenized
            if s_norm in txt_u.split() or txt_u == s_norm:
                # find parent row
                tr = td.find_parent('tr')
                if not tr:
                    continue
                # prefer td with class col7 or col3 or nearest non-serial td
                title = None
                # Prefer col7/col3 cells which typically hold titles
                t = tr.find('td', attrs={'class': re.compile(r'col7|col3', re.I)})
                if t:
                    title = t.get_text(' ', strip=True)
                if not title:
                    # fallback: pick the best td text in the row excluding the serial cell
                    candidates = []  # list of (text, html)
                    for ctd in tr.find_all('td'):
                        ctxt = ctd.get_text(' ', strip=True)
                        if not ctxt:
                            continue
                        if s_norm in ctxt.upper():
                            continue
                        candidates.append((ctxt, str(ctd)))
                    if candidates:
                        # prefer candidates using common heuristics and HTML context
                        scored = [(_score_title_candidate(text, html), text) for (text, html) in candidates]
                        scored.sort(reverse=True)
                        title = scored[0][1]
                if title:
                    # sanitize
                    t = title.strip()
                    if t and t.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
                        return t
    return None


# ---- Shared local cheats database (loaded once, used by CheatsTab and LibraryView) ----
_CHEATS_DB_CACHE: Optional[dict] = None
_CHEATS_DB_INDEX: Optional[Dict[str, Tuple[dict, str]]] = None


def get_cheats_database() -> dict:
    """Load (and cache for the process lifetime) the built-in PS2 cheats database.
    Shared so the multi-MB JSON is parsed once, not once per widget that needs it."""
    global _CHEATS_DB_CACHE
    if _CHEATS_DB_CACHE is not None:
        return _CHEATS_DB_CACHE
    db_paths = [
        os.path.join(os.path.dirname(__file__), 'ps2_cheats_database_merged.json'),
        os.path.join(os.path.dirname(__file__), 'ps2_cheats_database.json'),
    ]
    for db_path in db_paths:
        try:
            if os.path.isfile(db_path):
                with open(db_path, 'r', encoding='utf-8') as f:
                    db = json.load(f)
                    games_count = len(db.get('games', []))
                    logger.info(f"[cheats_db] Loaded {games_count} games from {os.path.basename(db_path)}")
                    _CHEATS_DB_CACHE = db
                    return db
        except json.JSONDecodeError as e:
            logger.error(f"[cheats_db] Invalid JSON in {db_path}: {e}")
        except Exception as e:
            logger.error(f"[cheats_db] Failed to load {db_path}: {e}")
    logger.warning("[cheats_db] No cheats database found - online features only")
    _CHEATS_DB_CACHE = {"games": []}
    return _CHEATS_DB_CACHE


def get_cheats_index() -> Dict[str, Tuple[dict, str]]:
    """Return {normalized_serial: (game_dict, region_key)}, built once from get_cheats_database()."""
    global _CHEATS_DB_INDEX
    if _CHEATS_DB_INDEX is not None:
        return _CHEATS_DB_INDEX
    index: Dict[str, Tuple[dict, str]] = {}
    for game in get_cheats_database().get('games', []):
        for region_key, region in (game.get('regions') or {}).items():
            serial = region.get('serial')
            if serial:
                index[norm_serial_key(serial)] = (game, region_key)
    _CHEATS_DB_INDEX = index
    return index


def find_local_cheats(serial: str) -> Optional[Tuple[str, str, List[dict]]]:
    """Look up a serial in the local cheats database.
    Returns (title, crc, cheats) or None if the serial isn't in the local DB."""
    if not serial:
        return None
    entry = get_cheats_index().get(norm_serial_key(serial))
    if not entry:
        return None
    game, region_key = entry
    region = game['regions'][region_key]
    return game.get('title', 'Unknown Game'), region.get('crc', ''), region.get('cheats', [])


def write_cheats_pnach(title: str, serial: str, crc: str, cheats: List[dict], cheats_dir: str) -> str:
    """Build and write a .pnach file for the given cheats. Returns the written filepath.
    Raises on failure (missing crc/cheats_dir, I/O errors) -- callers handle user-facing messaging.
    Shared by CheatsTab's manual install button and LibraryView's one-click sync so there's a
    single pnach-writing implementation instead of two drifting copies.
    """
    if not crc:
        raise ValueError("Cannot write a .pnach file without a CRC value.")
    if not cheats_dir or not os.path.isdir(cheats_dir):
        raise ValueError("Invalid PCSX2 cheats folder path.")

    pnach_lines = [
        f"// {title}",
        f"// Serial: {serial}",
        f"// CRC: {crc}",
        f"// Generated by PCSX2 Manager",
        f"// {len(cheats)} cheat(s)",
        "",
        "gametitle=" + title,
        "",
    ]
    for cheat in cheats:
        pnach_lines.append(f"// {cheat.get('name', '')}")
        if cheat.get('description'):
            pnach_lines.append(f"// {cheat['description']}")
        for code in cheat.get('codes', []):
            pnach_lines.append(code)
        pnach_lines.append("")

    filepath = os.path.join(cheats_dir, f"{crc.upper()}.pnach")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(pnach_lines))
    return filepath


# ---- Curated texture-pack manifest ----
# texture_sources.json maps a game serial to a known community GitHub repo that
# publishes texture packs as release assets. There is no automatic/scraped
# texture-pack discovery -- entries are hand-verified (real repo, real release,
# real asset) rather than guessed, so most games will honestly report "not
# found" until the manifest is extended. Users can edit the JSON file directly.
_TEXTURE_MANIFEST_CACHE: Optional[dict] = None


def _load_texture_manifest() -> dict:
    global _TEXTURE_MANIFEST_CACHE
    if _TEXTURE_MANIFEST_CACHE is not None:
        return _TEXTURE_MANIFEST_CACHE
    path = os.path.join(os.path.dirname(__file__), 'texture_sources.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            _TEXTURE_MANIFEST_CACHE = json.load(f)
    except Exception as e:
        logger.warning(f"[textures] Failed to load texture_sources.json: {e}")
        _TEXTURE_MANIFEST_CACHE = {}
    return _TEXTURE_MANIFEST_CACHE


def get_texture_pack_options(serial: str) -> List[dict]:
    """Return the curated manifest entries for `serial` (may be empty, may have
    more than one -- some games have multiple community texture packs)."""
    if not serial:
        return []
    entries = _load_texture_manifest().get(serial.upper())
    if not entries:
        return []
    if isinstance(entries, dict):
        entries = [entries]
    return entries


def resolve_texture_release_asset(entry: dict) -> Optional[Tuple[str, str, str]]:
    """Resolve one manifest entry's current download URL for its GitHub release
    asset via GitHub's public releases API (no auth needed for public repos
    within rate limits). Returns (display_name, repo, download_url), or None if
    there's no matching release/asset or `requests` isn't available."""
    if requests is None or not entry:
        return None
    repo = entry.get('github_repo')
    asset_pattern = (entry.get('asset_pattern') or '').lower()
    if not repo:
        return None
    try:
        resp = requests.get(
            f'https://api.github.com/repos/{repo}/releases/latest',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'PCSX2-Manager/1.0'},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        for asset in resp.json().get('assets', []):
            name = asset.get('name', '')
            if not asset_pattern or name.lower() == asset_pattern:
                return entry.get('name', repo), repo, asset.get('browser_download_url')
    except Exception as e:
        logger.warning(f"[textures] Failed to resolve GitHub release for {repo}: {e}")
    return None


def resolve_texture_pack_url(serial: str) -> Optional[Tuple[str, str, str]]:
    """Resolve the first/default curated texture-pack option for `serial`.
    Convenience wrapper around get_texture_pack_options()/resolve_texture_release_asset()
    for callers that don't need to offer a choice between multiple packs."""
    options = get_texture_pack_options(serial)
    if not options:
        return None
    return resolve_texture_release_asset(options[0])


def _score_title_candidate(text: str, html: Optional[str] = None) -> int:
    """Return a heuristic score for a title candidate. Higher is better.
    Boosts multi-word, alphabetic content, presence of lowercase (likely proper titles),
    and punctuation like parentheses or colon. Penalizes short tokens, hex-like tokens,
    and common placeholders.
    """
    if not text:
        return -9999
    # sanitize leading punctuation/nbsp
    t = re.sub(r'^[\s\u00A0\._:\-\|]+', '', text).strip()
    tu = t.upper()
    # obvious placeholders should be rejected
    if tu in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
        return -9999
    # base score from length (favor substantial titles)
    score = max(0, len(t))
    # must contain letters to be useful
    if not re.search(r'[A-Za-z]', t):
        score -= 120
    else:
        score += 40
    # multi-word bonus
    words = [w for w in re.split(r'\s+', t) if w]
    if len(words) > 1:
        score += 14 * min(6, len(words))
    # lowercase presence is a good sign (titles often mixed case)
    if re.search(r'[a-z]', t):
        score += 24
    # punctuation often in titles
    if re.search(r'[\(\)\-:–—\.]', t):
        score += 10
    # penalize short ALL-CAPS tokens (likely abbreviations or placeholders)
    if t.isupper():
        # heavily penalize if many short tokens (e.g., 'INFO', 'DVD MENU', 'PS1')
        short_tokens = [w for w in words if len(w) < 5]
        if len(words) == 1 and len(t) < 6:
            score -= 60
        elif len(short_tokens) >= len(words) and len(words) <= 3:
            score -= 36
    # penalize hex-like tokens
    if re.fullmatch(r'[0-9A-Fa-f]{1,8}', t):
        score -= 100
    # prefer candidates with many alphabetic chars relative to length
    alpha = len(re.findall(r'[A-Za-z]', t))
    if alpha > 0:
        score += int((alpha / max(1, len(t))) * 40)
    # boost when HTML suggests a title cell (col3 or col7) or anchor/link text
    if html:
        hu = html.lower()
        if 'class="col3"' in hu or "class='col3'" in hu or 'class="col7"' in hu or "class='col7'" in hu:
            score += 60
        # prefer anchor text only if it's not the generic 'INFO' placeholder
        if '<a' in hu:
            # try to extract anchor text
            try:
                soup = BeautifulSoup(html, 'html.parser')
                a = soup.find('a')
                if a:
                    at = (a.get_text(' ', strip=True) or '').strip()
                    if at and at.upper() not in ('INFO', '詳細', 'DETAILS') and re.search(r'[A-Za-z]', at):
                        score += 36
                    else:
                        # generic anchors are less useful
                        score -= 18
            except Exception:
                score += 8
    return score


# Helpers extracted from build_pnach to reduce function complexity
def ai_label_for_group(label_hint, codes, inline_hints=None, used_labels=None):
    import re
    from collections import Counter
    used_labels = used_labels or set()
    # Use comment if it's meaningful
    if label_hint and not re.match(r"^(patch|cheat|code|modifier|fix|enable|disable|on|off|1|2|3|4|5|6|7|8|9|0| )+$", label_hint, re.I):
        label = label_hint.strip()
        if label not in used_labels:
            used_labels.add(label)
            return label
    # Use inline comment if present and meaningful
    if inline_hints:
        meaningful = [h.strip() for h in inline_hints if h and not re.match(r"^(patch|cheat|code|modifier|fix|enable|disable|on|off|1|2|3|4|5|6|7|8|9|0| )+$", h, re.I)]
        if meaningful:
            cnt = Counter(meaningful)
            label = cnt.most_common(1)[0][0]
            if label not in used_labels:
                used_labels.add(label)
                return label
    # Try to infer from code patterns and keywords.
    code_text = " ".join(f"{a} {v}" for a, v in codes)
    patterns = [
        (r"infinite.?ammo|unlimited.?ammo|max.?ammo|all.?ammo|endless.?ammo|never.?reload|no.?reload", "Infinite Ammo"),
        (r"one.?hit.?kill|1.?hit.?kill|kill.?in.?1|insta.?kill|instant.?kill|kill.?with.?one", "One-Hit Kill"),
        (r"invincib|invulnerab|god.?mode|no.?damage|no.?hit|no.?death|immortal|never.?die|undying|unharmed|invincible", "Invincibility"),
        (r"unlock.?char|all.?char|all.?fighters|all.?heroes|all.?players|all.?characters|every.?character|character.?select", "Unlock Characters"),
        (r"unlock.?level|all.?level|all.?stages|all.?maps|every.?level|stage.?select|open.?all.?levels", "Unlock Levels/Stages"),
        (r"unlock.?weapon|all.?weapon|all.?guns|all.?arms|every.?weapon|weapon.?select|all.?swords|all.?items.?unlocked", "Unlock All Weapons"),
        (r"unlock.?item|all.?item|all.?cards|all.?gear|all.?equipment|every.?item|item.?select|all.?collectibles|all.?costumes|all.?outfits", "Unlock All Items"),
        (r"exp|experience|level.?up|max.?level|lvl.?up|gain.?level|max.?exp|infinite.?exp|infinite.?experience|level.?999|level.?max", "EXP/Level Modifier"),
        (r"stat.?max|max.?stat|all.?stat|full.?stat|999.?stat|255.?stat|max.?strength|max.?defense|max.?attack|max.?magic|max.?skill|max.?ability|all.?abilities|all.?skills|all.?stats", "Max Stats"),
        (r"money|gil|zenny|cash|gold|coins|credits|points|score|infinite.?money|max.?money|max.?gold|max.?cash|max.?score|all.?points", "Money/Score Modifier"),
        (r"health|hp|life|max.?hp|full.?hp|restore.?hp|heal|infinite.?hp|infinite.?health|never.?hurt|max.?life|auto.?heal|auto.?recovery", "Health Modifier"),
        (r"mp|sp|ap|ep|energy|mana|magic.?points|infinite.?mp|max.?mp|infinite.?energy|max.?energy|full.?mp|full.?energy", "MP/Energy Modifier"),
        (r"timer|time.?stop|freeze.?time|infinite.?time|no.?timer|time.?modifier|slow.?time|fast.?time|pause.?timer|no.?countdown", "Timer Modifier"),
        (r"speed.?up|fast.?move|run.?fast|move.?speed|walk.?speed|move.?faster|faster.?movement|quick.?move|speed.?modifier|slow.?motion|slowmo|slow.?move", "Speed Modifier"),
        (r"gravity|low.?gravity|zero.?gravity|float|fly|anti.?gravity|moon.?jump|super.?jump|high.?jump", "Gravity Modifier"),
        (r"npc|enemy|ai|boss|monster|foe|all.?enemies|enemy.?modifier|enemy.?ai|boss.?rush|enemy.?stats|enemy.?hp|enemy.?damage", "NPC/Enemy Modifier"),
        (r"distance|range|reach|attack.?range|long.?range|melee.?range|shoot.?range", "Distance/Range Modifier"),
        (r"menu|pause|debug.?menu|test.?menu|secret.?menu|hidden.?menu|cheat.?menu|extra.?menu|bonus.?menu", "Menu/Debug Modifier"),
        (r"latency|input.?lag|input.?latency|controller.?lag|controller.?delay|input.?delay", "Input Latency Modifier"),
        (r"camera|fov|field.?of.?view|zoom|angle|perspective|camera.?control|free.?camera|camera.?hack|camera.?mod", "Camera Modifier"),
        (r"music|sound|audio|bgm|sfx|mute|volume|no.?music|no.?sound|disable.?music|disable.?sound|soundtrack|background.?music", "Music/Sound Modifier"),
        (r"language|region|pal|ntsc|japan|usa|europe|eng|fre|ger|ita|spa|por|rus|chi|kor|region.?free|region.?unlock|language.?select|multi.?language|all.?languages", "Language/Region Patch"),
        (r"save.?anywhere|save.?menu|quick.?save|auto.?save|save.?state|save.?anytime|save.?hack|save.?modifier|save.?location", "Save Anywhere/Save Modifier"),
        (r"walk.?through.?walls|no.?clip|noclip|clip.?off|ghost.?mode|walk.?anywhere|pass.?through.?walls|phase.?through.?walls|wall.?hack|collision.?off|collision.?hack", "No Clip/Walk Through Walls"),
        (r"debug|test|dev.?mode|developer|debug.?mode|test.?mode|beta.?mode|prototype.?mode|dev.?tools|dev.?menu|debug.?tools", "Debug/Test Mode"),
        (r"framerate|60.?fps|30.?fps|120.?fps|fps.?unlock|frame.?rate|unlocked.?fps|frame.?skip|frame.?rate.?modifier", "Framerate Modifier"),
        (r"fix|patch|workaround|bypass|skip|crash|freeze|hang|softlock|hardlock|anti.?crash|anti.?freeze|skip.?scene|skip.?cutscene|skip.?intro|skip.?logo|skip.?movie|skip.?video", "Fix/Bypass Patch"),
        (r"cheat|enable|disable|toggle|on.?off|activate|deactivate|switch|turn.?on|turn.?off", "Cheat Toggle"),
        (r"^20[0-9A-F]{6}", "Simple 8-bit Patch"),
        (r"^10[0-9A-F]{6}", "16-bit Patch"),
        (r"^00[0-9A-F]{6}", "8-bit Patch"),
        (r"^E0[0-9A-F]{6}", "Conditional Patch"),
        (r"^D0[0-9A-F]{6}", "Conditional Patch"),
        (r"^2[0-9A-F]{7}", "Write Patch"),
        (r"^1[0-9A-F]{7}", "Write Patch"),
        (r"^0[0-9A-F]{7}", "Write Patch"),
    ]
    if (not label_hint) and (not inline_hints or not any(h and not re.match(r"^(patch|cheat|code|modifier|fix|enable|disable|on|off|1|2|3|4|5|6|7|8|9|0| )+$", h, re.I) for h in inline_hints)):
        for pat, name in patterns:
            if re.search(pat, code_text, re.I):
                if name not in used_labels:
                    used_labels.add(name)
                    return name
    if len(codes) == 1:
        a, v = codes[0]
        label = f"Patch {a[-6:]}={v[-6:]}"
        if label not in used_labels:
            used_labels.add(label)
            return label
    n = len(used_labels) + 1
    label = f"Cheat Group {n} ({len(codes)} codes)"
    used_labels.add(label)
    return label


def split_group_if_mixed(label_hint, codes, hints):
    import re
    if not codes or len(codes) <= 1:
        return [(label_hint, codes, hints)]

    def _is_trivial_hint(h):
        return not h or re.match(r"^(patch|cheat|code|modifier|fix|enable|disable|on|off|1|2|3|4|5|6|7|8|9|0| )+$", h, re.I)

    meaningful_keys = [ (h.strip() if h and not _is_trivial_hint(h) else "__NO_HINT__") for h in hints ]
    if any(k != "__NO_HINT__" for k in meaningful_keys):
        res = []
        cur_codes = []
        cur_hints = []
        cur_key = meaningful_keys[0]
        for (a,v), k, h in zip(codes, meaningful_keys, hints):
            if k != cur_key and cur_codes:
                res.append((None if cur_key=="__NO_HINT__" else cur_key, list(cur_codes), list(cur_hints)))
                cur_codes = []
                cur_hints = []
                cur_key = k
            cur_codes.append((a,v))
            cur_hints.append(h)
        if cur_codes:
            res.append((None if cur_key=="__NO_HINT__" else cur_key, list(cur_codes), list(cur_hints)))
        if len(res) > 1:
            min_run = 1
            i = 0
            merged = []
            while i < len(res):
                key, rcodes, rhints = res[i]
                if len(rcodes) < min_run:
                    if merged:
                        pk, pcodes, phints = merged[-1]
                        merged[-1] = (pk, pcodes + rcodes, phints + rhints)
                    else:
                        if i+1 < len(res):
                            nk, ncodes, nhints = res[i+1]
                            res[i+1] = (nk, rcodes + ncodes, rhints + nhints)
                        else:
                            merged.append((key, rcodes, rhints))
                    i += 1
                    continue
                else:
                    merged.append((key, rcodes, rhints))
                    i += 1
            if len(merged) > 1:
                return merged
    prefixes = [a[:2] for a, _ in codes]
    uniq_pref = sorted(set(prefixes), key=lambda x: prefixes.count(x), reverse=True)
    if len(uniq_pref) > 1 and len(codes) >= 4:
        split_map = {}
        for p in uniq_pref:
            split_map[p] = []
        for a, v in codes:
            split_map[a[:2]].append((a, v))
        res = []
        for p in uniq_pref:
            grp = split_map.get(p, [])
            if grp:
                res.append((None, grp, [None]*len(grp)))
        return res
    return [(label_hint, codes, hints)]


def _set_label_pixmap_exact(label: 'QLabel', pixmap: 'QPixmap', max_dim: int = 420):
    """Scale pixmap down to fit within max_dim x max_dim, keep aspect ratio.
    Do not scale up small images; set the label fixed size to the resulting pixmap size
    so the image is displayed without cropping or stretching.
    """
    try:
        if not pixmap or pixmap.isNull():
            try:
                label.clear()
            except Exception:
                pass
            return
        w = pixmap.width()
        h = pixmap.height()
        if w <= 0 or h <= 0:
            label.clear()
            return
        # don't upscale; only scale down to max_dim
        maxd = int(max_dim or 512)
        scale = 1.0
        if max(w, h) > maxd:
            scale = float(maxd) / float(max(w, h))
        tw = max(1, int(w * scale))
        th = max(1, int(h * scale))
        scaled = pixmap.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(scaled)
        # make the label exactly the pixmap size so there's no cropping
        try:
            label.setFixedSize(scaled.size())
        except Exception:
            pass
    except Exception:
        try:
            label.clear()
        except Exception:
            pass


def parse_serials(text: str) -> List[str]:
    # finditer to capture full match
    return sorted({m.group(0).upper().replace("_", "-") for m in SERIAL_RE.finditer(text)})


def parse_pnach_text(text: str) -> PnachData:
    pd = PnachData()
    lines = text.splitlines()
    for line in lines:
        m = TITLE_LINE.match(line)
        if m:
            pd.title = m.group(1).strip()
            break
    pd.serials = parse_serials(text)
    mcrc = CRC_IN_TEXT.search(text)
    if mcrc:
        pd.crc = normalize_crc(mcrc.group(1))
    for line in lines:
        # Remove leading comment markers for patch scan, but keep original for comments
        scan_line = line.lstrip()
        # If the line starts with comment markers, strip them for patch recognition
        if scan_line.startswith("//") or scan_line.startswith("#") or scan_line.startswith(";"):
            scan_line = scan_line.lstrip("/#; ")
        # If it's a patch line, record as raw_pair
        m = PNACH_PATCH_LINE.match(scan_line)
        if m:
            # Accept all types, but only store address and value, pad value to 8
            addr = m.group(1).upper()
            val = m.group(3).upper().rjust(8, "0")
            pair = (addr, val)
            pd.raw_pairs.append(pair)
            # preserve inline hint from the original line if present (// ...)
            hint_m = re.search(r"//(.+)$", line)
            hint = hint_m.group(1).strip() if hint_m else None
            if hint:
                pd.items.append((addr, val, hint))
            else:
                pd.items.append(pair)
        else:
            # Skip empty lines
            if not line.strip():
                continue
            # Preserve bracket headers that may include trailing text on the same line.
            # Example: "[50/60 FPS] author-asasega ..." should become:
            #   "[50/60 FPS]"
            #   "author-asasega ..."
            mbr_full = re.match(r"^\s*\[([^\]]+)\]\s*(.+)$", line)
            if mbr_full:
                header = mbr_full.group(1).strip()
                remainder = mbr_full.group(2).rstrip()
                pd.comments.append(f"[{header}]")
                pd.items.append(f"[{header}]")
                if remainder:
                    pd.comments.append(remainder)
                    pd.items.append(remainder)
                continue
            # Skip title lines (already captured earlier)
            if TITLE_LINE.match(line):
                continue
            # Keep original leading comment markers (//, #, ;) and formatting; strip only trailing newlines/spaces
            pd.comments.append(line.rstrip())
            pd.items.append(line.rstrip())
    return pd


def parse_raw_8x8(text: str) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(("#", "//", ";")):
            continue
        s = s.replace(",", " ").replace("=", " ").replace("\t", " ")
        parts = [p for p in s.split() if p]
        # Accept patterns like: XXXXXXXX Y, XXXXXXXX YYYY, XXXXXXXX YYYYYYYY
        if len(parts) >= 2 and HEX8.match(parts[0]) and re.fullmatch(r"[0-9A-Fa-f]{1,8}", parts[1]):
            addr = parts[0].upper()
            val = parts[1].upper().rjust(8, "0")  # pad to 8
            pairs.append((addr, val))
    return pairs


def build_pnach(pd: PnachData) -> str:
    out = []
    if pd.title:
        out.append(f"gametitle={pd.title}")
    if pd.serials:
        out.append(f"// serials: {'; '.join(pd.serials)}")
    if pd.crc:
        out.append(f"// CRC: 0x{pd.crc}")
    if pd.comments:
        out.extend(pd.comments)
    out.append("")

    # Use module-level helpers for label inference and group splitting to keep this function concise
    from collections import Counter

    # Robust grouping: split by blank lines, comment headers, bracket headers, or contiguous patch lines
    lines = list(pd.items) if getattr(pd, 'items', None) else []

    groups = []
    current_label = None
    current_group = []
    inline_hints = []

    def flush_group():
        nonlocal current_label, current_group, inline_hints
        if current_group:
            groups.append((current_label, list(current_group), list(inline_hints)))
            current_group = []
            current_label = None
            inline_hints = []

    BRACKET_HDR = re.compile(r"^\s*\[(.*?)\]\s*$")
    for item in lines:
        if isinstance(item, str):
            mbr = BRACKET_HDR.match(item)
            if mbr:
                flush_group()
                current_label = "__RAW_LITERAL__:" + mbr.group(1).strip()
                continue
            m = re.match(r"\s*(//|#|;)\s*([^:]+):?", item)
            if m:
                flush_group()
                current_label = m.group(2).strip()
            elif item.strip() == "":
                flush_group()
        elif isinstance(item, tuple):
            if len(item) == 3:
                addr, val, hint = item
            else:
                addr, val = item
                hint = None
                m = re.search(r"//(.+)$", val)
                if m:
                    hint = m.group(1).strip()
                    val = val.split("//")[0].strip()
            current_group.append((addr, val))
            inline_hints.append(hint)
    flush_group()

    # Apply splitting pass using module helper
    post_groups = []
    for label, codes, hints in groups:
        splits = split_group_if_mixed(label, codes, hints)
        for s_label, s_codes, s_hints in splits:
            post_groups.append((s_label, s_codes, s_hints))
    groups = post_groups

    used_labels = set()
    if not groups:
        label = ai_label_for_group(pd.title, pd.raw_pairs, used_labels=used_labels)
        out.append(f"[Cheats/{label}]")
        for addr, val in pd.raw_pairs:
            out.append(f"patch=1,EE,{addr},extended,{val}")
    else:
        for idx, (label, codes, hints) in enumerate(groups, 1):
            if label and isinstance(label, str) and label.startswith("__RAW_LITERAL__:"):
                literal = label.split(':', 1)[1]
                out.append(f"[{literal}]")
            else:
                group_label = ai_label_for_group(label, codes, inline_hints=hints, used_labels=used_labels) or f"Cheat {idx}"
                out.append(f"[Cheats/{group_label}]")
            for addr, val in codes:
                out.append(f"patch=1,EE,{addr},extended,{val}")
    out.append("")
    out.append("// Generated by PCSX2 Patch & Texture Manager")
    return "\n".join(out).strip() + "\n"


# ---------------------------- Title Resolver (offline lists) ----------------------------

class ResolveWorker(QThread):
    progressed = Signal(int, int)  # current, total
    resolved = Signal(dict)        # mapping dict {key -> title}
    failed = Signal(str)

    def __init__(self, keys: List[str], local_map: Dict[str, str], use_bundled_lists: bool = False, try_online: bool = False):
        super().__init__()
        self.keys = keys
        self.local_map = {k.upper(): v for k, v in (local_map or {}).items()}
        self.use_bundled_lists = use_bundled_lists
        # only true if caller wants it AND requests is available
        self.try_online = bool(try_online and (requests is not None))
        self.out: Dict[str, str] = {}

    def run(self):
        total = len(self.keys)

        def norm_serial(s):
            return (s or "").upper().replace('-', '').replace('_', '').replace(' ', '')

        psx_map = {}
        psx_crc_map = {}
        # Use local HTML files placed next to the script: ulist2.html, plist2.html, jlist2.html
        if self.use_bundled_lists:
            urls = ['ulist2.html', 'plist2.html', 'jlist2.html']
            for url in urls:
                for enc in ('utf-8', 'windows-1252', 'shift_jis'):
                    try:
                        with open(url, 'r', encoding=enc) as f:
                            soup = BeautifulSoup(f, 'html.parser')
                    except Exception:
                        continue
                    for row in soup.find_all('tr'):
                        tds = row.find_all('td')
                        serial = title = crc = None
                        for td in tds:
                            txt = td.get_text(strip=True)
                            m = SERIAL_RE.search(txt)
                            if m and not serial:
                                serial = m.group(0)
                            if not title and len(txt) > 2 and not SERIAL_RE.search(txt) and not CRC_IN_TEXT.search(txt):
                                title = txt
                            mcrc = CRC_IN_TEXT.search(txt)
                            if mcrc and not crc:
                                crc = mcrc.group(1).upper()
                        if serial and title:
                            psx_map[norm_serial(serial)] = title
                        if serial and crc:
                            psx_crc_map[norm_serial(serial)] = crc
                        if crc and title:
                            psx_map[crc.upper()] = title

        # Parallel resolver per-key
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def resolve_one(key):
            k = (key or '').upper().strip()
            k_norm = norm_serial(k)
            title = self.local_map.get(k) or self.local_map.get(k_norm)
            crc = None
            found_title_html = None
            # Try local HTML bundles
            if not title and self.use_bundled_lists and k:
                title = psx_map.get(k_norm) or psx_map.get(k)
            if not crc and self.use_bundled_lists and k:
                crc = psx_crc_map.get(k_norm) or psx_crc_map.get(k)

            # Online lookup if requested and something missing
            if self.try_online and k and (not title or not crc):
                found_title, found_crc, found_html = cheat_online.resolve_serial_online([k, k_norm])
                if found_title and not title:
                    title = found_title
                    found_title_html = found_html
                if found_crc and not crc:
                    crc = found_crc

            # include optional matched html if present
            return (k, title, crc, found_title_html)

        max_workers = min(6, (os.cpu_count() or 4))
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(resolve_one, key): key for key in self.keys}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if isinstance(res, tuple) and len(res) >= 3:
                        k, title, crc = res[0], res[1], res[2]
                        html_snip = res[3] if len(res) > 3 else None
                        if title:
                            self.out[k] = title
                        if crc:
                            self.out[k + '_CRC'] = crc
                        if html_snip:
                            # store a small snippet for later debugging
                            try:
                                self.out[k + '_HTML'] = html_snip
                            except Exception:
                                pass
                except Exception:
                    pass
                completed += 1
                try:
                    self.progressed.emit(completed, total)
                except Exception:
                    pass

        self.resolved.emit(self.out)


class SingleOnlineLookup(QThread):
    """One-off focused lookup for a single serial using PSXDataCenter pages."""
    found = Signal(str)   # title
    failed = Signal()

    def __init__(self, serial: str, parent=None):
        super().__init__(parent)
        self.serial = serial

    def run(self):
        if requests is None:
            self.failed.emit()
            return
        serial = (self.serial or '').strip()
        if not serial:
            self.failed.emit()
            return
        try:
            title, _crc, _html = cheat_online.resolve_serial_online([serial, norm_serial_key(serial)])
        except Exception:
            logger.debug(f"[SingleOnlineLookup] lookup failed for {self.serial}", exc_info=True)
            self.failed.emit()
            return
        if title:
            self.found.emit(title)
        else:
            self.failed.emit()


# ---------------------------- GUI ----------------------------

class CheatsTab(QWidget):
    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self.parent.paths_changed.connect(self.load_paths)
        self._shutting_down = False  # Flag to prevent new workers during shutdown
        self.mapping: Dict[str, str] = {}  # CRC/Serial -> Title
        # persistent mapping store path (auto-load/save)
        self.map_store_path = os.path.join(os.path.expanduser("~"), ".pcsx2_manager_mapping.json")
        # create minimal widgets early so helper methods can use them safely
        self.list = QListWidget()
        self.progress = QProgressBar()
        
        # Debounce timer for auto-title to prevent freezing on every keystroke
        self._autotitle_timer = QTimer()
        self._autotitle_timer.setSingleShot(True)
        self._autotitle_timer.setInterval(500)  # 500ms delay
        self._autotitle_timer.timeout.connect(self._do_autotitle)
        
        # Load built-in cheats database
        self.cheats_database = self._load_cheats_database()
        
        self._build_ui()
        # load persisted mapping if present
        try:
            if os.path.isfile(self.map_store_path):
                with open(self.map_store_path, 'r', encoding='utf-8') as fh:
                    obj = json.load(fh)
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k and v:
                                self.mapping[str(k).upper()] = str(v)
        except Exception as e:
            logger.warning(f"Failed to load mapping: {e}")
        self.refresh_list()

    def save_mapping(self, path: Optional[str] = None):
        """Persist the current mapping to a JSON file. If path is provided, use that, else use default store."""
        try:
            outp = path or self.map_store_path
            # write a stable sorted mapping
            with open(outp, 'w', encoding='utf-8') as fh:
                json.dump({k: self.mapping[k] for k in sorted(self.mapping.keys())}, fh, ensure_ascii=False, indent=2)
            # reflect chosen path in UI if user-specified via load
            if path and hasattr(self, 'map_path'):
                self.map_path.setText(outp)
            return True
        except (IOError, OSError) as e:
            logger.error(f"Failed to save mapping to {outp}: {e}")
            return False
    
    def _load_cheats_database(self) -> dict:
        """Load the built-in PS2 cheats database (shared module-level cache -- see get_cheats_database())."""
        return get_cheats_database()

    # ---- Worker management to prevent GC / crashes ----
    def _start_worker(self, worker: QThread):
        # Don't start new workers if shutting down
        if getattr(self, '_shutting_down', False):
            return
        # Keep a strong reference so the worker isn't GC'd mid-run
        if not hasattr(self, "_workers"):
            self._workers = []
        worker.setParent(self)
        self._workers.append(worker)
        def _cleanup():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()
        worker.finished.connect(_cleanup)
        worker.start()

    def _preview_context_menu(self, pos):
        # Show context menu with Refresh Cover action
        menu = QMenu(self)
        act_refresh = menu.addAction("Refresh Cover")
        act = menu.exec_(self.preview_cover.mapToGlobal(pos))
        if act == act_refresh:
            # Force re-download by removing cached file and spawning worker.
            serial = self.preview_serial.text().strip()
            if not serial:
                try:
                    sel = self.packs_list.selectedItems()
                    if sel:
                        serial = (sel[0].data(0, Qt.UserRole + 2) or '').strip()
                except Exception:
                    serial = ''
            serial_key = norm_serial_key(serial)
            if not serial_key:
                return
            cache_name = os.path.join(self._thumb_cache, f"cover_{serial_key}.jpg")
            try:
                if os.path.isfile(cache_name):
                    os.remove(cache_name)
            except Exception:
                pass
            remote_url = f"https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/default/{serial_key}.jpg"
            # Build candidate variants to probe (normalized, original, no-separators, lower)
            raw = (serial or '').strip()
            sk = norm_serial_key(raw)
            variants = []
            if sk:
                variants.append(sk.upper())
            if raw:
                variants.append(raw.upper())
            variants.append(raw.replace('-', '').replace('_', '').replace(' ', '').upper())
            variants.append((raw.replace('-', '').replace('_', '').replace(' ', '')).lower())
            variants.append(sk.lower())
            seen = set()
            uniq = []
            for v in variants:
                if not v: continue
                if v in seen: continue
                seen.add(v)
                uniq.append(v)
            candidates = [f"https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/default/{v}.jpg" for v in uniq]
            # Prefer previously successful candidate if recorded in index.json
            try:
                idx_file = os.path.join(self._thumb_cache, 'index.json')
                if os.path.isfile(idx_file):
                    with open(idx_file, 'r', encoding='utf-8') as inf:
                        idx = json.load(inf)
                    # find any recorded key matching our variants
                    for v in uniq:
                        if v in idx:
                            known = idx[v]
                            if known in candidates:
                                candidates.remove(known)
                                candidates.insert(0, known)
                                break
            except Exception:
                pass
            self.preview_loading.setVisible(True)

            def _on_fetched(path: str):
                try:
                    pm = QPixmap(path)
                    if pm and not pm.isNull():
                        _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                except Exception:
                    self.preview_cover.clear()
                finally:
                    self.preview_loading.setVisible(False)

            def _on_failed():
                try:
                    # try local cache first
                    if os.path.isfile(cache_name):
                        pm = QPixmap(cache_name)
                        if pm and not pm.isNull():
                            _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                            return
                    # fallback to bundled logo.png if available
                    bundled = os.path.join(os.path.dirname(__file__), 'logo.png')
                    if os.path.isfile(bundled):
                        pm = QPixmap(bundled)
                        if pm and not pm.isNull():
                            _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                            return
                    # Show placeholder
                    placeholder = create_cover_placeholder(serial)
                    if placeholder and not placeholder.isNull():
                        _set_label_pixmap_exact(self.preview_cover, placeholder, max_dim=420)
                except Exception:
                    try:
                        self.preview_cover.clear()
                    except Exception:
                        pass
                finally:
                    self.preview_loading.setVisible(False)

            worker = CoverFetchWorker(candidates, cache_name, parent=self)
            worker.fetched.connect(_on_fetched)
            worker.fetch_failed.connect(_on_failed)
            self._start_worker(worker)

    def _build_ui(self):
        # Create a scroll area for the entire tab content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        
        # Create a container widget for all content
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG)
        layout.setSpacing(theme.SPACING_MD)
        
        # Quick Start Guide (collapsible)
        self.quick_start_group = QGroupBox("Quick Start Guide")
        self.quick_start_group.setCheckable(True)
        self.quick_start_group.setChecked(True)  # Expand by default for beginners
        qs_layout = QVBoxLayout()
        quick_start_text = QLabel(
            "<b>How to add cheats:</b><br>"
            "1. Enter your game's <b>Serial</b> (e.g., SLUS-12345) or <b>CRC</b><br>"
            "2. Click <b>Fetch Online Cheats</b> or paste codes below<br>"
            "3. Click <b>Generate Preview</b> to see the result<br>"
            "4. Click <b>Save to Cheats</b> to install<br><br>"
            "<i>Tip: You can drag & drop .pnach files directly!</i>"
        )
        quick_start_text.setWordWrap(True)
        qs_layout.addWidget(quick_start_text)
        self.quick_start_group.setLayout(qs_layout)
        layout.addWidget(self.quick_start_group)
        
        # Built-in Cheats Browser (NEW FEATURE)
        self.browser_group = QGroupBox("Browse Built-in Cheats Database")
        self.browser_group.setCheckable(True)
        self.browser_group.setChecked(True)  # Open by default
        browser_layout = QVBoxLayout()
        
        # Info label
        browser_info = QLabel(
            f"<b>{len(self.cheats_database.get('games', []))} popular PS2 games</b> with cheats for different regions (PAL, NTSC-U, NTSC-J)<br>"
            "Select a game and region, choose cheats, then click 'Install Selected Cheats'"
        )
        browser_info.setWordWrap(True)
        browser_layout.addWidget(browser_info)
        
        # Game selector with search and letter filter
        search_label = QLabel("<b>Search Games:</b>")
        browser_layout.addWidget(search_label)
        
        # Search box
        self.game_search = QLineEdit()
        self.game_search.setPlaceholderText("Type game title to search... (e.g., 'Final Fantasy', 'Metal Gear')")
        self.game_search.textChanged.connect(self._on_game_search_changed)
        browser_layout.addWidget(self.game_search)
        
        # Letter filter buttons
        letter_row = QWidget()
        letter_layout = QHBoxLayout(letter_row)
        letter_layout.setContentsMargins(0, 5, 0, 5)
        letter_layout.addWidget(QLabel("Filter by first letter:"))
        
        self.letter_buttons = {}
        letters = "0-9 A B C D E F G H I J K L M N O P Q R S T U V W X Y Z ALL".split()
        for letter in letters:
            btn = QPushButton(letter)
            btn.setMaximumWidth(40)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, l=letter: self._on_letter_filter_clicked(l))
            self.letter_buttons[letter] = btn
            letter_layout.addWidget(btn)
        
        letter_layout.addStretch()
        browser_layout.addWidget(letter_row)
        
        # Game list with search results
        game_list_label = QLabel("<b>Available Games:</b>")
        browser_layout.addWidget(game_list_label)
        
        # Store current filter state (initialize BEFORE populate_game_list)
        self._current_letter_filter = None
        self._current_search = ""
        
        self.game_list_widget = QListWidget()
        self.game_list_widget.itemSelectionChanged.connect(self._on_game_list_selected)
        self.game_list_widget.setMinimumHeight(150)
        self._populate_game_list()
        browser_layout.addWidget(self.game_list_widget)
        
        # Region selector
        region_row = QWidget()
        region_layout = QHBoxLayout(region_row)
        region_layout.setContentsMargins(0, 5, 0, 5)
        region_layout.addWidget(QLabel("Region:"))
        self.region_selector = QComboBox()
        self.region_selector.addItem("-- Select region --", None)
        self.region_selector.currentIndexChanged.connect(self._on_region_selected)
        region_layout.addWidget(self.region_selector, 1)
        
        # Serial/CRC info display
        self.region_info_label = QLabel("")
        self.region_info_label.setObjectName(theme.OBJ_MUTED_LABEL)
        region_layout.addWidget(self.region_info_label)
        browser_layout.addWidget(region_row)
        
        # Cheats list with checkboxes
        cheats_label = QLabel("<b>Available Cheats:</b>")
        browser_layout.addWidget(cheats_label)
        
        self.cheats_tree = QTreeWidget()
        self.cheats_tree.setHeaderLabels(["Cheat Name", "Description"])
        self.cheats_tree.setColumnWidth(0, 250)
        self.cheats_tree.setAlternatingRowColors(True)
        self.cheats_tree.setMinimumHeight(200)
        browser_layout.addWidget(self.cheats_tree)
        
        # Action buttons
        browser_actions = QWidget()
        browser_actions_layout = QHBoxLayout(browser_actions)
        browser_actions_layout.setContentsMargins(0, 5, 0, 5)
        
        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.clicked.connect(self._select_all_cheats)
        self.btn_select_all.setEnabled(False)
        
        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_deselect_all.clicked.connect(self._deselect_all_cheats)
        self.btn_deselect_all.setEnabled(False)
        
        self.btn_install_selected = QPushButton("Install Selected Cheats")
        self.btn_install_selected.setMinimumHeight(40)
        self.btn_install_selected.setObjectName(theme.OBJ_SUCCESS_BUTTON)
        self.btn_install_selected.clicked.connect(self._install_selected_cheats)
        self.btn_install_selected.setEnabled(False)
        
        browser_actions_layout.addWidget(self.btn_select_all)
        browser_actions_layout.addWidget(self.btn_deselect_all)
        browser_actions_layout.addStretch()
        browser_actions_layout.addWidget(self.btn_install_selected)
        browser_layout.addWidget(browser_actions)
        
        self.browser_group.setLayout(browser_layout)
        layout.addWidget(self.browser_group)
        
        # Target directories panel (simplified, collapsible)
        self.paths_group = QGroupBox("PCSX2 Folders (Auto-detected)")
        self.paths_group.setCheckable(True)
        self.paths_group.setChecked(False)
        fl = QFormLayout(self.paths_group)
        self.cheats_dir = QLineEdit()
        self.cheats_dir.setReadOnly(True)
        self.textures_dir = QLineEdit()
        self.textures_dir.setReadOnly(True)
        self.btn_browse_cheats = QPushButton("Change…")
        self.btn_browse_cheats.clicked.connect(lambda: self._pick_dir(self.cheats_dir))
        self.btn_browse_textures = QPushButton("Change…")
        self.btn_browse_textures.clicked.connect(lambda: self._pick_dir(self.textures_dir))

        fl.addRow("Cheats folder:", self._row(self.cheats_dir, self.btn_browse_cheats))
        fl.addRow("Textures folder:", self._row(self.textures_dir, self.btn_browse_textures))
        layout.addWidget(self.paths_group)

        # Main cheat builder panel (simplified)
        build_group = QGroupBox("Add Cheats to Your Game")
        bl = QVBoxLayout(build_group)
        
        # Basic info section
        basic_info = QWidget()
        basic_layout = QFormLayout(basic_info)
        basic_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Game title (auto-filled)")
        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText("e.g., SLUS-12345")
        self.serial_edit.setToolTip("The game's serial number, usually found on the disc or in PCSX2")
        self.crc_edit = QLineEdit()
        self.crc_edit.setPlaceholderText("e.g., F4715852 (optional)")
        self.crc_edit.setToolTip("8-digit hex code identifying your game version. Leave empty if unsure.")
        
        basic_layout.addRow("Game Title:", self.title_edit)
        basic_layout.addRow("Serial Number:", self.serial_edit)
        basic_layout.addRow("CRC (optional):", self.crc_edit)
        bl.addWidget(basic_info)
        
        # Action buttons (prominent)
        action_row = QWidget()
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 10, 0, 10)
        
        self.btn_fetch_online = QPushButton("Fetch Online Cheats")
        self.btn_fetch_online.setMinimumHeight(40)
        self.btn_fetch_online.setToolTip("Download cheats from online databases")
        self.btn_fetch_online.clicked.connect(self._fetch_online_cheats)
        
        self.btn_open_pnach = QPushButton("Open Cheat File")
        self.btn_open_pnach.setMinimumHeight(40)
        self.btn_open_pnach.setToolTip("Load an existing .pnach cheat file")
        self.btn_open_pnach.clicked.connect(self._open_pnach_file)
        
        action_layout.addWidget(self.btn_fetch_online)
        action_layout.addWidget(self.btn_open_pnach)
        bl.addWidget(action_row)
        
        # Codes editor
        codes_label = QLabel("Cheat Codes:")
        bl.addWidget(codes_label)
        self.codes_text = QTextEdit()
        self.codes_text.setPlaceholderText(
            "Paste or edit cheat codes here...\n\n"
            "Supported formats:\n"
            "• Raw codes (XXXXXXXX YYYYYYYY)\n"
            "• PNACH format (patch=1,EE,XXXXXXXX,extended,YYYYYYYY)\n"
            "• Format is auto-detected"
        )
        self.codes_text.setMinimumHeight(150)
        bl.addWidget(self.codes_text)
        
        # Generate and Save buttons
        action_row2 = QWidget()
        action_layout2 = QHBoxLayout(action_row2)
        action_layout2.setContentsMargins(0, 5, 0, 5)
        
        self.btn_make = QPushButton("Preview")
        self.btn_make.setMinimumHeight(35)
        self.btn_make.setToolTip("Preview how the cheat file will look")
        self.btn_make.clicked.connect(self._generate_preview)

        self.btn_save = QPushButton("Save to PCSX2")
        self.btn_save.setMinimumHeight(35)
        self.btn_save.setToolTip("Install the cheats to your PCSX2 folder")
        self.btn_save.clicked.connect(self._save_to_cheats)
        
        action_layout2.addWidget(self.btn_make)
        action_layout2.addWidget(self.btn_save)
        bl.addWidget(action_row2)
        
        # Preview (collapsible)
        self.preview_group = QGroupBox("Preview")
        self.preview_group.setCheckable(True)
        self.preview_group.setChecked(False)
        preview_layout = QVBoxLayout()
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(200)
        preview_layout.addWidget(self.preview)
        self.preview_group.setLayout(preview_layout)
        bl.addWidget(self.preview_group)
        
        layout.addWidget(build_group)
        
        # Advanced options (collapsible)
        self.advanced_group = QGroupBox("Advanced Options")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        adv_layout = QVBoxLayout(self.advanced_group)
        
        # Open any file button
        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_open_codes = QPushButton("Open Any File…")
        self.btn_open_codes.clicked.connect(self._open_codes_file)
        mode_layout.addWidget(self.btn_open_codes)
        mode_layout.addStretch()
        adv_layout.addWidget(mode_row)
        
        # Title resolver
        resolver_subgroup = QGroupBox("Title Auto-Detection")
        resolver_layout = QVBoxLayout()
        
        map_row = QWidget()
        map_layout = QHBoxLayout(map_row)
        map_layout.setContentsMargins(0, 0, 0, 0)
        self.map_path = QLineEdit()
        self.map_path.setPlaceholderText("Custom title mapping file (optional)")
        self.btn_load_map = QPushButton("Load…")
        self.btn_load_map.clicked.connect(self._load_mapping)
        map_layout.addWidget(self.map_path)
        map_layout.addWidget(self.btn_load_map)
        resolver_layout.addWidget(map_row)
        
        self.chk_offline_lists = QCheckBox("Use offline game database")
        self.chk_offline_lists.setToolTip("Use bundled PSXDataCenter lists for offline title lookup")
        self.chk_offline_lists.setChecked(True)
        
        self.chk_online = QCheckBox("Enable online lookup")
        self.chk_online.setToolTip("Search PSXDataCenter.com for game titles (requires internet)")
        
        self.btn_resolve = QPushButton("Resolve Title Now")
        self.btn_resolve.setToolTip("Look up the game title using the Serial/CRC you entered")
        self.btn_resolve.clicked.connect(self._resolve_title_clicked)
        
        resolver_layout.addWidget(self.chk_offline_lists)
        resolver_layout.addWidget(self.chk_online)
        resolver_layout.addWidget(self.btn_resolve)
        
        self.progress.setMinimum(0)
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        self.progress.setMaximumHeight(15)
        resolver_layout.addWidget(self.progress)
        
        self.source_label = QLabel("")
        self.source_label.setObjectName(theme.OBJ_MUTED_LABEL)
        resolver_layout.addWidget(self.source_label)
        
        resolver_subgroup.setLayout(resolver_layout)
        adv_layout.addWidget(resolver_subgroup)
        
        layout.addWidget(self.advanced_group)

        # Existing cheats list
        list_group = QGroupBox("Installed Cheats")
        v2 = QVBoxLayout(list_group)
        
        # Search/filter bar
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 5)
        search_layout.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by game name or CRC...")
        self.search_box.textChanged.connect(self._filter_existing_cheats)
        search_layout.addWidget(self.search_box)
        v2.addWidget(search_row)
        
        v2.addWidget(self.list)
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.clicked.connect(self.refresh_list)
        v2.addWidget(self.btn_refresh)
        layout.addWidget(list_group)

        # Set the container as the scroll area's widget
        scroll.setWidget(container)
        
        # Set the scroll area as the main layout for this tab
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        # QoL: auto-title when user edits CRC/Serial (debounced to prevent freezing)
        self.serial_edit.textChanged.connect(lambda: self._autotitle_timer.start())
        self.crc_edit.textChanged.connect(lambda: self._autotitle_timer.start())

        # Drag & Drop
        self.setAcceptDrops(True)

    

    

    def _fetch_online_cheats(self):
        # Automatically collect serial/CRC keys from several places:
        #  - explicit CRC field
        #  - explicit serial field (semicolon separated)
        #  - any serials found in the main codes/editor text area
        keys = []
        crc = self.crc_edit.text().strip()
        if crc:
            keys.append(crc)
        serials = [s.strip() for s in self.serial_edit.text().split(';') if s.strip()]
        keys.extend(serials)
        # Scan the main codes editor for embedded serials/CRCs (auto-detect)
        try:
            editor_text = self.codes_text.toPlainText()
        except Exception:
            editor_text = ''
        try:
            from __main__ import parse_serials
        except Exception:
            # parse_serials is defined in this module; fall back to local reference
            parse_serials = globals().get('parse_serials')
        if parse_serials and editor_text:
            found = parse_serials(editor_text)
            for f in found:
                if f not in keys:
                    keys.append(f)
        if not keys:
            QMessageBox.information(self, "No Serial/CRC", "No serials or CRCs detected to fetch. Enter a Serial/CRC or paste content containing them.")
            return
        all_results = []
        for key in keys:
            try:
                results = fetch_and_cache_cheats(key)
            except Exception as e:
                results = [{'source': 'error', 'error': str(e)}]
            if results:
                all_results.append((key, results))
        if not all_results:
            QMessageBox.information(self, "No Cheats Found", "No cheats found online for the given Serial/CRC.")
            return
        # Show results in a dialog
        msg = ""
        for key, results in all_results:
            msg += f"<b>{key}</b><br>"
            for entry in results:
                if 'error' in entry:
                    msg += f"<i>Error: {entry['error']}</i><br>"
                elif entry.get('source') == 'gamehacking.org':
                    data = entry.get('data')
                    if data and isinstance(data, dict):
                        cheats = data.get('codes') or data.get('results') or []
                        if cheats:
                            for cheat in cheats:
                                desc = cheat.get('name') or cheat.get('desc') or ''
                                code = cheat.get('code') or ''
                                msg += f"<b>{desc}</b><br><pre>{code}</pre>"
                        else:
                            msg += f"<i>No codes found on GameHacking.org.</i><br>"
                    else:
                        msg += f"<i>No data from GameHacking.org.</i><br>"
                elif entry.get('source') == 'psxdatacenter':
                    html = entry.get('html', '')
                    # Try to extract cheat table or relevant chunk
                    snippet = html[:2000] + ('...' if len(html) > 2000 else '')
                    msg += f"<b>PSXDatacenter:</b><br><pre>{snippet}</pre>"
                else:
                    msg += f"<pre>{entry}</pre>"
            msg += "<hr>"
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Online Cheats")
        dlg.setTextFormat(Qt.RichText)
        dlg.setText(msg)
        dlg.setStandardButtons(QMessageBox.Ok)
        dlg.exec()

    def _show_fetch_results(self, results):
        """Present a selectable list of fetched cheats and allow importing codes into the editor.
        `results` should be a list of dicts: {source,title,codes,raw_html,link}
        """
        if not results:
            QMessageBox.information(self, "No Results", "No fetched cheat entries to display.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Fetched Cheats")
        vbox = QVBoxLayout(dlg)

        listw = QListWidget()
        listw.setSelectionMode(QAbstractItemView.ExtendedSelection)

        # Populate list
        for idx, e in enumerate(results):
            title = e.get('title') or e.get('source') or f"Entry {idx+1}"
            codes = e.get('codes') or []
            if not codes and isinstance(e.get('data'), dict):
                codes = e['data'].get('codes') or []
            count = len(codes) if isinstance(codes, (list, tuple)) else (1 if codes else 0)
            item = QListWidgetItem(f"[{e.get('source')}] {title} ({count} codes)")
            item.setData(Qt.UserRole, e)
            listw.addItem(item)

        vbox.addWidget(listw)

        # Layout: left = per-entry editable codes (when single selected), right = aggregated preview
        hmid = QWidget()
        hmid_h = QHBoxLayout(hmid)
        hmid_h.setContentsMargins(0, 0, 0, 0)

        codes_col = QVBoxLayout()
        codes_lbl = QLabel('Codes (editable):')
        codes_list = QListWidget()
        codes_list.setSelectionMode(QAbstractItemView.SingleSelection)
        codes_list.setEditTriggers(QListWidget.DoubleClicked | QListWidget.EditKeyPressed)
        codes_col.addWidget(codes_lbl)
        codes_col.addWidget(codes_list)

        preview_col = QVBoxLayout()
        preview_lbl = QLabel('Preview (editable):')
        preview = QTextEdit()
        preview.setAcceptRichText(False)
        preview.setPlaceholderText(
            'Select one or more entries to aggregate their codes here. You can edit before importing.'
        )
        preview_col.addWidget(preview_lbl)
        preview_col.addWidget(preview)

        left_w = QWidget()
        left_w.setLayout(codes_col)
        right_w = QWidget()
        right_w.setLayout(preview_col)
        hmid_h.addWidget(left_w, 1)
        hmid_h.addWidget(right_w, 2)
        vbox.addWidget(hmid)

        # Options: Replace vs Append
        opt_row = QWidget()
        opt_h = QHBoxLayout(opt_row)
        opt_h.setContentsMargins(0, 0, 0, 0)
        rb_append = QRadioButton('Append to editor')
        rb_replace = QRadioButton('Replace editor')

        # Load stored preference for append/replace
        settings = QSettings('PCSX2-Manager', 'PatchTextureManager')
        pref = settings.value('fetch_dialog/mode', 'append')
        if pref == 'replace':
            rb_replace.setChecked(True)
        else:
            rb_append.setChecked(True)

        opt_h.addWidget(rb_append)
        opt_h.addWidget(rb_replace)
        opt_h.addStretch(1)
        vbox.addWidget(opt_row)

        # Buttons
        btn_row = QWidget()
        btn_h = QHBoxLayout(btn_row)
        btn_h.setContentsMargins(0, 0, 0, 0)
        btn_aggregate = QPushButton("Aggregate Selected")
        btn_import = QPushButton("Import Preview")
        btn_close = QPushButton("Close")
        btn_h.addWidget(btn_aggregate)
        btn_h.addWidget(btn_import)
        btn_h.addWidget(btn_close)
        btn_h.addStretch(1)
        vbox.addWidget(btn_row)

        # Helper to extract code lines from an entry
        def _extract_codes_from_entry(e) -> List[str]:
            codes = e.get('codes')
            if codes and isinstance(codes, (list, tuple)):
                return [str(x).strip() for x in codes if str(x).strip()]
            for key in ('code', 'raw', 'text'):
                v = e.get(key)
                if v and isinstance(v, str):
                    return [ln for ln in v.splitlines() if ln.strip()]
            data = e.get('data') or {}
            if isinstance(data, dict):
                c = data.get('codes') or data.get('results')
                if c and isinstance(c, (list, tuple)):
                    return [str(x).strip() for x in c if str(x).strip()]
                if c and isinstance(c, str):
                    return [ln for ln in c.splitlines() if ln.strip()]
            return []

        def do_aggregate():
            items = listw.selectedItems()
            if not items:
                QMessageBox.information(dlg, 'No selection', 'Select one or more entries to aggregate.')
                return
            agg_lines = []
            for it in items:
                e = it.data(Qt.UserRole)
                for ln in _extract_codes_from_entry(e):
                    agg_lines.append(ln)
            preview.setPlainText('\n'.join(agg_lines))

        def _populate_codes_list_for_item(it: QListWidgetItem):
            codes_list.clear()
            if not it:
                return
            e = it.data(Qt.UserRole)
            codes = _extract_codes_from_entry(e)
            for ln in codes:
                item = QListWidgetItem(ln)
                item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                codes_list.addItem(item)

        def _codes_item_changed(changed_item: QListWidgetItem):
            lines = [codes_list.item(i).text() for i in range(codes_list.count())]
            preview.setPlainText('\n'.join(lines))

        def do_import_preview():
            text = preview.toPlainText().strip()
            if not text:
                QMessageBox.information(dlg, 'Empty preview', 'Nothing to import.')
                return
            try:
                mode_val = 'replace' if rb_replace.isChecked() else 'append'
                settings.setValue('fetch_dialog/mode', mode_val)
            except Exception:
                pass

            if rb_replace.isChecked():
                self.codes_text.setPlainText(text)
            else:
                cur = self.codes_text.toPlainText().rstrip()
                if cur:
                    cur = cur + '\n\n' + text
                else:
                    cur = text
                self.codes_text.setPlainText(cur)
            dlg.accept()

        # Connections
        btn_aggregate.clicked.connect(do_aggregate)
        btn_import.clicked.connect(do_import_preview)
        btn_close.clicked.connect(dlg.reject)
        listw.itemSelectionChanged.connect(
            lambda: (
                _populate_codes_list_for_item(listw.currentItem())
                if len(listw.selectedItems()) == 1
                else do_aggregate()
            )
        )
        codes_list.itemChanged.connect(_codes_item_changed)

        dlg.setLayout(vbox)
        dlg.resize(720, 520)
        dlg.exec()
    # Drag & drop events

    # Drag & drop events
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            low = path.lower()
            if low.endswith('.pnach'):
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        text = f.read()
                    self.codes_text.setPlainText(text)
                    # Prefer CRC from filename if present
                    m = re.search(r"([0-9A-Fa-f]{8})", os.path.basename(path))
                    prefer_crc = m.group(1) if m else None
                    self._autofill_from_text(text, prefer_filename_crc=prefer_crc)
                except Exception as ex:
                    QMessageBox.warning(self, 'Drop error', str(ex))
            elif low.endswith(('.zip',)):
                # forward to textures tab
                self.parent.textures_tab.import_zip_path(path)
            elif os.path.isdir(path):
                self.parent.textures_tab.import_folder_path(path)
            elif low.endswith(('.txt', '.ini', '.cb', '.cbc', '.rtxt', '.bin')):
                # RAW-ish or converter source
                try:
                    with open(path, 'r', encoding='utf-8', errors='replace') as f:
                        text = f.read()
                    self.codes_text.setPlainText(text)
                    m = re.search(r"([0-9A-Fa-f]{8})", os.path.basename(path))
                    prefer_crc = m.group(1) if m else None
                    self._autofill_from_text(text, prefer_filename_crc=prefer_crc)
                except Exception as ex:
                    QMessageBox.warning(self, 'Drop error', str(ex))

    def _row(self, *widgets):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for wd in widgets:
            h.addWidget(wd)
        h.addStretch(1)
        return w

    def load_paths(self, paths: dict):
        self.cheats_dir.setText(paths.get("cheats", ""))
        self.textures_dir.setText(paths.get("textures", ""))

    def _pick_dir(self, line: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Select folder", line.text() or os.path.expanduser("~"))
        if d: line.setText(d)

    def _open_pnach_file(self):
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        path, _ = QFileDialog.getOpenFileName(self, "Open PNACH", os.path.expanduser("~"), "PNACH files (*.pnach);;All files (*.*)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            self.codes_text.setPlainText(text)
            # prefer CRC from filename if present
            fname = os.path.basename(path)
            m = re.search(r"([0-9A-Fa-f]{8})", fname)
            prefer_crc = m.group(1) if m else None
            self._autofill_from_text(text, prefer_filename_crc=prefer_crc)
        except Exception as e:
            QMessageBox.warning(self, "Open error", f"Failed to open: {e}")

    def _open_codes_file(self):
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        path, _ = QFileDialog.getOpenFileName(self, "Open codes file", os.path.expanduser("~"), "All files (*.*)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            self.codes_text.setPlainText(text)
            # Try to infer CRC from filename if it looks like XXXXXXXX.pnach or contains 8-hex
            fname = os.path.basename(path)
            m = re.search(r"([0-9A-Fa-f]{8})", fname)
            prefer_crc = m.group(1) if m else None
            self._autofill_from_text(text, prefer_filename_crc=prefer_crc)
        except Exception as e:
            QMessageBox.warning(self, "Open error", f"Failed to open: {e}")

    # --- Code Conversion ---
    # Omniconvert integration removed - placeholder was non-functional
    # Users can paste RAW codes directly or use the built-in parser

    def _basic_nonraw_to_raw(self, text: str) -> List[Tuple[str,str]]:
        """Very light parser: if lines look like XXXXXXXX YYYYYYYY or XXXXXXXX=YYYYYYYY, treat as RAW."""
        return parse_raw_8x8(text)

    # --- Title Resolver (load mapping) ---
    def _load_mapping(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load mapping (CSV/JSON)", os.path.expanduser("~"), "CSV/JSON (*.csv *.json);")
        if not path: return
        try:
            mapping: Dict[str,str] = {}
            if path.lower().endswith('.json'):
                with open(path, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
                for k, v in obj.items(): mapping[str(k).upper()] = str(v)
            else:
                # CSV: key,title
                import csv
                with open(path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        k = (row.get('key') or row.get('id') or row.get('crc') or row.get('serial') or '').upper()
                        t = row.get('title') or row.get('name') or ''
                        if k and t: mapping[k] = t
            # Expand mapping with normalized serials
            expanded = {}
            for k, v in mapping.items():
                expanded[k.upper()] = v
                if SERIAL_RE.search(k):
                    expanded[norm_serial_key(k)] = v
            self.mapping = expanded
            self.map_path.setText(path)
            QMessageBox.information(self, "Loaded", f"Loaded {len(mapping)} mappings.")
        except Exception as e:
            QMessageBox.critical(self, "Mapping error", str(e))

    # --- Unified auto-fill logic ---
    def _autofill_from_text(self, text: str, prefer_filename_crc: Optional[str] = None):
        """
        Best-effort extraction:
        - PNACH format: try parse_pnach_text()
        - RAW-ish text: parse_serials() + CRC_IN_TEXT
        - Fallbacks: filename CRC, emuLog scan
        - Auto-fill Title from local mapping and/or bundled lists if checkbox is on
        """
        # Always clear previous values. When loading a new codes or PNACH file,
        # any previously displayed CRC, serials, title or source labels should be reset.
        self.serial_edit.clear()
        self.crc_edit.clear()
        self.title_edit.clear()
        # Note: the source_label may contain multiple sources separated by " | ". Clear it fully.
        self.source_label.setText("")
        # Try PNACH first
        pd = parse_pnach_text(text)
        found_crc = pd.crc
        found_serials = pd.serials[:]
        found_title = pd.title

        # If nothing, try RAW-ish
        if not (found_crc or found_serials or found_title):
            found_serials = parse_serials(text)
            m = CRC_IN_TEXT.search(text)
            if m:
                found_crc = normalize_crc(m.group(1))

        # Filename CRC preferred if provided
        if prefer_filename_crc and not found_crc:
            fn_crc = normalize_crc(prefer_filename_crc)
            if fn_crc:
                found_crc = fn_crc

        # If still no CRC, ask logs
        if not found_crc:
            suggested = self.parent.textures_tab._suggest_crc_from_logs()
            if suggested:
                found_crc = suggested

        # Push to UI: fill serials and CRC if found
        if found_serials:
            self.serial_edit.setText('; '.join(sorted(set(found_serials))))
        if found_crc:
            self.crc_edit.setText(found_crc)

        # Determine the title source. Prefer the title embedded in the PNACH file (gametitle=)
        # over mapping or offline lists. Keep track of which source(s) provided the title.
        title = None
        source_tags = []
        if found_title:
            title = found_title.strip()
            source_tags.append("Title: PNACH")
        # If no title from PNACH, try the local mapping (CSV/JSON)
        if not title:
            mapping = getattr(self, 'mapping', {}) or {}
            keys_to_try = []
            if found_crc:
                keys_to_try.append(found_crc)
            keys_to_try.extend(found_serials or [])
            for k in keys_to_try:
                kU = k.upper().strip()
                if kU in mapping:
                    title = mapping[kU]
                    source_tags.append("Title: mapping")
                    break
                kN = norm_serial_key(kU)
                if kN in mapping:
                    title = mapping[kN]
                    source_tags.append("Title: mapping")
                    break
        # If still no title and user wants bundled lists, spawn a worker to resolve offline
        if not title and (self.chk_offline_lists.isChecked()) and (found_crc or found_serials):
            keys_to_try = []
            if found_crc:
                keys_to_try.append(found_crc)
            keys_to_try.extend(found_serials or [])
            def on_done(out):
                picked = None
                for kk in keys_to_try:
                    if kk.upper() in out:
                        picked = out[kk.upper()]
                        break
                if picked:
                    # Only set the title if it hasn't been set by PNACH or mapping
                    if not self.title_edit.text().strip():
                        self.title_edit.setText(picked)
                        self.source_label.setText("Title: offline lists")
            worker = ResolveWorker(keys_to_try, getattr(self, 'mapping', {}) or {}, use_bundled_lists=True, try_online=False)
            worker.resolved.connect(on_done)
            self._start_worker(worker)
        else:
            # If a title was found from PNACH or mapping, update the UI accordingly
            if title:
                self.title_edit.setText(title)
                if source_tags:
                    self.source_label.setText(" | ".join(source_tags))

    def _resolve_title_clicked(self):
        keys: List[str] = []
        crc = normalize_crc(self.crc_edit.text())
        if crc: keys.append(crc)
        for s in [s.strip() for s in self.serial_edit.text().split(';') if s.strip()]:
            keys.append(s.upper())
        if not keys:
            QMessageBox.information(self, "No keys", "Enter a CRC or Serial to resolve.")
            return
        self.progress.setMaximum(len(keys))
        self.progress.setValue(0)
        # Always try online as fallback
        worker = ResolveWorker(
            keys,
            self.mapping,
            use_bundled_lists=self.chk_offline_lists.isChecked(),
            try_online=self.chk_online.isChecked()
        )
        worker.progressed.connect(lambda i,t: self.progress.setValue(i))
        def done(out: Dict[str,str]):
            # Prefer CRC title, then serial
            title = None
            found_crc = None
            if crc and crc in out:
                title = out[crc]
            if not title:
                for s in keys:
                    if s in out:
                        title = out[s]
                        break
            # Try to get CRC from results
            if crc and (crc+'_CRC') in out:
                found_crc = out[crc+'_CRC']
            if not found_crc:
                for s in keys:
                    if (s+'_CRC') in out:
                        found_crc = out[s+'_CRC']
                        break
            if title:
                self.title_edit.setText(title)
                self.source_label.setText("Title: online" if self.chk_online.isChecked() else "Title: mapping/offline")
            if found_crc:
                self.crc_edit.setText(found_crc)
            if not title and not found_crc:
                self.source_label.setText("")
                QMessageBox.information(self, "No match", "No title or CRC found in mapping or online.\n\nPossible reasons:\n- Serial/CRC not present in PSXDataCenter or mapping.\n- Serial format/region mismatch.\n- Demo, prototype, or rare disc.\n- Try another region or check for typos.")
        worker.resolved.connect(done)
        worker.failed.connect(lambda msg: QMessageBox.critical(self, "Resolve error", msg))
        self._start_worker(worker)

    def _generate_preview(self):
        title = self.title_edit.text().strip() or None
        serials = [s.strip() for s in self.serial_edit.text().split(";") if s.strip()]
        crc = normalize_crc(self.crc_edit.text())
        content = self.codes_text.toPlainText()

        # Auto-detect format based on content
        if 'patch=' in content.lower() or content.strip().startswith('//'):
            # Looks like PNACH format
            pd = parse_pnach_text(content)
            if title: pd.title = title
            if serials: pd.serials = serials
            if crc: pd.crc = crc
            if not pd.raw_pairs:
                QMessageBox.information(self, "No patch lines", "The .pnach contains no patch lines in 'patch=1,EE,XXXXXXXX,extended,YYYYYYYY' format.")
                return
        else:
            # Try to parse as RAW pairs
            pairs = parse_raw_8x8(content)
            if not pairs:
                bad = self._collect_invalid_raw_lines(content)
                hint = "\n".join(bad) if bad else "No candidate lines detected."
                QMessageBox.information(
                    self, "No codes",
                    "No valid RAW pairs found.\nExpected lines like: XXXXXXXX YYYYYYYY (hex)\n\nSome problematic lines:\n" + hint
                )
                return
            pd = PnachData(crc=crc, serials=serials, title=title, raw_pairs=pairs)
        self.preview.setPlainText(build_pnach(pd))

    def _save_to_cheats(self):
        cheats_dir = self.cheats_dir.text().strip()
        if not cheats_dir or not os.path.isdir(cheats_dir):
            QMessageBox.warning(self, "Missing cheats folder", "Please set a valid PCSX2 cheats folder path.")
            return
        preview = self.preview.toPlainText().strip()
        if not preview:
            QMessageBox.information(self, "Nothing to save", "Generate a preview first.")
            return
        crc = normalize_crc(self.crc_edit.text())
        serials = [s.strip() for s in self.serial_edit.text().split(";") if s.strip()]

        # If CRC is missing but serial is present, try to resolve CRC (local + optional lightweight online best-effort)
        if not crc and serials:
            serial_upper = serials[0].upper()
            mapping = self.mapping if hasattr(self, 'mapping') else {}
            crc_from_map = None
            for k in mapping:
                if k == serial_upper and normalize_crc(mapping[k]):
                    crc_from_map = normalize_crc(mapping[k])
                    break
                if mapping[k].upper() == serial_upper and normalize_crc(k):
                    crc_from_map = normalize_crc(k)
                    break
            # Optional: minimal online scrape if available (kept as fallback)
            if not crc_from_map and requests is not None:
                try:
                    serial_variants = [serial_upper, serial_upper.replace('-', ''), serial_upper.replace('_', ''), serial_upper.replace(' ', '')]
                    found_crc = None
                    url_templates = [
                        'https://psxdatacenter.com/ps2/ntscu2.html',
                        'https://psxdatacenter.com/ps2/pal2.html',
                        'https://psxdatacenter.com/ps2/ntscj2.html',
                    ]
                    for url in url_templates:
                        try:
                            resp = requests.get(url, timeout=10)
                            if resp.status_code == 200:
                                html = resp.text.upper()
                                for variant in serial_variants:
                                    idx = html.find(variant.upper())
                                    if idx != -1:
                                        window = html[max(0, idx-250):idx+250]
                                        mcrc = CRC_IN_TEXT.search(window)
                                        if mcrc:
                                            found_crc = normalize_crc(mcrc.group(1))
                                            break
                                if found_crc:
                                    break
                        except Exception:
                            continue
                    crc_from_map = found_crc
                except Exception:
                    crc_from_map = None

            if crc_from_map:
                crc = crc_from_map
                self.crc_edit.setText(crc)
            else:
                QMessageBox.warning(self, "CRC not found", "Could not resolve CRC for the given serial. Please provide a valid CRC.")
                return

        if not crc:
            QMessageBox.warning(self, "Need CRC", "A valid CRC is required to save the patch. Please provide or resolve the CRC.")
            return

        fname = f"{crc}.pnach"
        outpath = os.path.join(cheats_dir, fname)
        try:
            with open(outpath, "w", encoding="utf-8") as f: f.write(preview)
            QMessageBox.information(self, "Saved", f"Wrote:\n{outpath}")
            self.refresh_list()
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save the cheat file.\n\nError: {str(e)}\n\nPlease check:\n- The cheats folder path is correct\n- You have write permissions\n- PCSX2 is not running")

    def refresh_list(self):
        self.list.clear()
        cheats_dir = self.cheats_dir.text().strip()
        if cheats_dir and os.path.isdir(cheats_dir):
            for name in sorted(os.listdir(cheats_dir)):
                if name.lower().endswith(".pnach"):
                    self.list.addItem(QListWidgetItem(name))
        # Apply current filter if any
        self._filter_existing_cheats(self.search_box.text())

    def _filter_existing_cheats(self, text: str):
        """Filter the installed cheats list by search text."""
        search_text = text.lower().strip()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not search_text:
                item.setHidden(False)
            else:
                item.setHidden(search_text not in item.text().lower())

    # QoL: auto-title when user types CRC/Serial
    def _maybe_autotitle(self):
        """Debounced trigger for auto-title lookup. Restarts timer on each keystroke."""
        self._autotitle_timer.start()
    
    def _do_autotitle(self):
        """Actual auto-title lookup logic, called after debounce delay."""
        mapping = getattr(self, 'mapping', {}) or {}
        keys = []
        crc = normalize_crc(self.crc_edit.text())
        if crc: keys.append(crc)
        for s in [s.strip() for s in self.serial_edit.text().split(';') if s.strip()]:
            keys.append(s.upper())
        for k in keys:
            if k in mapping:
                self.title_edit.setText(mapping[k])
                self.source_label.setText("Title: mapping")
                return
            kN = norm_serial_key(k)
            if kN in mapping:
                self.title_edit.setText(mapping[kN])
                self.source_label.setText("Title: mapping")
                return
        # Optionally try bundled lists if box checked
        if keys and self.chk_offline_lists.isChecked():
            def on_done(out):
                for k in keys:
                    if k.upper() in out:
                        self.title_edit.setText(out[k.upper()])
                        self.source_label.setText("Title: offline lists")
                        return
            worker = ResolveWorker(keys, mapping, use_bundled_lists=True, try_online=False)
            worker.resolved.connect(on_done)
            self._start_worker(worker)
    
    # ---- Cheat Browser Methods ----
    
    def _populate_game_list(self):
        """Populate the game list widget with all games (or filtered)."""
        self.game_list_widget.clear()
        
        search_text = self._current_search.lower().strip()
        letter_filter = self._current_letter_filter
        
        for game in self.cheats_database.get('games', []):
            title = game.get('title', '').strip()
            
            # Apply letter filter
            if letter_filter and letter_filter != "ALL":
                first_char = title[0].upper() if title else ''
                if letter_filter.startswith('0'):  # "0-9"
                    if not first_char.isdigit():
                        continue
                elif first_char != letter_filter:
                    continue
            
            # Apply search filter
            if search_text and search_text not in title.lower():
                continue
            
            # Add to list
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, game)
            self.game_list_widget.addItem(item)
        
        # Show result count
        count = self.game_list_widget.count()
        if search_text or letter_filter:
            search_info = f"Found {count} game(s)"
            if search_text:
                search_info += f" matching '{self._current_search}'"
            if letter_filter and letter_filter != "ALL":
                if search_text:
                    search_info += f" starting with '{letter_filter}'"
                else:
                    search_info += f" starting with '{letter_filter}'"
            self.game_list_widget.setToolTip(search_info)
    
    def _on_game_search_changed(self, text):
        """Handle search text changes."""
        self._current_search = text
        self._populate_game_list()
    
    def _on_letter_filter_clicked(self, letter):
        """Handle letter filter button clicks."""
        # Toggle current filter or set new one
        if self._current_letter_filter == letter:
            self._current_letter_filter = None
            self.letter_buttons[letter].setChecked(False)
        else:
            # Uncheck all other buttons
            for btn in self.letter_buttons.values():
                btn.setChecked(False)
            # Check the clicked button
            self.letter_buttons[letter].setChecked(True)
            self._current_letter_filter = letter
        
        self._populate_game_list()
    
    def _on_game_list_selected(self):
        """Handle game selection from the list."""
        self.region_selector.clear()
        self.region_selector.addItem("-- Select region --", None)
        self.cheats_tree.clear()
        self.region_info_label.setText("")
        self.btn_select_all.setEnabled(False)
        self.btn_deselect_all.setEnabled(False)
        self.btn_install_selected.setEnabled(False)
        
        selected_items = self.game_list_widget.selectedItems()
        if not selected_items:
            return
        
        game = selected_items[0].data(Qt.UserRole)
        if game and 'regions' in game:
            for region_name in sorted(game['regions'].keys()):
                self.region_selector.addItem(region_name, game['regions'][region_name])
    
    def _on_region_selected(self, index):
        """Handle region selection in the browser."""
        self.cheats_tree.clear()
        self.region_info_label.setText("")
        self.btn_select_all.setEnabled(False)
        self.btn_deselect_all.setEnabled(False)
        self.btn_install_selected.setEnabled(False)
        
        region_data = self.region_selector.currentData()
        if not region_data:
            return
        
        # Display serial and CRC info
        serial = region_data.get('serial', 'N/A')
        crc = region_data.get('crc', 'N/A')
        self.region_info_label.setText(f"Serial: {serial} | CRC: {crc}")
        
        # Populate cheats tree
        cheats = region_data.get('cheats', [])
        for cheat in cheats:
            item = QTreeWidgetItem([cheat['name'], cheat['description']])
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, cheat)  # Store cheat data
            self.cheats_tree.addTopLevelItem(item)
        
        if cheats:
            self.btn_select_all.setEnabled(True)
            self.btn_deselect_all.setEnabled(True)
            self.btn_install_selected.setEnabled(True)
    
    def _select_all_cheats(self):
        """Select all cheats in the tree."""
        for i in range(self.cheats_tree.topLevelItemCount()):
            item = self.cheats_tree.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)
    
    def _deselect_all_cheats(self):
        """Deselect all cheats in the tree."""
        for i in range(self.cheats_tree.topLevelItemCount()):
            item = self.cheats_tree.topLevelItem(i)
            item.setCheckState(0, Qt.Unchecked)
    
    def _install_selected_cheats(self):
        """Install selected cheats to PCSX2."""
        # Get selected cheats
        selected_cheats = []
        for i in range(self.cheats_tree.topLevelItemCount()):
            item = self.cheats_tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                cheat_data = item.data(0, Qt.UserRole)
                if cheat_data:
                    selected_cheats.append(cheat_data)
        
        if not selected_cheats:
            QMessageBox.information(self, "No Cheats Selected", "Please select at least one cheat to install.")
            return
        
        # Get region data for serial and CRC
        region_data = self.region_selector.currentData()
        if not region_data:
            QMessageBox.warning(self, "No Region Selected", "Please select a region first.")
            return
        
        serial = region_data.get('serial', '')
        crc = region_data.get('crc', '')
        # Get game from the selected game in game_list_widget
        selected_game_items = self.game_list_widget.selectedItems()
        game = selected_game_items[0].data(Qt.UserRole) if selected_game_items else None
        title = game.get('title', 'Unknown Game') if game else 'Unknown Game'
        
        # Check if cheats folder is set
        cheats_dir = self.cheats_dir.text().strip()
        if not cheats_dir or not os.path.isdir(cheats_dir):
            QMessageBox.warning(self, "Missing Cheats Folder", 
                              "Please set a valid PCSX2 cheats folder path in the settings.")
            return
        
        if not crc:
            QMessageBox.warning(self, "Missing CRC", "Cannot install cheats without a CRC value.")
            return

        filename = f"{crc.upper()}.pnach"
        existing_filepath = os.path.join(cheats_dir, filename)
        if os.path.isfile(existing_filepath):
            reply = QMessageBox.question(
                self, "File Exists",
                f"A cheat file for this game already exists:\n{filename}\n\nDo you want to overwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        try:
            filepath = write_cheats_pnach(title, serial, crc, selected_cheats, cheats_dir)

            # Update mapping
            if serial and title:
                self.mapping[serial.upper()] = title
                self.mapping[crc.upper()] = title
                self.save_mapping()

            # Refresh list
            self.refresh_list()

            # Show success message
            QMessageBox.information(
                self, "Cheats Installed Successfully",
                f"Installed {len(selected_cheats)} cheat(s) to:\n{filepath}\n\n"
                f"The cheats are now available in PCSX2!"
            )

        except Exception as e:
            QMessageBox.critical(self, "Installation Failed", f"Failed to install cheats:\n{str(e)}")

    def _collect_invalid_raw_lines(self, text: str, limit: int = 6) -> List[str]:
        bad = []
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if not s or s.startswith(("#", "//", ";")):
                continue
            parts = [p for p in s.replace(",", " ").replace("=", " ").split() if p]
            if len(parts) < 2 or not HEX8.match(parts[0]) or not re.fullmatch(r"[0-9A-Fa-f]{1,8}", parts[1]):
                bad.append(f"L{i}: {line[:120]}")
                if len(bad) >= limit:
                    break
        return bad


class TexturesTab(QWidget):
    class PackInstallWorker(QThread):
        """Background worker that wraps the headless installer so tests and the UI
        can run installs in a QThread and receive progress signals. Exposed as
        TexturesTab.PackInstallWorker for tests.
        """
        progressed = Signal(int, int, str)
        file_progressed = Signal(int, int, str, int, int)
        finished = Signal(int, list)
        failed = Signal(str)

        def __init__(self, items, base, target_hint: str = '', installer=None, parent=None):
            super().__init__(parent)
            self.items = items
            self.base = base
            self.target_hint = target_hint
            # installer is an optional callable to perform installs; if None, run will import the module
            self.installer = installer
            self._cancel = False

        def cancel(self):
            self._cancel = True

        def run(self):
            # Use provided installer callable when available to avoid importing inside worker thread
            perform_pack_installs = self.installer
            if perform_pack_installs is None:
                try:
                    from textures_install import perform_pack_installs
                except Exception as e:
                    try:
                        self.failed.emit(str(e))
                    except Exception:
                        pass
                    return

            def progress_cb(c, t, d):
                try:
                    self.progressed.emit(c, t, d)
                except Exception:
                    pass

            def file_progress_cb(idx, total_items, display, written, total_bytes):
                try:
                    self.file_progressed.emit(idx, total_items, display, written, total_bytes)
                except Exception:
                    pass

            try:
                installed, failures = perform_pack_installs(
                    self.items,
                    self.base,
                    target_hint=self.target_hint,
                    progress_cb=progress_cb,
                    cancel_cb=lambda: self._cancel,
                    file_progress_cb=file_progress_cb,
                )
                try:
                    self.finished.emit(installed, failures)
                except Exception:
                    pass
            except Exception as e:
                try:
                    self.failed.emit(str(e))
                except Exception:
                    pass

        def start(self):
            # If no QApplication (tests that use this worker without GUI), run synchronously
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
            except Exception:
                app = None
            if app is None:
                try:
                    self.run()
                except Exception:
                    pass
                return
            # Ensure a strong reference so the QThread object isn't GC'd while running
            try:
                _ACTIVE_WORKERS.append(self)
                def _on_finish():
                    try:
                        _ACTIVE_WORKERS.remove(self)
                    except Exception:
                        pass
                    try:
                        self.deleteLater()
                    except Exception:
                        pass
                self.finished.connect(_on_finish)
            except Exception:
                pass
            super().start()

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", os.path.expanduser("~"))
        if folder:
            self.import_folder_path(folder)

    def _import_zip(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select ZIP file", os.path.expanduser("~"), "ZIP Files (*.zip)")
        if file:
            self.import_zip_path(file)
    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self.parent.paths_changed.connect(self.load_paths)
        self._shutting_down = False  # Flag to prevent new workers during shutdown
        # Thumbnail cache used for installed pack icons
        self._thumb_cache = os.path.join(os.path.expanduser("~"), ".pcsx2_manager_thumbs")
        try:
            os.makedirs(self._thumb_cache, exist_ok=True)
        except Exception:
            pass
        
        # Debounce timer for search filter to improve performance
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)  # 150ms delay
        self._filter_timer.timeout.connect(self._do_filter)
        self._pending_filter_text = ""
        
        self._build_ui()
        
        # Defer initial scan until after UI is fully initialized
        # This prevents threading issues during startup
        QTimer.singleShot(100, self._deferred_scan)

    def _preview_context_menu(self, pos):
        # Context menu for preview cover in TexturesTab
        menu = QMenu(self)
        act_refresh = menu.addAction("Refresh Cover")
        act = menu.exec_(self.preview_cover.mapToGlobal(pos))
        if act == act_refresh:
            # Prefer the preview serial, fall back to the selected item's cached serial
            serial = self.preview_serial.text().strip()
            if not serial:
                try:
                    sel = self.packs_list.selectedItems()
                    if sel:
                        serial = (sel[0].data(0, Qt.UserRole + 2) or '').strip()
                except Exception:
                    serial = ''
            serial_key = norm_serial_key(serial)
            if not serial_key:
                return
            cache_name = os.path.join(self._thumb_cache, f"cover_{serial_key}.jpg")
            try:
                if os.path.isfile(cache_name):
                    os.remove(cache_name)
            except Exception:
                pass
            # Build candidate variants to probe (normalized, original, no-separators, lower)
            raw = (serial or '').strip()
            sk = norm_serial_key(raw)
            variants = []
            if sk:
                variants.append(sk.upper())
            if raw:
                variants.append(raw.upper())
            variants.append(raw.replace('-', '').replace('_', '').replace(' ', '').upper())
            variants.append((raw.replace('-', '').replace('_', '').replace(' ', '')).lower())
            variants.append(sk.lower())
            seen = set()
            uniq = []
            for v in variants:
                if not v: continue
                if v in seen: continue
                seen.add(v)
                uniq.append(v)
            candidates = [f"https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/default/{v}.jpg" for v in uniq]
            # Prefer previously successful candidate if recorded in index.json
            try:
                idx_file = os.path.join(self._thumb_cache, 'index.json')
                if os.path.isfile(idx_file):
                    with open(idx_file, 'r', encoding='utf-8') as inf:
                        idx = json.load(inf)
                    for v in uniq:
                        if v in idx:
                            known = idx[v]
                            if known in candidates:
                                candidates.remove(known)
                                candidates.insert(0, known)
                                break
            except Exception:
                pass
            self.preview_loading.setVisible(True)

            def _on_fetched(path: str):
                try:
                    pm = QPixmap(path)
                    if pm and not pm.isNull():
                        _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                except Exception:
                    self.preview_cover.clear()
                finally:
                    self.preview_loading.setVisible(False)

            def _on_failed():
                try:
                    # try local cache first
                    if os.path.isfile(cache_name):
                        pm = QPixmap(cache_name)
                        if pm and not pm.isNull():
                            _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                            return
                    # fallback to bundled logo.png if available
                    bundled = os.path.join(os.path.dirname(__file__), 'logo.png')
                    if os.path.isfile(bundled):
                        pm = QPixmap(bundled)
                        if pm and not pm.isNull():
                            _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                            return
                    # Show placeholder
                    placeholder = create_cover_placeholder(serial)
                    if placeholder and not placeholder.isNull():
                        _set_label_pixmap_exact(self.preview_cover, placeholder, max_dim=420)
                except Exception:
                    try:
                        self.preview_cover.clear()
                    except Exception:
                        pass
                finally:
                    self.preview_loading.setVisible(False)

            worker = CoverFetchWorker(candidates, cache_name, parent=self)
            worker.fetched.connect(_on_fetched)
            worker.fetch_failed.connect(_on_failed)
            self._start_worker(worker)

    def _build_ui(self):
        # Create a scroll area for the entire tab content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        
        # Create a container widget for all content
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG)
        layout.setSpacing(theme.SPACING_MD)

        group = QGroupBox("Texture Pack Import")
        fl = QFormLayout(group)
        self.textures_dir = QLineEdit()
        self.btn_browse_textures = QPushButton("Browse…")
        self.btn_browse_textures.clicked.connect(lambda: self._pick_dir(self.textures_dir))

        self.target_folder_name = QLineEdit()
        self.target_folder_name.setPlaceholderText("Game ID (e.g., SLUS-12345) or custom folder name")
        self.btn_zip = QPushButton("Import ZIP…")
        self.btn_zip.clicked.connect(self._import_zip)
        self.btn_folder = QPushButton("Import Folder…")
        self.btn_folder.clicked.connect(self._import_folder)

        self.preload_chk = QCheckBox("Suggest enabling texture replacement in PCSX2 settings (manual)")

        fl.addRow("textures:", self._row(self.textures_dir, self.btn_browse_textures))
        fl.addRow("Target folder name:", self.target_folder_name)
        fl.addRow(self._row(self.btn_zip, self.btn_folder))
        fl.addRow(self.preload_chk)
        layout.addWidget(group)

        info = QLabel(
            "Hint: Newer PCSX2 nightlies store texture packs under a 'textures' folder in the user directory.\n"
            "Packs are often organized in subfolders named after the game's CRC. You can paste the CRC here."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Installed packs list + actions
        packs_group = QGroupBox("Installed Packs")
        pv = QVBoxLayout(packs_group)
        # Use a QTreeWidget with three columns: Folder/Serial, Title, Staging
        self.packs_list = QTreeWidget()
        self.packs_list.setColumnCount(3)
        self.packs_list.setHeaderLabels(["Folder/Serial", "Title", "Staged"])
        # Add a search box above the list to filter by serial or title
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by serial or title...")
        self.search_edit.textChanged.connect(self._filter_packs)
        # Allow multi-selection for mass-install operations
        self.packs_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.packs_list.itemSelectionChanged.connect(self._on_pack_selected)
        # Context menu for revealing pack paths and staging folder configuration
        self.packs_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.packs_list.customContextMenuRequested.connect(self._packs_context_menu)

        # Layout: left = search + list, right = preview/metadata
        split_row = QHBoxLayout()
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(0,0,0,0)
        left_l.addWidget(self.search_edit)
        left_l.addWidget(self.packs_list)

        # Preview panel on the right
        self.preview_cover = QLabel()
        # Do not force a fixed size; we will size the label to the pixmap exact fit
        self.preview_cover.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_cover.setFrameStyle(QLabel.Box | QLabel.Plain)
        self.preview_cover.setAlignment(Qt.AlignCenter)
        # allow right-click to refresh remote cover
        self.preview_cover.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_cover.customContextMenuRequested.connect(self._preview_context_menu)
        # Loading indicator shown while fetching remote cover
        self.preview_loading = QLabel("Loading...")
        self.preview_loading.setVisible(False)
        self.preview_loading.setAlignment(Qt.AlignCenter)
        self.preview_loading.setObjectName(theme.OBJ_OVERLAY_LABEL)
        self.preview_title = QLabel("")
        self.preview_serial = QLabel("")
        self.preview_path = QLabel("")
        self.preview_title.setWordWrap(True)
        meta_v = QVBoxLayout()
        # stack cover and loading label vertically (loading under cover so it can be shown/hidden)
        meta_v.addWidget(self.preview_cover)
        meta_v.addWidget(self.preview_loading)
        meta_v.addWidget(self.preview_title)
        meta_v.addWidget(self.preview_serial)
        meta_v.addWidget(self.preview_path)
        meta_v.addStretch(1)
        right_w = QWidget()
        right_w.setLayout(meta_v)

        split_row.addWidget(left_w, 3)
        split_row.addWidget(right_w, 2)
        pv.addLayout(split_row)

        btn_row = QWidget()
        br = QHBoxLayout(btn_row)
        br.setContentsMargins(0, 0, 0, 0)
        self.btn_open_pack = QPushButton("Open")
        self.btn_open_pack.clicked.connect(self._open_selected_pack)
        self.btn_install_pack = QPushButton("Install")
        self.btn_install_pack.clicked.connect(self._install_selected_pack)
        # Mass-install selected staged packs
        self.btn_install_selected = QPushButton("Install Selected")
        self.btn_install_selected.clicked.connect(self._install_selected_multiple)
        self.btn_remove_pack = QPushButton("Remove")
        self.btn_remove_pack.clicked.connect(self._remove_selected_pack)
        self.btn_refresh_packs = QPushButton("Refresh")
        self.btn_refresh_packs.clicked.connect(self.scan_installed_textures)
        for b in (self.btn_open_pack, self.btn_install_pack, self.btn_install_selected, self.btn_remove_pack, self.btn_refresh_packs):
            br.addWidget(b)
        br.addStretch(1)
        # Debug buttons hidden for cleaner UI (uncomment if needed for troubleshooting)
        # self.btn_resolve_all = QPushButton("Resolve All")
        # self.btn_resolve_all.clicked.connect(self._resolve_all_packs)
        # self.btn_show_matched = QPushButton("Show matched HTML")
        # self.btn_show_matched.clicked.connect(self._show_matched_for_selected)
        # br.addWidget(self.btn_resolve_all)
        # br.addWidget(self.btn_show_matched)
        pv.addWidget(btn_row)
        layout.addWidget(packs_group)

        # disable action buttons until a pack is selected
        self.btn_open_pack.setEnabled(False)
        self.btn_install_pack.setEnabled(False)
        self.btn_remove_pack.setEnabled(False)

        # Configure packs_list for better UX
        header = self.packs_list.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.packs_list.setAlternatingRowColors(True)
        self.packs_list.setSortingEnabled(True)
        self.packs_list.sortByColumn(1, Qt.AscendingOrder)
        
        # Set the container as the scroll area's widget
        scroll.setWidget(container)
        
        # Set the scroll area as the main layout for this tab
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _filter_packs(self, text: str):
        """Debounced trigger for filtering. Stores text and restarts timer."""
        self._pending_filter_text = text
        self._filter_timer.start()
    
    def _do_filter(self):
        """Actual filtering logic, called after debounce delay."""
        text = self._pending_filter_text.strip().lower()
        for i in range(self.packs_list.topLevelItemCount()):
            it = self.packs_list.topLevelItem(i)
            serial = (it.text(0) or '').lower()
            title = (it.text(1) or '').lower()
            match = (not text) or (text in serial) or (text in title)
            it.setHidden(not match)

    # ---- Worker management to prevent GC / crashes ----
    def _start_worker(self, worker: QThread):
        # Don't start new workers if shutting down
        if getattr(self, '_shutting_down', False):
            return
        # Keep a strong reference so the worker isn't GC'd mid-run
        if not hasattr(self, "_workers"):
            self._workers = []
        worker.setParent(self)
        self._workers.append(worker)
        def _cleanup():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()
        # Try to attach common signals if present
        try:
            worker.fetched.connect(_cleanup)
            worker.fetch_failed.connect(_cleanup)
        except Exception:
            try:
                worker.finished.connect(_cleanup)
            except Exception:
                pass
        worker.start()
    
    def _deferred_scan(self):
        """Perform initial texture scan after UI is fully initialized."""
        try:
            self.scan_installed_textures()
        except Exception as e:
            try:
                logger.debug(f"[TexturesTab] deferred scan failed: {e}")
            except Exception:
                pass
    
    def cleanup_workers(self):
        """Stop and cleanup all running workers."""
        if hasattr(self, "_workers"):
            for worker in list(self._workers):
                try:
                    if worker.isRunning():
                        worker.quit()
                        worker.wait(1000)  # Wait up to 1 second
                    worker.deleteLater()
                except Exception:
                    pass
            self._workers.clear()

    # Public helpers for DnD from Cheats tab
    def import_zip_path(self, path: str):
        base = self.textures_dir.text().strip()
        if not base or not os.path.isdir(base):
            QMessageBox.warning(self, "Missing textures folder", "Please set a valid PCSX2 textures folder path.")
            return

        # Create a staging imports area inside the textures folder so imports are non-destructive
        imports_root = self._imports_root(base)
        os.makedirs(imports_root, exist_ok=True)
        zipname = os.path.splitext(os.path.basename(path))[0]
        staging = os.path.join(imports_root, zipname)
        try:
            # ensure clean staging
            if os.path.exists(staging):
                shutil.rmtree(staging)
            os.makedirs(staging, exist_ok=True)
            with zipfile.ZipFile(path, 'r') as z:
                z.extractall(staging)

            # Detect top-level folders inside the staging area that represent separate packs
            tops = [os.path.join(staging, p) for p in os.listdir(staging)]
            pack_dirs = []
            for p in tops:
                if os.path.isdir(p):
                    # If a folder contains images or a 'replacements' subtree, treat it as a pack
                    rep = os.path.join(p, 'replacements')
                    if self._find_replacements_in_tree(p) or (os.path.isdir(rep) and self._find_replacements_in_tree(rep)):
                        pack_dirs.append(p)
            # If no obvious child packs, treat the whole staging folder as one pack
            if not pack_dirs:
                pack_dirs = [staging]

            # Register each detected pack in the UI without copying into the textures base
            for pd in pack_dirs:
                display_name = os.path.basename(pd)
                # try to prefer a serial-like display name
                m = SERIAL_RE.search(display_name)
                if m:
                    display_name = m.group(0).upper()
                # avoid duplicates
                exists = False
                for i in range(self.packs_list.topLevelItemCount()):
                    it = self.packs_list.topLevelItem(i)
                    if it and it.data(0, Qt.UserRole) == pd:
                        exists = True
                        break
                if exists:
                    continue
                safe_key = os.path.basename(display_name).replace(os.sep, '_')
                thumb = self._make_thumbnail(pd, safe_key)
                # resolve title similarly to import_folder_path
                title_col = ""
                try:
                    if SERIAL_RE.search(display_name) and not HEX8.match(display_name):
                        serial = display_name
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        kU = serial.upper().strip()
                        title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                        try:
                            bl = bundled_lookup_title(kU)
                            if bl:
                                title_col = bl
                                try:
                                    self.parent.cheats_tab.mapping[kU] = bl
                                    self.parent.cheats_tab.save_mapping()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    title_col = ""
                it = QTreeWidgetItem([display_name, title_col, "staged"])
                it.setData(0, Qt.UserRole, pd)
                tt = pd
                try:
                    if title_col:
                        tt = f"{pd}\n{title_col}"
                except Exception:
                    pass
                it.setToolTip(0, tt)
                # Use the thumbnail if it was successfully created
                if thumb and os.path.isfile(thumb):
                    it.setIcon(0, QIcon(thumb))
                else:
                    it.setIcon(0, QIcon())
                self.packs_list.addTopLevelItem(it)

            QMessageBox.information(self, "Imported (staged)", f"Imported ZIP into staging folder:\n{staging}\n\nPacks are available in the list and will be installed only when you click Install.")
        except Exception as e:
            QMessageBox.critical(self, "ZIP Import Failed", f"Could not import the ZIP file.\n\nError: {str(e)}\n\nPlease check:\n- The file is a valid ZIP archive\n- It's not corrupted\n- You have enough disk space")

    def _imports_root(self, base_textures_dir: str) -> str:
        """Return the configured imports/staging root. Reads a settings key if present, otherwise defaults to <base>/_imports."""
        try:
            # allow a global override via QSettings under key 'staging/imports_root'
            from PySide6.QtCore import QSettings
            qs = QSettings()
            cfg = qs.value('staging/imports_root', '')
            if cfg:
                return os.path.expanduser(cfg)
        except Exception:
            pass
        return os.path.join(base_textures_dir, '_imports')

    def _packs_context_menu(self, pos):
        sel = self.packs_list.itemAt(pos)
        menu = QMenu(self)
        act_reveal = menu.addAction('Reveal in Explorer')
        act_open_staging = menu.addAction('Open staging folder')
        act_set_staging = menu.addAction('Set staging folder...')
        act = menu.exec_(self.packs_list.mapToGlobal(pos))
        if act == act_reveal and sel:
            p = sel.data(0, Qt.UserRole)
            if p and os.path.exists(p):
                if os.name == 'nt':
                    subprocess.Popen(['explorer', os.path.normpath(p)])
                else:
                    subprocess.Popen(['xdg-open', p])
        elif act == act_open_staging:
            base = self.textures_dir.text().strip()
            if not base: return
            st = self._imports_root(base)
            if not os.path.isdir(st):
                QMessageBox.information(self, 'Staging folder', f'Staging folder does not exist:\n{st}')
                return
            if os.name == 'nt':
                subprocess.Popen(['explorer', os.path.normpath(st)])
            else:
                subprocess.Popen(['xdg-open', st])
        elif act == act_set_staging:
            # allow user to pick a folder to use as staging root
            d = QFileDialog.getExistingDirectory(self, 'Select staging folder', os.path.expanduser('~'))
            if d:
                try:
                    from PySide6.QtCore import QSettings
                    qs = QSettings()
                    qs.setValue('staging/imports_root', os.path.expanduser(d))
                    QMessageBox.information(self, 'Staging folder', f'Staging folder set to:\n{d}')
                except Exception:
                    QMessageBox.information(self, 'Staging folder', f'Staging folder selection saved to:\n{d}')

    def _install_selected_multiple(self):
        items = self.packs_list.selectedItems()
        if not items:
            return
        base = self.textures_dir.text().strip()
        if not base or not os.path.isdir(base):
            QMessageBox.warning(self, "Missing textures folder", "Please set a valid PCSX2 textures folder path.")
            return

        install_items = []
        for it in items:
            try:
                src = it.data(0, Qt.UserRole) or ''
                install_items.append((it.text(0) or '', src))
            except Exception:
                continue

        dlg = QDialog(self)
        dlg.setWindowTitle('Installing Packs')
        dlg.setModal(False)
        v = QVBoxLayout(dlg)
        overall_label = QLabel('Overall:')
        overall_bar = QProgressBar()
        overall_bar.setRange(0, 100)
        per_label = QLabel('Current:')
        per_bar = QProgressBar()
        per_bar.setRange(0, 100)
        eta_label = QLabel('ETA: --:--')
        failures_text = QTextEdit()
        failures_text.setReadOnly(True)
        failures_text.setMaximumHeight(120)
        btn_row = QWidget()
        bh = QHBoxLayout(btn_row)
        retry_btn = QPushButton('Retry Failures')
        retry_btn.setEnabled(False)
        close_btn = QPushButton('Close')
        bh.addWidget(retry_btn)
        bh.addWidget(close_btn)

        v.addWidget(overall_label)
        v.addWidget(overall_bar)
        v.addWidget(per_label)
        v.addWidget(per_bar)
        v.addWidget(eta_label)
        v.addWidget(failures_text)
        v.addWidget(btn_row)
        dlg.show()

        state = {
            'samples': deque(maxlen=6),
            'ema': None,
            'pack_totals': {},
            'current_idx': 0,
            'last_ts': None,
            'failures': [],
        }

        target_hint = self.target_folder_name.text().strip() or ''
        # Use a plain threading.Thread for the dialog installer to avoid Qt QThread / COM issues on Windows.
        import threading

        try:
            from textures_install import perform_pack_installs as _perform_pack_installs
        except Exception:
            _perform_pack_installs = None

        class _DialogWorker:
            def __init__(self, items, base, target_hint, installer):
                self.items = items
                self.base = base
                self.target_hint = target_hint
                self.installer = installer
                self._cancel = False
                self._thread = None

            def cancel(self):
                self._cancel = True

            def is_running(self):
                return self._thread is not None and self._thread.is_alive()

            def start(self, progress_cb, file_progress_cb, finished_cb, failed_cb):
                def _run():
                    try:
                        if not self.installer:
                            # import on main thread failed earlier; try import here as fallback
                            from textures_install import perform_pack_installs as _inst
                        else:
                            _inst = self.installer
                        def _cancel_cb():
                            return self._cancel

                        def _progress_cb(c, t, d):
                            # marshal UI update into Qt main thread
                            QTimer.singleShot(0, lambda: progress_cb(c, t, d))

                        def _file_progress_cb(idx, total_items, display, written, total_bytes):
                            QTimer.singleShot(0, lambda: file_progress_cb(idx, total_items, display, written, total_bytes))

                        installed, failures = _inst(self.items, self.base, target_hint=self.target_hint, progress_cb=_progress_cb, cancel_cb=_cancel_cb, file_progress_cb=_file_progress_cb)
                        QTimer.singleShot(0, lambda: finished_cb(installed, failures))
                    except Exception as e:
                        QTimer.singleShot(0, lambda: failed_cb(str(e)))
                # If running under pytest, run inline to avoid Windows COM / thread issues in test environment
                if os.environ.get('PYTEST_CURRENT_TEST'):
                    _run()
                    return
                th = threading.Thread(target=_run, daemon=True)
                self._thread = th
                th.start()

        worker = _DialogWorker(install_items, base, target_hint, _perform_pack_installs)
        dlg._worker = worker

        def on_progress(c, t, d):
            try:
                overall_bar.setValue(int((c / max(1, t)) * 100))
                per_label.setText(f"Current: {d}")
                now = time.time()
                if state['last_ts'] is None:
                    state['last_ts'] = now
                remaining_bytes = 0
                for idx_key, tot in state['pack_totals'].items():
                    if idx_key >= c:
                        remaining_bytes += tot
                ema = state['ema']
                sec = remaining_bytes / ema if ema and ema > 0 else None
                eta_label.setText(f"ETA: {fmt_eta(sec)}")
            except Exception:
                pass

        def on_file_progress(idx, total_items, display, written, total_bytes):
            try:
                if total_bytes:
                    per_bar.setValue(int((written / max(1, total_bytes)) * 100))
                now = time.time()
                last = state.get('last_ts') or now
                dt = max(1e-6, now - last)
                state['last_ts'] = now
                try:
                    state['pack_totals'][idx] = total_bytes
                except Exception:
                    pass
                try:
                    sample_bps = written / dt if dt > 0 else 0
                    ema = state.get('ema')
                    if ema:
                        lo = max(1.0, ema * 0.1)
                        hi = max(lo, ema * 10.0)
                        sample_bps = max(lo, min(hi, sample_bps))
                    state['samples'].append(sample_bps)
                    alpha = 0.4
                    s = state['ema']
                    if s is None:
                        s = sample_bps
                    else:
                        s = alpha * sample_bps + (1 - alpha) * s
                    state['ema'] = s
                except Exception:
                    pass
                ema = state.get('ema')
                remaining = 0
                for k, v in state.get('pack_totals', {}).items():
                    if k >= idx:
                        remaining += v
                sec = remaining / ema if ema and ema > 0 else None
                eta_label.setText(f"ETA: {fmt_eta(sec)} ({fmt_speed(ema)})")
            except Exception:
                pass

        def on_finished(installed, failures):
            try:
                if failures:
                    state['failures'] = failures
                    failures_text.clear()
                    for f in failures:
                        try:
                            failures_text.append(str(f))
                        except Exception:
                            pass
                    retry_btn.setEnabled(True)
                else:
                    retry_btn.setEnabled(False)
                try:
                    dlg.hide()
                except Exception:
                    pass
                try:
                    QTimer.singleShot(50, dlg.close)
                except Exception:
                    try:
                        dlg.close()
                    except Exception:
                        pass
            except Exception:
                pass

        def on_failed(msg):
            try:
                QMessageBox.critical(self, 'Install failed', msg)
                dlg.close()
            except Exception:
                pass

        def do_retry():
            retry_items = [(d, s) for (d, s, msg) in state.get('failures', [])]
            if not retry_items:
                return
            failures_text.clear()
            retry_btn.setEnabled(False)
            new_worker = _DialogWorker(retry_items, base, target_hint, _perform_pack_installs)
            dlg._worker = new_worker
            new_worker.start(on_progress, on_file_progress, on_finished, on_failed)

        retry_btn.clicked.connect(do_retry)

        def _close_and_cancel():
            try:
                worker.cancel()
            except Exception:
                pass
            try:
                dlg.hide()
            except Exception:
                pass
            try:
                dlg.close()
            except Exception:
                pass

        close_btn.clicked.connect(_close_and_cancel)

        # Start the dialog worker
        worker.start(on_progress, on_file_progress, on_finished, on_failed)

        # Watchdog: ensure the dialog closes when the worker stops even if signals are missed
        def _watch_worker():
            try:
                w = getattr(dlg, '_worker', None)
                if not w:
                    try:
                        dlg.hide()
                        QTimer.singleShot(50, dlg.close)
                    except Exception:
                        pass
                    return
                running = False
                try:
                    running = bool(w.isRunning())
                except Exception:
                    running = False
                if not running:
                    try:
                        dlg.hide()
                    except Exception:
                        pass
                    try:
                        QTimer.singleShot(50, dlg.close)
                    except Exception:
                        try:
                            dlg.close()
                        except Exception:
                            pass
                    return
                # re-schedule
                QTimer.singleShot(100, _watch_worker)
            except Exception:
                pass

        QTimer.singleShot(200, _watch_worker)

    def import_folder_path(self, src: str):
        base = self.textures_dir.text().strip()
        if not base or not os.path.isdir(base):
            QMessageBox.warning(self, "Missing textures folder", "Please set a valid PCSX2 textures folder path.")
            return

        # If src is already inside base (user selected the intended pack folder), use it directly
        try:
            common = os.path.commonpath([os.path.abspath(base), os.path.abspath(src)])
        except Exception:
            common = None
        if common and os.path.abspath(common) == os.path.abspath(base):
            # If user selected the textures base itself, don't register it as a pack.
            # Instead trigger a scan to list detected serial/CRC subfolders and return.
            try:
                if os.path.abspath(src) == os.path.abspath(base):
                    try:
                        # refresh listing and focus user on Installed Packs
                        self.scan_installed_textures()
                    except Exception:
                        pass
                    return
            except Exception:
                pass
            # Otherwise fall through for cases like selecting a 'replacements' subfolder inside base
            bn = os.path.basename(src)
            if bn.lower() == 'replacements':
                pack_dir = src
                display_name = os.path.basename(os.path.dirname(src))
            else:
                pack_dir = src
                display_name = os.path.basename(src)
            # Instead of copying into the textures base immediately, stage the selected folder under _imports
            imports_root = self._imports_root(base)
            os.makedirs(imports_root, exist_ok=True)
            bn = os.path.basename(src)
            staging = os.path.join(imports_root, bn)
            try:
                if os.path.exists(staging):
                    shutil.rmtree(staging)
                shutil.copytree(src, staging)
            except Exception:
                # fallback: try to move or continue using src as staging
                staging = src

            # Detect child pack folders inside staging and register them separately
            pack_dirs = []
            for child in os.listdir(staging):
                childp = os.path.join(staging, child)
                if os.path.isdir(childp):
                    if self._find_replacements_in_tree(childp) or os.path.isdir(os.path.join(childp, 'replacements')):
                        pack_dirs.append(childp)
            if not pack_dirs:
                pack_dirs = [staging]

            for pd in pack_dirs:
                display_name = os.path.basename(pd)
                m = SERIAL_RE.search(display_name)
                if m:
                    display_name = m.group(0).upper()
                exists = False
                for i in range(self.packs_list.topLevelItemCount()):
                    it = self.packs_list.topLevelItem(i)
                    if it and it.data(0, Qt.UserRole) == pd:
                        exists = True
                        break
                if exists:
                    continue
                safe_key = os.path.basename(display_name).replace(os.sep, '_')
                thumb = self._make_thumbnail(pd, safe_key)
                title_col = ""
                try:
                    if SERIAL_RE.search(display_name) and not HEX8.match(display_name):
                        kU = display_name.upper().strip()
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                        try:
                            bl = bundled_lookup_title(kU)
                            if bl:
                                title_col = bl
                                try:
                                    self.parent.cheats_tab.mapping[kU] = bl
                                    self.parent.cheats_tab.save_mapping()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    title_col = ""
                it = QTreeWidgetItem([display_name, title_col, "staged"])
                it.setData(0, Qt.UserRole, pd)
                tt = pd
                try:
                    if title_col:
                        tt = f"{pd}\n{title_col}"
                except Exception:
                    pass
                it.setToolTip(0, tt)
                # Use the thumbnail if it was successfully created
                if thumb and os.path.isfile(thumb):
                    it.setIcon(0, QIcon(thumb))
                else:
                    it.setIcon(0, QIcon())
                self.packs_list.addTopLevelItem(it)
            # Refresh UI list but do not install any pack yet
            try:
                # keep focus on Installed Packs
                self.scan_installed_textures()
            except Exception:
                pass
            return

        # Otherwise infer target folder name from user input or source folder name
        sub = self.target_folder_name.text().strip()
        if not sub:
            # If source ends with 'replacements', use parent folder name
            bn = os.path.basename(src)
            if bn.lower() == 'replacements':
                candidate = os.path.basename(os.path.dirname(src))
            else:
                candidate = os.path.basename(src)
            # Prefer serial if detected in the candidate or inside folder tree
            m = SERIAL_RE.search(candidate)
            if not m:
                # shallow search inside src for serial-like folder or file names
                for root, dirs, files in os.walk(src):
                    for nm in dirs + files:
                        mm = SERIAL_RE.search(nm)
                        if mm:
                            m = mm
                            break
                    if m:
                        break
            sub = m.group(0).upper() if m else candidate

        target = os.path.join(base, sub)
        try:
            if os.path.exists(target) and os.path.isdir(target):
                # copy contents of src into existing target
                for item in os.listdir(src):
                    s = os.path.join(src, item)
                    d = os.path.join(target, item)
                    if os.path.isdir(s):
                        if os.path.exists(d): shutil.rmtree(d)
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)
            else:
                # copy entire src into target
                shutil.copytree(src, target)
            QMessageBox.information(self, "Imported", f"Copied folder contents to:\n{target}")
            try:
                self.scan_installed_textures()
            except Exception:
                pass
        except Exception as e:
            QMessageBox.critical(self, "Copy error", str(e))

    # Drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith('.zip'):
                self.import_zip_path(p)
            elif os.path.isdir(p):
                self.import_folder_path(p)

    def _row(self, *widgets):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for wd in widgets:
            h.addWidget(wd)
        h.addStretch(1)
        return w

    def load_paths(self, paths: dict):
        self.textures_dir.setText(paths.get("textures", ""))

    def _pick_dir(self, line: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, "Select folder", line.text() or os.path.expanduser("~"))
        if d: line.setText(d)

    def _target_dir(self) -> Optional[str]:
        base = self.textures_dir.text().strip()
        if not base or not os.path.isdir(base):
            QMessageBox.warning(self, "Missing textures folder", "Please set a valid PCSX2 textures folder path.")
            return None
        sub = self.target_folder_name.text().strip()
        if not sub:
            # Try auto-CRC from logs
            suggestion = self._suggest_crc_from_logs()
            if suggestion:
                self.target_folder_name.setText(suggestion)
                sub = suggestion
            else:
                QMessageBox.information(self, "Folder name needed", "Enter a target subfolder name (CRC recommended).")
                return None
        out = os.path.join(base, sub)
        os.makedirs(out, exist_ok=True)
        return out

    def _on_pack_selected(self):
        sel = self.packs_list.selectedItems()
        if not sel:
            # clear preview
            try:
                self.preview_cover.clear()
                self.preview_title.setText("")
                self.preview_serial.setText("")
                self.preview_path.setText("")
            except Exception:
                pass
            self.btn_open_pack.setEnabled(False)
            self.btn_install_pack.setEnabled(False)
            self.btn_remove_pack.setEnabled(False)
            return

        it = sel[0]
        pack_dir = it.data(0, Qt.UserRole)
        # Prefer an explicit serial stored on the item (UserRole+2). If missing, try to compute and cache one.
        serial_stored = ''
        try:
            serial_stored = (it.data(0, Qt.UserRole + 2) or '').strip()
        except Exception:
            serial_stored = ''
        if not serial_stored:
            # Try to extract from display text then from path
            try:
                disp = it.text(0) or ''
                m = SERIAL_RE.search(disp)
                if m:
                    serial_stored = m.group(0).upper()
                else:
                    pth = it.data(0, Qt.UserRole) or ''
                    try:
                        m2 = SERIAL_RE.search(os.path.basename(pth) or '')
                        if m2:
                            serial_stored = m2.group(0).upper()
                    except Exception:
                        serial_stored = ''
            except Exception:
                serial_stored = ''
            # cache back onto the item for future use
            try:
                if serial_stored:
                    it.setData(0, Qt.UserRole + 2, serial_stored)
            except Exception:
                pass
        # populate preview path
        self.preview_path.setText(pack_dir or "")

    # Prefer Title column (column 1) for the preview title when available
        try:
            title_col = it.text(1) or ""
        except Exception:
            # fallback if API differs
            title_col = ""

        # The display column (0) may include 'Serial — Title' for backward compat
        try:
            display_col = it.text(0) or ""
        except Exception:
            display_col = str(it)

        serial_val = ""
        title_val = ""

        if title_col and title_col.strip():
            # Use explicit title column; try to extract serial from display_col or path
            title_val = title_col.strip()
            # If display_col contains an em-dash, left side is serial
            if '—' in display_col:
                parts = [p.strip() for p in display_col.split('—', 1)]
                serial_val = parts[0]
            else:
                # Prefer stored serial if present, otherwise try to find a serial-like token in display_col
                if serial_stored:
                    serial_val = serial_stored
                else:
                    m = SERIAL_RE.search(display_col or '')
                    if m:
                        serial_val = m.group(0).upper()
                    else:
                        # fallback: try pack_dir basename
                        try:
                            bn = os.path.basename(pack_dir or '')
                            m2 = SERIAL_RE.search(bn)
                            if m2:
                                serial_val = m2.group(0).upper()
                        except Exception:
                            serial_val = ""
        else:
            # No explicit title column: parse display_col for both serial and title
            if '—' in display_col:
                parts = [p.strip() for p in display_col.split('—', 1)]
                serial_val = parts[0]
                title_val = parts[1]
            else:
                # try to extract serial first, then use rest as title
                if serial_stored:
                    serial_val = serial_stored
                    # try to produce a title by removing serial token from display_col if present
                    m = SERIAL_RE.search(display_col or '')
                    if m:
                        title_val = display_col.replace(m.group(0), '').strip(' -_/') or ""
                    else:
                        title_val = display_col
                else:
                    m = SERIAL_RE.search(display_col or '')
                    if m:
                        serial_val = m.group(0).upper()
                        title_val = display_col.replace(m.group(0), '').strip(' -_/') or ""
                    else:
                        # nothing serial-like; use display_col as title
                        title_val = display_col

        # Populate preview widgets
        try:
            self.preview_title.setText(title_val or "")
            self.preview_serial.setText(serial_val or "")
        except Exception:
            pass

    # Try to resolve title from local mapping if missing
        try:
            if not title_val and serial_val:
                mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                kU = serial_val.upper().strip()
                title_val = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or title_val
        except Exception:
            pass

        # Try to get game cover - prioritize actual covers over random texture files
        pix = None
        
        # First check if we have a serial to fetch proper cover
        if serial_stored:
            serial_val = serial_stored

        if serial_val and requests is not None:
            try:
                # Normalize the serial for cache filename and remote URL lookups
                serial_key = norm_serial_key(serial_val)
                cache_name = os.path.join(self._thumb_cache, f"cover_{serial_key}.jpg")
                # If cache exists, load it synchronously
                if os.path.isfile(cache_name):
                    pm = QPixmap(cache_name)
                    if pm and not pm.isNull():
                        pix = pm
                else:
                    # Build a prioritized list of candidate serial keys to probe for remote covers
                    raw = (serial_val or '').strip()
                    sk = norm_serial_key(raw)
                    variants = []
                    # preferred: normalized uppercase no separators
                    if sk:
                        variants.append(sk.upper())
                    # original presentation (uppercase)
                    if raw:
                        variants.append(raw.upper())
                    # no-hyphen/no-underscore/lower variants
                    variants.append(raw.replace('-', '').replace('_', '').replace(' ', '').upper())
                    variants.append((raw.replace('-', '').replace('_', '').replace(' ', '')).lower())
                    variants.append(sk.lower())
                    # dedupe while preserving order
                    seen = set()
                    uniq = []
                    for v in variants:
                        if not v: continue
                        if v in seen: continue
                        seen.add(v)
                        uniq.append(v)
                    candidates = [f"https://raw.githubusercontent.com/xlenore/ps2-covers/main/covers/default/{v}.jpg" for v in uniq]
                    # Prefer previously successful candidate if recorded in index.json
                    try:
                        idx_file = os.path.join(self._thumb_cache, 'index.json')
                        if os.path.isfile(idx_file):
                            with open(idx_file, 'r', encoding='utf-8') as inf:
                                idx = json.load(inf)
                            for v in uniq:
                                if v in idx:
                                    known = idx[v]
                                    if known in candidates:
                                        candidates.remove(known)
                                        candidates.insert(0, known)
                                        break
                    except Exception:
                        pass
                    self.preview_loading.setVisible(True)

                    # local handlers for worker signals
                    def _on_fetched(path: str):
                        try:
                            pm = QPixmap(path)
                            if pm and not pm.isNull():
                                # set pixmap but size label to exact scaled dimensions (no cropping)
                                _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                        except Exception:
                            self.preview_cover.clear()
                        finally:
                            self.preview_loading.setVisible(False)

                    def _on_failed():
                        try:
                            # Try cached file first
                            if os.path.isfile(cache_name):
                                pm = QPixmap(cache_name)
                                if pm and not pm.isNull():
                                    _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                                    return
                            
                            # Try bundled logo
                            bundled = os.path.join(os.path.dirname(__file__), 'logo.png')
                            if os.path.isfile(bundled):
                                pm = QPixmap(bundled)
                                if pm and not pm.isNull():
                                    _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                                    return
                            
                            # Show placeholder with hint - use exact fitting like other pixmaps
                            placeholder = create_cover_placeholder(serial_val)
                            if placeholder and not placeholder.isNull():
                                _set_label_pixmap_exact(self.preview_cover, placeholder, max_dim=420)
                            else:
                                self.preview_cover.clear()
                        except Exception as e:
                            logger.error(f"Error in _on_failed: {e}")
                            try:
                                self.preview_cover.clear()
                            except Exception:
                                pass
                        finally:
                            self.preview_loading.setVisible(False)

                    worker = CoverFetchWorker(candidates, cache_name, parent=self)
                    worker.fetched.connect(_on_fetched)
                    worker.fetch_failed.connect(_on_failed)
                    self._start_worker(worker)
            except Exception:
                pix = None

        if pix:
            # Display pixmap with exact fit up to a sensible maximum
            _set_label_pixmap_exact(self.preview_cover, pix, max_dim=420)
        else:
            self.preview_cover.clear()

        # enable actions
        self.btn_open_pack.setEnabled(bool(pack_dir))
        # allow install for local zips or external packs; assume install enabled
        self.btn_install_pack.setEnabled(True)
        self.btn_remove_pack.setEnabled(bool(pack_dir))

    def scan_installed_textures(self):
        """Scan the textures base folder for installed packs (subfolders). Build thumbnails for each pack."""
        base = self.textures_dir.text().strip()
        self.packs_list.clear()
        if not base or not os.path.isdir(base):
            return
        
        # Process events periodically to keep UI responsive
        from PySide6.QtWidgets import QApplication
        process_counter = 0

        def contains_images(d: str, depth=2) -> bool:
            exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
            try:
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.lower().endswith(exts):
                            return True
                    if os.path.relpath(root, d).count(os.sep) >= depth:
                        continue
            except Exception:
                return False
            return False

        # If user pointed to a 'replacements' folder inside a CRC folder, show that CRC as a pack
        bn = os.path.basename(base)
        parent = os.path.dirname(base)
        if bn.lower() == 'replacements' and os.path.isdir(parent):
            parent_bn = os.path.basename(parent)
            if HEX8.match(parent_bn) or SERIAL_RE.search(parent_bn) or contains_images(base):
                # mark serial folders explicitly
                if SERIAL_RE.search(parent_bn) and not HEX8.match(parent_bn):
                    # Try to resolve full title from mapping using serial
                    serial = parent_bn
                    mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                    title = None
                    kU = serial.upper().strip()
                    if kU in mapping:
                        title = mapping[kU]
                    else:
                        kN = norm_serial_key(kU)
                        if kN in mapping:
                            title = mapping[kN]
                    display = f"{serial} — {title}" if title else serial
                else:
                    display = parent_bn
                pack_dir = base
                thumb = self._make_thumbnail(pack_dir, display)
                title_col = ""
                try:
                    if SERIAL_RE.search(parent_bn) and not HEX8.match(parent_bn):
                        kU = parent_bn.upper().strip()
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                except Exception:
                    title_col = ""
                it = QTreeWidgetItem([display, title_col, ""]) 
                it.setData(0, Qt.UserRole, pack_dir)
                tt = pack_dir
                try:
                    if title_col:
                        tt = f"{pack_dir}\n{title_col}"
                except Exception:
                    pass
                it.setToolTip(0, tt)
                # Use the thumbnail if it was successfully created
                if thumb and os.path.isfile(thumb):
                    it.setIcon(0, QIcon(thumb))
                else:
                    it.setIcon(0, QIcon())
                try:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"[TexturesTab] adding item: display='{display}' title_col='{title_col}' path='{pack_dir}'")
                except Exception:
                    pass
                self.packs_list.addTopLevelItem(it)

        # helper: check shallow images (direct files in base or a direct 'replacements' child)
        def _contains_images_shallow(d: str) -> bool:
            exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
            try:
                # check direct files in d
                for f in os.listdir(d):
                    pth = os.path.join(d, f)
                    if os.path.isfile(pth) and f.lower().endswith(exts):
                        return True
                # check direct 'replacements' child
                repl = os.path.join(d, 'replacements')
                if os.path.isdir(repl):
                    for f in os.listdir(repl):
                        if f.lower().endswith(exts):
                            return True
            except Exception:
                return False
            return False

        

        # If the base itself looks like a CRC folder or contains images, treat it as a single pack
        # but if the base contains serial/CRC subfolders, prefer listing those instead.
        # Look for serial/CRC child folders not only immediately under base but also one level deeper.
        def _find_serial_children(root: str, max_depth: int = 2):
            found = []
            try:
                # breadth-first-ish: check immediate children first, then one-level nested
                for name in os.listdir(root):
                    p = os.path.join(root, name)
                    if os.path.isdir(p):
                        if SERIAL_RE.search(name) or HEX8.match(name):
                            found.append(name)
                # if none found at level 1, check level 2 (child of each immediate child)
                if not found and max_depth >= 2:
                    for name in os.listdir(root):
                        p = os.path.join(root, name)
                        if os.path.isdir(p):
                            try:
                                for sub in os.listdir(p):
                                    ps = os.path.join(p, sub)
                                    if os.path.isdir(ps) and (SERIAL_RE.search(sub) or HEX8.match(sub)):
                                        found.append(os.path.join(name, sub))
                            except Exception:
                                continue
            except Exception:
                return []
            return found

        child_dirs = _find_serial_children(base, max_depth=2)
        has_serial_children = bool(child_dirs)
        try:
            if child_dirs:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"[TexturesTab] detected serial children under '{base}': {child_dirs}")
        except Exception:
            pass

        if (HEX8.match(bn) or SERIAL_RE.search(bn) or contains_images(base)) and (not has_serial_children):
            # mark serial folders explicitly
            if SERIAL_RE.search(bn) and not HEX8.match(bn):
                # Resolve serial -> full title when possible
                serial = bn
                mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                title = None
                kU = serial.upper().strip()
                if kU in mapping:
                    title = mapping[kU]
                else:
                    kN = norm_serial_key(kU)
                    if kN in mapping:
                        title = mapping[kN]
                display = f"{serial} — {title}" if title else serial
            else:
                display = bn
            pack_dir = base
            # prefer 'replacements' subfolder for actual images if present
            repl = os.path.join(base, 'replacements')
            if os.path.isdir(repl) and contains_images(repl):
                pack_dir = repl
            safe_key = display.replace(os.sep, '_')
            thumb = self._make_thumbnail(pack_dir, safe_key)
            title_col = ""
            try:
                if SERIAL_RE.search(bn) and not HEX8.match(bn):
                    kU = bn.upper().strip()
                    mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                    title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
            except Exception:
                title_col = ""
            it = QTreeWidgetItem([display, title_col, ""]) 
            it.setData(0, Qt.UserRole, pack_dir)
            tt = pack_dir
            try:
                if title_col:
                    tt = f"{pack_dir}\n{title_col}"
            except Exception:
                pass
            it.setToolTip(0, tt)
            # Use the thumbnail if it was successfully created
            if thumb and os.path.isfile(thumb):
                it.setIcon(0, QIcon(thumb))
            else:
                it.setIcon(0, QIcon())
            try:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"[TexturesTab] adding item: display='{display}' title_col='{title_col}' path='{pack_dir}'")
            except Exception:
                pass
            self.packs_list.addTopLevelItem(it)
            return
        def contains_images(d: str, depth=2) -> bool:
            exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
            try:
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.lower().endswith(exts):
                            return True
                    # limit depth to avoid long walks
                    if os.path.relpath(root, d).count(os.sep) >= depth:
                        continue
            except Exception:
                return False
            return False

        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            try:
                logger.debug(f"[TexturesTab] scanning child: '{name}' is_dir={os.path.isdir(p)}")
            except Exception:
                pass
            # show ZIP files as importable packs
            if os.path.isfile(p) and p.lower().endswith('.zip'):
                title_col = ""
                try:
                    if SERIAL_RE.search(name) and not HEX8.match(name):
                        kU = name.upper().strip()
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                except Exception:
                    title_col = ""
                it = QTreeWidgetItem([name, title_col, ""]) 
                it.setData(0, Qt.UserRole, p)
                tt = p
                try:
                    if title_col:
                        tt = f"{p}\n{title_col}"
                except Exception:
                    pass
                it.setToolTip(0, tt)
                it.setIcon(0, QIcon())
                try:
                    logger.debug(f"[TexturesTab] adding zip item: display='{name}' title_col='{title_col}' path='{p}'")
                except Exception:
                    pass
                self.packs_list.addTopLevelItem(it)
        
                # Process events every 5 items to keep UI responsive
                process_counter += 1
                if process_counter % 5 == 0:
                    QApplication.processEvents()
        
                continue

            if not os.path.isdir(p):
                continue

            # If this child folder itself is a serial/CRC folder, prefer to add it as a pack
            try:
                if SERIAL_RE.search(name) or HEX8.match(name):
                    # Diagnostic: list immediate entries to understand folder layout
                    try:
                        entries = os.listdir(p)
                        logger.debug(f"[TexturesTab] child entries for '{name}': {entries}")
                    except Exception:
                        entries = []
                    try:
                        has_repl = os.path.isdir(os.path.join(p, 'replacements'))
                        logger.debug(f"[TexturesTab] '{name}' has 'replacements' child: {has_repl}")
                    except Exception:
                        pass
                    # Find the best image root (prefer replacements)
                    target = self._find_replacements_in_tree(p) or p
                    logger.debug(f"[TexturesTab] _find_replacements_in_tree('{p}') -> {target}")
                    # If still no images, check direct 'replacements' child explicitly
                    try:
                        repl = os.path.join(p, 'replacements')
                        if os.path.isdir(repl) and contains_images(repl):
                            target = repl
                    except Exception:
                        pass
                    # Always add the serial/CRC child as a pack entry (user can inspect it)
                    display = name
                    if SERIAL_RE.search(name) and not HEX8.match(name):
                        serial = name
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        title = None
                        kU = serial.upper().strip()
                        if kU in mapping:
                            title = mapping[kU]
                        else:
                            kN = norm_serial_key(kU)
                            if kN in mapping:
                                title = mapping[kN]
                        display = f"{serial} — {title}" if title else serial
                    safe_key = display.replace(os.sep, '_')
                    thumb = self._make_thumbnail(target, safe_key)
                    title_col = ""
                    try:
                        if SERIAL_RE.search(name) and not HEX8.match(name):
                            kU = name.upper().strip()
                            mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                            title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                            # Try bundled local lookup as a deterministic source before async resolver
                            try:
                                bl = bundled_lookup_title(kU)
                                if bl:
                                    title_col = bl
                                    try:
                                        # persist into mapping
                                        self.parent.cheats_tab.mapping[kU] = bl
                                        self.parent.cheats_tab.save_mapping()
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                    except Exception:
                        title_col = ""
                    it = QTreeWidgetItem([display, title_col, ""]) 
                    it.setData(0, Qt.UserRole, target)
                    tt = target
                    try:
                        if title_col:
                            tt = f"{target}\n{title_col}"
                    except Exception:
                        pass
                    it.setToolTip(0, tt)
                    # Use the thumbnail if it was successfully created
                    if thumb and os.path.isfile(thumb):
                        it.setIcon(0, QIcon(thumb))
                    else:
                        it.setIcon(0, QIcon())
                    try:
                        logger.debug(f"[TexturesTab] adding serial child item: display='{display}' title_col='{title_col}' path='{target}'")
                    except Exception:
                        pass
                    self.packs_list.addTopLevelItem(it)
                    
                    # Process events to keep UI responsive
                    process_counter += 1
                    if process_counter % 5 == 0:
                        QApplication.processEvents()
                    
                    continue
            except Exception:
                pass

            # If folder contains CRC-named child folders, list those separately
            try:
                children = [d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d))]
            except Exception:
                children = []
            crc_children = [d for d in children if HEX8.match(d)]
            if crc_children:
                for c in sorted(crc_children):
                    pack_dir = os.path.join(p, c)
                    # If CRC child is actually a serial, try to resolve title
                    if SERIAL_RE.search(c) and not HEX8.match(c):
                        serial = c
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        title = None
                        kU = serial.upper().strip()
                        if kU in mapping:
                            title = mapping[kU]
                        else:
                            kN = norm_serial_key(kU)
                            if kN in mapping:
                                title = mapping[kN]
                        display = f"{serial} — {title}" if title else f"{name}/{c}"
                    else:
                        display = f"{name}/{c}"
                    thumb = self._make_thumbnail(pack_dir, display.replace(os.sep, '_'))
                    title_col = ""
                    try:
                        if SERIAL_RE.search(c) and not HEX8.match(c):
                            kU = c.upper().strip()
                            mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                            title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                    except Exception:
                        title_col = ""
                    it = QTreeWidgetItem([display, title_col, ""]) 
                    it.setData(0, Qt.UserRole, pack_dir)
                    tt = pack_dir
                    try:
                        if title_col:
                            tt = f"{pack_dir}\n{title_col}"
                    except Exception:
                        pass
                    it.setToolTip(0, tt)
                    # Use the thumbnail if it was successfully created
                    if thumb and os.path.isfile(thumb):
                        it.setIcon(0, QIcon(thumb))
                    else:
                        it.setIcon(0, QIcon())
                    try:
                        logger.debug(f"[TexturesTab] adding crc-child item: display='{display}' title_col='{title_col}' path='{pack_dir}'")
                    except Exception:
                        pass
                    self.packs_list.addTopLevelItem(it)
                    
                    # Process events to keep UI responsive
                    process_counter += 1
                    if process_counter % 5 == 0:
                        QApplication.processEvents()
                    
                continue

            # If the folder (or a single nested child) contains images, treat it as a pack
            target = p
            # collapse single-child chains up to depth 3
            for _ in range(3):
                try:
                    subs = [d for d in os.listdir(target) if os.path.isdir(os.path.join(target, d))]
                except Exception:
                    subs = []
                if len(subs) == 1 and not contains_images(target):
                    target = os.path.join(target, subs[0])
                else:
                    break

            if contains_images(target):
                # display name should be relative to base to help identify nested packs
                display = os.path.relpath(target, base)
                # cache key needs safe name (no path separators)
                safe_key = display.replace(os.sep, '_')
                thumb = self._make_thumbnail(target, safe_key)
                # If display looks like a serial, try to resolve title and prefer showing the full title
                if SERIAL_RE.search(os.path.basename(display)) and not HEX8.match(os.path.basename(display)):
                    serial = os.path.basename(display)
                    mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                    title = None
                    kU = serial.upper().strip()
                    if kU in mapping:
                        title = mapping[kU]
                    else:
                        kN = norm_serial_key(kU)
                        if kN in mapping:
                            title = mapping[kN]
                    item_text = f"{serial} — {title}" if title else serial
                else:
                    item_text = display
                title_col = ""
                try:
                    if SERIAL_RE.search(os.path.basename(display)) and not HEX8.match(os.path.basename(display)):
                        kU = os.path.basename(display).upper().strip()
                        mapping = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                        title_col = mapping.get(kU) or mapping.get(norm_serial_key(kU)) or ""
                        try:
                            bl = bundled_lookup_title(kU)
                            if bl:
                                title_col = bl
                                try:
                                    self.parent.cheats_tab.mapping[kU] = bl
                                    self.parent.cheats_tab.save_mapping()
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    title_col = ""
                it = QTreeWidgetItem([item_text, title_col, ""]) 
                it.setData(0, Qt.UserRole, target)
                tt = target
                try:
                    if title_col:
                        tt = f"{target}\n{title_col}"
                except Exception:
                    pass
                it.setToolTip(0, tt)
                # Use the thumbnail if it was successfully created
                if thumb and os.path.isfile(thumb):
                    it.setIcon(0, QIcon(thumb))
                else:
                    it.setIcon(0, QIcon())
                try:
                    logger.debug(f"[TexturesTab] adding image-pack item: display='{item_text}' title_col='{title_col}' path='{target}'")
                except Exception:
                    pass
                self.packs_list.addTopLevelItem(it)
                
                # Process events to keep UI responsive
                process_counter += 1
                if process_counter % 5 == 0:
                    QApplication.processEvents()

        # After full listing, print diagnostics and resolve titles for items missing Title column
        try:
            # If we detected serial/CRC child folders, remove any top-level item that points to the base folder
            try:
                if has_serial_children:
                    # remove matching items (iterate backwards)
                    for idx in range(self.packs_list.topLevelItemCount()-1, -1, -1):
                        itm = self.packs_list.topLevelItem(idx)
                        try:
                            pth = itm.data(0, Qt.UserRole)
                            if isinstance(pth, str) and os.path.abspath(pth) == os.path.abspath(base):
                                try:
                                    logger.debug(f"[TexturesTab] removing base-as-pack item at index {idx} (path='{pth}')")
                                except Exception:
                                    pass
                                self.packs_list.takeTopLevelItem(idx)
                        except Exception:
                            continue
            except Exception:
                pass
            # Diagnostic: enumerate all items we added so we can see what display/title/path they have
            try:
                for i in range(self.packs_list.topLevelItemCount()):
                    itm = self.packs_list.topLevelItem(i)
                    if not itm:
                        continue
                    disp = itm.text(0) or ''
                    title_col = itm.text(1) or ''
                    data_path = itm.data(0, Qt.UserRole) or ''
                    try:
                        logger.debug(f"[TexturesTab] item #{i}: display='{disp}' title_col='{title_col}' path='{data_path}'")
                    except Exception:
                        pass
            except Exception:
                pass

            keys = []
            item_map = {}
            for i in range(self.packs_list.topLevelItemCount()):
                itm = self.packs_list.topLevelItem(i)
                if not itm:
                    continue
                title_col = (itm.text(1) or '').strip()
                if title_col:
                    continue
                # try display name then stored path
                display = itm.text(0) or ''
                cand = None
                m = SERIAL_RE.search(display)
                if m:
                    cand = m.group(0).upper().strip()
                else:
                    try:
                        p = itm.data(0, Qt.UserRole)
                        if isinstance(p, str):
                            m2 = SERIAL_RE.search(os.path.basename(p))
                            if m2:
                                cand = m2.group(0).upper().strip()
                    except Exception:
                        cand = None
                if cand:
                    if cand not in keys:
                        keys.append(cand)
                    item_map.setdefault(cand, []).append(itm)

            if keys:
                try:
                    logger.debug(f"[TexturesTab] resolving serial keys: {keys}")
                except Exception:
                    pass
                # Build variants for more robust lookup (with/without hyphen, normalized)
                expanded_keys = []
                for k in keys:
                    if not k: continue
                    k = k.strip()
                    variants = [k, k.upper(), norm_serial_key(k), k.replace('-', ''), k.replace('-', '').upper()]
                    # keep unique preserving order
                    for v in variants:
                        if v and v not in expanded_keys:
                            expanded_keys.append(v)

                try:
                    logger.debug(f"[TexturesTab] expanded resolver keys: {expanded_keys}")
                except Exception:
                    pass

                local_map = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
                # Use bundled local PSXDataCenter lists by default for reliability
                use_bundled = True
                # Respect the user's 'Also try web lookup' checkbox for online fallback
                try_online = False
                try:
                    try_online = bool(getattr(self.parent.cheats_tab, 'chk_online', None) and self.parent.cheats_tab.chk_online.isChecked()) and (requests is not None)
                except Exception:
                    try_online = False
                if try_online:
                    try:
                        logger.debug("[TexturesTab] online lookup enabled for resolver")
                    except Exception:
                        pass

                worker = ResolveWorker(keys=list(expanded_keys), local_map=local_map, use_bundled_lists=use_bundled, try_online=try_online)

                def _on_resolved(out: Dict[str, str]):
                    try:
                        logger.debug(f"[TexturesTab] resolver returned: {out}")
                    except Exception:
                        pass
                    # Collect serials that still need a better lookup (resolver returned placeholders)
                    need_online = []
                    for cand, items in item_map.items():
                        picked = None
                        # Check multiple variant forms in returned map
                        candidates_to_check = [cand, cand.upper(), norm_serial_key(cand), cand.replace('-', ''), cand.replace('-', '').upper()]
                        for ck in candidates_to_check:
                            if not ck: continue
                            if ck in out:
                                picked = out[ck]
                                break
                        # Try CRC-linked entries if present
                        if not picked:
                            for ck in candidates_to_check:
                                if (ck + '_CRC') in out:
                                    crc = out[ck + '_CRC']
                                    if crc in out:
                                        picked = out[crc]
                                        break
                        # If picked is an unhelpful placeholder like 'INFO' or 'TITLE', treat as unresolved
                        if isinstance(picked, str) and picked.strip().upper() in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
                            picked = None
                        if picked:
                            for it in items:
                                try:
                                    it.setText(1, picked)
                                    tt = it.toolTip(0) or it.data(0, Qt.UserRole) or ''
                                    it.setToolTip(0, f"{tt}\n{picked}")
                                except Exception:
                                    pass
                            try:
                                self.parent.cheats_tab.mapping[cand.upper()] = picked
                                # persist mapping
                                try:
                                    self.parent.cheats_tab.save_mapping()
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        else:
                            # schedule focused online lookup for this serial if possible
                            try:
                                if SERIAL_RE.search(cand):
                                    need_online.append(cand)
                            except Exception:
                                pass

                    # Kick focused online lookups for unresolved serials (best-effort)
                    if need_online and requests is not None:
                        try:
                            for s in need_online:
                                def make_on_found(serial):
                                    def _on_found(title: str):
                                        try:
                                            # update all items for this serial
                                            for it in item_map.get(serial, []):
                                                try:
                                                    it.setText(1, title)
                                                    tt = it.toolTip(0) or it.data(0, Qt.UserRole) or ''
                                                    it.setToolTip(0, f"{tt}\n{title}")
                                                except Exception:
                                                    pass
                                                # cache in mapping and persist
                                                try:
                                                    self.parent.cheats_tab.mapping[serial.upper()] = title
                                                    try:
                                                        self.parent.cheats_tab.save_mapping()
                                                    except Exception:
                                                        pass
                                                except Exception:
                                                    pass
                                        except Exception:
                                            pass
                                    return _on_found

                                def make_on_failed(serial):
                                    def _on_failed():
                                        try:
                                            logger.debug(f"[TexturesTab] SingleOnlineLookup failed for {serial}")
                                            # Automatic-only mode: do not prompt the user. Leave unresolved.
                                            try:
                                                pass
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass
                                    return _on_failed

                                worker2 = SingleOnlineLookup(s, parent=self)
                                worker2.found.connect(make_on_found(s))
                                worker2.failed.connect(make_on_failed(s))
                                self._start_worker(worker2)
                        except Exception:
                            pass

                worker.resolved.connect(_on_resolved)
                try:
                    self.parent.cheats_tab._start_worker(worker)
                except Exception:
                    self._start_worker(worker)
        except Exception:
            pass

    def _make_thumbnail(self, pack_dir: str, key: str) -> Optional[str]:
        """Create or reuse a thumbnail image path for a pack. Returns path to thumbnail file usable by QIcon."""
        try:
            # Sanitize the key to create a valid filename
            # Remove or replace characters that are invalid in filenames
            import re
            # Replace invalid filename characters with underscore
            safe_key = re.sub(r'[<>:"/\\|?*◆♦●○■□▲△▼▽◇◆★☆]', '_', key)
            # Also replace em-dash and other special dashes with regular dash
            safe_key = safe_key.replace('—', '-').replace('–', '-')
            # Remove any remaining non-ASCII characters that might cause issues
            safe_key = safe_key.encode('ascii', 'ignore').decode('ascii')
            # Remove multiple consecutive underscores
            safe_key = re.sub(r'_+', '_', safe_key)
            # Remove leading/trailing underscores and spaces
            safe_key = safe_key.strip('_ ')
            
            cache_file = os.path.join(self._thumb_cache, f"{safe_key}.png")
            # Check if cached thumbnail exists - if so, use it (performance optimization)
            # Only regenerate if cache is missing or very old (>30 days)
            if os.path.isfile(cache_file):
                try:
                    cache_age = time.time() - os.path.getmtime(cache_file)
                    if cache_age < (30 * 24 * 3600):  # Less than 30 days old
                        return cache_file
                except Exception:
                    # If we can't check age, just use the cache
                    return cache_file
            
            # find first suitable image
            exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
            for root, _, files in os.walk(pack_dir):
                for f in files:
                    if f.lower().endswith(exts):
                        src = os.path.join(root, f)
                        try:
                            pix = QPixmap(src)
                            if pix and not pix.isNull():
                                try:
                                    # don't upscale small images; only scale down to max 64
                                    maxd = 64
                                    w = pix.width()
                                    h = pix.height()
                                    scale = 1.0
                                    if max(w, h) > maxd:
                                        scale = float(maxd) / float(max(w, h))
                                    tw = max(1, int(w * scale))
                                    th = max(1, int(h * scale))
                                    scaled = pix.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                                    scaled.save(cache_file, 'PNG')
                                    return cache_file
                                except Exception:
                                    pass
                        except Exception:
                            continue
                break
            
            # If no images found, create a placeholder thumbnail
            try:
                # Create a 64x64 placeholder with a folder icon or neutral color
                placeholder = QPixmap(64, 64)
                placeholder.fill(Qt.transparent)
                
                # Draw a simple folder/texture icon
                painter = QPainter(placeholder)
                try:
                    painter.setRenderHint(QPainter.Antialiasing)
                    
                    # Draw a folder-like shape
                    painter.setPen(QPen(QColor(150, 150, 150), 2))
                    painter.setBrush(QColor(200, 200, 200, 180))
                    painter.drawRoundedRect(8, 16, 48, 40, 4, 4)
                    
                    # Draw a tab
                    painter.setBrush(QColor(180, 180, 180, 180))
                    painter.drawRoundedRect(8, 12, 24, 8, 2, 2)
                    
                    # Draw texture pattern (small squares)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(120, 120, 120, 100))
                    for i in range(3):
                        for j in range(3):
                            painter.drawRect(16 + i*12, 24 + j*12, 8, 8)
                finally:
                    # Always end the painter, even if drawing fails
                    painter.end()
                
                # Save placeholder
                placeholder.save(cache_file, 'PNG')
                return cache_file
            except Exception as e:
                try:
                    logger.debug(f"[TexturesTab] placeholder generation failed: {e}")
                except Exception:
                    pass
            
            return None
        except Exception:
            return None

    def _find_replacements_in_tree(self, start: str) -> Optional[str]:
        """Recursively search for a 'replacements' folder or the first folder that contains images.
        Returns the path to the folder that should be used as the pack root (replacements) or None."""
        exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
        # If start itself contains images, prefer it
        for root, dirs, files in os.walk(start):
            for f in files:
                if f.lower().endswith(exts):
                    return root
            # prefer a direct 'replacements' folder if found among children
            for d in list(dirs):
                if d.lower() == 'replacements':
                    cand = os.path.join(root, d)
                    # ensure it contains images
                    for _, __, files2 in os.walk(cand):
                        for f2 in files2:
                            if f2.lower().endswith(exts):
                                return cand
        return None

    def _install_selected_pack(self):
        sel = self.packs_list.selectedItems()
        if not sel:
            return
        # resolve source path from selected item
        src = sel[0].data(0, Qt.UserRole)
        base = self.textures_dir.text().strip()
        if not base or not os.path.isdir(base):
            QMessageBox.warning(self, "Missing textures folder", "Please set a valid PCSX2 textures folder path.")
            return
        # Determine source folder: if selected item is a zip file, extract to a temp dir
        temp_dir = None
        try:
            if os.path.isfile(src) and src.lower().endswith('.zip'):
                temp_dir = os.path.join(self._thumb_cache, "_zip_extract")
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
                os.makedirs(temp_dir, exist_ok=True)
                with zipfile.ZipFile(src, 'r') as z:
                    z.extractall(temp_dir)
                src_folder = temp_dir
            else:
                src_folder = src

            # Find replacements or image root inside src_folder
            chosen = None
            # direct replacements subfolder
            repl = os.path.join(src_folder, 'replacements')
            if os.path.isdir(repl):
                chosen = self._find_replacements_in_tree(repl) or repl
            else:
                chosen = self._find_replacements_in_tree(src_folder) or src_folder

            if not chosen:
                QMessageBox.information(self, "No images", "Could not find replacement images inside the selected pack.")
                return

            # Determine target folder name: prefer detected Serial code where possible
            display = sel[0].text(0)
            # Try to extract a serial from the display text first
            m = SERIAL_RE.search(display or '')
            serial_candidate = m.group(0).upper() if m else None
            # Also scan chosen folder for serial-like names
            if not serial_candidate:
                for root, dirs, files in os.walk(chosen):
                    for nm in dirs + files:
                        mm = SERIAL_RE.search(nm)
                        if mm:
                            serial_candidate = mm.group(0).upper()
                            break
                    if serial_candidate:
                        break

            if self.target_folder_name.text().strip():
                target_name = self.target_folder_name.text().strip()
            elif serial_candidate:
                target_name = serial_candidate
            else:
                # fallback to basename of display
                target_name = os.path.basename(display)
            if '/' in target_name or '\\' in target_name:
                target_name = os.path.basename(target_name)

            dst = os.path.join(base, target_name)
            # copy chosen content into dst (replace if exists)
            if os.path.exists(dst):
                if QMessageBox.question(self, 'Overwrite', f'Target exists: {dst}\nReplace it?') != QMessageBox.StandardButton.Yes:
                    return
                shutil.rmtree(dst)
            shutil.copytree(chosen, dst)
            QMessageBox.information(self, 'Installed', f'Installed pack into:\n{dst}')
            self.scan_installed_textures()
        except Exception as e:
            QMessageBox.critical(self, 'Install failed', str(e))
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try: shutil.rmtree(temp_dir)
                except Exception: pass

    def _open_selected_pack(self):
        sel = self.packs_list.selectedItems()
        if not sel:
            return
        p = sel[0].data(0, Qt.UserRole)
        if os.name == 'nt':
            subprocess.Popen(['explorer', os.path.normpath(p)])
        else:
            subprocess.Popen(['xdg-open', p])

    def _show_matched_for_selected(self):
        sel = self.packs_list.selectedItems()
        if not sel:
            return
        it = sel[0]
        # matched HTML stored in UserRole+1
        try:
            snippet = it.data(0, Qt.UserRole + 1) or ''
        except Exception:
            snippet = ''
        dlg = QDialog(self)
        dlg.setWindowTitle('Matched HTML for pack')
        v = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(snippet or '(no matched HTML stored)')
        v.addWidget(txt)
        b = QPushButton('Close')
        b.clicked.connect(dlg.accept)
        v.addWidget(b)
        dlg.exec()

    def _resolve_all_packs(self):
        # Collect unresolved serials from the list and run ResolveWorker in bulk
        keys = []
        item_map = {}
        for i in range(self.packs_list.topLevelItemCount()):
            itm = self.packs_list.topLevelItem(i)
            if not itm: continue
            title_col = (itm.text(1) or '').strip()
            if title_col:
                continue
            display = itm.text(0) or ''
            cand = None
            m = SERIAL_RE.search(display)
            if m:
                cand = m.group(0).upper().strip()
            else:
                try:
                    p = itm.data(0, Qt.UserRole)
                    if isinstance(p, str):
                        m2 = SERIAL_RE.search(os.path.basename(p))
                        if m2:
                            cand = m2.group(0).upper().strip()
                except Exception:
                    cand = None
            if cand:
                if cand not in keys:
                    keys.append(cand)
                item_map.setdefault(cand, []).append(itm)

        if not keys:
            QMessageBox.information(self, 'Resolve All', 'No unresolved serial-named packs found.')
            return

        # Prepare expanded variants
        expanded = []
        for k in keys:
            if not k: continue
            variants = [k, k.upper(), norm_serial_key(k), k.replace('-', ''), k.replace('-', '').upper()]
            for v in variants:
                if v and v not in expanded:
                    expanded.append(v)

        local_map = getattr(self.parent.cheats_tab, 'mapping', {}) or {}
        use_bundled = True
        try_online = False
        try:
            try_online = bool(getattr(self.parent.cheats_tab, 'chk_online', None) and self.parent.cheats_tab.chk_online.isChecked()) and (requests is not None)
        except Exception:
            try_online = False

        worker = ResolveWorker(keys=list(expanded), local_map=local_map, use_bundled_lists=use_bundled, try_online=try_online)

        def _on_resolved(out: Dict[str, str]):
            try:
                logger.debug(f"[TexturesTab.resolve_all] resolver returned: {out}")
            except Exception:
                pass
            for cand, items in item_map.items():
                picked = None
                html_snip = None
                candidates_to_check = [cand, cand.upper(), norm_serial_key(cand), cand.replace('-', ''), cand.replace('-', '').upper()]
                for ck in candidates_to_check:
                    if not ck: continue
                    if ck in out:
                        picked = out[ck]
                        break
                if not picked:
                    for ck in candidates_to_check:
                        if (ck + '_CRC') in out:
                            crc = out[ck + '_CRC']
                            if crc in out:
                                picked = out[crc]
                                break
                # Grab html snippet if provided
                for ck in candidates_to_check:
                    key_html = ck + '_HTML'
                    if key_html in out:
                        html_snip = out[key_html]
                        break

                if isinstance(picked, str) and picked.strip().upper() in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
                    picked = None

                if picked:
                    for it in items:
                        try:
                            it.setText(1, picked)
                            tt = it.toolTip(0) or it.data(0, Qt.UserRole) or ''
                            it.setToolTip(0, f"{tt}\n{picked}")
                            if html_snip:
                                it.setData(0, Qt.UserRole + 1, html_snip)
                        except Exception:
                            pass
                    try:
                        self.parent.cheats_tab.mapping[cand.upper()] = picked
                        try:
                            self.parent.cheats_tab.save_mapping()
                        except Exception:
                            pass
                    except Exception:
                        pass
                else:
                    # leave unresolved
                    pass

        worker.resolved.connect(_on_resolved)
        try:
            self.parent.cheats_tab._start_worker(worker)
        except Exception:
            self._start_worker(worker)

    def _remove_selected_pack(self):
        sel = self.packs_list.selectedItems()
        if not sel:
            return
        p = sel[0].data(0, Qt.UserRole)
        ok = QMessageBox.question(self, 'Remove Pack', f'Remove installed pack folder?\n{p}')
        if ok == QMessageBox.StandardButton.Yes:
            try:
                shutil.rmtree(p)
                self.scan_installed_textures()
            except Exception as e:
                QMessageBox.critical(self, 'Remove failed', str(e))

    def _suggest_crc_from_logs(self) -> Optional[str]:
        # Read emuLog.txt for last CRC = 0xXXXXXXXX
        logs_dir = self.parent.settings_tab.paths.get("logs", "")
        if not logs_dir or not os.path.isdir(logs_dir):
            return None
        log_path = os.path.join(logs_dir, 'emuLog.txt')
        if not os.path.isfile(log_path):
            # try recent logs
            candidates = [os.path.join(logs_dir, f) for f in os.listdir(logs_dir) if f.lower().endswith('.txt')]
            candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            for p in candidates:
                m = self._scan_crc_in_file(p)
                if m: return m
            return None
        return self._scan_crc_in_file(log_path)

    @staticmethod
    def _scan_crc_in_file(p: str) -> Optional[str]:
        try:
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    m = re.search(r"CRC\s*=\s*0x([0-9A-Fa-f]{8})", line)
                    if m: return m.group(1).upper()
        except Exception:
            return None
        return None


class SettingsTab(QWidget):
    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self.paths: Dict[str, str] = {}
        self._build_ui()

    def _build_ui(self):
        # Create a scroll area for the entire tab content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        
        # Create a container widget for all content
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG)
        layout.setSpacing(theme.SPACING_MD)
        
        # Main settings
        grp = QGroupBox("PCSX2 Installation")
        fl = QFormLayout(grp)
        self.user_dir = QLineEdit()
        self.user_dir.setToolTip("The main PCSX2 user data folder")
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.clicked.connect(self._browse)
        self.btn_detect = QPushButton("Auto-detect")
        self.btn_detect.setToolTip("Automatically find your PCSX2 folder")
        self.btn_detect.clicked.connect(self._detect)
        fl.addRow("User folder:", self._row(self.user_dir, self.btn_browse, self.btn_detect))
        layout.addWidget(grp)

        # Detected subfolders (simplified, collapsible)
        subgrp = QGroupBox("Detected Folders")
        subgrp.setCheckable(True)
        subgrp.setChecked(True)  # Expand by default to show detected paths
        fl2 = QFormLayout(subgrp)
        self.cheats_label = QLabel("")
        self.cheatsws_label = QLabel("")
        self.textures_label = QLabel("")
        self.logs_label = QLabel("")
        fl2.addRow("Cheats:", self.cheats_label)
        fl2.addRow("Cheats WS:", self.cheatsws_label)
        fl2.addRow("Textures:", self.textures_label)
        fl2.addRow("Logs:", self.logs_label)
        layout.addWidget(subgrp)

        # Quick actions
        quick_grp = QGroupBox("Quick Actions")
        quick_layout = QVBoxLayout()
        
        self.btn_enable_cheats = QPushButton("Enable Cheats in PCSX2")
        self.btn_enable_cheats.setMinimumHeight(35)
        self.btn_enable_cheats.setToolTip("Automatically enable cheats in PCSX2.ini")
        self.btn_enable_cheats.clicked.connect(self._toggle_cheats_ini)
        
        self.btn_enable_textures = QPushButton("Enable Texture Replacement")
        self.btn_enable_textures.setMinimumHeight(35)
        self.btn_enable_textures.setToolTip("Automatically enable texture replacement in PCSX2.ini")
        self.btn_enable_textures.clicked.connect(self._toggle_textures_ini)
        
        quick_layout.addWidget(self.btn_enable_cheats)
        quick_layout.addWidget(self.btn_enable_textures)
        quick_grp.setLayout(quick_layout)
        layout.addWidget(quick_grp)

        # Advanced integrations (collapsible)
        cfg = QGroupBox("Advanced Integrations")
        cfg.setCheckable(True)
        cfg.setChecked(False)
        cfgl = QFormLayout(cfg)
        
        self.pcsx2_exe = QLineEdit()
        self.pcsx2_exe.setPlaceholderText("Path to pcsx2.exe (optional)")
        self.pcsx2_exe.setToolTip("PCSX2 executable for quick launch")
        self.pcsx2_exe.editingFinished.connect(self._save_pcsx2_exe)
        btn_pcsx2 = QPushButton("Browse…")
        btn_pcsx2.clicked.connect(lambda: self._pick_file(self.pcsx2_exe))
        self.btn_launch = QPushButton("Launch PCSX2")
        self.btn_launch.clicked.connect(self._launch_pcsx2)

        cfgl.addRow("PCSX2 exe:", self._row(self.pcsx2_exe, btn_pcsx2, self.btn_launch))
        layout.addWidget(cfg)

        # Profiles (collapsible)
        prof = QGroupBox("Game Profiles")
        prof.setCheckable(True)
        prof.setChecked(False)
        prof.setToolTip("Save game configurations for quick access")
        pfl = QVBoxLayout(prof)
        
        profile_form = QWidget()
        profile_form_layout = QFormLayout(profile_form)
        self.profile_title = QLineEdit()
        self.profile_serial = QLineEdit()
        self.profile_crc = QLineEdit()
        profile_form_layout.addRow("Title:", self.profile_title)
        profile_form_layout.addRow("Serial:", self.profile_serial)
        profile_form_layout.addRow("CRC:", self.profile_crc)
        pfl.addWidget(profile_form)
        
        profile_btns = QWidget()
        profile_btns_layout = QHBoxLayout(profile_btns)
        profile_btns_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_profile_save = QPushButton("Save Profile")
        self.btn_profile_save.clicked.connect(self._save_profile)
        self.btn_profile_export = QPushButton("Export")
        self.btn_profile_export.clicked.connect(self._export_profiles)
        self.btn_profile_import = QPushButton("Import")
        self.btn_profile_import.clicked.connect(self._import_profiles)
        profile_btns_layout.addWidget(self.btn_profile_save)
        profile_btns_layout.addWidget(self.btn_profile_export)
        profile_btns_layout.addWidget(self.btn_profile_import)
        pfl.addWidget(profile_btns)
        
        self.profiles_list = QListWidget()
        self.profiles: Dict[str, Dict] = {}
        self.profiles_list.itemSelectionChanged.connect(self._load_selected_profile)
        pfl.addWidget(self.profiles_list)
        
        layout.addWidget(prof)

        layout.addStretch(1)
        
        # Set the container as the scroll area's widget
        scroll.setWidget(container)
        
        # Set the scroll area as the main layout for this tab
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

        self._load_settings()

    def _row(self, *widgets):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        for wd in widgets:
            h.addWidget(wd)
        h.addStretch(1)
        return w

    def _pick_file(self, line: QLineEdit):
        p, _ = QFileDialog.getOpenFileName(self, "Select file", os.path.expanduser("~"), "All files (*.*)")
        if p:
            line.setText(p)
            if line is self.pcsx2_exe:
                self._save_pcsx2_exe()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select PCSX2 user directory", self.user_dir.text() or os.path.expanduser("~"))
        if d:
            self.user_dir.setText(d)
            self._update_subs()

    def _detect(self):
        guesses = default_pcsx2_user_dirs()
        base = guesses[0] if guesses else os.path.join(os.path.expanduser("~"), "Documents", "PCSX2")
        self.user_dir.setText(base)
        self._update_subs()

    def _update_subs(self):
        base = self.user_dir.text().strip()
        self.paths = ensure_subdirs(base)
        self.cheats_label.setText(self.paths["cheats"])
        self.cheatsws_label.setText(self.paths["cheats_ws"])
        self.textures_label.setText(self.paths["textures"])
        self.logs_label.setText(self.paths["logs"])
        self.parent.state.pcsx2_paths = self.paths
        self.parent.paths_changed.emit(self.paths)
        self._save_user_dir()

    # --- Persistence (QSettings) ---
    def _qsettings(self) -> QSettings:
        return QSettings('PCSX2-Manager', 'PatchTextureManager')

    def _load_settings(self):
        s = self._qsettings()
        saved_dir = s.value('paths/user_dir', '', str)
        if saved_dir:
            self.user_dir.setText(saved_dir)
            self._update_subs()
        else:
            self._detect()
        saved_exe = s.value('paths/pcsx2_exe', '', str)
        if saved_exe:
            self.pcsx2_exe.setText(saved_exe)
        saved_profiles = s.value('profiles/data', '', str)
        if saved_profiles:
            try:
                self.profiles = json.loads(saved_profiles)
                self._refresh_profiles()
            except Exception:
                pass

    def _save_user_dir(self):
        self._qsettings().setValue('paths/user_dir', self.user_dir.text().strip())

    def _save_pcsx2_exe(self):
        self._qsettings().setValue('paths/pcsx2_exe', self.pcsx2_exe.text().strip())

    def _save_profiles(self):
        try:
            self._qsettings().setValue('profiles/data', json.dumps(self.profiles))
        except Exception:
            pass

    # INI toggles (best-effort; may vary by version)
    def _ini_set_bool(self, ini_path: str, key: str, val: bool):
        try:
            if not os.path.isfile(ini_path): return False
            with open(ini_path, 'r', encoding='utf-8', errors='replace') as f: lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.strip().lower().startswith(key.lower()+"="):
                    lines[i] = f"{key}={'enabled' if val else 'disabled'}\n"
                    found = True
                    break
            if not found:
                lines.append(f"{key}={'enabled' if val else 'disabled'}\n")
            with open(ini_path, 'w', encoding='utf-8') as f: f.writelines(lines)
            return True
        except Exception:
            return False

    def _toggle_cheats_ini(self):
        ini = os.path.join(self.paths.get('inis',''), 'PCSX2.ini')
        ok = self._ini_set_bool(ini, 'EnableCheats', True)
        QMessageBox.information(self, "Cheats", "Cheats enabled." if ok else "Could not modify INI (path/version mismatch).")

    def _toggle_textures_ini(self):
        ini = os.path.join(self.paths.get('inis',''), 'PCSX2.ini')
        ok = self._ini_set_bool(ini, 'EnableTextureReplacement', True)
        QMessageBox.information(self, "Textures", "Texture replacement enabled." if ok else "Could not modify INI (path/version mismatch).")

    def _launch_pcsx2(self):
        exe = self.pcsx2_exe.text().strip()
        if not exe:
            QMessageBox.information(self, "PCSX2", "Set pcsx2 executable path first.")
            return
        try:
            subprocess.Popen([exe])
        except Exception as e:
            QMessageBox.critical(self, "Launch error", str(e))

    # Profiles
    def _save_profile(self):
        title = self.profile_title.text().strip()
        serial = self.profile_serial.text().strip().upper()
        crc = (self.profile_crc.text().strip().upper() if HEX8.match(self.profile_crc.text().strip()) else '')
        if not (title or serial or crc):
            QMessageBox.information(self, "Profile", "Provide at least a title, serial or CRC.")
            return
        key = crc or serial or title
        self.profiles[key] = {"title": title, "serial": serial, "crc": crc}
        self._refresh_profiles()
        self._save_profiles()

    def _refresh_profiles(self):
        self.profiles_list.clear()
        for k, v in sorted(self.profiles.items()):
            t = v.get('title') or ''
            s = v.get('serial') or ''
            c = v.get('crc') or ''
            self.profiles_list.addItem(QListWidgetItem(f"{t}  [{s}]  ({c})"))

    def _load_selected_profile(self):
        idx = self.profiles_list.currentRow()
        if idx < 0: return
        key = list(sorted(self.profiles.keys()))[ idx ]
        v = self.profiles[key]
        self.profile_title.setText(v.get('title',''))
        self.profile_serial.setText(v.get('serial',''))
        self.profile_crc.setText(v.get('crc',''))
        # Also push to Cheats tab fields for convenience
        self.parent.cheats_tab.title_edit.setText(v.get('title',''))
        self.parent.cheats_tab.serial_edit.setText(v.get('serial',''))
        self.parent.cheats_tab.crc_edit.setText(v.get('crc',''))

    def _export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Profiles", os.path.expanduser("~"), "JSON (*.json)")
        if not path: return
        try:
            with open(path, 'w', encoding='utf-8') as f: json.dump(self.profiles, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Profiles", "Exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))

    def _import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profiles", os.path.expanduser("~"), "JSON (*.json)")
        if not path: return
        try:
            with open(path, 'r', encoding='utf-8') as f: self.profiles = json.load(f)
            self._refresh_profiles()
            self._save_profiles()

            QMessageBox.information(self, "Profiles", "Imported.")
        except Exception as e:
            QMessageBox.critical(self, "Import error", str(e))


class ResizableFrame(QWidget):
    """Outer frame for the frameless MainWindow. Draws the visible window border
    and lets the user resize by dragging its edges: we just tell Qt which edge
    via QWindow.startSystemResize() and the OS window manager does the rest, so
    native resize behavior (cursors, snapping) keeps working despite the
    frameless hint.
    """

    MARGIN = theme.RESIZE_MARGIN

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(theme.OBJ_APP_FRAME)
        self.setMouseTracking(True)

    def _edge_at(self, pos):
        r = self.rect()
        m = self.MARGIN
        edge = Qt.Edge(0)
        if pos.y() <= m:
            edge |= Qt.TopEdge
        if pos.y() >= r.height() - m:
            edge |= Qt.BottomEdge
        if pos.x() <= m:
            edge |= Qt.LeftEdge
        if pos.x() >= r.width() - m:
            edge |= Qt.RightEdge
        return edge if edge else None

    _CURSORS = {
        Qt.TopEdge: Qt.SizeVerCursor,
        Qt.BottomEdge: Qt.SizeVerCursor,
        Qt.LeftEdge: Qt.SizeHorCursor,
        Qt.RightEdge: Qt.SizeHorCursor,
        Qt.TopEdge | Qt.LeftEdge: Qt.SizeFDiagCursor,
        Qt.BottomEdge | Qt.RightEdge: Qt.SizeFDiagCursor,
        Qt.TopEdge | Qt.RightEdge: Qt.SizeBDiagCursor,
        Qt.BottomEdge | Qt.LeftEdge: Qt.SizeBDiagCursor,
    }

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            edge = self._edge_at(e.position().toPoint())
            if edge:
                wh = self.window().windowHandle()
                if wh:
                    wh.startSystemResize(edge)
                    return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        edge = self._edge_at(e.position().toPoint())
        self.setCursor(self._CURSORS.get(edge, Qt.ArrowCursor))
        super().mouseMoveEvent(e)


class TitleBar(QWidget):
    """Custom-drawn, draggable title bar replacing the native OS chrome."""

    def __init__(self, window: 'MainWindow'):
        super().__init__(window)
        self._window = window
        self.setObjectName(theme.OBJ_TITLE_BAR)
        self.setFixedHeight(theme.TITLE_BAR_HEIGHT)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(4)

        icon_label = QLabel()
        icon_label.setPixmap(QIcon("logo.png").pixmap(18, 18))
        layout.addWidget(icon_label)

        title_label = QLabel("PCSX2 Manager")
        title_label.setObjectName(theme.OBJ_TITLE_BAR_LABEL)
        layout.addWidget(title_label)

        self.btn_menu = self._make_button("menu", "Menu")
        self.btn_menu.setPopupMode(QToolButton.InstantPopup)
        self.btn_menu.setMenu(self._window.build_app_menu())
        layout.addWidget(self.btn_menu)

        layout.addStretch(1)

        self.btn_settings = self._make_button("settings", "Settings")
        self.btn_settings.clicked.connect(self._window.open_settings_dialog)
        layout.addWidget(self.btn_settings)

        self.btn_min = self._make_button("minimize", "Minimize")
        self.btn_min.clicked.connect(self._window.showMinimized)
        layout.addWidget(self.btn_min)

        self.btn_max = self._make_button("maximize", "Maximize")
        self.btn_max.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.btn_max)

        self.btn_close = self._make_button("close", "Close")
        self.btn_close.setObjectName(theme.OBJ_TITLE_BAR_CLOSE_BUTTON)
        self.btn_close.clicked.connect(self._window.close)
        layout.addWidget(self.btn_close)

    def _make_button(self, icon_name, tooltip):
        b = QToolButton()
        b.setIcon(icons.tab_icon(icon_name))
        b.setToolTip(tooltip)
        b.setObjectName(theme.OBJ_TITLE_BAR_BUTTON)
        b.setFixedSize(30, 26)
        b.setCursor(Qt.ArrowCursor)
        return b

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
            self.btn_max.setIcon(icons.tab_icon("maximize"))
        else:
            self._window.showMaximized()
            self.btn_max.setIcon(icons.tab_icon("restore"))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            wh = self._window.windowHandle()
            if wh:
                if e.position().y() <= theme.RESIZE_MARGIN:
                    wh.startSystemResize(Qt.TopEdge)
                else:
                    wh.startSystemMove()
                return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(e)


def read_iso_serial(path: str) -> Optional[str]:
    """Read the PS2 serial directly out of an ISO9660 disc image's SYSTEM.CNF
    (the boot file every PS2 disc has, containing e.g. "BOOT2 = cdrom0:\\SLUS_205.46;1").

    This is the fallback for the very common case where the filename doesn't
    embed the serial at all (many "clean" ROM sets are named by title only, e.g.
    "Grand Theft Auto - San Andreas (USA).iso"). Implemented as a minimal,
    read-only ISO9660 primary-volume-descriptor + root-directory walk -- no new
    dependency. Only handles plain 2048-byte-sector .iso images (not raw
    2352-byte .bin or compressed .chd/.cso); returns None on any failure.
    """
    try:
        with open(path, 'rb') as f:
            f.seek(16 * 2048)
            pvd = f.read(2048)
            if len(pvd) < 2048 or pvd[1:6] != b'CD001':
                return None
            root_record = pvd[156:156 + 34]
            root_lba = int.from_bytes(root_record[2:6], 'little')
            root_size = int.from_bytes(root_record[10:14], 'little')
            if root_size <= 0 or root_size > 10 * 1024 * 1024:
                return None

            f.seek(root_lba * 2048)
            root_data = f.read(root_size)
            system_cnf = None
            i = 0
            while i < len(root_data):
                rec_len = root_data[i]
                if rec_len == 0:
                    i = ((i // 2048) + 1) * 2048
                    continue
                if rec_len < 33 or i + rec_len > len(root_data):
                    break
                rec = root_data[i:i + rec_len]
                id_len = rec[32]
                name = rec[33:33 + id_len].decode('ascii', errors='ignore').upper()
                if name.startswith('SYSTEM.CNF'):
                    system_cnf = {
                        'lba': int.from_bytes(rec[2:6], 'little'),
                        'size': int.from_bytes(rec[10:14], 'little'),
                    }
                    break
                i += rec_len

            if not system_cnf or not (0 < system_cnf['size'] <= 65536):
                return None
            f.seek(system_cnf['lba'] * 2048)
            content = f.read(system_cnf['size']).decode('ascii', errors='ignore')
            m = re.search(r'([A-Za-z]{4})_(\d{3})\.(\d{2})', content)
            if m:
                return f"{m.group(1).upper()}-{m.group(2)}{m.group(3)}"
    except Exception as e:
        logger.debug(f"[read_iso_serial] Failed to read {path}: {e}")
    return None


class GameScanWorker(QThread):
    """Walks a folder for PS2 disc images and extracts each one's serial.

    Tries the filename first (fast, e.g. "SLUS-20946 - Title.iso"); if that
    doesn't contain a serial, falls back to reading SYSTEM.CNF directly out of
    plain .iso images via read_iso_serial(). .bin/.chd/.cso files without a
    filename serial are skipped -- reading their content would need raw-sector
    or decompression handling this v1 doesn't have.
    """

    progressed = Signal(int, int)
    finished = Signal(list, int)  # entries, total disc images found (before serial resolution)

    GAME_EXTS = ('.iso', '.bin', '.chd', '.cso')

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self.folder = folder

    def run(self):
        paths = []
        try:
            for root, _dirs, files in os.walk(self.folder):
                for fn in files:
                    if fn.lower().endswith(self.GAME_EXTS):
                        paths.append(os.path.join(root, fn))
        except Exception as e:
            logger.error(f"[GameScanWorker] Failed to walk {self.folder}: {e}")

        total = max(1, len(paths))
        entries: List[GameEntry] = []
        seen = set()

        for i, path in enumerate(paths, 1):
            fname = os.path.basename(path)
            serial = None
            m = SERIAL_RE.search(fname)
            if m:
                serial = m.group(0).upper().replace('_', '-').replace(' ', '-')
            elif path.lower().endswith('.iso'):
                serial = read_iso_serial(path)
            if serial and serial not in seen:
                seen.add(serial)
                title = bundled_lookup_title(serial) or os.path.splitext(fname)[0]
                entries.append(GameEntry(serial=serial, title=title, crc=None, source_path=path))
            self.progressed.emit(i, total)

        self.finished.emit(entries, len(paths))


def _entry_to_dict(g: GameEntry) -> dict:
    return {"serial": g.serial, "title": g.title, "crc": g.crc, "source_path": g.source_path}


def _dict_to_entry(d: dict) -> GameEntry:
    return GameEntry(
        serial=d.get('serial', ''),
        title=d.get('title', ''),
        crc=d.get('crc'),
        source_path=d.get('source_path'),
    )


class GameListItemWidget(QWidget):
    """Row widget for the library list: a small disc icon + title + serial,
    used via QListWidget.setItemWidget() instead of plain single-line text."""

    def __init__(self, title: str, serial: str):
        super().__init__()
        self.setObjectName(theme.OBJ_GAME_ROW)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SPACING_SM, theme.SPACING_XS, theme.SPACING_SM, theme.SPACING_XS)
        lay.setSpacing(theme.SPACING_SM)

        icon_label = QLabel()
        icon_label.setPixmap(icons.tab_icon("disc").pixmap(20, 20))
        icon_label.setFixedSize(20, 20)
        lay.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        title_label = QLabel(title or serial)
        title_label.setObjectName(theme.OBJ_GAME_ROW_TITLE)
        serial_label = QLabel(serial)
        serial_label.setObjectName(theme.OBJ_MUTED_LABEL)
        text_col.addWidget(title_label)
        text_col.addWidget(serial_label)
        lay.addLayout(text_col, 1)


class LibraryView(QWidget):
    """The main screen: your scanned game library on the left, and on the
    right a cover-art detail panel with a one-click "Sync" for the selected
    game's cheats and textures. Replaces the old Cheats/Textures/Bulk Scanner
    tabs as the primary flow.
    """

    LIBRARY_STORE = os.path.join(os.path.expanduser("~"), ".pcsx2_manager_library.json")
    COVER_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".pcsx2_manager_thumbs")

    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self._shutting_down = False
        self._workers: List[QThread] = []
        self.games: Dict[str, GameEntry] = {}
        self._cover_generation = 0

        self._build_ui()
        self._load_library()
        self._refresh_list()

    # ---- UI ----
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG, theme.SPACING_LG)
        root.setSpacing(theme.SPACING_LG)

        left_widget = QWidget()
        left_widget.setObjectName(theme.OBJ_SIDEBAR)
        left_widget.setMinimumWidth(300)
        left_widget.setMaximumWidth(380)
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(theme.SPACING_MD, theme.SPACING_MD, theme.SPACING_MD, theme.SPACING_MD)
        left.setSpacing(theme.SPACING_SM)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(theme.SPACING_SM)
        self.btn_scan = QPushButton("Scan Folder…")
        self.btn_scan.clicked.connect(self._scan_folder)
        self.btn_add = QPushButton("Add Game…")
        toolbar.addWidget(self.btn_scan)
        toolbar.addWidget(self.btn_add)
        self.btn_add.clicked.connect(self._add_game_manually)
        left.addLayout(toolbar)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search your library…")
        self.search_box.textChanged.connect(self._refresh_list)
        left.addWidget(self.search_box)

        self.library_count_label = QLabel("")
        self.library_count_label.setObjectName(theme.OBJ_MUTED_LABEL)
        left.addWidget(self.library_count_label)

        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        left.addWidget(self.scan_progress)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(2)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        left.addWidget(self.list_widget, 1)

        root.addWidget(left_widget)

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(theme.SPACING_MD)

        hero = QHBoxLayout()
        hero.setSpacing(theme.SPACING_LG)

        cover_stack_widget = QWidget()
        cover_stack_widget.setFixedSize(theme.COVER_WIDTH, theme.COVER_HEIGHT)
        cover_stack = QStackedLayout(cover_stack_widget)
        cover_stack.setStackingMode(QStackedLayout.StackAll)
        cover_stack.setContentsMargins(0, 0, 0, 0)

        self.cover_label = QLabel()
        self.cover_label.setObjectName(theme.OBJ_COVER_FRAME)
        self.cover_label.setFixedSize(theme.COVER_WIDTH, theme.COVER_HEIGHT)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setScaledContents(False)
        cover_stack.addWidget(self.cover_label)

        self.cover_loading_label = QLabel("Loading cover…")
        self.cover_loading_label.setObjectName(theme.OBJ_OVERLAY_LABEL)
        self.cover_loading_label.setFixedSize(theme.COVER_WIDTH, theme.COVER_HEIGHT)
        self.cover_loading_label.setAlignment(Qt.AlignCenter)
        self.cover_loading_label.setVisible(False)
        cover_stack.addWidget(self.cover_loading_label)

        hero.addWidget(cover_stack_widget, 0, Qt.AlignTop)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(theme.SPACING_XS)
        hero_text.addStretch(1)

        self.detail_title = QLabel("Select a game from your library")
        self.detail_title.setObjectName(theme.OBJ_HERO_TITLE)
        self.detail_title.setWordWrap(True)
        f = self.detail_title.font()
        f.setPointSize(f.pointSize() + 8)
        self.detail_title.setFont(f)
        hero_text.addWidget(self.detail_title)

        self.detail_subtitle = QLabel("Scan a folder or add a game to get started.")
        self.detail_subtitle.setObjectName(theme.OBJ_MUTED_LABEL)
        hero_text.addWidget(self.detail_subtitle)

        hero_text.addSpacing(theme.SPACING_MD)

        status_grp = QGroupBox("Status")
        status_form = QFormLayout(status_grp)
        self.cheats_status_label = QLabel("—")
        self.textures_status_label = QLabel("—")
        status_form.addRow("Cheats:", self.cheats_status_label)
        status_form.addRow("Textures:", self.textures_status_label)
        hero_text.addWidget(status_grp)

        texture_row = QHBoxLayout()
        texture_row.setSpacing(theme.SPACING_SM)
        texture_label = QLabel("Texture pack:")
        texture_label.setObjectName(theme.OBJ_MUTED_LABEL)
        self.texture_pack_combo = QComboBox()
        texture_row.addWidget(texture_label)
        texture_row.addWidget(self.texture_pack_combo, 1)
        self.texture_pack_row = QWidget()
        self.texture_pack_row.setLayout(texture_row)
        self.texture_pack_row.setVisible(False)
        hero_text.addWidget(self.texture_pack_row)

        self.btn_sync = QPushButton("Sync This Game")
        self.btn_sync.setObjectName(theme.OBJ_SUCCESS_BUTTON)
        self.btn_sync.setMinimumHeight(42)
        self.btn_sync.setEnabled(False)
        self.btn_sync.clicked.connect(self._sync_selected)
        hero_text.addWidget(self.btn_sync)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setObjectName(theme.OBJ_MUTED_LABEL)
        hero_text.addWidget(self.result_label)

        hero_text.addStretch(2)
        hero.addLayout(hero_text, 1)
        right.addLayout(hero)
        right.addStretch(1)
        root.addWidget(right_widget, 1)

        self._set_cover_pixmap(create_library_cover_placeholder(""))

    # ---- persistence ----
    def _load_library(self):
        try:
            if os.path.isfile(self.LIBRARY_STORE):
                with open(self.LIBRARY_STORE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for d in data:
                    ge = _dict_to_entry(d)
                    if ge.serial:
                        self.games[ge.serial] = ge
        except Exception as e:
            logger.warning(f"[LibraryView] Failed to load library: {e}")

    def _save_library(self):
        try:
            data = [_entry_to_dict(g) for g in self.games.values()]
            with open(self.LIBRARY_STORE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[LibraryView] Failed to save library: {e}")

    # ---- list ----
    def _refresh_list(self, filter_text: str = ""):
        self.list_widget.clear()
        ft = (filter_text or "").strip().upper()
        self.library_count_label.setText(f"{len(self.games)} game(s) in your library" if self.games else "")
        for serial in sorted(self.games.keys(), key=lambda s: (self.games[s].title or s).upper()):
            g = self.games[serial]
            if ft and ft not in (g.title or "").upper() and ft not in g.serial.upper():
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, g.serial)
            row = GameListItemWidget(g.title, g.serial)
            item.setSizeHint(row.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, row)

    def _selected_game(self) -> Optional[GameEntry]:
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return self.games.get(items[0].data(Qt.UserRole))

    def _set_status(self, label: QLabel, text: str, kind: str = "muted"):
        obj_names = {
            "success": theme.OBJ_STATUS_SUCCESS,
            "warning": theme.OBJ_STATUS_WARNING,
            "error": theme.OBJ_STATUS_ERROR,
        }
        label.setText(text)
        label.setObjectName(obj_names.get(kind, theme.OBJ_MUTED_LABEL))
        label.style().unpolish(label)
        label.style().polish(label)

    def _on_selection_changed(self):
        game = self._selected_game()
        if not game:
            self.btn_sync.setEnabled(False)
            self.detail_title.setText("Select a game from your library")
            self.detail_subtitle.setText("Scan a folder or add a game to get started.")
            self._set_status(self.cheats_status_label, "—")
            self._set_status(self.textures_status_label, "—")
            self.result_label.setText("")
            self.texture_pack_row.setVisible(False)
            self._set_cover_pixmap(create_library_cover_placeholder(""))
            self.parent.state.current_game = None
            self.parent.current_game_changed.emit(None)
            return
        self.detail_title.setText(game.title or game.serial)
        subtitle = game.serial + (f"   ·   CRC {game.crc}" if game.crc else "")
        self.detail_subtitle.setText(subtitle)
        self._set_status(self.cheats_status_label, "Not synced yet")
        self._set_status(self.textures_status_label, "Not synced yet")
        self.result_label.setText("")
        self.btn_sync.setEnabled(True)

        self.texture_pack_combo.clear()
        options = get_texture_pack_options(game.serial)
        for opt in options:
            self.texture_pack_combo.addItem(opt.get('name') or opt.get('github_repo') or 'Texture pack', opt)
        self.texture_pack_row.setVisible(bool(options))

        self._load_cover(game)

        self.parent.state.current_game = game
        self.parent.current_game_changed.emit(game)

    # ---- cover art ----
    def _set_cover_pixmap(self, pm: QPixmap):
        if not pm or pm.isNull():
            self.cover_label.clear()
            return
        w, h = theme.COVER_WIDTH, theme.COVER_HEIGHT
        scaled = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        if scaled.width() > w or scaled.height() > h:
            x = max(0, (scaled.width() - w) // 2)
            y = max(0, (scaled.height() - h) // 2)
            scaled = scaled.copy(x, y, w, h)
        self.cover_label.setPixmap(scaled)

    def _load_cover(self, game: GameEntry):
        self._cover_generation += 1
        gen = self._cover_generation
        serial_key = norm_serial_key(game.serial)

        try:
            os.makedirs(self.COVER_CACHE_DIR, exist_ok=True)
        except Exception:
            pass
        cache_path = os.path.join(self.COVER_CACHE_DIR, f"cover_{serial_key}.jpg")

        self.cover_loading_label.setVisible(False)

        if os.path.isfile(cache_path):
            pm = QPixmap(cache_path)
            if pm and not pm.isNull():
                self._set_cover_pixmap(pm)
                return

        self._set_cover_pixmap(create_library_cover_placeholder(game.serial))
        candidates = build_cover_candidates(game.serial)
        if not candidates:
            return

        self.cover_loading_label.setVisible(True)
        worker = CoverFetchWorker(candidates, cache_path, parent=self)

        def _on_fetched(path):
            if gen != self._cover_generation:
                return  # selection moved on since this fetch started
            self.cover_loading_label.setVisible(False)
            pm = QPixmap(path)
            if pm and not pm.isNull():
                self._set_cover_pixmap(pm)
            else:
                self._set_cover_pixmap(create_library_cover_placeholder(game.serial, found=False))

        def _on_failed():
            if gen != self._cover_generation:
                return
            self.cover_loading_label.setVisible(False)
            self._set_cover_pixmap(create_library_cover_placeholder(game.serial, found=False))

        worker.fetched.connect(_on_fetched)
        worker.fetch_failed.connect(_on_failed)
        self._start_worker(worker)

    # ---- scanning ----
    def _scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select your games folder", os.path.expanduser("~"))
        if not folder:
            return
        self.scan_progress.setVisible(True)
        self.scan_progress.setRange(0, 0)
        self.btn_scan.setEnabled(False)
        worker = GameScanWorker(folder, parent=self)
        worker.progressed.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_finished)
        self._start_worker(worker)

    def _on_scan_progress(self, current, total):
        self.scan_progress.setRange(0, total)
        self.scan_progress.setValue(current)

    def _on_scan_finished(self, entries, total_files):
        self.scan_progress.setVisible(False)
        self.btn_scan.setEnabled(True)
        added = 0
        for g in entries:
            if g.serial not in self.games:
                self.games[g.serial] = g
                added += 1
        self._save_library()
        self._refresh_list(self.search_box.text())

        if total_files == 0:
            msg = "No disc images (.iso/.bin/.chd/.cso) were found in that folder."
        elif not entries:
            msg = (f"Found {total_files} disc image(s) in that folder, but couldn't determine "
                   f"a serial for any of them (filename has no serial, and reading SYSTEM.CNF "
                   f"didn't work for .bin/.chd/.cso -- only plain .iso is supported for that).")
        else:
            msg = f"Found {total_files} disc image(s) in that folder, added {added} new to your library."
        QMessageBox.information(self, "Scan Complete", msg)

    # ---- manual add ----
    def _add_game_manually(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Game")
        lay = QFormLayout(dlg)
        serial_edit = QLineEdit()
        serial_edit.setPlaceholderText("e.g. SLUS-20946")
        title_edit = QLineEdit()
        title_edit.setPlaceholderText("Optional -- looked up automatically if left blank")
        lay.addRow("Serial:", serial_edit)
        lay.addRow("Title:", title_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addRow(btns)
        if dlg.exec() != QDialog.Accepted:
            return

        m = SERIAL_RE.search(serial_edit.text().strip())
        if not m:
            QMessageBox.warning(self, "Invalid Serial", "Enter a valid PS2 serial, e.g. SLUS-20946.")
            return
        serial = m.group(0).upper().replace('_', '-').replace(' ', '-')
        title = title_edit.text().strip() or bundled_lookup_title(serial) or serial
        self.games[serial] = GameEntry(serial=serial, title=title, crc=None, source_path=None)
        self._save_library()
        self._refresh_list(self.search_box.text())

    # ---- sync ----
    def _preview_sync(self, game: GameEntry, paths: dict) -> str:
        """Describe what "Sync This Game" is actually about to do, without doing
        any of it -- shown in a confirmation dialog so nothing installs as a
        surprise. Local-only checks (no extra network calls beyond what a normal
        sync would make anyway)."""
        lines = []
        cheats_dir = paths.get('cheats', '')
        textures_dir = paths.get('textures', '')

        local = find_local_cheats(game.serial)
        if local:
            title, crc, cheats = local
            if self._cheats_already_installed(cheats_dir, crc):
                lines.append("Cheats: already installed -- will be left unchanged.")
            elif cheats:
                lines.append(
                    f"Cheats: {len(cheats)} code(s) from the local database will be "
                    f"written to cheats\\{crc.upper()}.pnach."
                )
            else:
                lines.append("Cheats: found in the local database, but it has no codes listed.")
        else:
            lines.append(
                "Cheats: not in the local database -- will search online sources "
                "(GameHacking.org, PSXDataCenter) instead."
            )

        chosen_entry = self.texture_pack_combo.currentData() if self.texture_pack_combo.count() else None
        if not textures_dir or not os.path.isdir(textures_dir):
            lines.append("Textures: PCSX2 textures folder isn't set -- nothing will be installed.")
        else:
            existing_dir = os.path.join(textures_dir, game.serial)
            if os.path.isdir(existing_dir) and os.listdir(existing_dir):
                lines.append("Textures: already installed -- will be left unchanged.")
            elif chosen_entry:
                lines.append(
                    f"Textures: \"{chosen_entry.get('name')}\" will be downloaded from "
                    f"{chosen_entry.get('github_repo')} and installed to textures\\{game.serial}\\."
                )
            else:
                lines.append("Textures: no pack found in the community index for this game.")
        return "\n\n".join(lines)

    def _sync_selected(self):
        game = self._selected_game()
        if not game:
            return
        paths = self.parent.state.pcsx2_paths or {}
        cheats_dir = paths.get('cheats', '')
        if not cheats_dir or not os.path.isdir(cheats_dir):
            QMessageBox.warning(self, "PCSX2 Folder Not Set", "Set your PCSX2 folder in Settings (gear icon) first.")
            return

        preview = self._preview_sync(game, paths)
        reply = QMessageBox.question(
            self, f"Sync {game.title or game.serial}?",
            preview + "\n\nExisting installs are never overwritten. Proceed?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        self.btn_sync.setEnabled(False)
        self.result_label.setText("Syncing…")
        QApplication.processEvents()

        cheats_msg = self._sync_cheats(game, cheats_dir)
        textures_msg = self._sync_textures(game, paths.get('textures', ''))

        self.btn_sync.setEnabled(True)
        self.result_label.setText(f"Cheats: {cheats_msg}\nTextures: {textures_msg}")

    @staticmethod
    def _cheats_already_installed(cheats_dir: str, crc: str) -> bool:
        return bool(crc) and os.path.isfile(os.path.join(cheats_dir, f"{crc.upper()}.pnach"))

    def _sync_cheats(self, game: GameEntry, cheats_dir: str) -> str:
        try:
            local = find_local_cheats(game.serial)
            if local:
                title, crc, cheats = local
                if crc:
                    game.crc = crc
                if self._cheats_already_installed(cheats_dir, crc):
                    self._set_status(self.cheats_status_label, "Already installed", "warning")
                    return "already installed -- left your existing .pnach unchanged"
                if not cheats:
                    self._set_status(self.cheats_status_label, "No codes in local database")
                    return "no codes in the local database"
                write_cheats_pnach(title, game.serial, crc, cheats, cheats_dir)
                self._set_status(self.cheats_status_label, f"{len(cheats)} code(s) installed", "success")
                self._save_library()
                return f"installed {len(cheats)} code(s) from the local database"

            results = fetch_and_cache_cheats(game.serial) or []
            codes = [
                {'name': entry.get('title') or entry.get('source', 'Cheat'),
                 'description': entry.get('source', ''),
                 'codes': entry['codes']}
                for entry in results if entry.get('codes')
            ]
            if not codes:
                self._set_status(self.cheats_status_label, "Not found")
                return "no cheats found (local database or online)"
            crc = game.crc or ''
            if not crc:
                self._set_status(self.cheats_status_label, "Found online, but no CRC available", "warning")
                return "found online, but couldn't determine a CRC to install with"
            if self._cheats_already_installed(cheats_dir, crc):
                self._set_status(self.cheats_status_label, "Already installed", "warning")
                return "already installed -- left your existing .pnach unchanged"
            write_cheats_pnach(game.title, game.serial, crc, codes, cheats_dir)
            self._set_status(self.cheats_status_label, f"{len(codes)} code(s) installed", "success")
            return f"installed {len(codes)} code(s) from online sources"
        except Exception as e:
            self._set_status(self.cheats_status_label, "Error", "error")
            logger.error(f"[LibraryView] Cheats sync failed for {game.serial}: {e}")
            return f"error -- {e}"

    def _sync_textures(self, game: GameEntry, textures_dir: str) -> str:
        if not textures_dir or not os.path.isdir(textures_dir):
            self._set_status(self.textures_status_label, "Textures folder not set", "warning")
            return "PCSX2 textures folder not set"
        if requests is None:
            self._set_status(self.textures_status_label, "Not found")
            return "no texture-pack lookup available (requests not installed)"

        # perform_pack_installs() unconditionally replaces an existing target
        # folder (textures_install.py's dst = os.path.join(base, target_hint));
        # a one-click sync must never silently wipe an already-installed pack.
        existing_dir = os.path.join(textures_dir, game.serial)
        if os.path.isdir(existing_dir) and os.listdir(existing_dir):
            self._set_status(self.textures_status_label, "Already installed", "warning")
            return "already installed -- left your existing pack unchanged"

        try:
            chosen_entry = self.texture_pack_combo.currentData() if self.texture_pack_combo.count() else None
            if chosen_entry:
                resolved = resolve_texture_release_asset(chosen_entry)
            else:
                resolved = resolve_texture_pack_url(game.serial)
            if not resolved or not resolved[2]:
                self._set_status(self.textures_status_label, "Not found")
                return "no pack found in the community index"
            display_name, repo, download_url = resolved

            tmp_dir = os.path.join(os.path.expanduser('~'), '.pcsx2_manager_tmp')
            os.makedirs(tmp_dir, exist_ok=True)
            local_zip = os.path.join(tmp_dir, f"{game.serial}_texture_pack.zip")
            resp = requests.get(download_url, timeout=60, stream=True)
            resp.raise_for_status()
            with open(local_zip, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)

            from textures_install import perform_pack_installs
            installed, failures = perform_pack_installs([(display_name, local_zip)], textures_dir, target_hint=game.serial)
            try:
                os.remove(local_zip)
            except Exception:
                pass

            if installed:
                self._set_status(self.textures_status_label, f"Installed ({display_name})", "success")
                return f"installed '{display_name}' from {repo}"
            msg = failures[0][2] if failures else "install failed"
            self._set_status(self.textures_status_label, "Install failed", "error")
            return f"found a pack but install failed -- {msg}"
        except Exception as e:
            self._set_status(self.textures_status_label, "Error", "error")
            logger.error(f"[LibraryView] Textures sync failed for {game.serial}: {e}")
            return f"error -- {e}"

    # ---- worker bookkeeping (matches CheatsTab/TexturesTab pattern) ----
    def _start_worker(self, worker: QThread):
        if getattr(self, '_shutting_down', False):
            return
        worker.setParent(self)
        self._workers.append(worker)

        def _cleanup():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            worker.deleteLater()
        worker.finished.connect(_cleanup)
        worker.start()


class MainWindow(QMainWindow):
    # Shared state signals: tabs subscribe instead of reaching into each other directly.
    paths_changed = Signal(dict)          # emitted with the latest PCSX2 paths dict
    current_game_changed = Signal(object)  # emitted with a GameEntry (or None)

    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.setWindowTitle("PCSX2 Manager")
        self.setWindowIcon(QIcon("logo.png"))
        self.resize(1100, 750)
        self.setMinimumSize(760, 480)

        # Custom-drawn title bar (TitleBar/ResizableFrame above). On Windows we keep
        # the window fully native (see nativeEvent()) so Snap/shadow/rounded-corners
        # keep working; elsewhere FramelessWindowHint + manual drag/resize is used.
        if not IS_WINDOWS:
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        # Apply the shared dark theme (see theme.py for tokens/QSS)
        self.setStyleSheet(theme.DARK_QSS)

        frame = ResizableFrame(self)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(theme.RESIZE_MARGIN, 0, theme.RESIZE_MARGIN, theme.RESIZE_MARGIN)
        outer.setSpacing(0)

        self.title_bar = TitleBar(self)
        outer.addWidget(self.title_bar)

        # These are no longer shown as tabs (see LibraryView) but stay alive,
        # unparented until opened, for the Advanced dialogs and existing
        # paths_changed/current_game_changed signal wiring in their __init__.
        self.cheats_tab = CheatsTab(self)
        self.textures_tab = TexturesTab(self)
        self.settings_tab = SettingsTab(self)

        self.library_view = LibraryView(self)
        outer.addWidget(self.library_view, 1)

        self.setCentralWidget(frame)

        self.setAcceptDrops(True)

        # Show welcome message on first run
        self._show_welcome_if_needed()

    # ---- Windows native chrome: keep Snap/shadow while hiding the native title bar ----
    def nativeEvent(self, eventType, message):
        if IS_WINDOWS and eventType == b'windows_generic_MSG':
            try:
                msg = _MSG.from_address(int(message))
            except Exception:
                return super().nativeEvent(eventType, message)

            if msg.message == WM_NCCALCSIZE:
                if msg.wParam:
                    try:
                        if self.isMaximized():
                            # Replicate the inset Windows normally applies so a maximized
                            # window doesn't hang off-screen / over the taskbar -- we're
                            # claiming the whole rect as client area, so nothing else does
                            # this for us automatically.
                            params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
                            border = (ctypes.windll.user32.GetSystemMetrics(SM_CXFRAME)
                                      + ctypes.windll.user32.GetSystemMetrics(SM_CXPADDEDBORDER))
                            params.rgrc[0].left += border
                            params.rgrc[0].top += border
                            params.rgrc[0].right -= border
                            params.rgrc[0].bottom -= border
                    except Exception:
                        pass
                    return True, 0
            elif msg.message == WM_NCHITTEST:
                try:
                    handled, result = self._win_hit_test(msg.lParam)
                    if handled:
                        return True, result
                except Exception:
                    pass
        return super().nativeEvent(eventType, message)

    def _win_hit_test(self, lparam):
        """Translate a WM_NCHITTEST screen point into resize-edge/caption regions
        so Windows handles drag-move (with Snap) and edge-resize natively, even
        though there's no visible native title bar."""
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        pos = self.mapFromGlobal(QPoint(x, y))
        w, h = self.width(), self.height()
        m = theme.RESIZE_MARGIN

        if not self.isMaximized():
            left = pos.x() < m
            right = pos.x() > w - m
            top = pos.y() < m
            bottom = pos.y() > h - m
            if top and left:
                return True, HT_TOPLEFT
            if top and right:
                return True, HT_TOPRIGHT
            if bottom and left:
                return True, HT_BOTTOMLEFT
            if bottom and right:
                return True, HT_BOTTOMRIGHT
            if left:
                return True, HT_LEFT
            if right:
                return True, HT_RIGHT
            if top:
                return True, HT_TOP
            if bottom:
                return True, HT_BOTTOM

        tb = self.title_bar
        tb_origin = tb.mapTo(self, QPoint(0, 0))
        local = QPoint(pos.x() - tb_origin.x(), pos.y() - tb_origin.y())
        if 0 <= local.x() <= tb.width() and 0 <= local.y() <= tb.height():
            child = tb.childAt(local)
            if isinstance(child, QToolButton):
                return False, HT_CLIENT
            return True, HT_CAPTION
        return False, HT_CLIENT

    def open_settings_dialog(self):
        self._open_widget_dialog(self.settings_tab, "Settings", size=(640, 700))

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        # Pass-through: if it's pnach, hand to Cheats; else textures or codes
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pnach'):
                self.cheats_tab.dropEvent(e)
                break
            else:
                self.textures_tab.dropEvent(e)
                break

    def build_app_menu(self) -> QMenu:
        """Menu shown from the title bar's hamburger button, replacing the
        native QMainWindow menu bar so the custom title bar is the only header."""
        menu = QMenu(self)
        about_act = QAction("About", self)
        about_act.triggered.connect(self._about)
        menu.addAction(about_act)
        menu.addSeparator()

        cheats_act = QAction("Advanced Cheat Editor…", self)
        cheats_act.triggered.connect(self.open_advanced_cheats)
        menu.addAction(cheats_act)
        textures_act = QAction("Advanced Texture Manager…", self)
        textures_act.triggered.connect(self.open_advanced_textures)
        menu.addAction(textures_act)
        menu.addSeparator()

        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        menu.addAction(exit_act)
        return menu

    def _open_widget_dialog(self, widget: QWidget, title: str, size=(900, 700)):
        """Host an existing tab widget (Cheats/Textures/Settings) in a one-off
        modal dialog, then detach it back so it survives to be reopened."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(*size)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        dlg.exec()
        lay.removeWidget(widget)
        widget.setParent(self)

    def open_advanced_cheats(self):
        game = self.state.current_game
        if game:
            self.cheats_tab.title_edit.setText(game.title or "")
            self.cheats_tab.serial_edit.setText(game.serial or "")
            self.cheats_tab.crc_edit.setText(game.crc or "")
        self._open_widget_dialog(self.cheats_tab, "Advanced Cheat Editor")

    def open_advanced_textures(self):
        self._open_widget_dialog(self.textures_tab, "Advanced Texture Manager")

    def _about(self):
        QMessageBox.information(
            self,
            "About PCSX2 Manager",
            "<h2>PCSX2 Manager</h2>"
            "<p><b>Version 2.0</b></p>"
            "<p>A simplified tool for managing PCSX2 cheats and texture packs.</p>"
            "<br>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>Scan a folder to build your game library</li>"
            "<li>One-click cheat + texture pack sync per game</li>"
            "<li>Region-correct cheat installation with an online database</li>"
            "<li>Drag & drop support</li>"
            "</ul>"
            "<br>"
            "<p><i>Tip: Click the gear icon in the title bar for Settings.</i></p>"
        )

    def _show_welcome_if_needed(self):
        """Show welcome dialog on first run"""
        settings = QSettings('PCSX2-Manager', 'PatchTextureManager')
        if not settings.value('welcome_shown', False):
            msg = QMessageBox(self)
            msg.setWindowTitle("Welcome to PCSX2 Manager!")
            msg.setTextFormat(Qt.RichText)
            msg.setText(
                "<h2>Welcome!</h2>"
                "<p>This tool helps you easily add cheats and texture packs to PCSX2.</p>"
                "<br>"
                "<p><b>Quick Start:</b></p>"
                "<ol>"
                "<li>Click the gear icon and verify your PCSX2 folder</li>"
                "<li>Use <b>Scan Folder</b> to add the games you own to your library</li>"
                "<li>Select a game and click <b>Sync</b> to install its cheats and textures</li>"
                "</ol>"
                "<br>"
                "<p><i>Tip: You can drag & drop .pnach files and texture packs!</i></p>"
            )
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            settings.setValue('welcome_shown', True)

    def _cleanup_workers(self, tab, timeout_ms=1000):
        """Helper to clean up workers for a given tab."""
        if not hasattr(tab, '_workers'):
            return

        for worker in list(tab._workers):
            try:
                if not worker.isRunning():
                    continue

                # Request graceful quit
                worker.quit()
                if worker.wait(timeout_ms):
                    continue  # Successfully quit

                # Force terminate if still running
                logger.warning(f"Force terminating worker: {worker.__class__.__name__}")
                worker.terminate()
                worker.wait(500)  # Give terminate a moment
            except RuntimeError as e:
                # Worker already deleted
                logger.debug(f"Worker cleanup: {e}")
            except Exception as e:
                logger.error(f"Error cleaning up worker: {e}")

    def closeEvent(self, event):
        """Clean up all running threads before closing."""
        logger.info("Application closing - cleaning up workers...")

        # Set shutdown flags to prevent new workers
        for tab_name in ['cheats_tab', 'textures_tab', 'library_view']:
            if hasattr(self, tab_name):
                tab = getattr(self, tab_name)
                tab._shutting_down = True

        # Clean up workers in each widget
        for tab_name in ['cheats_tab', 'textures_tab', 'library_view']:
            if hasattr(self, tab_name):
                self._cleanup_workers(getattr(self, tab_name))

        logger.info("Worker cleanup complete")
        event.accept()



def main():
    QCoreApplication.setOrganizationName("PCSX2-Manager")
    QCoreApplication.setApplicationName("PatchTextureManager")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("logo.png"))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
