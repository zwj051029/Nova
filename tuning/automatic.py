"""Acknowledged, watchdog-protected trial orchestration; no Qt or serial dependency."""
import collections
import math
import time
import uuid

from .models import PIDGains
from .protocol import decode, encode, telemetry
from .safety import check_live_sample, validate_candidate
from .models import TelemetrySample
from .session import TuningSession


class AutomaticTuner:
    TERMINAL = {"idle", "accepted", "restored", "aborted"}
    REQUIRED = {"ack", "set_pid", "set_target", "stop", "watchdog", "timestamp", "limits"}

    def __init__(self, config, send, clock=time.monotonic, on_result=None, on_status=None, on_applied=None):
        config.validate()
        self.config, self.send, self.clock = config, send, clock
        self.session = TuningSession(config)
        self.on_result, self.on_status, self.on_applied = on_result, on_status, on_applied
        self.state, self.message = "idle", ""
        self.pending = None
        self.request_count = 0
        self.token = uuid.uuid4().hex[:12]
        self.original = None
        self.nominated = None
        self.verified = None
        self.next_gains = None
        self.verifying = False
        self.auto = True
        self.lease = False
        self.last_heartbeat = self.last_received = clock()
        self.last_seq = self.last_time = None
        self.stable = collections.deque()
        self.oscillation = collections.deque()
        self.saturated_at = None
        self.no_improvement = 0
        self.best_score = math.inf
        self.failure = ""

    @property
    def active(self):
        return self.state not in self.TERMINAL

    def _status(self, state, message):
        self.state, self.message = state, message
        if self.on_status:
            self.on_status(state, message)

    def _request(self, command, callback, **payload):
        self.request_count += 1
        request_id = f"{self.token}-{self.request_count}"
        message = dict(type="command", id=request_id, cmd=command, channel=self.config.channel, **payload)
        self.pending = (request_id, command, self.clock() + 1.5, callback)
        try:
            self.send(encode(message))
        except Exception as exc:
            self.pending = None
            self.fail(f"发送失败: {exc}")

    def start(self, baseline, automatic=True):
        if self.active:
            raise RuntimeError("已有活动试验")
        if not validate_candidate(baseline, baseline, self.config)[0]:
            raise ValueError("基准 PID 超出档案范围")
        if self.config.mode == "P" and (baseline.ki or baseline.kd) or self.config.mode == "PI" and baseline.kd:
            raise ValueError("P/PI 模式要求未使用的参数为零")
        if self.config.max_trials < 3:
            raise ValueError("自动调参至少需要 3 轮（含最终复测）")
        if abs(self.config.step_target - self.config.initial_target) < self.config.minimum_step:
            raise ValueError("目标阶跃过小")
        for target in (self.config.initial_target, self.config.step_target):
            if not self.config.safety.actual_min <= target <= self.config.safety.actual_max:
                raise ValueError("试验目标超出安全范围")
        baseline = PIDGains(*(round(v, 6) for v in baseline.as_array()))
        self.session.set_baseline(baseline)
        self.auto = automatic
        self.last_received = self.clock()
        self._status("handshake", "检查设备能力与控制周期")
        self._request("hello", self._hello)

    def _hello(self, ack):
        if ack.get("version") != 2 or not self.REQUIRED <= set(ack.get("capabilities", [])):
            self.fail("设备不支持完整的 Nova v2 自动调参协议；请使用手动模式")
            return
        if ack.get("algorithm") != self.config.algorithm or not math.isclose(float(ack.get("period", 0)), self.config.sample_period_seconds, rel_tol=.01):
            self.fail("设备控制算法/采样周期与档案不一致")
            return
        self._request("get", self._snapshot)

    def _snapshot(self, ack):
        self.original = PIDGains(*map(float, ack["gains"]))
        if not all(math.isfinite(v) and 0 <= v <= 1e6 for v in self.original.as_array()):
            raise ValueError("设备参数读回无效")
        limits = self.config.safety
        self._request("configure", self._configured, actual_min=limits.actual_min, actual_max=limits.actual_max,
                      output_limit=limits.output_abs_max, watchdog=max(.8, limits.telemetry_timeout))

    def _configured(self, ack):
        self.lease = True
        self._request("stop", lambda _: self._begin_trial(self.session.baseline, True))

    def _begin_trial(self, gains, baseline=False):
        self.next_gains = gains
        self.is_baseline = baseline
        self._status("applying", "下发参数并等待设备确认")
        self._request("set_pid", self._pid_ack, gains=list(gains.as_array()))

    def _pid_ack(self, ack):
        actual = PIDGains(*map(float, ack["gains"]))
        if any(abs(a-b) > 5e-7 for a,b in zip(actual.as_array(), self.next_gains.as_array())):
            self.fail("设备实际应用的 PID 与请求不一致")
            return
        if self.on_applied:
            self.on_applied(actual)
        self._request("set_target", self._initial_ack, value=self.config.initial_target)

    def _initial_ack(self, ack):
        if not math.isclose(float(ack["value"]), self.config.initial_target, abs_tol=1e-9):
            raise ValueError("初始目标确认不一致")
        self.stable.clear()
        self.oscillation.clear()
        self.saturated_at = None
        self.phase_started = self.clock()
        self._status("settling", "等待初始状态稳定")

    def handle_line(self, line):
        if not self.active:
            return
        message = decode(line)
        if message and message.get("type") == "ack":
            if self.pending and message.get("id") == self.pending[0] and message.get("cmd") == self.pending[1]:
                callback = self.pending[3]
                self.pending = None
                if message.get("ok") is not True:
                    self.fail(f"设备拒绝命令: {message.get('error', 'unknown')}")
                    return
                try:
                    callback(message)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    self.fail(f"确认帧无效: {exc}")
            return
        if message and message.get("channel") == self.config.channel and message.get("type") == "fault":
            self.fail(f"设备故障: {message.get('reason', 'unknown')}")
            return
        frame = telemetry(line)
        if not frame:
            if message and message.get("type") == "telemetry" and message.get("channel") == self.config.channel:
                self.fail("无效遥测数据")
            return
        if frame.channel != self.config.channel or frame.timestamp is None:
            return
        if self.last_seq is not None and (frame.sequence != self.last_seq + 1 or frame.timestamp <= self.last_time):
            self.fail("遥测丢帧、乱序或设备时间回退")
            return
        self.last_seq, self.last_time = frame.sequence, frame.timestamp
        self.last_received = self.clock()
        if self.state in ("stopping", "review", "awaiting_confirmation", "handshake"):
            return
        expected_target = self.config.step_target if self.state == "capturing" else self.config.initial_target
        if self.state in ("settling", "prefill", "capturing") and not math.isclose(frame.setpoint, expected_target, abs_tol=1e-6):
            self.fail("目标值被外部修改或未正确生效")
            return
        sample = TelemetrySample(frame.timestamp, frame.setpoint, frame.actual, frame.output)
        safe, reason = check_live_sample(sample, self.config.safety)
        if not safe:
            self.fail(reason)
            return
        if self.state in ("settling", "prefill", "capturing"):
            if abs(frame.output) >= self.config.safety.output_abs_max * .999:
                if self.saturated_at is None:
                    self.saturated_at = self.clock()
                elif self.clock() - self.saturated_at >= self.config.safety.saturation_seconds:
                    self.fail("控制输出持续饱和")
                    return
            else:
                self.saturated_at = None
        if self.state == "settling":
            if abs(frame.actual - self.config.initial_target) <= self.config.stable_tolerance:
                self.stable.append(frame.timestamp)
                if frame.timestamp - self.stable[0] >= self.config.stable_seconds:
                    self.session.start_capture(self.next_gains, self.is_baseline)
                    self.phase_started = self.clock()
                    self._status("prefill", "记录阶跃前数据")
            else:
                self.stable.clear()
        if self.session.capturing:
            safe, reason = self.session.ingest(frame.setpoint, frame.actual, frame.output, frame.timestamp, frame.sequence)
            if not safe:
                self.fail(reason)
                return
            self.oscillation.append((frame.timestamp, frame.actual-frame.setpoint))
            while self.oscillation and frame.timestamp-self.oscillation[0][0] > 2:
                self.oscillation.popleft()
            errors = [error for _,error in self.oscillation if abs(error)>self.config.stable_tolerance]
            if len(errors)>10 and sum(a*b<0 for a,b in zip(errors, errors[1:]))>=8:
                self.fail("检测到持续振荡")

    def tick(self):
        if not self.active:
            return
        now = self.clock()
        if self.pending and now > self.pending[2]:
            command = self.pending[1]
            self.pending = None
            self.fail(f"{command} 确认超时")
            return
        if self.lease and now-self.last_heartbeat >= .2:
            self.last_heartbeat = now
            try:
                self.send(encode({"cmd":"heartbeat", "id": f"{self.token}-heartbeat", "channel":self.config.channel}))
            except Exception as exc:
                self.fail(f"心跳发送失败: {exc}")
                return
        if self.state not in ("handshake", "stopping", "review", "awaiting_confirmation") and now-self.last_received > self.config.safety.telemetry_timeout:
            self.fail("遥测超时")
            return
        if self.state == "settling" and now-self.phase_started > self.config.stability_timeout:
            self.fail("初始状态未能稳定")
        elif self.state == "prefill" and now-self.phase_started >= self.config.pre_seconds and not self.pending:
            self._request("set_target", self._step_ack, value=self.config.step_target)
        elif self.state == "capturing" and now-self.phase_started >= self.config.capture_seconds:
            self._finish_trial()

    def _step_ack(self, ack):
        if not math.isclose(float(ack["value"]), self.config.step_target, abs_tol=1e-9):
            raise ValueError("阶跃目标确认不一致")
        self.phase_started = self.clock()
        self._status("capturing", f"采集第 {len(self.session.history)+1} 轮" + ("（最优复测）" if self.verifying else ""))

    def _publish(self, result):
        if self.on_result:
            self.on_result(result)

    def _finish_trial(self):
        result = self.session.finish_capture()
        self._status("evaluating", "分析试验结果")
        self._publish(result)
        if not result.safe:
            self.fail(result.metrics.reason or "试验结果无效")
            return
        if self.verifying:
            if result.metrics.score > self.nominated.metrics.score * 1.1 + .5:
                self.fail("最优参数复测退化，未接受结果")
                return
            self.verified = result
            self._request("stop", lambda _: self._status("review", "复测通过，设备已停止；请选择接受最优参数或恢复原参数"))
            return
        if result.metrics.score < self.best_score - .01:
            self.best_score, self.no_improvement = result.metrics.score, 0
        else:
            self.no_improvement += 1
        finish = (len(self.session.history) >= self.config.max_trials-1 or
                  self.no_improvement >= self.config.patience or self.best_score <= self.config.target_score)
        if finish:
            self.nominated = self.session.best_result()
            self.verifying = True
            self.next_gains = self.nominated.gains
        else:
            try:
                self.next_gains, self.reason = self.session.suggest()
            except RuntimeError:
                self.nominated = self.session.best_result()
                self.verifying, self.next_gains = True, self.nominated.gains
        self._request("stop", self._between_trials)

    def _between_trials(self, ack):
        if self.auto:
            self._begin_trial(self.next_gains)
        else:
            self._status("awaiting_confirmation", f"设备已停止，下一组 {self.next_gains.formatted()}；等待人工确认")

    def confirm_next(self):
        if self.state == "awaiting_confirmation":
            self._begin_trial(self.next_gains)

    def decide(self, accept):
        if self.state != "review" or not self.verified:
            raise RuntimeError("尚未通过最终复测")
        gains = self.verified.gains if accept else self.original
        self._status("deciding", "等待最终参数确认（设备保持停止）")
        def confirmed(ack):
            if tuple(ack["gains"]) != gains.as_array():
                raise ValueError("最终参数确认不一致")
            self.lease = False
            if self.on_applied:
                self.on_applied(gains)
            self._status("accepted" if accept else "restored", "参数已确认保存到设备 RAM，输出保持停止；未写入 Flash")
        self._request("set_pid", confirmed, gains=list(gains.as_array()))

    def fail(self, reason):
        if self.state in self.TERMINAL:
            return
        if self.state == "stopping":
            self.lease = False
            self.pending = None
            self._status("aborted", self.failure + "；停止未确认，依赖设备看门狗")
            return
        if self.session.samples and (self.session.capturing or self.state in ("prefill", "capturing")):
            self._publish(self.session.record_failure(reason))
        self.failure = reason
        self.session.capturing = False
        self.pending = None
        self._status("stopping", reason + "；请求停止输出")
        def stopped(ack):
            self.lease = False
            self._status("aborted", reason + "；设备已确认停止，未自动恢复运动")
        self._request("stop", stopped)

    def stop(self):
        self.fail("用户停止试验")
