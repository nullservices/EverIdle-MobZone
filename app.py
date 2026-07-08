#!/usr/bin/env python3
"""
EQ Emulator Mob & Camp Manager
A desktop application for managing mob spawn data and camp assignments
"""

import sys
import os
import pandas as pd
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLineEdit, QPushButton,
    QLabel, QComboBox, QSpinBox, QGroupBox, QSplitter,
    QMessageBox, QFileDialog, QTabWidget, QHeaderView,
    QTreeWidget, QTreeWidgetItem, QMenu, QAction, QToolBar,
    QStatusBar, QCheckBox, QProgressDialog, QDialog,
    QDialogButtonBox, QFormLayout, QTextEdit
)
from PyQt5.QtCore import Qt, QSortFilterProxyModel, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QBrush, QIcon

import csv
from collections import defaultdict
import re


class MobDataModel:
    """Data model for managing mob and camp data"""
    
    def __init__(self):
        self.df = None
        self.camps = {}  # zone -> {camp_id: camp_name}
        self.camp_assignments = {}  # mob_id -> camp_id
        self.file_path = None
        self.modified = False
        
    def load_from_csv(self, file_path):
        """Load mob data from CSV file"""
        try:
            # Read CSV with pipe delimiter
            self.df = pd.read_csv(file_path, sep='|', encoding='utf-8', 
                                   quotechar='"', on_bad_lines='skip')
            self.file_path = file_path
            self.modified = False
            
            # Parse existing camp data from spawn_group_id and spawn_group_name
            self._parse_camps()
            
            return True
        except Exception as e:
            print(f"Error loading CSV: {e}")
            return False
    
    def _parse_camps(self):
        """Extract camp information from existing spawn_group data"""
        if self.df is None:
            return
            
        self.camps = defaultdict(dict)
        self.camp_assignments = {}
        
        for idx, row in self.df.iterrows():
            if pd.notna(row['spawn_group_id']) and pd.notna(row['spawn_group_name']):
                group_id = str(row['spawn_group_id'])
                group_name = str(row['spawn_group_name'])
                zone = str(row['zone_short_name']) if pd.notna(row['zone_short_name']) else 'unknown'
                mob_id = str(row['npc_type_id']) if pd.notna(row['npc_type_id']) else None
                
                if mob_id:
                    self.camp_assignments[mob_id] = group_id
                    self.camps[zone][group_id] = group_name
        
    def save_to_csv(self, file_path=None):
        """Save data back to CSV"""
        if file_path:
            self.file_path = file_path
            
        if self.file_path is None:
            return False
            
        try:
            # Update spawn_group_id and spawn_group_name from camp assignments
            if self.df is not None:
                for idx, row in self.df.iterrows():
                    mob_id = str(row['npc_type_id']) if pd.notna(row['npc_type_id']) else None
                    if mob_id and mob_id in self.camp_assignments:
                        camp_id = self.camp_assignments[mob_id]
                        zone = str(row['zone_short_name']) if pd.notna(row['zone_short_name']) else 'unknown'
                        camp_name = self.camps.get(zone, {}).get(camp_id, '')
                        self.df.at[idx, 'spawn_group_id'] = camp_id
                        self.df.at[idx, 'spawn_group_name'] = camp_name
            
            self.df.to_csv(self.file_path, sep='|', index=False, encoding='utf-8', quotechar='"')
            self.modified = False
            return True
        except Exception as e:
            print(f"Error saving CSV: {e}")
            return False
    
    def assign_camp(self, mob_id, camp_id, camp_name, zone):
        """Assign a mob to a camp"""
        if mob_id not in self.camp_assignments or self.camp_assignments[mob_id] != camp_id:
            self.camp_assignments[mob_id] = camp_id
            self.camps[zone][camp_id] = camp_name
            self.modified = True
            return True
        return False
    
    def unassign_camp(self, mob_id):
        """Remove camp assignment from a mob"""
        if mob_id in self.camp_assignments:
            del self.camp_assignments[mob_id]
            self.modified = True
            return True
        return False
    
    def get_camp_for_mob(self, mob_id):
        """Get camp info for a mob"""
        if mob_id in self.camp_assignments:
            camp_id = self.camp_assignments[mob_id]
            return camp_id, self.camps.get(camp_id, {}).get(camp_id, '')
        return None, None
    
    def get_camps_for_zone(self, zone):
        """Get all camps for a zone"""
        return self.camps.get(zone, {})
    
    def get_mobs_in_camp(self, zone, camp_id):
        """Get all mobs assigned to a camp"""
        if self.df is None:
            return []
            
        mobs = []
        for idx, row in self.df.iterrows():
            mob_id = str(row['npc_type_id']) if pd.notna(row['npc_type_id']) else None
            row_zone = str(row['zone_short_name']) if pd.notna(row['zone_short_name']) else 'unknown'
            if mob_id and mob_id in self.camp_assignments:
                if self.camp_assignments[mob_id] == camp_id and row_zone == zone:
                    mobs.append({
                        'mob_id': mob_id,
                        'name': row.get('mob_name', ''),
                        'level': row.get('mob_level', ''),
                        'zone': row_zone,
                        'x': row.get('x', ''),
                        'y': row.get('y', ''),
                        'z': row.get('z', ''),
                    })
        return mobs


