import serial
import serial.tools.list_ports
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QLineEdit, QCheckBox, QSpinBox, QPlainTextEdit,
    QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, QObject, Signal
from PySide6.QtGui import (
    QFont, QColor, QTextCursor, QTextCharFormat,
    QKeySequence, QCursor, QShortcut,
)

from i18n import Translator
from serial_worker import SerialWorker
from theme import colors

BTN_OPEN_STYLE = """
QPushButton {
    background-color: #165DFF;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #0E4BD7; }
QPushButton:pressed { background-color: #0A3AB0; }
QPushButton:disabled { background-color: #D0D0D0; color: #888888; }
"""

BTN_CLOSE_STYLE = """
QPushButton {
    background-color: #E05555;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #C94444; }
QPushButton:pressed { background-color: #B03333; }
"""

MODE_STR_STYLE = ""

MODE_HEX_STYLE = """
QPushButton {
    background-color: #F5A623;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #E09515; }
QPushButton:pressed { background-color: #C8840A; }
"""

_MONO_FONT = QFont("Consolas", 11)

_BOX_STYLE_SEND = (
    "background: #F0F8FF;"
    "border: 1px solid #E5E8EB;"
    "border-radius: 6px;"
)
_BOX_STYLE_RECV = (
    "background: #FAFBFC;"
    "border: 1px solid #E5E8EB;"
    "border-radius: 6px;"
)


# ---------------------------------------------------------------------------
# Rotating refresh button
# ---------------------------------------------------------------------------

# 8 帧箭头字符模拟旋转
_SPIN_FRAMES = ["↻", "↷", "↶", "↺", "↻", "↷", "↶", "↺"]

class RefreshButton(QPushButton):
    """圆形刷新按钮，用 QTimer 帧切换模拟旋转动画。"""

    def __init__(self, parent=None):
        super().__init__("↻", parent)
        self.setFixedSize(32, 32)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.apply_theme("light")
        self._frame = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(80)  # ~12fps, 8帧 ≈ 1圈/秒
        self._spin_timer.timeout.connect(self._next_frame)

    def apply_theme(self, theme: str) -> None:
        c = colors(theme)
        self.setStyleSheet(f"""
            QPushButton {{
                background: {c['surface']};
                border: 1px solid {c['border_strong']};
                border-radius: 16px;
                font-size: 16px;
                color: {c['text_secondary']};
            }}
            QPushButton:hover {{
                background: {c['accent_soft']};
                color: {c['accent']};
                border-color: {c['accent']};
            }}
            QPushButton:pressed {{
                background: {c['pressed']};
                color: {c['accent']};
            }}
            QPushButton:disabled {{
                background: {c['surface_alt']};
                border: 1px solid {c['border']};
                color: {c['disabled']};
            }}
        """)

    def _next_frame(self) -> None:
        self._frame = (self._frame + 1) % len(_SPIN_FRAMES)
        self.setText(_SPIN_FRAMES[self._frame])

    def start_spin(self) -> None:
        self._frame = 0
        self.setEnabled(False)
        self.setToolTip("")
        self._spin_timer.start()

    def stop_spin(self) -> None:
        self._spin_timer.stop()
        self.setText("↻")
        self.setEnabled(True)


# ---------------------------------------------------------------------------
# Background port scanner
# ---------------------------------------------------------------------------

