import math
import tempfile
import unittest
from pathlib import Path
from tuning.device import SimulatedDevice
from tuning.metrics import analyze_step_response
from tuning.models import PIDGains, TelemetrySample, TuningConfig, TrialResult, ResponseMetrics
from tuning.protocol import encode, decode, telemetry
from tuning.session import TuningSession
from tuning.storage import save_session, load_session
from tuning.optimizer import BayesianPIDOptimizer
from tuning.simulator import FirstOrderPlant


class QualityTests(unittest.TestCase):
    def test_nonfinite_and_last_sample_not_settled(self):
        samples = [TelemetrySample(i*.1, 0 if i<5 else 1, 0 if i<5 else .5, .2) for i in range(30)]
        samples[-1] = TelemetrySample(2.9, 1, 1, .2)
        self.assertTrue(math.isnan(analyze_step_response(samples, TuningConfig()).settling_time))
        samples[-1] = TelemetrySample(2.9, 1, float("nan"), .2)
        self.assertFalse(analyze_step_response(samples, TuningConfig()).valid)

    def test_real_timeline_and_dropped_frame(self):
        session = TuningSession(TuningConfig())
        session.start_capture(PIDGains(1,0,0))
        self.assertTrue(session.ingest(0,0,0,10,1)[0])
        self.assertTrue(session.ingest(0,0,0,10.025,2)[0])
        self.assertAlmostEqual(session.samples[-1].timestamp,.025)
        self.assertFalse(session.ingest(0,0,0,10.05,4)[0])
        result = session.record_failure("missing")
        self.assertEqual(len(result.samples),2)

    def test_strict_storage_roundtrip(self):
        config = TuningConfig()
        history = [TrialResult(1,PIDGains(1,0,0),ResponseMetrics(False, "invalid"),False)]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = save_session(Path(directory),history[0].gains,config,history)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("NaN",text)
            self.assertNotIn("Infinity",text)
            baseline, loaded, trials = load_session(path)
            self.assertEqual(baseline,history[0].gains)
            self.assertFalse(trials[0].safe)

    def test_simulated_device_responds_to_gains(self):
        responses = []
        for kp in (.5, 3):
            device = SimulatedDevice()
            self.assertTrue(device.command({"cmd":"set_pid","gains":[kp,0,0]})["ok"])
            device.command({"cmd":"set_target","value":1})
            for _ in range(200):
                frame = device.step()
            self.assertIsNotNone(telemetry(encode(frame).decode()))
            responses.append(frame["pv"])
        self.assertGreater(responses[1],responses[0]+.2)

    def test_device_watchdog_and_protocol_validation(self):
        device = SimulatedDevice()
        device.command({"cmd":"configure","actual_min":-2,"actual_max":2,"output_limit":3,"watchdog":.1})
        for _ in range(20):
            frame = device.step()
        self.assertFalse(device.enabled)
        self.assertEqual(frame["type"],"fault")
        self.assertIsNone(telemetry(">1,nan,1,1"))
        self.assertIsNone(decode('@{"x":NaN}'))

    def test_optimizer_improves_repeatable_simulated_benchmark(self):
        config=TuningConfig()
        optimizer=BayesianPIDOptimizer(config)
        gains=PIDGains(1,.5,0)
        history=[]
        for i in range(12):
            samples=FirstOrderPlant().run_step(gains)
            metrics=analyze_step_response(samples,config)
            history.append(TrialResult(i+1,gains,metrics,metrics.valid and metrics.overshoot_percent<=30,i==0,samples))
            if i<11:
                gains,_=optimizer.suggest(history,gains)
        best=min(result.metrics.score for result in history if result.safe)
        self.assertLess(best,history[0].metrics.score*.75)
