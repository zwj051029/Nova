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
        if seed is not None and all(seed != result.gains for result in history):
            return seed, "安全初始化探索"

        lower = np.asarray(self.config.gain_min.as_array(), dtype=float)
        upper = np.asarray(self.config.gain_max.as_array(), dtype=float)
        span = np.maximum(np.maximum(np.abs(reference.as_array()) * self.config.safety.max_relative_gain_change,
                                    self.config.safety.max_absolute_gain_change.as_array()) * 2,
                          self.config.gain_resolution.as_array())
        x = np.asarray([r.gains.as_array() for r in safe_results], dtype=float)
        x = (x - lower) / span
        y = np.asarray([r.metrics.score for r in safe_results], dtype=float)
        y_mean = float(np.mean(y))
        y_std = max(float(np.std(y)), 1e-6)
        yn = (y - y_mean) / y_std

        candidates = self._candidate_pool(best.gains, lower, upper, reference)
        seen = {tuple(round(v, 6) for v in r.gains.as_array()) for r in history}
        resolution = np.asarray(self.config.gain_resolution.as_array())
        candidates = np.unique(np.round(np.round(candidates / resolution) * resolution, 6), axis=0)
        for i,active in enumerate(self.config.active_axes()):
            if not active:
                candidates[:,i]=reference.as_array()[i]
        candidates = np.asarray([row for row in candidates if tuple(row) not in seen
                                 and validate_candidate(PIDGains(*row), reference, self.config)[0]])
        if not len(candidates):
            raise RuntimeError("当前范围内没有未测试参数，请调整范围或结束调参")
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
        axes = [i for i, active in enumerate(self.config.active_axes()) if active]
        if not axes:
            return None
        axis = axes[(count - 1) % len(axes)]
        values = list(best.as_array())
        upper = self.config.gain_max.as_array()
        step = max(abs(values[axis]) * 0.10, upper[axis] * 0.005, 1e-6)
        allowed = max(abs(reference.as_array()[axis]) * self.config.safety.max_relative_gain_change,
                      self.config.safety.max_absolute_gain_change.as_array()[axis])
        step = min(step, allowed * 0.5)
        values[axis] = min(upper[axis], values[axis] + step)
        resolution = self.config.gain_resolution.as_array()
        values = [round(round(v / r) * r, 6) if active else reference.as_array()[i]
                  for i,(v,r,active) in enumerate(zip(values,resolution,self.config.active_axes()))]
        candidate = PIDGains(*values)
        ok, _ = validate_candidate(candidate, reference, self.config)
        return candidate if ok and candidate != best else None

    def _candidate_pool(
        self, best: PIDGains, lower: np.ndarray, upper: np.ndarray,
        reference: PIDGains,
    ) -> np.ndarray:
        span = upper - lower
        center = np.asarray(best.as_array(), dtype=float)
        base = np.asarray(reference.as_array())
        radius = np.maximum(np.abs(base) * self.config.safety.max_relative_gain_change,
                            self.config.safety.max_absolute_gain_change.as_array())
        low = np.maximum(lower, base - radius)
        high = np.minimum(upper, base + radius)
        for i, active in enumerate(self.config.active_axes()):
            if not active:
                low[i] = high[i] = base[i]
        raw = self._rng.uniform(low, high, size=(1200, 3))
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
