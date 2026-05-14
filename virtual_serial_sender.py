"""
虚拟串口发送器 + 接收器。

- 每 200ms 发送一帧变化数据（目标值正弦波动，实际值带噪声）
- 同时打印收到的任何数据（用于验证上位机发送的 PID 指令）
- 第 15 帧发送一行乱码，测试上位机错误处理

用法：
    python virtual_serial_sender.py COM11
"""

import sys
import time
import math
import random
import threading
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM11"
BAUDRATE = 115200


def receive_loop(ser: serial.Serial) -> None:
    while True:
        try:
            if ser.in_waiting:
                raw = ser.readline()
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    print(f"[收到] {line}")
        except serial.SerialException:
            break


def main() -> None:
    print(f"打开串口 {PORT} @ {BAUDRATE}，Ctrl+C 停止")
    try:
        with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
            t = threading.Thread(target=receive_loop, args=(ser,), daemon=True)
            t.start()

            counter = 0
            while True:
                counter += 1

                if counter == 15:
                    ser.write(b"hello world\r\n")
                    print("已发送乱码: hello world")
                    time.sleep(0.2)
                    continue

                setpoint = 150.0 + 50.0 * math.sin(counter * 0.05)
                actual = setpoint + random.uniform(-5.0, 5.0)
                frame = f">1,{setpoint:.2f},{actual:.2f},0.65\r\n"
                ser.write(frame.encode("utf-8"))
                print(f"[发送] {frame.strip()}")
                time.sleep(0.2)

    except serial.SerialException as e:
        print(f"串口错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
