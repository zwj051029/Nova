import sys
import platform
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QAction

from i18n import Translator
from serial_worker import SerialWorker
from serial_page import SerialPage
from pid_page import PidPage


def _system_font() -> str:
    if platform.system() == "Windows":
        return "Segoe UI"
    if platform.system() == "Darwin":
        return "SF Pro Display"
    return "sans-serif"


GLOBAL_STYLE = """
QWidget {
    font-family: "%(font)s", sans-serif;
    font-size: 9pt;
    color: #333333;
}
QPushButton {
    background-color: #A8E6CF;
    color: #333333;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
}
QPushButton:hover    { background-color: #8FD3B5; }
QPushButton:pressed  { background-color: #6DB89A; }
QPushButton:disabled { background-color: #D0D0D0; color: #888888; }
QGroupBox {
    font-weight: bold;
    border: 1px solid #B8C4D0;
    border-radius: 6px;
    margin-top: 8px;
    background-color: rgba(255,255,255,220);
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QComboBox {
    border: 1px solid #C8D0DC;
    border-radius: 4px;
    padding: 3px 6px;
    background: white;
}
QComboBox::drop-down { border: none; }
QDoubleSpinBox, QSpinBox, QLineEdit {
    border: 1px solid #C8D0DC;
    border-radius: 4px;
    padding: 2px 4px;
    background: white;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #D0D8E4;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px; height: 12px;
    margin: -4px 0;
    background: #6DB89A;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: #A8E6CF;
    border-radius: 2px;
}
QSplitter::handle {
    background: #D0D8E4;
}
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical   { height: 3px; }
""" % {"font": _system_font()}

NAV_BTN_STYLE = """
QPushButton {
    background-color: transparent;
    color: #555;
    border: none;
    border-radius: 6px;
    padding: 8px 4px;
    font-size: 9pt;
}
QPushButton:hover   { background-color: #D8DFE8; }
QPushButton:checked { background-color: #C5D5E8; color: #1A3A5C; font-weight: bold; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1280, 800)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#F5F7FA"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self._tr = Translator()
        self._tr.on_change(self._retranslate)

        self._worker = SerialWorker()
        self._worker.line_received.connect(self._on_line_received)

        self._build_ui()
        self._build_menu()

        self._serial_page.refresh_ports()
        self._pid_page.set_send_enabled(False)
        self._retranslate()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_nav())

        self._stack = QStackedWidget()
        self._serial_page = SerialPage(self._worker)
        self._serial_page.on_connection_changed = self._on_connection_changed
        self._pid_page = PidPage(self._worker)
        self._stack.addWidget(self._serial_page)   # index 0
        self._stack.addWidget(self._pid_page)       # index 1

        outer.addWidget(self._stack, stretch=1)

    def _build_nav(self) -> QWidget:
        nav = QWidget()
        nav.setFixedWidth(72)
        nav.setStyleSheet("background-color: #E8ECF1; border-right: 1px solid #D0D8E4;")

        layout = QVBoxLayout(nav)
        layout.setContentsMargins(4, 12, 4, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._nav_serial_btn = QPushButton()
        self._nav_serial_btn.setStyleSheet(NAV_BTN_STYLE)
        self._nav_serial_btn.setCheckable(True)
        self._nav_serial_btn.setChecked(True)
        self._nav_serial_btn.clicked.connect(lambda: self._switch_page(0))

        self._nav_pid_btn = QPushButton()
        self._nav_pid_btn.setStyleSheet(NAV_BTN_STYLE)
        self._nav_pid_btn.setCheckable(True)
        self._nav_pid_btn.clicked.connect(lambda: self._switch_page(1))

        layout.addWidget(self._nav_serial_btn)
        layout.addWidget(self._nav_pid_btn)
        layout.addStretch()
        return nav

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        self._lang_menu = menubar.addMenu("")
        self._action_zh = QAction("中文", self)
        self._action_en = QAction("English", self)
        self._action_zh.triggered.connect(lambda: self._tr.set_lang("zh"))
        self._action_en.triggered.connect(lambda: self._tr.set_lang("en"))
        self._lang_menu.addAction(self._action_zh)
        self._lang_menu.addAction(self._action_en)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _switch_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._nav_serial_btn.setChecked(index == 0)
        self._nav_pid_btn.setChecked(index == 1)

    # ------------------------------------------------------------------
    # Data routing
    # ------------------------------------------------------------------

    def _on_line_received(self, line: str) -> None:
        self._serial_page.append_received(line)
        self._pid_page.ingest_line(line)

    def _on_connection_changed(self, opened: bool) -> None:
        self._pid_page.set_send_enabled(opened)
        if not opened:
            self._pid_page.clear_plot()

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def _retranslate(self) -> None:
        t = self._tr.tr
        self.setWindowTitle(t("window_title"))
        self._nav_serial_btn.setText(t("nav_serial"))
        self._nav_pid_btn.setText(t("nav_pid"))
        self._lang_menu.setTitle(t("menu_language"))
        self._action_zh.setText(t("lang_zh"))
        self._action_en.setText(t("lang_en"))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._worker.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
