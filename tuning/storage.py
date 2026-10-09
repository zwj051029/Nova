from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import PIDGains, TrialResult, TuningConfig, SafetyLimits, ResponseMetrics, TelemetrySample


def _clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(_clean(payload), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def config_from_dict(data: dict) -> TuningConfig:
    values = dict(data)
    for key in ("gain_min", "gain_max", "gain_resolution"):
        if key in values:
            values[key] = PIDGains(**values[key])
    safety = dict(values.pop("safety", {}))
    if "max_absolute_gain_change" in safety:
        safety["max_absolute_gain_change"] = PIDGains(**safety["max_absolute_gain_change"])
    values["safety"] = SafetyLimits(**safety)
    config = TuningConfig(**values)
    config.validate()
    return config


def load_session(path: Path):
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("会话文件超过 64 MiB 限制")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version", 1) not in (1, 2):
        raise ValueError("不支持的会话版本")
    config = config_from_dict(data["config"])
    history = []
    for trial in data["trials"]:
        metrics = {key: value for key, value in trial["metrics"].items() if value is not None}
        gains=PIDGains(**trial["gains"])
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1e6 for v in gains.as_array()):
            raise ValueError("记录中有无效 PID")
        measured=ResponseMetrics(**metrics)
        if measured.valid and not math.isfinite(measured.score):
            raise ValueError("有效试验必须包含有限评分")
        samples=[TelemetrySample(**sample) for sample in trial.get("samples", [])]
        if any(not all(isinstance(v,(int,float)) and math.isfinite(v) for v in asdict(sample).values()) for sample in samples):
            raise ValueError("记录中有无效采样")
        history.append(TrialResult(trial["index"], gains,measured, trial["safe"], trial.get("is_baseline", False),samples))
    baseline=PIDGains(**data["baseline"])
    if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1e6 for v in baseline.as_array()):
        raise ValueError("记录中基准参数无效")
    return baseline, config, history


def save_session(
    directory: Path, baseline: PIDGains, config: TuningConfig,
    history: list[TrialResult], path: Path | None = None, metadata: dict | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if path is None:
        path = directory / f"pid_tuning_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    created = datetime.now().isoformat(timespec="seconds")
    if path.exists():
        created = json.loads(path.read_text(encoding="utf-8")).get("created_at", created)
    payload = {
        "schema_version": 2,
        "created_at": created,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline": asdict(baseline),
        "config": asdict(config),
        "trials": [result.to_dict(include_samples=True) for result in history],
        "metadata": metadata or {},
    }
    atomic_json(path, payload)
    return path
