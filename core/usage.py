"""
Usage tracking: snapshots and cumulative totals.
Depends on: constants
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone

from constants import USAGE_SNAPSHOT_SCHEMA_VERSION, USAGE_CUMULATIVE_SCHEMA_VERSION


def _usage_snapshot_path(provider):
    """Return /tmp usage snapshot file path for a provider."""
    return os.path.join(tempfile.gettempdir(), "cc-proxy-usage-snapshot-{}.json".format(provider))


def _usage_snapshot_save(provider, usage_data, reason="stop"):
    """Persist usage snapshot atomically. Returns True on success."""
    if not isinstance(usage_data, dict):
        return False

    captured_at = time.time()
    iso = datetime.fromtimestamp(captured_at, tz=timezone.utc).isoformat()
    payload = {
        "schema_version": USAGE_SNAPSHOT_SCHEMA_VERSION,
        "provider": provider,
        "captured_at": captured_at,
        "captured_at_iso": iso,
        "reason": reason,
        "usage_data": usage_data,
    }

    path = _usage_snapshot_path(provider)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _usage_snapshot_load(provider):
    """Load usage snapshot; return dict with usage_data + metadata, or None."""
    path = _usage_snapshot_path(provider)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != USAGE_SNAPSHOT_SCHEMA_VERSION:
        return None
    if data.get("provider") != provider:
        return None
    usage_data = data.get("usage_data")
    if not isinstance(usage_data, dict):
        return None

    return {
        "usage_data": usage_data,
        "captured_at": data.get("captured_at"),
        "captured_at_iso": data.get("captured_at_iso"),
        "reason": data.get("reason", ""),
    }


def _usage_cumulative_path(provider):
    """Return /tmp cumulative usage file path for a provider."""
    return os.path.join(tempfile.gettempdir(), "cc-proxy-usage-cumulative-{}.json".format(provider))


def _usage_totals_extract(usage_data):
    """Extract top-level usage totals from usage_data dict."""
    if not isinstance(usage_data, dict):
        return None
    u = usage_data.get("usage")
    if not isinstance(u, dict):
        return None
    return {
        "total_requests": int(u.get("total_requests", 0) or 0),
        "success_count":  int(u.get("success_count", 0) or 0),
        "failure_count":  int(u.get("failure_count", 0) or 0),
        "total_tokens":   int(u.get("total_tokens", 0) or 0),
    }


def _usage_cumulative_load(provider):
    """Load cumulative usage totals for a provider; return dict or None."""
    path = _usage_cumulative_path(provider)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != USAGE_CUMULATIVE_SCHEMA_VERSION:
        return None
    if data.get("provider") != provider:
        return None

    totals = data.get("totals")
    if not isinstance(totals, dict):
        return None
    if not all(k in totals for k in ("total_requests", "success_count", "failure_count", "total_tokens")):
        return None

    return data


def _usage_cumulative_save(provider, payload):
    """Persist cumulative payload atomically."""
    path = _usage_cumulative_path(provider)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def _usage_cumulative_clear(provider):
    """Delete cumulative usage file for provider."""
    path = _usage_cumulative_path(provider)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _usage_cumulative_update_from_live(provider, usage_data):
    """Update cumulative totals by adding positive delta from current live totals."""
    current = _usage_totals_extract(usage_data)
    if current is None:
        return False

    prev = _usage_cumulative_load(provider)
    prev_live = prev.get("last_live_totals") if prev else None
    prev_total = prev.get("totals") if prev else None

    if not isinstance(prev_live, dict):
        prev_live = {k: 0 for k in current.keys()}
    if not isinstance(prev_total, dict):
        prev_total = {k: 0 for k in current.keys()}

    delta = {}
    for k, v in current.items():
        p = int(prev_live.get(k, 0) or 0)
        delta[k] = v - p if v >= p else v

    new_total = {}
    for k in current.keys():
        new_total[k] = int(prev_total.get(k, 0) or 0) + int(delta.get(k, 0) or 0)

    now_ts = time.time()
    payload = {
        "schema_version": USAGE_CUMULATIVE_SCHEMA_VERSION,
        "provider": provider,
        "updated_at": now_ts,
        "updated_at_iso": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
        "totals": new_total,
        "last_live_totals": current,
    }
    return _usage_cumulative_save(provider, payload)


def _usage_cumulative_apply_to_usage_data(provider, usage_data):
    """Overlay cumulative totals into usage_data for display continuity."""
    if not isinstance(usage_data, dict):
        return usage_data
    u = usage_data.get("usage")
    if not isinstance(u, dict):
        return usage_data

    cum = _usage_cumulative_load(provider)
    if not cum:
        return usage_data

    totals = cum.get("totals") or {}
    for k in ("total_requests", "success_count", "failure_count", "total_tokens"):
        if k in totals:
            u[k] = int(totals.get(k, 0) or 0)
    return usage_data
