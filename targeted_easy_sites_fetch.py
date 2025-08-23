import requests
from bs4 import BeautifulSoup
import json
import time
import re
from cheat_online import _normalize_code_lines

HEADERS = {'User-Agent': 'PCSX2-Manager/1.0 (+https://example)'}
SITES = [
    'gamehacking.org',
    'gamefaqs.com',
    'cheatcc.com',
    'neoseeker.com',
    'supercheats.com',
]
SERIALS = ["SLUS-21678", "SCUS-97481", "SLUS-20312", "SLES-53346"]

HEX = re.compile(r'\b[0-9A-Fa-f]{8}\b')


def bing_site_search(site, query, max_links=6):
    q = f'site:{site} {query}'
    url = 'https://www.bing.com/search'
    try:
        r = requests.get(url, params={'q': q}, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
        links = [a.get('href') for a in soup.select('li.b_algo h2 a') if a.get('href')]
        return links[:max_links]
    except Exception:
        return []


def extract_codes_from_page(html):
    out = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for b in soup.find_all(['pre','code']):
            lines = [l.strip() for l in b.get_text().splitlines() if l.strip()]
            out.extend(_normalize_code_lines(lines))
        # fallback: scan body text for hex pairs
        txt = soup.get_text('\n', strip=True)
        hexs = HEX.findall(txt)
        if len(hexs) >= 2:
            for i in range(0, len(hexs)-1, 2):
                out.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
    except Exception:
        pass
    # dedupe
    seen=set(); res=[]
    for c in out:
        if c not in seen:
            seen.add(c); res.append(c)
    return res


def main():
    allresults = {}
    for s in SERIALS:
        print('\n==', s, '==')
        allresults[s] = []
        for site in SITES:
            print(' site search:', site)
            links = bing_site_search(site, s)
            for link in links:
                try:
                    r = requests.get(link, headers=HEADERS, timeout=10)
                    if r.status_code != 200:
                        continue
                    codes = extract_codes_from_page(r.text)
                    if codes:
                        print('  found on', site, link, 'codes=', len(codes))
                        allresults[s].append({'site': site, 'link': link, 'codes': codes})
                    time.sleep(0.4)
                except Exception as e:
                    # skip
                    pass
    with open('targeted_fetch_results.json','w',encoding='utf-8') as f:
        json.dump(allresults,f,ensure_ascii=False,indent=2)
    print('\nWrote targeted_fetch_results.json')

if __name__=='__main__':
    main()
