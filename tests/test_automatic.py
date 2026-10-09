import unittest
from tuning.automatic import AutomaticTuner
from tuning.device import SimulatedDevice
from tuning.models import PIDGains, SafetyLimits, TuningConfig
from tuning.protocol import decode, encode


class Harness:
    def __init__(self, automatic=True, drop_every=0):
        self.time = 0.
        self.queue = []
        self.device = SimulatedDevice(drop_every=drop_every)
        self.config = TuningConfig(sample_period_seconds=.02, capture_seconds=4, max_trials=4,
            stability_timeout=30, safety=SafetyLimits(actual_min=-2, actual_max=2, output_abs_max=10))
        self.tuner = AutomaticTuner(self.config, self.send, clock=lambda:self.time)
        self.tuner.start(PIDGains(1,.5,0), automatic)

    def send(self, data):
        self.queue.append(encode(self.device.command(decode(data.decode()))).decode())

    def step(self, telemetry=True):
        self.time += self.device.dt
        for line in self.queue[:]:
            self.queue.remove(line)
            self.tuner.handle_line(line)
        frame = self.device.step()
        if frame and telemetry:
            self.tuner.handle_line(encode(frame).decode())
        self.tuner.tick()

    def run(self, until=("review","aborted","awaiting_confirmation"), limit=12000):
        for _ in range(limit):
            self.step()
            if self.tuner.state in until:
                return self.tuner.state
        raise AssertionError((self.tuner.state,self.tuner.message))


