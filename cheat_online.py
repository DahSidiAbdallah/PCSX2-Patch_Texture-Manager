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
    We attempt to extract a nearby HTML snippet and a plausible title.
    """
    if not requests or not BeautifulSoup:
        return []
    urls = [
        'https://psxdatacenter.com/ps2/ntscu2.html',
        'https://psxdatacenter.com/ps2/pal2.html',
        'https://psxdatacenter.com/ps2/ntscj2.html',
    ]
    out = []
    headers = {"User-Agent": "PCSX2-Manager/1.0 (+https://example)"}
    for url in urls:
        resp = _safe_get(url, headers=headers)
        if not resp or resp.status_code != 200 or not resp.text:
            continue
        html = resp.text
        if serial_or_crc.upper() not in html.upper():
            continue
        snippets = _extract_table_snippets(html, serial_or_crc)
        for sn in snippets:
            title = None
            try:
                soup = BeautifulSoup(sn, 'html.parser')
                # Heuristic: find the nearest <td> with class col3/col7 or any <td> text not matching serial/CRC
                td = soup.find('td')
                if td:
                    cand = td.get_text(' ', strip=True)
                    if cand and not re.search(r"\b(?:%s)\b" % re.escape(serial_or_crc), cand, re.I):
                        title = cand
            except Exception:
                title = None
            out.append({'source': 'psxdatacenter', 'title': title, 'codes': [], 'raw_html': sn, 'link': url})
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
