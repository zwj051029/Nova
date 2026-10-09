import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from main import MainWindow
from serial_worker import LineFramer, SerialWorker
from tuning.models import PIDGains, ResponseMetrics, TrialResult, TuningConfig
from tuning.optimizer import BayesianPIDOptimizer


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ui_theme_toast_precision(self):
        window = MainWindow()
        for theme in ("dark", "light"):
            window._apply_theme(theme, persist=False)
            window._show_toast("test", True)
        page = window._pid_page
        page.set_values(1.234567, 0.000123, 150)
        self.assertEqual(page._pid_ki.formatted_value(), "0.000123")
        self.assertEqual(page.current_values(), (1.234567, 0.000123, 150))
        page._pid_ki._set_decimals(2)
        self.assertEqual(page._pid_ki.value(), 0)
        page._pid_kp.spinbox.lineEdit().setText("1")
        page._pid_kp._sync_decimals_from_editor()
        self.assertEqual(page._pid_kp._decimals, 2)
        window.close()

    def test_large_burst_and_fragmented_lines(self):
        framer = LineFramer()
        self.assertEqual(len(framer.feed(b">1,1,1,1\n" * 2000)), 2000)
        self.assertEqual(framer.feed(b">1,1,"), [])
        self.assertEqual(framer.feed(b"1,1\n"), [">1,1,1,1"])
        framer.feed(b"x" * 5000)
        self.assertEqual(framer.feed(b"bad\nOK\n"), ["OK"])

    def test_serial_owner_and_partial_write(self):
        worker = SerialWorker()
        with self.assertRaises(Exception):
            worker.write(b"test")
        worker._port = Mock(is_open=True)
        worker._port.write.return_value = 2
        worker.acquire("ai")
        with self.assertRaises(RuntimeError):
            worker.write(b"test")
        with self.assertRaises(Exception):
            worker.write(b"test", owner="ai")
        worker.release("ai")

    def test_optimizer_does_not_repeat_history(self):
        baseline = PIDGains(1, .5, .1)
        gains = [baseline, PIDGains(1.1,.5,.1), PIDGains(1,.55,.1), PIDGains(1,.5,.11)]
        history = [TrialResult(i+1, g, ResponseMetrics(True, score=30-i), True) for i,g in enumerate(gains)]
        for seed in range(20):
            candidate, _ = BayesianPIDOptimizer(TuningConfig(), seed).suggest(history, baseline)
            self.assertNotIn(candidate, gains)
