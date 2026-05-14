"""
虚拟串口发送器 —— 发送变化的目标值和带噪声的实际值。

用法：
    python virtual_serial_sender.py COM11
"""

import sys
import time
import math
import random
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM11"
BAUDRATE = 115200


def main() -> None:
    print(f"打开串口 {PORT} @ {BAUDRATE}，Ctrl+C 停止")
    try:
        with serial.Serial(PORT, BAUDRATE, timeout=1) as ser:
            # 每隔一段发一行乱码，测试错误处理
            noise_at = 15
            counter = 0
            setpoint = 100.0

            while True:
                counter += 1

                if counter == noise_at:
                    ser.write(b"hello world\r\n")
                    print("已发送乱码: hello world")
                    time.sleep(1)
                    continue

                # 目标值在 100~200 之间缓慢正弦变化
                setpoint = 150.0 + 50.0 * math.sin(counter * 0.05)
                # 实际值跟随目标值，加随机噪声
                actual = setpoint + random.uniform(-5.0, 5.0)

                frame = f">1,{setpoint:.2f},{actual:.2f},0.65\r\n"
                ser.write(frame.encode("utf-8"))
                print(f"已发送: {frame.strip()}")
                time.sleep(0.2)

    except serial.SerialException as e:
        print(f"串口错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("已停止")


if __name__ == "__main__":
    main()