class MobTableModel(QSortFilterProxyModel):
    """Proxy model for filtering mob data"""
    
    def __init__(self):
        super().__init__()
        self.filter_text = ""
        self.filter_zone = ""
        self.filter_level_min = 0
        self.filter_level_max = 999
        self.filter_named = False
        self.filter_raid = False
        self.filter_camp = ""
        self.filter_has_camp = -1  # -1 = all, 0 = no camp, 1 = has camp
        
    def set_filter(self, text="", zone="", level_min=0, level_max=999, 
                   named=False, raid=False, camp="", has_camp=-1):
        self.filter_text = text.lower()
        self.filter_zone = zone
        self.filter_level_min = level_min
        self.filter_level_max = level_max
        self.filter_named = named
        self.filter_raid = raid
        self.filter_camp = camp
        self.filter_has_camp = has_camp
        self.invalidateFilter()
    
    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        if model is None or model.df is None:
            return True
            
        row_data = model.df.iloc[source_row]
        zone = str(row_data.get('zone_short_name', ''))
        
        # Zone filter
        if self.filter_zone and zone != self.filter_zone:
            return False
        
        # Level filter
        try:
            level = int(row_data.get('mob_level', 0))
        except (ValueError, TypeError):
            level = 0
        if level < self.filter_level_min or level > self.filter_level_max:
            return False
        
        # Text search
        if self.filter_text:
            search_fields = ['mob_name', 'zone_name', 'zone_short_name', 
                           'spawn_group_name', 'npc_type_id']
            found = False
            for field in search_fields:
                val = str(row_data.get(field, ''))
                if self.filter_text in val.lower():
                    found = True
                    break
            if not found:
                return False
        
        # Named filter
        if self.filter_named:
            name = str(row_data.get('mob_name', ''))
            if not any(x in name.lower() for x in ['#', 'named', 'boss', 'guardian']):
                return False
        
        # Camp assignment filter
        mob_id = str(row_data.get('npc_type_id', ''))
        if self.filter_has_camp == 1:
            if mob_id not in model.camp_assignments:
                return False
        elif self.filter_has_camp == 0:
            if mob_id in model.camp_assignments:
                return False
        
        # Camp filter
        if self.filter_camp:
            if mob_id not in model.camp_assignments:
                return False
            if model.camp_assignments[mob_id] != self.filter_camp:
                return False
        
        return True


