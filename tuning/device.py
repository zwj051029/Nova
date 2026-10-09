"""Deterministic closed-loop device and a serial-compatible real-time adapter."""
import collections
import math
import random
import threading
import time

from .models import PIDGains
from .protocol import decode, encode


class SimulatedDevice:
    def __init__(self, dt=.02, noise=0.0, delay_samples=0, drop_every=0, seed=7):
        self.dt, self.noise, self.drop_every = dt, noise, drop_every
        self.rng = random.Random(seed)
        self.delay = collections.deque([0.] * delay_samples)
        self.gains = PIDGains(1, .5, 0)
        self.target = self.value = self.integral = self.previous_value = 0.
        self.time = 0.
        self.seq = 0
        self.enabled = True
        self.watchdog = None
        self.last_heartbeat = 0.
        self.output_limit = 10.
        self.actual_min, self.actual_max = -100., 100.
        self.fault = ""

    def command(self, message):
        request_id = message.get("id")
        command = message.get("cmd")
        ack = {"type": "ack", "id": request_id, "cmd": command, "ok": True}
        try:
            if message.get("channel", 1) != 1:
                raise ValueError("unknown channel")
            if command == "hello":
                ack.update(version=2, capabilities=["ack", "set_pid", "set_target", "stop", "watchdog", "timestamp", "limits"],
                           algorithm="positional_pid_d_on_measurement", period=self.dt)
            elif command == "get":
                ack.update(gains=list(self.gains.as_array()), target=self.target, enabled=self.enabled)
            elif command == "configure":
                limits = [float(message[k]) for k in ("actual_min", "actual_max", "output_limit", "watchdog")]
                if not all(math.isfinite(v) for v in limits) or limits[0] >= limits[1] or limits[2] <= 0 or limits[3] <= 0:
                    raise ValueError("invalid limits")
                self.actual_min, self.actual_max, self.output_limit, self.watchdog = limits
                self.last_heartbeat = self.time
                self.fault = ""
            elif command == "heartbeat":
                self.last_heartbeat = self.time
            elif command == "set_pid":
                gains = PIDGains(*map(float, message["gains"]))
                if not all(math.isfinite(v) and 0 <= v <= 1e6 for v in gains.as_array()):
                    raise ValueError("invalid gains")
                self.gains = gains
                self.integral = 0.
                ack["gains"] = list(gains.as_array())
            elif command == "set_target":
                target = float(message["value"])
                if not math.isfinite(target) or not self.actual_min <= target <= self.actual_max or self.fault:
                    raise ValueError("unsafe target or latched fault")
                self.target = target
                self.enabled = True
                ack["value"] = target
            elif command == "stop":
                self.enabled = False
                self.integral = 0.
            else:
                raise ValueError("unsupported command")
        except (ValueError, TypeError, KeyError) as exc:
            ack.update(ok=False, error=str(exc))
        return ack

    def step(self):
        self.time += self.dt
        if self.watchdog is not None and self.enabled and self.time - self.last_heartbeat > self.watchdog:
            self.enabled = False
            self.fault = "watchdog timeout"
        error = self.target - self.value
        derivative = -(self.value - self.previous_value) / self.dt
        proposed_integral = self.integral + error * self.dt
        raw = self.gains.kp * error + self.gains.ki * proposed_integral + self.gains.kd * derivative
        output = max(-self.output_limit, min(self.output_limit, raw)) if self.enabled else 0.
        if self.enabled and (abs(raw) <= self.output_limit or raw * error < 0):
            self.integral = proposed_integral
        self.previous_value = self.value
        self.delay.append(output)
        delayed = self.delay.popleft()
        self.value += self.dt * (-self.value + delayed) / 1.2
        if not self.actual_min <= self.value <= self.actual_max:
            self.fault, self.enabled = "actual limit", False
        self.seq += 1
        if self.fault:
            return {"type": "fault", "reason": self.fault, "channel": 1}
        if self.drop_every and self.seq % self.drop_every == 0:
            return None
        return {"type": "telemetry", "channel": 1, "seq": self.seq, "time": self.time,
                "sp": self.target, "pv": self.value + self.rng.gauss(0, self.noise), "out": output}


class SimulatedPort:
    def __init__(self, **options):
        self.device = SimulatedDevice(**options)
        self.is_open = True
        self.buffer = bytearray()
        self.input = b""
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while self.is_open:
            with self.lock:
                frame = self.device.step()
                if frame:
                    self.buffer.extend(encode(frame))
            time.sleep(self.device.dt)

    @property
    def in_waiting(self):
        with self.lock:
            return len(self.buffer)

    def read(self, count):
        with self.lock:
            result = bytes(self.buffer[:count])
            del self.buffer[:count]
            return result

    def write(self, data):
        with self.lock:
            self.input += data
            while b"\n" in self.input:
                line, self.input = self.input.split(b"\n", 1)
                text = line.decode("utf-8").strip()
                message = decode(text)
                if message:
                    self.buffer.extend(encode(self.device.command(message)))
                elif text.startswith("PID:"):
                    try:
                        payload = text[4:]
                        values = list(self.device.gains.as_array())
                        if "=" in payload:
                            key, value = payload.split("=")
                            values[("Kp", "Ki", "Kd").index(key)] = float(value)
                        else:
                            values = list(map(float, payload.split(",")))
                        self.device.command({"cmd": "set_pid", "gains": values})
                    except (ValueError, TypeError):
                        pass
            return len(data)

    def close(self):
        self.is_open = False
        self.thread.join(.5)
