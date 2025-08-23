import json
import time
import re
import os
from urllib.parse import urlparse, quote_plus

import requests
from bs4 import BeautifulSoup

from cheat_online import _normalize_code_lines, fetch_psxdatacenter_cheats, fetch_gamehacking_org_cheats

SERIALS = ["SLUS-21678", "SCUS-97481", "SLUS-20312", "SLES-53346"]
CACHE_DIR = 'cheat_cache'
os.makedirs(CACHE_DIR, exist_ok=True)
HEADERS = {'User-Agent': 'PCSX2-Manager/1.0 (+https://example)'}

# domains we prioritize
PRIOR_DOMAINS = ('gamehacking.org', 'psxdatacenter.com', 'gamefaqs.com')


def bing_search_links(query, max_links=8):
    url = f'https://www.bing.com/search?q={quote_plus(query)}'
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        links = []
        for li in soup.select('li.b_algo h2 a'):
            href = li.get('href')
            if href:
                links.append(href)
                if len(links) >= max_links:
                    break
        return links
    except Exception:
        return []


def extract_codes_from_url(url, serial):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        txt = r.text or ''
    except Exception:
        return []
    out = []
    try:
        soup = BeautifulSoup(txt, 'html.parser')
        # look for code/pre blocks
        blocks = soup.find_all(['pre', 'code'])
        for b in blocks:
            lines = [l.strip() for l in b.get_text().splitlines() if l.strip()]
            norms = _normalize_code_lines(lines)
            if norms:
                out.extend(norms)
        # fallback: look for long hex sequences in text nearby the serial
        if not out:
            U = txt.upper()
            idx = U.find(serial.upper())
            if idx != -1:
                start = max(0, idx-2000)
                end = min(len(txt), idx+2000)
                seg = txt[start:end]
                hexs = re.findall(r'\b[0-9A-Fa-f]{8}\b', seg)
                if len(hexs) >= 2:
                    for i in range(0, len(hexs)-1, 2):
                        out.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
    except Exception:
        pass
    return out


def process_serial(serial):
    results = []
    # 1) try existing specialized parsers
    try:
        results.extend(fetch_psxdatacenter_cheats(serial))
    except Exception:
        pass
    try:
        results.extend(fetch_gamehacking_org_cheats(serial))
    except Exception:
        pass

    # 2) broad Bing queries
    queries = [
        f'{serial} cheats',
        f'{serial} cheat codes',
        f'{serial} site:gamehacking.org',
        f'{serial} site:psxdatacenter.com',
        f'{serial} site:gamefaqs.com',
    ]
    visited = set()
    for q in queries:
        links = bing_search_links(q, max_links=6)
        # prioritize our domains
        links = sorted(links, key=lambda u: 0 if urlparse(u).netloc.endswith(PRIOR_DOMAINS) else 1)
        for link in links:
            if link in visited:
                continue
            visited.add(link)
            codes = extract_codes_from_url(link, serial)
            if codes:
                results.append({'source': 'broad_web', 'link': link, 'title': None, 'codes': codes})
            # be polite
            time.sleep(0.5)
    # dedupe codes
    for e in results:
        if 'codes' in e:
            e['codes'] = list(dict.fromkeys(e['codes']))
    # save cache
    cache_path = os.path.join(CACHE_DIR, f'{serial}.json')
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return results


if __name__ == '__main__':
    import sys
    allres = {}
    for s in SERIALS:
        print('Processing', s)
        r = process_serial(s)
        print('  found entries:', len(r))
        for e in r[:3]:
            print('   -', e.get('source'), 'codes:', len(e.get('codes', [])), 'link:', e.get('link'))
        allres[s] = r
    # write summary
    with open('cheat_fetch_summary.json', 'w', encoding='utf-8') as f:
        json.dump(allres, f, ensure_ascii=False, indent=2)
    print('Done. Summary in cheat_fetch_summary.json')
