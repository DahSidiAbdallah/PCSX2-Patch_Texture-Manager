#!/usr/bin/env python3
"""
Scan local PS2 Cheats folder and extract cheat data.
Integrates with fetch_github_cheats.py for comprehensive cheat database.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class LocalCheatsScanner:
    """Scan and parse local PNACH cheat files."""
    
    # Regex to extract info from filename
    # Format: CRC_HEX - Game Title SERIAL.pnach
    # CRC can be 4-8 hex digits (will be normalized to 8)
    # Title can contain spaces and dashes  
    # Serial is uppercase letters + numbers with optional dashes/spaces
    FILENAME_PATTERN = re.compile(
        r'^([0-9A-Fa-f]{4,8})\s*-\s*(.+?)\s+([A-Z0-9\s\-\.]+?)\.pnach$',
        re.IGNORECASE
    )
    
    @staticmethod
    def parse_pnach_file(filepath: str) -> Dict:
        """Parse a single PNACH file and extract cheat information."""
        result = {
            'filepath': filepath,
            'filename': os.path.basename(filepath),
            'crc': None,
            'serial': None,
            'game_title': None,
            'cheats': [],
            'cheats_count': 0
        }
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Parse file content
            lines = content.split('\n')
            current_cheat = None
            
            for line in lines:
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith('//'):
                    continue
                
                # Extract header info
                if line.startswith('gametitle='):
                    result['game_title'] = line.split('=', 1)[1].strip()
                elif line.startswith('serial='):
                    result['serial'] = line.split('=', 1)[1].strip().upper()
                elif line.startswith('[') and line.endswith(']'):
                    # Start of new cheat
                    if current_cheat and current_cheat.get('codes'):
                        result['cheats'].append(current_cheat)
                    
                    cheat_name = line[1:-1].strip()
                    cheat_name = cheat_name.replace('Cheats/', '', 1) if cheat_name.startswith('Cheats/') else cheat_name
                    current_cheat = {
                        'name': cheat_name,
                        'codes': [],
                        'description': ''
                    }
                
                elif current_cheat is not None and (line.startswith('code') or line.startswith('patch=')):
                    # Parse cheat code - handle both code= and patch= formats
                    if line.startswith('code'):
                        match = re.match(r'code\d+=(.+)', line)
                        if match:
                            current_cheat['codes'].append(match.group(1).strip())
                    elif line.startswith('patch='):
                        # Add patch line as-is (it's already a complete code)
                        current_cheat['codes'].append(line)
            
            # Add last cheat
            if current_cheat and current_cheat.get('codes'):
                result['cheats'].append(current_cheat)
            
            result['cheats_count'] = len(result['cheats'])
            
            # Extract CRC and serial from filename if not in file
            crc_from_filename, serial_from_filename = LocalCheatsScanner.parse_filename(result['filename'])
            
            if not result['crc']:
                result['crc'] = crc_from_filename
            if not result['serial']:
                result['serial'] = serial_from_filename
            if not result['game_title']:
                result['game_title'] = result['filename'].replace('.pnach', '')
            
            # Normalize values
            if result['crc']:
                result['crc'] = result['crc'].upper()
            if result['serial']:
                result['serial'] = result['serial'].upper()
        
        except Exception as e:
            logger.error(f"Error parsing {filepath}: {e}")
            result['error'] = str(e)
        
        return result
    
    @staticmethod
    def parse_filename(filename: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract CRC and serial from PNACH filename."""
        match = LocalCheatsScanner.FILENAME_PATTERN.match(filename)
        if match:
            crc = match.group(1).upper()
            # Pad CRC to 8 digits with leading zeros
            crc = crc.zfill(8)
            serial_str = match.group(3).upper().strip() if match.group(3) else None
            if serial_str:
                # Extract the first serial code if multiple are present
                # Take the first continuous alphanumeric+dash sequence
                serial_match = re.search(r'([A-Z]+[A-Z0-9\-]*[0-9]+)', serial_str)
                serial = serial_match.group(1) if serial_match else serial_str
                # Normalize spaces to nothing in serials
                serial = serial.replace(' ', '')
                return crc, serial
            return crc, None
        return None, None
    
    @staticmethod
    def scan_folder(folder_path: str) -> List[Dict]:
        """Scan a folder for all PNACH files and parse them."""
        results = []
        
        if not os.path.isdir(folder_path):
            logger.error(f"Folder not found: {folder_path}")
            return results
        
        pnach_files = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.endswith('.pnach'):
                    pnach_files.append(os.path.join(root, file))
        
        logger.info(f"Found {len(pnach_files)} PNACH files in {folder_path}")
        
        for filepath in pnach_files:
            parsed = LocalCheatsScanner.parse_pnach_file(filepath)
            results.append(parsed)
        
        return results
    
    @staticmethod
    def determine_region(serial: str) -> str:
        """Determine region from PS2 serial code."""
        if not serial:
            return 'Unknown'
        
        serial = serial.upper()
        
        if serial.startswith('SLUS'):
            return 'NTSC-U'
        elif serial.startswith('SLES'):
            return 'PAL'
        elif serial.startswith('SLPS') or serial.startswith('SCPS'):
            return 'NTSC-J'
        elif serial.startswith('SLKA'):
            return 'NTSC-K'
        elif serial.startswith('SLPM'):
            return 'NTSC-J'
        else:
            return 'Unknown'
    
    @staticmethod
    def build_database(scan_results: List[Dict]) -> Dict:
        """Convert scan results into database format."""
        games_by_key = {}  # Key: (crc, serial)
        
        for result in scan_results:
            if not result.get('cheats'):
                continue
            
            key = (result.get('crc', ''), result.get('serial', ''))
            
            if key not in games_by_key:
                # Create new game entry
                region = LocalCheatsScanner.determine_region(result.get('serial'))
                games_by_key[key] = {
                    'title': result.get('game_title', 'Unknown'),
                    'regions': {
                        region: {
                            'serial': result.get('serial'),
                            'crc': result.get('crc'),
                            'cheats': result.get('cheats', [])
                        }
                    }
                }
            else:
                # MERGE cheats from duplicate files (without deduplication)
                # Let merge_cheats_databases.py handle deduplication
                existing_game = games_by_key[key]
                region = LocalCheatsScanner.determine_region(result.get('serial'))
                
                if region not in existing_game['regions']:
                    # New region
                    existing_game['regions'][region] = {
                        'serial': result.get('serial'),
                        'crc': result.get('crc'),
                        'cheats': result.get('cheats', [])
                    }
                else:
                    # Merge ALL cheats (no name-based dedup)
                    # Preserves all cheat codes from all files
                    existing_game['regions'][region]['cheats'].extend(result.get('cheats', []))
        
        return {
            'games': list(games_by_key.values()),
            'source': 'local_scan',
            'total_games': len(games_by_key),
            'total_files': len(scan_results)
        }


