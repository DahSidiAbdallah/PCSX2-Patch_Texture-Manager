import json
import sys

serials = ["SLUS-21678", "SCUS-97481", "SLUS-20312", "SLES-53346"]

try:
    from cheat_online import fetch_and_cache_cheats
except Exception as e:
    print("ERROR: could not import cheat_online:", e)
    sys.exit(2)

for s in serials:
    print("===", s, "===")
    try:
        res = fetch_and_cache_cheats(s)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    except Exception as e:
        print("FETCH ERROR for", s, str(e))
    print()
