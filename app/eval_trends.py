"""Eval trend history + regression alerts (issue #126, Workstream K).

Records evaluation metric points (from /v1/evaluate and experiment summaries) in a
bounded in-memory store and derives trend summaries + regression alerts by comparing
recent metric values to configured thresholds (reuses eval_datasets.regression
threshold shapes where applicable). Config-driven; recording is lightweight and
bounded. No ui/* imports.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional

import yaml

from core.evaluation.regression_gate import DEFAULT_CONFIG_DIR, normalize_thresholds


def _load_eval_cfg(config_dir: Optional[Any]) -> Dict[str, Any]:
    try:
        base = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
        path = base / "eval_datasets.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data.get("eval_datasets"), Mapping):
            data = data["eval_datasets"]
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _flatten_metrics(metrics: Any, prefix: str = "") -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not isinstance(metrics, Mapping):
        return out
    for key, value in metrics.items():
        name = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        num = _num(value)
        if num is not None:
            out[name] = num
        elif isinstance(value, Mapping):
            out.update(_flatten_metrics(value, name))
    return out


class EvalTrendStore:
    """Bounded evaluation trend history with alert derivation."""

    def __init__(
        self,
        max_entries: int = 2000,
        config_dir: Optional[Any] = None,
        store: Optional[Any] = None,
    ):
        self.max_entries = max(1, int(max_entries))
        self.config_dir = config_dir
        self._points: Deque[Dict[str, Any]] = deque(maxlen=self.max_entries)
        self._lock = threading.Lock()
        self._store = store
        self._prefix = "eval_trends"

    def _config(self) -> Dict[str, Any]:
        return _load_eval_cfg(self.config_dir)

    def record(
        self,
        metrics: Any,
        *,
        source: str = "evaluate",
        evaluator: Optional[str] = None,
        evaluator_key: Optional[str] = None,
        dataset: Optional[str] = None,
        tenant: Optional[str] = None,
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        flat = _flatten_metrics(metrics)
        if not flat:
            return None
        point = {
            "id": str(uuid.uuid4()),
            "timestamp": round(time.time(), 6),
            "source": source,
            "evaluator": evaluator,
            "evaluator_key": evaluator_key,
            "dataset": dataset,
            "tenant": tenant,
            "request_id": request_id,
            "metrics": flat,
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self._points.append(point)
            if self._store is not None:
                try:
                    self._store.set(f"{self._prefix}:point:{point['id']}", point)
                except Exception:
                    pass
        return point

    def _points_for(self, tenant: Optional[str]) -> List[Dict[str, Any]]:
        with self._lock:
            points = list(self._points)
        if tenant is None:
            return points
        return [p for p in points if p.get("tenant") == str(tenant)]

    def trends(
        self,
        *,
        tenant: Optional[str] = None,
        evaluator: Optional[str] = None,
        dataset: Optional[str] = None,
        metric: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        points = self._points_for(tenant)
        if evaluator is not None:
            points = [p for p in points if p.get("evaluator_key") == evaluator or p.get("evaluator") == evaluator]
        if dataset is not None:
            points = [p for p in points if p.get("dataset") == dataset]
        points = points[-max(1, int(limit)) :]

        series: Dict[str, List[Dict[str, Any]]] = {}
        for point in points:
            for name, value in (point.get("metrics") or {}).items():
                if metric is not None and name != metric:
                    continue
                series.setdefault(name, []).append(
                    {
                        "timestamp": point["timestamp"],
                        "value": value,
                        "request_id": point.get("request_id"),
                        "evaluator": point.get("evaluator_key") or point.get("evaluator"),
                        "dataset": point.get("dataset"),
                    }
                )

        summaries: Dict[str, Any] = {}
        for name, values in series.items():
            nums = [v["value"] for v in values]
            latest = nums[-1]
            prev = nums[-2] if len(nums) >= 2 else None
            summaries[name] = {
                "count": len(nums),
                "latest": round(latest, 6),
                "mean": round(sum(nums) / len(nums), 6),
                "min": round(min(nums), 6),
                "max": round(max(nums), 6),
                "delta": round(latest - prev, 6) if prev is not None else None,
                "trend": ("regressing" if prev is not None and latest < prev else "improving" if prev is not None and latest > prev else "stable"),
            }

        payload: Dict[str, Any] = {
            "num_points": len(points),
            "series": series,
            "summaries": summaries,
        }
        if tenant is not None:
            payload["tenant"] = str(tenant)
        return payload

    def alerts(self, *, tenant: Optional[str] = None) -> Dict[str, Any]:
        cfg = self._config()
        regression = cfg.get("regression") if isinstance(cfg.get("regression"), Mapping) else {}
        thresholds = normalize_thresholds(regression.get("thresholds") if isinstance(regression, Mapping) else {})
        # per-dataset thresholds are surfaced as alert thresholds too
        ds_map = regression.get("datasets") if isinstance(regression, Mapping) else {}
        extra: Dict[str, float] = {}
        if isinstance(ds_map, Mapping):
            for _name, spec in ds_map.items():
                if isinstance(spec, Mapping):
                    extra.update(normalize_thresholds(spec.get("thresholds") or spec))
        for k, v in extra.items():
            thresholds.setdefault(k, v)

        trend = self.trends(tenant=tenant, limit=200)
        summaries = trend.get("summaries") or {}
        alerts: List[Dict[str, Any]] = []
        for metric_name, minimum in thresholds.items():
            summary = summaries.get(metric_name)
            if summary is None:
                continue
            latest = summary["latest"]
            if latest + 1e-12 < float(minimum):
                alerts.append(
                    {
                        "metric": metric_name,
                        "latest": latest,
                        "threshold": float(minimum),
                        "delta": round(latest - float(minimum), 6),
                        "severity": "critical" if latest < float(minimum) * 0.9 else "warning",
                        "status": "firing",
                        "message": f"{metric_name} regressed: {latest:.6f} < {float(minimum):.6f}",
                    }
                )
        payload: Dict[str, Any] = {
            "num_alerts": len(alerts),
            "thresholds": thresholds,
            "alerts": alerts,
            "regression_enabled": bool(regression.get("enabled", False)) if isinstance(regression, Mapping) else False,
        }
        if tenant is not None:
            payload["tenant"] = str(tenant)
        return payload
