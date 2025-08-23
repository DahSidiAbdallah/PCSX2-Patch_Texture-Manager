from cheat_online import fetch_and_cache_cheats

for key in ['F4715852', 'SLUS-21234', 'SCUS-97402']:
    print('---', key)
    try:
        res = fetch_and_cache_cheats(key)
        print(type(res), len(res))
        for r in res[:3]:
            print(r.get('source'), r.get('title') if isinstance(r, dict) else r)
    except Exception as e:
        print('error', e)
