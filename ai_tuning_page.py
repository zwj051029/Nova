from __future__ import annotations

import math
import time
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QComboBox, QScrollArea, QMessageBox, QFileDialog, QDialog,
)

from i18n import Translator
from serial_worker import SerialWorker
from tuning.models import PIDGains, SafetyLimits, TuningConfig
from tuning.session import TuningSession
from tuning.storage import save_session, load_session, atomic_json, config_from_dict
from tuning.protocol import telemetry
from tuning.automatic import AutomaticTuner
from tuning.config_dialog import ConfigDialog
from tuning.reporting import explain, export_csv, export_html
from tuning.cloud_advisor import CloudAdvisorDialog
from theme import colors


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
        values = tuple(float(field) for field in fields[1:])
        return values if all(math.isfinite(value) for value in values) else None
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
        self._theme = "light"
        self._status_color = "#86909C"
        self._result_values: list[QLabel] = []
        self.on_toast = None
        self.on_data_sent = None
        self.on_pid_applied = None
        self.baseline_provider = None
        self._auto = None
        self._history_only = False
        self._profile_config = TuningConfig()
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
        self._config_panel = self._build_config_panel()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._config_panel)
        scroll.setMinimumWidth(320)
        splitter.addWidget(scroll)
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

        self._profile_btn = QPushButton("设备档案与独立范围 / Profile")
        self._profile_btn.clicked.connect(self._edit_profile)
        layout.addWidget(self._profile_btn)
        profile_actions = QHBoxLayout()
        save_profile = QPushButton("保存方案 / Save")
        load_profile = QPushButton("加载方案 / Load")
        self._save_profile_btn=save_profile
        self._load_profile_btn=load_profile
        save_profile.clicked.connect(self._save_profile)
        load_profile.clicked.connect(self._load_profile)
        demo_profile=QPushButton("模拟预设 / Demo")
        self._demo_profile_btn=demo_profile
        demo_profile.clicked.connect(self._demo_profile)
        profile_actions.addWidget(save_profile)
        profile_actions.addWidget(load_profile)
        profile_actions.addWidget(demo_profile)
        layout.addLayout(profile_actions)
        self._profile_summary = QLabel("Generic · PID · Channel 1")
        self._profile_summary.setWordWrap(True)
        layout.addWidget(self._profile_summary)

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
        self._gain_max.setToolTip("修改此处会覆盖三个参数上限；独立范围请使用设备档案。")
        self._gain_max.valueChanged.connect(self._uniform_max)
        self._relative_change = QSpinBox()
        self._relative_change.setRange(1, 100)
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

        automatic = QGridLayout()
        self._run_mode = QComboBox()
        self._run_mode.addItems(["每轮确认 / Confirm each trial", "受限自动 / Automatic"])
        self._auto_start = QPushButton("▶ 自动试验 / Start")
        self._auto_next = QPushButton("下一轮 / Confirm next")
        self._accept_best = QPushButton("接受最优 / Accept best")
        self._restore_original = QPushButton("恢复原参数 / Restore")
        self._auto_start.clicked.connect(self._start_automatic)
        self._auto_next.clicked.connect(lambda: self._auto.confirm_next() if self._auto else None)
        self._accept_best.clicked.connect(lambda: self._auto.decide(True) if self._auto else None)
        self._restore_original.clicked.connect(lambda: self._auto.decide(False) if self._auto else None)
        for col, widget in enumerate((self._run_mode, self._auto_start, self._auto_next)):
            automatic.addWidget(widget, 0, col)
        automatic.addWidget(self._accept_best, 1, 1)
        automatic.addWidget(self._restore_original, 1, 2)
        layout.addLayout(automatic)

        library = QHBoxLayout()
        self._history_btn = QPushButton("打开记录 / History")
        self._export_btn = QPushButton("导出报告 / Export")
        self._explain_btn = QPushButton("调参解释 / Insights")
        self._history_btn.clicked.connect(self._open_history)
        self._export_btn.clicked.connect(self._export_history)
        self._explain_btn.clicked.connect(self._show_insights)
        self._cloud_btn=QPushButton("云端解释 / Cloud")
        self._cloud_btn.clicked.connect(self._show_cloud_insights)
        for button in (self._history_btn,self._export_btn,self._explain_btn,self._cloud_btn):
            library.addWidget(button)
        layout.addLayout(library)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(
            "background:#FFF7E8; color:#7A4E00; border:1px solid #FFD591;"
            "border-radius:5px; padding:7px;")
        layout.addWidget(self._hint)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._sp_curve = self._plot.plot(pen=pg.mkPen("#2ECC71", width=2), name="Setpoint")
        self._pv_curve = self._plot.plot(pen=pg.mkPen("#E74C3C", width=2), name="Actual")
        self._baseline_curve = self._plot.plot(pen=pg.mkPen("#86909C", width=1, style=Qt.PenStyle.DashLine), name="Baseline")
        self._best_curve = self._plot.plot(pen=pg.mkPen("#9B71F5", width=2), name="Best")
        self._legend = self._plot.addLegend()
        for curve,name in ((self._sp_curve,"目标 / SP"),(self._pv_curve,"当前 / PV"),
                           (self._baseline_curve,"基准 / Baseline"),(self._best_curve,"最优 / Best")):
            self._legend.addItem(curve,name)
        self._plot.setLabel("bottom","Time / 时间",units="s")
        layout.addWidget(self._plot, 2)

        self._table = QTableWidget(0, 8)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._preview_trial)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
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
        spin.setDecimals(6)
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
        value.setWordWrap(True)
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet("font-family:Consolas; font-size:14px; color:#165DFF;")
        self._result_values.append(value)
        v.addWidget(value)
        layout.addWidget(box, 0, column)
        return value

    def _config(self) -> TuningConfig:
        return replace(self._profile_config,
            safety=replace(self._profile_config.safety,
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

    def _uniform_max(self, value):
        self._profile_config.gain_max = PIDGains(value,value,value)

    def _demo_profile(self):
        self._apply_config(TuningConfig(device_name="Nova simulated plant",sample_period_seconds=.02,
            capture_seconds=4,max_trials=5,gain_max=PIDGains(5,2,.2),
            safety=SafetyLimits(actual_min=-2,actual_max=2,output_abs_max=10)))
        for spin,value in zip((self._kp,self._ki,self._kd),(1,.5,0)):
            spin.setValue(value)
        self._hint.setText("模拟预设已加载（未发送指令）。请选择 sim:// 串口，再开始自动试验。")

    def _apply_config(self, config):
        self._profile_config = config
        self._gain_max.blockSignals(True)
        self._gain_max.setValue(max(config.gain_max.as_array()))
        self._gain_max.blockSignals(False)
        self._relative_change.setValue(round(config.safety.max_relative_gain_change*100))
        self._max_trials.setValue(config.max_trials)
        self._capture_seconds.setValue(config.capture_seconds)
        self._sample_period_ms.setValue(config.sample_period_seconds*1000)
        self._actual_min.setValue(config.safety.actual_min)
        self._actual_max.setValue(config.safety.actual_max)
        self._output_max.setValue(config.safety.output_abs_max)
        self._overshoot_max.setValue(config.safety.max_overshoot_percent)
        self._profile_summary.setText(f"{config.device_name} · {config.mode} · CH {config.channel}\n"
            f"{config.initial_target:g} → {config.step_target:g} {config.unit}\n"
            f"Max: {config.gain_max.formatted()}")
        if config.mode == "P":
            self._ki.setValue(0)
        if config.mode in ("P","PI"):
            self._kd.setValue(0)

    def _edit_profile(self):
        dialog=ConfigDialog(self._config(),self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_config(dialog.result_config())

    def _save_profile(self):
        filename,_=QFileDialog.getSaveFileName(self,"保存参数方案", "nova_profile.json", "JSON (*.json)")
        if not filename:
            return
        try:
            config=self._config()
            config.validate()
            atomic_json(Path(filename),{"schema_version":1,"config":asdict(config),"gains":asdict(self._gains_from_inputs())})
            self._toast("方案已保存（未下发设备）",True)
        except (ValueError,OSError) as exc:
            self._toast(str(exc),False)

    def _load_profile(self):
        filename,_=QFileDialog.getOpenFileName(self,"加载参数方案","","JSON (*.json)")
        if not filename:
            return
        try:
            data=json.loads(Path(filename).read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise ValueError("不支持的档案版本")
            config=config_from_dict(data["config"])
            gains=PIDGains(**data["gains"])
            if not all(math.isfinite(v) and 0<=v<=1e6 for v in gains.as_array()):
                raise ValueError("档案参数无效")
            self._apply_config(config)
            for spin,value in zip((self._kp,self._ki,self._kd),gains.as_array()):
                spin.setValue(value)
            self._toast("方案已加载；未发送任何设备命令",True)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            self._toast(str(exc),False)

    def _open_history(self):
        base=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        filename,_=QFileDialog.getOpenFileName(self,"打开历史（只读回放）",str(Path(base)/"tuning_sessions"),"JSON (*.json)")
        if not filename:
            return
        try:
            baseline,config,history=load_session(Path(filename))
            self._auto=None
            self._proposed=None
            self._session=TuningSession(config)
            self._session.set_baseline(baseline)
            self._session.history=history
            self._history_only=True
            self._session_path=Path(filename)
            self._table.setRowCount(0)
            self._baseline_value.setText(baseline.formatted())
            self._best_value.setText("--")
            for result in history:
                self._append_result(result)
            if history:
                self._table.selectRow(0)
            self._hint.setText("历史只读回放：未修改设备参数。可选择不同试验、查看解释或导出报告。")
            self._set_status("History / 只读", "#86909C")
            self._refresh_buttons()
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self._toast(str(exc),False)

    def _export_history(self):
        if not self._session or not self._session.history:
            return
        filename,kind=QFileDialog.getSaveFileName(self,"导出试验","nova_report.html",
            "HTML report (*.html);;CSV telemetry (*.csv);;JSON session (*.json)")
        if not filename:
            return
        try:
            path=Path(filename)
            if "CSV" in kind:
                export_csv(path,self._session.history)
            elif "JSON" in kind:
                save_session(path.parent,self._session.baseline,self._session.config,self._session.history,path)
            else:
                export_html(path,self._session.history,self._session.config)
            self._toast("报告已导出",True)
        except (OSError,ValueError) as exc:
            self._toast(str(exc),False)

    def _show_insights(self):
        if self._session:
            QMessageBox.information(self,"调参解释 / Local insights",explain(self._session.history,self._session.config))

    def _show_cloud_insights(self):
        if self._session:
            CloudAdvisorDialog(self._session.history,self._session.config,self).exec()

    def _gains_from_inputs(self) -> PIDGains:
        return PIDGains(self._kp.value(), self._ki.value(), self._kd.value())

    def _start_automatic(self, checked=False, confirmed=False) -> None:
        if not self._require_connection() or self._worker.owner:
            return
        config = self._config()
        if not confirmed:
            answer = QMessageBox.warning(self, "自动调参安全确认 / Safety",
                f"设备将执行 {config.initial_target:g} → {config.step_target:g} 阶跃。\n"
                "请确认机械行程、负载、输出限制、独立急停和设备看门狗。\n"
                "试验结束/异常将停止输出，不会自动恢复运动。\n"
                "仅支持 Nova v2 协议；建议先使用 sim://。",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Ok:
                return
        try:
            self._worker.acquire("ai")
            self._auto = AutomaticTuner(config, lambda data: self._worker.write(data, owner="ai"),
                on_result=self._auto_result, on_status=self._auto_status, on_applied=self.on_pid_applied)
            self._session = self._auto.session
            self._proposed=None
            self._history_only = False
            self._session_path = None
            self._table.setRowCount(0)
            self._auto.start(self._gains_from_inputs(), self._run_mode.currentIndex() == 1)
            self._baseline_value.setText(self._session.baseline.formatted())
            self._best_value.setText("--")
        except (ValueError, RuntimeError) as exc:
            self._worker.release("ai")
            self._toast(str(exc), False)
        self._refresh_buttons()

    def _auto_result(self, result) -> None:
        self._append_result(result)
        self._save_session()

    def _auto_status(self, state, message) -> None:
        self._set_status(state, "#F53F3F" if state in ("aborted", "stopping") else "#165DFF")
        self._hint.setText(message)
        if self._auto and self._auto.next_gains:
            self._proposed_value.setText(self._auto.next_gains.formatted())
        if state in AutomaticTuner.TERMINAL:
            self._worker.release("ai")
            self._save_session()
        self._refresh_buttons()

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
        try:
            config.validate()
        except ValueError as exc:
            self._toast(str(exc), False)
            return
        if config.safety.actual_min >= config.safety.actual_max:
            self._toast(self._tr.tr("ai_invalid_actual_range"), False)
            return
        gains = self._gains_from_inputs()
        if any(value > self._gain_max.value() for value in gains.as_array()):
            self._toast(self._tr.tr("ai_invalid_baseline"), False)
            return
        self._session = TuningSession(config)
        self._auto = None
        self._history_only = False
        self._session.set_baseline(gains)
        self._proposed = None
        self._session_path = None
        self._baseline_value.setText(gains.formatted())
        self._best_value.setText("--")
        self._proposed_value.setText("--")
        self._table.setRowCount(0)
        if self._send_pid(gains):
            self._worker.acquire("ai")
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
        self._worker.release("ai")

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
            self._worker.acquire("ai")
            self._session.start_capture(proposed)
            self._proposed = None
            self._begin_capture_ui()

    def _abort(self) -> None:
        if self._auto and self._auto.active:
            self._auto.stop()
            return
        if not self._session:
            return
        if self._history_only or (self._auto and not self._auto.active):
            return
        baseline = self._session.abort()
        self._proposed = None
        if baseline and self._worker.is_open():
            self._send_pid(baseline)
        self._set_status(self._tr.tr("ai_aborted"), "#F53F3F")
        self._hint.setText(self._tr.tr("ai_abort_hint"))
        self._refresh_buttons()
        self._worker.release("ai")

    def _send_pid(self, gains: PIDGains) -> bool:
        try:
            self._worker.write(f"PID:{gains.formatted()}\r\n".encode("utf-8"), owner="ai")
            if self.on_data_sent:
                self.on_data_sent()
            if self.on_pid_applied:
                self.on_pid_applied(gains)
            return True
        except Exception as exc:
            self._toast(str(exc), False)
            return False

    def ingest_line(self, line: str) -> None:
        if self._auto and self._auto.active:
            self._auto.handle_line(line)
            return
        frame = telemetry(line)
        if frame is None or not self._session or not self._session.capturing or frame.channel != self._session.config.channel:
            return
        safe, reason = self._session.ingest(frame.setpoint, frame.actual, frame.output, frame.timestamp, frame.sequence)
        if not safe:
            result = self._session.record_failure(reason)
            self._append_result(result)
            self._save_session()
            baseline = self._session.abort()
            if baseline and self._worker.is_open():
                self._send_pid(baseline)
            self._set_status(self._tr.tr("ai_safety_abort"), "#F53F3F")
            self._toast(reason, False)
            self._refresh_buttons()
            self._worker.release("ai")

    def refresh_plot(self) -> None:
        samples = self._session.samples if self._session else []
        if samples:
            stride = max(1, len(samples) // 2000)
            visible = samples[::stride]
            self._sp_curve.setData([s.timestamp for s in visible], [s.setpoint for s in visible])
            self._pv_curve.setData([s.timestamp for s in visible], [s.actual for s in visible])

    def _preview_trial(self) -> None:
        if not self._session or self._session.capturing:
            return
        row = self._table.currentRow()
        if 0 <= row < len(self._session.history):
            samples = self._session.history[row].samples
            self._sp_curve.setData([s.timestamp for s in samples], [s.setpoint for s in samples])
            self._pv_curve.setData([s.timestamp for s in samples], [s.actual for s in samples])

    def _begin_capture_ui(self) -> None:
        self._capture_t0 = time.monotonic()
        self._sp_curve.setData([], [])
        self._pv_curve.setData([], [])
        self._set_status(self._tr.tr("ai_capturing"), "#00B42A")
        self._hint.setText(self._tr.tr("ai_step_hint"))
        self._refresh_buttons()

    def _update_capture_clock(self) -> None:
        if self._auto and self._auto.active:
            self._auto.tick()
            self.refresh_plot()
            return
        if not self._session or not self._session.capturing:
            return
        elapsed = time.monotonic() - self._capture_t0
        if time.monotonic() - self._session.last_received_at > self._session.config.safety.telemetry_timeout:
            self._append_result(self._session.record_failure("遥测超时"))
            self._save_session()
            self._abort()
            self._toast("遥测超时：已请求恢复基准，设备是否生效未经确认", False)
            return
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
                c = colors(self._theme)
                item.setForeground(QColor(c["success"] if result.safe else c["danger"]))
            self._table.setItem(row, column, item)
        best = self._session.best_result() if self._session else None
        if best:
            self._best_value.setText(
                f"{best.gains.formatted()}  |  {best.metrics.score:.2f}")
            self._best_curve.setData([s.timestamp for s in best.samples], [s.actual for s in best.samples])
        baseline = next((r for r in self._session.history if r.is_baseline), None)
        if baseline:
            self._baseline_curve.setData([s.timestamp for s in baseline.samples], [s.actual for s in baseline.samples])

    def _save_session(self) -> None:
        if not self._session or not self._session.baseline or (not self._session.history and not self._auto) or self._history_only:
            return
        base = os.environ.get("NOVA_DATA_DIR") or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        try:
            self._session_path = save_session(
                Path(base) / "tuning_sessions", self._session.baseline,
                self._session.config, self._session.history, self._session_path,
                metadata={"state":self._auto.state,"message":self._auto.message,
                          "original":asdict(self._auto.original) if self._auto.original else None,
                          "verified_trial":self._auto.verified.index if self._auto.verified else None,
                          "events":self._auto.events} if self._auto else None)
        except OSError as exc:
            self._toast(f"保存失败: {exc}", False)

    def _require_connection(self) -> bool:
        if not self._worker.is_open():
            self._toast(self._tr.tr("toast_pid_not_open"), False)
            return False
        return True

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected and self._auto and self._auto.active:
            self._auto.fail("串口断开")
        if not connected and self._session and self._session.capturing:
            self._append_result(self._session.record_failure("串口断开"))
            self._save_session()
            self._session.abort()
            self._set_status(self._tr.tr("status_disconnected"), "#86909C")
        self._refresh_buttons()

    def restore_baseline(self) -> None:
        """Best-effort restoration before a deliberate disconnect or app exit."""
        if self._auto and self._auto.active:
            self._auto.stop()
            return
        if not self._session or not self._session.capturing:
            return
        baseline = self._session.abort()
        if baseline and self._worker.is_open():
            self._send_pid(baseline)
        self._worker.release("ai")

    def _refresh_buttons(self) -> None:
        capturing = bool(self._session and self._session.capturing)
        active = bool(self._auto and self._auto.active)
        self._auto_start.setEnabled(self._connected and not capturing and not active)
        self._auto_next.setEnabled(active and self._auto.state == "awaiting_confirmation")
        self._accept_best.setEnabled(active and self._auto.state == "review")
        self._restore_original.setEnabled(active and self._auto.state == "review")
        self._run_mode.setEnabled(not active and not capturing)
        if hasattr(self, "_config_panel"):
            self._config_panel.setEnabled(not active and not capturing)
        valid_history = bool(self._session and self._session.best_result())
        self._history_btn.setEnabled(not active and not capturing)
        self._export_btn.setEnabled(bool(self._session and self._session.history) and not active and not capturing)
        self._explain_btn.setEnabled(bool(self._session and self._session.history) and not active and not capturing)
        self._cloud_btn.setEnabled(bool(self._session and self._session.history) and not active and not capturing)
        self._baseline_btn.setEnabled(self._connected and not capturing and not active)
        self._finish_btn.setEnabled(capturing and not active)
        self._suggest_btn.setEnabled(not capturing and valid_history and self._auto is None and not self._history_only)
        self._apply_btn.setEnabled(
            self._connected and not capturing and self._proposed is not None and self._auto is None and not self._history_only)
        self._abort_btn.setEnabled(active or (self._session is not None and self._auto is None and not self._history_only))
        self._abort_btn.setText("停止试验 / STOP" if self._auto else self._tr.tr("ai_abort"))

    def _set_status(self, text: str, color: str) -> None:
        self._status_color = color
        self._status.setText(text)
        self._apply_status_style()

    def _apply_status_style(self) -> None:
        c = colors(self._theme)
        semantic = {
            "#165DFF": "accent", "#F53F3F": "danger", "#00B42A": "success",
            "#722ED1": "purple", "#86909C": "muted",
        }
        status_color = c.get(semantic.get(self._status_color, "muted"), self._status_color)
        self._status.setStyleSheet(
            f"background:{c['surface_alt']}; color:{status_color};"
            f"border:1px solid {status_color}; border-radius:10px; padding:3px 9px;")

    def apply_theme(self, theme: str) -> None:
        self._theme = theme
        c = colors(theme)
        self._title.setStyleSheet(f"font-size:18px; font-weight:bold; color:{c['text']};")
        self._apply_status_style()
        primary = f"""
            QPushButton {{ background:{c['accent']}; color:white; border:none; border-radius:5px;
            padding:7px 12px; font-weight:bold; }}
            QPushButton:hover {{ background:{c['accent_hover']}; }}
            QPushButton:disabled {{ background:{c['surface_alt']}; color:{c['disabled']}; }}
        """
        secondary = f"""
            QPushButton {{ background:{c['accent_soft']}; color:{c['accent']};
            border:1px solid {c['accent_border']}; border-radius:5px; padding:7px 10px; font-weight:bold; }}
            QPushButton:hover {{ background:{c['hover']}; border-color:{c['accent']}; }}
            QPushButton:disabled {{ background:{c['surface_alt']}; color:{c['disabled']}; border-color:{c['border']}; }}
        """
        danger = f"""
            QPushButton {{ background:{c['danger']}; color:white; border:none; border-radius:5px;
            padding:8px 12px; font-weight:bold; }}
            QPushButton:hover {{ background:#CB2634; }}
            QPushButton:disabled {{ background:{c['surface_alt']}; color:{c['disabled']}; }}
        """
        self._baseline_btn.setStyleSheet(primary)
        self._apply_btn.setStyleSheet(primary)
        self._finish_btn.setStyleSheet(secondary)
        self._suggest_btn.setStyleSheet(secondary)
        self._load_manual_btn.setStyleSheet(secondary)
        self._abort_btn.setStyleSheet(danger)
        for button in (self._auto_start, self._auto_next, self._accept_best, self._restore_original):
            button.setStyleSheet(secondary)
        self._hint.setStyleSheet(
            f"background:{c['warning_bg']}; color:{c['warning_text']};"
            f"border:1px solid {c['warning_border']}; border-radius:5px; padding:7px;")
        for value in self._result_values:
            value.setStyleSheet(
                f"font-family:Consolas; font-size:14px; color:{c['accent']};")
        self._plot.setBackground(c["plot"])
        for axis_name in ("left", "bottom"):
            axis = self._plot.getAxis(axis_name)
            axis.setPen(pg.mkPen(c["border_strong"]))
            axis.setTextPen(pg.mkPen(c["text_secondary"]))
        if hasattr(self._legend, "setLabelTextColor"):
            self._legend.setLabelTextColor(c["text"])
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 7)
            if item:
                item.setForeground(QColor(c["success"] if item.text() == self._tr.tr("ai_safe") else c["danger"]))

    def _toast(self, message: str, success: bool) -> None:
        if self.on_toast:
            self.on_toast(message, success)

    def retranslate(self) -> None:
        t = self._tr.tr
        self._save_profile_btn.setText("保存方案" if self._tr.lang=="zh" else "Save")
        self._load_profile_btn.setText("加载方案" if self._tr.lang=="zh" else "Load")
        self._demo_profile_btn.setText("模拟预设" if self._tr.lang=="zh" else "Demo")
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
        if self._auto and self._auto.active:
            self._hint.setText(self._auto.message)
        elif not self._session:
            self._hint.setText(t("ai_initial_hint"))
        self._table.setHorizontalHeaderLabels([
            t("ai_col_trial"), t("ai_col_pid"), t("ai_col_score"),
            t("ai_col_rise"), t("ai_col_settling"), t("ai_col_overshoot"),
            t("ai_col_error"), t("ai_col_safety"),
        ])
        if not self._session:
            self._set_status(t("ai_idle"), "#86909C")
        self._refresh_buttons()
