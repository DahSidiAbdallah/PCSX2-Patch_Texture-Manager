import json
import os

# Test what the CheatsTabWidget is actually seeing
db_path = 'ps2_cheats_database_merged.json'

print(f"File exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    with open(db_path) as f:
        db = json.load(f)
    
    games = db.get('games', [])
    total_cheats = sum(len(r.get('cheats',[])) for g in games for r in g.get('regions',{}).values())
    
    print(f"Games: {len(games)}")
    print(f"Total cheats: {total_cheats}")
    
    # Show first 5 games
    print("\nFirst 5 games:")
    for game in games[:5]:
        print(f"  - {game.get('title')} ({len(game.get('regions', {}))} regions)")
