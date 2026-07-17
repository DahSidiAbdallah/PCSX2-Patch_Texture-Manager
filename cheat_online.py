"""Online cheat database integration for PCSX2 Patch & Texture Manager.
This module provides small, respectful scrapers/parsers and returns a
list of structured entries. Each entry is a dict with keys:
 - source: short source name
 - title: optional human title
 - codes: optional list of code strings (RAW lines or pnach lines)
 - raw_html: optional HTML blob for debugging
 - link: optional URL where the entry was found

Implementations are best-effort. Network access is optional.
"""

import os
import re
import json

try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None
    BeautifulSoup = None


def _safe_get(url, timeout=10, headers=None):
    if not requests:
        return None
    try:
        return requests.get(url, timeout=timeout, headers=headers or {})
    except Exception:
        return None


def fetch_pcsx2_forum_cheats(serial_or_crc):
    # Placeholder: PCSX2 forums have varied structure; avoid aggressive scraping.
    return []


# --- Shared PSXDataCenter title/CRC resolution ---
# Duplicated (not imported) from main.py's SERIAL_RE/CRC_IN_TEXT/normalize_crc so this
# module stays importable standalone without a circular import back into main.py.
_CRC_IN_TEXT = re.compile(r"\bCRC\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{8})\b")
_HEX8 = re.compile(r"^[0-9A-Fa-f]{8}$")

PSXDATACENTER_URLS = [
    'https://psxdatacenter.com/ps2/ntscu2.html',
    'https://psxdatacenter.com/ps2/pal2.html',
    'https://psxdatacenter.com/ps2/ntscj2.html',
]


def _normalize_crc(crc):
    if not crc:
        return None
    crc = crc.strip().upper()
    return crc if _HEX8.match(crc) else None


def _score_title_candidate(text, html=None):
    """Heuristic score for a title candidate; higher is better. See resolve_title_and_crc."""
    if not text:
        return -9999
    t = re.sub(r'^[\s \._:\-\|]+', '', text).strip()
    tu = t.upper()
    if tu in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
        return -9999
    score = max(0, len(t))
    if not re.search(r'[A-Za-z]', t):
        score -= 120
    else:
        score += 40
    words = [w for w in re.split(r'\s+', t) if w]
    if len(words) > 1:
        score += 14 * min(6, len(words))
    if re.search(r'[a-z]', t):
        score += 24
    if re.search(r'[\(\)\-:–—\.]', t):
        score += 10
    if t.isupper():
        short_tokens = [w for w in words if len(w) < 5]
        if len(words) == 1 and len(t) < 6:
            score -= 60
        elif len(short_tokens) >= len(words) and len(words) <= 3:
            score -= 36
    if re.fullmatch(r'[0-9A-Fa-f]{1,8}', t):
        score -= 100
    alpha = len(re.findall(r'[A-Za-z]', t))
    if alpha > 0:
        score += int((alpha / max(1, len(t))) * 40)
    if html:
        hu = html.lower()
        if 'class="col3"' in hu or "class='col3'" in hu or 'class="col7"' in hu or "class='col7'" in hu:
            score += 60
        if '<a' in hu:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                a = soup.find('a')
                if a:
                    at = (a.get_text(' ', strip=True) or '').strip()
                    if at and at.upper() not in ('INFO', '詳細', 'DETAILS') and re.search(r'[A-Za-z]', at):
                        score += 36
                    else:
                        score -= 18
            except Exception:
                score += 8
    return score


