import requests
from cheat_online import fetch_psxdatacenter_cheats, fetch_gamehacking_org_cheats

serials = ["SLUS-21678", "SCUS-97481", "SLUS-20312", "SLES-53346"]
urls = [
    'https://psxdatacenter.com/ps2/ntscu2.html',
    'https://psxdatacenter.com/ps2/pal2.html',
    'https://psxdatacenter.com/ps2/ntscj2.html',
]

for s in serials:
    print('===', s, '===')
    try:
        pd = fetch_psxdatacenter_cheats(s)
        print('psxdatacenter entries:', len(pd))
    except Exception as e:
        print('psxdatacenter error:', e)
    try:
        gh = fetch_gamehacking_org_cheats(s)
        print('gamehacking entries:', len(gh))
    except Exception as e:
        print('gamehacking error:', e)
    # check raw HTML pages for occurrence
    for u in urls:
        try:
            r = requests.get(u, timeout=10)
            ok = s.upper() in (r.text or '').upper()
            print('url', u, 'contains serial?', ok)
        except Exception as e:
            print('url', u, 'error', e)
    print()
