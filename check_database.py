import json

print("Checking ps2_cheats_database.json...")
with open('ps2_cheats_database.json') as f:
    db = json.load(f)

games = db.get('games', [])
print(f"Total games: {len(games)}")
print(f"\nFirst 10 games:")
for game in games[:10]:
    title = game.get('title', '?')
    regions = len(game.get('regions', {}))
    print(f"  - {title} ({regions} regions)")

# Check if any have cheats
total_cheats = 0
for game in games:
    for region_data in game.get('regions', {}).values():
        total_cheats += len(region_data.get('cheats', []))

print(f"\nTotal cheats: {total_cheats}")
