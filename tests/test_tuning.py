import math
import unittest

from tuning.metrics import analyze_step_response
from tuning.models import PIDGains, ResponseMetrics, SafetyLimits, TrialResult, TuningConfig
from tuning.optimizer import BayesianPIDOptimizer
from tuning.safety import validate_candidate
from tuning.session import TuningSession
from tuning.simulator import FirstOrderPlant


class MetricsTests(unittest.TestCase):
    def test_stable_step_response_is_scored(self):
        config = TuningConfig(minimum_samples=20)
        samples = FirstOrderPlant().run_step(PIDGains(2.0, 1.0, 0.05))
        metrics = analyze_step_response(samples, config)
        self.assertTrue(metrics.valid, metrics.reason)
        self.assertTrue(math.isfinite(metrics.score))
        self.assertGreater(metrics.sample_count, 100)
        self.assertGreaterEqual(metrics.overshoot_percent, 0.0)

    def test_capture_without_step_is_rejected(self):
        plant = FirstOrderPlant()
        samples = plant.run_step(PIDGains(1.0, 0.0, 0.0), setpoint=0.0)
        metrics = analyze_step_response(samples, TuningConfig())
        self.assertFalse(metrics.valid)

    def test_moving_setpoint_is_not_misclassified_as_step(self):
        samples = FirstOrderPlant().run_step(PIDGains(1.0, 0.0, 0.0))
        moving = [type(sample)(sample.timestamp, sample.timestamp,
                               sample.actual, sample.output) for sample in samples]
        metrics = analyze_step_response(moving, TuningConfig())
        self.assertFalse(metrics.valid)


class SafetyTests(unittest.TestCase):
    def test_relative_change_is_enforced(self):
        config = TuningConfig()
        reference = PIDGains(1.0, 1.0, 1.0)
        self.assertTrue(validate_candidate(PIDGains(1.1, 1.0, 1.0), reference, config)[0])
        self.assertFalse(validate_candidate(PIDGains(2.0, 1.0, 1.0), reference, config)[0])

    def test_live_overshoot_aborts_capture(self):
        config = TuningConfig(
            sample_period_seconds=0.02,
            safety=SafetyLimits(max_overshoot_percent=10.0),
        )
        session = TuningSession(config)
        gains = PIDGains(1.0, 0.0, 0.0)
        session.set_baseline(gains)
        session.start_capture(gains, is_baseline=True)
        session.ingest(0.0, 0.0, 0.0)
        safe, reason = session.ingest(1.0, 1.5, 1.0)
        self.assertFalse(safe)
        self.assertIn("超调", reason)
        self.assertFalse(session.capturing)

    def test_configured_sample_period_rebuilds_timeline(self):
        config = TuningConfig(sample_period_seconds=0.025)
        session = TuningSession(config)
        gains = PIDGains(1.0, 0.0, 0.0)
        session.set_baseline(gains)
        session.start_capture(gains)
        session.ingest(0.0, 0.0, 0.0)
        session.ingest(0.0, 0.0, 0.0)
        self.assertAlmostEqual(session.samples[1].timestamp, 0.025)


class OptimizerTests(unittest.TestCase):
    def test_suggestion_is_bounded_and_not_baseline(self):
        config = TuningConfig()
        baseline = PIDGains(1.0, 0.5, 0.1)
        history = [TrialResult(
            index=1, gains=baseline,
            metrics=ResponseMetrics(valid=True, score=30.0),
            safe=True, is_baseline=True,
        )]
        candidate, _ = BayesianPIDOptimizer(config).suggest(history, baseline)
        self.assertNotEqual(candidate, baseline)
        self.assertTrue(validate_candidate(candidate, baseline, config)[0])

    def test_gaussian_process_stage_returns_safe_candidate(self):
        config = TuningConfig()
        baseline = PIDGains(1.0, 0.5, 0.1)
        gains = [
            baseline,
            PIDGains(1.1, 0.5, 0.1),
            PIDGains(1.0, 0.55, 0.1),
            PIDGains(1.0, 0.5, 0.11),
        ]
        history = [TrialResult(
            i + 1, gain, ResponseMetrics(valid=True, score=30.0 - i), True,
        ) for i, gain in enumerate(gains)]
        candidate, reason = BayesianPIDOptimizer(config).suggest(history, baseline)
        self.assertTrue(validate_candidate(candidate, baseline, config)[0])
        self.assertIn("高斯过程", reason)


if __name__ == "__main__":
    unittest.main()
