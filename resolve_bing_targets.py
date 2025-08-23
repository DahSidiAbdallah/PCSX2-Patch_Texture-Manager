import json
import requests
from bs4 import BeautifulSoup

with open('cheat_fetch_summary.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for serial, entries in data.items():
    print('\n==', serial, '==')
    if not entries:
        print('  (no entries)')
        continue
    for e in entries:
        link = e.get('link')
        print('\n  original link:', link)
        try:
            r = requests.get(link, headers={'User-Agent':'PCSX2-Manager/1.0'}, timeout=10, allow_redirects=True)
            print('   final url:', r.url)
            soup = BeautifulSoup(r.text, 'html.parser')
            blocks = soup.find_all(['pre','code'])
            if blocks:
                print('   code blocks found:', len(blocks))
                for i, b in enumerate(blocks[:3], 1):
                    text = b.get_text('\n', strip=True)
                    sample = '\n'.join(text.splitlines()[:12])
                    print(f'    block #{i} sample:\n{sample}')
            else:
                # fallback: show nearby text around serial
                U = (r.text or '').upper()
                idx = U.find(serial.upper())
                if idx!=-1:
                    seg = r.text[max(0, idx-400):idx+400]
                    print('   snippet around serial:')
                    print(seg[:800])
                else:
                    print('   no code blocks and serial not found in page body')
        except Exception as ex:
            print('   fetch error:', ex)
