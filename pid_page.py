import collections
import platform
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QGroupBox,
    QSlider, QDoubleSpinBox, QGridLayout, QSplitter,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from i18n import Translator
from serial_worker import SerialWorker

BUFFER_SIZE = 500


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


class PidRow:
    def __init__(self, name: str, left_grid: QGridLayout, right_grid: QGridLayout, row: int):
        self.name = name
        self._syncing = False

        # 左侧：标签 + SpinBox
        left_row = QWidget()
        left_hbox = QHBoxLayout(left_row)
        left_hbox.setContentsMargins(0, 0, 0, 0)
        left_hbox.setSpacing(6)
        self._label = QLabel(name)
        self.spinbox = QDoubleSpinBox()
        self.spinbox.setRange(0.0, 10.0)
        self.spinbox.setSingleStep(0.01)
        self.spinbox.setDecimals(2)
        self.spinbox.setValue(0.0)
        self.spinbox.setFixedWidth(80)
        left_hbox.addWidget(self._label)
        left_hbox.addWidget(self.spinbox)
        left_hbox.addStretch()
        left_grid.addWidget(left_row, row, 0)

        # 右侧：滑块 + 发送按钮
        right_row = QWidget()
        right_hbox = QHBoxLayout(right_row)
        right_hbox.setContentsMargins(0, 0, 0, 0)
        right_hbox.setSpacing(4)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setValue(0)
        self.send_btn = QPushButton()
        self.send_btn.setFixedWidth(48)
        right_hbox.addWidget(self.slider, stretch=1)
        right_hbox.addWidget(self.send_btn)
        right_grid.addWidget(right_row, row, 0)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spinbox.valueChanged.connect(self._spinbox_changed)

    def value(self) -> float:
        return self.spinbox.value()

    def retranslate(self, send_text: str) -> None:
        self.send_btn.setText(send_text)

    def _slider_changed(self, v: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.spinbox.setValue(v / 100.0)
        self._syncing = False

    def _spinbox_changed(self, v: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.slider.setValue(round(v * 100))
        self._syncing = False


class PidPage(QWidget):
    """页面2：波形图（左右布局，左侧 PID 面板，右侧波形）。"""

    def __init__(self, worker: SerialWorker, parent=None):
        super().__init__(parent)
        self._worker = worker
        self._tr = Translator()
        self._buf_setpoint: collections.deque[float] = collections.deque(maxlen=BUFFER_SIZE)
        self._buf_actual: collections.deque[float] = collections.deque(maxlen=BUFFER_SIZE)
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

        layout.addWidget(self._build_pid_panel())
        layout.addWidget(self._build_plot_widget(), stretch=1)

    def _build_pid_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(360)
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

        # ---- 可拖拽分隔条（参考串口配置页面） ----
        col_splitter = QSplitter(Qt.Orientation.Horizontal)
        col_splitter.setHandleWidth(4)

        left_widget = QWidget()
        left_grid = QGridLayout(left_widget)
        left_grid.setSpacing(8)
        left_grid.setContentsMargins(4, 0, 0, 0)

        right_widget = QWidget()
        right_grid = QGridLayout(right_widget)
        right_grid.setSpacing(8)
        right_grid.setContentsMargins(0, 0, 4, 0)
        right_grid.setColumnStretch(0, 1)

        col_splitter.addWidget(left_widget)
        col_splitter.addWidget(right_widget)
        col_splitter.setStretchFactor(0, 0)
        col_splitter.setStretchFactor(1, 1)
        col_splitter.setSizes([120, 200])
        group_layout.addWidget(col_splitter)

        self._pid_kp = PidRow("Kp", left_grid, right_grid, 0)
        self._pid_ki = PidRow("Ki", left_grid, right_grid, 1)
        self._pid_kd = PidRow("Kd", left_grid, right_grid, 2)

        self._pid_kp.send_btn.clicked.connect(lambda: self._send_single(self._pid_kp))
        self._pid_ki.send_btn.clicked.connect(lambda: self._send_single(self._pid_ki))
        self._pid_kd.send_btn.clicked.connect(lambda: self._send_single(self._pid_kd))

        self._send_all_btn = QPushButton()
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

    # ------------------------------------------------------------------
    # PID send
    # ------------------------------------------------------------------

    def _send_single(self, row: PidRow) -> None:
        msg = f"PID:{row.name}={row.value():.2f}\r\n"
        self._worker.write(msg.encode("utf-8"))
        print(f"已发送: {msg.strip()}")

    def _send_all(self) -> None:
        msg = f"PID:{self._pid_kp.value():.2f},{self._pid_ki.value():.2f},{self._pid_kd.value():.2f}\r\n"
        self._worker.write(msg.encode("utf-8"))
        print(f"已发送: {msg.strip()}")

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
        self._pid_kp.retranslate(t("send_param_btn"))
        self._pid_ki.retranslate(t("send_param_btn"))
        self._pid_kd.retranslate(t("send_param_btn"))
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
