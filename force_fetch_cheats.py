import json
from cheat_online import fetch_and_cache_cheats

fetch_and_cache_cheats.force = True
fetch_and_cache_cheats.max_age_hours = 0
serials = ["SLUS-21678", "SCUS-97481", "SLUS-20312", "SLES-53346"]
for s in serials:
    print('===', s, '===')
    try:
        res = fetch_and_cache_cheats(s)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    except Exception as e:
        print('ERROR', e)
    print()
