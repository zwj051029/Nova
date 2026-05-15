import threading
import time
import serial
from PySide6.QtCore import QObject, Signal


class SerialWorker(QObject):
    line_received = Signal(str)
    lines_received = Signal(list)   # batch signal: list[str]

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
            port, baudrate, timeout=0.05,   # 50ms timeout，让 read 快速返回
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
        buf = b""
        while not self._stop_event.is_set():
            try:
                waiting = self._port.in_waiting if self._port else 0
                if waiting:
                    chunk = self._port.read(waiting)
                    self.rx_bytes += len(chunk)
                    buf += chunk

                    # 按换行符切割，保留不完整的最后一段
                    parts = buf.split(b"\n")
                    buf = parts[-1]          # 最后一段可能不完整，留到下次
                    lines = []
                    for raw in parts[:-1]:
                        line = raw.decode("utf-8", errors="replace").strip()
                        if line:
                            lines.append(line)

                    if lines:
                        # 批量发射，减少跨线程信号次数
                        self.lines_received.emit(lines)
                        # 同时逐条发射 line_received 保持兼容
                        for line in lines:
                            self.line_received.emit(line)
                else:
                    time.sleep(0.005)
            except serial.SerialException:
                break
