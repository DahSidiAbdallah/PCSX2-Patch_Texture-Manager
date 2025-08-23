#!/usr/bin/env python3

import os
import sys
import re
import json
import shutil
import zipfile
import subprocess
import tempfile

from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QTabWidget, QVBoxLayout,
    QHBoxLayout, QFormLayout, QLineEdit, QTextEdit, QPushButton, QLabel,
    QMessageBox, QListWidget, QListWidgetItem, QGroupBox, QCheckBox, QComboBox,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QSpinBox, QDialog
)
from PySide6.QtWidgets import QRadioButton
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QInputDialog
from PySide6.QtCore import QThread, Signal, Qt, QSettings, QTimer
from PySide6.QtGui import QPixmap, QIcon, QDragEnterEvent, QDropEvent, QAction, QPainter, QColor
from PySide6.QtWidgets import QSizePolicy
import concurrent.futures

# Optional for online features elsewhere; not required for offline resolver
try:
    import requests  # optional for certain lookups
except Exception:
    requests = None


# Online cheat database integration
from cheat_online import fetch_and_cache_cheats
from bs4 import BeautifulSoup

# ---------------------------- Helpers / Model ----------------------------

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

    def __post_init__(self):
        if self.serials is None:
            self.serials = []
        if self.raw_pairs is None:
            self.raw_pairs = []
        if self.comments is None:
            self.comments = []


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
        if requests is None:
            try:
                print("[CoverFetchWorker] requests not available; aborting cover fetch")
            except Exception:
                pass
            self.fetch_failed.emit()
            return

        # Try each candidate URL in order. Use HEAD first when possible to avoid downloading 404 HTML.
        for candidate in self.urls:
            if not candidate:
                continue
            try:
                try:
                    print(f"[CoverFetchWorker] probing: {candidate}")
                except Exception:
                    pass
                # Prefer HEAD to check existence; fall back to GET if server doesn't honor HEAD
                ok = False
                try:
                    resp = requests.head(candidate, timeout=8)
                    status = getattr(resp, 'status_code', None)
                    if status == 200:
                        ok = True
                    else:
                        # Some GitHub raw endpoints don't respond to HEAD reliably; we'll try GET below
                        ok = False
                except Exception:
                    ok = False

                if not ok:
                    # Try GET directly
                    resp = requests.get(candidate, timeout=12)
                    status = getattr(resp, 'status_code', None)
                    content = getattr(resp, 'content', None) or b''
                    clen = len(content)
                    try:
                        print(f"[CoverFetchWorker] response: status={status} content_len={clen} for {candidate}")
                    except Exception:
                        pass
                    if status == 200 and content:
                        # write to cache and emit
                        try:
                            try:
                                os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                            except Exception:
                                pass
                            with open(self.cache_path, 'wb') as fh:
                                fh.write(content)
                            try:
                                print(f"[CoverFetchWorker] wrote cache: {self.cache_path} (from {candidate})")
                            except Exception:
                                pass
                            # Persist successful candidate basename into an index next to the cache folder
                            try:
                                idx_dir = os.path.dirname(self.cache_path)
                                idx_file = os.path.join(idx_dir, 'index.json')
                                key = os.path.splitext(os.path.basename(candidate))[0]
                                data = {}
                                if os.path.isfile(idx_file):
                                    try:
                                        with open(idx_file, 'r', encoding='utf-8') as inf:
                                            data = json.load(inf)
                                    except Exception:
                                        data = {}
                                data[key] = candidate
                                try:
                                    with open(idx_file, 'w', encoding='utf-8') as outf:
                                        json.dump(data, outf)
                                except Exception:
                                    pass
                            except Exception:
                                pass
                            self.fetched.emit(self.cache_path)
                            return
                        except Exception as e:
                            try:
                                print(f"[CoverFetchWorker] write failed: {e}")
                            except Exception:
                                pass
                            self.fetch_failed.emit()
                            return
                    else:
                        # try next candidate
                        continue
                else:
                    # HEAD returned 200; perform GET to fetch content
                    try:
                        resp = requests.get(candidate, timeout=12)
                        status = getattr(resp, 'status_code', None)
                        content = getattr(resp, 'content', None) or b''
                        clen = len(content)
                        try:
                            print(f"[CoverFetchWorker] got: status={status} content_len={clen} for {candidate}")
                        except Exception:
                            pass
                        if status == 200 and content:
                            try:
                                try:
                                    os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                                except Exception:
                                    pass
                                with open(self.cache_path, 'wb') as fh:
                                    fh.write(content)
                                try:
                                    print(f"[CoverFetchWorker] wrote cache: {self.cache_path} (from {candidate})")
                                except Exception:
                                    pass
                                self.fetched.emit(self.cache_path)
                                return
                            except Exception as e:
                                try:
                                    print(f"[CoverFetchWorker] write failed: {e}")
                                except Exception:
                                    pass
                                self.fetch_failed.emit()
                                return
                        else:
                            continue
                    except Exception:
                        continue
            except Exception:
                continue

        # All candidates exhausted
        try:
            print(f"[CoverFetchWorker] all candidates failed: {self.urls}")
        except Exception:
            pass
        self.fetch_failed.emit()


