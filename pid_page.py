import collections
import platform
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QGroupBox,
    QSlider, QDoubleSpinBox, QGridLayout, QSplitter,
    QAbstractSpinBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from i18n import Translator
from serial_worker import SerialWorker

BUFFER_SIZE = 500

BTN_SEND_STYLE = """
QPushButton {
    background-color: #165DFF;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #0E4BD7; }
QPushButton:pressed { background-color: #0A3AB0; }
QPushButton:disabled { background-color: #C9CDD4; color: #86909C; }
"""

BTN_PRECISION_STYLE = """
QLabel {
    background-color: #F7FAFF;
    color: #165DFF;
    border: 1px solid #B7D1FF;
    border-radius: 3px;
    padding: 2px 3px;
    font-size: 11px;
    font-weight: bold;
}
"""

BTN_PRECISION_ICON_STYLE = """
QPushButton {
    background-color: #EEF4FF;
    color: #165DFF;
    border: 1px solid #B7D1FF;
    border-radius: 4px;
    padding: 0;
    font-size: 15px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #DCE9FF; border-color: #165DFF; }
QPushButton:pressed { background-color: #C7DCFF; }
QPushButton:disabled { background-color: #F2F3F5; color: #86909C; border-color: #E5E8EB; }
"""

BTN_SEND_ALL_STYLE = """
QPushButton {
    background-color: #165DFF;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    font-size: 14px;
    font-weight: bold;
    min-height: 38px;
}
QPushButton:hover   { background-color: #0E4BD7; }
QPushButton:pressed { background-color: #0A3AB0; }
QPushButton:disabled { background-color: #C9CDD4; color: #86909C; }
"""


def _system_font() -> str:
    if platform.system() == "Windows":
        return "Segoe UI"
    if platform.system() == "Darwin":
        return "SF Pro Display"
    return "sans-serif"


def parse_line(line: str) -> tuple[int, float, float, float] | None:
    if not line.startswith(">"):
        return None
    try:
        parts = line[1:].split(",")
        if len(parts) != 4:
            return None
        return int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    except ValueError:
        return None


class PrecisionSpinBox(QDoubleSpinBox):
    """内部保留 6 位输入能力，界面按当前选择的精度显示。"""

    def __init__(self, parent=None):
        self._display_decimals = 2
        super().__init__(parent)
        # Qt 会用 decimals 限制键盘输入，因此内部始终允许到 6 位。
        super().setDecimals(6)

    def set_display_decimals(self, decimals: int, refresh_text: bool = True) -> None:
        self._display_decimals = max(2, min(6, decimals))
        if refresh_text:
            self.lineEdit().setText(self.textFromValue(self.value()))

    def textFromValue(self, value: float) -> str:
        return self.locale().toString(value, "f", self._display_decimals)