def main():
    """Main execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scan local PS2 cheats folder and build database')
    parser.add_argument('--folder', default='./PS2 Cheats', help='Path to PS2 cheats folder')
    parser.add_argument('--output', default='local_cheats_database.json', help='Output database JSON path')
    parser.add_argument('--summary', action='store_true', help='Print summary instead of saving database')
    
    args = parser.parse_args()
    
    try:
        # Scan folder
        logger.info(f"Scanning {args.folder}...")
        results = LocalCheatsScanner.scan_folder(args.folder)
        
        logger.info(f"Scanned {len(results)} files")
        
        # Count games and cheats
        games_with_cheats = sum(1 for r in results if r.get('cheats'))
        total_cheats = sum(r.get('cheats_count', 0) for r in results)
        
        logger.info(f"Games with cheats: {games_with_cheats}")
        logger.info(f"Total cheat entries: {total_cheats}")
        
        if args.summary:
            # Print summary
            print("\n=== LOCAL CHEATS SUMMARY ===")
            print(f"Total files scanned: {len(results)}")
            print(f"Games with cheats: {games_with_cheats}")
            print(f"Total cheat entries: {total_cheats}")
            
            # Group by region
            regions = {}
            for result in results:
                if result.get('serial'):
                    region = LocalCheatsScanner.determine_region(result['serial'])
                    if region not in regions:
                        regions[region] = 0
                    regions[region] += 1
            
            print("\nGames by region:")
            for region, count in sorted(regions.items()):
                print(f"  {region}: {count}")
        
        else:
            # Build and save database
            database = LocalCheatsScanner.build_database(results)
            
            os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
            
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(database, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Database saved to {args.output}")
            logger.info(f"Total games in database: {database['total_games']}")
    
    except Exception as e:
        logger.error(f"Failed: {e}")
        raise


if __name__ == '__main__':
    main()