def norm_serial_key(s: str) -> str:
    return (s or "").upper().replace("-", "").replace("_", "").replace(" ", "")


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
                    cand = t.get_text(' ', strip=True)
                    # ignore unhelpful placeholders
                    if cand and cand.strip() and cand.upper() not in ('INFO','TITLE','N/A','UNKNOWN') and re.search(r'[A-Za-z]', cand):
                        title = cand
                if not title:
                    # fallback: pick the best td text in the row excluding the serial cell
                    candidates = []  # list of (text, html)
                    for ctd in tr.find_all('td'):
                        ctxt = ctd.get_text(' ', strip=True)
                        if not ctxt: continue
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
            pd.raw_pairs.append((m.group(1).upper(), m.group(3).upper().rjust(8, "0")))
        else:
            # Skip empty lines
            if not line.strip():
                continue
            # Skip title lines (already captured earlier)
            if TITLE_LINE.match(line):
                continue
            # Preserve comment or metadata lines (including bracket headers or key=value lines)
            # Keep original leading comment markers (//, #, ;) and formatting; strip only trailing newlines/spaces
            pd.comments.append(line.rstrip())
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
    # --- AI-based label generation for each cheat group ---
    import re
    
    def ai_label_for_group(label_hint, codes, inline_hints=None, used_labels=None):
        used_labels = used_labels or set()
        # Use comment if it's meaningful
        if label_hint and not re.match(r"^(patch|cheat|code|modifier|fix|enable|disable|on|off|1|2|3|4|5|6|7|8|9|0| )+$", label_hint, re.I):
            label = label_hint.strip()
            if label not in used_labels:
                used_labels.add(label)
                return label
        # Use inline comment if present and meaningful
        if inline_hints:
            for hint in inline_hints:
                if hint and not re.match(r"^(patch|cheat|code|modifier|fix|enable|disable|on|off|1|2|3|4|5|6|7|8|9|0| )+$", hint, re.I):
                    label = hint.strip()
                    if label not in used_labels:
                        used_labels.add(label)
                        return label
        # Try to infer from code patterns and keywords
        code_text = " ".join(f"{a} {v}" for a,v in codes)
        patterns = [
            # Gameplay/character (expanded synonyms)
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
            # Address/value hints (common cheat code address/value patterns)
            (r"^20[0-9A-F]{6}", "Simple 8-bit Patch"),
            (r"^10[0-9A-F]{6}", "16-bit Patch"),
            (r"^00[0-9A-F]{6}", "8-bit Patch"),
            (r"^E0[0-9A-F]{6}", "Conditional Patch"),
            (r"^D0[0-9A-F]{6}", "Conditional Patch"),
            (r"^2[0-9A-F]{7}", "Write Patch"),
            (r"^1[0-9A-F]{7}", "Write Patch"),
            (r"^0[0-9A-F]{7}", "Write Patch"),
        ]
        for pat, name in patterns:
            if re.search(pat, code_text, re.I):
                if name not in used_labels:
                    used_labels.add(name)
                    return name
        # Fallback: summarize by address/value
        if len(codes) == 1:
            a, v = codes[0]
            label = f"Patch {a[-6:]}={v[-6:]}"
            if label not in used_labels:
                used_labels.add(label)
                return label
        # Ensure unique fallback
        n = len(used_labels) + 1
        label = f"Cheat Group {n} ({len(codes)} codes)"
        used_labels.add(label)
        return label

    # Robust grouping: split by blank lines, comment headers, or contiguous patch lines
    lines = []
    if pd.comments:
        lines.extend(pd.comments)
    for addr, val in pd.raw_pairs:
        lines.append((addr, val))

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

    for item in lines:
        if isinstance(item, str):
            m = re.match(r"\s*(//|#|;)\s*([^:]+):?", item)
            if m:
                flush_group()
                current_label = m.group(2).strip()
            elif item.strip() == "":
                flush_group()
        elif isinstance(item, tuple):
            addr, val = item
            # Check for inline comment as hint
            hint = None
            m = re.search(r"//(.+)$", val)
            if m:
                hint = m.group(1).strip()
                val = val.split("//")[0].strip()
            current_group.append((addr, val))
            inline_hints.append(hint)
    flush_group()

    used_labels = set()
    if not groups:
        # fallback: all codes in one group
        label = ai_label_for_group(pd.title, pd.raw_pairs, used_labels=used_labels)
        out.append(f"[Cheats/{label}]")
        for addr, val in pd.raw_pairs:
            out.append(f"patch=1,EE,{addr},extended,{val}")
    else:
        for idx, (label, codes, hints) in enumerate(groups, 1):
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
            found_html = None
            found_title_html = None
            # Try local HTML bundles
            if not title and self.use_bundled_lists and k:
                title = psx_map.get(k_norm) or psx_map.get(k)
            if not crc and self.use_bundled_lists and k:
                crc = psx_crc_map.get(k_norm) or psx_crc_map.get(k)

            # Online lookup if requested and something missing
            if self.try_online and k and (not title or not crc):
                HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PCSX2-Manager/1.0)"}
                serial_variants = [k, k_norm]
                url_templates = [
                    'https://psxdatacenter.com/ps2/ntscu2.html',
                    'https://psxdatacenter.com/ps2/pal2.html',
                    'https://psxdatacenter.com/ps2/ntscj2.html',
                ]
                found_title = None
                found_crc = None

                def scan_page(html: str):
                    nonlocal found_title, found_crc, found_html, found_title_html
                    U = html.upper()
                    for sv in serial_variants:
                        pos = U.find(sv.upper())
                        if pos == -1:
                            pos = U.find(sv.upper().replace('-', '').replace('_', ''))
                        if pos != -1:
                            window = html[max(0, pos-4000): pos+4000]
                            mcrc = CRC_IN_TEXT.search(window)
                            if mcrc and not found_crc:
                                found_crc = normalize_crc(mcrc.group(1))
                            m = re.search(r'<td[^>]*class=["\']col2["\'][^>]*>.*?(%s).*?</td>\s*<td[^>]*class=["\']col3["\'][^>]*>(.*?)</td>' % re.escape(sv), window, flags=re.IGNORECASE | re.DOTALL)
                            if m and not found_title:
                                cand_html = m.group(2)
                                cand = BeautifulSoup(cand_html, 'html.parser').get_text(strip=True)
                                if cand and len(cand) > 3 and cand.upper() not in ('INFO','TITLE','N/A','UNKNOWN') and re.search(r'[A-Za-z]', cand):
                                    found_title = cand
                                    found_html = m.group(0)
                                    found_title_html = cand_html
                            if not found_title:
                                m2 = re.search(r'<td[^>]*class=["\']col6["\'][^>]*>.*?(%s).*?</td>\s*<td[^>]*class=["\']col7["\'][^>]*>(.*?)</td>' % re.escape(sv), window, flags=re.IGNORECASE | re.DOTALL)
                                if m2:
                                    cand_html = m2.group(2)
                                    cand = BeautifulSoup(cand_html, 'html.parser').get_text(strip=True)
                                    if cand and len(cand) > 3 and cand.upper() not in ('INFO','TITLE','N/A','UNKNOWN') and re.search(r'[A-Za-z]', cand):
                                        found_title = cand
                                        found_html = m2.group(0)
                                        found_title_html = cand_html
                            if not found_title:
                                # Try table-row based extraction: find the <tr> that contains the serial and pick nearby cells/links
                                soup = BeautifulSoup(window, 'html.parser')
                                sv_u = sv.upper()
                                picked = None
                                picked_html = None
                                candidates = []
                                for tr in soup.find_all('tr'):
                                    tr_txt = tr.get_text(' ', strip=True).upper()
                                    if sv_u in tr_txt or sv_u.replace('-', '') in tr_txt:
                                        # prefer col with title-like text: look for <td class=col3> or any <a> text
                                        td3 = tr.find('td', attrs={'class': re.compile(r'col3', re.I)})
                                        if td3:
                                            cand_html = str(td3)
                                            cand = td3.get_text(' ', strip=True)
                                            if cand and len(cand) > 3 and cand.upper() not in ('INFO','TITLE','N/A','UNKNOWN') and re.search(r'[A-Za-z]', cand):
                                                picked = cand
                                                picked_html = cand_html
                                                break
                                        # try any link text in this row
                                        a = tr.find('a')
                                        if a and a.get_text(strip=True):
                                            cand_html = str(a)
                                            cand = a.get_text(' ', strip=True)
                                            if len(cand) > 3 and cand.upper() not in ('INFO','TITLE','N/A','UNKNOWN') and re.search(r'[A-Za-z]', cand):
                                                picked = cand
                                                picked_html = cand_html
                                                break
                                        # fallback: look at neighboring <td> siblings
                                        tds = tr.find_all('td')
                                        if len(tds) >= 2:
                                            # choose the best td text that's not the serial using scoring
                                            cands = [td.get_text(' ', strip=True) for td in tds]
                                            cands = [c for c in cands if c and sv_u not in c.upper()]
                                            if cands:
                                                # cands are td texts; find the original td HTML to give context
                                                td_elements = tr.find_all('td')
                                                html_candidates = []
                                                for td in td_elements:
                                                    ctxt = td.get_text(' ', strip=True)
                                                    if ctxt and sv_u not in ctxt.upper():
                                                        html_candidates.append((ctxt, str(td)))
                                                if html_candidates:
                                                    scored = [(_score_title_candidate(text, html), text, html) for (text, html) in html_candidates]
                                                else:
                                                    scored = [(_score_title_candidate(c), c, None) for c in cands]
                                                scored.sort(reverse=True)
                                                cand = scored[0][1]
                                                if cand and len(cand) > 3 and cand.upper() not in ('INFO','TITLE','N/A','UNKNOWN'):
                                                    picked = cand
                                                    picked_html = str(tr)
                                                    break
                                if not picked:
                                    # fallback to searching for nearby plain text tokens after the serial
                                    text = soup.get_text(' ', strip=True)
                                    after = text.upper().split(sv.upper(), 1)[-1] if sv.upper() in text.upper() else text.upper()
                                    chunks = re.split(r'[\|\-\n\r]+', after)
                                    for ch in chunks:
                                        c = ch.strip()
                                        if not c: continue
                                        if SERIAL_RE.search(c) or CRC_IN_TEXT.search(c):
                                            continue
                                        if len(c) > 3 and c.upper() not in ('INFO','TITLE','N/A','UNKNOWN') and re.search(r'[A-Za-z]', c):
                                            picked = c
                                            picked_html = None
                                            break
                                if picked:
                                    found_title = picked
                                    if picked_html:
                                        found_html = picked_html
                                        found_title_html = picked_html

                if self.try_online and requests is not None:
                    for url in url_templates:
                        try:
                            resp = requests.get(url, headers=HEADERS, timeout=8)
                            if resp.status_code == 200 and resp.text:
                                scan_page(resp.text)
                                if found_title and (found_crc or crc):
                                    break
                        except Exception:
                            continue

                if found_title and not title:
                    title = found_title
                if found_crc and not crc:
                    crc = found_crc

            # include optional matched html if present
            return (k, title, crc, found_title_html or found_html)

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
        try:
            print(f"[SingleOnlineLookup] starting lookup for {self.serial}")
        except Exception:
            pass
        if requests is None:
            try:
                print("[SingleOnlineLookup] requests missing, aborting")
            except Exception:
                pass
            self.failed.emit()
            return
        serial = (self.serial or '').strip()
        if not serial:
            self.failed.emit()
            return
        HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PCSX2-Manager/1.0)"}
        serial_variants = [serial, norm_serial_key(serial)]
        url_templates = [
            'https://psxdatacenter.com/ps2/ntscu2.html',
            'https://psxdatacenter.com/ps2/pal2.html',
            'https://psxdatacenter.com/ps2/ntscj2.html',
        ]
        try:
            for url in url_templates:
                try:
                    print(f"[SingleOnlineLookup] fetching {url} for {self.serial}")
                except Exception:
                    pass
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=10)
                except Exception as e:
                    try:
                        print(f"[SingleOnlineLookup] request failed: {e}")
                    except Exception:
                        pass
                    continue
                if resp.status_code != 200 or not resp.text:
                    try:
                        print(f"[SingleOnlineLookup] bad status {resp.status_code} for {url}")
                    except Exception:
                        pass
                    continue
                html = resp.text
                U = html.upper()
                for sv in serial_variants:
                    sv_u = sv.upper()
                    pos = U.find(sv_u)
                    if pos == -1:
                        pos = U.find(sv_u.replace('-', '').replace('_', ''))
                    if pos == -1:
                        continue
                    try:
                        print(f"[SingleOnlineLookup] serial {self.serial} found in page {url} at pos {pos}")
                    except Exception:
                        pass
                    window = html[max(0, pos-3000): pos+3000]
                    # Try to find a title cell via regex for table columns used on PSXDataCenter
                    m = re.search(r'<td[^>]*class=["\']col3["\'][^>]*>(.*?)</td>', window, flags=re.IGNORECASE | re.DOTALL)
                    if m:
                        cand = BeautifulSoup(m.group(1), 'html.parser').get_text(strip=True)
                        if cand and len(cand) > 3 and cand.upper() not in ('INFO', 'TITLE'):
                            try:
                                print(f"[SingleOnlineLookup] candidate title (td col3): {cand}")
                            except Exception:
                                pass
                            self.found.emit(cand)
                            return
                    # fallback: extract nearby plain text after serial
                    soup = BeautifulSoup(window, 'html.parser')
                    text = soup.get_text(' ', strip=True)
                    after = text.upper().split(sv_u, 1)[-1] if sv_u in text.upper() else text.upper()
                    # find candidate chunks (split by ' - ' or punctuation)
                    chunks = re.split(r'[\|\-\n\r]+', after)
                    for ch in chunks:
                        c = ch.strip()
                        if not c: continue
                        # skip tokens that look like serials or headers
                        if SERIAL_RE.search(c) or CRC_IN_TEXT.search(c):
                            continue
                        if len(c) > 3 and c.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
                            # pick the first reasonably long chunk
                            title = BeautifulSoup(c, 'html.parser').get_text(strip=True)
                            if title:
                                try:
                                    print(f"[SingleOnlineLookup] fallback candidate: {title}")
                                except Exception:
                                    pass
                                self.found.emit(title)
                                return
            # nothing found
            self.failed.emit()
        except Exception:
            self.failed.emit()


