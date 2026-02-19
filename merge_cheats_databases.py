#!/usr/bin/env python3
"""
Unified cheat database merger.
Combines local cheats, GitHub cheats, and existing database into comprehensive collection.
"""

import os
import json
import logging
from typing import Dict, List
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class CheatsDatabase:
    """Manage and merge cheat databases."""
    
    @staticmethod
    def normalize_game_title(title: str) -> str:
        """Normalize game title for comparison."""
        return title.lower().strip()
    
    @staticmethod
    def load_database(filepath: str) -> Dict:
        """Load JSON database."""
        if not os.path.exists(filepath):
            logger.warning(f"Database not found: {filepath}")
            return {'games': []}
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
            return {'games': []}
    
    @staticmethod
    def save_database(database: Dict, filepath: str):
        """Save JSON database."""
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Database saved: {filepath}")
    
    @staticmethod
    def merge_databases(databases: List[Dict], prefer_larger: bool = True) -> Dict:
        """
        Merge multiple databases into one comprehensive database.
        
        Args:
            databases: List of database dicts to merge
            prefer_larger: If True, prefer entries with more cheats
        """
        merged = {'games': []}
        game_lookup = {}  # Key: normalized (game_title, serial, crc)
        
        for db_idx, db in enumerate(databases):
            for game in db.get('games', []):
                game_title = game.get('title', 'Unknown')
                norm_title = CheatsDatabase.normalize_game_title(game_title)
                
                for region, region_data in game.get('regions', {}).items():
                    serial = region_data.get('serial', '')
                    crc = region_data.get('crc', '')
                    cheats = region_data.get('cheats', [])
                    
                    # Create lookup key
                    key = (norm_title, serial.upper() if serial else '', crc.upper() if crc else '')
                    
                    if key not in game_lookup:
                        # New entry
                        game_lookup[key] = {
                            'title': game_title,
                            'regions': {}
                        }
                    
                    # Merge region data
                    if region not in game_lookup[key]['regions']:
                        game_lookup[key]['regions'][region] = {
                            'serial': serial,
                            'crc': crc,
                            'cheats': cheats
                        }
                    else:
                        # Decide whether to replace
                        existing_cheats = game_lookup[key]['regions'][region].get('cheats', [])
                        new_cheats = cheats
                        
                        if prefer_larger and len(new_cheats) > len(existing_cheats):
                            game_lookup[key]['regions'][region]['cheats'] = new_cheats
                            game_lookup[key]['regions'][region]['serial'] = serial or game_lookup[key]['regions'][region]['serial']
                            game_lookup[key]['regions'][region]['crc'] = crc or game_lookup[key]['regions'][region]['crc']
                        elif len(new_cheats) > 0 and len(existing_cheats) == 0:
                            game_lookup[key]['regions'][region]['cheats'] = new_cheats
        
        # Convert back to list
        merged['games'] = list(game_lookup.values())
        merged['merge_date'] = datetime.now().isoformat()
        merged['total_games'] = len(merged['games'])
        
        # Count total cheats
        total_cheats = 0
        for game in merged['games']:
            for region_data in game.get('regions', {}).values():
                total_cheats += len(region_data.get('cheats', []))
        
        merged['total_cheats'] = total_cheats
        
        return merged
    
    @staticmethod
    def get_game_cheats(database: Dict, game_title: str, serial: str = None, region: str = None) -> List[Dict]:
        """
        Search database for cheats by game title and optional serial/region.
        """
        results = []
        norm_title = CheatsDatabase.normalize_game_title(game_title)
        
        for game in database.get('games', []):
            if CheatsDatabase.normalize_game_title(game.get('title', '')) == norm_title:
                for reg, reg_data in game.get('regions', {}).items():
                    # Check region match
                    if region and reg != region:
                        continue
                    
                    # Check serial match
                    if serial and reg_data.get('serial', '').upper() != serial.upper():
                        continue
                    
                    cheats = reg_data.get('cheats', [])
                    if cheats:
                        results.append({
                            'region': reg,
                            'serial': reg_data.get('serial'),
                            'crc': reg_data.get('crc'),
                            'cheats': cheats
                        })
        
        return results
    
    @staticmethod
    def get_statistics(database: Dict) -> Dict:
        """Get database statistics."""
        stats = {
            'total_games': len(database.get('games', [])),
            'total_cheats': 0,
            'by_region': {},
            'games_by_region': {},
            'max_cheats_per_game': 0,
            'avg_cheats_per_game': 0
        }
        
        cheat_counts_per_game = []
        
        for game in database.get('games', []):
            for region, reg_data in game.get('regions', {}).items():
                cheats = reg_data.get('cheats', [])
                cheat_count = len(cheats)
                
                stats['total_cheats'] += cheat_count
                
                if region not in stats['by_region']:
                    stats['by_region'][region] = 0
                    stats['games_by_region'][region] = 0
                
                stats['by_region'][region] += cheat_count
                stats['games_by_region'][region] += 1
                cheat_counts_per_game.append(cheat_count)
        
        if cheat_counts_per_game:
            stats['max_cheats_per_game'] = max(cheat_counts_per_game)
            stats['avg_cheats_per_game'] = sum(cheat_counts_per_game) / len(cheat_counts_per_game)
        
        return stats


