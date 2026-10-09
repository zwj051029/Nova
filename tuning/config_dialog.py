from dataclasses import replace
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QGridLayout, QLabel, QLineEdit,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QDialogButtonBox, QMessageBox, QTabWidget, QWidget)
from .models import PIDGains


class ConfigDialog(QDialog):
    """Device profile editor: all gain scales are explicit and independent."""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config=config
        self.setWindowTitle("设备档案 / Device profile")
        self.resize(740,600)
        root=QVBoxLayout(self)
        tabs=QTabWidget()
        root.addWidget(tabs)
        general=QWidget()
        form=QFormLayout(general)
        self.name=QLineEdit(config.device_name)
        self.unit=QLineEdit(config.unit)
        self.mode=QComboBox()
        self.mode.addItems(["P","PI","PID"])
        self.mode.setCurrentText(config.mode)
        self.channel=QSpinBox()
        self.channel.setRange(0,65535)
        self.channel.setValue(config.channel)
        form.addRow("名称 / Name",self.name)
        form.addRow("单位 / Unit",self.unit)
        form.addRow("模式 / Mode",self.mode)
        form.addRow("通道 / Channel",self.channel)
        form.addRow("算法 / Algorithm",QLabel(config.algorithm))
        self.fields={}
        entries=[("sample_period_seconds","设备周期 / Period (s)",.00001,10,6),
                 ("initial_target","初始目标 / Initial",-1e6,1e6,6),
                 ("step_target","阶跃目标 / Step",-1e6,1e6,6),
                 ("pre_seconds","阶跃前采集 / Prefill (s)",.1,60,2),
                 ("capture_seconds","阶跃后采集 / Capture (s)",2,600,2),
                 ("stable_tolerance","初始稳定容差 / Tolerance",1e-6,1e6,6),
                 ("stable_seconds","初始稳定保持 / Hold (s)",.1,60,2),
                 ("stability_timeout","稳定等待上限 / Timeout (s)",1,600,2),
                 ("settling_hold_seconds","评分稳定保持 / Score hold (s)",.1,60,2),
                 ("target_score","目标评分 / Target score",0,1e6,3)]
        for key,label,low,high,digits in entries:
            spin=self.spin(getattr(config,key),low,high,digits)
            form.addRow(label,spin)
            self.fields[key]=spin
        self.patience=QSpinBox()
        self.patience.setRange(1,100)
        self.patience.setValue(config.patience)
        form.addRow("无改善停止轮数 / Patience",self.patience)
        tabs.addTab(general,"试验 / Trial")
        gains=QWidget()
        grid=QGridLayout(gains)
        for column,label in enumerate(["参数","下限 Min","上限 Max","分辨率","零附近最大步长","锁定"]):
            grid.addWidget(QLabel(label),0,column)
        self.gains=[]
        for i,name in enumerate(("Kp","Ki","Kd")):
            grid.addWidget(QLabel(name),i+1,0)
            row=[]
            for col,value in enumerate((config.gain_min.as_array()[i],config.gain_max.as_array()[i],
                    config.gain_resolution.as_array()[i],config.safety.max_absolute_gain_change.as_array()[i])):
                spin=self.spin(value,1e-6 if col==2 else 0,1e6,6)
                spin.setMinimumWidth(125)
                grid.addWidget(spin,i+1,col+1)
                row.append(spin)
            lock=QCheckBox()
            lock.setChecked(config.locked[i])
            grid.addWidget(lock,i+1,5)
            row.append(lock)
            self.gains.append(row)
        note=QLabel("允许变化量 = max(|当前参数| × 相对比例, 零附近最大步长)。\n请按实际设备填写小参数尺度；锁定参数不会参与搜索。")
        note.setWordWrap(True)
        grid.addWidget(note,4,0,1,6)
        grid.setRowStretch(5,1)
        tabs.addTab(gains,"参数尺度 / Gain scales")
        safety=QWidget()
        safeform=QFormLayout(safety)
        self.safety={}
        for key,label,lo,hi in [("actual_min","实际值下限 / PV min",-1e9,1e9),
            ("actual_max","实际值上限 / PV max",-1e9,1e9),
            ("output_abs_max","输出绝对上限 / Output limit",.000001,1e9),
            ("max_overshoot_percent","最大超调 %",0,500),
            ("max_relative_gain_change","相对增益变化 0–1",.01,1),
            ("telemetry_timeout","遥测超时 / Telemetry timeout (s)",.2,10),
            ("saturation_seconds","饱和持续上限 / Saturation (s)",.1,60)]:
            spin=self.spin(getattr(config.safety,key),lo,hi,6)
            safeform.addRow(label,spin)
            self.safety[key]=spin
        tabs.addTab(safety,"保护 / Safety")
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def spin(value,low,high,digits):
        spin=QDoubleSpinBox()
        spin.setDecimals(digits)
        spin.setRange(low,high)
        spin.setValue(value)
        return spin

    def result_config(self):
        safety=replace(self.config.safety,**{key:spin.value() for key,spin in self.safety.items()},
                       max_absolute_gain_change=PIDGains(*(row[3].value() for row in self.gains)))
        return replace(self.config,**{key:spin.value() for key,spin in self.fields.items()},
            device_name=self.name.text().strip() or "Generic",unit=self.unit.text().strip(),
            mode=self.mode.currentText(),channel=self.channel.value(),safety=safety,patience=self.patience.value(),
            gain_min=PIDGains(*(row[0].value() for row in self.gains)),
            gain_max=PIDGains(*(row[1].value() for row in self.gains)),
            gain_resolution=PIDGains(*(row[2].value() for row in self.gains)),
            locked=tuple(row[4].isChecked() for row in self.gains))

    def validate_accept(self):
        try:
            self.result_config().validate()
        except ValueError as exc:
            QMessageBox.warning(self,"配置无效 / Invalid",str(exc))
            return
        self.accept()
