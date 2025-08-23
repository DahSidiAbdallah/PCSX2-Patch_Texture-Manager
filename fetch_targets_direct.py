import requests
from bs4 import BeautifulSoup
import re

HEADERS = {'User-Agent': 'PCSX2-Manager/1.0 (+https://example)'}

targets = [
    ('SLUS-21678', 'https://www.scribd.com/document/848012292/SLUS-21678-428113C2-drabon-ball-budokai-tekainchi-3-pnach'),
    ('SLUS-20312', 'https://forums.pcsx2.net/Thread-final-fantasy-X-ntsc-U-SLUS-20312-BB3D833A-cheats-not-working-NEED-CHEATS')
]

HEX_PAIR = re.compile(r'\b[0-9A-Fa-f]{8}\b')


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
                if ln.lower().startswith('patch='):
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
        # forum post bodies
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


for serial, url in targets:
    print('\n---', serial, url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print('status_code=', r.status_code, 'final_url=', r.url)
        codes = extract_codes_from_html(r.text)
        print('codes found direct:', len(codes))
        for c in codes[:10]:
            print('  ', c)
    except Exception as e:
        print('direct fetch failed:', e)

    # If Scribd, try text proxy (r.jina.ai)
    if 'scribd.com' in url:
        proxy = 'https://r.jina.ai/http://' + url.replace('https://','').replace('http://','')
        try:
            rp = requests.get(proxy, headers=HEADERS, timeout=15)
            print('proxy status=', rp.status_code)
            codes2 = extract_codes_from_html(rp.text)
            print('codes found via proxy:', len(codes2))
            for c in codes2[:10]:
                print('  ', c)
        except Exception as e:
            print('proxy fetch failed:', e)

    # If forum, try appending ?view=print or m=1 for mobile
    if 'forums.pcsx2.net' in url:
        alt = url + '?view=print'
        try:
            ra = requests.get(alt, headers=HEADERS, timeout=15)
            print('alt view status=', ra.status_code)
            codes3 = extract_codes_from_html(ra.text)
            print('codes found in alt view:', len(codes3))
            for c in codes3[:10]:
                print('  ', c)
        except Exception as e:
            print('alt fetch failed:', e)

print('\nDone')