class _PortScanner(QObject):
    finished = Signal(list, str)  # (ports, error_msg)

    def scan(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
            self.finished.emit(ports, "")
        except Exception as e:
            self.finished.emit([], str(e))


# ---------------------------------------------------------------------------
# SerialPage
# ---------------------------------------------------------------------------

class SerialPage(QWidget):
    """
    串口收发页面。

    布局：
      ┌──────────────┬──────────────────────────────┐
      │  左：串口参数  │  右上：发送区（可拖拽）         │
      │  配置面板     ├──────────────────────────────┤
      │              │  右下：接收区（可拖拽）         │
      └──────────────┴──────────────────────────────┘
    """

    def __init__(self, worker: SerialWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._theme = "light"
        self._tr = Translator()
        self._loop_timer = QTimer(self)
        self._loop_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._loop_timer.timeout.connect(self._do_send)
        self._tr.on_change(self.retranslate)
        self.on_connection_changed = None
        self.on_before_disconnect = None
        self.on_data_sent = None
        self.on_toast = None
        self._is_recv_hex = False  # False=字符串, True=十六进制

        self._scanner = _PortScanner()
        self._scanner.finished.connect(self._on_scan_finished)

        self._build_ui()

        # F5 shortcut
        sc = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        sc.activated.connect(self._trigger_refresh)

        self.retranslate()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._left_panel = self._build_left_panel()
        h_splitter.addWidget(self._left_panel)
        h_splitter.addWidget(self._build_right_panel())
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)
        h_splitter.setSizes([220, 800])

        root.addWidget(h_splitter)

    # ---- left: serial config ----

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(180)
        panel.setMaximumWidth(480)

        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(0)

        self._config_group = QGroupBox()
        group_layout = QVBoxLayout(self._config_group)
        group_layout.setContentsMargins(8, 14, 8, 8)
        group_layout.setSpacing(0)

        col_splitter = QSplitter(Qt.Orientation.Horizontal)
        col_splitter.setHandleWidth(4)

        lbl_widget = QWidget()
        lbl_grid = QGridLayout(lbl_widget)
        lbl_grid.setSpacing(8)
        lbl_grid.setContentsMargins(4, 0, 0, 0)

        ctrl_widget = QWidget()
        ctrl_grid = QGridLayout(ctrl_widget)
        ctrl_grid.setSpacing(8)
        ctrl_grid.setContentsMargins(0, 0, 4, 0)
        ctrl_grid.setColumnStretch(0, 1)

        col_splitter.addWidget(lbl_widget)
        col_splitter.addWidget(ctrl_widget)
        col_splitter.setStretchFactor(0, 0)
        col_splitter.setStretchFactor(1, 1)
        col_splitter.setSizes([64, 200])
        group_layout.addWidget(col_splitter)

        def row(label_attr, combo_attr, items, default=None, r=0):
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            setattr(self, label_attr, lbl)
            cb = QComboBox()
            cb.addItems(items)
            if default:
                cb.setCurrentText(default)
            setattr(self, combo_attr, cb)
            lbl_grid.addWidget(lbl, r, 0)
            ctrl_grid.addWidget(cb, r, 0)

        # port row with round refresh button
        self._port_label = QLabel()
        self._port_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._port_combo = QComboBox()
        self._refresh_btn = RefreshButton()
        self._refresh_btn.clicked.connect(self._trigger_refresh)
        lbl_grid.addWidget(self._port_label, 0, 0)
        port_row = QHBoxLayout()
        port_row.setSpacing(4)
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.addWidget(self._port_combo, stretch=1)
        port_row.addWidget(self._refresh_btn)
        port_container = QWidget()
        port_container.setLayout(port_row)
        ctrl_grid.addWidget(port_container, 0, 0)

        row("_baud_label", "_baud_combo",
            ["1200","2400","4800","9600","19200","38400","57600","115200","230400","460800","921600"],
            "115200", r=1)
        row("_flow_label", "_flow_combo",
            ["None", "XON/XOFF", "RTS/CTS", "DSR/DTR"], r=2)
        row("_parity_label", "_parity_combo",
            ["None", "Even", "Odd", "Mark", "Space"], r=3)
        row("_bytesize_label", "_bytesize_combo",
            ["5", "6", "7", "8"], "8", r=4)
        row("_stopbits_label", "_stopbits_combo",
            ["1", "1.5", "2"], "1", r=5)

        self._signals_label = QLabel()
        group_layout.addSpacing(4)
        group_layout.addWidget(self._signals_label)

        sig_row = QHBoxLayout()
        self._dtr_chk = QCheckBox("DTR")
        self._rts_chk = QCheckBox("RTS")
        self._brk_chk = QCheckBox("Break")
        for chk in (self._dtr_chk, self._rts_chk, self._brk_chk):
            sig_row.addWidget(chk)
            chk.toggled.connect(self._update_signals)
        sig_row.addStretch()
        sig_widget = QWidget()
        sig_widget.setLayout(sig_row)
        group_layout.addWidget(sig_widget)

        v.addWidget(self._config_group)

        self._toggle_btn = QPushButton()
        self._toggle_btn.setMinimumHeight(40)
        self._toggle_btn.setStyleSheet(BTN_OPEN_STYLE)
        self._toggle_btn.clicked.connect(self._toggle_serial)
        v.addSpacing(8)
        v.addWidget(self._toggle_btn)
        v.addStretch()
        return panel

    # ---- right: send + receive ----

    def _build_right_panel(self) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self._build_send_panel())
        v_splitter.addWidget(self._build_recv_panel())
        v_splitter.setStretchFactor(0, 1)
        v_splitter.setStretchFactor(1, 2)

        v.addWidget(v_splitter)
        return container

    def _build_send_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 8)
        v.setSpacing(8)

        hdr = QHBoxLayout()
        self._send_label = QLabel()
        self._send_label.setStyleSheet("font-weight: bold; color: #555;")
        self._clear_send_btn = QPushButton()
        self._clear_send_btn.setFixedWidth(72)
        self._clear_send_btn.clicked.connect(self._clear_send_box)
        hdr.addWidget(self._send_label)
        hdr.addStretch()
        hdr.addWidget(self._clear_send_btn)
        v.addLayout(hdr)

        self._send_box = QPlainTextEdit()
        self._send_box.setMaximumBlockCount(10000)
        self._send_box.setReadOnly(True)
        self._send_box.setFont(_MONO_FONT)
        self._send_box.setStyleSheet(_BOX_STYLE_SEND)
        v.addWidget(self._send_box, stretch=1)

        input_row = QHBoxLayout()
        self._send_input = QLineEdit()
        self._send_input.setFont(_MONO_FONT)
        self._send_input.returnPressed.connect(self._manual_send)
        self._send_btn = QPushButton()
        self._send_btn.setFixedWidth(64)
        self._send_btn.clicked.connect(self._manual_send)
        input_row.addWidget(self._send_input, stretch=1)
        input_row.addWidget(self._send_btn)
        v.addLayout(input_row)

        self._is_hex_mode = False

        self._mode_btn = QPushButton()
        self._mode_btn.setFixedWidth(100)
        self._mode_btn.clicked.connect(self._toggle_mode)

        self._loop_chk = QCheckBox()
        self._loop_chk.toggled.connect(self._toggle_loop)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(50, 60000)
        self._interval_spin.setValue(1000)
        self._interval_spin.setMinimumWidth(90)
        self._interval_spin.valueChanged.connect(self._loop_timer.setInterval)
        self._suffix_combo = QComboBox()
        self._suffix_combo.addItems(["CRLF", "LF", "CR", "None"])
        self._suffix_combo.setToolTip("发送结尾 / Line ending")

        self._interval_label = QLabel()

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        opt_row.addWidget(self._mode_btn)
        opt_row.addWidget(self._suffix_combo)
        opt_row.addSpacing(4)
        opt_row.addWidget(self._loop_chk)
        opt_row.addWidget(self._interval_spin)
        opt_row.addWidget(self._interval_label)
        opt_row.addStretch()
        v.addLayout(opt_row)

        return panel

    def _build_recv_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 8, 12, 12)
        v.setSpacing(8)

        hdr = QHBoxLayout()
        self._recv_label = QLabel()
        self._recv_label.setStyleSheet("font-weight: bold; color: #555;")

        self._recv_mode_btn = QPushButton()
        self._recv_mode_btn.setFixedWidth(100)
        self._recv_mode_btn.clicked.connect(self._toggle_recv_mode)

        self._clear_recv_btn = QPushButton()
        self._clear_recv_btn.setFixedWidth(72)
        self._clear_recv_btn.clicked.connect(self._clear_recv_box)

        hdr.addWidget(self._recv_label)
        hdr.addStretch()
        hdr.addWidget(self._recv_mode_btn)
        hdr.addSpacing(4)
        hdr.addWidget(self._clear_recv_btn)
        v.addLayout(hdr)

        self._recv_box = QPlainTextEdit()
        self._recv_box.setMaximumBlockCount(10000)
        self._recv_box.setReadOnly(True)
        self._recv_box.setFont(_MONO_FONT)
        self._recv_box.setStyleSheet(_BOX_STYLE_RECV)
        v.addWidget(self._recv_box, stretch=1)
        return panel

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_received(self, line: str) -> None:
        self._append_to(self._recv_box, line, "#2E7D32")

    def append_received_bytes(self, data: bytes) -> None:
        if self._is_recv_hex:
            # 每 16 字节一行，保证对齐不折行
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                hex_str = " ".join(f"{b:02X}" for b in chunk)
                self._append_to(self._recv_box, hex_str, "#7B5EA7")
        else:
            try:
                text = data.decode("utf-8").rstrip("\r\n")
                for line in text.splitlines():
                    if line:
                        self._append_to(self._recv_box, line, "#2E7D32")
            except UnicodeDecodeError:
                for i in range(0, len(data), 16):
                    chunk = data[i:i + 16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    self._append_to(self._recv_box, hex_str, "#7B5EA7")

    def current_port(self) -> str:
        return self._port_combo.currentText()

    def current_baud(self) -> int:
        try:
            return int(self._baud_combo.currentText())
        except ValueError:
            return 115200

    # ------------------------------------------------------------------
    # Refresh ports
    # ------------------------------------------------------------------

    def refresh_ports(self) -> None:
        """Synchronous refresh used on startup (before UI is shown)."""
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self._apply_ports(ports)

    def _trigger_refresh(self) -> None:
        """Async refresh triggered by button or F5."""
        if self._worker.is_open():
            return
        self._prev_ports = set(
            self._port_combo.itemText(i) for i in range(self._port_combo.count())
            if self._port_combo.itemText(i) != self._tr.tr("no_port")
        )
        self._prev_selection = self._port_combo.currentText()
        self._refresh_btn.start_spin()
        self._scanner.scan()

    def _on_scan_finished(self, ports: list, error: str) -> None:
        self._refresh_btn.stop_spin()
        self._refresh_btn.setToolTip(self._tr.tr("refresh_tooltip"))

        if error:
            msg = self._tr.tr("toast_refresh_fail") + "：" + error
            if self.on_toast:
                self.on_toast(msg, False)
            return

        prev = getattr(self, "_prev_ports", set())
        prev_sel = getattr(self, "_prev_selection", "")
        new_ports = set(ports) - prev

        self._apply_ports(ports, prev_sel, highlight=new_ports)

        t = self._tr.tr
        if new_ports or set(ports) != prev:
            msg = t("toast_refresh_ok_found").format(n=len(ports)) if ports else t("toast_refresh_ok")
        else:
            msg = t("toast_refresh_ok")
        if self.on_toast:
            self.on_toast(msg, True)

    def _apply_ports(self, ports: list, restore_sel: str = "",
                     highlight: set = None) -> None:
        self._port_combo.clear()
        if ports:
            self._port_combo.addItems(ports)
            if restore_sel and restore_sel in ports:
                self._port_combo.setCurrentText(restore_sel)
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setText(self._tr.tr("open_port"))

            if highlight:
                from PySide6.QtGui import QStandardItem
                from PySide6.QtCore import QTimer as _QTimer
                model = self._port_combo.model()
                highlighted_rows = []
                for i in range(model.rowCount()):
                    item = model.item(i)
                    if item and item.text() in highlight:
                        item.setBackground(QColor("#E8FFEA"))
                        highlighted_rows.append(i)

                def _clear_highlight():
                    for r in highlighted_rows:
                        it = model.item(r)
                        if it:
                            it.setBackground(QColor("transparent"))
                _QTimer.singleShot(1500, _clear_highlight)
        else:
            self._port_combo.addItem(self._tr.tr("no_port"))
            self._toggle_btn.setEnabled(False)
            self._toggle_btn.setText(self._tr.tr("no_port_available"))

    # ------------------------------------------------------------------
    # Serial control
    # ------------------------------------------------------------------

    def _toggle_serial(self) -> None:
        t = self._tr.tr
        if self._worker.is_open():
            self._loop_timer.stop()
            self._loop_chk.setChecked(False)
            self._lock_input(False)
            if self.on_before_disconnect:
                self.on_before_disconnect()
            self._worker.close()
            self._update_controls(opened=False)
        else:
            port = self._port_combo.currentText()
            try:
                baudrate = int(self._baud_combo.currentText())
            except ValueError:
                baudrate = 115200
            bytesize_map = {"5": serial.FIVEBITS, "6": serial.SIXBITS,
                            "7": serial.SEVENBITS, "8": serial.EIGHTBITS}
            parity_map = {"None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN,
                          "Odd": serial.PARITY_ODD, "Mark": serial.PARITY_MARK,
                          "Space": serial.PARITY_SPACE}
            stopbits_map = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE,
                            "2": serial.STOPBITS_TWO}
            try:
                self._worker.open(
                    port, baudrate,
                    bytesize=bytesize_map.get(self._bytesize_combo.currentText(), serial.EIGHTBITS),
                    parity=parity_map.get(self._parity_combo.currentText(), serial.PARITY_NONE),
                    stopbits=stopbits_map.get(self._stopbits_combo.currentText(), serial.STOPBITS_ONE),
                    xonxoff=self._flow_combo.currentText() == "XON/XOFF",
                    rtscts=self._flow_combo.currentText() == "RTS/CTS",
                    dsrdtr=self._flow_combo.currentText() == "DSR/DTR",
                )
                self._update_signals()
                self._update_controls(opened=True)
            except Exception as e:
                self._append_to(self._recv_box, t("error_open_port") + str(e), "#C62828")

    def handle_disconnect(self) -> None:
        self._loop_chk.setChecked(False)
        self._loop_timer.stop()
        self._update_controls(False)

    def _update_signals(self) -> None:
        try:
            self._worker.set_signals(self._dtr_chk.isChecked(), self._rts_chk.isChecked(), self._brk_chk.isChecked())
        except Exception as exc:
            if self.on_toast:
                self.on_toast(str(exc), False)

    def _update_controls(self, opened: bool) -> None:
        t = self._tr.tr
        if opened:
            self._toggle_btn.setText(t("close_port"))
            self._toggle_btn.setStyleSheet(BTN_CLOSE_STYLE)
        else:
            self._toggle_btn.setText(t("open_port"))
            self._toggle_btn.setStyleSheet(BTN_OPEN_STYLE)
        for w in (self._port_combo, self._baud_combo, self._flow_combo,
                  self._parity_combo, self._bytesize_combo, self._stopbits_combo,
                  self._refresh_btn):
            w.setEnabled(not opened)
        self._send_btn.setEnabled(opened)
        self._loop_chk.setEnabled(opened)
        if self.on_connection_changed:
            self.on_connection_changed(opened)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def _manual_send(self) -> None:
        if self._loop_chk.isChecked():
            self._loop_chk.setChecked(False)
        self._do_send()

    def _do_send(self) -> None:
        if not self._worker.is_open():
            return
        text = self._send_input.text()
        if not text:
            return
        t = self._tr.tr
        suffix = {"CRLF": b"\r\n", "LF": b"\n", "CR": b"\r", "None": b""}[self._suffix_combo.currentText()]
        if self._is_hex_mode:
            try:
                data = bytes.fromhex(text.replace(" ", "")) + suffix
            except ValueError as e:
                self._append_to(self._recv_box, t("hex_error") + str(e), "#C62828")
                return
            display = " ".join(f"{b:02X}" for b in data)
        else:
            data = text.encode("utf-8") + suffix
            display = text

        try:
            self._worker.write(data)
        except Exception as exc:
            self._loop_chk.setChecked(False)
            if self.on_toast:
                self.on_toast(str(exc), False)
            return
        self._append_to(self._send_box, display, "#1565C0")
        if self.on_data_sent:
            self.on_data_sent()

    def _toggle_loop(self, checked: bool) -> None:
        if checked and self._worker.is_open():
            self._loop_timer.start(self._interval_spin.value())
            self._lock_input(True)
        else:
            self._loop_timer.stop()
            self._lock_input(False)

    def _lock_input(self, locked: bool) -> None:
        c = colors(self._theme)
        self._send_input.setReadOnly(locked)
        self._send_input.setStyleSheet(
            f"background:{c['surface_alt']}; border:1px solid {c['border']}; border-radius:4px;"
            if locked else
            f"background:{c['input']}; color:{c['text']}; border:1px solid {c['border_strong']}; border-radius:4px;"
        )
        cursor = Qt.CursorShape.ForbiddenCursor if locked else Qt.CursorShape.IBeamCursor
        self._send_input.setCursor(cursor)

    def _toggle_mode(self) -> None:
        self._is_hex_mode = not self._is_hex_mode
        self._suffix_combo.setCurrentText("None" if self._is_hex_mode else "CRLF")
        self._update_mode_btn()

    def _toggle_recv_mode(self) -> None:
        self._is_recv_hex = not self._is_recv_hex
        self._update_recv_mode_btn()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append_to(self, box: QPlainTextEdit, text: str, color: str) -> None:
        if self._theme == "dark":
            color = {
                "#2E7D32": "#65D38E", "#7B5EA7": "#C3A6FF",
                "#C62828": "#FF7B7B", "#1565C0": "#70A4FF",
            }.get(color, color)
        cursor = box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(text + "\n", fmt)
        box.setTextCursor(cursor)
        box.ensureCursorVisible()

    def _clear_send_box(self) -> None:
        self._send_box.clear()

    def _clear_recv_box(self) -> None:
        self._recv_box.clear()

    def _update_mode_btn(self) -> None:
        t = self._tr.tr
        if self._is_hex_mode:
            self._mode_btn.setText(t("mode_btn_hex"))
            self._mode_btn.setStyleSheet(MODE_HEX_STYLE)
            self._send_input.setPlaceholderText(t("send_input_ph_hex"))
        else:
            self._mode_btn.setText(t("mode_btn_str"))
            self._mode_btn.setStyleSheet(MODE_STR_STYLE)
            self._send_input.setPlaceholderText(t("send_input_ph_str"))

    def _update_recv_mode_btn(self) -> None:
        t = self._tr.tr
        if self._is_recv_hex:
            self._recv_mode_btn.setText(t("recv_mode_btn_hex"))
            self._recv_mode_btn.setStyleSheet(MODE_HEX_STYLE)
        else:
            self._recv_mode_btn.setText(t("recv_mode_btn_str"))
            self._recv_mode_btn.setStyleSheet(MODE_STR_STYLE)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self._left_panel.setStyleSheet(
            f"background:{c['surface_alt']}; border-right:1px solid {c['border']};")
        self._send_label.setStyleSheet(f"font-weight:bold; color:{c['text_secondary']};")
        self._recv_label.setStyleSheet(f"font-weight:bold; color:{c['text_secondary']};")
        self._send_box.setStyleSheet(
            f"background:{c['send_box']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:6px;")
        self._recv_box.setStyleSheet(
            f"background:{c['recv_box']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:6px;")
        self._refresh_btn.apply_theme(theme)
        self._lock_input(self._loop_chk.isChecked())
        self._update_mode_btn()
        self._update_recv_mode_btn()

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def retranslate(self) -> None:
        t = self._tr.tr
        self._config_group.setTitle(t("serial_config_group"))
        self._port_label.setText(t("port_label"))
        self._baud_label.setText(t("baud_label"))
        self._flow_label.setText(t("flow_ctrl_label"))
        self._parity_label.setText(t("parity_label"))
        self._bytesize_label.setText(t("bytesize_label"))
        self._stopbits_label.setText(t("stopbits_label"))
        self._signals_label.setText(t("signals_label"))
        self._refresh_btn.setToolTip(t("refresh_tooltip"))
        self._send_label.setText(t("send_label"))
        self._send_btn.setText(t("send_btn"))
        self._update_mode_btn()
        self._loop_chk.setText(t("loop_send_chk"))
        self._interval_label.setText(t("loop_interval_lbl"))
        self._recv_label.setText(t("recv_label"))
        self._clear_recv_btn.setText(t("clear_recv_btn"))
        self._update_recv_mode_btn()
        self._clear_send_btn.setText(t("clear_send_btn"))
        self._send_box.setPlaceholderText(t("send_placeholder"))
        self._recv_box.setPlaceholderText(t("placeholder"))
        if self._worker.is_open():
            self._toggle_btn.setText(t("close_port"))
        else:
            self._toggle_btn.setText(t("open_port"))
