import threading
import serial
from PySide6.QtCore import QObject, Signal


class SerialWorker(QObject):
    line_received = Signal(str)

    def __init__(self):
        super().__init__()
        self._port: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def open(self, port: str, baudrate: int,
             bytesize=8, parity="N", stopbits=1) -> None:
        self._port = serial.Serial(
            port, baudrate, timeout=1,
            bytesize=bytesize, parity=parity, stopbits=stopbits,
        )
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
