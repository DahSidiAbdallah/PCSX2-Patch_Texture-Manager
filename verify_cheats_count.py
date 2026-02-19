import os
import json
import re
from pathlib import Path

print("=" * 80)
print("SCANNING LOCAL PS2 CHEATS FOLDER")
print("=" * 80)

cheats_folder = "./PS2 Cheats"

# Count total pnach files
total_files = 0
files_with_cheats = 0
total_cheats_found = 0
games_dict = {}  # Track unique games by (serial, crc, title)

for root, dirs, files in os.walk(cheats_folder):
    for file in files:
        if file.endswith('.pnach'):
            total_files += 1
            filepath = os.path.join(root, file)
            
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Count patch= lines (each one is a code)
                cheat_count = len(re.findall(r'^patch=', content, re.MULTILINE))
                
                if cheat_count > 0:
                    files_with_cheats += 1
                    total_cheats_found += cheat_count
                    
                    # Extract info from filename
                    filename = os.path.basename(filepath)
                    
                    # Try to parse: CRC_HEX - Title SERIAL.pnach
                    match = re.match(r'^([0-9A-Fa-f]{8})\s*-\s*(.+?)(?:\s+([A-Z]+(?:-[0-9]+)?))?\.pnach$', filename.replace('.pnach', ''))
                    
                    if match:
                        crc = match.group(1)
                        title = match.group(2).strip()
                        serial = match.group(3) if match.group(3) else "?"
                    else:
                        crc = "?"
                        title = filename.replace('.pnach', '')
                        serial = "?"
                    
                    key = (serial, crc, title)
                    if key not in games_dict:
                        games_dict[key] = 0
                    games_dict[key] += cheat_count
                    
            except Exception as e:
                pass

print(f"\n📊 STATISTICS:")
print(f"  Total .pnach files:        {total_files:,}")
print(f"  Files with cheats:         {files_with_cheats:,}")
print(f"  Total cheat patches:       {total_cheats_found:,}")
print(f"  Unique games:              {len(games_dict):,}")

# Now check merged database
print(f"\n{'='*80}")
print("MERGED DATABASE COMPARISON")
print(f"{'='*80}")

if os.path.exists('ps2_cheats_database_merged.json'):
    with open('ps2_cheats_database_merged.json') as f:
        db = json.load(f)
    
    db_games = len(db.get('games', []))
    db_cheats = sum(len(r.get('cheats', [])) for g in db['games'] for r in g.get('regions', {}).values())
    
    print(f"\n📦 MERGED DATABASE:")
    print(f"  Games in database:         {db_games:,}")
    print(f"  Total cheats in database:  {db_cheats:,}")
else:
    db_games = 0
    db_cheats = 0
    print(f"\n❌ Merged database NOT found!")

print(f"\n📈 COMPARISON:")
print(f"  Local folder games:        {len(games_dict):,}")
print(f"  Database games:            {db_games:,}")
print(f"  Difference:                {len(games_dict) - db_games:+,} games")
print(f"")
print(f"  Local folder cheats:       {total_cheats_found:,}")
print(f"  Database cheats:           {db_cheats:,}")
print(f"  Difference:                {total_cheats_found - db_cheats:+,} cheats")

if total_cheats_found == db_cheats and len(games_dict) == db_games:
    print(f"\n✅ ALL CHEATS CAPTURED! No missing cheats detected.")
else:
    print(f"\n⚠️  DISCREPANCY DETECTED!")
    if total_cheats_found > db_cheats:
        print(f"   Missing {total_cheats_found - db_cheats} cheats in database")
    if len(games_dict) > db_games:
        print(f"   Missing {len(games_dict) - db_games} games in database")

print(f"\n{'='*80}")
