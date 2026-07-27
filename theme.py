"""Centralized theme tokens and QSS for the PCSX2 Manager UI.

Visual language: the PS2's own "Browser" boot menu -- a deep navy-to-royal-blue
backdrop, glassy rounded panels, and a bright cyan-blue glow used for accents,
focus, and selection instead of a flat solid highlight. Single source of truth
so the look can be adjusted from one place instead of hunting through inline
setStyleSheet() calls scattered across main.py.
"""

# --- Color tokens ---
# Deep navy base (used as the flat QWidget default so nested widgets don't
# each render their own slice of a gradient -- QSS gradients are per-widget-rect,
# so they only look right applied to a handful of large, single-instance
# containers like the app frame/title bar/dialogs, not to QWidget globally).
COLOR_BG = "#0a1330"
COLOR_BG_TOP = "#050915"
COLOR_BG_BOTTOM = "#122a63"

COLOR_SURFACE = "#132449"
COLOR_SURFACE_ALT = "#1b3160"
COLOR_BORDER = "#274a8c"
COLOR_BORDER_STRONG = "#3f6ac4"

COLOR_ACCENT = "#2f7cf6"
COLOR_ACCENT_HOVER = "#4f96ff"
COLOR_ACCENT_PRESSED = "#1f5fd1"
COLOR_GLOW = "#5ec8ff"

COLOR_TEXT = "#eaf2ff"
COLOR_TEXT_MUTED = "#8fa8d6"
COLOR_TEXT_DISABLED = "#4d5f8a"

COLOR_SUCCESS = "#2fd18a"
COLOR_SUCCESS_HOVER = "#42e69c"
COLOR_DANGER = "#ff5470"
COLOR_WARNING = "#ffb84d"

# --- Spacing tokens (px) ---
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24

RADIUS_SM = 6
RADIUS_MD = 9
RADIUS_LG = 14

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

TITLE_BAR_HEIGHT = 38
RESIZE_MARGIN = 6
COVER_WIDTH = 200
COVER_HEIGHT = 266

# Reusable gradient snippets so panels/buttons/dialogs share the same glassy
# language instead of each spelling out qlineargradient stops separately.
_GRAD_APP_BG = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {COLOR_BG_TOP}, stop:0.55 {COLOR_BG}, stop:1 {COLOR_BG_BOTTOM})"
)
_GRAD_PANEL = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {COLOR_SURFACE_ALT}, stop:1 {COLOR_SURFACE})"
)
_GRAD_BUTTON = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {COLOR_ACCENT_HOVER}, stop:1 {COLOR_ACCENT})"
)
_GRAD_BUTTON_HOVER = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {COLOR_GLOW}, stop:1 {COLOR_ACCENT_HOVER})"
)
_GRAD_SUCCESS = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    f"stop:0 {COLOR_SUCCESS_HOVER}, stop:1 {COLOR_SUCCESS})"
)

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
        border-bottom: 2px solid {COLOR_GLOW};
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
        border: 1px solid {COLOR_GLOW};
    }}
    QLineEdit:disabled, QTextEdit:disabled {{
        color: {COLOR_TEXT_DISABLED};
        background-color: {COLOR_SURFACE};
    }}
    QPushButton {{
        background: {_GRAD_BUTTON};
        color: white;
        border: 1px solid {COLOR_BORDER_STRONG};
        border-radius: {RADIUS_SM}px;
        padding: 8px 18px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {_GRAD_BUTTON_HOVER};
        border: 1px solid {COLOR_GLOW};
    }}
    QPushButton:pressed {{
        background-color: {COLOR_ACCENT_PRESSED};
    }}
    QPushButton:disabled {{
        background: {COLOR_SURFACE_ALT};
        border: 1px solid {COLOR_BORDER};
        color: {COLOR_TEXT_DISABLED};
    }}
    QPushButton#{OBJ_SUCCESS_BUTTON} {{
        background: {_GRAD_SUCCESS};
        border: 1px solid {COLOR_SUCCESS};
    }}
    QPushButton#{OBJ_SUCCESS_BUTTON}:hover {{
        background: {COLOR_SUCCESS_HOVER};
        border: 1px solid {COLOR_SUCCESS_HOVER};
    }}
    QGroupBox {{
        background-color: rgba(19, 36, 73, 120);
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
        color: {COLOR_GLOW};
    }}
    QLabel {{
        color: {COLOR_TEXT_MUTED};
    }}
    QLabel#{OBJ_MUTED_LABEL} {{
        color: {COLOR_TEXT_MUTED};
        font-size: 11px;
    }}
    QLabel#{OBJ_OVERLAY_LABEL} {{
        background: rgba(5, 9, 21, 0.72);
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
        border-radius: {RADIUS_SM}px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
        background-color: {COLOR_ACCENT};
        color: white;
        border: 1px solid {COLOR_GLOW};
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
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {COLOR_ACCENT}, stop:1 {COLOR_GLOW});
        border-radius: {RADIUS_SM - 1}px;
    }}
    QScrollBar:vertical {{
        background-color: transparent;
        width: 12px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {COLOR_BORDER_STRONG};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {COLOR_GLOW};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 12px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {COLOR_BORDER_STRONG};
        border-radius: 6px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {COLOR_GLOW};
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
        background-color: {COLOR_GLOW};
        border-color: {COLOR_GLOW};
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
    QDialog {{
        background: {_GRAD_APP_BG};
    }}
    QWidget#{OBJ_APP_FRAME} {{
        background: {_GRAD_APP_BG};
        border: 1px solid {COLOR_BORDER_STRONG};
    }}
    QWidget#{OBJ_TITLE_BAR} {{
        background: {_GRAD_PANEL};
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
"""