def resolve_title_and_crc(html: str, serial_variants):
    """Scan a PSXDataCenter-style HTML page for a title/CRC matching any of serial_variants.

    Returns (title, crc, html_snippet); any element may be None if not found. This is the
    single, shared implementation of the title-scraping heuristics that used to be
    duplicated (and drifting) between this module and main.py's ResolveWorker/SingleOnlineLookup.
    """
    if not BeautifulSoup or not html:
        return None, None, None
    found_title = None
    found_crc = None
    found_html = None
    found_title_html = None
    U = html.upper()
    for sv in serial_variants:
        pos = U.find(sv.upper())
        if pos == -1:
            pos = U.find(sv.upper().replace('-', '').replace('_', ''))
        if pos == -1:
            continue
        window = html[max(0, pos - 4000): pos + 4000]
        mcrc = _CRC_IN_TEXT.search(window)
        if mcrc and not found_crc:
            found_crc = _normalize_crc(mcrc.group(1))
        m = re.search(
            r'<td[^>]*class=["\']col2["\'][^>]*>.*?(%s).*?</td>\s*<td[^>]*class=["\']col3["\'][^>]*>(.*?)</td>' % re.escape(sv),
            window, flags=re.IGNORECASE | re.DOTALL)
        if m and not found_title:
            cand_html = m.group(2)
            cand = BeautifulSoup(cand_html, 'html.parser').get_text(strip=True)
            if cand and len(cand) > 3 and cand.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN') and re.search(r'[A-Za-z]', cand):
                found_title = cand
                found_html = m.group(0)
                found_title_html = cand_html
        if not found_title:
            m2 = re.search(
                r'<td[^>]*class=["\']col6["\'][^>]*>.*?(%s).*?</td>\s*<td[^>]*class=["\']col7["\'][^>]*>(.*?)</td>' % re.escape(sv),
                window, flags=re.IGNORECASE | re.DOTALL)
            if m2:
                cand_html = m2.group(2)
                cand = BeautifulSoup(cand_html, 'html.parser').get_text(strip=True)
                if cand and len(cand) > 3 and cand.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN') and re.search(r'[A-Za-z]', cand):
                    found_title = cand
                    found_html = m2.group(0)
                    found_title_html = cand_html
        if not found_title:
            soup = BeautifulSoup(window, 'html.parser')
            sv_u = sv.upper()
            picked = None
            picked_html = None
            for tr in soup.find_all('tr'):
                tr_txt = tr.get_text(' ', strip=True).upper()
                if sv_u in tr_txt or sv_u.replace('-', '') in tr_txt:
                    td3 = tr.find('td', attrs={'class': re.compile(r'col3', re.I)})
                    if td3:
                        cand_html = str(td3)
                        cand = td3.get_text(' ', strip=True)
                        if cand and len(cand) > 3 and cand.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN') and re.search(r'[A-Za-z]', cand):
                            picked = cand
                            picked_html = cand_html
                            break
                    a = tr.find('a')
                    if a and a.get_text(strip=True):
                        cand_html = str(a)
                        cand = a.get_text(' ', strip=True)
                        if len(cand) > 3 and cand.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN') and re.search(r'[A-Za-z]', cand):
                            picked = cand
                            picked_html = cand_html
                            break
                    tds = tr.find_all('td')
                    if len(tds) >= 2:
                        cands = [td.get_text(' ', strip=True) for td in tds]
                        cands = [c for c in cands if c and sv_u not in c.upper()]
                        if cands:
                            html_candidates = []
                            for td in tds:
                                ctxt = td.get_text(' ', strip=True)
                                if ctxt and sv_u not in ctxt.upper():
                                    html_candidates.append((ctxt, str(td)))
                            if html_candidates:
                                scored = [(_score_title_candidate(text, html_), text, html_) for (text, html_) in html_candidates]
                            else:
                                scored = [(_score_title_candidate(c), c, None) for c in cands]
                            scored.sort(reverse=True)
                            cand = scored[0][1]
                            if cand and len(cand) > 3 and cand.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN'):
                                picked = cand
                                picked_html = str(tr)
                                break
            if not picked:
                text = soup.get_text(' ', strip=True)
                after = text.upper().split(sv.upper(), 1)[-1] if sv.upper() in text.upper() else text.upper()
                chunks = re.split(r'[\|\-\n\r]+', after)
                for ch in chunks:
                    c = ch.strip()
                    if not c:
                        continue
                    if re.search(r"\b(SCUS|SLUS|SLES|SCES|SLPS|SLPM|SCPS|SCAJ|SLKA|ULUS|UCUS|PBPX|PAPX|TCUS|TCES)[-_ ]?\d{3,6}\b", c, re.IGNORECASE) or _CRC_IN_TEXT.search(c):
                        continue
                    if len(c) > 3 and c.upper() not in ('INFO', 'TITLE', 'N/A', 'UNKNOWN') and re.search(r'[A-Za-z]', c):
                        picked = c
                        picked_html = None
                        break
            if picked:
                found_title = picked
                if picked_html:
                    found_html = picked_html
                    found_title_html = picked_html
        if found_title and found_crc:
            break
    return found_title, found_crc, (found_title_html or found_html)


