from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import PIDGains, TrialResult, TuningConfig


def save_session(
    directory: Path, baseline: PIDGains, config: TuningConfig,
    history: list[TrialResult], path: Path | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if path is None:
        path = directory / f"pid_tuning_{datetime.now():%Y%m%d_%H%M%S}.json"
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "baseline": asdict(baseline),
        "config": asdict(config),
        "trials": [result.to_dict(include_samples=True) for result in history],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
