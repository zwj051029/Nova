import sys
import platform
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QStatusBar, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QPalette, QColor, QAction

from i18n import Translator
from serial_worker import SerialWorker
from serial_page import SerialPage
from pid_page import PidPage


def _system_font() -> str:
    if platform.system() == "Windows":
        return "Microsoft YaHei"
    if platform.system() == "Darwin":
        return "SF Pro Display"
    return "sans-serif"


GLOBAL_STYLE = """
QWidget {
    font-family: "%(font)s", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #1D2129;
}
QPushButton {
    background-color: #F2F3F5;
    color: #4E5969;
    border: none;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover    { background-color: #E5E6EB; }
QPushButton:pressed  { background-color: #D9DAE0; }
QPushButton:disabled { background-color: #F2F3F5; color: #C9CDD4; }
QGroupBox {
    font-weight: bold;
    font-size: 13px;
    border: 1px solid #E5E8EB;
    border-radius: 6px;
    margin-top: 8px;
    background-color: #FAFBFC;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #1D2129;
}
QComboBox {
    border: 1px solid #D0D5DD;
    border-radius: 4px;
    padding: 3px 6px;
    background: white;
    min-height: 28px;
}
QComboBox:focus {
    border: 2px solid #165DFF;
}
QComboBox::drop-down { border: none; }
QDoubleSpinBox, QSpinBox, QLineEdit {
    border: 1px solid #D0D5DD;
    border-radius: 4px;
    padding: 2px 6px;
    background: white;
    min-height: 28px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {
    border: 2px solid #165DFF;
}
QCheckBox {
    spacing: 6px;
    color: #1D2129;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #D0D5DD;
    border-radius: 3px;
    background: white;
}
QCheckBox::indicator:checked {
    background-color: #165DFF;
    border-color: #165DFF;
    image: none;
}
QCheckBox::indicator:hover {
    border-color: #165DFF;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #E5E8EB;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px; height: 14px;
    margin: -5px 0;
    background: #165DFF;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #165DFF;
    border-radius: 2px;
}
QSplitter::handle {
    background: #E5E8EB;
}
QSplitter::handle:horizontal { width: 5px; }
QSplitter::handle:vertical   { height: 3px; }
QStatusBar {
    background: #F7F8FA;
    border-top: 1px solid #E5E8EB;
    font-size: 12px;
    color: #4E5969;
}
""" % {"font": _system_font()}

NAV_BTN_STYLE = """
QPushButton {
    background-color: transparent;
    color: #666666;
    border: none;
    border-radius: 6px;
    padding: 10px 4px;
    font-size: 12px;
}
QPushButton:hover   { background-color: #D8DFE8; color: #1D2129; }
QPushButton:checked { background-color: #165DFF; color: white; font-weight: bold; }
"""


# ---------------------------------------------------------------------------
# Toast notification
# ---------------------------------------------------------------------------

