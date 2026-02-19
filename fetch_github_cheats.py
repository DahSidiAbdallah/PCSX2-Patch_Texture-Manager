#!/usr/bin/env python3
"""
Fetch and parse PS2 cheats from GitHub repository and integrate into database.
Handles .pnach file format parsing and merges with existing cheat database.
"""

import os
import json
import re
import zipfile
import tempfile
import shutil
from urllib.request import urlopen
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# GitHub repo URL
GITHUB_REPO = "https://github.com/xs1l3n7x/pcsx2_cheats_collection"
GITHUB_ZIP_URL = "https://github.com/xs1l3n7x/pcsx2_cheats_collection/archive/refs/heads/main.zip"


class PnachParser:
    """Parse PCSX2 .pnach cheat files."""
    
    @staticmethod
    def parse_filename(filename: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract CRC and serial from pnach filename.
        Format: CRC_HEX - Game Name SERIAL.pnach or CRC_HEX - Game Name.pnach
        """
        # Remove .pnach extension
        name = filename.replace('.pnach', '')
        
        # Try to extract CRC from start (8 hex chars)
        match = re.match(r'^([0-9A-Fa-f]{8})\s*-\s*(.+?)(?:\s+([A-Z]+(?:-[0-9]+)?))?\s*$', name)
        if match:
            crc = match.group(1).upper()
            game_name = match.group(2).strip()
            serial = match.group(3) if match.group(3) else None
            return crc, serial, game_name
        
        # Fallback: just return what we have
        return None, None, name
    
    @staticmethod
    def parse_pnach_content(content: str) -> Dict:
        """
        Parse PNACH file content.
        Format:
        gametitle=Game Name
        serial=SLUS-20123
        cheats=X
        [Cheat Name]
        code0=patch=1,EE,address,extended,value
        """
        result = {
            'gametitle': None,
            'serial': None,
            'cheats': []
        }
        
        lines = content.split('\n')
        current_cheat = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            
            # Parse header info
            if line.startswith('gametitle='):
                result['gametitle'] = line.split('=', 1)[1].strip()
            elif line.startswith('serial='):
                result['serial'] = line.split('=', 1)[1].strip()
            elif line.startswith('cheats='):
                continue  # Just a count
            elif line.startswith('[') and line.endswith(']'):
                # New cheat section
                if current_cheat and current_cheat.get('codes'):
                    result['cheats'].append(current_cheat)
                cheat_name = line[1:-1].strip()
                cheat_name = cheat_name.replace('Cheats/', '', 1) if cheat_name.startswith('Cheats/') else cheat_name
                current_cheat = {
                    'name': cheat_name,
                    'codes': []
                }
            elif current_cheat and (line.startswith('code') or line.startswith('patch=')):
                # Parse cheat code - handle both code= and patch= formats
                if line.startswith('code'):
                    code_match = re.match(r'code\d+=(.+)', line)
                    if code_match:
                        current_cheat['codes'].append(code_match.group(1).strip())
                elif line.startswith('patch='):
                    # Add patch line as-is (it's already a complete code)
                    current_cheat['codes'].append(line)
        
        # Add last cheat
        if current_cheat:
            result['cheats'].append(current_cheat)
        
        return result
    
    @staticmethod
    def extract_crc_from_pnach_content(content: str) -> Optional[str]:
        """Extract CRC from PNACH file if available."""
        # Look for CRC in comments or metadata
        for line in content.split('\n'):
            if 'CRC' in line or 'crc' in line:
                match = re.search(r'[0-9A-Fa-f]{8}', line)
                if match:
                    return match.group(0).upper()
        return None


def download_github_cheats(extract_path: str) -> str:
    """Download and extract the GitHub cheat collection."""
    logger.info(f"Downloading cheats from {GITHUB_ZIP_URL}...")
    
    try:
        with urlopen(GITHUB_ZIP_URL, timeout=30) as response:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
                tmp.write(response.read())
                tmp_path = tmp.name
        
        # Extract ZIP
        logger.info(f"Extracting to {extract_path}...")
        os.makedirs(extract_path, exist_ok=True)
        
        with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        
        os.unlink(tmp_path)
        
        # Find the cheats folder (it's in main subfolder)
        cheats_folder = None
        for root, dirs, files in os.walk(extract_path):
            if 'cheats' in dirs:
                cheats_folder = os.path.join(root, 'cheats')
                break
        
        if not cheats_folder:
            raise FileNotFoundError("Cheats folder not found in downloaded archive")
        
        logger.info(f"Found cheats folder at {cheats_folder}")
        return cheats_folder
    
    except Exception as e:
        logger.error(f"Failed to download cheats: {e}")
        raise


def scan_pnach_files(cheats_folder: str) -> List[str]:
    """Scan folder for .pnach files."""
    pnach_files = []
    for root, dirs, files in os.walk(cheats_folder):
        for file in files:
            if file.endswith('.pnach'):
                pnach_files.append(os.path.join(root, file))
    
    return sorted(pnach_files)


def merge_cheats_to_database(db_path: str, pnach_files: List[str], crc_to_serial_map: Optional[Dict] = None) -> Dict:
    """
    Merge parsed PNACH cheats into the database JSON.
    """
    # Load existing database
    if os.path.exists(db_path):
        with open(db_path, 'r', encoding='utf-8') as f:
            database = json.load(f)
    else:
        database = {'games': []}
    
    # Create lookup maps
    game_lookup = {}  # Key: (crc, serial) -> index
    for idx, game in enumerate(database.get('games', [])):
        for region, region_data in game.get('regions', {}).items():
            crc = region_data.get('crc', '')
            serial = region_data.get('serial', '')
            if crc or serial:
                game_lookup[(crc.upper() if crc else '', serial.upper() if serial else '')] = idx
    
    parser = PnachParser()
    added_count = 0
    updated_count = 0
    
    for pnach_file in pnach_files:
        try:
            with open(pnach_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            filename = os.path.basename(pnach_file)
            parsed = parser.parse_pnach_content(content)
            
            # Extract identifiers
            crc_from_file = parser.extract_crc_from_pnach_content(content)
            crc_from_filename = None
            
            try:
                crc_from_filename, serial_from_filename, _ = parser.parse_filename(filename)
            except:
                pass
            
            crc = (crc_from_file or crc_from_filename or '').upper()
            serial = (parsed.get('serial') or serial_from_filename or '').upper()
            game_title = parsed.get('gametitle') or filename.replace('.pnach', '')
            
            if not crc and not serial:
                logger.warning(f"Skipping {filename}: No CRC or serial found")
                continue
            
            # Determine region from serial
            region = determine_region(serial)
            
            # Check if we have this game already
            lookup_key = (crc, serial)
            if lookup_key in game_lookup:
                # Update existing game
                game_idx = game_lookup[lookup_key]
                game = database['games'][game_idx]
                
                if region not in game['regions']:
                    game['regions'][region] = {}
                
                game['regions'][region].update({
                    'crc': crc,
                    'serial': serial,
                    'cheats': parsed.get('cheats', [])
                })
                
                updated_count += 1
            else:
                # Add new game
                new_game = {
                    'title': game_title,
                    'regions': {
                        region: {
                            'crc': crc,
                            'serial': serial,
                            'cheats': parsed.get('cheats', [])
                        }
                    }
                }
                
                database['games'].append(new_game)
                game_lookup[lookup_key] = len(database['games']) - 1
                added_count += 1
        
        except Exception as e:
            logger.error(f"Error processing {pnach_file}: {e}")
            continue
    
    logger.info(f"Merge complete: {added_count} new games, {updated_count} updated")
    
    return database


def determine_region(serial: str) -> str:
    """Determine region from serial code."""
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
    else:
        return 'Unknown'


def main():
    """Main execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch and merge GitHub PS2 cheats into database')
    parser.add_argument('--db', default='ps2_cheats_database.json', help='Path to cheats database JSON')
    parser.add_argument('--local-folder', help='Use local cheats folder instead of downloading')
    parser.add_argument('--output', help='Save merged database to this path (defaults to --db)')
    parser.add_argument('--github-folder', default='./github_cheats_temp', help='Temporary folder for GitHub download')
    parser.add_argument('--keep-temp', action='store_true', help='Keep temporary folder after processing')
    
    args = parser.parse_args()
    
    try:
        # Get cheats folder
        if args.local_folder:
            cheats_folder = args.local_folder
            logger.info(f"Using local folder: {cheats_folder}")
        else:
            cheats_folder = download_github_cheats(args.github_folder)
        
        # Scan for pnach files
        pnach_files = scan_pnach_files(cheats_folder)
        logger.info(f"Found {len(pnach_files)} .pnach files")
        
        # Merge into database
        database = merge_cheats_to_database(args.db, pnach_files)
        
        # Save database
        output_path = args.output or args.db
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Database saved to {output_path}")
        logger.info(f"Total games in database: {len(database['games'])}")
        
        # Cleanup
        if not args.keep_temp and not args.local_folder:
            shutil.rmtree(args.github_folder, ignore_errors=True)
    
    except Exception as e:
        logger.error(f"Failed to merge cheats: {e}")
        raise


if __name__ == '__main__':
    main()
