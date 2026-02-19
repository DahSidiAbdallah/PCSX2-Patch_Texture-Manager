import re

def parse_filename(filename):
    name = filename.replace('.pnach', '')
    print(f"Parsing: {name}")
    
    match = re.match(r'^([0-9A-Fa-f]{8})\s*-\s*(.+?)(?:\s+([A-Z]+(?:-[0-9]+)?))?\s*$', name)
    if match:
        crc = match.group(1).upper()
        game_name = match.group(2).strip()
        serial = match.group(3) if match.group(3) else None
        print(f"  ✓ CRC: {crc}, Serial: {serial}, Title: {game_name}")
        return crc, serial, game_name
    else:
        print(f"  ✗ NO MATCH")
        return None, None, name

# Test files
test_files = [
    "0001171A - .hack - Outbreak Part 3 SLUS-20563.pnach",
    "000B73EE - Simple 2000 Series Vol. 65 - The Kyonshi Panic SLPM-62543.pnach",
    "02E1970F.pnach",
    "SCUS-97481_2F123FD8.pnach"
]

for f in test_files:
    parse_filename(f)
