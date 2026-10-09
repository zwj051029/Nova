from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
import math


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
    max_absolute_gain_change: PIDGains = field(default_factory=lambda: PIDGains(0.02, 0.02, 0.002))
    telemetry_timeout: float = 1.0
    saturation_seconds: float = 1.0


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
    settling_hold_seconds: float = 0.5
    channel: int = 1
    mode: str = "PID"
    locked: tuple[bool, bool, bool] = (False, False, False)
    gain_resolution: PIDGains = field(default_factory=lambda: PIDGains(1e-6, 1e-6, 1e-6))
    initial_target: float = 0.0
    step_target: float = 1.0
    stable_tolerance: float = 0.02
    stable_seconds: float = 0.5
    stability_timeout: float = 30.0
    pre_seconds: float = 1.0
    patience: int = 5
    target_score: float = 0.0
    device_name: str = "Generic"
    unit: str = "unit"
    algorithm: str = "positional_pid_d_on_measurement"

    def validate(self) -> None:
        for gains in (self.gain_min, self.gain_max, self.gain_resolution, self.safety.max_absolute_gain_change):
            if not all(math.isfinite(v) and v >= 0 for v in gains.as_array()):
                raise ValueError("PID 范围、分辨率和变化限制必须为有限非负数")
        if any(lo > hi or step < 1e-6 for lo, hi, step in zip(self.gain_min.as_array(), self.gain_max.as_array(), self.gain_resolution.as_array())):
            raise ValueError("参数范围或分辨率无效（协议最小分辨率为 0.000001）")
        numeric = (self.capture_seconds, self.sample_period_seconds, self.settling_hold_seconds,
                   self.stable_seconds, self.stability_timeout, self.pre_seconds,
                   self.safety.telemetry_timeout, self.safety.saturation_seconds, self.stable_tolerance,
                   self.minimum_step, self.settling_tolerance_percent)
        if not all(math.isfinite(v) and v > 0 for v in numeric):
            raise ValueError("时间和容差必须为正数")
        if (any(type(v) is not int for v in (self.max_trials, self.minimum_samples, self.channel, self.patience))
                or not 1 <= self.max_trials <= 100 or self.minimum_samples < 3 or self.channel < 0):
            raise ValueError("试验数、采样数或通道无效")
        if (self.mode not in ("P", "PI", "PID") or not isinstance(self.locked, (list, tuple))
                or len(self.locked) != 3 or any(type(v) is not bool for v in self.locked)):
            raise ValueError("控制模式无效")
        limits = self.safety
        if not all(math.isfinite(v) for v in (limits.actual_min, limits.actual_max, limits.output_abs_max,
                limits.max_relative_gain_change, limits.max_overshoot_percent, self.initial_target, self.step_target)):
            raise ValueError("安全限制必须为有限数")
        if limits.actual_min >= limits.actual_max or limits.output_abs_max <= 0 or not 0 < limits.max_relative_gain_change <= 1:
            raise ValueError("安全范围无效")
        weights=(self.weight_iae,self.weight_overshoot,self.weight_settling,self.weight_steady_error,self.weight_output_variation)
        if not all(math.isfinite(v) and v>=0 for v in weights) or sum(weights)<=0:
            raise ValueError("评分权重无效")
        if not 1<=self.patience<=100 or not math.isfinite(self.target_score) or self.target_score<0 or limits.max_overshoot_percent<0:
            raise ValueError("停止条件无效")

    def active_axes(self) -> tuple[bool, bool, bool]:
        return tuple(not self.locked[i] and i < {"P": 1, "PI": 2, "PID": 3}[self.mode] for i in range(3))


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
