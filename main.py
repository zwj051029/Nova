import sys
import threading
import collections
import platform
import serial
import serial.tools.list_ports
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QComboBox,
    QLabel, QPushButton, QPlainTextEdit,
    QSplitter, QGroupBox, QSlider, QDoubleSpinBox,
    QGridLayout,
)
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QPalette, QColor, QFont

BUFFER_SIZE = 500

# ------------------------------------------------------------------
# Styles
# ------------------------------------------------------------------

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
    border: 1px solid #D0D8E4;
    border-radius: 6px;
    margin-top: 8px;
    background-color: rgba(255,255,255,200);
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

QDoubleSpinBox {
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
    width: 12px;
    height: 12px;
    margin: -4px 0;
    background: #6DB89A;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: #A8E6CF;
    border-radius: 2px;
}
""" % {"font": _system_font()}

BTN_CONNECTED_STYLE = """
QPushButton {
    background-color: #6DB89A;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #5AA882; }
QPushButton:pressed { background-color: #4A9870; }
"""

BTN_DISCONNECTED_STYLE = ""  # 回退到全局样式


# ------------------------------------------------------------------
# Protocol
# ------------------------------------------------------------------

def parse_line(line: str) -> tuple[int, float, float, float] | None:
    if not line.startswith(">"):
        return None
    try:
        parts = line[1:].split(",")
        if len(parts) != 4:
            return None
        return int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    except ValueError:
        return None


# ------------------------------------------------------------------
# Serial reader
# ------------------------------------------------------------------

class SerialReader(QObject):
    line_received = Signal(str)

    def __init__(self):
        super().__init__()
        self._port: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def open(self, port: str, baudrate: int) -> None:
        self._port = serial.Serial(port, baudrate, timeout=1)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None

    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    def write(self, data: bytes) -> None:
        if self._port and self._port.is_open:
            self._port.write(data)

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._port and self._port.in_waiting:
                    raw = self._port.readline()
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        self.line_received.emit(line)
            except serial.SerialException:
                break


# ------------------------------------------------------------------
# PID row widget
# ------------------------------------------------------------------

class PidRow:
    def __init__(self, name: str, layout: QGridLayout, row: int):
        self.name = name
        self._syncing = False

        layout.addWidget(QLabel(name), row, 0)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        layout.addWidget(self.slider, row, 1)

        self.spinbox = QDoubleSpinBox()
        self.spinbox.setRange(0.0, 10.0)
        self.spinbox.setSingleStep(0.01)
        self.spinbox.setDecimals(2)
        self.spinbox.setValue(0.0)
        self.spinbox.setFixedWidth(80)
        layout.addWidget(self.spinbox, row, 2)

        self.send_btn = QPushButton("发送")
        self.send_btn.setFixedWidth(48)
        layout.addWidget(self.send_btn, row, 3)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spinbox.valueChanged.connect(self._spinbox_changed)

    def value(self) -> float:
        return self.spinbox.value()

    def _slider_changed(self, v: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.spinbox.setValue(v / 100.0)
        self._syncing = False

    def _spinbox_changed(self, v: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.slider.setValue(round(v * 100))
        self._syncing = False


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nova")
        self.resize(1200, 800)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#F5F7FA"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self._buf_setpoint: collections.deque[float] = collections.deque(maxlen=BUFFER_SIZE)
        self._buf_actual: collections.deque[float] = collections.deque(maxlen=BUFFER_SIZE)

        self._reader = SerialReader()
        self._reader.line_received.connect(self._on_line_received)

        self._build_ui()
        self._refresh_ports()

        print(f"窗口实际尺寸: {self.size().width()} x {self.size().height()}")
        print("窗口创建成功")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_left_panel())
        layout.addWidget(self._build_right_panel(), stretch=1)

        self._update_controls(opened=False)

    def _build_left_panel(self) -> QWidget:
        left = QWidget()
        left.setFixedWidth(380)
        left.setStyleSheet("""
            QWidget#leftPanel {
                background: white;
                border-right: 1px solid #D0D8E4;
            }
        """)
        left.setObjectName("leftPanel")

        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 标题
        title = QLabel("Serial PID Tuner")
        title_font = QFont(_system_font(), 16)
        title_font.setWeight(QFont.Weight.Light)
        title.setFont(title_font)
        title.setStyleSheet("color: #B0B8C4; margin-bottom: 4px;")
        left_layout.addWidget(title)

        # 串口设置
        left_layout.addWidget(QLabel("串口号"))
        self._port_combo = QComboBox()
        left_layout.addWidget(self._port_combo)

        left_layout.addWidget(QLabel("波特率"))
        self._baud_combo = QComboBox()
        self._baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400"])
        self._baud_combo.setCurrentText("115200")
        left_layout.addWidget(self._baud_combo)

        self._refresh_btn = QPushButton("刷新串口列表")
        self._refresh_btn.clicked.connect(self._refresh_ports)
        left_layout.addWidget(self._refresh_btn)

        self._toggle_btn = QPushButton("已断开")
        self._toggle_btn.clicked.connect(self._toggle_serial)
        left_layout.addWidget(self._toggle_btn)

        left_layout.addWidget(self._build_pid_group())
        left_layout.addStretch()
        return left

    def _build_pid_group(self) -> QGroupBox:
        group = QGroupBox("PID 参数")
        grid = QGridLayout(group)
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)

        self._pid_kp = PidRow("Kp", grid, 0)
        self._pid_ki = PidRow("Ki", grid, 1)
        self._pid_kd = PidRow("Kd", grid, 2)

        self._pid_kp.send_btn.clicked.connect(lambda: self._send_single(self._pid_kp))
        self._pid_ki.send_btn.clicked.connect(lambda: self._send_single(self._pid_ki))
        self._pid_kd.send_btn.clicked.connect(lambda: self._send_single(self._pid_kd))

        self._send_all_btn = QPushButton("发送全部")
        self._send_all_btn.clicked.connect(self._send_all_pid)
        grid.addWidget(self._send_all_btn, 3, 0, 1, 4)

        return group

    def _build_right_panel(self) -> QSplitter:
        self._plot_widget = self._build_plot()

        right_bottom = QWidget()
        bottom_layout = QVBoxLayout(right_bottom)
        bottom_layout.setContentsMargins(0, 4, 0, 0)
        bottom_layout.setSpacing(4)

        clear_btn = QPushButton("清空接收区")
        clear_btn.setFixedWidth(100)
        clear_btn.clicked.connect(lambda: self._text_box.clear())
        bottom_layout.addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self._text_box = QPlainTextEdit()
        self._text_box.setReadOnly(True)
        self._text_box.setPlaceholderText("等待串口数据…")
        self._text_box.setFont(QFont("Consolas, Courier New, monospace", 9))
        self._text_box.setStyleSheet("background: #FAFAFA; border: 1px solid #D0D8E4; border-radius: 4px;")
        bottom_layout.addWidget(self._text_box)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._plot_widget)
        splitter.addWidget(right_bottom)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        return splitter

    def _build_plot(self) -> pg.PlotWidget:
        pw = pg.PlotWidget()
        pw.setBackground("w")
        pw.showGrid(x=True, y=True, alpha=0.2)

        axis_font = QFont(_system_font(), 10)
        pw.getAxis("left").setStyle(tickFont=axis_font)
        pw.getAxis("bottom").setStyle(tickFont=axis_font)
        pw.setLabel("left", "数值", **{"font-size": "10pt"})
        pw.setLabel("bottom", "采样点", **{"font-size": "10pt"})
        pw.enableAutoRange()

        pw.addLegend(offset=(10, 10))

        self._curve_setpoint = pw.plot(
            [], name="目标值",
            pen=pg.mkPen(color="#2ECC71", width=2, style=Qt.PenStyle.DashLine),
            antialias=True,
        )
        self._curve_actual = pw.plot(
            [], name="实际值",
            pen=pg.mkPen(color="#E74C3C", width=2),
            antialias=True,
        )
        return pw

    # ------------------------------------------------------------------
    # Serial
    # ------------------------------------------------------------------

    def _refresh_ports(self) -> None:
        self._port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if ports:
            self._port_combo.addItems(ports)
            self._toggle_btn.setEnabled(True)
        else:
            self._port_combo.addItem("无可用串口")
            self._toggle_btn.setEnabled(False)

    def _toggle_serial(self) -> None:
        if self._reader.is_open():
            self._reader.close()
            self._update_controls(opened=False)
            self._clear_plot()
            print("串口已关闭")
        else:
            port = self._port_combo.currentText()
            baudrate = int(self._baud_combo.currentText())
            try:
                self._clear_plot()
                self._reader.open(port, baudrate)
                self._update_controls(opened=True)
                print(f"串口已打开: {port} @ {baudrate}")
            except serial.SerialException as e:
                self._text_box.appendPlainText(f"[错误] 无法打开串口: {e}")

    def _update_controls(self, opened: bool) -> None:
        if opened:
            self._toggle_btn.setText("已连接")
            self._toggle_btn.setStyleSheet(BTN_CONNECTED_STYLE)
        else:
            self._toggle_btn.setText("已断开")
            self._toggle_btn.setStyleSheet(BTN_DISCONNECTED_STYLE)

        self._port_combo.setEnabled(not opened)
        self._baud_combo.setEnabled(not opened)
        self._refresh_btn.setEnabled(not opened)
        self._send_all_btn.setEnabled(opened)
        self._pid_kp.send_btn.setEnabled(opened)
        self._pid_ki.send_btn.setEnabled(opened)
        self._pid_kd.send_btn.setEnabled(opened)

    def _clear_plot(self) -> None:
        self._buf_setpoint.clear()
        self._buf_actual.clear()
        self._curve_setpoint.setData([])
        self._curve_actual.setData([])

    # ------------------------------------------------------------------
    # PID send
    # ------------------------------------------------------------------

    def _send_single(self, row: PidRow) -> None:
        msg = f"PID:{row.name}={row.value():.2f}\r\n"
        self._reader.write(msg.encode("utf-8"))
        print(f"已发送: {msg.strip()}")

    def _send_all_pid(self) -> None:
        kp = self._pid_kp.value()
        ki = self._pid_ki.value()
        kd = self._pid_kd.value()
        msg = f"PID:{kp:.2f},{ki:.2f},{kd:.2f}\r\n"
        self._reader.write(msg.encode("utf-8"))
        print(f"已发送: {msg.strip()}")

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _on_line_received(self, line: str) -> None:
        self._text_box.appendPlainText(line)

        parsed = parse_line(line)
        if parsed is None:
            return

        _, setpoint, actual, _ = parsed
        self._buf_setpoint.append(setpoint)
        self._buf_actual.append(actual)
        self._curve_setpoint.setData(list(self._buf_setpoint))
        self._curve_actual.setData(list(self._buf_actual))

    def closeEvent(self, event) -> None:
        self._reader.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLE)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