def resolve_serial_online(serial_variants, urls=None, timeout=8):
    """Fetch PSXDataCenter pages and resolve a title/CRC for the given serial variants.

    Returns (title, crc, html_snippet); any element may be None if nothing was found or
    `requests` isn't available.
    """
    if not requests:
        return None, None, None
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PCSX2-Manager/1.0)"}
    found_title = found_crc = found_html = None
    for url in (urls or PSXDATACENTER_URLS):
        resp = _safe_get(url, timeout=timeout, headers=headers)
        if not resp or resp.status_code != 200 or not resp.text:
            continue
        title, crc, html_snip = resolve_title_and_crc(resp.text, serial_variants)
        if title and not found_title:
            found_title = title
            found_html = html_snip
        if crc and not found_crc:
            found_crc = crc
        if found_title and found_crc:
            break
    return found_title, found_crc, found_html


def _extract_table_snippets(html: str, key: str):
    """Return small HTML snippets around matches of key (case-insensitive)."""
    if not BeautifulSoup:
        return []
    U = html.upper()
    keyU = key.upper()
    snippets = []
    pos = 0
    while True:
        idx = U.find(keyU, pos)
        if idx == -1:
            break
        start = max(0, idx - 1000)
        end = min(len(html), idx + 1000)
        snippets.append(html[start:end])
        pos = idx + 1
    return snippets


def fetch_psxdatacenter_cheats(serial_or_crc):
    """Return structured entries from PSXDataCenter pages if the serial/crc appears.
    Title resolution uses the same heuristics as resolve_title_and_crc (shared with
    main.py's ResolveWorker/SingleOnlineLookup) rather than a separate, weaker guess.
    """
    if not requests or not BeautifulSoup:
        return []
    out = []
    headers = {"User-Agent": "PCSX2-Manager/1.0 (+https://example)"}
    serial_variants = [serial_or_crc, serial_or_crc.upper().replace('-', '').replace('_', '')]
    for url in PSXDATACENTER_URLS:
        resp = _safe_get(url, headers=headers)
        if not resp or resp.status_code != 200 or not resp.text:
            continue
        html = resp.text
        if serial_or_crc.upper() not in html.upper():
            continue
        title, _crc, html_snip = resolve_title_and_crc(html, serial_variants)
        out.append({'source': 'psxdatacenter', 'title': title, 'codes': [], 'raw_html': html_snip, 'link': url})
    return out


def parse_psxdatacenter_html(html: str, key: str):
    """Parse a PSXDataCenter HTML blob and return structured entries for given key.
    This is the core parser used by fetch_psxdatacenter_cheats and by tests.
    """
    if not BeautifulSoup:
        return []
    entries = []
    snippets = _extract_table_snippets(html, key)
    for sn in snippets:
        title = None
        codes = []
        try:
            soup = BeautifulSoup(sn, 'html.parser')
            # attempt to find a title cell nearby (col3/col7 are common in PSXDataCenter)
            td = soup.find(lambda t: t.name == 'td' and t.get('class') and any(c in ('col3','col7') for c in t.get('class')))
            if td:
                cand = td.get_text(' ', strip=True)
                if cand and not re.search(re.escape(key), cand, re.I):
                    title = cand
            if not title:
                # fallback: first td text that isn't the serial/CRC
                for td in soup.find_all('td'):
                    txt = td.get_text(' ', strip=True)
                    if txt and not re.search(re.escape(key), txt, re.I) and len(txt) > 3:
                        title = txt
                        break
            # attempt to find code blocks in pre/code, or inside td.col7
            found = False
            for container in soup.find_all(['pre','code']):
                lines = [l.strip() for l in container.get_text().splitlines() if l.strip()]
                norms = _normalize_code_lines(lines)
                if norms:
                    codes.extend(norms)
                    found = True
            if not found:
                td7 = soup.find(lambda t: t.name == 'td' and t.get('class') and 'col7' in t.get('class'))
                if td7:
                    lines = [l.strip() for l in td7.get_text().splitlines() if l.strip()]
                    codes.extend(_normalize_code_lines(lines))
        except Exception:
            pass
        entries.append({'source': 'psxdatacenter', 'title': title, 'codes': codes, 'raw_html': sn})
    return entries


