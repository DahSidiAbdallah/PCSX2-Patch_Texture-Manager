#!/usr/bin/env python3
"""
Quick start script to merge all cheats and update GUI.
Run this to integrate the extensive GitHub cheat collection.
"""

import os
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print welcome banner."""
    print("\n" + "="*70)
    print("  PS2 CHEATS DATABASE MERGER & INTEGRATOR")
    print("  Combines Local + GitHub cheats into comprehensive collection")
    print("="*70 + "\n")


def check_dependencies():
    """Check required dependencies."""
    logger.info("Checking dependencies...")
    
    required = ['json', 're', 'zipfile', 'pathlib']
    optional = ['requests', 'bs4']
    
    missing_optional = []
    for mod in optional:
        try:
            __import__(mod)
        except ImportError:
            missing_optional.append(mod)
    
    if missing_optional:
        logger.warning(f"Optional modules not found: {', '.join(missing_optional)}")
        logger.warning("Some features may not work without these packages")


def step_1_scan_local():
    """Step 1: Scan local PS2 Cheats folder."""
    logger.info("\n" + "="*70)
    logger.info("STEP 1: SCANNING LOCAL CHEATS")
    logger.info("="*70)
    
    local_folder = './PS2 Cheats'
    
    if not os.path.exists(local_folder):
        logger.warning(f"Local cheats folder not found: {local_folder}")
        logger.info("Creating scan anyway with empty results...")
        return None
    
    try:
        from scan_local_cheats import LocalCheatsScanner
        
        logger.info(f"Scanning folder: {local_folder}")
        results = LocalCheatsScanner.scan_folder(local_folder)
        
        logger.info(f"✓ Found {len(results)} PNACH files")
        
        # Get stats
        games_with_cheats = sum(1 for r in results if r.get('cheats'))
        total_cheats = sum(r.get('cheats_count', 0) for r in results)
        
        logger.info(f"✓ Games with cheats: {games_with_cheats}")
        logger.info(f"✓ Total cheat entries: {total_cheats}")
        
        return results
    
    except Exception as e:
        logger.error(f"Failed to scan local folder: {e}")
        return None


def step_2_fetch_github():
    """Step 2: Fetch GitHub cheats."""
    logger.info("\n" + "="*70)
    logger.info("STEP 2: FETCHING GITHUB CHEATS")
    logger.info("="*70)
    logger.info("Repository: https://github.com/xs1l3n7x/pcsx2_cheats_collection")
    logger.info("This may take a while on first run (~563 games)...")
    
    try:
        from fetch_github_cheats import download_github_cheats, scan_pnach_files
        
        github_folder = './github_cheats_temp'
        
        logger.info("Downloading...")
        cheats_folder = download_github_cheats(github_folder)
        
        logger.info("Scanning downloaded cheats...")
        pnach_files = scan_pnach_files(cheats_folder)
        
        logger.info(f"✓ Found {len(pnach_files)} PNACH files")
        
        return pnach_files
    
    except Exception as e:
        logger.error(f"Failed to fetch GitHub cheats: {e}")
        logger.info("Continuing without GitHub cheats...")
        return None


def step_3_merge():
    """Step 3: Merge all databases."""
    logger.info("\n" + "="*70)
    logger.info("STEP 3: MERGING DATABASES")
    logger.info("="*70)
    
    try:
        from merge_cheats_databases import merge_all_cheats
        
        logger.info("Merging all cheat sources...")
        logger.info("  - Local PS2 Cheats folder")
        logger.info("  - GitHub repository")
        logger.info("  - Existing ps2_cheats_database.json")
        
        merged_db = merge_all_cheats(
            use_github=True,
            output_db='ps2_cheats_database_merged.json'
        )
        
        logger.info(f"✓ Merged database created successfully!")
        logger.info(f"  Total games: {merged_db.get('total_games', 0)}")
        logger.info(f"  Total cheats: {merged_db.get('total_cheats', 0)}")
        
        return merged_db
    
    except Exception as e:
        logger.error(f"Failed to merge databases: {e}")
        import traceback
        traceback.print_exc()
        return None


def step_4_verify():
    """Step 4: Verify merged database."""
    logger.info("\n" + "="*70)
    logger.info("STEP 4: VERIFYING DATABASE")
    logger.info("="*70)
    
    db_path = 'ps2_cheats_database_merged.json'
    
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return False
    
    try:
        import json
        
        with open(db_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        # Verify structure
        if 'games' not in db:
            logger.error("Invalid database structure: missing 'games' field")
            return False
        
        games = db['games']
        logger.info(f"✓ Database structure valid")
        logger.info(f"✓ Total games: {len(games)}")
        
        # Count cheats by region
        regions = {}
        for game in games:
            for region, reg_data in game.get('regions', {}).items():
                if region not in regions:
                    regions[region] = {'games': 0, 'cheats': 0}
                
                cheats = reg_data.get('cheats', [])
                regions[region]['games'] += 1
                regions[region]['cheats'] += len(cheats)
        
        logger.info("\nCheats by region:")
        for region in sorted(regions.keys()):
            reg = regions[region]
            logger.info(f"  {region:12} - {reg['games']:4} games, {reg['cheats']:5} cheats")
        
        return True
    
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return False


def step_5_instructions():
    """Step 5: Provide integration instructions."""
    logger.info("\n" + "="*70)
    logger.info("STEP 5: INTEGRATION INSTRUCTIONS")
    logger.info("="*70)
    
    instructions = """