# ---------------------------- GUI ----------------------------

class CheatsTab(QWidget):
    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self.mapping: Dict[str, str] = {}  # CRC/Serial -> Title
        # persistent mapping store path (auto-load/save)
        self.map_store_path = os.path.join(os.path.expanduser("~"), ".pcsx2_manager_mapping.json")
        # create minimal widgets early so helper methods can use them safely
        self.list = QListWidget()
        self.progress = QProgressBar()
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
        except Exception:
            pass
        self.refresh_list()

    def save_mapping(self, path: Optional[str] = None):
        """Persist the current mapping to a JSON file. If path is provided, use that, else use default store."""
        try:
            outp = path or self.map_store_path
            # write a stable sorted mapping
            with open(outp, 'w', encoding='utf-8') as fh:
                json.dump({k: self.mapping[k] for k in sorted(self.mapping.keys())}, fh, ensure_ascii=False, indent=2)
            # reflect chosen path in UI if user-specified via load
            try:
                if path:
                    self.map_path.setText(outp)
            except Exception:
                pass
            return True
        except Exception:
            return False

    # ---- Worker management to prevent GC / crashes ----
    def _start_worker(self, worker: QThread):
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

    # (Old duplicate preview handler removed)

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
        layout = QVBoxLayout(self)

        # Target directories panel
        self.paths_group = QGroupBox("PCSX2 Folders")
        fl = QFormLayout(self.paths_group)
        self.cheats_dir = QLineEdit()
        self.cheatsws_dir = QLineEdit()
        self.textures_dir = QLineEdit()
        self.btn_browse_cheats = QPushButton("Browse…")
        self.btn_browse_cheats.clicked.connect(lambda: self._pick_dir(self.cheats_dir))
        self.btn_browse_cheatsws = QPushButton("Browse…")
        self.btn_browse_cheatsws.clicked.connect(lambda: self._pick_dir(self.cheatsws_dir))
        self.btn_browse_textures = QPushButton("Browse…")
        self.btn_browse_textures.clicked.connect(lambda: self._pick_dir(self.textures_dir))

        fl.addRow("cheats:", self._row(self.cheats_dir, self.btn_browse_cheats))
        fl.addRow("cheats_ws:", self._row(self.cheatsws_dir, self.btn_browse_cheatsws))
        fl.addRow("textures:", self._row(self.textures_dir, self.btn_browse_textures))
        layout.addWidget(self.paths_group)

        # Import/Build panel
        build_group = QGroupBox("Build / Import PNACH")
        bl = QFormLayout(build_group)
        self.title_edit = QLineEdit()
        self.serial_edit = QLineEdit()
        self.crc_edit = QLineEdit()
        self.crc_edit.setPlaceholderText("8 hex digits, e.g., F4715852")

        self.input_mode = QComboBox()
        self.input_mode.addItems([
            "Paste RAW 8x8 pairs",
            "Open existing .pnach file",
            "Convert non-RAW (Omniconvert)…",
        ])

        self.codes_text = QTextEdit()
        self.codes_text.setPlaceholderText(
            "Paste RAW pairs like:\nXXXXXXXX YYYYYYYY\n…"
        )
        self.btn_open_pnach = QPushButton("Open .pnach…")
        self.btn_open_pnach.clicked.connect(self._open_pnach_file)

        # NEW: open generic codes file
        self.btn_open_codes = QPushButton("Open codes file…")
        self.btn_open_codes.clicked.connect(self._open_codes_file)

        self.btn_make = QPushButton("Generate Preview")
        self.btn_make.clicked.connect(self._generate_preview)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)

        self.btn_save = QPushButton("Save to cheats")
        self.btn_save.clicked.connect(self._save_to_cheats)

        # Online cheat fetch button
        self.btn_fetch_online = QPushButton("Fetch Online Cheats")
        self.btn_fetch_online.setToolTip(
            "Fetch and display cheats from PCSX2 forums, GameHacking.org, and PSXDatacenter for the current Serial/CRC."
        )
        self.btn_fetch_online.clicked.connect(self._fetch_online_cheats)

        # Title Resolver controls
        self.map_path = QLineEdit()
        self.map_path.setPlaceholderText("Load CRC/Serial→Title mapping CSV/JSON…")
        self.btn_load_map = QPushButton("Load mapping…")
        self.btn_load_map.clicked.connect(self._load_mapping)

        # UPDATED: offline wording
        self.chk_offline_lists = QCheckBox(
            "Use bundled PSXDataCenter lists (offline)"
        )
        self.chk_offline_lists.setToolTip(
            "Use locally stored PSXDataCenter HTML lists (ulist2.html / plist2.html / jlist2.html) to expand the mapping without internet."
        )
        self.chk_online = QCheckBox("Also try web lookup (PSXDataCenter)")
        self.chk_online.setToolTip(
            "If checked, we will attempt a quick web lookup on psxdatacenter.com to fill missing title/CRC. Needs internet."
        )
        self.btn_resolve = QPushButton("Resolve Title")
        self.btn_resolve.clicked.connect(self._resolve_title_clicked)
        self.progress.setMinimum(0)
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        self.source_label = QLabel("")
        bl.addRow("Title:", self.title_edit)
        bl.addRow("Serial(s):", self.serial_edit)
        bl.addRow("CRC:", self.crc_edit)
        bl.addRow(
            "Input:",
            self._row(
                self.input_mode, self.btn_open_pnach, self.btn_open_codes, self.btn_fetch_online
            ),
        )
        bl.addRow("Codes / Content:", self.codes_text)
        bl.addRow(self._row(self.btn_make, self.btn_save))
        bl.addRow(QLabel("Title Resolver:"))
        bl.addRow(
            self._row(
                self.map_path,
                self.btn_load_map,
                self.chk_offline_lists,
                self.chk_online,
                self.btn_resolve,
            )
        )
        bl.addRow("Progress:", self.progress)
        bl.addRow("Detected from:", self.source_label)
        bl.addRow("Preview:", self.preview)
        layout.addWidget(build_group)

        # Existing cheats list
        list_group = QGroupBox("Installed PNACH Files")
        v2 = QVBoxLayout(list_group)
        v2.addWidget(self.list)
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.clicked.connect(self.refresh_list)
        v2.addWidget(self.btn_refresh)
        layout.addWidget(list_group)

        # QoL: auto-title when user edits CRC/Serial
        self.serial_edit.textChanged.connect(self._maybe_autotitle)
        self.crc_edit.textChanged.connect(self._maybe_autotitle)

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
        # Try each key, prefer lightweight fetch_and_cache_cheats then fallback to Playwright rendering
        all_results = []
        for key in keys:
            try:
                results = fetch_and_cache_cheats(key)
            except Exception as e:
                results = [{'source': 'error', 'error': str(e)}]
            # If no results, try the Playwright renderer (if available)
            if not results:
                try:
                    # dynamic import to avoid requiring Playwright at startup
                    import importlib, os
                    pw_mod_path = os.path.join(os.path.dirname(__file__), 'playwright_fetch.py')
                    if os.path.isfile(pw_mod_path):
                        # run the helper script in a subprocess to fetch and write cache for this key
                        # We'll call the existing script `playwright_fetch.py` which writes to cheat_cache/<serial>.json
                        import subprocess, sys
                        subprocess.run([sys.executable, pw_mod_path], check=False)
                        # read the cache file if present
                        import json
                        cache_path = os.path.join(os.path.dirname(__file__), 'cheat_cache', f"{key}.json")
                        if os.path.isfile(cache_path):
                            try:
                                with open(cache_path, 'r', encoding='utf-8') as f:
                                    results = json.load(f)
                            except Exception:
                                results = []
                except Exception:
                    pass
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
                    self.input_mode.setCurrentIndex(1)
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
                    self.input_mode.setCurrentIndex(0)
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
        self.cheatsws_dir.setText(paths.get("cheats_ws", ""))
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
            # Pick input mode based on extension
            if path.lower().endswith(".pnach"):
                self.input_mode.setCurrentIndex(1)  # Existing PNACH
            else:
                self.input_mode.setCurrentIndex(0)  # RAW 8x8 pairs (try conversion if needed)
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
            # Pick input mode based on extension
            if path.lower().endswith(".pnach"):
                self.input_mode.setCurrentIndex(1)  # Existing PNACH
            else:
                self.input_mode.setCurrentIndex(0)  # RAW 8x8 pairs (try conversion if needed)
        except Exception as e:
            QMessageBox.warning(self, "Open error", f"Failed to open: {e}")

    # --- Code Conversion ---
    def _convert_with_omniconvert(self, text: str) -> Optional[str]:
        """Optional: call an external Omniconvert CLI if user configured path in Settings.
        Expect it to output RAW pairs that we return as string. Placeholder implementation."""
        exe = self.parent.settings_tab.omniconvert_path.text().strip()
        if not exe or not os.path.isfile(exe):
            return None
        try:
            # Placeholder for future Omniconvert CLI integration.
            return None
        except Exception:
            return None

        # If cache_file was not created and no images found, try to synthesize a tiny placeholder so UI has an icon
        try:
            if not os.path.isfile(cache_file):
                # Create a 64x64 placeholder with a neutral color and key text (if key provided)
                try:
                    pix = QPixmap(64, 64)
                    pix.fill(QColor(200, 200, 200))
                    painter = QPainter(pix)
                    painter.setPen(QColor(120, 120, 120))
                    # draw a simple center rectangle accent
                    painter.drawRect(8, 8, 48, 48)
                    try:
                        # Optionally draw first 4 characters of key
                        if key:
                            text = (key[:4] if len(key) > 0 else '')
                            painter.drawText(12, 36, text)
                    except Exception:
                        pass
                    painter.end()
                    pix.save(cache_file, 'PNG')
                    return cache_file
                except Exception:
                    pass
        except Exception:
            pass

    def _basic_nonraw_to_raw(self, text: str) -> List[Tuple[str,str]]:
        """Very light parser: if lines look like XXXXXXXX YYYYYYYY or XXXXXXXX=YYYYYYYY, treat as RAW.
        This does not convert ARMAX encodings; for that use Omniconvert."""
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

        # Push to UI
        if found_serials:
            self.serial_edit.setText('; '.join(sorted(set(found_serials))))
        if found_crc:
            self.crc_edit.setText(found_crc)

        # Auto-resolve title from mapping
        title = None
        mapping = getattr(self, 'mapping', {}) or {}
        keys_to_try = []
        if found_crc: keys_to_try.append(found_crc)
        keys_to_try.extend(found_serials or [])
        sources = []
        for k in keys_to_try:
            kU = k.upper().strip()
            if kU in mapping:
                title = mapping[kU]
                sources.append("Title: mapping")
                break
            kN = norm_serial_key(kU)
            if kN in mapping:
                title = mapping[kN]
                sources.append("Title: mapping")
                break

        # If still no title and user wants bundled lists, do a quick worker on the side
        if not title and (self.chk_offline_lists.isChecked()) and (found_crc or found_serials):
            def on_done(out):
                picked = None
                for kk in keys_to_try:
                    if kk.upper() in out:
                        picked = out[kk.upper()]
                        break
                if picked:
                    self.title_edit.setText(picked)
                    self.source_label.setText("Title: offline lists")
            worker = ResolveWorker(keys_to_try, mapping, use_bundled_lists=True, try_online=False)
            worker.resolved.connect(on_done)
            self._start_worker(worker)
        elif title:
            self.title_edit.setText(title)
            self.source_label.setText(" | ".join(sources))

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

        mode = self.input_mode.currentIndex()
        if mode == 0:  # RAW -> PNACH
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
        elif mode == 1:  # Existing PNACH -> normalize
            pd = parse_pnach_text(content)
            if title: pd.title = title
            if serials: pd.serials = serials
            if crc: pd.crc = crc
            if not pd.raw_pairs:
                QMessageBox.information(self, "No patch lines", "The .pnach contains no patch lines in 'patch=1,EE,XXXXXXXX,extended,YYYYYYYY' format.")
        else:  # Omniconvert path
            raw_pairs = self._basic_nonraw_to_raw(content)
            if not raw_pairs:
                maybe = self._convert_with_omniconvert(content)
                if maybe:
                    raw_pairs = parse_raw_8x8(maybe)
            if not raw_pairs:
                QMessageBox.information(self, "Conversion needed", "Provide RAW pairs or configure Omniconvert in Settings.")
                return
            pd = PnachData(crc=crc, serials=serials, title=title, raw_pairs=raw_pairs)
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
            QMessageBox.critical(self, "Write failed", str(e))

    def refresh_list(self):
        self.list.clear()
        cheats_dir = self.cheats_dir.text().strip()
        if cheats_dir and os.path.isdir(cheats_dir):
            for name in sorted(os.listdir(cheats_dir)):
                if name.lower().endswith(".pnach"):
                    self.list.addItem(QListWidgetItem(name))

    # QoL: auto-title when user types CRC/Serial
    def _maybe_autotitle(self):
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
            worker.start()

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
        # Thumbnail cache used for installed pack icons
        self._thumb_cache = os.path.join(os.path.expanduser("~"), ".pcsx2_manager_thumbs")
        try:
            os.makedirs(self._thumb_cache, exist_ok=True)
        except Exception:
            pass
        self._build_ui()

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
        layout = QVBoxLayout(self)

        group = QGroupBox("Texture Pack Import")
        fl = QFormLayout(group)
        self.textures_dir = QLineEdit()
        self.btn_browse_textures = QPushButton("Browse…")
        self.btn_browse_textures.clicked.connect(lambda: self._pick_dir(self.textures_dir))

        self.target_folder_name = QLineEdit()
        self.target_folder_name.setPlaceholderText("Prefer the game's   Serial (e.g. SLUS-12345) or a custom folder name")
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

        # Drag & Drop
        self.setAcceptDrops(True)

        # Installed packs list + actions
        packs_group = QGroupBox("Installed Packs")
        pv = QVBoxLayout(packs_group)
        # Use a QTreeWidget with three columns: Folder/Serial, Title, Staging
        self.packs_list = QTreeWidget()
        self.packs_list.setColumnCount(3)
        self.packs_list.setHeaderLabels(["Folder/Serial", "Title", "Staged"])
        # Allow multi-selection for mass-install operations
        self.packs_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.packs_list.itemSelectionChanged.connect(self._on_pack_selected)
        # Context menu for revealing pack paths and staging folder configuration
        self.packs_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.packs_list.customContextMenuRequested.connect(self._packs_context_menu)

        # Layout: left = list, right = preview/metadata
        split_row = QHBoxLayout()
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(0,0,0,0)
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
        self.preview_loading.setStyleSheet('background: rgba(0,0,0,0.6); color: white;')
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
        # Add Resolve All and Show Matched HTML debug buttons
        self.btn_resolve_all = QPushButton("Resolve All")
        self.btn_resolve_all.clicked.connect(self._resolve_all_packs)
        self.btn_show_matched = QPushButton("Show matched HTML")
        self.btn_show_matched.clicked.connect(self._show_matched_for_selected)
        br.addWidget(self.btn_resolve_all)
        br.addWidget(self.btn_show_matched)
        pv.addWidget(btn_row)
        layout.addWidget(packs_group)

        # disable action buttons until a pack is selected
        self.btn_open_pack.setEnabled(False)
        self.btn_install_pack.setEnabled(False)
        self.btn_remove_pack.setEnabled(False)

        # initial scan
        try:
            self.scan_installed_textures()
        except Exception:
            pass

    # ---- Worker management to prevent GC / crashes ----
    def _start_worker(self, worker: QThread):
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
                if thumb:
                    it.setIcon(0, QIcon(thumb))
                self.packs_list.addTopLevelItem(it)

            QMessageBox.information(self, "Imported (staged)", f"Imported ZIP into staging folder:\n{staging}\n\nPacks are available in the list and will be installed only when you click Install.")
        except Exception as e:
            QMessageBox.critical(self, "ZIP error", str(e))

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
        # Confirm bulk install
        if QMessageBox.question(self, 'Install Selected', f'Install {len(items)} selected packs into:\n{base}?') != QMessageBox.StandardButton.Yes:
            return
        # Iterate and call existing install logic per item but avoid repeated confirmations
        for it in items:
            try:
                src = it.data(0, Qt.UserRole)
                if not src:
                    continue
                # use similar logic as _install_selected_pack but non-interactive
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

                    repl = os.path.join(src_folder, 'replacements')
                    if os.path.isdir(repl):
                        chosen = self._find_replacements_in_tree(repl) or repl
                    else:
                        chosen = self._find_replacements_in_tree(src_folder) or src_folder
                    if not chosen:
                        continue
                    # infer target name
                    display = it.text(0)
                    m = SERIAL_RE.search(display or '')
                    serial_candidate = m.group(0).upper() if m else None
                    if not serial_candidate:
                        for root, dirs, files in os.walk(chosen):
                            for nm in dirs + files:
                                mm = SERIAL_RE.search(nm)
                                if mm:
                                    serial_candidate = mm.group(0).upper()
                                    break
                            if serial_candidate: break
                    if self.target_folder_name.text().strip():
                        target_name = self.target_folder_name.text().strip()
                    elif serial_candidate:
                        target_name = serial_candidate
                    else:
                        target_name = os.path.basename(display)
                    target_name = os.path.basename(target_name)
                    dst = os.path.join(base, target_name)
                    if os.path.exists(dst):
                        try:
                            shutil.rmtree(dst)
                        except Exception:
                            continue
                    shutil.copytree(chosen, dst)
                finally:
                    if temp_dir and os.path.exists(temp_dir):
                        try: shutil.rmtree(temp_dir)
                        except Exception: pass
            except Exception:
                continue
        QMessageBox.information(self, 'Installed', f'Installed {len(items)} packs into:\n{base}')
        try:
            self.scan_installed_textures()
        except Exception:
            pass

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
                if thumb:
                    it.setIcon(0, QIcon(thumb))
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

        # find a cover image (first local image) and load scaled pixmap
        pix = None
        try:
            exts = ('.png', '.jpg', '.jpeg', '.bmp', '.tga')
            if pack_dir and os.path.exists(pack_dir):
                for root, _, files in os.walk(pack_dir):
                    for f in files:
                        if f.lower().endswith(exts):
                            pth = os.path.join(root, f)
                            pm = QPixmap(pth)
                            if pm and not pm.isNull():
                                # keep original pixmap; we'll size the label to fit while preserving aspect ratio
                                pix = pm
                                break
                    if pix:
                        break
        except Exception:
            pix = None

        # If no local cover found and we have a serial, try the remote cover URL and cache it (async)
        # Ensure serial is normalized and prefer stored serial when available
        if serial_stored:
            serial_val = serial_stored

        if not pix and serial_val and requests is not None:
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
                            if os.path.isfile(cache_name):
                                pm = QPixmap(cache_name)
                                if pm and not pm.isNull():
                                    _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
                                    return
                            bundled = os.path.join(os.path.dirname(__file__), 'logo.png')
                            if os.path.isfile(bundled):
                                pm = QPixmap(bundled)
                                if pm and not pm.isNull():
                                    _set_label_pixmap_exact(self.preview_cover, pm, max_dim=420)
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
                if thumb:
                    it.setIcon(0, QIcon(thumb))
                try:
                    print(f"[TexturesTab] adding item: display='{display}' title_col='{title_col}' path='{pack_dir}'")
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
                print(f"[TexturesTab] detected serial children under '{base}': {child_dirs}")
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
            if thumb:
                it.setIcon(0, QIcon(thumb))
            try:
                print(f"[TexturesTab] adding item: display='{display}' title_col='{title_col}' path='{pack_dir}'")
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
                print(f"[TexturesTab] scanning child: '{name}' is_dir={os.path.isdir(p)}")
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
                    print(f"[TexturesTab] adding zip item: display='{name}' title_col='{title_col}' path='{p}'")
                except Exception:
                    pass
                self.packs_list.addTopLevelItem(it)
        
                continue

            if not os.path.isdir(p):
                continue

            # If this child folder itself is a serial/CRC folder, prefer to add it as a pack
            try:
                if SERIAL_RE.search(name) or HEX8.match(name):
                    # Diagnostic: list immediate entries to understand folder layout
                    try:
                        entries = os.listdir(p)
                        print(f"[TexturesTab] child entries for '{name}': {entries}")
                    except Exception:
                        entries = []
                    try:
                        has_repl = os.path.isdir(os.path.join(p, 'replacements'))
                        print(f"[TexturesTab] '{name}' has 'replacements' child: {has_repl}")
                    except Exception:
                        pass
                    # Find the best image root (prefer replacements)
                    target = self._find_replacements_in_tree(p) or p
                    print(f"[TexturesTab] _find_replacements_in_tree('{p}') -> {target}")
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
                    if thumb:
                        it.setIcon(0, QIcon(thumb))
                    try:
                        print(f"[TexturesTab] adding serial child item: display='{display}' title_col='{title_col}' path='{target}'")
                    except Exception:
                        pass
                    self.packs_list.addTopLevelItem(it)
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
                    if thumb:
                        it.setIcon(0, QIcon(thumb))
                    try:
                        print(f"[TexturesTab] adding crc-child item: display='{display}' title_col='{title_col}' path='{pack_dir}'")
                    except Exception:
                        pass
                    self.packs_list.addTopLevelItem(it)
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
                if thumb:
                    it.setIcon(0, QIcon(thumb))
                try:
                    print(f"[TexturesTab] adding image-pack item: display='{item_text}' title_col='{title_col}' path='{target}'")
                except Exception:
                    pass
                self.packs_list.addTopLevelItem(it)

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
                                    print(f"[TexturesTab] removing base-as-pack item at index {idx} (path='{pth}')")
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
                        print(f"[TexturesTab] item #{i}: display='{disp}' title_col='{title_col}' path='{data_path}'")
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
                    print(f"[TexturesTab] resolving serial keys: {keys}")
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
                    print(f"[TexturesTab] expanded resolver keys: {expanded_keys}")
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
                        print("[TexturesTab] online lookup enabled for resolver")
                    except Exception:
                        pass

                worker = ResolveWorker(keys=list(expanded_keys), local_map=local_map, use_bundled_lists=use_bundled, try_online=try_online)

                def _on_resolved(out: Dict[str, str]):
                    try:
                        print(f"[TexturesTab] resolver returned: {out}")
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
                                            print(f"[TexturesTab] SingleOnlineLookup failed for {serial}")
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
            cache_file = os.path.join(self._thumb_cache, f"{key}.png")
            if os.path.isfile(cache_file) and (os.path.getmtime(cache_file) > os.path.getmtime(pack_dir)):
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
                print(f"[TexturesTab.resolve_all] resolver returned: {out}")
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


