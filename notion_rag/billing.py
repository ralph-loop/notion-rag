"""Billing aggregation from Gemini API cost logs.

Reads JSONL logs from logs/*/gemini/ directories and aggregates costs
by day, month, or total period.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

LOG_BASE = Path(__file__).resolve().parent.parent / "logs"


def get_billing(period: str = "total") -> dict:
    """Aggregate Gemini API costs from log files.

    Arguments:
        period: Aggregation period: "total", "daily", or "monthly". String.

    Returns:
        dict with keys:
        - total: {embedding_cost, vision_cost, query_cost, total_cost}
        - breakdown: list of {period, embedding_cost, vision_cost, query_cost, total_cost}
          (only for "daily" or "monthly" periods, sorted chronologically)
    """
    # Scan all date directories
    entries = _scan_logs()

    if period == "total":
        totals = _aggregate_total(entries)
        return {"total": totals, "breakdown": []}
    elif period == "daily":
        breakdown = _aggregate_by(entries, key_fn=lambda ts: ts[:10])  # YYYY-MM-DD
        totals = _aggregate_total(entries)
        return {"total": totals, "breakdown": breakdown}
    elif period == "monthly":
        breakdown = _aggregate_by(entries, key_fn=lambda ts: ts[:7])  # YYYY-MM
        totals = _aggregate_total(entries)
        return {"total": totals, "breakdown": breakdown}
    else:
        raise ValueError(f"Invalid period: {period}. Use 'total', 'daily', or 'monthly'.")


def _scan_logs() -> list[dict]:
    """Scan all gemini log files and return parsed entries.

    Returns:
        list of dicts, each with at least 'timestamp', 'total_cost', '_log_type' keys.
    """
    entries = []
    if not LOG_BASE.exists():
        return entries

    for date_dir in sorted(LOG_BASE.iterdir()):
        gemini_dir = date_dir / "gemini"
        if not gemini_dir.is_dir():
            continue
        for log_file in gemini_dir.glob("*.jsonl"):
            log_type = log_file.stem  # "indexing", "query", "sync", "init"
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        entry["_log_type"] = log_type
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
    return entries


def _aggregate_total(entries: list[dict]) -> dict:
    """Aggregate all entries into a single total.

    Arguments:
        entries: List of parsed log entries. List[dict].

    Returns:
        dict with embedding_cost, vision_cost, query_cost, total_cost.
    """
    embedding_cost = 0.0
    vision_cost = 0.0
    query_cost = 0.0

    for e in entries:
        log_type = e.get("_log_type", "")
        if log_type == "indexing":
            embedding_cost += e.get("embedding_cost", 0.0)
            vision_cost += e.get("vision_cost", 0.0)
        elif log_type == "query":
            query_cost += e.get("cost", e.get("total_cost", 0.0))
        elif log_type in ("sync", "init"):
            embedding_cost += e.get("indexing_cost", 0.0)
            vision_cost += e.get("image_cost", 0.0)

    return {
        "embedding_cost": round(embedding_cost, 8),
        "vision_cost": round(vision_cost, 8),
        "query_cost": round(query_cost, 8),
        "total_cost": round(embedding_cost + vision_cost + query_cost, 8),
    }


def _aggregate_by(entries: list[dict], key_fn) -> list[dict]:
    """Aggregate entries by a time-based key function.

    Arguments:
        entries: List of parsed log entries. List[dict].
        key_fn: Function that takes a timestamp string and returns the grouping key. Callable.

    Returns:
        list of dicts sorted by period key, each with period, embedding_cost,
        vision_cost, query_cost, total_cost.
    """
    groups = defaultdict(list)
    for e in entries:
        ts = e.get("timestamp", "")
        if ts:
            key = key_fn(ts)
            groups[key].append(e)

    result = []
    for key in sorted(groups.keys()):
        agg = _aggregate_total(groups[key])
        agg["period"] = key
        result.append(agg)
    return result
