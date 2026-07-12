from __future__ import annotations

import numpy as np

from .models import PIDGains, TrialResult, TuningConfig
from .safety import validate_candidate


class BayesianPIDOptimizer:
    """Small Gaussian-process optimizer specialized for three PID gains."""

    def __init__(self, config: TuningConfig, seed: int = 2026):
        self.config = config
        self._rng = np.random.default_rng(seed)

    def suggest(
        self, history: list[TrialResult], reference: PIDGains,
    ) -> tuple[PIDGains, str]:
        safe_results = [r for r in history if r.safe and r.metrics.valid]
        if not safe_results:
            return reference, "尚无有效基准试验"

        best = min(safe_results, key=lambda r: r.metrics.score)
        seed = self._seed_candidate(len(safe_results), best.gains, reference)
        if seed is not None:
            return seed, "安全初始化探索"

        lower = np.asarray(self.config.gain_min.as_array(), dtype=float)
        upper = np.asarray(self.config.gain_max.as_array(), dtype=float)
        span = np.maximum(upper - lower, 1e-12)
        x = np.asarray([r.gains.as_array() for r in safe_results], dtype=float)
        x = (x - lower) / span
        y = np.asarray([r.metrics.score for r in safe_results], dtype=float)
        y_mean = float(np.mean(y))
        y_std = max(float(np.std(y)), 1e-6)
        yn = (y - y_mean) / y_std

        candidates = self._candidate_pool(best.gains, lower, upper, reference)
        cx = (candidates - lower) / span
        mean, std = self._gp_predict(x, yn, cx)
        # Lower-confidence bound: exploit good regions while retaining exploration.
        acquisition = mean - 1.25 * std
        for unsafe in (r for r in history if not r.safe):
            ux = (np.asarray(unsafe.gains.as_array()) - lower) / span
            distance = np.linalg.norm(cx - ux, axis=1)
            acquisition += np.exp(-np.square(distance / 0.08)) * 5.0
        idx = int(np.argmin(acquisition))
        gains = PIDGains(*map(float, candidates[idx]))
        predicted = mean[idx] * y_std + y_mean
        return gains, f"高斯过程预测评分 {predicted:.2f}，不确定度 {std[idx] * y_std:.2f}"

    def _seed_candidate(
        self, count: int, best: PIDGains, reference: PIDGains,
    ) -> PIDGains | None:
        if count >= 4:
            return None
        axis = (count - 1) % 3
        values = list(best.as_array())
        upper = self.config.gain_max.as_array()
        step = max(abs(values[axis]) * 0.10, upper[axis] * 0.005, 1e-6)
        safety_scale = max(abs(reference.as_array()[axis]), upper[axis] * 0.01, 1e-9)
        step = min(step, safety_scale * self.config.safety.max_relative_gain_change * 0.5)
        values[axis] = min(upper[axis], values[axis] + step)
        candidate = PIDGains(*values)
        ok, _ = validate_candidate(candidate, reference, self.config)
        return candidate if ok and candidate != best else None

    def _candidate_pool(
        self, best: PIDGains, lower: np.ndarray, upper: np.ndarray,
        reference: PIDGains,
    ) -> np.ndarray:
        span = upper - lower
        center = np.asarray(best.as_array(), dtype=float)
        radius = np.maximum(span * 0.12, np.abs(center) * 0.20)
        raw = self._rng.uniform(-1.0, 1.0, size=(2500, 3)) * radius + center
        raw = np.clip(raw, lower, upper)
        valid = []
        for row in raw:
            gains = PIDGains(*map(float, row))
            if validate_candidate(gains, reference, self.config)[0]:
                valid.append(row)
        if not valid:
            return np.asarray([center])
        return np.asarray(valid)

    @staticmethod
    def _gp_predict(
        x: np.ndarray, y: np.ndarray, candidates: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        length_scale = 0.25

        def kernel(a: np.ndarray, b: np.ndarray) -> np.ndarray:
            sq = np.sum((a[:, None, :] - b[None, :, :]) ** 2, axis=2)
            return np.exp(-0.5 * sq / (length_scale ** 2))

        kxx = kernel(x, x) + np.eye(len(x)) * 1e-5
        try:
            chol = np.linalg.cholesky(kxx)
            alpha = np.linalg.solve(chol.T, np.linalg.solve(chol, y))
            kxs = kernel(x, candidates)
            mean = kxs.T @ alpha
            v = np.linalg.solve(chol, kxs)
            variance = np.maximum(1.0 - np.sum(v * v, axis=0), 1e-9)
        except np.linalg.LinAlgError:
            mean = np.full(len(candidates), float(np.mean(y)))
            variance = np.ones(len(candidates))
        return mean, np.sqrt(variance)
