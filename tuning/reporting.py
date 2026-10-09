"""Local evidence-based explanations and portable HTML/CSV reports."""
import csv
import html
import math
from dataclasses import asdict
from pathlib import Path


def explain(history, config):
    valid = [r for r in history if r.safe and r.metrics.valid and math.isfinite(r.metrics.score)]
    if not valid:
        return "尚无有效安全试验。请检查阶跃、时间戳、采样量和设备状态；不要据此增加 PID。"
    best = min(valid, key=lambda r:r.metrics.score)
    baseline = next((r for r in valid if r.is_baseline),valid[0])
    m = best.metrics
    lines = ["本地数据解释（规则分析，不是大语言模型；不直接控制设备）",
             f"有效试验 {len(valid)}/{len(history)}；最佳第 {best.index} 轮，PID = {best.gains.formatted()}。",
             f"评分 {baseline.metrics.score:.3f} → {m.score:.3f}（越低越好）。"]
    if baseline.metrics.score > 0:
        lines.append(f"相对基准评分改善 {(baseline.metrics.score-m.score)/baseline.metrics.score*100:.1f}%。")
    lines.append(f"超调 {m.overshoot_percent:.2f}%；稳态平均绝对误差 {m.steady_state_error:.6g} {config.unit}。")
    if not math.isfinite(m.settling_time):
        lines.append("采集窗口内未确认持续稳定：优先检查振荡、稳态误差或适当延长观察，不应仅凭总分接受参数。")
    else:
        lines.append(f"稳定时间 {m.settling_time:.3f} s；需至少保持 {config.settling_hold_seconds:g} s。")
    if m.overshoot_percent > config.safety.max_overshoot_percent*.7:
        lines.append("超调接近保护阈值：建议收紧探索范围并复测试验，避免继续激进增加增益。")
    if len(valid) < 4:
        lines.append("有效样本较少：当前结果仅是初步比较，不能推断全局最优。")
    for result in history:
        if not result.safe:
            lines.append(f"第 {result.index} 轮失败：{result.metrics.reason or '安全阈值未通过'}。")
    lines.append("不同负载、采样周期或目标幅度的结果不可直接混为同一试验；建议在相同条件下复测。")
    return "\n".join(lines)


def export_csv(path: Path, history):
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["trial","kp","ki","kd","safe","time_s","setpoint","actual","output"])
        for result in history:
            for sample in result.samples:
                writer.writerow([result.index,*result.gains.as_array(),result.safe,
                                 sample.timestamp,sample.setpoint,sample.actual,sample.output])


def export_html(path: Path, history, config):
    escape=html.escape
    rows=[]
    curves=[]
    for result in history:
        m=result.metrics
        rows.append(f"<tr><td>{result.index}</td><td>{result.gains.formatted()}</td>"
            f"<td>{m.score:.3f}</td><td>{m.overshoot_percent:.2f}%</td><td>{m.settling_time:.3f}</td>"
            f"<td>{m.steady_state_error:.6g}</td><td>{'PASS' if result.safe else escape(m.reason)}</td></tr>")
    valid=[r for r in history if r.safe and r.metrics.valid and r.samples]
    if valid:
        baseline=next((r for r in valid if r.is_baseline),valid[0])
        best=min(valid,key=lambda r:r.metrics.score)
        selected=[(baseline,"#94a3b8"),(best,"#38bdf8")]
        xs=[s.timestamp for r,_ in selected for s in r.samples]
        ys=[s.actual for r,_ in selected for s in r.samples]
        low,high=min(ys),max(ys)
        for result,color in selected:
            samples=result.samples[::max(1,len(result.samples)//1200)]
            points=" ".join(f"{30+840*s.timestamp/max(max(xs),1e-9):.1f},{260-230*(s.actual-low)/max(high-low,1e-9):.1f}" for s in samples)
            curves.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    content=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Nova PID Report</title>
<style>body{{background:#0b1220;color:#e2e8f0;font:15px system-ui;max-width:1100px;margin:40px auto;padding:24px}}
h1{{color:#38bdf8}}section{{background:#152033;border:1px solid #334155;border-radius:12px;padding:24px;margin:20px 0}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:10px;border-bottom:1px solid #334155;text-align:left}}
pre{{white-space:pre-wrap}}svg{{width:100%;background:#0b1220;border-radius:8px}}</style>
<h1>Nova · PID 调参报告</h1><p>{escape(config.device_name)} · {escape(config.mode)} · {escape(config.unit)}</p>
<section><h2>试验结论</h2><pre>{escape(explain(history,config))}</pre></section>
<section><h2>响应对比</h2><p>灰色：基准，蓝色：最佳；横轴：时间，纵轴：实际值。</p>
<svg viewBox="0 0 900 290">{''.join(curves)}</svg></section>
<section><h2>逐轮结果</h2><table><tr><th>#</th><th>Kp, Ki, Kd</th><th>Score</th><th>Overshoot</th><th>Settling (s)</th><th>MAE</th><th>Status</th></tr>{''.join(rows)}</table></section>
<section><h2>设备与安全配置</h2><pre>{escape(str(asdict(config)))}</pre></section>
<p>此报告是软件试验记录，不构成硬件安全认证。Flash 持久化由下位机单独处理。</p></html>'''
    path.write_text(content,encoding="utf-8")