def merge_all_cheats(local_folder: str = './PS2 Cheats', 
                     existing_db: str = 'ps2_cheats_database.json',
                     output_db: str = 'ps2_cheats_database_merged.json',
                     use_github: bool = True):
    """
    Merge all available cheat sources into one database.
    """
    logger.info("=== CHEAT DATABASE MERGER ===")
    
    # Step 1: Scan local folder
    logger.info("\nStep 1: Scanning local cheats folder...")
    from scan_local_cheats import LocalCheatsScanner
    
    if os.path.exists(local_folder):
        scan_results = LocalCheatsScanner.scan_folder(local_folder)
        local_db = LocalCheatsScanner.build_database(scan_results)
        logger.info(f"Local: {local_db['total_games']} games, cheats scanned")
    else:
        local_db = {'games': []}
        logger.warning(f"Local folder not found: {local_folder}")
    
    databases_to_merge = [local_db]
    
    # Step 2: Download and parse GitHub cheats (optional)
    if use_github:
        logger.info("\nStep 2: Fetching GitHub cheats...")
        try:
            from fetch_github_cheats import download_github_cheats, scan_pnach_files, merge_cheats_to_database
            
            github_folder = './github_cheats_temp'
            cheat_folder = download_github_cheats(github_folder)
            pnach_files = scan_pnach_files(cheat_folder)
            
            # Create temporary database just for GitHub
            github_db = merge_cheats_to_database('', pnach_files)
            databases_to_merge.append(github_db)
            
            logger.info(f"GitHub: {len(github_db.get('games', []))} games fetched")
            
            # Cleanup
            import shutil
            shutil.rmtree(github_folder, ignore_errors=True)
        
        except Exception as e:
            logger.error(f"Failed to fetch GitHub cheats: {e}")
    
    # Step 3: Load existing database
    logger.info("\nStep 3: Loading existing database...")
    if os.path.exists(existing_db):
        existing = CheatsDatabase.load_database(existing_db)
        if existing.get('games'):
            databases_to_merge.append(existing)
            logger.info(f"Existing: {len(existing.get('games', []))} games loaded")
    
    # Step 4: Merge all
    logger.info("\nStep 4: Merging all databases...")
    merged_db = CheatsDatabase.merge_databases(databases_to_merge, prefer_larger=True)
    
    # Step 5: Save
    logger.info("\nStep 5: Saving merged database...")
    CheatsDatabase.save_database(merged_db, output_db)
    
    # Step 6: Print statistics
    logger.info("\n=== STATISTICS ===")
    stats = CheatsDatabase.get_statistics(merged_db)
    logger.info(f"Total games: {stats['total_games']}")
    logger.info(f"Total cheats: {stats['total_cheats']}")
    logger.info(f"Average cheats/game: {stats['avg_cheats_per_game']:.1f}")
    logger.info(f"Max cheats in a game: {stats['max_cheats_per_game']}")
    
    logger.info("\nCheats by region:")
    for region, count in sorted(stats['games_by_region'].items()):
        cheats = stats['by_region'].get(region, 0)
        logger.info(f"  {region}: {count} games, {cheats} cheats")
    
    logger.info(f"\nMerged database saved to: {output_db}")
    
    return merged_db


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Merge all cheat sources')
    parser.add_argument('--local-folder', default='./PS2 Cheats', help='Local cheats folder')
    parser.add_argument('--existing-db', default='ps2_cheats_database.json', help='Existing database')
    parser.add_argument('--output', default='ps2_cheats_database_merged.json', help='Output database')
    parser.add_argument('--no-github', action='store_true', help='Skip GitHub download')
    
    args = parser.parse_args()
    
    merge_all_cheats(
        local_folder=args.local_folder,
        existing_db=args.existing_db,
        output_db=args.output,
        use_github=not args.no_github
    )