class PidRow:
    def __init__(self, name: str, labels_grid: QGridLayout, spinboxes_grid: QGridLayout,
                 right_grid: QGridLayout, row: int):
        self.name = name
        self._syncing = False
        self._edit_sync_pending = False
        self._decimals = 2

        # 标签
        self._label = QLabel(name)
        labels_grid.addWidget(self._label, row, 0)

        # 数值框
        self.spinbox = PrecisionSpinBox()
        self.spinbox.setRange(0.0, 100.0)
        self.spinbox.setSingleStep(10 ** -self._decimals)
        self.spinbox.set_display_decimals(self._decimals)
        self.spinbox.setValue(0.0)
        self.spinbox.setFixedWidth(146)
        self.spinbox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spinboxes_grid.addWidget(self.spinbox, row, 0)

        # 右侧：滑块 + 精度加减控件 + 发送按钮
        right_row = QWidget()
        right_hbox = QHBoxLayout(right_row)
        right_hbox.setContentsMargins(0, 0, 0, 0)
        right_hbox.setSpacing(4)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self._update_slider_range()
        self.slider.setValue(0)
        precision_controls = QWidget()
        precision_layout = QHBoxLayout(precision_controls)
        precision_layout.setContentsMargins(0, 0, 0, 0)
        precision_layout.setSpacing(2)
        self.precision_decrease_btn = QPushButton("−")
        self.precision_label = QLabel()
        self.precision_increase_btn = QPushButton("+")
        for btn in (self.precision_decrease_btn, self.precision_increase_btn):
            btn.setFixedSize(24, 26)
            btn.setStyleSheet(BTN_PRECISION_ICON_STYLE)
        self.precision_label.setFixedSize(30, 26)
        self.precision_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.precision_label.setStyleSheet(BTN_PRECISION_STYLE)
        precision_layout.addWidget(self.precision_decrease_btn)
        precision_layout.addWidget(self.precision_label)
        precision_layout.addWidget(self.precision_increase_btn)
        self.send_btn = QPushButton()
        self.send_btn.setFixedWidth(52)
        self.send_btn.setStyleSheet(BTN_SEND_STYLE)
        right_hbox.addWidget(self.slider, stretch=1)
        right_hbox.addWidget(precision_controls)
        right_hbox.addWidget(self.send_btn)
        right_grid.addWidget(right_row, row, 0)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spinbox.valueChanged.connect(self._spinbox_changed)
        self.spinbox.lineEdit().textEdited.connect(self._on_text_edited)
        self.precision_decrease_btn.clicked.connect(self._decrease_decimals)
        self.precision_increase_btn.clicked.connect(self._increase_decimals)

    def value(self) -> float:
        return self.spinbox.value()

    def formatted_value(self) -> str:
        return f"{self.value():.{self._decimals}f}"

    def retranslate(self, t) -> None:
        self.send_btn.setText(t("send_param_btn"))
        self.precision_label.setText(t("decimal_places_btn").format(n=self._decimals))
        tooltip = t("decimal_places_tooltip")
        self.precision_label.setToolTip(tooltip)
        self.precision_decrease_btn.setToolTip(t("decimal_places_decrease_tooltip"))
        self.precision_increase_btn.setToolTip(tooltip)
        self.precision_decrease_btn.setEnabled(self._decimals > 2)
        self.precision_increase_btn.setEnabled(self._decimals < 6)

    def _update_slider_range(self) -> None:
        self.slider.setRange(0, 100 * (10 ** self._decimals))

    def _increase_decimals(self) -> None:
        self._set_decimals(self._decimals + 1)

    def _decrease_decimals(self) -> None:
        self._set_decimals(self._decimals - 1)

    def _set_decimals(self, decimals: int, value: float | None = None,
                      preserve_editor_text: bool = False) -> None:
        decimals = max(2, min(6, decimals))
        if decimals == self._decimals:
            return
        if value is None:
            value = self.spinbox.value()
        self._syncing = True
        self._decimals = decimals
        self.spinbox.set_display_decimals(
            self._decimals, refresh_text=not preserve_editor_text)
        self.spinbox.setSingleStep(10 ** -self._decimals)
        self._update_slider_range()
        if not preserve_editor_text:
            self.spinbox.setValue(value)
        self.slider.setValue(round(value * (10 ** self._decimals)))
        self._syncing = False
        self.retranslate(Translator().tr)
        self.precision_decrease_btn.setEnabled(self._decimals > 2)
        self.precision_increase_btn.setEnabled(self._decimals < 6)

    def _on_text_edited(self, text: str) -> None:
        """用户直接输入或删减小数位时，同步精度显示与滑块刻度。"""
        if self._edit_sync_pending:
            return
        self._edit_sync_pending = True
        # 等本次按键由 QDoubleSpinBox 完整解析后再调整精度，避免输入被重排。
        QTimer.singleShot(0, self._sync_decimals_from_editor)

    def _sync_decimals_from_editor(self) -> None:
        self._edit_sync_pending = False
        text = self.spinbox.lineEdit().text()
        decimal_point = self.spinbox.locale().decimalPoint()
        if decimal_point not in text:
            return
        fraction = text.rsplit(decimal_point, 1)[1]
        if not fraction.isdigit():
            return
        decimals = max(2, min(6, len(fraction)))
        if decimals == self._decimals:
            return
        value, ok = self.spinbox.locale().toDouble(text)
        if ok:
            # 不重写正在编辑的文本，否则全选后重新输入时会打断后续按键。
            self._set_decimals(decimals, value, preserve_editor_text=True)

    def _slider_changed(self, v: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.spinbox.setValue(v / (10 ** self._decimals))
        self._syncing = False

    def _spinbox_changed(self, v: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.slider.setValue(round(v * (10 ** self._decimals)))
        self._syncing = False


class PidPage(QWidget):
    """页面2：波形图（左右布局，左侧 PID 面板，右侧波形）。"""

    def __init__(self, worker: SerialWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._tr = Translator()
        self._buf_setpoint: collections.deque[float] = collections.deque(maxlen=BUFFER_SIZE)
        self._buf_actual: collections.deque[float] = collections.deque(maxlen=BUFFER_SIZE)
        self.on_toast = None
        self._tr.on_change(self.retranslate)
        self._build_ui()
        self.retranslate()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 面板与波形图之间可拖拽
        page_splitter = QSplitter(Qt.Orientation.Horizontal)
        page_splitter.setHandleWidth(4)
        page_splitter.addWidget(self._build_pid_panel())
        page_splitter.addWidget(self._build_plot_widget())
        page_splitter.setStretchFactor(0, 0)
        page_splitter.setStretchFactor(1, 1)
        page_splitter.setSizes([450, 790])
        layout.addWidget(page_splitter)

    def _build_pid_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(430)
        panel.setStyleSheet(
            "background: #FAFBFC;"
            "border-right: 1px solid #E5E8EB;"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._pid_group_box = QGroupBox()
        group_layout = QVBoxLayout(self._pid_group_box)
        group_layout.setContentsMargins(8, 14, 8, 8)
        group_layout.setSpacing(8)

        # ---- 外层分隔条：(标签+数值) | (滑块+按钮) ----
        outer_splitter = QSplitter(Qt.Orientation.Horizontal)
        outer_splitter.setHandleWidth(4)

        # 左侧区域：标签 + 数值（内部也可拖拽）
        inner_splitter = QSplitter(Qt.Orientation.Horizontal)
        inner_splitter.setHandleWidth(4)

        labels_widget = QWidget()
        labels_grid = QGridLayout(labels_widget)
        labels_grid.setSpacing(8)
        labels_grid.setContentsMargins(4, 0, 0, 0)

        spinboxes_widget = QWidget()
        spinboxes_grid = QGridLayout(spinboxes_widget)
        spinboxes_grid.setSpacing(8)
        spinboxes_grid.setContentsMargins(0, 0, 0, 0)

        inner_splitter.addWidget(labels_widget)
        inner_splitter.addWidget(spinboxes_widget)
        inner_splitter.setStretchFactor(0, 0)
        inner_splitter.setStretchFactor(1, 0)
        inner_splitter.setSizes([36, 146])

        # 右侧区域：滑块 + 发送按钮
        right_widget = QWidget()
        right_grid = QGridLayout(right_widget)
        right_grid.setSpacing(8)
        right_grid.setContentsMargins(0, 0, 4, 0)
        right_grid.setColumnStretch(0, 1)

        outer_splitter.addWidget(inner_splitter)
        outer_splitter.addWidget(right_widget)
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        outer_splitter.setSizes([196, 216])
        group_layout.addWidget(outer_splitter)

        self._pid_kp = PidRow("Kp", labels_grid, spinboxes_grid, right_grid, 0)
        self._pid_ki = PidRow("Ki", labels_grid, spinboxes_grid, right_grid, 1)
        self._pid_kd = PidRow("Kd", labels_grid, spinboxes_grid, right_grid, 2)

        self._pid_kp.send_btn.clicked.connect(lambda: self._send_single(self._pid_kp))
        self._pid_ki.send_btn.clicked.connect(lambda: self._send_single(self._pid_ki))
        self._pid_kd.send_btn.clicked.connect(lambda: self._send_single(self._pid_kd))

        self._send_all_btn = QPushButton()
        self._send_all_btn.setStyleSheet(BTN_SEND_ALL_STYLE)
        self._send_all_btn.clicked.connect(self._send_all)
        group_layout.addWidget(self._send_all_btn)

        v.addWidget(self._pid_group_box)
        v.addStretch()
        return panel

    def _build_plot_widget(self) -> pg.PlotWidget:
        pw = pg.PlotWidget()
        pw.setBackground("w")
        pw.showGrid(x=True, y=True, alpha=0.2)

        axis_font = QFont(_system_font(), 10)
        pw.getAxis("left").setStyle(tickFont=axis_font)
        pw.getAxis("bottom").setStyle(tickFont=axis_font)
        pw.enableAutoRange()

        self._legend = pw.addLegend(offset=(10, 10))
        self._curve_setpoint = pw.plot(
            [], name="",
            pen=pg.mkPen(color="#2ECC71", width=2, style=Qt.PenStyle.DashLine),
            antialias=True,
        )
        self._curve_actual = pw.plot(
            [], name="",
            pen=pg.mkPen(color="#E74C3C", width=2),
            antialias=True,
        )
        self._plot_widget_ref = pw
        return pw

    # ------------------------------------------------------------------
    # Data ingestion (called by main window on each received line)
    # ------------------------------------------------------------------

    def ingest_line(self, line: str) -> None:
        parsed = parse_line(line)
        if parsed is None:
            return
        _, setpoint, actual, _ = parsed
        self._buf_setpoint.append(setpoint)
        self._buf_actual.append(actual)
        self._curve_setpoint.setData(list(self._buf_setpoint))
        self._curve_actual.setData(list(self._buf_actual))

    def clear_plot(self) -> None:
        self._buf_setpoint.clear()
        self._buf_actual.clear()
        self._curve_setpoint.setData([])
        self._curve_actual.setData([])

    def current_values(self) -> tuple[float, float, float]:
        return self._pid_kp.value(), self._pid_ki.value(), self._pid_kd.value()

    def set_values(self, kp: float, ki: float, kd: float) -> None:
        self._pid_kp.spinbox.setValue(kp)
        self._pid_ki.spinbox.setValue(ki)
        self._pid_kd.spinbox.setValue(kd)

    # ------------------------------------------------------------------
    # PID send
    # ------------------------------------------------------------------

    def _send_single(self, row: PidRow) -> None:
        if not self._worker.is_open():
            if self.on_toast:
                self.on_toast(self._tr.tr("toast_pid_not_open"), False)
            return
        val = row.formatted_value()
        msg = f"PID:{row.name}={val}\r\n"
        try:
            self._worker.write(msg.encode("utf-8"))
            if self.on_toast:
                self.on_toast(f"{row.name}={val} ✓", True)
        except Exception as e:
            if self.on_toast:
                self.on_toast(self._tr.tr("toast_pid_send_fail") + f": {e}", False)

    def _send_all(self) -> None:
        if not self._worker.is_open():
            if self.on_toast:
                self.on_toast(self._tr.tr("toast_pid_not_open"), False)
            return
        kp = self._pid_kp.formatted_value()
        ki = self._pid_ki.formatted_value()
        kd = self._pid_kd.formatted_value()
        msg = f"PID:{kp},{ki},{kd}\r\n"
        try:
            self._worker.write(msg.encode("utf-8"))
            if self.on_toast:
                self.on_toast(f"Kp={kp}, Ki={ki}, Kd={kd} ✓", True)
        except Exception as e:
            if self.on_toast:
                self.on_toast(self._tr.tr("toast_pid_send_fail") + f": {e}", False)

    def set_send_enabled(self, enabled: bool) -> None:
        self._send_all_btn.setEnabled(enabled)
        self._pid_kp.send_btn.setEnabled(enabled)
        self._pid_ki.send_btn.setEnabled(enabled)
        self._pid_kd.send_btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def retranslate(self) -> None:
        t = self._tr.tr
        self._pid_group_box.setTitle(t("pid_group"))
        self._pid_kp.retranslate(t)
        self._pid_ki.retranslate(t)
        self._pid_kd.retranslate(t)
        self._send_all_btn.setText(t("send_all_btn"))

        self._plot_widget_ref.setLabel("left", t("plot_left_axis"), **{"font-size": "10pt"})
        self._plot_widget_ref.setLabel("bottom", t("plot_bottom_axis"), **{"font-size": "10pt"})
        self._legend.clear()
        self._legend.addItem(self._curve_setpoint, t("curve_setpoint"))
        self._legend.addItem(self._curve_actual, t("curve_actual"))
        self._retranslate_plot_menu()

    def _retranslate_plot_menu(self) -> None:
        t = self._tr.tr
        vb = self._plot_widget_ref.getViewBox()
        menu = vb.menu

        menu.viewAll.setText(t("vb_view_all"))
        actions = menu.actions()
        axis_labels = [t("vb_x_axis"), t("vb_y_axis")]
        for i, idx in enumerate([1, 2]):
            if idx < len(actions):
                actions[idx].setText(axis_labels[i])
                sub = actions[idx].menu()
                if sub:
                    sub.setTitle(axis_labels[i])
                    ctrl = menu.ctrl[i]
                    ctrl.autoRadio.setText(t("vb_auto"))
                    ctrl.manualRadio.setText(t("vb_manual"))
                    ctrl.invertCheck.setText(t("vb_invert"))
                    ctrl.mouseCheck.setText(t("vb_mouse_enabled"))
                    ctrl.visibleOnlyCheck.setText(t("vb_visible_only"))
                    ctrl.autoPanCheck.setText(t("vb_auto_pan"))
                    from PySide6.QtWidgets import QLabel as _QLabel
                    for child in ctrl.linkCombo.parent().findChildren(_QLabel):
                        if child.text().endswith(":"):
                            child.setText(t("vb_link_axis"))
                            break

        for action in actions:
            sub = action.menu()
            if sub and ("Mouse" in action.text() or "鼠标" in action.text()):
                action.setText(t("vb_mouse_mode"))
                sub.setTitle(t("vb_mouse_mode"))
                break

        if len(menu.mouseModes) >= 2:
            menu.mouseModes[0].setText(t("vb_3button"))
            menu.mouseModes[1].setText(t("vb_1button"))

        plot_item = self._plot_widget_ref.getPlotItem()
        ctrl_menu = plot_item.ctrlMenu
        ctrl_menu.setTitle(t("pi_plot_options"))
        submenu_keys = ["pi_transforms", "pi_downsample", "pi_average",
                        "pi_alpha", "pi_grid", "pi_points"]
        for i, action in enumerate(ctrl_menu.actions()):
            if i < len(submenu_keys):
                action.setText(t(submenu_keys[i]))
                sub = action.menu()
                if sub:
                    sub.setTitle(t(submenu_keys[i]))

        c = plot_item.ctrl
        c.fftCheck.setText(t("pi_fft"))
        c.subtractMeanCheck.setText(t("pi_subtract_mean"))
        c.logXCheck.setText(t("pi_log_x"))
        c.logYCheck.setText(t("pi_log_y"))
        c.derivativeCheck.setText(t("pi_derivative"))
        c.phasemapCheck.setText(t("pi_phasemap"))
        c.downsampleCheck.setText(t("pi_ds_check"))
        c.autoDownsampleCheck.setText(t("pi_ds_auto"))
        c.subsampleRadio.setText(t("pi_ds_subsample"))
        c.meanRadio.setText(t("pi_ds_mean"))
        c.peakRadio.setText(t("pi_ds_peak"))
        c.clipToViewCheck.setText(t("pi_ds_clip"))
        c.maxTracesCheck.setText(t("pi_ds_max_traces"))
        c.forgetTracesCheck.setText(t("pi_ds_forget"))
        c.autoAlphaCheck.setText(t("pi_alpha_auto"))
        c.alphaGroup.setTitle(t("pi_alpha"))
        c.xGridCheck.setText(t("pi_grid_x"))
        c.yGridCheck.setText(t("pi_grid_y"))
        c.autoPointsCheck.setText(t("pi_points_auto"))
        c.pointsGroup.setTitle(t("pi_points"))

        scene = self._plot_widget_ref.scene()
        if hasattr(scene, "contextMenu") and scene.contextMenu:
            scene.contextMenu[0].setText(t("gs_export"))
