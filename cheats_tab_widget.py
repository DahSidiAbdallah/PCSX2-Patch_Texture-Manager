#!/usr/bin/env python3
"""
Enhanced Cheats Tab UI Component for PCSX2 Manager GUI.
Integrates with merged cheat database for displaying and managing cheats.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QFont
import json
import os
import logging

logger = logging.getLogger(__name__)


class CheatsTabWidget(QWidget):
    """Enhanced cheats browser and manager widget."""
    
    cheats_selected = Signal(dict)  # Emitted when cheats are selected for a game
    
    def __init__(self, cheats_db_path: str = 'ps2_cheats_database_merged.json'):
        super().__init__()
        self.cheats_db_path = cheats_db_path
        self.cheats_database = {}
        self.current_game_cheats = []
        
        self.init_ui()
        self.load_database()
    
    def init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout()
        
        # Search section
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search Game:"))
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter game title or serial...")
        self.search_input.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_input)
        
        # Region filter
        search_layout.addWidget(QLabel("Region:"))
        self.region_combo = QComboBox()
        self.region_combo.addItems(['All', 'NTSC-U', 'PAL', 'NTSC-J', 'NTSC-K'])
        self.region_combo.currentTextChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.region_combo)
        
        # Refresh button
        self.refresh_btn = QPushButton("Refresh Database")
        self.refresh_btn.clicked.connect(self.refresh_database)
        search_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(search_layout)
        
        # Results table
        results_label = QLabel("Search Results:")
        results_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(results_label)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(['Game Title', 'Serial', 'Region', 'Cheats'])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.results_table.setColumnWidth(0, 300)
        self.results_table.itemSelectionChanged.connect(self.on_game_selected)
        layout.addWidget(self.results_table)
        
        # Cheats details section
        cheats_label = QLabel("Available Cheats:")
        cheats_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(cheats_label)
        
        self.cheats_table = QTableWidget()
        self.cheats_table.setColumnCount(3)
        self.cheats_table.setHorizontalHeaderLabels(['Cheat Name', 'Codes', 'Description'])
        self.cheats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cheats_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.cheats_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.cheats_table)
        
        # Info bar
        info_layout = QHBoxLayout()
        self.info_label = QLabel()
        info_layout.addWidget(self.info_label)
        info_layout.addStretch()
        
        self.db_stats_label = QLabel()
        self.update_status()
        info_layout.addWidget(self.db_stats_label)
        
        layout.addLayout(info_layout)
        
        self.setLayout(layout)
    
    def load_database(self):
        """Load cheats database."""
        if not os.path.exists(self.cheats_db_path):
            logger.warning(f"Database not found: {self.cheats_db_path}")
            # Try fallback to old database
            if os.path.exists('ps2_cheats_database.json'):
                logger.info("Falling back to ps2_cheats_database.json")
                self.cheats_db_path = 'ps2_cheats_database.json'
            else:
                QMessageBox.warning(
                    self,
                    "Database Not Found",
                    f"Cheats database not found at:\n{self.cheats_db_path}\n\n"
                    "Please run merge_cheats_databases.py first."
                )
                return
        
        try:
            with open(self.cheats_db_path, 'r', encoding='utf-8') as f:
                self.cheats_database = json.load(f)
            
            games_count = len(self.cheats_database.get('games', []))
            logger.info(f"Loaded {games_count} games from database: {self.cheats_db_path}")
            print(f"✓ Loaded {games_count} games")  # Debug output
            self.update_status()
            self.populate_results_table()  # Force refresh
        
        except Exception as e:
            logger.error(f"Failed to load database: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to load database: {e}")
    
    def refresh_database(self):
        """Force refresh of the database."""
        self.cheats_database = {}  # Clear cache
        self.load_database()
        QMessageBox.information(self, "Refreshed", "Database reloaded successfully!")
    
    def update_status(self):
        """Update status information."""
        games = self.cheats_database.get('games', [])
        total_cheats = sum(
            len(reg_data.get('cheats', []))
            for game in games
            for reg_data in game.get('regions', {}).values()
        )
        
        self.db_stats_label.setText(
            f"Database: {len(games)} games | {total_cheats} total cheats"
        )
    
    def on_search_changed(self):
        """Handle search input changes."""
        self.populate_results_table()
    
    def populate_results_table(self):
        """Populate results table based on search criteria."""
        search_text = self.search_input.text().lower().strip()
        region_filter = self.region_combo.currentText()
        
        self.results_table.setRowCount(0)
        matches = []
        
        for game in self.cheats_database.get('games', []):
            game_title = game.get('title', '').lower()
            
            # Check if game matches search
            if search_text and search_text not in game_title:
                # Check serial too
                found = False
                for region_data in game.get('regions', {}).values():
                    if search_text in region_data.get('serial', '').lower():
                        found = True
                        break
                if not found:
                    continue
            
            # Add regions
            for region, region_data in game.get('regions', {}).items():
                if region_filter != 'All' and region != region_filter:
                    continue
                
                cheats = region_data.get('cheats', [])
                if not cheats:
                    continue
                
                matches.append({
                    'title': game.get('title', 'Unknown'),
                    'serial': region_data.get('serial', ''),
                    'region': region,
                    'cheats_count': len(cheats),
                    'cheats': cheats
                })
        
        # Populate table
        self.results_table.setRowCount(len(matches))
        
        for row, match in enumerate(matches):
            self.results_table.setItem(row, 0, QTableWidgetItem(match['title']))
            self.results_table.setItem(row, 1, QTableWidgetItem(match['serial']))
            self.results_table.setItem(row, 2, QTableWidgetItem(match['region']))
            self.results_table.setItem(row, 3, QTableWidgetItem(str(match['cheats_count'])))
    
    def on_game_selected(self):
        """Handle game selection."""
        selected_rows = self.results_table.selectedIndexes()
        if not selected_rows:
            self.cheats_table.setRowCount(0)
            return
        
        row = selected_rows[0].row()
        
        # Get selected game
        game_title = self.results_table.item(row, 0).text()
        serial = self.results_table.item(row, 1).text()
        region = self.results_table.item(row, 2).text()
        
        # Find game in database and display cheats
        for game in self.cheats_database.get('games', []):
            if game.get('title') == game_title:
                for reg, reg_data in game.get('regions', {}).items():
                    if reg == region and reg_data.get('serial') == serial:
                        self.display_cheats(reg_data.get('cheats', []))
                        self.current_game_cheats = reg_data.get('cheats', [])
                        
                        # Emit signal
                        self.cheats_selected.emit({
                            'title': game_title,
                            'serial': serial,
                            'region': region,
                            'cheats': self.current_game_cheats
                        })
                        return
    
    def display_cheats(self, cheats: list):
        """Display cheats in the table."""
        self.cheats_table.setRowCount(0)
        
        for row, cheat in enumerate(cheats):
            self.cheats_table.insertRow(row)
            
            name = cheat.get('name', 'Unknown')
            codes = ' | '.join(cheat.get('codes', []))[:100] + (
                '...' if len(' | '.join(cheat.get('codes', []))) > 100 else ''
            )
            description = cheat.get('description', '')
            
            self.cheats_table.setItem(row, 0, QTableWidgetItem(name))
            self.cheats_table.setItem(row, 1, QTableWidgetItem(codes))
            self.cheats_table.setItem(row, 2, QTableWidgetItem(description))
        
        if cheats:
            self.info_label.setText(f"Found {len(cheats)} cheats for selected game")
        else:
            self.info_label.setText("No cheats available for this game")
    
    def export_cheats(self, game_title: str, output_path: str):
        """Export selected game cheats to a file."""
        if not self.current_game_cheats:
            QMessageBox.warning(self, "No Cheats", "No cheats selected for export")
            return
        
        try:
            export_data = {
                'game': game_title,
                'cheats': self.current_game_cheats
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            QMessageBox.information(self, "Success", f"Cheats exported to:\n{output_path}")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export cheats:\n{e}")