def fetch_gamehacking_org_cheats(serial_or_crc):
    """Query GameHacking.org search API and return structured results.
    Fallback: basic HTML scrape if API isn't reachable.
    """
    if not requests:
        return []
    out = []
    headers = {"User-Agent": "PCSX2-Manager/1.0 (+https://example)"}
    api_url = f'https://gamehacking.org/api/search?game={serial_or_crc}'
    resp = _safe_get(api_url, headers=headers)
    if resp and resp.status_code == 200:
        try:
            data = resp.json()
            # API returns a list of results; attempt to normalize
            for item in (data or []):
                title = item.get('name') or item.get('title') or item.get('game') or None
                codes = []
                # try common fields
                if 'codes' in item and isinstance(item['codes'], list):
                    for c in item['codes']:
                        # c might be dict or string
                        if isinstance(c, dict):
                            codes.append(c.get('code') or c.get('text') or str(c))
                        else:
                            codes.append(str(c))
                out.append({'source': 'gamehacking.org', 'title': title, 'codes': codes, 'raw_html': None, 'link': api_url, 'data': item})
            return out
        except Exception:
            pass

    # Fallback: search HTML result page
    search_url = f'https://gamehacking.org/?s={serial_or_crc}'
    resp2 = _safe_get(search_url, headers=headers)
    if resp2 and resp2.status_code == 200 and BeautifulSoup:
        try:
            soup = BeautifulSoup(resp2.text, 'html.parser')
            for h in soup.find_all(['h2','h3','h4','article']):
                txt = h.get_text(' ', strip=True)
                if serial_or_crc.upper() in txt.upper() or serial_or_crc.upper().replace('-', '') in txt.upper():
                    # get nearby code block
                    codes = []
                    nxt = h.find_next(['pre','code'])
                    if nxt:
                        lines = [c.strip() for c in nxt.get_text().splitlines() if c.strip()]
                        codes = _normalize_code_lines(lines)
                    out.append({'source': 'gamehacking.org', 'title': txt, 'codes': codes, 'raw_html': str(h), 'link': search_url})
        except Exception:
            pass
    return out


def parse_gamehacking_json(obj):
    """Normalize a GameHacking.org API JSON object into structured entries.
    Accepts either a list of items or a single item.
    """
    out = []
    items = obj if isinstance(obj, list) else (obj or [])
    for item in items:
        title = item.get('name') or item.get('title') or item.get('game') or None
        codes = []
        if isinstance(item, dict):
            if 'codes' in item and isinstance(item['codes'], list):
                for c in item['codes']:
                    if isinstance(c, dict):
                        code_text = c.get('code') or c.get('text') or ''
                        codes.extend(_normalize_code_lines([code_text]))
                    else:
                        codes.extend(_normalize_code_lines([str(c)]))
            # Some API variants include a single 'code' field
            if 'code' in item and isinstance(item['code'], str):
                codes.extend(_normalize_code_lines([item['code']]))
        out.append({'source': 'gamehacking.org', 'title': title, 'codes': codes, 'data': item})
    return out


def parse_gamehacking_html(html: str, key: str):
    if not BeautifulSoup:
        return []
    out = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for block in soup.find_all(['h2','h3','h4','article']):
            txt = block.get_text(' ', strip=True)
            if key.upper() in txt.upper():
                codes = []
                nxt = block.find_next(['pre','code'])
                if nxt:
                    lines = [l.strip() for l in nxt.get_text().splitlines() if l.strip()]
                    codes = _normalize_code_lines(lines)
                out.append({'source': 'gamehacking.org', 'title': txt, 'codes': codes, 'raw_html': str(block)})
    except Exception:
        pass
    return out


