import serial
import serial.tools.list_ports
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QComboBox, QPushButton, QGroupBox,
    QLineEdit, QCheckBox, QSpinBox, QPlainTextEdit,
    QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat

from i18n import Translator
from serial_worker import SerialWorker

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

# 字符串模式：默认绿色（继承全局）
MODE_STR_STYLE = ""

# 十六进制模式：橙黄色提醒
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

_MONO_FONT = QFont("Consolas", 11)  # ~14-15px

# 统一文本框边框样式
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


class SerialPage(QWidget):
    """
    串口收发页面。

    布局：
      ┌──────────────┬──────────────────────────────┐
      │  左：串口参数  │  右上：发送区（可拖拽）         │
      │  配置面板     ├──────────────────────────────┤
      │              │  右下：接收区（可拖拽）         │
      └──────────────┴──────────────────────────────┘
    左右、右侧上下均可通过鼠标拖拽调整大小。
    """

    def __init__(self, worker: SerialWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._tr = Translator()
        self._loop_timer = QTimer(self)
        self._loop_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._loop_timer.timeout.connect(self._do_send)
        self._tr.on_change(self.retranslate)
        self.on_connection_changed = None  # optional callback(bool)
        self.on_data_sent = None           # optional callback()
        self._build_ui()
        self.retranslate()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(self._build_left_panel())
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
        panel.setStyleSheet(
            "background: #FAFBFC;"
            "border-right: 1px solid #E5E8EB;"
        )

        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 12, 10, 12)
        v.setSpacing(0)

        self._config_group = QGroupBox()
        group_layout = QVBoxLayout(self._config_group)
        group_layout.setContentsMargins(8, 14, 8, 8)
        group_layout.setSpacing(0)

        # 标签列和控件列用内嵌 splitter 分隔，可拖动调整列宽
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

        # helpers — 标签放 lbl_grid，控件放 ctrl_grid
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

        # port row (with refresh button)
        self._port_label = QLabel()
        self._port_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._port_combo = QComboBox()
        self._refresh_btn = QPushButton()
        self._refresh_btn.setFixedWidth(44)
        self._refresh_btn.clicked.connect(self.refresh_ports)
        lbl_grid.addWidget(self._port_label, 0, 0)
        port_row = QHBoxLayout()
        port_row.setSpacing(4)
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.addWidget(self._port_combo, stretch=1)
        port_row.addWidget(self._refresh_btn)
        port_container = QWidget()
        port_container.setLayout(port_row)
        ctrl_grid.addWidget(port_container, 0, 0)

        row("_baud_label",      "_baud_combo",
            ["1200","2400","4800","9600","19200","38400","57600","115200","230400","460800","921600"],
            "115200", r=1)
        row("_flow_label",      "_flow_combo",
            ["None", "XON/XOFF", "RTS/CTS", "DSR/DTR"], r=2)
        row("_parity_label",    "_parity_combo",
            ["None", "Even", "Odd", "Mark", "Space"], r=3)
        row("_bytesize_label",  "_bytesize_combo",
            ["5", "6", "7", "8"], "8", r=4)
        row("_stopbits_label",  "_stopbits_combo",
            ["1", "1.5", "2"], "1", r=5)

        # control signals — 跨两列，放在 group_layout 下方
        self._signals_label = QLabel()
        group_layout.addSpacing(4)
        group_layout.addWidget(self._signals_label)

        sig_row = QHBoxLayout()
        self._dtr_chk = QCheckBox("DTR")
        self._rts_chk = QCheckBox("RTS")
        self._brk_chk = QCheckBox("Break")
        for chk in (self._dtr_chk, self._rts_chk, self._brk_chk):
            sig_row.addWidget(chk)
        sig_row.addStretch()
        sig_widget = QWidget()
        sig_widget.setLayout(sig_row)
        group_layout.addWidget(sig_widget)

        v.addWidget(self._config_group)

        # connect button
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

        # header row
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

        # send log (read-only, shows [TX] lines)
        self._send_box = QPlainTextEdit()
        self._send_box.setReadOnly(True)
        self._send_box.setFont(_MONO_FONT)
        self._send_box.setStyleSheet(_BOX_STYLE_SEND)
        v.addWidget(self._send_box, stretch=1)

        # input row
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

        # options row
        self._is_hex_mode = False  # False = string, True = hex

        self._mode_btn = QPushButton()
        self._mode_btn.setFixedWidth(100)
        self._mode_btn.clicked.connect(self._toggle_mode)

        self._loop_chk = QCheckBox()
        self._loop_chk.toggled.connect(self._toggle_loop)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(50, 60000)
        self._interval_spin.setValue(1000)
        self._interval_spin.setMinimumWidth(90)  # 防止数字与箭头重叠

        self._interval_label = QLabel()

        opt_row = QHBoxLayout()
        opt_row.setSpacing(8)
        opt_row.addWidget(self._mode_btn)
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
        self._clear_recv_btn = QPushButton()
        self._clear_recv_btn.setFixedWidth(72)
        self._clear_recv_btn.clicked.connect(self._clear_recv_box)
        hdr.addWidget(self._recv_label)
        hdr.addStretch()
        hdr.addWidget(self._clear_recv_btn)
        v.addLayout(hdr)

        self._recv_box = QPlainTextEdit()
        self._recv_box.setReadOnly(True)
        self._recv_box.setFont(_MONO_FONT)
        self._recv_box.setStyleSheet(_BOX_STYLE_RECV)
        v.addWidget(self._recv_box, stretch=1)
        return panel

    # ------------------------------------------------------------------
    # Public API for main window to push received data
    # ------------------------------------------------------------------

    def append_received(self, line: str) -> None:
        self._append_to(self._recv_box, line, "#2E7D32")

    def current_port(self) -> str:
        return self._port_combo.currentText()

    def current_baud(self) -> int:
        try:
            return int(self._baud_combo.currentText())
        except ValueError:
            return 115200

    # ------------------------------------------------------------------
    # Serial control
    # ------------------------------------------------------------------

    def refresh_ports(self) -> None:
        self._port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self._port_combo.addItems(ports)
            self._toggle_btn.setEnabled(True)
        else:
            self._port_combo.addItem(self._tr.tr("no_port"))
            self._toggle_btn.setEnabled(False)
            self._toggle_btn.setText(self._tr.tr("no_port_available"))

    def _toggle_serial(self) -> None:
        t = self._tr.tr
        if self._worker.is_open():
            self._loop_timer.stop()
            self._loop_chk.setChecked(False)
            self._lock_input(False)
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
                )
                self._update_controls(opened=True)
            except Exception as e:
                self._append_to(self._recv_box, t("error_open_port") + str(e), "#C62828")

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
        """手动发送：停止循环、解锁输入框、发送一次。"""
        if self._loop_chk.isChecked():
            self._loop_chk.setChecked(False)  # 触发 _toggle_loop → 停止定时器并解锁
        self._do_send()

    def _do_send(self) -> None:
        if not self._worker.is_open():
            return
        text = self._send_input.text()
        if not text:
            return
        t = self._tr.tr
        if self._is_hex_mode:
            try:
                data = bytes.fromhex(text.replace(" ", "")) + b"\r\n"
            except ValueError as e:
                self._append_to(self._recv_box, t("hex_error") + str(e), "#C62828")
                return
            display = " ".join(f"{b:02X}" for b in data)
        else:
            data = (text + "\r\n").encode("utf-8")
            display = text

        self._worker.write(data)
        self._append_to(self._send_box, display, "#1565C0")
        if self.on_data_sent:
            self.on_data_sent()
        # do NOT clear input — user keeps it for repeated sends

    def _toggle_loop(self, checked: bool) -> None:
        if checked and self._worker.is_open():
            self._loop_timer.start(self._interval_spin.value())
            self._lock_input(True)
        else:
            self._loop_timer.stop()
            self._lock_input(False)

    def _lock_input(self, locked: bool) -> None:
        self._send_input.setReadOnly(locked)
        self._send_input.setStyleSheet(
            "background: #F2F3F5; border: 1px solid #E5E8EB; border-radius: 4px;"
            if locked else
            "background: white; border: 1px solid #D0D5DD; border-radius: 4px;"
        )
        cursor = Qt.CursorShape.ForbiddenCursor if locked else Qt.CursorShape.IBeamCursor
        self._send_input.setCursor(cursor)

    def _toggle_mode(self) -> None:
        self._is_hex_mode = not self._is_hex_mode
        self._update_mode_btn()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _append_to(box: QPlainTextEdit, text: str, color: str) -> None:
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
        self._refresh_btn.setText(t("refresh_btn"))
        self._send_label.setText(t("send_label"))
        self._send_btn.setText(t("send_btn"))
        self._update_mode_btn()  # 更新模式按钮文字和占位符
        self._loop_chk.setText(t("loop_send_chk"))
        self._interval_label.setText(t("loop_interval_lbl"))
        self._recv_label.setText(t("recv_label"))
        self._clear_recv_btn.setText(t("clear_recv_btn"))
        self._clear_send_btn.setText(t("clear_send_btn"))
        self._send_box.setPlaceholderText(t("send_placeholder"))
        self._recv_box.setPlaceholderText(t("placeholder"))
        if self._worker.is_open():
            self._toggle_btn.setText(t("close_port"))
        else:
            self._toggle_btn.setText(t("open_port"))
