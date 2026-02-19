#!/usr/bin/env python3
import json

db = json.load(open('ps2_cheats_database_merged.json'))
print(f'✓ Database loaded successfully')
print(f'  Total games: {len(db["games"])}')
print(f'  Sample game: {db["games"][0]["title"]}')
print(f'  Regions: {list(db["games"][0].get("regions", {}).keys())}')