def _normalize_code_lines(lines):
    """Take raw lines (strings) and normalize to RAW 8x8 pairs or PNACH patch lines.
    Returns a list of normalized code strings (RAW pairs like 'XXXXXXXX YYYYYYYY' or PNACH lines).
    """
    out = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # If PNACH patch line, keep as-is
        if s.lower().startswith('patch='):
            out.append(s)
            continue
        # remove common prefixes/tokens
        s2 = s.replace(':', ' ').replace('\t', ' ').replace(',', ' ').strip()
        parts = [p for p in s2.split() if p]
        if len(parts) >= 2 and re.fullmatch(r'[0-9A-Fa-f]{1,8}', parts[0]) and re.fullmatch(r'[0-9A-Fa-f]{1,8}', parts[1]):
            addr = parts[0].upper().rjust(8, '0')
            val = parts[1].upper().rjust(8, '0')
            out.append(f"{addr} {val}")
            continue
        # Some codes are given as groups separated by spaces; attempt to find any 8-hex tokens
        hexs = re.findall(r'\b[0-9A-Fa-f]{8}\b', s)
        if len(hexs) >= 2:
            # pair them sequentially
            for i in range(0, len(hexs)-1, 2):
                a = hexs[i].upper(); v = hexs[i+1].upper()
                out.append(f"{a} {v}")
            continue
        # Otherwise keep raw line as fallback
        out.append(s)
    return out


def fetch_and_cache_cheats(serial_or_crc, cache_dir="cheat_cache"):
    """Fetch cheats and cache them.

    Parameters:
    - serial_or_crc: key
    - cache_dir: directory
    - force: if True, ignore existing cache and refetch
    - max_age_hours: cache TTL in hours (if file older, re-fetch)
    """
    def _now():
        import time
        return time.time()

    os.makedirs(cache_dir, exist_ok=True)
    key = (serial_or_crc or '').upper()
    cache_path = os.path.join(cache_dir, f"{key}.json")
    force = False
    max_age_hours = 24
    # Allow callers to pass force or max_age by setting attributes on the function (backwards compat)
    # e.g., fetch_and_cache_cheats.force = True
    if hasattr(fetch_and_cache_cheats, 'force') and fetch_and_cache_cheats.force:
        force = True
    if hasattr(fetch_and_cache_cheats, 'max_age_hours'):
        try:
            max_age_hours = int(fetch_and_cache_cheats.max_age_hours)
        except Exception:
            pass

    if not force and os.path.isfile(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            import time
            age_hours = (time.time() - mtime) / 3600.0
            if age_hours <= max_age_hours:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass

    results = []
    # Order: forum, PSXDataCenter, GameHacking
    try:
        results.extend(fetch_pcsx2_forum_cheats(key))
    except Exception:
        pass
    try:
        results.extend(fetch_psxdatacenter_cheats(key))
    except Exception:
        pass
    try:
        results.extend(fetch_gamehacking_org_cheats(key))
    except Exception:
        pass

    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return results


def parse_pcsx2_forum_html(html: str, key: str):
    """Basic parser for forum threads: extract <pre>/<code> blocks and nearby titles."""
    if not BeautifulSoup:
        return []
    out = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # Some forums wrap posts in containers with class names; fall back to any <article> or <div>
        candidates = soup.find_all(class_=re.compile(r'post|message|entry', re.I)) or soup.find_all('article') or soup.find_all('div')
        for post in candidates:
            txt = post.get_text(' ', strip=True)
            if key.upper() not in txt.upper():
                continue
            title = None
            # try to find a heading in the post
            h = post.find(['h1','h2','h3','h4'])
            if h:
                title = h.get_text(' ', strip=True)
            codes = []
            for b in post.find_all(['pre','code']):
                lines = [l.strip() for l in b.get_text().splitlines() if l.strip()]
                codes.extend(_normalize_code_lines(lines))
            out.append({'source': 'pcsx2_forum', 'title': title, 'codes': codes, 'raw_html': str(post)})
    except Exception:
        pass
    return out


def parse_codeblock_text(text: str):
    """Convenience: parse a raw text block into normalized code lines."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return _normalize_code_lines(lines)
