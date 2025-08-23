import json
import re
import time
import os
from urllib.parse import unquote, urlparse
import requests
from bs4 import BeautifulSoup

CACHE_DIR = 'cheat_cache'
SUMMARY = 'cheat_fetch_summary.json'
HEADERS = {'User-Agent': 'PCSX2-Manager/1.0 (+https://example)'}

# heuristics to find target urls inside Bing wrapper pages
TARGET_RE = re.compile(r'(https?://[A-Za-z0-9\-._~:/?#\[\]@!$&\'"()*+,;=%]+)')


def find_embedded_target(html, serial):
    """Look for an embedded target URL in a Bing wrapper page's HTML."""
    # try JS pattern var u = "https://..."
    m = re.search(r'var\s+u\s*=\s*"(https?://[^"]+)"', html)
    if m:
        return m.group(1)
    # try window.location.href = '...'
    m = re.search(r'window\.location(?:\.href)?\s*=\s*"(https?://[^"]+)"', html)
    if m:
        return m.group(1)
    # fallback: find any https url in the snippet near the serial
    U = html.upper()
    idx = U.find(serial.upper())
    if idx != -1:
        start = max(0, idx-800)
        end = min(len(html), idx+800)
        seg = html[start:end]
        m2 = TARGET_RE.search(seg)
        if m2:
            return m2.group(1)
    # fallback: search entire doc for prioritized domains
    for domain in ('forums.pcsx2.net', 'scribd.com', 'gamehacking.org', 'psxdatacenter.com'):
        m3 = re.search(r'(https?://[^"\'>\s]*' + re.escape(domain) + r'[^"\'>\s]*)', html)
        if m3:
            return m3.group(1)
    return None


def extract_codes_from_html(html, serial):
    out = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # find pre/code blocks
        for b in soup.find_all(['pre','code']):
            txt = b.get_text('\n', strip=True)
            # split into lines and collect hex-like pairs
            for ln in txt.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                # raw PNACH lines
                if ln.lower().startswith('patch='):
                    out.append(ln)
                    continue
                # find 8-hex tokens
                hexs = re.findall(r'\b[0-9A-Fa-f]{8}\b', ln)
                if len(hexs) >= 2:
                    for i in range(0, len(hexs)-1, 2):
                        out.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
                else:
                    # detect common code pattern like 'XXXXXXXX YYYYYYYY'
                    m = re.search(r'([0-9A-Fa-f]{1,8})\s+([0-9A-Fa-f]{1,8})', ln)
                    if m:
                        a = m.group(1).upper().rjust(8,'0')
                        v = m.group(2).upper().rjust(8,'0')
                        out.append(f"{a} {v}")
        # additional heuristics: forum post bodies
        for cls in ('postbody','message','post','content'):
            for div in soup.find_all(class_=re.compile(cls, re.I)):
                txt = div.get_text('\n', strip=True)
                hexs = re.findall(r'\b[0-9A-Fa-f]{8}\b', txt)
                if len(hexs) >= 2:
                    for i in range(0, len(hexs)-1, 2):
                        out.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
    except Exception:
        pass
    # dedupe while preserving order
    seen = set()
    res = []
    for r in out:
        if r not in seen:
            seen.add(r)
            res.append(r)
    return res


def deep_process(summary_path=SUMMARY):
    if not os.path.isfile(summary_path):
        print('No summary found at', summary_path)
        return
    with open(summary_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for serial, entries in data.items():
        print('\nProcessing', serial)
        all_found = []
        for e in entries:
            link = e.get('link')
            if not link:
                continue
            print('  wrapper:', link)
            try:
                r = requests.get(link, headers=HEADERS, timeout=10)
                html = r.text or ''
            except Exception as ex:
                print('   failed to fetch wrapper:', ex)
                continue
            target = find_embedded_target(html, serial)
            if target:
                print('   embedded target found:', target)
                try:
                    r2 = requests.get(target, headers=HEADERS, timeout=10)
                    codes = extract_codes_from_html(r2.text or '', serial)
                    print('    codes found:', len(codes))
                    for c in codes[:6]:
                        print('     ', c)
                    all_found.append({'source':'resolved_target','link':target,'codes':codes})
                    time.sleep(0.5)
                except Exception as ex:
                    print('    fetch target error:', ex)
            else:
                print('   no embedded target found in wrapper; trying to fetch the wrapper page body for codes')
                codes = extract_codes_from_html(html, serial)
                print('    codes found in wrapper:', len(codes))
                if codes:
                    all_found.append({'source':'wrapper_page','link':link,'codes':codes})
        # additionally probe site-specific search for pcsx2 forum threads
        # attempt Bing site search for forums.pcsx2.net
        query = f'site:forums.pcsx2.net {serial}'
        try:
            bres = requests.get('https://www.bing.com/search', params={'q':query}, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(bres.text or '', 'html.parser')
            links = [a.get('href') for a in soup.select('li.b_algo h2 a') if a.get('href')]
            for u in links[:6]:
                print('  try forum search link:', u)
                try:
                    r3 = requests.get(u, headers=HEADERS, timeout=10)
                    codes = extract_codes_from_html(r3.text or '', serial)
                    if codes:
                        print('    forum codes found:', len(codes), 'at', r3.url)
                        all_found.append({'source':'forum_search','link':r3.url,'codes':codes})
                except Exception as ex:
                    print('    fetch failed:', ex)
                time.sleep(0.5)
        except Exception as ex:
            print('  forum site search failed:', ex)

        # also try direct PSXDataCenter pages
        for url in ('https://psxdatacenter.com/ps2/ntscu2.html','https://psxdatacenter.com/ps2/pal2.html','https://psxdatacenter.com/ps2/ntscj2.html'):
            try:
                r4 = requests.get(url, headers=HEADERS, timeout=10)
                if serial.upper() in (r4.text or '').upper():
                    print('   found serial on PSXDataCenter page:', url)
                    codes = extract_codes_from_html(r4.text or '', serial)
                    if codes:
                        print('    psxdatacenter codes found:', len(codes))
                        all_found.append({'source':'psxdatacenter_page','link':url,'codes':codes})
            except Exception:
                pass
            time.sleep(0.3)

        # write to cache if anything found
        if all_found:
            cache_path = os.path.join(CACHE_DIR, f'{serial}.json')
            try:
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(all_found, f, ensure_ascii=False, indent=2)
                print('  updated cache at', cache_path)
            except Exception as ex:
                print('  failed to write cache:', ex)
        else:
            print('  no additional entries found for', serial)

if __name__ == '__main__':
    deep_process()