class CampDialog(QDialog):
    """Dialog for assigning a camp to selected mobs"""
    
    def __init__(self, parent=None, zone=None, existing_camps=None, selected_mobs=None):
        super().__init__(parent)
        self.zone = zone
        self.existing_camps = existing_camps or {}
        self.selected_mobs = selected_mobs or []
        self.camp_id = None
        self.camp_name = None
        self.is_new_camp = False
        
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Assign Camp")
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        
        # Info label
        info_label = QLabel(f"Assigning camp to {len(self.selected_mobs)} mob(s) in zone: {self.zone}")
        layout.addWidget(info_label)
        
        # Existing camps
        group = QGroupBox("Existing Camps")
        group_layout = QVBoxLayout(group)
        
        self.camp_list = QTreeWidget()
        self.camp_list.setHeaderLabels(["Camp ID", "Camp Name", "Mob Count"])
        self.camp_list.setColumnWidth(0, 150)
        self.camp_list.setColumnWidth(1, 200)
        self.camp_list.itemDoubleClicked.connect(self.on_camp_selected)
        
        for camp_id, camp_name in self.existing_camps.items():
            item = QTreeWidgetItem([camp_id, camp_name, ""])
            item.setData(0, Qt.UserRole, camp_id)
            self.camp_list.addTopLevelItem(item)
        
        group_layout.addWidget(self.camp_list)
        layout.addWidget(group)
        
        # New camp option
        group2 = QGroupBox("Create New Camp")
        group2_layout = QFormLayout(group2)
        
        self.new_camp_id = QLineEdit()
        self.new_camp_id.setPlaceholderText("e.g., zone_c1")
        group2_layout.addRow("Camp ID:", self.new_camp_id)
        
        self.new_camp_name = QLineEdit()
        self.new_camp_name.setPlaceholderText("e.g., Entrance")
        group2_layout.addRow("Camp Name:", self.new_camp_name)
        
        layout.addWidget(group2)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # Connect signals
        self.camp_list.itemSelectionChanged.connect(self.on_selection_changed)
        
    def on_selection_changed(self):
        selected = self.camp_list.selectedItems()
        if selected:
            item = selected[0]
            camp_id = item.data(0, Qt.UserRole)
            if camp_id:
                self.camp_id = camp_id
                self.camp_name = self.existing_camps.get(camp_id, "")
                self.is_new_camp = False
                # Clear new camp fields
                self.new_camp_id.setText("")
                self.new_camp_name.setText("")
    
    def on_camp_selected(self, item, column):
        camp_id = item.data(0, Qt.UserRole)
        if camp_id:
            self.camp_id = camp_id
            self.camp_name = self.existing_camps.get(camp_id, "")
            self.is_new_camp = False
    
    def accept(self):
        # Check if creating new camp
        if self.new_camp_id.text() and self.new_camp_name.text():
            self.camp_id = self.new_camp_id.text()
            self.camp_name = self.new_camp_name.text()
            self.is_new_camp = True
            super().accept()
        elif self.camp_id:
            super().accept()
        else:
            QMessageBox.warning(self, "No Selection", 
                               "Please select an existing camp or enter a new camp ID and name.")


