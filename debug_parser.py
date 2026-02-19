#!/usr/bin/env python3
"""Debug parser to understand deduplication."""

from scan_local_cheats import LocalCheatsScanner
import os
from collections import defaultdict

# Scan all files and group by (crc, serial) key
crc_serial_groups = defaultdict(list)

for result in LocalCheatsScanner.scan_folder('./PS2 Cheats'):
    if result.get('cheats'):
        key = (result.get('crc', ''), result.get('serial', ''))
        crc_serial_groups[key].append((result['filename'], result['cheats_count']))

print(f"Total (CRC,Serial) keys: {len(crc_serial_groups)}")
print(f"Total .pnach files: {sum(len(v) for v in crc_serial_groups.values())}")

# Find keys with multiple files
multi_file_groups = {k: v for k, v in crc_serial_groups.items() if len(v) > 1}
print(f"\nKeys with multiple files: {len(multi_file_groups)}")
print(f"Total files in multi-file groups: {sum(len(v) for v in multi_file_groups.values())}")

# Show some examples
print("\nExamples of files grouped by same (CRC,Serial):")
for key, files in list(multi_file_groups.items())[:5]:
    print(f"\nKey {key}:")
    for filename, cheat_count in files:
        print(f"  - {filename} ({cheat_count} cheats)")

# Count files with empty CRC or serial
empty_key_count = 0
for key, files in crc_serial_groups.items():
    if key[0] == '' or key[1] == '':
        empty_key_count += len(files)

print(f"\n\nFiles with empty CRC or Serial: {empty_key_count}")
