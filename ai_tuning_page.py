from __future__ import annotations

import math
import time
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from i18n import Translator
from serial_worker import SerialWorker
from tuning.models import PIDGains, SafetyLimits, TuningConfig
from tuning.session import TuningSession
from tuning.storage import save_session


PRIMARY_STYLE = """
QPushButton { background:#165DFF; color:white; border:none; border-radius:5px;
padding:7px 12px; font-weight:bold; }
QPushButton:hover { background:#0E4BD7; }
QPushButton:disabled { background:#C9CDD4; color:#86909C; }
"""
SECONDARY_STYLE = """
QPushButton { background:#EEF4FF; color:#165DFF; border:1px solid #B7D1FF;
border-radius:5px; padding:7px 10px; font-weight:bold; }
QPushButton:hover { background:#DCE9FF; }
QPushButton:disabled { background:#F2F3F5; color:#86909C; border-color:#E5E8EB; }
"""
DANGER_STYLE = """
QPushButton { background:#F53F3F; color:white; border:none; border-radius:5px;
padding:8px 12px; font-weight:bold; }
QPushButton:hover { background:#CB2634; }
QPushButton:disabled { background:#F2F3F5; color:#C9CDD4; }
"""


def _parse_pid_frame(line: str) -> tuple[float, float, float] | None:
    if not line.startswith(">"):
        return None
    try:
        fields = line[1:].split(",")
        if len(fields) != 4:
            return None
        int(fields[0])
        return float(fields[1]), float(fields[2]), float(fields[3])
    except ValueError:
        return None