class ToastWidget(QWidget):
    """顶部居中浮层提示，显示 2 秒后自动淡出。"""

    def __init__(self, message: str, success: bool, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        icon_lbl = QLabel("✓" if success else "✗")
        icon_lbl.setStyleSheet(
            f"color: {'#00B42A' if success else '#F53F3F'};"
            "font-size: 14px; font-weight: bold;"
        )
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("color: #1D2129; font-size: 14px;")
        msg_lbl.setMinimumWidth(88)
        msg_lbl.setMaximumWidth(268)

        layout.addWidget(icon_lbl)
        layout.addWidget(msg_lbl)

        self.setStyleSheet("""
            ToastWidget {
                background-color: white;
                border: 1px solid #E5E8EB;
                border-radius: 8px;
            }
        """)

        self.adjustSize()
        self._position_center(parent)
        self.raise_()
        self.show()

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

        QTimer.singleShot(2000, self._start_fade_out)

    def _position_center(self, parent: QWidget) -> None:
        x = (parent.width() - self.width()) // 2
        self.move(x, 20)

    def _start_fade_out(self) -> None:
        self._fade_anim.setDuration(300)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_anim.finished.connect(self.close)
        self._fade_anim.start()


class _StatusIndicator(QWidget):
    """状态栏内容 widget。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(0)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("color: #86909C; font-size: 10px;")

        self._status_lbl = QLabel()
        self._port_lbl = QLabel()
        self._baud_lbl = QLabel()
        self._rx_lbl = QLabel()
        self._tx_lbl = QLabel()

        for lbl in (self._status_lbl, self._port_lbl, self._baud_lbl,
                    self._rx_lbl, self._tx_lbl):
            lbl.setStyleSheet("color: #4E5969; font-size: 12px;")

        def sep():
            s = QLabel("  |  ")
            s.setStyleSheet("color: #C9CDD4; font-size: 12px;")
            return s

        layout.addWidget(self._dot)
        layout.addSpacing(4)
        layout.addWidget(self._status_lbl)
        layout.addWidget(sep())
        layout.addWidget(self._port_lbl)
        layout.addWidget(sep())
        layout.addWidget(self._baud_lbl)
        layout.addWidget(sep())
        layout.addWidget(self._rx_lbl)
        layout.addWidget(sep())
        layout.addWidget(self._tx_lbl)
        layout.addStretch()

    def set_disconnected(self, t) -> None:
        self._dot.setStyleSheet("color: #86909C; font-size: 10px;")
        self._status_lbl.setText(t("status_disconnected"))
        self._port_lbl.setText(f"{t('status_port')}: --")
        self._baud_lbl.setText(f"{t('status_baud')}: --")
        self._rx_lbl.setText(f"{t('status_rx')}: 0 B")
        self._tx_lbl.setText(f"{t('status_tx')}: 0 B")

    def set_connected(self, t, port: str, baud: int) -> None:
        self._dot.setStyleSheet("color: #00B42A; font-size: 10px;")
        self._status_lbl.setText(t("status_connected"))
        self._port_lbl.setText(f"{t('status_port')}: {port}")
        self._baud_lbl.setText(f"{t('status_baud')}: {baud}")
        self._rx_lbl.setText(f"{t('status_rx')}: 0 B")
        self._tx_lbl.setText(f"{t('status_tx')}: 0 B")

    def update_rx(self, t, n: int) -> None:
        self._rx_lbl.setText(f"{t('status_rx')}: {n} B")

    def update_tx(self, t, n: int) -> None:
        self._tx_lbl.setText(f"{t('status_tx')}: {n} B")

    def retranslate(self, t, connected: bool, port: str, baud: int,
                    rx: int, tx: int) -> None:
        if connected:
            self.set_connected(t, port, baud)
            self.update_rx(t, rx)
            self.update_tx(t, tx)
        else:
            self.set_disconnected(t)


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

        self._connected_port = ""
        self._connected_baud = 0

        self._build_ui()
        self._build_menu()
        self._build_status_bar()

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
        self._serial_page.on_data_sent = self._on_data_sent
        self._serial_page.on_toast = self._show_toast
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
        self._nav_serial_btn.setMinimumHeight(64)
        self._nav_serial_btn.clicked.connect(lambda: self._switch_page(0))

        self._nav_pid_btn = QPushButton()
        self._nav_pid_btn.setStyleSheet(NAV_BTN_STYLE)
        self._nav_pid_btn.setCheckable(True)
        self._nav_pid_btn.setMinimumHeight(64)
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

    def _build_status_bar(self) -> None:
        self._status_indicator = _StatusIndicator()
        sb = self.statusBar()
        sb.setFixedHeight(30)
        sb.addWidget(self._status_indicator, 1)

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
        self._status_indicator.update_rx(self._tr.tr, self._worker.rx_bytes)

    def _on_data_sent(self) -> None:
        self._status_indicator.update_tx(self._tr.tr, self._worker.tx_bytes)

    def _show_toast(self, message: str, success: bool) -> None:
        ToastWidget(message, success, self.centralWidget())

    def _on_connection_changed(self, opened: bool) -> None:
        self._pid_page.set_send_enabled(opened)
        if opened:
            self._connected_port = self._serial_page.current_port()
            self._connected_baud = self._serial_page.current_baud()
            self._status_indicator.set_connected(
                self._tr.tr, self._connected_port, self._connected_baud)
        else:
            self._connected_port = ""
            self._connected_baud = 0
            self._status_indicator.set_disconnected(self._tr.tr)
            self._pid_page.clear_plot()

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def _retranslate(self) -> None:
        t = self._tr.tr
        self.setWindowTitle(t("window_title"))
        self._nav_serial_btn.setText("🔌\n" + t("nav_serial"))
        self._nav_pid_btn.setText("📈\n" + t("nav_pid"))
        self._lang_menu.setTitle(t("menu_language"))
        self._action_zh.setText(t("lang_zh"))
        self._action_en.setText(t("lang_en"))
        self._status_indicator.retranslate(
            t,
            self._worker.is_open(),
            self._connected_port,
            self._connected_baud,
            self._worker.rx_bytes,
            self._worker.tx_bytes,
        )

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
