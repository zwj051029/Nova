"""
虚拟串口发送器 —— 每秒向指定串口发送一帧测试数据。

Windows 用法（需先安装 com0com 创建虚拟串口对，见下方说明）：
    python virtual_serial_sender.py COM3

Linux / macOS 用法（需先用 socat 创建虚拟串口对，见下方说明）：
    python virtual_serial_sender.py /dev/ttyV0
"""

import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
BAUDRATE = 115200
INTERVAL = 1.0  # 秒


def main() -> None:
    print(f"打开串口 {PORT} @ {BAUDRATE}，每 {INTERVAL}s 发送一帧，Ctrl+C 停止")
    try:
        with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
            counter = 1
            while True:
                frame = f">{ counter},1500.5,1498.3,0.65\r\n"
                ser.write(frame.encode("utf-8"))
                print(f"已发送: {frame.strip()}")
                counter += 1
                time.sleep(INTERVAL)
    except serial.SerialException as e:
        print(f"串口错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