class AiTuningPage(QWidget):
    """Human-in-the-loop, safety-constrained AI PID tuning page."""

    def __init__(self, worker: SerialWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._tr = Translator()
        self._tr.on_change(self.retranslate)
        self._session: TuningSession | None = None
        self._connected = False
        self._proposed: PIDGains | None = None
        self._session_path: Path | None = None
        self._capture_t0 = 0.0
        self.on_toast = None
        self.on_data_sent = None
        self.on_pid_applied = None
        self.baseline_provider = None
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._update_capture_clock)
        self._timer.start()
        self.retranslate()
        self.set_connected(False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        self._title = QLabel()
        self._title.setStyleSheet("font-size:18px; font-weight:bold; color:#1D2129;")
        self._status = QLabel()
        self._status.setStyleSheet(
            "background:#F2F3F5; color:#4E5969; border-radius:10px; padding:4px 10px;")
        header.addWidget(self._title)
        header.addStretch()
        header.addWidget(self._status)
        root.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_config_panel())
        splitter.addWidget(self._build_workspace())
        splitter.setSizes([340, 800])
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _build_config_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(8)

        self._baseline_group = QGroupBox()
        baseline_form = QFormLayout(self._baseline_group)
        self._kp = self._gain_spin(1.0)
        self._ki = self._gain_spin(0.0)
        self._kd = self._gain_spin(0.0)
        baseline_form.addRow("Kp", self._kp)
        baseline_form.addRow("Ki", self._ki)
        baseline_form.addRow("Kd", self._kd)
        self._load_manual_btn = QPushButton()
        self._load_manual_btn.setStyleSheet(SECONDARY_STYLE)
        self._load_manual_btn.clicked.connect(self._load_manual_pid)
        baseline_form.addRow(self._load_manual_btn)
        layout.addWidget(self._baseline_group)

        self._search_group = QGroupBox()
        search_form = QFormLayout(self._search_group)
        self._gain_max = self._gain_spin(100.0)
        self._relative_change = QSpinBox()
        self._relative_change.setRange(5, 100)
        self._relative_change.setValue(20)
        self._relative_change.setSuffix(" %")
        self._max_trials = QSpinBox()
        self._max_trials.setRange(4, 100)
        self._max_trials.setValue(20)
        self._capture_seconds = QDoubleSpinBox()
        self._capture_seconds.setRange(2.0, 600.0)
        self._capture_seconds.setValue(10.0)
        self._capture_seconds.setSuffix(" s")
        self._sample_period_ms = QDoubleSpinBox()
        self._sample_period_ms.setRange(0.01, 10_000.0)
        self._sample_period_ms.setDecimals(3)
        self._sample_period_ms.setValue(10.0)
        self._sample_period_ms.setSuffix(" ms")
        search_form.addRow(self._label("gain_max"), self._gain_max)
        search_form.addRow(self._label("relative_change"), self._relative_change)
        search_form.addRow(self._label("max_trials"), self._max_trials)
        search_form.addRow(self._label("capture_time"), self._capture_seconds)
        search_form.addRow(self._label("sample_period"), self._sample_period_ms)
        layout.addWidget(self._search_group)

        self._safety_group = QGroupBox()
        safety_form = QFormLayout(self._safety_group)
        self._actual_min = self._wide_spin(-1_000_000.0)
        self._actual_max = self._wide_spin(1_000_000.0)
        self._output_max = self._wide_spin(1_000_000.0)
        self._overshoot_max = QDoubleSpinBox()
        self._overshoot_max.setRange(0.0, 500.0)
        self._overshoot_max.setValue(30.0)
        self._overshoot_max.setSuffix(" %")
        safety_form.addRow(self._label("actual_min"), self._actual_min)
        safety_form.addRow(self._label("actual_max"), self._actual_max)
        safety_form.addRow(self._label("output_max"), self._output_max)
        safety_form.addRow(self._label("overshoot_max"), self._overshoot_max)
        layout.addWidget(self._safety_group)
        layout.addStretch()
        return panel

    def _build_workspace(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(8)

        cards = QGridLayout()
        self._baseline_value = self._result_card(cards, 0)
        self._proposed_value = self._result_card(cards, 1)
        self._best_value = self._result_card(cards, 2)
        layout.addLayout(cards)

        buttons = QHBoxLayout()
        self._baseline_btn = QPushButton()
        self._finish_btn = QPushButton()
        self._suggest_btn = QPushButton()
        self._apply_btn = QPushButton()
        self._abort_btn = QPushButton()
        self._baseline_btn.setStyleSheet(PRIMARY_STYLE)
        self._finish_btn.setStyleSheet(SECONDARY_STYLE)
        self._suggest_btn.setStyleSheet(SECONDARY_STYLE)
        self._apply_btn.setStyleSheet(PRIMARY_STYLE)
        self._abort_btn.setStyleSheet(DANGER_STYLE)
        self._baseline_btn.clicked.connect(self._start_baseline)
        self._finish_btn.clicked.connect(self._finish_capture)
        self._suggest_btn.clicked.connect(self._suggest)
        self._apply_btn.clicked.connect(self._apply_proposed)
        self._abort_btn.clicked.connect(self._abort)
        for button in (self._baseline_btn, self._finish_btn, self._suggest_btn,
                       self._apply_btn, self._abort_btn):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            "background:#FFF7E8; color:#7A4E00; border:1px solid #FFD591;"
            "border-radius:5px; padding:7px;")
        layout.addWidget(self._hint)

        plot = pg.PlotWidget()
        plot.setBackground("w")
        plot.showGrid(x=True, y=True, alpha=0.2)
        self._sp_curve = plot.plot(pen=pg.mkPen("#2ECC71", width=2), name="Setpoint")
        self._pv_curve = plot.plot(pen=pg.mkPen("#E74C3C", width=2), name="Actual")
        plot.addLegend()
        layout.addWidget(plot, 2)

        self._table = QTableWidget(0, 8)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)
        return panel

    @staticmethod
    def _gain_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1_000_000.0)
        spin.setDecimals(6)
        spin.setValue(value)
        return spin

    @staticmethod
    def _wide_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spin.setDecimals(3)
        spin.setValue(value)
        return spin

    @staticmethod
    def _label(key: str) -> QLabel:
        label = QLabel()
        label.setProperty("tr_key", key)
        return label

    def _result_card(self, layout: QGridLayout, column: int) -> QLabel:
        box = QGroupBox()
        box.setProperty("card_index", column)
        v = QVBoxLayout(box)
        value = QLabel("--")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet("font-family:Consolas; font-size:14px; color:#165DFF;")
        v.addWidget(value)
        layout.addWidget(box, 0, column)
        return value

    def _config(self) -> TuningConfig:
        gain_max = self._gain_max.value()
        return TuningConfig(
            gain_min=PIDGains(0.0, 0.0, 0.0),
            gain_max=PIDGains(gain_max, gain_max, gain_max),
            safety=SafetyLimits(
                actual_min=self._actual_min.value(),
                actual_max=self._actual_max.value(),
                output_abs_max=abs(self._output_max.value()),
                max_overshoot_percent=self._overshoot_max.value(),
                max_relative_gain_change=self._relative_change.value() / 100.0,
            ),
            capture_seconds=self._capture_seconds.value(),
            sample_period_seconds=self._sample_period_ms.value() / 1000.0,
            max_trials=self._max_trials.value(),
        )

    def _gains_from_inputs(self) -> PIDGains:
        return PIDGains(self._kp.value(), self._ki.value(), self._kd.value())

    def _load_manual_pid(self) -> None:
        if not self.baseline_provider:
            return
        gains = self.baseline_provider()
        self._kp.setValue(gains.kp)
        self._ki.setValue(gains.ki)
        self._kd.setValue(gains.kd)

    def _start_baseline(self) -> None:
        if not self._require_connection():
            return
        config = self._config()
        if config.safety.actual_min >= config.safety.actual_max:
            self._toast(self._tr.tr("ai_invalid_actual_range"), False)
            return
        gains = self._gains_from_inputs()
        if any(value > self._gain_max.value() for value in gains.as_array()):
            self._toast(self._tr.tr("ai_invalid_baseline"), False)
            return
        self._session = TuningSession(config)
        self._session.set_baseline(gains)
        self._proposed = None
        self._session_path = None
        self._baseline_value.setText(gains.formatted())
        self._best_value.setText("--")
        self._proposed_value.setText("--")
        self._table.setRowCount(0)
        if self._send_pid(gains):
            self._session.start_capture(gains, is_baseline=True)
            self._begin_capture_ui()

    def _finish_capture(self) -> None:
        if not self._session or not self._session.capturing:
            return
        result = self._session.finish_capture()
        self._append_result(result)
        if not result.safe:
            baseline = self._session.abort()
            self._proposed = None
            if baseline and self._worker.is_open():
                self._send_pid(baseline)
        if result.safe:
            self._set_status(self._tr.tr("ai_ready"), "#165DFF")
        else:
            self._set_status(self._tr.tr("ai_safety_abort"), "#F53F3F")
        if result.metrics.valid:
            self._toast(self._tr.tr("ai_trial_scored").format(
                score=result.metrics.score), result.safe)
        else:
            self._toast(result.metrics.reason, False)
        self._refresh_buttons()
        self._save_session()

    def _suggest(self) -> None:
        if not self._session:
            self._toast(self._tr.tr("ai_need_baseline"), False)
            return
        if len(self._session.history) >= self._session.config.max_trials:
            self._toast(self._tr.tr("ai_max_trials_reached"), False)
            return
        try:
            gains, reason = self._session.suggest()
        except RuntimeError as exc:
            self._toast(str(exc), False)
            return
        self._proposed = gains
        self._proposed_value.setText(gains.formatted())
        self._set_status(self._tr.tr("ai_proposal_ready"), "#722ED1")
        self._hint.setText(self._tr.tr("ai_proposal_reason").format(reason=reason))
        self._refresh_buttons()

    def _apply_proposed(self) -> None:
        if not self._require_connection() or not self._session or not self._proposed:
            return
        proposed = self._proposed
        if self._send_pid(proposed):
            self._session.start_capture(proposed)
            self._proposed = None
            self._begin_capture_ui()

    def _abort(self) -> None:
        if not self._session:
            return
        baseline = self._session.abort()
        self._proposed = None
        if baseline and self._worker.is_open():
            self._send_pid(baseline)
        self._set_status(self._tr.tr("ai_aborted"), "#F53F3F")
        self._hint.setText(self._tr.tr("ai_abort_hint"))
        self._refresh_buttons()

    def _send_pid(self, gains: PIDGains) -> bool:
        try:
            self._worker.write(f"PID:{gains.formatted()}\r\n".encode("utf-8"))
            if self.on_data_sent:
                self.on_data_sent()
            if self.on_pid_applied:
                self.on_pid_applied(gains)
            return True
        except Exception as exc:
            self._toast(str(exc), False)
            return False

    def ingest_line(self, line: str) -> None:
        parsed = _parse_pid_frame(line)
        if parsed is None or not self._session or not self._session.capturing:
            return
        safe, reason = self._session.ingest(*parsed)
        samples = self._session.samples
        if samples:
            t0 = samples[0].timestamp
            x = [sample.timestamp - t0 for sample in samples]
            self._sp_curve.setData(x, [sample.setpoint for sample in samples])
            self._pv_curve.setData(x, [sample.actual for sample in samples])
        if not safe:
            baseline = self._session.abort()
            if baseline and self._worker.is_open():
                self._send_pid(baseline)
            self._set_status(self._tr.tr("ai_safety_abort"), "#F53F3F")
            self._toast(reason, False)
            self._refresh_buttons()

    def _begin_capture_ui(self) -> None:
        self._capture_t0 = time.monotonic()
        self._sp_curve.setData([], [])
        self._pv_curve.setData([], [])
        self._set_status(self._tr.tr("ai_capturing"), "#00B42A")
        self._hint.setText(self._tr.tr("ai_step_hint"))
        self._refresh_buttons()

    def _update_capture_clock(self) -> None:
        if not self._session or not self._session.capturing:
            return
        elapsed = time.monotonic() - self._capture_t0
        remaining = max(0.0, self._session.config.capture_seconds - elapsed)
        self._status.setText(self._tr.tr("ai_capturing_time").format(seconds=remaining))
        if elapsed >= self._session.config.capture_seconds:
            self._finish_capture()

    def _append_result(self, result) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        m = result.metrics
        values = [
            str(result.index), result.gains.formatted(),
            f"{m.score:.2f}" if m.valid else "--",
            f"{m.rise_time:.3f}" if math.isfinite(m.rise_time) else "--",
            f"{m.settling_time:.3f}" if math.isfinite(m.settling_time) else "--",
            f"{m.overshoot_percent:.2f}%", f"{m.steady_state_error:.4g}",
            self._tr.tr("ai_safe") if result.safe else self._tr.tr("ai_unsafe"),
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 7:
                item.setForeground(QColor("#00B42A" if result.safe else "#F53F3F"))
            self._table.setItem(row, column, item)
        best = self._session.best_result() if self._session else None
        if best:
            self._best_value.setText(
                f"{best.gains.formatted()}  |  {best.metrics.score:.2f}")

    def _save_session(self) -> None:
        if not self._session or not self._session.baseline or not self._session.history:
            return
        base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        try:
            self._session_path = save_session(
                Path(base) / "tuning_sessions", self._session.baseline,
                self._session.config, self._session.history, self._session_path)
        except OSError:
            pass

    def _require_connection(self) -> bool:
        if not self._worker.is_open():
            self._toast(self._tr.tr("toast_pid_not_open"), False)
            return False
        return True

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected and self._session and self._session.capturing:
            self._session.abort()
            self._set_status(self._tr.tr("status_disconnected"), "#86909C")
        self._refresh_buttons()

    def restore_baseline(self) -> None:
        """Best-effort restoration before a deliberate disconnect or app exit."""
        if not self._session:
            return
        baseline = self._session.abort()
        if baseline and self._worker.is_open():
            self._send_pid(baseline)

    def _refresh_buttons(self) -> None:
        capturing = bool(self._session and self._session.capturing)
        valid_history = bool(self._session and self._session.best_result())
        self._baseline_btn.setEnabled(self._connected and not capturing)
        self._finish_btn.setEnabled(capturing)
        self._suggest_btn.setEnabled(not capturing and valid_history)
        self._apply_btn.setEnabled(
            self._connected and not capturing and self._proposed is not None)
        self._abort_btn.setEnabled(self._session is not None)

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(
            f"background:{color}18; color:{color}; border-radius:10px; padding:4px 10px;")

    def _toast(self, message: str, success: bool) -> None:
        if self.on_toast:
            self.on_toast(message, success)

    def retranslate(self) -> None:
        t = self._tr.tr
        self._title.setText(t("ai_title"))
        self._baseline_group.setTitle(t("ai_baseline_group"))
        self._search_group.setTitle(t("ai_search_group"))
        self._safety_group.setTitle(t("ai_safety_group"))
        for label in self.findChildren(QLabel):
            key = label.property("tr_key")
            if key:
                label.setText(t(f"ai_{key}"))
        cards = self.findChildren(QGroupBox)
        card_titles = [t("ai_baseline_card"), t("ai_proposed_card"), t("ai_best_card")]
        for box in cards:
            index = box.property("card_index")
            if index is not None:
                box.setTitle(card_titles[int(index)])
        self._load_manual_btn.setText(t("ai_load_manual"))
        self._baseline_btn.setText(t("ai_start_baseline"))
        self._finish_btn.setText(t("ai_finish_capture"))
        self._suggest_btn.setText(t("ai_suggest"))
        self._apply_btn.setText(t("ai_apply"))
        self._abort_btn.setText(t("ai_abort"))
        self._hint.setText(t("ai_initial_hint"))
        self._table.setHorizontalHeaderLabels([
            t("ai_col_trial"), t("ai_col_pid"), t("ai_col_score"),
            t("ai_col_rise"), t("ai_col_settling"), t("ai_col_overshoot"),
            t("ai_col_error"), t("ai_col_safety"),
        ])
        if not self._session or not self._session.capturing:
            self._set_status(t("ai_idle"), "#86909C")
        self._refresh_buttons()
