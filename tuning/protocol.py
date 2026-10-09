"""Nova v2: newline-delimited @JSON; legacy telemetry remains read-only compatible."""
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Frame:
    channel: int
    setpoint: float
    actual: float
    output: float
    timestamp: float | None = None
    sequence: int | None = None


def encode(message: dict) -> bytes:
    return ("@" + json.dumps(message, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: str) -> dict | None:
    if not line.startswith("@"):
        return None
    try:
        data = json.loads(line[1:], parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def telemetry(line: str) -> Frame | None:
    try:
        data = decode(line)
        if data and data.get("type") == "telemetry":
            frame = Frame(int(data["channel"]), float(data["sp"]), float(data["pv"]), float(data["out"]), float(data["time"]), int(data["seq"]))
        elif line.startswith(">"):
            channel, sp, pv, out = line[1:].split(",")
            frame = Frame(int(channel), float(sp), float(pv), float(out))
        else:
            return None
        values = (frame.setpoint, frame.actual, frame.output)
        if frame.timestamp is not None:
            values += (frame.timestamp,)
        return frame if all(math.isfinite(v) for v in values) else None
    except (ValueError, KeyError, TypeError, OverflowError):
        return None
