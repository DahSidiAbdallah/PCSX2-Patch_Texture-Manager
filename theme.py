"""Centralized theme tokens and QSS for the PCSX2 Manager UI.

Single source of truth for colors/spacing/radii so the look of the app can be
adjusted (or a light variant added later) from one place instead of hunting
through inline setStyleSheet() calls scattered across main.py.
"""

# --- Color tokens ---
COLOR_BG = "#1e1e20"
COLOR_SURFACE = "#26262a"
COLOR_SURFACE_ALT = "#2f2f34"
COLOR_BORDER = "#3d3d42"
COLOR_BORDER_STRONG = "#4a4a51"

COLOR_ACCENT = "#3b82f6"
COLOR_ACCENT_HOVER = "#569bfb"
COLOR_ACCENT_PRESSED = "#2f6bd1"

COLOR_TEXT = "#e8e8ea"
COLOR_TEXT_MUTED = "#9a9aa2"
COLOR_TEXT_DISABLED = "#67676d"

COLOR_SUCCESS = "#2fb170"
COLOR_SUCCESS_HOVER = "#38c880"
COLOR_DANGER = "#e5484d"
COLOR_WARNING = "#d9a441"

# --- Spacing tokens (px) ---
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24

RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 9

FONT_FAMILY = '"Segoe UI", "Inter", sans-serif'

# Object names used to target specific widgets with QSS instead of scattering
# ad-hoc setStyleSheet() calls through main.py.
OBJ_MUTED_LABEL = "mutedLabel"
OBJ_SUCCESS_BUTTON = "successButton"
OBJ_OVERLAY_LABEL = "overlayLabel"

OBJ_APP_FRAME = "appFrame"
OBJ_TITLE_BAR = "titleBar"
OBJ_TITLE_BAR_LABEL = "titleBarLabel"
OBJ_TITLE_BAR_BUTTON = "titleBarButton"
OBJ_TITLE_BAR_CLOSE_BUTTON = "titleBarCloseButton"

OBJ_STATUS_SUCCESS = "statusSuccess"
OBJ_STATUS_WARNING = "statusWarning"
OBJ_STATUS_ERROR = "statusError"

OBJ_COVER_FRAME = "coverFrame"
OBJ_HERO_TITLE = "heroTitle"
OBJ_GAME_ROW = "gameRow"
OBJ_GAME_ROW_TITLE = "gameRowTitle"
OBJ_SIDEBAR = "sidebar"

TITLE_BAR_HEIGHT = 38
RESIZE_MARGIN = 6
COVER_WIDTH = 200
COVER_HEIGHT = 266

