import threading
import time
import serial
from PySide6.QtCore import QObject, Signal


class SerialWorker(QObject):
    # chunk_received: 原始字节块，接收区始终显示
    chunk_received = Signal(bytes)
    # lines_received: 按换行符分割出的完整文本行，用于 PID 解析
    lines_received = Signal(list)

    def __init__(self):
        super().__init__()
        self._port: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.rx_bytes: int = 0
        self.tx_bytes: int = 0

    def open(self, port: str, baudrate: int,
             bytesize=8, parity="N", stopbits=1) -> None:
        self._port = serial.Serial(
            port, baudrate, timeout=0.05,
            bytesize=bytesize, parity=parity, stopbits=stopbits,
        )
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None

    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    def write(self, data: bytes) -> None:
        if self._port and self._port.is_open:
            self._port.write(data)
            self._port.flush()
            self.tx_bytes += len(data)

    def _read_loop(self) -> None:
        line_buf = b""   # 用于拼接文本行，提取 PID 格式
        while not self._stop_event.is_set():
            try:
                waiting = self._port.in_waiting if self._port else 0
                if waiting:
                    chunk = self._port.read(waiting)
                    self.rx_bytes += len(chunk)

                    # 1. 原始数据直接发射给接收区显示
                    self.chunk_received.emit(chunk)

                    # 2. 尝试按换行符提取文本行，供 PID 解析
                    line_buf += chunk
                    # 防止 buf 无限增长（非文本协议时不会有换行符）
                    if len(line_buf) > 4096:
                        line_buf = line_buf[-4096:]
                    parts = line_buf.split(b"\n")
                    line_buf = parts[-1]
                    lines = []
                    for raw in parts[:-1]:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line:
                            lines.append(line)
                    if lines:
                        self.lines_received.emit(lines)
                else:
                    time.sleep(0.005)
            except serial.SerialException:
                break
