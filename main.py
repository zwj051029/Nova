import sys
import random
import threading
import collections
import serial
import serial.tools.list_ports
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QComboBox,
    QLabel, QPushButton, QPlainTextEdit,
    QSplitter,
)
from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtGui import QPalette, QColor

BUFFER_SIZE = 500
PLOT_INTERVAL_MS = 20   # 波形刷新间隔
DEBUG_INTERVAL_MS = 1000  # 调试打印间隔


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nova")
        self.resize(1200, 800)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#F0F4F8"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self._buffer: collections.deque[float] = collections.deque(
            [0.0] * BUFFER_SIZE, maxlen=BUFFER_SIZE
        )

        self._reader = SerialReader()
        self._reader.line_received.connect(self._append_line)

        self._build_ui()
        self._refresh_ports()
        self._start_timers()

        print(f"窗口实际尺寸: {self.size().width()} x {self.size().height()}")
        print("窗口创建成功")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- left panel ---
        left = QWidget()
        left.setFixedWidth(300)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

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

        self._toggle_btn = QPushButton("打开串口")
        self._toggle_btn.clicked.connect(self._toggle_serial)
        left_layout.addWidget(self._toggle_btn)

        left_layout.addStretch()

        # --- right panel: plot + text in a splitter ---
        self._plot_widget = self._build_plot()

        self._text_box = QPlainTextEdit()
        self._text_box.setReadOnly(True)
        self._text_box.setPlaceholderText("等待串口数据…")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._plot_widget)
        splitter.addWidget(self._text_box)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(left)
        layout.addWidget(splitter, stretch=1)

        self._update_controls(opened=False)

    def _build_plot(self) -> pg.PlotWidget:
        pw = pg.PlotWidget()
        pw.setBackground("w")

        pw.showGrid(x=True, y=True, alpha=0.3)
        pw.setLabel("left", "数值")
        pw.setLabel("bottom", "采样点")
        pw.setYRange(0, 100)

        self._curve = pw.plot(
            list(self._buffer),
            pen=pg.mkPen(color="#1E90FF", width=2),
        )
        return pw

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def _start_timers(self) -> None:
        self._plot_timer = QTimer(self)
        self._plot_timer.timeout.connect(self._update_plot)
        self._plot_timer.start(PLOT_INTERVAL_MS)

        self._debug_timer = QTimer(self)
        self._debug_timer.timeout.connect(self._debug_print)
        self._debug_timer.start(DEBUG_INTERVAL_MS)

    def _update_plot(self) -> None:
        self._buffer.append(random.uniform(0, 100))
        self._curve.setData(list(self._buffer))

    def _debug_print(self) -> None:
        latest = self._buffer[-1]
        print(f"[调试] 缓冲区样本数: {len(self._buffer)}  最新值: {latest:.2f}")

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
            print("串口已关闭")
        else:
            port = self._port_combo.currentText()
            baudrate = int(self._baud_combo.currentText())
            try:
                self._reader.open(port, baudrate)
                self._update_controls(opened=True)
                print(f"串口已打开: {port} @ {baudrate}")
            except serial.SerialException as e:
                self._text_box.appendPlainText(f"[错误] 无法打开串口: {e}")

    def _update_controls(self, opened: bool) -> None:
        self._toggle_btn.setText("关闭串口" if opened else "打开串口")
        self._port_combo.setEnabled(not opened)
        self._baud_combo.setEnabled(not opened)
        self._refresh_btn.setEnabled(not opened)

    def _append_line(self, line: str) -> None:
        self._text_box.appendPlainText(line)

    def closeEvent(self, event) -> None:
        self._plot_timer.stop()
        self._debug_timer.stop()
        self._reader.close()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
