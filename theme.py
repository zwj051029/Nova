"""Application-wide light/dark theme definitions."""

from __future__ import annotations

import platform

from PySide6.QtCore import QSettings


THEMES = {
    "light": {
        "window": "#F5F7FA",
        "surface": "#FFFFFF",
        "surface_alt": "#FAFBFC",
        "input": "#FFFFFF",
        "border": "#E5E8EB",
        "border_strong": "#D0D5DD",
        "text": "#1D2129",
        "text_secondary": "#4E5969",
        "muted": "#86909C",
        "disabled": "#C9CDD4",
        "nav": "#E8ECF1",
        "hover": "#E5E6EB",
        "pressed": "#D9DAE0",
        "accent": "#165DFF",
        "accent_hover": "#0E4BD7",
        "accent_soft": "#EEF4FF",
        "accent_border": "#B7D1FF",
        "plot": "#FFFFFF",
        "send_box": "#F0F8FF",
        "recv_box": "#FAFBFC",
        "warning_bg": "#FFF7E8",
        "warning_text": "#7A4E00",
        "warning_border": "#FFD591",
        "success": "#00B42A",
        "danger": "#F53F3F",
        "purple": "#722ED1",
    },
    "dark": {
        "window": "#0F141C",
        "surface": "#171D27",
        "surface_alt": "#1B222D",
        "input": "#111720",
        "border": "#2A3442",
        "border_strong": "#3A4658",
        "text": "#E8EDF5",
        "text_secondary": "#AAB4C4",
        "muted": "#7D899A",
        "disabled": "#596577",
        "nav": "#141A23",
        "hover": "#252E3C",
        "pressed": "#303B4C",
        "accent": "#4C8DFF",
        "accent_hover": "#70A4FF",
        "accent_soft": "#1A2942",
        "accent_border": "#35598A",
        "plot": "#111720",
        "send_box": "#111D2C",
        "recv_box": "#151B24",
        "warning_bg": "#332812",
        "warning_text": "#FFD27A",
        "warning_border": "#6E5420",
        "success": "#33D17A",
        "danger": "#FF6B6B",
        "purple": "#B18CFF",
    },
}


def system_font() -> str:
    if platform.system() == "Windows":
        return "Microsoft YaHei"
    if platform.system() == "Darwin":
        return "SF Pro Display"
    return "sans-serif"


def normalize_theme(theme: str | None) -> str:
    return theme if theme in THEMES else "light"


def load_theme() -> str:
    return normalize_theme(QSettings("Nova", "PIDTuner").value("theme", "light"))


def save_theme(theme: str) -> None:
    QSettings("Nova", "PIDTuner").setValue("theme", normalize_theme(theme))


def colors(theme: str) -> dict[str, str]:
    return THEMES[normalize_theme(theme)]


def global_style(theme: str) -> str:
    c = colors(theme)
    return f"""
QWidget {{
    font-family: "{system_font()}", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {c['text']};
}}
QMainWindow, QDialog, QStackedWidget {{ background: {c['window']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['window']}; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; background: {c['window']}; }}
QTabBar::tab {{ background: {c['surface_alt']}; color: {c['text_secondary']}; padding: 8px 12px; }}
QTabBar::tab:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QMenuBar {{ background: {c['surface']}; color: {c['text']}; border-bottom: 1px solid {c['border']}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {c['hover']}; border-radius: 4px; }}
QMenu {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']}; padding: 5px; }}
QMenu::item {{ padding: 6px 28px 6px 10px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QPushButton {{
    background-color: {c['hover']}; color: {c['text_secondary']}; border: none;
    border-radius: 4px; padding: 4px 10px;
}}
QPushButton:hover {{ background-color: {c['pressed']}; color: {c['text']}; }}
QPushButton:pressed {{ background-color: {c['border_strong']}; }}
QPushButton:disabled {{ background-color: {c['surface_alt']}; color: {c['disabled']}; }}
QGroupBox {{
    font-weight: bold; font-size: 13px; border: 1px solid {c['border']};
    border-radius: 6px; margin-top: 8px; background-color: {c['surface_alt']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {c['text']}; }}
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{
    border: 1px solid {c['border_strong']}; border-radius: 4px; padding: 2px 6px;
    background: {c['input']}; color: {c['text']}; min-height: 28px;
    selection-background-color: {c['accent']}; selection-color: white;
}}
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{ border: 2px solid {c['accent']}; }}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']};
    selection-background-color: {c['accent_soft']}; selection-color: {c['accent']};
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    background: {c['surface_alt']}; border-left: 1px solid {c['border']}; width: 18px;
}}
QCheckBox {{ spacing: 6px; color: {c['text']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['border_strong']}; border-radius: 3px; background: {c['input']}; }}
QCheckBox::indicator:checked {{ background-color: {c['accent']}; border-color: {c['accent']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; background: {c['accent']}; border-radius: 7px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSplitter::handle {{ background: {c['border']}; }}
QSplitter::handle:horizontal {{ width: 5px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QPlainTextEdit, QTextEdit {{
    background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']};
    selection-background-color: {c['accent']}; selection-color: white;
}}
QTableWidget {{
    background: {c['surface']}; alternate-background-color: {c['surface_alt']};
    color: {c['text']}; gridline-color: {c['border']}; border: 1px solid {c['border']};
}}
QHeaderView::section {{
    background: {c['surface_alt']}; color: {c['text_secondary']};
    border: none; border-right: 1px solid {c['border']}; border-bottom: 1px solid {c['border']};
    padding: 5px;
}}
QTableCornerButton::section {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; }}
QScrollBar:vertical {{ background: {c['surface_alt']}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {c['border_strong']}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border_strong']}; padding: 4px; }}
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['text_secondary']}; }}
"""


def nav_button_style(theme: str) -> str:
    c = colors(theme)
    return f"""
QPushButton {{ background: transparent; color: {c['text_secondary']}; border: none;
border-radius: 6px; padding: 10px 4px; font-size: 12px; }}
QPushButton:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton:checked {{ background: {c['accent']}; color: white; font-weight: bold; }}
"""