class BulkScanWorker(QThread):
    progressed = Signal(int, int)  # current, total
    scanned = Signal(int, dict)    # row index, result dict (backwards compat)
    scanned_batch = Signal(list)   # list of (row index, result dict)
    finished = Signal()

    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.paths = paths
        # tune worker threads (IO+CPU mixed); cap for responsiveness
        self.max_workers = min(8, (os.cpu_count() or 4))

    def run(self):
        total = len(self.paths)
        results = [None] * total

        def process(i, p):
            res = {"file": p, "serials": "", "crc": "", "title": "", "status": ""}
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                pd = parse_pnach_text(text)
                serials = pd.serials[:]
                crc = pd.crc
                title = pd.title or ""
                if not serials:
                    serials = parse_serials(text)
                if not crc:
                    m = re.search(r"([0-9A-Fa-f]{8})", os.path.basename(p))
                    if m: crc = normalize_crc(m.group(1))
                res = {
                    "file": p,
                    "serials": "; ".join(serials),
                    "crc": crc or "",
                    "title": title,
                    "status": "parsed"
                }
            except Exception as e:
                res = {"file": p, "serials": "", "crc": "", "title": "", "status": f"error: {e}"}
            return (i, res)

        # Use a thread pool to parallelize file parsing and reduce wall time on many files
        batch = []
        batch_size = 20
        processed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(process, idx, path): idx for idx, path in enumerate(self.paths)}
            for fut in concurrent.futures.as_completed(futures):
                idx, res = fut.result()
                results[idx] = res
                batch.append((idx, res))
                processed += 1
                # emit progress as processed/total
                try:
                    self.progressed.emit(processed, total)
                except Exception:
                    pass
                if len(batch) >= batch_size:
                    try:
                        self.scanned_batch.emit(batch[:])
                    except Exception:
                        pass
                    # for backwards compat, also emit individual scanned signals
                    for ii, rr in batch:
                        try:
                            self.scanned.emit(ii, rr)
                        except Exception:
                            pass
                    batch.clear()
        # flush remaining
        if batch:
            try:
                self.scanned_batch.emit(batch[:])
            except Exception:
                pass
            for ii, rr in batch:
                try:
                    self.scanned.emit(ii, rr)
                except Exception:
                    pass
            batch.clear()
        # final progress ensure
        try:
            self.progressed.emit(total, total)
        except Exception:
            pass
        self.finished.emit()


