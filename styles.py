# File Location: styles.py
# Academic & Life Command Center — global QSS stylesheet module (Phase 1).
#
# Implements the visual skin used by every phase:
#   background  #0F131A (base) / #151A22 (raised panels)
#   text        #E1E8ED          borders  #242E3B
#   accents     #38A6FF (active / live)  #D9822B (predictive)  #FF4D4D (risk)
#   monospace fonts for all numeric / data / log / status fields
#   dense layout, minimal padding (grids collapse, no fat margins)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
COLORS = {
    "bg_base":    "#0F131A",
    "bg_raised":  "#151A22",
    "text":       "#E1E8ED",
    "text_muted": "#8A97A8",
    "border":     "#242E3B",
    "accent":     "#38A6FF",
    "predictive": "#D9822B",
    "risk":       "#FF4D4D",
    "ok":         "#38A6FF",
    "selection":  "#1F2A3A",
    "hover":      "#1A2230",
}

QSS = f"""
/* ============================== BASE ============================== */
* {{
    outline: none;
}}
QWidget {{
    background-color: {COLORS['bg_base']};
    color: {COLORS['text']};
    font-size: 13px;
}}
QMainWindow, QDialog, QMessageBox {{
    background-color: {COLORS['bg_base']};
}}

/* Raised panels: cards, side drawers, detail panes */
QWidget[panel="true"] {{
    background-color: {COLORS['bg_raised']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
}}

/* Monospace for numeric / data / log / status fields */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit,
QTextEdit, QStatusBar, QLabel[mono="true"] {{
    font-family: "JetBrains Mono", "DejaVu Sans Mono", "Ubuntu Mono", monospace;
}}

/* Muted helper text */
QLabel[muted="true"] {{
    color: {COLORS['text_muted']};
}}

/* ============================== INPUTS ============================== */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {COLORS['bg_raised']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: {COLORS['selection']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {COLORS['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_raised']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['selection']};
}}

/* ============================== BUTTONS ============================== */
QPushButton {{
    background-color: {COLORS['bg_raised']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    padding: 4px 12px;
    color: {COLORS['text']};
}}
QPushButton:hover {{
    background-color: {COLORS['hover']};
    border-color: {COLORS['accent']};
}}
QPushButton:pressed {{
    background-color: {COLORS['selection']};
}}
QPushButton:default {{
    border-color: {COLORS['accent']};
}}
QPushButton:disabled {{
    color: {COLORS['text_muted']};
    border-color: {COLORS['border']};
}}

/* ============================== TABS ============================== */
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {COLORS['bg_raised']};
    border: 1px solid {COLORS['border']};
    border-bottom: none;
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    color: {COLORS['text_muted']};
}}
QTabBar::tab:selected {{
    background-color: {COLORS['bg_base']};
    border-top: 2px solid {COLORS['accent']};
    color: {COLORS['text']};
}}
QTabBar::tab:hover:!selected {{
    color: {COLORS['text']};
}}

/* ============================== TABLES / LISTS ============================== */
QTableWidget, QTreeWidget, QListWidget {{
    background-color: {COLORS['bg_raised']};
    border: 1px solid {COLORS['border']};
    border-radius: 3px;
    gridline-color: {COLORS['border']};
}}
QHeaderView::section {{
    background-color: {COLORS['bg_base']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    padding: 4px 8px;
    font-weight: 600;
}}
QTableWidget::item:selected, QTreeWidget::item:selected,
QListWidget::item:selected {{
    background-color: {COLORS['selection']};
    color: {COLORS['accent']};
}}
QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {COLORS['hover']};
}}

/* ============================== SCROLLBARS ============================== */
QScrollBar:vertical {{
    background: {COLORS['bg_base']};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border']};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS['accent']};
}}
QScrollBar:horizontal {{
    background: {COLORS['bg_base']};
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {COLORS['border']};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ============================== STATUS BADGES ============================== */
QLabel[role="active"]     {{ color: {COLORS['accent']}; }}
QLabel[role="predictive"] {{ color: {COLORS['predictive']}; }}
QLabel[role="risk"]       {{ color: {COLORS['risk']}; }}
QLabel[role="muted"]      {{ color: {COLORS['text_muted']}; }}

/* ============================== STATUS BAR ============================== */
QStatusBar {{
    background-color: {COLORS['bg_raised']};
    border-top: 1px solid {COLORS['border']};
    color: {COLORS['text_muted']};
}}
QStatusBar::item {{
    border: none;
}}

/* ============================== SPLITTER / GROUP BOX ============================== */
QSplitter::handle {{
    background-color: {COLORS['border']};
}}
QGroupBox {{
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {COLORS['text_muted']};
}}
"""


def apply_theme(app):
    """Apply the Command Center skin to a QApplication (or top-level widget).

    Call once at startup with the QApplication instance; also safe to call on
    a QMainWindow/QWidget to re-skin just that subtree.
    """
    app.setStyleSheet(QSS)
    return app
