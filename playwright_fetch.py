from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import json
import os

HEADERS = {'User-Agent': 'PCSX2-Manager/1.0 (+https://example)'}
CACHE_DIR = 'cheat_cache'
os.makedirs(CACHE_DIR, exist_ok=True)

TARGETS = [
    ('SLUS-21678', 'https://www.scribd.com/document/848012292/SLUS-21678-428113C2-drabon-ball-budokai-tekainchi-3-pnach'),
    ('SLUS-20312', 'https://forums.pcsx2.net/Thread-final-fantasy-X-ntsc-U-SLUS-20312-BB3D833A-cheats-not-working-NEED-CHEATS')
]

HEX_PAIR = re.compile(r'\b[0-9A-Fa-f]{8}\b')
PNACH_LINE = re.compile(r'^patch=', re.I)


def extract_codes_from_html(html):
    codes = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for b in soup.find_all(['pre','code']):
            txt = b.get_text('\n', strip=True)
            for ln in txt.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                if PNACH_LINE.match(ln):
                    codes.append(ln)
                    continue
                hexs = HEX_PAIR.findall(ln)
                if len(hexs) >= 2:
                    for i in range(0, len(hexs)-1, 2):
                        codes.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
                else:
                    m = re.search(r'([0-9A-Fa-f]{1,8})\s+([0-9A-Fa-f]{1,8})', ln)
                    if m:
                        a = m.group(1).upper().rjust(8,'0')
                        v = m.group(2).upper().rjust(8,'0')
                        codes.append(f"{a} {v}")
        # search post content containers
        for cls in ('postbody','message','postcontent','post','content','messageContent'):
            for div in soup.find_all(class_=re.compile(cls, re.I)):
                txt = div.get_text('\n', strip=True)
                hexs = HEX_PAIR.findall(txt)
                if len(hexs) >= 2:
                    for i in range(0, len(hexs)-1, 2):
                        codes.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
    except Exception:
        pass
    # dedupe preserving order
    seen = set(); out = []
    for c in codes:
        if c not in seen:
            seen.add(c); out.append(c)
    return out


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS['User-Agent'])
        page = context.new_page()
        results = {}
        for serial, url in TARGETS:
            print('Visiting', url)
            try:
                page.goto(url, timeout=30000)
                # wait for network idle and short delay for dynamic content
                page.wait_for_load_state('networkidle', timeout=15000)
                page.wait_for_timeout(1000)
                content = page.content()
                # also try innerText of body
                try:
                    body_text = page.inner_text('body')
                except Exception:
                    body_text = ''
                codes = extract_codes_from_html(content)
                # if no codes, try scanning body text for hex pairs
                if not codes and body_text:
                    hexs = HEX_PAIR.findall(body_text)
                    if len(hexs) >= 2:
                        for i in range(0, len(hexs)-1, 2):
                            codes.append(f"{hexs[i].upper()} {hexs[i+1].upper()}")
                print(' Found codes:', len(codes))
                results[serial] = [{'source': 'playwright', 'link': url, 'codes': codes}]
                # save cache
                path = os.path.join(CACHE_DIR, f"{serial}.json")
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(results[serial], f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(' Error visiting', url, e)
                results[serial] = []
        browser.close()
    # write summary
    with open('playwright_fetch_summary.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print('Done. Summary written to playwright_fetch_summary.json')

if __name__ == '__main__':
    run()
