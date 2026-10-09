import threading
import time
import serial
from PySide6.QtCore import QObject, Signal


class LineFramer:
    """Bound unfinished lines without dropping complete frames in a burst."""
    def __init__(self, limit=4096):
        self.buffer = b""
        self.limit = limit
        self.discarding = False

    def feed(self, chunk):
        parts = (self.buffer + chunk).split(b"\n")
        self.buffer = parts.pop()
        lines = []
        for raw in parts:
            if self.discarding:
                self.discarding = False
                continue
            if len(raw) <= self.limit:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    lines.append(line)
        if len(self.buffer) > self.limit:
            self.buffer = b""
            self.discarding = True
        return lines


class SerialWorker(QObject):
    # chunk_received: 原始字节块，接收区始终显示
    chunk_received = Signal(bytes)
    # lines_received: 按换行符分割出的完整文本行，用于 PID 解析
    lines_received = Signal(list)
    connection_lost = Signal(str)

    def __init__(self):
        super().__init__()
        self._port: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.rx_bytes: int = 0
        self.tx_bytes: int = 0
        self.owner = None
        self._write_lock = threading.Lock()

    def open(self, port: str, baudrate: int,
             bytesize=8, parity="N", stopbits=1, **options) -> None:
        self.close()
        if port == "sim://":
            from tuning.device import SimulatedPort
            self._port = SimulatedPort()
        else:
            self._port = serial.serial_for_url(
            port, baudrate=baudrate, timeout=0.05, write_timeout=0.25,
            bytesize=bytesize, parity=parity, stopbits=stopbits, **options,
        )
        self.rx_bytes = self.tx_bytes = 0
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None
        self.owner = None

    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open and not self._stop_event.is_set()

    def acquire(self, owner):
        if self.owner not in (None, owner):
            raise RuntimeError("设备正由其他调参流程控制")
        self.owner = owner

    def release(self, owner):
        if self.owner == owner:
            self.owner = None

    def write(self, data: bytes, owner=None) -> None:
        if self.owner is not None and self.owner != owner:
            raise RuntimeError("AI 试验期间禁止其他页面发送指令")
        if not self.is_open():
            raise serial.SerialException("串口未连接")
        with self._write_lock:
            written = self._port.write(data)
            self.tx_bytes += written
            if written != len(data):
                raise serial.SerialTimeoutException("串口数据未完整发送")

    def set_signals(self, dtr, rts, brk):
        if self.owner:
            raise RuntimeError("AI 试验期间禁止更改串口信号")
        if self.is_open():
            self._port.dtr = dtr
            self._port.rts = rts
            self._port.break_condition = brk

    def _read_loop(self) -> None:
        framer = LineFramer()
        while not self._stop_event.is_set():
            try:
                waiting = self._port.in_waiting if self._port else 0
                if waiting:
                    chunk = self._port.read(min(waiting, 65536))
                    self.rx_bytes += len(chunk)

                    # 1. 原始数据直接发射给接收区显示
                    self.chunk_received.emit(chunk)

                    # 2. 尝试按换行符提取文本行，供 PID 解析
                    lines = framer.feed(chunk)
                    if lines:
                        self.lines_received.emit(lines)
                else:
                    time.sleep(0.005)
            except (serial.SerialException, OSError) as exc:
                self._stop_event.set()
                self.connection_lost.emit(str(exc))
                break