class BulkTab(QWidget):
    """
    Bulk scan a set of files/folders and list:
    File | Serial(s) | CRC | Title | Status
    - Add Files / Add Folder / Clear
    - Scan (parse serial/CRC)
    - Resolve Titles (local mapping + optional offline lists + optional online)
    - Copy Selected / Copy All / Export CSV
    - Load in Cheats (double-click row or button)
    """
    ALLOWED_EXTS = (".pnach", ".txt", ".ini", ".cb", ".cbc", ".rtxt")

    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self.paths: List[str] = []
        self.rows: List[Dict[str, str]] = []  # {"file","serials","crc","title","status"}
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Controls row
        ctrl_row = QWidget()
        h = QHBoxLayout(ctrl_row)
        h.setContentsMargins(0, 0, 0, 0)
        self.btn_add_files = QPushButton("Add Files…")
        self.btn_add_files.clicked.connect(self._add_files)
        self.btn_add_folder = QPushButton("Add Folder…")
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.clicked.connect(self._clear_all)
        self.chk_recurse = QCheckBox("Recurse")
        h.addWidget(self.btn_add_files)
        h.addWidget(self.btn_add_folder)
        h.addWidget(self.btn_clear)
        h.addWidget(self.chk_recurse)
        h.addStretch(1)
        layout.addWidget(ctrl_row)

        # Options row (use Cheats tab settings by default)
        opt = QWidget()
        oh = QHBoxLayout(opt)
        oh.setContentsMargins(0, 0, 0, 0)
        self.chk_offline_lists = QCheckBox("Use bundled PSXDataCenter lists (offline)")
        self.chk_online = QCheckBox("Also try web lookup (PSXDataCenter)")
        # mirror initial state from Cheats tab if available after MainWindow init
        oh.addWidget(self.chk_offline_lists)
        oh.addWidget(self.chk_online)
        oh.addStretch(1)
        layout.addWidget(opt)

        # Search row
        search_bar = QWidget()
        sh = QHBoxLayout(search_bar)
        sh.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search… (supports regex if enabled)")
        self.search_in = QComboBox()
        self.search_in.addItems(["All columns", "File", "Serial(s)", "CRC", "Title", "Status"])
        self.chk_regex = QCheckBox("Regex")
        self.btn_clear_search = QPushButton("Clear")
        self.btn_clear_search.clicked.connect(lambda: self.search_edit.clear())
        sh.addWidget(QLabel("Find:"))
        sh.addWidget(self.search_edit)
        sh.addWidget(self.search_in)
        sh.addWidget(self.chk_regex)
        sh.addWidget(self.btn_clear_search)
        sh.addStretch(1)
        layout.addWidget(search_bar)

        # Debounce timer for search
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filter)
        self.search_edit.textChanged.connect(lambda _: self._search_timer.start(200))
        self.search_in.currentIndexChanged.connect(lambda _: self._apply_filter())
        self.chk_regex.toggled.connect(lambda _: self._apply_filter())

        # Action buttons
        actions = QWidget()
        ah = QHBoxLayout(actions)
        ah.setContentsMargins(0, 0, 0, 0)
        self.btn_scan = QPushButton("Scan")
        self.btn_scan.clicked.connect(self._scan_files)
        self.btn_resolve = QPushButton("Resolve Titles")
        self.btn_resolve.clicked.connect(self._resolve_titles)
        self.btn_copy_sel = QPushButton("Copy Selected")
        self.btn_copy_sel.clicked.connect(self._copy_selected)
        self.btn_copy_all = QPushButton("Copy All")
        self.btn_copy_all.clicked.connect(self._copy_all)
        self.btn_export = QPushButton("Export CSV…")
        self.btn_export.clicked.connect(self._export_csv)
        self.btn_load_cheats = QPushButton("Load in Cheats")
        self.btn_load_cheats.clicked.connect(self._load_selected_into_cheats)
        ah.addWidget(self.btn_scan)
        ah.addWidget(self.btn_resolve)
        ah.addStretch(1)
        ah.addWidget(self.btn_copy_sel)
        ah.addWidget(self.btn_copy_all)
        ah.addWidget(self.btn_export)
        ah.addWidget(self.btn_load_cheats)
        layout.addWidget(actions)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Table
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["File", "Serial(s)", "CRC", "Title", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.doubleClicked.connect(self._load_selected_into_cheats)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # allow user drag-resize
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(40)
        self.table.setColumnWidth(0, 320)  # File
        self.table.setColumnWidth(1, 180)  # Serials
        self.table.setColumnWidth(2, 100)  # CRC
        self.table.setColumnWidth(3, 320)  # Title
        self.table.setColumnWidth(4, 120)  # Status
        layout.addWidget(self.table)

        # Keep the spinbox in sync when user drags the header
        def _on_resized(_logicalIndex, _old, _new):
            if self.col_pick.currentIndex() == _logicalIndex:
                self.col_width.setValue(self.table.columnWidth(_logicalIndex))

        header.sectionResized.connect(_on_resized)

        # Column sizing controls
        size_row = QWidget()
        sz = QHBoxLayout(size_row)
        sz.setContentsMargins(0, 0, 0, 0)
        self.col_pick = QComboBox()
        self.col_pick.addItems(["File", "Serial(s)", "CRC", "Title", "Status"])
        self.col_width = QSpinBox()
        self.col_width.setRange(40, 1500)
        self.col_width.setValue(180)
        btn_minus = QPushButton("–")
        btn_plus = QPushButton("+")
        btn_auto = QPushButton("Auto")
        sz.addWidget(QLabel("Column:"))
        sz.addWidget(self.col_pick)
        sz.addWidget(QLabel("Width:"))
        sz.addWidget(self.col_width)
        sz.addWidget(btn_minus)
        sz.addWidget(btn_plus)
        sz.addWidget(btn_auto)
        sz.addStretch(1)
        layout.addWidget(size_row)

        def _apply_width():
            c = self.col_pick.currentIndex()
            self.table.setColumnWidth(c, int(self.col_width.value()))

        btn_plus.clicked.connect(lambda: self.col_width.setValue(self.col_width.value() + 20))
        btn_minus.clicked.connect(lambda: self.col_width.setValue(max(40, self.col_width.value() - 20)))
        self.col_width.valueChanged.connect(lambda _: _apply_width())
        btn_auto.clicked.connect(lambda: self.table.resizeColumnToContents(self.col_pick.currentIndex()))

        # Focus search with Ctrl+F
        find_act = QAction(self)
        find_act.setShortcut("Ctrl+F")
        find_act.triggered.connect(lambda: self.search_edit.setFocus())
        self.addAction(find_act)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add files", os.path.expanduser("~"),
            "Cheat/code files (*.pnach *.txt *.ini *.cb *.cbc *.rtxt);;All files (*.*)")
        if not files: return
        self.paths += [p for p in files if self._allowed(p)]
        self._refresh_table_rows(new_only=True)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder", os.path.expanduser("~"))
        if not folder: return
        if self.chk_recurse.isChecked():
            for root, _, files in os.walk(folder):
                for name in files:
                    p = os.path.join(root, name)
                    if self._allowed(p): self.paths.append(p)
        else:
            for name in os.listdir(folder):
                p = os.path.join(folder, name)
                if os.path.isfile(p) and self._allowed(p): self.paths.append(p)
        self._refresh_table_rows(new_only=True)

    def _allowed(self, path: str) -> bool:
        return path.lower().endswith(self.ALLOWED_EXTS)

    def _clear_all(self):
        self.paths.clear()
        self.rows.clear()
        self.table.setRowCount(0)
        self.progress.setMaximum(1)
        self.progress.setValue(0)

    # ---------- Table Helpers ----------
    def _refresh_table_rows(self, new_only=False):
        existing_files = set(self._iter_column_values(0))
        to_add = [p for p in self.paths if (p not in existing_files or not new_only)]
        self.table.setSortingEnabled(False)
        for p in to_add:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, val in enumerate([p, "", "", "", "queued"]):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.table.setSortingEnabled(True)
        self._reapply_filter_after_data_change()

    def _iter_column_values(self, col: int):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, col)
            yield it.text() if it else ""

    def _set_row(self, r: int, file: str, serials: str, crc: str, title: str, status: str):
        self.table.setItem(r, 0, QTableWidgetItem(file))
        self.table.setItem(r, 1, QTableWidgetItem(serials))
        self.table.setItem(r, 2, QTableWidgetItem(crc))
        self.table.setItem(r, 3, QTableWidgetItem(title))
        self.table.setItem(r, 4, QTableWidgetItem(status))

    # ---------- Filtering ----------
    def _apply_filter(self):
        """Filter rows by search text over selected column(s)."""
        text = self.search_edit.text()
        use_regex = self.chk_regex.isChecked()
        scope = self.search_in.currentText()  # "All columns" or specific

        # Pre-compile regex or escape text
        pattern = None
        if text:
            try:
                if use_regex:
                    pattern = re.compile(text, re.IGNORECASE)
                else:
                    pattern = re.compile(re.escape(text), re.IGNORECASE)
            except re.error:
                # invalid regex: show nothing and mark progress bar to hint
                for r in range(self.table.rowCount()):
                    self.table.setRowHidden(r, True)
                self.progress.setFormat("Invalid regex")
                return

        shown = 0
        for r in range(self.table.rowCount()):
            # Gather text per row
            cols = [
                self.table.item(r, c).text() if self.table.item(r, c) else ""
                for c in range(self.table.columnCount())
            ]
            if not pattern:
                keep = True  # empty query -> show all
            else:
                if scope == "All columns":
                    hay = " | ".join(cols)
                    keep = bool(pattern.search(hay))
                else:
                    idx = ["File","Serial(s)","CRC","Title","Status"].index(scope)
                    hay = cols[idx]
                    keep = bool(pattern.search(hay))
            self.table.setRowHidden(r, not keep)
            if keep:
                shown += 1

        self.progress.setFormat(f"Showing {shown}/{self.table.rowCount()}")
        # keep progress bar visible but not 'busy'
        if self.progress.maximum() <= 1:
                self.progress.setMaximum(1)
                self.progress.setValue(1)

    def _reapply_filter_after_data_change(self):
        """Call after Scan or Resolve to keep current filter applied."""
        self._apply_filter()

    def _set_progress(self, current: int, total: int):
        """Helper to update the progress bar with a percentage and counts."""
        total = max(1, int(total or 1))
        current = max(0, int(current or 0))
        self.progress.setMaximum(total)
        # clamp current to total for display
        cur = min(current, total)
        self.progress.setValue(cur)
        try:
            percent = int((cur / total) * 100)
        except Exception:
            percent = 0
        self.progress.setFormat(f"{percent}% ({cur}/{total})")

    # ---------- Scanning ----------
    def _scan_files(self):
        paths = [self.table.item(r, 0).text() for r in range(self.table.rowCount())]
        self.progress.setMaximum(max(1, len(paths)))
        self.progress.setValue(0)
        self._disable_ui(True)
        self.table.setSortingEnabled(False)
        for r in range(self.table.rowCount()):
            for c in range(1, 5):
                self.table.setItem(r, c, QTableWidgetItem(""))
        self.worker = BulkScanWorker(paths)
        # connect progress → percent formatter
        self.worker.progressed.connect(self._set_progress)
        # Batched update handler to reduce UI updates
        def on_scanned_batch(batch):
            # batch: list of (idx, result)
            # Sort by index to keep table stable
            for idx, result in sorted(batch, key=lambda x: x[0]):
                self._set_row(idx, result["file"], result["serials"], result["crc"], result["title"], result["status"])
        self.worker.scanned_batch.connect(on_scanned_batch)
        # Backward compat single-item signal
        def on_scanned(idx, result):
            self._set_row(idx, result["file"], result["serials"], result["crc"], result["title"], result["status"])
        self.worker.scanned.connect(on_scanned)
        def on_finished():
            # final label and reset
            self.progress.setMaximum(1)
            self.progress.setValue(1)
            self.progress.setFormat("Done")
            self._disable_ui(False)
            self.table.setSortingEnabled(True)
            self._reapply_filter_after_data_change()
        self.worker.finished.connect(on_finished)
        self.worker.start()

    def _disable_ui(self, disable: bool):
        self.btn_add_files.setDisabled(disable)
        self.btn_add_folder.setDisabled(disable)
        self.btn_clear.setDisabled(disable)
        self.chk_recurse.setDisabled(disable)
        self.chk_offline_lists.setDisabled(disable)
        self.chk_online.setDisabled(disable)
        self.btn_scan.setDisabled(disable)
        self.btn_resolve.setDisabled(disable)
        self.btn_copy_sel.setDisabled(disable)
        self.btn_copy_all.setDisabled(disable)
        self.btn_export.setDisabled(disable)
        self.btn_load_cheats.setDisabled(disable)

    # ---------- Resolve Titles (batch) ----------
    def _resolve_titles(self):
        # Collect keys for unresolved rows
        keys = []
        for r in range(self.table.rowCount()):
            title = self.table.item(r, 3).text().strip() if self.table.item(r,3) else ""
            if title: continue
            crc = self.table.item(r, 2).text().strip()
            serials = (self.table.item(r, 1).text() or "").split(";")
            # Try to extract from filename if missing
            if not crc or not any(serials):
                file_path = self.table.item(r, 0).text() if self.table.item(r,0) else ""
                fname = os.path.basename(file_path)
                # CRC: look for 8 hex digits
                m_crc = re.search(r"([0-9A-Fa-f]{8})", fname)
                if m_crc and not crc:
                    crc = m_crc.group(1).upper()
                # Serial: look for common serial pattern
                m_serial = re.search(r"([A-Z]{4,5}[-_ ]?\d{3,5})", fname, re.IGNORECASE)
                if m_serial and not any(serials):
                    serials = [m_serial.group(1).replace("_", "-").upper()]
            if crc:
                keys.append(crc)
            for s in [x.strip() for x in serials if x.strip()]:
                keys.append(s)
        # Nothing to do?
        if not keys:
            QMessageBox.information(self, "Resolve Titles", "Nothing to resolve: no serials or CRCs found to look up. (Did you scan files first?)")
            return

        # Kick a single ResolveWorker for the whole batch
        worker = ResolveWorker(
            keys=list(dict.fromkeys(keys)),  # unique preserve order
            local_map=getattr(self.parent.cheats_tab, "mapping", {}) or {},
            use_bundled_lists=self.chk_offline_lists.isChecked(),
            try_online=self.chk_online.isChecked() and (requests is not None)
        )
        # progress → mirror into our bar (show percent)
        self.progress.setMaximum(max(1, len(keys)))
        self.progress.setValue(0)
        worker.progressed.connect(self._set_progress)

        def on_done(out: Dict[str,str]):
            # Update each row’s title/CRC if available
            for r in range(self.table.rowCount()):
                file = self.table.item(r,0).text()
                serials = [x.strip() for x in (self.table.item(r,1).text() or "").split(";") if x.strip()]
                crc = (self.table.item(r,2).text() or "").strip()
                title = (self.table.item(r,3).text() or "").strip()

                # Prefer CRC title, else any serial title
                picked_title = title
                if not picked_title and crc and crc in out:
                    picked_title = out[crc]
                if not picked_title:
                    for s in serials:
                        if s in out:
                            picked_title = out[s]
                            break
                        n = norm_serial_key(s)
                        if n in out:
                            picked_title = out[n]
                            break

                # Some workers also emit *_CRC — try to fill CRC if missing
                if not crc:
                    for s in [crc] + serials if crc else serials:
                        if not s:
                            continue
                        kk = s + "_CRC"
                        if kk in out:
                            crc = out[kk]
                            break

                # Only mark as resolved if Title, CRC, and at least one Serial are present
                if picked_title and crc and serials and any(serials):
                    self._set_row(r, file, "; ".join(serials), crc, picked_title, "resolved")
                # Otherwise, keep as-is (could optionally set a different status)
            # small UX touch
            self.progress.setMaximum(1)
            self.progress.setValue(1)
            self.progress.setFormat("Done")
            self._reapply_filter_after_data_change()
        worker.resolved.connect(on_done)
        # Reuse the Cheats tab worker manager to keep thread alive
        self.parent.cheats_tab._start_worker(worker)

    # ---------- Copy / Export ----------
    def _gather_rows(self, only_selected=False) -> List[List[str]]:
        rows = []
        indices = self.table.selectionModel().selectedRows() if only_selected else [self.table.model().index(r,0) for r in range(self.table.rowCount())]
        for idx in indices:
            r = idx.row()
            vals = [self.table.item(r,c).text() if self.table.item(r,c) else "" for c in range(5)]
            rows.append(vals)
        return rows

    def _copy_selected(self):
        self._copy_rows(True)

    def _copy_all(self):
        self._copy_rows(False)

    def _copy_rows(self, only_selected: bool):
        rows = self._gather_rows(only_selected)
        lines = ["\t".join(["File","Serial(s)","CRC","Title","Status"])]
        for vals in rows:
            lines.append("\t".join(vals))
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "Copied", f"Copied {'selected' if only_selected else 'all'} rows to clipboard.")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", os.path.expanduser("~"), "CSV (*.csv)")
        if not path: return
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["File","Serial(s)","CRC","Title","Status"])
            for vals in self._gather_rows(False):
                w.writerow(vals)
        QMessageBox.information(self, "Export", f"Saved: {path}")

    # ---------- Hand-off to Cheats ----------
    def _load_selected_into_cheats(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            QMessageBox.information(self, "Load in Cheats", "Select at least one row.")
            return
        # Load the first selected row
        r = sel[0].row()
        path = self.table.item(r,0).text()
        serials = [x.strip() for x in (self.table.item(r,1).text() or "").split(";") if x.strip()]
        crc = (self.table.item(r,2).text() or "").strip()
        title = (self.table.item(r,3).text() or "").strip()
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            QMessageBox.warning(self, "Open failed", str(e))
            return

        cheats = self.parent.cheats_tab
        # Fill editor with content
        cheats.codes_text.setPlainText(text)
        # Prefer CRC from filename too
        m = re.search(r"([0-9A-Fa-f]{8})", os.path.basename(path))
        prefer_crc = m.group(1) if m else None

        # If we already have fields from the table, set them first (then let autofill backfill missing bits)
        if serials:
            cheats.serial_edit.setText("; ".join(serials))
        if crc:
            cheats.crc_edit.setText(crc)
        if title:
            cheats.title_edit.setText(title)

        # backfill anything missing via the same logic used elsewhere
        cheats._autofill_from_text(text, prefer_filename_crc=prefer_crc)
        # pick mode based on extension
        if path.lower().endswith(".pnach"):
            cheats.input_mode.setCurrentIndex(1)
        else:
            cheats.input_mode.setCurrentIndex(0)

        # jump to Cheats tab
        self.parent.tabs.setCurrentWidget(cheats)

class SettingsTab(QWidget):
    def __init__(self, parent: 'MainWindow'):
        super().__init__()
        self.parent = parent
        self.paths: Dict[str, str] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        grp = QGroupBox("PCSX2 User Directory")
        fl = QFormLayout(grp)
        self.user_dir = QLineEdit()
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.clicked.connect(self._browse)
        self.btn_detect = QPushButton("Auto-detect")
        self.btn_detect.clicked.connect(self._detect)
        fl.addRow("Base:", self._row(self.user_dir, self.btn_browse, self.btn_detect))
        layout.addWidget(grp)

        subgrp = QGroupBox("Detected Subfolders (created if missing)")
        fl2 = QFormLayout(subgrp)
        self.cheats_label = QLabel("")
        self.cheatsws_label = QLabel("")
        self.textures_label = QLabel("")
        self.logs_label = QLabel("")
        fl2.addRow("cheats:", self.cheats_label)
        fl2.addRow("cheats_ws:", self.cheatsws_label)
        fl2.addRow("textures:", self.textures_label)
        fl2.addRow("logs:", self.logs_label)
        layout.addWidget(subgrp)

        # Omniconvert + PCSX2 toggles
        cfg = QGroupBox("Integrations & Toggles (best-effort)")
        cfgl = QFormLayout(cfg)
        self.omniconvert_path = QLineEdit()
        self.omniconvert_path.setPlaceholderText("Path to Omniconvert.exe (optional)")
        btn_omni = QPushButton("Browse…")
        btn_omni.clicked.connect(lambda: self._pick_file(self.omniconvert_path))
        self.btn_enable_cheats = QPushButton("Enable Cheats in INI")
        self.btn_enable_cheats.clicked.connect(self._toggle_cheats_ini)
        self.btn_enable_textures = QPushButton("Enable Texture Replacement in INI")
        self.btn_enable_textures.clicked.connect(self._toggle_textures_ini)
        self.pcsx2_exe = QLineEdit()
        self.pcsx2_exe.setPlaceholderText("Path to pcsx2(.exe) for test launch (optional)")
        btn_pcsx2 = QPushButton("Browse…")
        btn_pcsx2.clicked.connect(lambda: self._pick_file(self.pcsx2_exe))
        self.btn_launch = QPushButton("Launch PCSX2 (test)")
        self.btn_launch.clicked.connect(self._launch_pcsx2)

        cfgl.addRow("Omniconvert:", self._row(self.omniconvert_path, btn_omni))
        cfgl.addRow(self._row(self.btn_enable_cheats, self.btn_enable_textures))
        cfgl.addRow("PCSX2 exe:", self._row(self.pcsx2_exe, btn_pcsx2, self.btn_launch))
        layout.addWidget(cfg)

        # Profiles
        prof = QGroupBox("Profiles")
        pfl = QFormLayout(prof)
        self.profile_title = QLineEdit()
        self.profile_serial = QLineEdit()
        self.profile_crc = QLineEdit()
        self.btn_profile_save = QPushButton("Save/Update Profile")
        self.btn_profile_save.clicked.connect(self._save_profile)
        self.btn_profile_export = QPushButton("Export Profiles JSON")
        self.btn_profile_export.clicked.connect(self._export_profiles)
        self.btn_profile_import = QPushButton("Import Profiles JSON")
        self.btn_profile_import.clicked.connect(self._import_profiles)
        self.profiles_list = QListWidget()
        self.profiles: Dict[str, Dict] = {}
        self.profiles_list.itemSelectionChanged.connect(self._load_selected_profile)

        pfl.addRow("Title:", self.profile_title)
        pfl.addRow("Serial:", self.profile_serial)
        pfl.addRow("CRC:", self.profile_crc)
        pfl.addRow(self._row(self.btn_profile_save, self.btn_profile_export, self.btn_profile_import))
        layout.addWidget(prof)
        layout.addWidget(self.profiles_list)

        layout.addStretch(1)

        self._detect()

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
        if p: line.setText(p)

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
        self.parent.cheats_tab.load_paths(self.paths)
        self.parent.textures_tab.load_paths(self.paths)

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
           
            QMessageBox.information(self, "Profiles", "Imported.")
        except Exception as e:
            QMessageBox.critical(self, "Import error", str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCSX2 Patch & Texture Manager")
        self.setWindowIcon(QIcon("logo.png"))
        self.resize(1180, 780)
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.cheats_tab = CheatsTab(self)
        self.bulk_tab = BulkTab(self)
        self.textures_tab = TexturesTab(self)
        self.settings_tab = SettingsTab(self)

        self.tabs.addTab(self.cheats_tab, "Cheats (.pnach)")
        self.tabs.addTab(self.bulk_tab, "Bulk Scanner")
        self.tabs.addTab(self.textures_tab, "Texture Packs")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Mirror initial resolver options into Bulk tab for convenience
        self.bulk_tab.chk_offline_lists.setChecked(self.cheats_tab.chk_offline_lists.isChecked())
        if hasattr(self.cheats_tab, "chk_online"):
            self.bulk_tab.chk_online.setChecked(self.cheats_tab.chk_online.isChecked())

        self._build_menu()
        self.setAcceptDrops(True)

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

    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        help_menu = mb.addMenu("Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._about)
        help_menu.addAction(about_act)

    def _about(self):
        QMessageBox.information(
            self,
            "About",
            "PCSX2 Patch & Texture Manager\n\n"
            "- RAW/PNACH import + auto-detect CRC/Serial\n"
            "- Title resolver via local mapping (+ optional offline lists)\n"
            "- Drag & Drop for .pnach/.zip/folders\n"
            "- Texture installer with auto-CRC suggestion\n"
            "- Omniconvert integration hook (optional)\n"
            "- Best-effort INI toggles + test launch\n"
            "- Per-game profiles (JSON)\n"
        )


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("logo.png"))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
