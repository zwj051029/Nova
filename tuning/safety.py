from __future__ import annotations

from .models import PIDGains, SafetyLimits, TelemetrySample, TuningConfig


def validate_candidate(
    candidate: PIDGains, reference: PIDGains, config: TuningConfig,
) -> tuple[bool, str]:
    for name, value, lower, upper in zip(
        ("Kp", "Ki", "Kd"), candidate.as_array(),
        config.gain_min.as_array(), config.gain_max.as_array(),
    ):
        if not lower <= value <= upper:
            return False, f"{name} 超出允许范围 [{lower:g}, {upper:g}]"

    limit = config.safety.max_relative_gain_change
    for name, value, base, upper in zip(
        ("Kp", "Ki", "Kd"), candidate.as_array(), reference.as_array(),
        config.gain_max.as_array(),
    ):
        scale = max(abs(base), upper * 0.01, 1e-9)
        if abs(value - base) > scale * limit + 1e-12:
            return False, f"{name} 单次变化超过 {limit * 100:.0f}%"
    return True, ""


def check_live_sample(
    sample: TelemetrySample, limits: SafetyLimits,
) -> tuple[bool, str]:
    if not limits.actual_min <= sample.actual <= limits.actual_max:
        return False, "实际值超出安全范围"
    if abs(sample.output) > limits.output_abs_max:
        return False, "控制输出超出安全范围"
    return True, ""
