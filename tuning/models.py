from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PIDGains:
    kp: float
    ki: float
    kd: float

    def as_array(self) -> tuple[float, float, float]:
        return self.kp, self.ki, self.kd

    def formatted(self, decimals: int = 6) -> str:
        return f"{self.kp:.{decimals}f},{self.ki:.{decimals}f},{self.kd:.{decimals}f}"


@dataclass(frozen=True)
class TelemetrySample:
    timestamp: float
    setpoint: float
    actual: float
    output: float


@dataclass
class ResponseMetrics:
    valid: bool
    reason: str = ""
    score: float = float("inf")
    rise_time: float = float("nan")
    settling_time: float = float("nan")
    overshoot_percent: float = 0.0
    steady_state_error: float = float("nan")
    iae: float = float("nan")
    itae: float = float("nan")
    control_effort: float = float("nan")
    output_variation: float = float("nan")
    sample_count: int = 0


@dataclass
class SafetyLimits:
    actual_min: float = -1_000_000.0
    actual_max: float = 1_000_000.0
    output_abs_max: float = 1_000_000.0
    max_overshoot_percent: float = 30.0
    max_relative_gain_change: float = 0.20


@dataclass
class TuningConfig:
    gain_min: PIDGains = field(default_factory=lambda: PIDGains(0.0, 0.0, 0.0))
    gain_max: PIDGains = field(default_factory=lambda: PIDGains(100.0, 100.0, 100.0))
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    capture_seconds: float = 10.0
    sample_period_seconds: float = 0.01
    max_trials: int = 20
    settling_tolerance_percent: float = 2.0
    minimum_step: float = 1e-6
    minimum_samples: int = 20
    weight_iae: float = 0.40
    weight_overshoot: float = 0.25
    weight_settling: float = 0.20
    weight_steady_error: float = 0.10
    weight_output_variation: float = 0.05


@dataclass
class TrialResult:
    index: int
    gains: PIDGains
    metrics: ResponseMetrics
    safe: bool
    is_baseline: bool = False
    samples: list[TelemetrySample] = field(default_factory=list)

    def to_dict(self, include_samples: bool = True) -> dict[str, Any]:
        data = {
            "index": self.index,
            "gains": asdict(self.gains),
            "metrics": asdict(self.metrics),
            "safe": self.safe,
            "is_baseline": self.is_baseline,
        }
        if include_samples:
            data["samples"] = [asdict(sample) for sample in self.samples]
        return data