DARK_QSS = f"""
    QMainWindow {{
        background-color: {COLOR_BG};
    }}
    QWidget {{
        background-color: {COLOR_BG};
        color: {COLOR_TEXT};
        font-family: {FONT_FAMILY};
    }}
    QTabWidget::pane {{
        border: none;
        background-color: {COLOR_BG};
    }}
    QTabBar::tab {{
        background-color: {COLOR_SURFACE};
        color: {COLOR_TEXT_MUTED};
        padding: 10px 22px;
        margin-right: 2px;
        border: none;
        border-top-left-radius: {RADIUS_MD}px;
        border-top-right-radius: {RADIUS_MD}px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {COLOR_BG};
        color: {COLOR_TEXT};
        border-bottom: 2px solid {COLOR_ACCENT};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {COLOR_SURFACE_ALT};
        color: {COLOR_TEXT};
    }}
    QLineEdit, QTextEdit, QComboBox {{
        background-color: {COLOR_SURFACE};
        border: 1px solid {COLOR_BORDER};
        border-radius: {RADIUS_SM}px;
        padding: 6px 8px;
        color: {COLOR_TEXT};
        selection-background-color: {COLOR_ACCENT};
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border: 1px solid {COLOR_ACCENT};
    }}
    QLineEdit:disabled, QTextEdit:disabled {{
        color: {COLOR_TEXT_DISABLED};
        background-color: {COLOR_SURFACE};
    }}
    QPushButton {{
        background-color: {COLOR_ACCENT};
        color: white;
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 8px 18px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {COLOR_ACCENT_HOVER};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_ACCENT_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: {COLOR_SURFACE_ALT};
        color: {COLOR_TEXT_DISABLED};
    }}
    QPushButton#{OBJ_SUCCESS_BUTTON} {{
        background-color: {COLOR_SUCCESS};
    }}
    QPushButton#{OBJ_SUCCESS_BUTTON}:hover {{
        background-color: {COLOR_SUCCESS_HOVER};
    }}
    QGroupBox {{
        border: 1px solid {COLOR_BORDER};
        border-radius: {RADIUS_LG}px;
        margin-top: 14px;
        padding-top: 14px;
        font-weight: 600;
        color: {COLOR_TEXT};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {COLOR_ACCENT};
    }}
    QLabel {{
        color: {COLOR_TEXT_MUTED};
    }}
    QLabel#{OBJ_MUTED_LABEL} {{
        color: {COLOR_TEXT_MUTED};
        font-size: 11px;
    }}
    QLabel#{OBJ_OVERLAY_LABEL} {{
        background: rgba(0, 0, 0, 0.6);
        color: white;
    }}
    QListWidget, QTreeWidget, QTableWidget {{
        background-color: {COLOR_SURFACE};
        border: 1px solid {COLOR_BORDER};
        border-radius: {RADIUS_SM}px;
        color: {COLOR_TEXT};
        alternate-background-color: {COLOR_SURFACE_ALT};
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 3px 2px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background-color: {COLOR_ACCENT};
        color: white;
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{
        background-color: {COLOR_SURFACE_ALT};
    }}
    QHeaderView::section {{
        background-color: {COLOR_SURFACE};
        color: {COLOR_TEXT_MUTED};
        border: none;
        border-bottom: 1px solid {COLOR_BORDER};
        padding: 6px;
        font-weight: 600;
    }}
    QProgressBar {{
        border: 1px solid {COLOR_BORDER};
        border-radius: {RADIUS_SM}px;
        text-align: center;
        background-color: {COLOR_SURFACE};
        color: {COLOR_TEXT};
    }}
    QProgressBar::chunk {{
        background-color: {COLOR_ACCENT};
        border-radius: {RADIUS_SM - 1}px;
    }}
    QScrollBar:vertical {{
        background-color: {COLOR_BG};
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {COLOR_BORDER_STRONG};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {COLOR_TEXT_MUTED};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: {COLOR_BG};
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {COLOR_BORDER_STRONG};
        border-radius: 6px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {COLOR_TEXT_MUTED};
    }}
    QCheckBox {{
        spacing: 8px;
        color: {COLOR_TEXT};
    }}
    QCheckBox::indicator {{
        width: 17px;
        height: 17px;
        border: 1px solid {COLOR_BORDER_STRONG};
        border-radius: {RADIUS_SM}px;
        background-color: {COLOR_SURFACE};
    }}
    QCheckBox::indicator:checked {{
        background-color: {COLOR_ACCENT};
        border-color: {COLOR_ACCENT};
    }}
    QMenuBar {{
        background-color: {COLOR_BG};
        color: {COLOR_TEXT};
        border-bottom: 1px solid {COLOR_BORDER};
    }}
    QMenuBar::item:selected {{
        background-color: {COLOR_SURFACE_ALT};
    }}
    QMenu {{
        background-color: {COLOR_SURFACE};
        color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER};
    }}
    QMenu::item:selected {{
        background-color: {COLOR_ACCENT};
        color: white;
    }}
    QToolTip {{
        background-color: {COLOR_SURFACE_ALT};
        color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER_STRONG};
        padding: 4px 6px;
    }}
    QWidget#{OBJ_APP_FRAME} {{
        background-color: {COLOR_BG};
        border: 1px solid {COLOR_BORDER_STRONG};
    }}
    QWidget#{OBJ_TITLE_BAR} {{
        background-color: {COLOR_SURFACE};
        border-bottom: 1px solid {COLOR_BORDER};
    }}
    QLabel#{OBJ_TITLE_BAR_LABEL} {{
        color: {COLOR_TEXT};
        font-weight: 600;
    }}
    QToolButton#{OBJ_TITLE_BAR_BUTTON} {{
        background-color: transparent;
        border: none;
        border-radius: {RADIUS_SM}px;
    }}
    QToolButton#{OBJ_TITLE_BAR_BUTTON}:hover {{
        background-color: {COLOR_SURFACE_ALT};
    }}
    QToolButton#{OBJ_TITLE_BAR_BUTTON}:pressed {{
        background-color: {COLOR_BORDER_STRONG};
    }}
    QToolButton#{OBJ_TITLE_BAR_CLOSE_BUTTON} {{
        background-color: transparent;
        border: none;
        border-radius: {RADIUS_SM}px;
    }}
    QToolButton#{OBJ_TITLE_BAR_CLOSE_BUTTON}:hover {{
        background-color: {COLOR_DANGER};
    }}
    QLabel#{OBJ_STATUS_SUCCESS} {{
        color: {COLOR_SUCCESS};
        font-weight: 600;
    }}
    QLabel#{OBJ_STATUS_WARNING} {{
        color: {COLOR_WARNING};
        font-weight: 600;
    }}
    QLabel#{OBJ_STATUS_ERROR} {{
        color: {COLOR_DANGER};
        font-weight: 600;
    }}
    QLabel#{OBJ_COVER_FRAME} {{
        background-color: {COLOR_SURFACE};
        border: 1px solid {COLOR_BORDER_STRONG};
        border-radius: {RADIUS_LG}px;
    }}
    QLabel#{OBJ_HERO_TITLE} {{
        color: {COLOR_TEXT};
        font-weight: 700;
    }}
    QWidget#{OBJ_SIDEBAR} {{
        background-color: {COLOR_SURFACE};
        border-radius: {RADIUS_LG}px;
    }}
    QWidget#{OBJ_GAME_ROW} {{
        background-color: transparent;
        border-radius: {RADIUS_MD}px;
    }}
    QLabel#{OBJ_GAME_ROW_TITLE} {{
        color: {COLOR_TEXT};
        font-weight: 600;
    }}
"""
