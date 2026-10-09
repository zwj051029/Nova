import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QStatusBar, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QPalette, QColor, QAction, QActionGroup

from i18n import Translator
from serial_worker import SerialWorker
from serial_page import SerialPage
from pid_page import PidPage
from ai_tuning_page import AiTuningPage
from tuning.models import PIDGains
from theme import colors, global_style, load_theme, nav_button_style, save_theme


# ---------------------------------------------------------------------------
# Toast notification
# ---------------------------------------------------------------------------

class ToastWidget(QWidget):
    """顶部居中浮层提示，显示 2 秒后自动淡出。"""

    def __init__(self, message: str, success: bool, parent: QWidget, theme: str):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        c = colors(theme)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        icon_lbl = QLabel("✓" if success else "✗")
        icon_lbl.setStyleSheet(
            f"color: {'#00B42A' if success else '#F53F3F'};"
            "font-size: 14px; font-weight: bold;"
        )
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet(f"color: {c['text']}; font-size: 14px;")
        msg_lbl.setMinimumWidth(88)
        msg_lbl.setMaximumWidth(268)

        layout.addWidget(icon_lbl)
        layout.addWidget(msg_lbl)

        self.setStyleSheet(f"""
            ToastWidget {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
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
        self._separators: list[QLabel] = []

        def sep():
            s = QLabel("  |  ")
            self._separators.append(s)
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
        self.apply_theme("light")

    def apply_theme(self, theme: str) -> None:
        c = colors(theme)
        for lbl in (self._status_lbl, self._port_lbl, self._baud_lbl,
                    self._rx_lbl, self._tx_lbl):
            lbl.setStyleSheet(f"color: {c['text_secondary']}; font-size: 12px;")
        for separator in self._separators:
            separator.setStyleSheet(f"color: {c['disabled']}; font-size: 12px;")

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
        self._theme = load_theme()

        self._tr = Translator()
        self._tr.on_change(self._retranslate)

        self._worker = SerialWorker()
        self._worker.chunk_received.connect(self._on_chunk_received)
        self._worker.lines_received.connect(self._on_lines_received)
        self._worker.connection_lost.connect(self._on_connection_lost)

        self._connected_port = ""
        self._connected_baud = 0

        # throttle buffer: accumulate lines, flush to UI every 50ms
        self._pending_lines: list[str] = []
        self._pending_chunks: list[bytes] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_lines)
        self._flush_timer.start()

        self._build_ui()
        self._build_menu()
        self._build_status_bar()

        self._serial_page.refresh_ports()
        self._pid_page.set_send_enabled(False)
        self._apply_theme(self._theme, persist=False)
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
        self._serial_page.on_before_disconnect = self._restore_ai_baseline
        self._serial_page.on_data_sent = self._on_data_sent
        self._serial_page.on_toast = self._show_toast
        self._pid_page = PidPage(self._worker)
        self._pid_page.on_toast = self._show_toast
        self._ai_page = AiTuningPage(self._worker)
        self._ai_page.on_toast = self._show_toast
        self._ai_page.on_data_sent = self._on_data_sent
        self._ai_page.on_pid_applied = self._on_ai_pid_applied
        self._ai_page.baseline_provider = self._manual_pid_gains
        self._stack.addWidget(self._serial_page)   # index 0
        self._stack.addWidget(self._pid_page)       # index 1
        self._stack.addWidget(self._ai_page)        # index 2

        outer.addWidget(self._stack, stretch=1)

    def _build_nav(self) -> QWidget:
        nav = QWidget()
        nav.setFixedWidth(72)
        self._nav = nav

        layout = QVBoxLayout(nav)
        layout.setContentsMargins(4, 12, 4, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._nav_serial_btn = QPushButton()
        self._nav_serial_btn.setCheckable(True)
        self._nav_serial_btn.setChecked(True)
        self._nav_serial_btn.setMinimumHeight(64)
        self._nav_serial_btn.clicked.connect(lambda: self._switch_page(0))

        self._nav_pid_btn = QPushButton()
        self._nav_pid_btn.setCheckable(True)
        self._nav_pid_btn.setMinimumHeight(64)
        self._nav_pid_btn.clicked.connect(lambda: self._switch_page(1))

        self._nav_ai_btn = QPushButton()
        self._nav_ai_btn.setCheckable(True)
        self._nav_ai_btn.setMinimumHeight(64)
        self._nav_ai_btn.clicked.connect(lambda: self._switch_page(2))

        layout.addWidget(self._nav_serial_btn)
        layout.addWidget(self._nav_pid_btn)
        layout.addWidget(self._nav_ai_btn)
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

        self._theme_menu = menubar.addMenu("")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._action_light = QAction("", self, checkable=True)
        self._action_dark = QAction("", self, checkable=True)
        self._theme_group.addAction(self._action_light)
        self._theme_group.addAction(self._action_dark)
        self._theme_menu.addAction(self._action_light)
        self._theme_menu.addAction(self._action_dark)
        self._action_light.triggered.connect(lambda: self._apply_theme("light"))
        self._action_dark.triggered.connect(lambda: self._apply_theme("dark"))

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
        self._nav_ai_btn.setChecked(index == 2)

    # ------------------------------------------------------------------
    # Data routing
    # ------------------------------------------------------------------

    def _on_chunk_received(self, chunk: bytes) -> None:
        self._pending_chunks.append(chunk)

    def _on_lines_received(self, lines: list) -> None:
        self._pending_lines.extend(lines)

    def _flush_lines(self) -> None:
        self._pid_page.set_send_enabled(self._worker.is_open() and self._worker.owner is None)
        self._serial_page.set_control_locked(self._worker.owner is not None)
        self._status_indicator.update_tx(self._tr.tr, self._worker.tx_bytes)
        # 刷新原始数据到接收区
        if self._pending_chunks:
            chunks = self._pending_chunks
            self._pending_chunks = []
            combined = b"".join(chunks)
            self._serial_page.append_received_bytes(combined)
            self._status_indicator.update_rx(self._tr.tr, self._worker.rx_bytes)

        # 刷新文本行到 PID 图
        if self._pending_lines:
            lines = self._pending_lines
            self._pending_lines = []
            for line in lines:
                self._pid_page.ingest_line(line)
                self._ai_page.ingest_line(line)
            self._pid_page.refresh_plot()
            self._ai_page.refresh_plot()

    def _on_connection_lost(self, reason: str) -> None:
        self._worker.close()
        self._serial_page.handle_disconnect()
        self._show_toast(reason, False)

    def _on_data_sent(self) -> None:
        self._status_indicator.update_tx(self._tr.tr, self._worker.tx_bytes)

    def _manual_pid_gains(self) -> PIDGains:
        return PIDGains(*self._pid_page.current_values())

    def _on_ai_pid_applied(self, gains: PIDGains) -> None:
        self._pid_page.set_values(gains.kp, gains.ki, gains.kd)

    def _restore_ai_baseline(self) -> bool:
        auto=self._ai_page._auto
        if auto and auto.active:
            if auto.state != "stopping":
                auto.stop()
            return not auto.active
        self._ai_page.restore_baseline()
        return True

    def _show_toast(self, message: str, success: bool) -> None:
        old = getattr(self, "_toast", None)
        if old is not None:
            try:
                old.close()
            except RuntimeError:
                pass
            self._toast = None
        toast = ToastWidget(message, success, self.centralWidget(), self._theme)
        self._toast = toast
        toast.destroyed.connect(self._on_toast_destroyed)

    def _on_toast_destroyed(self, obj) -> None:
        if self._toast is obj:
            self._toast = None

    def _on_connection_changed(self, opened: bool) -> None:
        self._pid_page.set_send_enabled(opened)
        self._ai_page.set_connected(opened)
        if opened:
            self._connected_port = self._serial_page.current_port()
            self._connected_baud = self._serial_page.current_baud()
            self._status_indicator.set_connected(
                self._tr.tr, self._connected_port, self._connected_baud)
        else:
            self._connected_port = ""
            self._connected_baud = 0
            self._pending_lines.clear()
            self._pending_chunks.clear()
            self._status_indicator.set_disconnected(self._tr.tr)
            self._pid_page.clear_plot()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self, theme: str, persist: bool = True) -> None:
        self._theme = theme if theme in ("light", "dark") else "light"
        c = colors(self._theme)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(global_style(self._theme))
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
            palette.setColor(QPalette.ColorRole.Base, QColor(c["input"]))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["surface_alt"]))
            palette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
            palette.setColor(QPalette.ColorRole.Button, QColor(c["surface_alt"]))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(c["accent"]))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
            app.setPalette(palette)
        self.setAutoFillBackground(True)
        self._nav.setStyleSheet(
            f"background:{c['nav']}; border-right:1px solid {c['border']};")
        nav_style = nav_button_style(self._theme)
        for button in (self._nav_serial_btn, self._nav_pid_btn, self._nav_ai_btn):
            button.setStyleSheet(nav_style)
        self._status_indicator.apply_theme(self._theme)
        self._serial_page.apply_theme(self._theme)
        self._pid_page.apply_theme(self._theme)
        self._ai_page.apply_theme(self._theme)
        self._action_light.setChecked(self._theme == "light")
        self._action_dark.setChecked(self._theme == "dark")
        if persist:
            save_theme(self._theme)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def _retranslate(self) -> None:
        t = self._tr.tr
        self.setWindowTitle(t("window_title"))
        self._nav_serial_btn.setText("🔌\n" + t("nav_serial"))
        self._nav_pid_btn.setText("📈\n" + t("nav_pid"))
        self._nav_ai_btn.setText("✨\n" + t("nav_ai"))
        self._lang_menu.setTitle(t("menu_language"))
        self._action_zh.setText(t("lang_zh"))
        self._action_en.setText(t("lang_en"))
        self._theme_menu.setTitle(t("menu_theme"))
        self._action_light.setText(t("theme_light"))
        self._action_dark.setText(t("theme_dark"))
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
        auto = self._ai_page._auto
        if auto and auto.active:
            if auto.state != "stopping":
                auto.stop()
            QTimer.singleShot(200, self.close)
            event.ignore()
            return
        self._ai_page.restore_baseline()
        self._worker.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("Nova")
    app.setApplicationName("Nova")
    from version import __version__
    app.setApplicationVersion(__version__)
    app.setStyleSheet(global_style(load_theme()))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