The merged cheat database has been created: ps2_cheats_database_merged.json

TO USE IN YOUR GUI:

1. Update main.py to use the new CheatsTabWidget:
   
   Add this import at the top:
   ────────────────────────────
   from cheats_tab_widget import CheatsTabWidget
   
   In your tab widget creation, add:
   ────────────────────────────
   cheats_tab = CheatsTabWidget('ps2_cheats_database_merged.json')
   tab_widget.addTab(cheats_tab, "Cheats Browser")

2. The new CheatsTabWidget provides:
   ✓ Game search by title or serial
   ✓ Region filtering (NTSC-U, PAL, NTSC-J, NTSC-K)
   ✓ Detailed cheat codes display
   ✓ Cheat export functionality

3. Database features:
   ✓ {total_games} PS2 games
   ✓ Extensive cheat collection
   ✓ Multi-region support
   ✓ JSON format for easy access

4. To update the database again:
   Simply run: python merge_cheats_databases.py
   
   Or delete ps2_cheats_database_merged.json and re-run this script.

AVAILABLE TOOLS:
────────────────
• fetch_github_cheats.py     - Download cheats from GitHub repo
• scan_local_cheats.py       - Scan local PS2 Cheats folder
• merge_cheats_databases.py  - Merge all sources into one DB
• cheats_tab_widget.py       - GUI component for displaying cheats
• run_cheat_merger.py        - This script (quick start)

NEXT STEPS:
───────────
1. Test the database with: python -c "import json; db=json.load(open('ps2_cheats_database_merged.json')); print(f'Database loaded: {{len(db[\"games\"])}} games')"
2. Integrate CheatsTabWidget into main.py
3. Enjoy browsing {total_games} games with cheats!

    """
    
    try:
        import json
        with open('ps2_cheats_database_merged.json', 'r') as f:
            db = json.load(f)
        total_games = len(db.get('games', []))
    except:
        total_games = 'N/A'
    
    print(instructions.format(total_games=total_games))


def main():
    """Main execution."""
    print_banner()
    
    try:
        # Check dependencies
        check_dependencies()
        
        # Run steps
        step_1_scan_local()
        step_2_fetch_github()
        merge_result = step_3_merge()
        
        if merge_result and step_4_verify():
            logger.info("\n" + "="*70)
            logger.info("✓ ALL STEPS COMPLETED SUCCESSFULLY!")
            logger.info("="*70)
            
            step_5_instructions()
        else:
            logger.error("\n" + "="*70)
            logger.error("✗ SOME STEPS FAILED")
            logger.error("="*70)
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.warning("\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
