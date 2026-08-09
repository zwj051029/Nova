from PySide6.QtCore import QSettings


_TRANSLATIONS: dict[str, dict[str, str]] = {
    # --- window ---
    "window_title":     {"zh": "Nova",              "en": "Nova"},
    "app_title":        {"zh": "Serial PID Tuner",  "en": "Serial PID Tuner"},

    # --- navigation ---
    "nav_serial":       {"zh": "串口\n收发",         "en": "Serial\nComm"},
    "nav_pid":          {"zh": "PID\n调参",          "en": "PID\nTuner"},
    "nav_ai":           {"zh": "AI\n调参",           "en": "AI\nTuning"},

    # --- serial panel ---
    "port_label":       {"zh": "端口号",             "en": "Port"},
    "baud_label":       {"zh": "波特率",             "en": "Baud Rate"},
    "flow_ctrl_label":  {"zh": "数据流控",           "en": "Flow Control"},
    "parity_label":     {"zh": "校验位",             "en": "Parity"},
    "bytesize_label":   {"zh": "数据位数",           "en": "Data Bits"},
    "stopbits_label":   {"zh": "停止位数",           "en": "Stop Bits"},
    "signals_label":    {"zh": "流控信号",           "en": "Control Signals"},
    "refresh_btn":      {"zh": "刷新",               "en": "Refresh"},
    "refresh_tooltip":  {"zh": "刷新串口列表 (F5)",   "en": "Refresh ports (F5)"},
    "toast_refresh_ok": {"zh": "刷新成功",            "en": "Refresh successful"},
    "toast_refresh_ok_found": {"zh": "刷新成功，发现 {n} 个串口", "en": "Refresh successful, found {n} port(s)"},
    "toast_refresh_fail":     {"zh": "刷新失败",      "en": "Refresh failed"},
    "no_port":          {"zh": "无可用串口",          "en": "No ports"},
    "connected":        {"zh": "已连接",             "en": "Connected"},
    "disconnected":     {"zh": "已断开",             "en": "Disconnected"},
    "open_port":        {"zh": "打开串口",            "en": "Open"},
    "close_port":       {"zh": "关闭串口",            "en": "Close"},
    "no_port_available":{"zh": "无可用串口",          "en": "No Port Available"},
    "serial_config_group": {"zh": "串口参数配置",    "en": "Serial Configuration"},

    # --- receive area ---
    "recv_label":       {"zh": "接收区",             "en": "Receive"},
    "clear_recv_btn":   {"zh": "清空接收",           "en": "Clear RX"},
    "clear_send_btn":   {"zh": "清空发送",           "en": "Clear TX"},
    "placeholder":      {"zh": "等待串口数据…",      "en": "Waiting for data…"},
    "send_placeholder": {"zh": "已发送的数据…",      "en": "Sent data…"},

    # --- send area ---
    "send_label":       {"zh": "发送区",             "en": "Send"},
    "send_btn":         {"zh": "发送",               "en": "Send"},
    "send_input_ph":    {"zh": "输入发送内容…",      "en": "Enter data to send…"},
    "hex_send_chk":     {"zh": "十六进制",           "en": "Hex"},
    "str_send_chk":     {"zh": "字符串",             "en": "String"},
    "recv_mode_btn_str":  {"zh": "📝 字符串",           "en": "📝 String"},
    "recv_mode_btn_hex":  {"zh": "🔢 十六进制",         "en": "🔢 Hex"},
    "mode_btn_str":     {"zh": "📝 字符串",           "en": "📝 String"},
    "mode_btn_hex":     {"zh": "🔢 十六进制",         "en": "🔢 Hex"},
    "send_input_ph_str":{"zh": "输入发送内容…",       "en": "Enter data to send…"},
    "send_input_ph_hex":{"zh": "例：41 42 0D 0A",    "en": "e.g. 41 42 0D 0A"},
    "loop_send_chk":    {"zh": "循环",               "en": "Loop"},
    "loop_interval_lbl":{"zh": "ms",                 "en": "ms"},
    "hex_error":        {"zh": "[错误] 十六进制格式无效: ", "en": "[Error] Invalid hex: "},

    # --- PID group ---
    "pid_group":        {"zh": "PID 参数",           "en": "PID Parameters"},
    "send_param_btn":   {"zh": "发送",               "en": "Send"},
    "send_all_btn":     {"zh": "发送全部",            "en": "Send All"},
    "decimal_places_btn": {"zh": "{n} 位",            "en": "{n} dp"},
    "decimal_places_tooltip": {"zh": "增加一位小数（最多 6 位）", "en": "Add one decimal place (up to 6)"},
    "decimal_places_decrease_tooltip": {"zh": "减少一位小数（最少 2 位）", "en": "Remove one decimal place (down to 2)"},

    # --- AI tuning ---
    "ai_title":         {"zh": "AI 辅助 PID 调参", "en": "AI-assisted PID Tuning"},
    "ai_baseline_group":{"zh": "稳定基准 PID", "en": "Stable Baseline PID"},
    "ai_search_group":  {"zh": "搜索设置", "en": "Search Settings"},
    "ai_safety_group":  {"zh": "安全边界", "en": "Safety Limits"},
    "ai_gain_max":      {"zh": "参数最大值", "en": "Gain maximum"},
    "ai_relative_change":{"zh": "单次最大变化", "en": "Max change per trial"},
    "ai_max_trials":    {"zh": "最大试验次数", "en": "Maximum trials"},
    "ai_capture_time":  {"zh": "单次采集时间", "en": "Capture duration"},
    "ai_sample_period": {"zh": "下位机采样周期", "en": "Device sample period"},
    "ai_actual_min":    {"zh": "实际值下限", "en": "Actual minimum"},
    "ai_actual_max":    {"zh": "实际值上限", "en": "Actual maximum"},
    "ai_output_max":    {"zh": "输出绝对值上限", "en": "Output absolute limit"},
    "ai_overshoot_max": {"zh": "最大允许超调", "en": "Maximum overshoot"},
    "ai_load_manual":   {"zh": "读取手动调参页数值", "en": "Load manual PID values"},
    "ai_baseline_card": {"zh": "基准 PID", "en": "Baseline PID"},
    "ai_proposed_card": {"zh": "AI 推荐 PID", "en": "AI Proposed PID"},
    "ai_best_card":     {"zh": "当前最佳 PID / 评分", "en": "Best PID / Score"},
    "ai_start_baseline":{"zh": "开始基准采集", "en": "Capture Baseline"},
    "ai_finish_capture":{"zh": "结束并评分", "en": "Finish & Score"},
    "ai_suggest":       {"zh": "生成 AI 推荐", "en": "Generate Proposal"},
    "ai_apply":         {"zh": "应用推荐并采集", "en": "Apply & Capture"},
    "ai_abort":         {"zh": "紧急停止并恢复", "en": "Abort & Restore"},
    "ai_initial_hint":  {"zh": "先确认一组稳定 PID，点击“开始基准采集”，随后手动改变目标值产生一次阶跃。", "en": "Confirm a stable PID, start baseline capture, then manually change the setpoint once."},
    "ai_step_hint":     {"zh": "正在采集：请手动改变一次目标值。到达采集时长后会自动评分。", "en": "Capturing: change the setpoint once. The trial will be scored automatically."},
    "ai_abort_hint":    {"zh": "调参已停止，并已尝试恢复基准 PID。", "en": "Tuning stopped and the baseline PID was restored."},
    "ai_proposal_reason":{"zh": "推荐依据：{reason}。确认设备处于安全状态后再应用。", "en": "Proposal: {reason}. Verify the plant is safe before applying."},
    "ai_idle":          {"zh": "空闲", "en": "Idle"},
    "ai_ready":         {"zh": "等待生成推荐", "en": "Ready for proposal"},
    "ai_capturing":     {"zh": "正在采集", "en": "Capturing"},
    "ai_capturing_time":{"zh": "采集中 · 剩余 {seconds:.1f}s", "en": "Capturing · {seconds:.1f}s left"},
    "ai_proposal_ready":{"zh": "推荐待确认", "en": "Proposal awaiting approval"},
    "ai_aborted":       {"zh": "已停止", "en": "Aborted"},
    "ai_safety_abort":  {"zh": "安全中止", "en": "Safety abort"},
    "ai_trial_scored":  {"zh": "试验评分：{score:.2f}", "en": "Trial score: {score:.2f}"},
    "ai_need_baseline": {"zh": "请先完成一次有效的基准试验", "en": "Complete a valid baseline trial first"},
    "ai_max_trials_reached":{"zh": "已达到最大试验次数", "en": "Maximum trial count reached"},
    "ai_invalid_actual_range":{"zh": "实际值安全下限必须小于上限", "en": "Actual minimum must be below maximum"},
    "ai_invalid_baseline":{"zh": "基准 PID 不能超过参数最大值", "en": "Baseline PID exceeds the gain maximum"},
    "ai_safe":          {"zh": "安全", "en": "Safe"},
    "ai_unsafe":        {"zh": "无效/不安全", "en": "Invalid / unsafe"},
    "ai_col_trial":     {"zh": "轮次", "en": "Trial"},
    "ai_col_pid":       {"zh": "PID", "en": "PID"},
    "ai_col_score":     {"zh": "评分", "en": "Score"},
    "ai_col_rise":      {"zh": "上升时间", "en": "Rise time"},
    "ai_col_settling":  {"zh": "调节时间", "en": "Settling"},
    "ai_col_overshoot": {"zh": "超调", "en": "Overshoot"},
    "ai_col_error":     {"zh": "稳态误差", "en": "Steady error"},
    "ai_col_safety":    {"zh": "安全性", "en": "Safety"},

    # --- plot ---
    "plot_left_axis":   {"zh": "数值",               "en": "Value"},
    "plot_bottom_axis": {"zh": "采样点",             "en": "Samples"},
    "curve_setpoint":   {"zh": "目标值",             "en": "Setpoint"},
    "curve_actual":     {"zh": "实际值",             "en": "Actual"},

    # --- status bar ---
    "status_disconnected": {"zh": "未连接",             "en": "Disconnected"},
    "status_connected":    {"zh": "已连接",             "en": "Connected"},
    "status_port":         {"zh": "端口",               "en": "Port"},
    "status_baud":         {"zh": "波特率",             "en": "Baud"},
    "status_rx":           {"zh": "RX",                 "en": "RX"},
    "status_tx":           {"zh": "TX",                 "en": "TX"},

    # --- menu ---
    "menu_language":    {"zh": "语言",               "en": "Language"},
    "lang_zh":          {"zh": "中文",               "en": "Chinese"},
    "lang_en":          {"zh": "英文",               "en": "English"},
    "menu_theme":       {"zh": "主题",               "en": "Theme"},
    "theme_light":      {"zh": "☀ 浅色",             "en": "☀ Light"},
    "theme_dark":       {"zh": "🌙 深色",             "en": "🌙 Dark"},

    # --- error messages ---
    "error_open_port":  {"zh": "[错误] 无法打开串口: ", "en": "[Error] Cannot open port: "},
    "toast_pid_send_fail": {"zh": "PID 发送失败",       "en": "PID send failed"},
    "toast_pid_not_open":  {"zh": "串口未打开",          "en": "Serial port not open"},

    # --- pyqtgraph ViewBox right-click menu ---
    "vb_view_all":      {"zh": "全部显示",           "en": "View All"},
    "vb_x_axis":        {"zh": "X 轴",               "en": "X axis"},
    "vb_y_axis":        {"zh": "Y 轴",               "en": "Y axis"},
    "vb_mouse_mode":    {"zh": "鼠标模式",           "en": "Mouse Mode"},
    "vb_3button":       {"zh": "三键（平移）",        "en": "3 button"},
    "vb_1button":       {"zh": "单键（缩放）",        "en": "1 button"},
    "vb_auto":          {"zh": "自动",               "en": "Auto"},
    "vb_manual":        {"zh": "手动",               "en": "Manual"},
    "vb_invert":        {"zh": "反转坐标轴",         "en": "Invert Axis"},
    "vb_mouse_enabled": {"zh": "鼠标启用",           "en": "Mouse Enabled"},
    "vb_visible_only":  {"zh": "仅可见数据",         "en": "Visible Data Only"},
    "vb_auto_pan":      {"zh": "仅自动平移",         "en": "Auto Pan Only"},
    "vb_link_axis":     {"zh": "关联坐标轴:",        "en": "Link Axis:"},

    # --- pyqtgraph PlotItem right-click menu ---
    "pi_plot_options":  {"zh": "绘图选项",           "en": "Plot Options"},
    "pi_transforms":    {"zh": "变换",               "en": "Transforms"},
    "pi_downsample":    {"zh": "降采样",             "en": "Downsample"},
    "pi_average":       {"zh": "平均",               "en": "Average"},
    "pi_alpha":         {"zh": "透明度",             "en": "Alpha"},
    "pi_grid":          {"zh": "网格",               "en": "Grid"},
    "pi_points":        {"zh": "点",                 "en": "Points"},
    "pi_fft":           {"zh": "功率谱 (FFT)",       "en": "Power Spectrum (FFT)"},
    "pi_subtract_mean": {"zh": "减去均值",           "en": "Subtract Mean"},
    "pi_log_x":         {"zh": "Log X",              "en": "Log X"},
    "pi_log_y":         {"zh": "Log Y",              "en": "Log Y"},
    "pi_derivative":    {"zh": "dy/dx",              "en": "dy/dx"},
    "pi_phasemap":      {"zh": "Y vs. Y'",           "en": "Y vs. Y'"},
    "pi_ds_check":      {"zh": "降采样",             "en": "Downsample"},
    "pi_ds_auto":       {"zh": "自动",               "en": "Auto"},
    "pi_ds_subsample":  {"zh": "子采样",             "en": "Subsample"},
    "pi_ds_mean":       {"zh": "均值",               "en": "Mean"},
    "pi_ds_peak":       {"zh": "峰值",               "en": "Peak"},
    "pi_ds_clip":       {"zh": "裁剪至视图",         "en": "Clip to View"},
    "pi_ds_max_traces": {"zh": "最大曲线数:",        "en": "Max Traces:"},
    "pi_ds_forget":     {"zh": "隐藏后删除",         "en": "Forget hidden traces"},
    "pi_alpha_auto":    {"zh": "自动",               "en": "Auto"},
    "pi_alpha_label":   {"zh": "不透明度",           "en": "Opacity"},
    "pi_grid_x":        {"zh": "显示 X 网格",        "en": "Show X Grid"},
    "pi_grid_y":        {"zh": "显示 Y 网格",        "en": "Show Y Grid"},
    "pi_points_auto":   {"zh": "自动",               "en": "Auto"},

    # --- pyqtgraph GraphicsScene ---
    "gs_export":        {"zh": "导出...",            "en": "Export..."},
}


class Translator:
    _instance: "Translator | None" = None

    def __new__(cls) -> "Translator":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lang = cls._instance._load_lang()
            cls._instance._callbacks: list = []
        return cls._instance

    def _load_lang(self) -> str:
        return QSettings("Nova", "PIDTuner").value("language", "zh")

    def _save_lang(self) -> None:
        QSettings("Nova", "PIDTuner").setValue("language", self._lang)

    @property
    def lang(self) -> str:
        return self._lang

    def set_lang(self, lang: str) -> None:
        if lang not in ("zh", "en"):
            return
        self._lang = lang
        self._save_lang()
        for cb in self._callbacks:
            cb()

    def tr(self, key: str) -> str:
        entry = _TRANSLATIONS.get(key)
        if entry is None:
            return key
        return entry.get(self._lang, key)

    def on_change(self, callback) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)