class AutomaticTests(unittest.TestCase):
    def test_repeated_stop_still_times_out_without_ack(self):
        h = Harness()
        h.run(until=("capturing", "aborted"))
        h.tuner.stop()
        h.tuner.stop()
        h.queue.clear()
        h.time += 2
        h.tuner.tick()
        self.assertEqual(h.tuner.state, "aborted")
        self.assertIn("停止未确认", h.tuner.message)
        self.assertFalse(h.tuner.lease)

    def test_final_ack_rejects_change_above_resolution(self):
        h = Harness()
        self.assertEqual(h.run(), "review")
        h.tuner.decide(True)
        for i, line in enumerate(h.queue):
            ack = decode(line)
            if ack.get("cmd") == "set_pid":
                ack["gains"][0] += .00001
                h.queue[i] = encode(ack).decode()
        self.assertEqual(h.run(until=("accepted", "aborted")), "aborted")
        self.assertIn("PID", h.tuner.message)

    def test_repeated_stop_keeps_waiting_for_ack(self):
        h = Harness()
        h.run(until=("capturing", "aborted"))
        h.tuner.stop()
        pending = h.tuner.pending
        h.tuner.stop()
        h.tuner.handle_line(encode({"type": "fault", "channel": 1, "reason": "watchdog"}).decode())
        self.assertEqual(h.tuner.state, "stopping")
        self.assertEqual(h.tuner.pending, pending)
        self.assertEqual(h.run(), "aborted")
        self.assertIn("已确认停止", h.tuner.message)

    def test_final_ack_allows_transport_rounding(self):
        h = Harness()
        self.assertEqual(h.run(), "review")
        original = h.device.command
        def rounded(message):
            ack = original(message)
            if message.get("cmd") == "set_pid":
                ack["gains"] = [value + 1e-8 for value in ack["gains"]]
            return ack
        h.device.command = rounded
        h.tuner.decide(True)
        self.assertEqual(h.run(until=("accepted", "aborted")), "accepted", h.tuner.message)

    def test_complete_automatic_and_accept(self):
        h = Harness()
        self.assertEqual(h.run(), "review", h.tuner.message)
        self.assertIsNotNone(h.tuner.verified)
        self.assertFalse(h.device.enabled)
        self.assertEqual(len(h.tuner.session.history),4)
        h.tuner.decide(True)
        h.run(until=("accepted","aborted"))
        self.assertEqual(h.tuner.state,"accepted",h.tuner.message)
        self.assertEqual(h.device.gains,h.tuner.verified.gains)
        self.assertFalse(h.device.enabled)

    def test_human_confirmation_and_restore(self):
        h = Harness(automatic=False)
        original = h.device.gains
        while h.run() == "awaiting_confirmation":
            self.assertFalse(h.device.enabled)
            h.tuner.confirm_next()
        self.assertEqual(h.tuner.state,"review",h.tuner.message)
        h.tuner.decide(False)
        h.run(until=("restored","aborted"))
        self.assertEqual(h.device.gains,original)
        self.assertEqual(h.tuner.state,"restored")

    def test_missing_ack_and_unsupported_device(self):
        clock = [0.]
        sent = []
        tuner = AutomaticTuner(TuningConfig(), sent.append, clock=lambda:clock[0])
        tuner.start(PIDGains(1,0,0))
        clock[0]=2
        tuner.tick()
        self.assertEqual(tuner.state,"stopping")
        clock[0]=4
        tuner.tick()
        self.assertEqual(tuner.state,"aborted")
        self.assertFalse(any(decode(data.decode()).get("cmd")=="set_pid" for data in sent))

    def test_dropped_frame_stops_device(self):
        h = Harness(drop_every=20)
        self.assertEqual(h.run(),"aborted")
        self.assertFalse(h.device.enabled)

    def test_telemetry_timeout_and_manual_interruption(self):
        h = Harness()
        for _ in range(200):
            h.step(telemetry=False)
        self.assertEqual(h.tuner.state,"aborted")
        self.assertFalse(h.device.enabled)
        h = Harness()
        for _ in range(100):
            h.step()
        h.tuner.stop()
        self.assertEqual(h.run(),"aborted")
        self.assertFalse(h.device.enabled)

    def test_pid_ack_mismatch_is_rejected(self):
        h=Harness()
        original=h.device.command
        def altered(message):
            ack=original(message)
            if message.get("cmd")=="set_pid":
                ack["gains"]=[999,999,999]
            return ack
        h.device.command=altered
        self.assertEqual(h.run(),"aborted")
        self.assertIn("PID",h.tuner.message)

    def test_external_target_change_and_unsupported_capability(self):
        h=Harness()
        h.run(until=("capturing","aborted"))
        h.device.target=.7
        self.assertEqual(h.run(),"aborted")
        self.assertIn("目标值",h.tuner.message)
        h=Harness()
        first=decode(h.queue[0])
        first["capabilities"]=[]
        h.queue[0]=encode(first).decode()
        self.assertEqual(h.run(),"aborted")
        self.assertIn("不支持",h.tuner.message)

    def test_failure_preserved_once_and_heartbeat_stops(self):
        h=Harness()
        h.run(until=("capturing","aborted"))
        count=len(h.tuner.session.history)
        h.tuner.fail("injected failure")
        self.assertFalse(h.tuner.lease)
        self.assertEqual(len(h.tuner.session.history),count+1)
        self.assertTrue(h.tuner.session.history[-1].samples)
        h.run()
        self.assertEqual(len(h.tuner.session.history),count+1)

    def test_other_channel_ignored_and_device_time_capture(self):
        h=Harness()
        h.run(until=("capturing","aborted"))
        h.tuner.handle_line(encode({"type":"fault","channel":2,"reason":"other"}).decode())
        self.assertEqual(h.tuner.state,"capturing")
        h.run()
        trial=h.tuner.session.history[0]
        after=[sample for sample in trial.samples if sample.setpoint==h.config.step_target]
        self.assertGreaterEqual(after[-1].timestamp-after[0].timestamp,h.config.capture_seconds-.021)

    def test_final_restore_uses_bounded_acknowledged_steps(self):
        h=Harness()
        self.assertEqual(h.run(),"review",h.tuner.message)
        h.tuner.original=PIDGains(2,.8,.01)
        changes=[]
        original=h.device.command
        def capture(message):
            if message.get("cmd")=="set_pid":
                before=h.device.gains
                result=original(message)
                changes.append((before,h.device.gains))
                return result
            return original(message)
        h.device.command=capture
        h.tuner.decide(False)
        h.run(until=("restored","aborted"))
        self.assertEqual(h.tuner.state,"restored",h.tuner.message)
        self.assertGreater(len(changes),1)
        for before,after in changes:
            for a,b,absolute in zip(before.as_array(),after.as_array(),h.config.safety.max_absolute_gain_change.as_array()):
                self.assertLessEqual(abs(b-a),max(abs(a)*.2,absolute)+1e-6)