class MobManager(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.model = MobDataModel()
        self.proxy_model = MobTableModel()
        self.current_zone = ""
        self.unsaved_changes = False
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("EQ Emulator Mob & Camp Manager")
        self.setGeometry(100, 100, 1400, 800)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Toolbar
        self.create_toolbar()
        
        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Filter controls
        left_panel = QWidget()
        left_panel.setMaximumWidth(300)
        left_layout = QVBoxLayout(left_panel)
        
        # File controls
        file_group = QGroupBox("File")
        file_layout = QVBoxLayout(file_group)
        
        file_buttons = QHBoxLayout()
        self.load_btn = QPushButton("Load CSV")
        self.load_btn.clicked.connect(self.load_file)
        file_buttons.addWidget(self.load_btn)
        
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_file)
        self.save_btn.setEnabled(False)
        file_buttons.addWidget(self.save_btn)
        
        file_layout.addLayout(file_buttons)
        left_layout.addWidget(file_group)
        
        # Search
        search_group = QGroupBox("Search")
        search_layout = QVBoxLayout(search_group)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search mobs...")
        self.search_input.textChanged.connect(self.apply_filters)
        search_layout.addWidget(self.search_input)
        
        left_layout.addWidget(search_group)
        
        # Filters
        filter_group = QGroupBox("Filters")
        filter_layout = QVBoxLayout(filter_group)
        
        # Zone filter
        zone_layout = QHBoxLayout()
        zone_layout.addWidget(QLabel("Zone:"))
        self.zone_combo = QComboBox()
        self.zone_combo.addItem("All Zones")
        self.zone_combo.currentTextChanged.connect(self.apply_filters)
        zone_layout.addWidget(self.zone_combo)
        filter_layout.addLayout(zone_layout)
        
        # Level filter
        level_layout = QHBoxLayout()
        level_layout.addWidget(QLabel("Level:"))
        self.level_min = QSpinBox()
        self.level_min.setRange(0, 100)
        self.level_min.setValue(0)
        self.level_min.valueChanged.connect(self.apply_filters)
        level_layout.addWidget(self.level_min)
        
        level_layout.addWidget(QLabel("-"))
        self.level_max = QSpinBox()
        self.level_max.setRange(0, 100)
        self.level_max.setValue(100)
        self.level_max.valueChanged.connect(self.apply_filters)
        level_layout.addWidget(self.level_max)
        filter_layout.addLayout(level_layout)
        
        # Toggle filters
        self.named_filter = QCheckBox("Named only")
        self.named_filter.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.named_filter)
        
        self.has_camp_filter = QComboBox()
        self.has_camp_filter.addItems(["All", "Has Camp", "No Camp"])
        self.has_camp_filter.currentIndexChanged.connect(self.apply_filters)
        filter_layout.addWidget(QLabel("Camp Assignment:"))
        filter_layout.addWidget(self.has_camp_filter)
        
        left_layout.addWidget(filter_group)
        
        # Camp management
        camp_group = QGroupBox("Camp Management")
        camp_layout = QVBoxLayout(camp_group)
        
        self.camp_tree = QTreeWidget()
        self.camp_tree.setHeaderLabels(["Camp", "Mobs"])
        self.camp_tree.setColumnWidth(0, 180)
        self.camp_tree.itemDoubleClicked.connect(self.on_camp_double_click)
        camp_layout.addWidget(self.camp_tree)
        
        camp_buttons = QHBoxLayout()
        self.assign_camp_btn = QPushButton("Assign Camp")
        self.assign_camp_btn.clicked.connect(self.assign_camp_dialog)
        self.assign_camp_btn.setEnabled(False)
        camp_buttons.addWidget(self.assign_camp_btn)
        
        self.remove_camp_btn = QPushButton("Remove Camp")
        self.remove_camp_btn.clicked.connect(self.remove_camp)
        self.remove_camp_btn.setEnabled(False)
        camp_buttons.addWidget(self.remove_camp_btn)
        
        camp_layout.addLayout(camp_buttons)
        left_layout.addWidget(camp_group)
        
        left_layout.addStretch()
        
        # Right panel - Table and details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # Table
        table_group = QGroupBox("Mobs")
        table_layout = QVBoxLayout(table_group)
        
        self.table = QTableWidget()
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_table_selection)
        
        table_layout.addWidget(self.table)
        right_layout.addWidget(table_group)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 1100])
        
        # Stats label
        self.stats_label = QLabel("No data loaded")
        self.status_bar.addWidget(self.stats_label)
        
        # Load file if provided as argument
        if len(sys.argv) > 1:
            QTimer.singleShot(100, lambda: self.load_file(sys.argv[1]))
    
    def create_toolbar(self):
        toolbar = self.addToolBar("Main")
        
        # File actions
        load_action = QAction("Load", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_file)
        toolbar.addAction(load_action)
        
        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_file)
        toolbar.addAction(save_action)
        
        toolbar.addSeparator()
        
        # View actions
        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_view)
        toolbar.addAction(refresh_action)
        
        # Export action
        export_action = QAction("Export", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_data)
        toolbar.addAction(export_action)
    
    def load_file(self, file_path=None):
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Open Mob Data File", "", "CSV Files (*.csv);;All Files (*)"
            )
            if not file_path:
                return
        
        if self.model.load_from_csv(file_path):
            self.refresh_view()
            self.save_btn.setEnabled(True)
            self.assign_camp_btn.setEnabled(True)
            self.remove_camp_btn.setEnabled(True)
            self.status_bar.showMessage(f"Loaded {len(self.model.df)} mobs from {file_path}", 5000)
            
            # Update zone combo
            self.update_zone_combo()
            
            # Update camp tree
            self.update_camp_tree()
        else:
            QMessageBox.critical(self, "Error", f"Failed to load file: {file_path}")
    
    def save_file(self):
        if self.model.save_to_csv():
            self.status_bar.showMessage(f"Saved to {self.model.file_path}", 3000)
            self.model.modified = False
            self.update_camp_tree()
        else:
            QMessageBox.critical(self, "Error", "Failed to save file")
    
    def export_data(self):
        if self.model.df is None or len(self.model.df) == 0:
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Data", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return
        
        try:
            self.model.df.to_csv(file_path, sep='|', index=False, encoding='utf-8', quotechar='"')
            self.status_bar.showMessage(f"Exported to {file_path}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export: {e}")
    
    def update_zone_combo(self):
        if self.model.df is None:
            return
        
        zones = sorted(self.model.df['zone_short_name'].dropna().unique())
        self.zone_combo.blockSignals(True)
        self.zone_combo.clear()
        self.zone_combo.addItem("All Zones")
        for zone in zones:
            if zone and str(zone) != 'nan':
                self.zone_combo.addItem(str(zone))
        self.zone_combo.blockSignals(False)
    
    def update_camp_tree(self):
        """Update the camp tree widget"""
        self.camp_tree.clear()
        
        if not self.model.camps:
            item = QTreeWidgetItem(["No camps defined"])
            self.camp_tree.addTopLevelItem(item)
            return
        
        total_mobs = 0
        for zone, camps in sorted(self.model.camps.items()):
            zone_item = QTreeWidgetItem([f"Zone: {zone}"])
            zone_item.setExpanded(True)
            font = zone_item.font(0)
            font.setBold(True)
            zone_item.setFont(0, font)
            self.camp_tree.addTopLevelItem(zone_item)
            
            for camp_id, camp_name in sorted(camps.items()):
                mobs = self.model.get_mobs_in_camp(zone, camp_id)
                count = len(mobs)
                total_mobs += count
                camp_item = QTreeWidgetItem([f"{camp_name} ({camp_id})", f"{count} mobs"])
                camp_item.setData(0, Qt.UserRole, {
                    'zone': zone,
                    'camp_id': camp_id,
                    'camp_name': camp_name
                })
                zone_item.addChild(camp_item)
        
        # Update stats
        self.status_bar.showMessage(f"Total mobs: {len(self.model.df)}, Camp assignments: {len(self.model.camp_assignments)}")
    
    def refresh_view(self):
        """Refresh the table view with current data"""
        if self.model.df is None or len(self.model.df) == 0:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.stats_label.setText("No data loaded")
            return
        
        # Update proxy model
        self.proxy_model.setSourceModel(None)
        
        # Set up table
        columns = ['npc_type_id', 'mob_name', 'mob_level', 'zone_short_name', 
                   'zone_name', 'x', 'y', 'z', 'heading', 'spawn_chance', 
                   'spawn_group_id', 'spawn_group_name', 'camp']
        
        display_columns = ['ID', 'Name', 'Level', 'Zone', 'Zone Name', 'X', 'Y', 'Z', 
                          'Heading', 'Spawn %', 'Camp ID', 'Camp Name', 'Camp']
        
        self.table.setColumnCount(len(display_columns))
        self.table.setHorizontalHeaderLabels(display_columns)
        
        # Populate table
        self.table.setRowCount(len(self.model.df))
        
        for row_idx, (_, row_data) in enumerate(self.model.df.iterrows()):
            for col_idx, col in enumerate(columns):
                value = row_data.get(col, '')
                
                # Special handling for camp
                if col == 'camp':
                    mob_id = str(row_data.get('npc_type_id', ''))
                    camp_id = self.model.camp_assignments.get(mob_id, '')
                    camp_name = ''
                    if camp_id:
                        zone = str(row_data.get('zone_short_name', 'unknown'))
                        camp_name = self.model.camps.get(zone, {}).get(camp_id, '')
                    value = f"{camp_name} ({camp_id})" if camp_id else ''
                else:
                    value = str(value) if pd.notna(value) else ''
                
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row_idx)
                
                # Color coding for camp assignments
                if col == 'camp' and value:
                    item.setBackground(QBrush(QColor(200, 230, 200)))
                
                self.table.setItem(row_idx, col_idx, item)
        
        # Resize columns
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        
        # Update stats
        self.stats_label.setText(f"Total: {len(self.model.df)} mobs | Zones: {len(self.model.df['zone_short_name'].dropna().unique())}")
    
    def apply_filters(self):
        """Apply all filters and update table"""
        if self.model.df is None or len(self.model.df) == 0:
            return
        
        search_text = self.search_input.text()
        zone = self.zone_combo.currentText()
        if zone == "All Zones":
            zone = ""
        
        level_min = self.level_min.value()
        level_max = self.level_max.value()
        
        named = self.named_filter.isChecked()
        
        has_camp_idx = self.has_camp_filter.currentIndex()
        has_camp = -1
        if has_camp_idx == 1:
            has_camp = 1  # Has camp
        elif has_camp_idx == 2:
            has_camp = 0  # No camp
        
        # Apply filter
        filtered_df = self.model.df.copy()
        
        # Manual filtering for now (we'll use the proxy model approach later)
        if search_text:
            search_lower = search_text.lower()
            filtered_df = filtered_df[
                filtered_df['mob_name'].astype(str).str.lower().str.contains(search_lower, na=False) |
                filtered_df['zone_name'].astype(str).str.lower().str.contains(search_lower, na=False) |
                filtered_df['zone_short_name'].astype(str).str.lower().str.contains(search_lower, na=False) |
                filtered_df['npc_type_id'].astype(str).str.contains(search_text, na=False)
            ]
        
        if zone:
            filtered_df = filtered_df[filtered_df['zone_short_name'].astype(str) == zone]
        
        if level_min > 0 or level_max < 100:
            filtered_df = filtered_df[
                (filtered_df['mob_level'].astype(float) >= level_min) & 
                (filtered_df['mob_level'].astype(float) <= level_max)
            ]
        
        if named:
            filtered_df = filtered_df[
                filtered_df['mob_name'].astype(str).str.contains('|'.join(['#', 'named', 'boss', 'guardian']), 
                                                               case=False, na=False)
            ]
        
        if has_camp == 1:
            filtered_df = filtered_df[
                filtered_df['npc_type_id'].astype(str).isin(self.model.camp_assignments.keys())
            ]
        elif has_camp == 0:
            filtered_df = filtered_df[
                ~filtered_df['npc_type_id'].astype(str).isin(self.model.camp_assignments.keys())
            ]
        
        # Update table with filtered data
        self.update_table_with_filtered(filtered_df)
        
        # Update stats
        self.stats_label.setText(f"Filtered: {len(filtered_df)} / {len(self.model.df)} mobs")
    
    def update_table_with_filtered(self, filtered_df):
        """Update table with filtered data"""
        columns = ['npc_type_id', 'mob_name', 'mob_level', 'zone_short_name', 
                   'zone_name', 'x', 'y', 'z', 'heading', 'spawn_chance', 
                   'spawn_group_id', 'spawn_group_name', 'camp']
        
        display_columns = ['ID', 'Name', 'Level', 'Zone', 'Zone Name', 'X', 'Y', 'Z', 
                          'Heading', 'Spawn %', 'Camp ID', 'Camp Name', 'Camp']
        
        self.table.setRowCount(len(filtered_df))
        self.table.setColumnCount(len(display_columns))
        self.table.setHorizontalHeaderLabels(display_columns)
        
        for row_idx, (_, row_data) in enumerate(filtered_df.iterrows()):
            for col_idx, col in enumerate(columns):
                value = row_data.get(col, '')
                
                if col == 'camp':
                    mob_id = str(row_data.get('npc_type_id', ''))
                    camp_id = self.model.camp_assignments.get(mob_id, '')
                    camp_name = ''
                    if camp_id:
                        zone = str(row_data.get('zone_short_name', 'unknown'))
                        camp_name = self.model.camps.get(zone, {}).get(camp_id, '')
                    value = f"{camp_name} ({camp_id})" if camp_id else ''
                else:
                    value = str(value) if pd.notna(value) else ''
                
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row_idx)
                
                if col == 'camp' and value:
                    item.setBackground(QBrush(QColor(200, 230, 200)))
                
                self.table.setItem(row_idx, col_idx, item)
    
    def on_table_selection(self):
        """Handle table selection changes"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        
        has_selection = len(selected_rows) > 0
        self.assign_camp_btn.setEnabled(has_selection)
        self.remove_camp_btn.setEnabled(has_selection)
        
        # Update status with selected count
        if has_selection:
            self.status_bar.showMessage(f"Selected {len(selected_rows)} mobs")
    
    def assign_camp_dialog(self):
        """Open camp assignment dialog"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            return
        
        # Get selected mob data
        selected_mobs = []
        zone = None
        for row_idx in selected_rows:
            mob_id_item = self.table.item(row_idx, 0)
            if mob_id_item:
                mob_id = mob_id_item.text()
                zone_item = self.table.item(row_idx, 3)
                if zone_item:
                    if zone is None:
                        zone = zone_item.text()
                    elif zone != zone_item.text():
                        QMessageBox.warning(self, "Mixed Zones", 
                                          "Please select mobs from the same zone.")
                        return
                selected_mobs.append({
                    'mob_id': mob_id,
                    'name': self.table.item(row_idx, 1).text() if self.table.item(row_idx, 1) else '',
                    'level': self.table.item(row_idx, 2).text() if self.table.item(row_idx, 2) else '',
                })
        
        if not selected_mobs:
            return
        
        if zone is None:
            zone = "unknown"
        
        # Get existing camps for this zone
        existing_camps = self.model.get_camps_for_zone(zone)
        
        dialog = CampDialog(self, zone, existing_camps, selected_mobs)
        if dialog.exec_() == QDialog.Accepted:
            camp_id = dialog.camp_id
            camp_name = dialog.camp_name
            
            if not camp_id or not camp_name:
                QMessageBox.warning(self, "Invalid Camp", "Camp ID and name are required.")
                return
            
            # Assign camp to all selected mobs
            assigned = 0
            for mob in selected_mobs:
                if self.model.assign_camp(mob['mob_id'], camp_id, camp_name, zone):
                    assigned += 1
            
            if assigned > 0:
                self.model.modified = True
                self.apply_filters()
                self.update_camp_tree()
                self.status_bar.showMessage(f"Assigned {assigned} mobs to camp '{camp_name}'", 3000)
    
    def remove_camp(self):
        """Remove camp assignment from selected mobs"""
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            return
        
        # Confirm
        reply = QMessageBox.question(
            self, "Remove Camp", 
            f"Remove camp assignment from {len(selected_rows)} mob(s)?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        removed = 0
        for row_idx in selected_rows:
            mob_id_item = self.table.item(row_idx, 0)
            if mob_id_item:
                mob_id = mob_id_item.text()
                if self.model.unassign_camp(mob_id):
                    removed += 1
        
        if removed > 0:
            self.apply_filters()
            self.update_camp_tree()
            self.status_bar.showMessage(f"Removed camp from {removed} mob(s)", 3000)
    
    def on_camp_double_click(self, item, column):
        """Filter mobs by camp when double-clicking a camp in the tree"""
        data = item.data(0, Qt.UserRole)
        if isinstance(data, dict):
            zone = data.get('zone')
            camp_id = data.get('camp_id')
            
            # Set zone filter
            index = self.zone_combo.findText(zone)
            if index >= 0:
                self.zone_combo.setCurrentIndex(index)
            
            # Clear search
            self.search_input.setText("")
            
            # We'll filter by camp using the camp selection in the filter
            # For now, just highlight the camp in the table
            self.apply_filters()
            
            self.status_bar.showMessage(f"Filtered to camp: {data.get('camp_name')} ({camp_id})", 3000)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set application style
    app.setApplicationName("EQ Mob Manager")
    app.setOrganizationName("EQ Tools")
    
    window = MobManager()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()