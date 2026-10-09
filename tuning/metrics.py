from __future__ import annotations

import math
import numpy as np

from .models import ResponseMetrics, TelemetrySample, TuningConfig


def analyze_step_response(
    samples: list[TelemetrySample], config: TuningConfig,
) -> ResponseMetrics:
    """Analyze the largest setpoint step in a captured telemetry window."""
    if len(samples) < config.minimum_samples:
        return ResponseMetrics(False, "采样点不足", sample_count=len(samples))

    t = np.asarray([s.timestamp for s in samples], dtype=float)
    sp = np.asarray([s.setpoint for s in samples], dtype=float)
    pv = np.asarray([s.actual for s in samples], dtype=float)
    out = np.asarray([s.output for s in samples], dtype=float)
    if not all(np.all(np.isfinite(a)) for a in (t, sp, pv, out)):
        return ResponseMetrics(False, "采样包含非有限数", sample_count=len(samples))
    t = t - t[0]

    dt = np.diff(t)
    if np.any(dt <= 0):
        return ResponseMetrics(False, "采样时间戳无效", sample_count=len(samples))

    diffs = np.abs(np.diff(sp))
    step_index = int(np.argmax(diffs)) + 1
    step_size = float(sp[step_index] - sp[step_index - 1])
    if abs(step_size) < config.minimum_step:
        return ResponseMetrics(False, "未检测到目标值阶跃", sample_count=len(samples))
    if step_index < 2 or len(samples) - step_index < max(8, config.minimum_samples // 3):
        return ResponseMetrics(False, "阶跃前后数据不足", sample_count=len(samples))

    initial = float(np.mean(pv[max(0, step_index - 5):step_index]))
    target = float(np.median(sp[step_index:]))
    setpoint_tolerance = max(abs(step_size) * 0.05, config.minimum_step * 2.0)
    if float(np.ptp(sp[step_index:])) > setpoint_tolerance:
        return ResponseMetrics(False, "阶跃后目标值未保持稳定", sample_count=len(samples))
    direction = 1.0 if step_size > 0 else -1.0
    post_t = t[step_index:] - t[step_index]
    post_pv = pv[step_index:]
    post_sp = sp[step_index:]
    post_out = out[step_index:]
    error = post_sp - post_pv
    amplitude = max(abs(target - initial), config.minimum_step)

    normalized_progress = direction * (post_pv - initial) / amplitude
    rise_hits = np.flatnonzero(normalized_progress >= 0.90)
    start_hits = np.flatnonzero(normalized_progress >= 0.10)
    rise_time = float(post_t[rise_hits[0]] - post_t[start_hits[0]]) if rise_hits.size and start_hits.size else float("nan")

    tolerance = amplitude * config.settling_tolerance_percent / 100.0
    within = np.abs(post_pv - target) <= tolerance
    settling_time = float("nan")
    outside = np.flatnonzero(~within)
    stable_start = int(outside[-1] + 1) if outside.size else 0
    if stable_start < len(post_t) and post_t[-1] - post_t[stable_start] >= config.settling_hold_seconds:
        settling_time = float(post_t[stable_start])

    if direction > 0:
        overshoot = max(0.0, float(np.max(post_pv) - target))
    else:
        overshoot = max(0.0, float(target - np.min(post_pv)))
    overshoot_percent = overshoot / amplitude * 100.0

    tail_count = max(3, len(post_pv) // 10)
    steady_error = float(np.mean(np.abs(error[-tail_count:])))
    iae = float(np.trapezoid(np.abs(error), post_t))
    itae = float(np.trapezoid(post_t * np.abs(error), post_t))
    control_effort = float(np.trapezoid(post_out * post_out, post_t))
    output_variation = float(np.sum(np.abs(np.diff(post_out))))
    duration = max(float(post_t[-1]), 1e-9)

    normalized_iae = iae / (amplitude * duration)
    normalized_settling = (settling_time / duration
                           if math.isfinite(settling_time) else 2.0)
    normalized_steady = steady_error / amplitude
    normalized_variation = output_variation / max(
        float(np.max(np.abs(post_out))) * duration, 1e-9)
    score = 100.0 * (
        config.weight_iae * normalized_iae
        + config.weight_overshoot * (overshoot_percent / 100.0)
        + config.weight_settling * normalized_settling
        + config.weight_steady_error * normalized_steady
        + config.weight_output_variation * normalized_variation
    )

    return ResponseMetrics(
        valid=True,
        score=score,
        rise_time=rise_time,
        settling_time=settling_time,
        overshoot_percent=overshoot_percent,
        steady_state_error=steady_error,
        iae=iae,
        itae=itae,
        control_effort=control_effort,
        output_variation=output_variation,
        sample_count=len(samples),
    )
