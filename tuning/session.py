from __future__ import annotations

import time

from .metrics import analyze_step_response
from .models import PIDGains, TelemetrySample, TrialResult, TuningConfig, ResponseMetrics
from .optimizer import BayesianPIDOptimizer
from .safety import check_live_sample, validate_candidate


class TuningSession:
    def __init__(self, config: TuningConfig):
        self.config = config
        self.baseline: PIDGains | None = None
        self.current_gains: PIDGains | None = None
        self.proposed: PIDGains | None = None
        self.history: list[TrialResult] = []
        self.capturing = False
        self.capture_is_baseline = False
        self.capture_started_at = 0.0
        self.samples: list[TelemetrySample] = []
        self._step_target: float | None = None
        self._step_initial_actual: float | None = None
        self.optimizer = BayesianPIDOptimizer(config)
        self._last_sequence = None
        self._device_t0 = None
        self.last_received_at = 0.0

    def set_baseline(self, gains: PIDGains) -> None:
        self.baseline = gains
        self.current_gains = gains
        self.proposed = None
        self.history.clear()

    def start_capture(self, gains: PIDGains, is_baseline: bool = False) -> None:
        self.current_gains = gains
        self.capture_is_baseline = is_baseline
        self.samples = []
        self._step_target = None
        self._step_initial_actual = None
        self.capture_started_at = time.monotonic()
        self.capturing = True
        self.last_received_at = self.capture_started_at
        self._last_sequence = None
        self._device_t0 = None

    def ingest(self, setpoint: float, actual: float, output: float,
               timestamp: float | None = None, sequence: int | None = None) -> tuple[bool, str]:
        if not self.capturing:
            return True, ""
        if len(self.samples) >= 200000:
            self.capturing = False
            return False, "单轮采样数超过 200000 上限"
        previous = self.samples[-1] if self.samples else None
        if sequence is not None:
            if self._last_sequence is not None and sequence != self._last_sequence + 1:
                self.capturing = False
                return False, "遥测丢帧或序号异常"
            self._last_sequence = sequence
        if timestamp is None:
            timestamp = previous.timestamp + self.config.sample_period_seconds if previous else 0.0
        else:
            if self._device_t0 is None:
                self._device_t0 = timestamp
            timestamp -= self._device_t0
            if previous and timestamp <= previous.timestamp:
                self.capturing = False
                return False, "设备时间戳未递增"
        self.last_received_at = time.monotonic()
        sample = TelemetrySample(timestamp, setpoint, actual, output)
        self.samples.append(sample)
        safe, reason = check_live_sample(sample, self.config.safety)
        if safe and previous and self._step_target is None:
            if abs(sample.setpoint - previous.setpoint) >= self.config.minimum_step:
                self._step_target = sample.setpoint
                self._step_initial_actual = previous.actual
        if safe and self._step_target is not None and self._step_initial_actual is not None:
            amplitude = abs(self._step_target - self._step_initial_actual)
            allowed = amplitude * self.config.safety.max_overshoot_percent / 100.0
            if self._step_target >= self._step_initial_actual:
                unsafe_overshoot = sample.actual > self._step_target + allowed
            else:
                unsafe_overshoot = sample.actual < self._step_target - allowed
            if unsafe_overshoot:
                safe, reason = False, "实时超调超过安全阈值"
        if not safe:
            self.capturing = False
        return safe, reason

    def finish_capture(self) -> TrialResult:
        if not self.current_gains:
            raise RuntimeError("尚未设置 PID 参数")
        self.capturing = False
        metrics = analyze_step_response(self.samples, self.config)
        safe = metrics.valid and (
            metrics.overshoot_percent <= self.config.safety.max_overshoot_percent)
        if metrics.valid and not safe:
            metrics.reason = "超调超过安全阈值"
        result = TrialResult(
            index=len(self.history) + 1,
            gains=self.current_gains,
            metrics=metrics,
            safe=safe,
            is_baseline=self.capture_is_baseline,
            samples=list(self.samples),
        )
        self.history.append(result)
        return result

    def record_failure(self, reason: str) -> TrialResult:
        result = TrialResult(len(self.history) + 1, self.current_gains,
                             ResponseMetrics(False, reason, sample_count=len(self.samples)),
                             False, self.capture_is_baseline, list(self.samples))
        self.history.append(result)
        self.capturing = False
        return result

    def suggest(self) -> tuple[PIDGains, str]:
        if not self.baseline:
            raise RuntimeError("请先设置并测试基准 PID")
        reference = self.current_gains or self.baseline
        gains, reason = self.optimizer.suggest(self.history, reference)
        ok, safety_reason = validate_candidate(gains, reference, self.config)
        if not ok:
            raise RuntimeError(safety_reason)
        self.proposed = gains
        return gains, reason

    def best_result(self) -> TrialResult | None:
        valid = [r for r in self.history if r.safe and r.metrics.valid]
        return min(valid, key=lambda r: r.metrics.score) if valid else None

    def abort(self) -> PIDGains | None:
        self.capturing = False
        self.samples = []
        self.proposed = None
        self.current_gains = self.baseline
        return self.baseline
