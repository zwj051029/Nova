import os
import csv
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from main import MainWindow
from serial_worker import LineFramer, SerialWorker
from tuning.models import PIDGains, ResponseMetrics, TrialResult, TuningConfig, TelemetrySample, SafetyLimits
from tuning.session import TuningSession
from tuning.optimizer import BayesianPIDOptimizer
from tuning.config_dialog import ConfigDialog
from tuning.storage import save_session


class RegressionTests(unittest.TestCase):
    def test_pid_transmission_keeps_independent_precision(self):
        window = MainWindow()
        try:
            page = window._pid_page
            page.set_values(1.234567, .000123, .12)
            page._pid_ki.precision_decrease_btn.click()
            self.assertEqual(page._pid_kp._decimals, 6)
            self.assertEqual(page._pid_ki._decimals, 5)
            self.assertEqual(page._pid_kd._decimals, 2)
            with patch.object(window._worker, "is_open", return_value=True), patch.object(window._worker, "write") as write:
                page._send_all()
                write.assert_called_with(b"PID:1.234567,0.00012,0.12\r\n")
                page._send_single(page._pid_kp)
                write.assert_called_with(b"PID:Kp=1.234567\r\n")
        finally:
            window.close()

    def test_pid_waveform_channel_pause_and_csv(self):
        window = MainWindow()
        try:
            page = window._pid_page
            page.ingest_line(">2,10,20,30")
            self.assertEqual(len(page._buf_actual), 0)
            page.ingest_line(">1,1,0.5,0.2")
            page.refresh_plot()
            page._pause.setChecked(True)
            page.ingest_line(">1,1,0.75,0.3")
            page.refresh_plot()
            self.assertEqual(list(page._curve_actual.getData()[1]), [.5])
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
                path = Path(directory) / "waveform.csv"
                with patch("pid_page.QFileDialog.getSaveFileName", return_value=(str(path), "CSV")):
                    page._export_waveform()
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.reader(stream))
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[1][1:], ["1.0", "0.5", "0.2"])
            page._pause.setChecked(False)
            page.refresh_plot()
            self.assertEqual(list(page._curve_actual.getData()[1]), [.5, .75])
        finally:
            window.close()

    def test_serial_loopback_reconnect_and_counters(self):
        worker = SerialWorker()
        chunks, lines = [], []
        worker.chunk_received.connect(chunks.append)
        worker.lines_received.connect(lines.extend)
        try:
            for _ in range(2):
                chunks.clear()
                lines.clear()
                worker.open("loop://", 115200)
                payload = "中文回环\n>1,1,0.5,0.2\n".encode("utf-8")
                worker.write(payload)
                for _ in range(100):
                    QTest.qWait(10)
                    if len(lines) == 2:
                        break
                self.assertEqual(b"".join(chunks), payload)
                self.assertEqual(lines, ["中文回环", ">1,1,0.5,0.2"])
                self.assertEqual(worker.rx_bytes, len(payload))
                self.assertEqual(worker.tx_bytes, len(payload))
                worker.close()
                self.assertFalse(worker.is_open())
        finally:
            worker.close()

    def test_selected_trial_survives_live_refresh(self):
        window = MainWindow()
        page = window._ai_page
        page._session = TuningSession(TuningConfig())
        samples = [TelemetrySample(0, 1, .25, 0), TelemetrySample(1, 1, .5, 0)]
        trial = TrialResult(1, PIDGains(1, 0, 0), ResponseMetrics(True, score=1), True, samples=samples)
        page._session.history = [trial]
        page._session.samples = [TelemetrySample(0, 2, 3, 0)]
        page._append_result(trial)
        page._table.selectRow(0)
        page.refresh_plot()
        self.assertEqual(list(page._pv_curve.getData()[1]), [.25, .5])
        page._session.capturing = True
        page.refresh_plot()
        self.assertEqual(list(page._pv_curve.getData()[1]), [3])
        page._session.capturing = False
        window.close()

    def test_profile_safety_precision_is_not_rounded(self):
        window = MainWindow()
        config = TuningConfig(max_trials=3, safety=SafetyLimits(
            max_relative_gain_change=.155123, max_overshoot_percent=12.345678))
        window._ai_page._apply_config(config)
        actual = window._ai_page._config()
        self.assertAlmostEqual(actual.safety.max_relative_gain_change, .155123, places=8)
        self.assertAlmostEqual(actual.safety.max_overshoot_percent, 12.345678, places=8)
        self.assertEqual(actual.max_trials, 3)
        window.close()

    def test_invalid_json_shapes_are_reported_without_crashing(self):
        window = MainWindow()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path = Path(directory) / "invalid.json"
            for contents in ("[]", '{"config":{},"baseline":{},"trials":[[]]}'):
                path.write_text(contents, encoding="utf-8")
                with patch("ai_tuning_page.QFileDialog.getOpenFileName", return_value=(str(path), "JSON")), patch.object(window._ai_page, "_toast") as toast:
                    window._ai_page._open_history()
                    self.assertFalse(toast.call_args.args[1])
                    window._ai_page._load_profile()
                    self.assertFalse(toast.call_args.args[1])
        window.close()

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

    def test_keyboard_precision_and_streamed_utf8(self):
        window=MainWindow()
        row=window._pid_page._pid_ki
        editor=row.spinbox.lineEdit()
        editor.selectAll()
        QTest.keyClicks(editor,"0.000123")
        self.app.processEvents()
        self.assertEqual(row._decimals,6)
        self.assertEqual(row.formatted_value(),"0.000123")
        QTest.keyClick(editor,Qt.Key.Key_Backspace)
        self.app.processEvents()
        self.assertEqual(row._decimals,5)
        page=window._serial_page
        text="中文串口\n".encode()
        page.append_received_bytes(text[:2])
        page.append_received_bytes(text[2:])
        self.assertEqual(page._recv_box.toPlainText(),"中文串口\n")
        window._apply_theme("dark",persist=False)
        window._apply_theme("light",persist=False)
        self.assertEqual(page._recv_box.toPlainText(),"中文串口\n")
        window.close()

    def test_hex_raw_and_signal_controls(self):
        window=MainWindow()
        port=Mock(is_open=True)
        port.write.side_effect=lambda data:len(data)
        window._worker._port=port
        page=window._serial_page
        page._toggle_mode()
        page._send_input.setText("AA 55 0D 0A")
        page._do_send()
        port.write.assert_called_once_with(b"\xaa\x55\r\n")
        page._dtr_chk.setChecked(True)
        self.assertTrue(port.dtr)
        window._worker.acquire("ai")
        page._do_send()
        self.assertEqual(port.write.call_count,1)
        window._worker.release("ai")
        window.close()

    def test_profile_roundtrip_independent_ranges(self):
        window=MainWindow()
        page=window._ai_page
        config=TuningConfig(gain_max=PIDGains(5,.001,.00001),gain_resolution=PIDGains(.001,.000001,.000001),locked=(False,True,False))
        dialog=ConfigDialog(config,window)
        updated=dialog.result_config()
        updated.validate()
        page._apply_config(updated)
        self.assertEqual(page._config().gain_max,config.gain_max)
        self.assertEqual(page._config().locked,config.locked)
        window.close()

    def test_history_is_readonly_and_never_sends(self):
        window=MainWindow()
        history=[TrialResult(1,PIDGains(1,.5,0),ResponseMetrics(True,score=10),True,True)]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            path=save_session(Path(directory),history[0].gains,TuningConfig(),history)
            before=path.read_bytes()
            with patch("ai_tuning_page.QFileDialog.getOpenFileName",return_value=(str(path),"JSON")),patch.object(window._worker,"write") as write:
                window._ai_page._open_history()
                window._ai_page._save_session()
                window._ai_page._abort()
                self.assertTrue(window._ai_page._history_only)
                self.assertFalse(window._ai_page._apply_btn.isEnabled())
                write.assert_not_called()
                self.assertEqual(path.read_bytes(),before)
        window.close()
