"""
Quota fetching (upstream provider APIs) and result caching.
Depends on: constants, config (_fmt_reset_time)
"""

import json
import time

from constants import PORTS, QUOTA_CACHE_TTL
from config import _fmt_reset_time


def _management_api_call(provider, secret, auth_index, method, url, headers, body=None):
    """POST /v0/management/api-call → (upstream_status_code, parsed_body_dict).

    Returns (None, None) on network/management error.
    Upstream 4xx/5xx returned as-is so callers can handle them.
    """
    import urllib.request
    import urllib.error
    port = PORTS[provider]
    endpoint = "http://127.0.0.1:{}/v0/management/api-call".format(port)
    payload = {"authIndex": auth_index, "method": method, "url": url, "header": headers}
    if body:
        payload["data"] = body
    raw = json.dumps(payload).encode()
    req = urllib.request.Request(endpoint, data=raw,
                                 headers={"Authorization": "Bearer " + secret,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            outer = json.loads(resp.read())
        status_code = outer.get("status_code", 0)
        try:
            parsed_body = json.loads(outer.get("body", "{}"))
        except Exception:
            parsed_body = {}
        return status_code, parsed_body
    except Exception:
        return None, None


def _fetch_quota_antigravity(provider, secret, auth_index):
    """fetchAvailableModels → {model_id: {"used_pct": int, "reset_str": str}}"""
    url = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
    headers = {
        "Authorization": "Bearer $TOKEN$",
        "Content-Type": "application/json",
        "User-Agent": "antigravity/1.11.5 windows/amd64",
    }
    status_code, data = _management_api_call(provider, secret, auth_index, "POST", url, headers, "{}")
    if data is None:
        return None
    if status_code != 200:
        err = (data.get("error") or {}).get("message", "HTTP {}".format(status_code))
        return {"__error__": {"display": "error", "used_pct": 100, "reset_str": err[:40]}}
    result = {}
    for model_id, minfo in data.get("models", {}).items():
        qi = minfo.get("quotaInfo", {})
        frac = qi.get("remainingFraction")
        if frac is None:
            continue
        reset_str = _fmt_reset_time(qi.get("resetTime", ""))
        display = minfo.get("displayName", model_id)
        result[model_id] = {
            "display": display,
            "used_pct": int(round((1.0 - frac) * 100)),
            "reset_str": reset_str,
        }
    return result


def _fetch_quota_claude(provider, secret, auth_index):
    """oauth/usage → {window_name: {"used_pct": int, "reset_str": str}}"""
    url = "https://api.anthropic.com/api/oauth/usage"
    headers = {
        "Authorization": "Bearer $TOKEN$",
        "Content-Type": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
    }
    status_code, data = _management_api_call(provider, secret, auth_index, "GET", url, headers)
    if data is None:
        return None
    if status_code != 200:
        err = (data.get("error") or {}).get("message", "HTTP {}".format(status_code))
        return {"__error__": {"display": "error", "used_pct": 100, "reset_str": err[:40]}}
    result = {}
    window_labels = {
        "five_hour":        "5h window",
        "seven_day":        "7d window",
        "seven_day_opus":   "7d opus",
        "seven_day_sonnet": "7d sonnet",
    }
    for key, label in window_labels.items():
        w = data.get(key)
        if not w:
            continue
        util = w.get("utilization")
        if util is None:
            continue
        used_pct = min(100, int(round(util)))
        reset_str = _fmt_reset_time(w.get("resets_at", ""))
        result[key] = {"display": label, "used_pct": used_pct, "reset_str": reset_str}
    return result


def _fetch_quota_codex(provider, secret, auth_index):
    """wham/usage → {window: {"used_pct": int, "reset_str": str}}"""
    url = "https://chatgpt.com/backend-api/wham/usage"
    headers = {
        "Authorization": "Bearer $TOKEN$",
        "Content-Type": "application/json",
        "User-Agent": "codex_cli_rs/0.76.0 (Debian 13.0.0; x86_64) WindowsTerminal",
    }
    status_code, data = _management_api_call(provider, secret, auth_index, "GET", url, headers)
    if data is None:
        return None
    if status_code != 200:
        err = (data.get("error") or {}).get("message", "HTTP {}".format(status_code))
        return {"__error__": {"display": "error", "used_pct": 100, "reset_str": err[:40]}}
    result = {}
    rl = data.get("rate_limit", {})
    for wkey, label in [("primary_window", "5h window"), ("secondary_window", "7d window")]:
        w = rl.get(wkey)
        if not w:
            continue
        used_pct = min(100, int(round(w.get("used_percent", 0) or 0)))
        reset_str = _fmt_reset_time(w.get("reset_after_seconds"))
        result[wkey] = {"display": label, "used_pct": used_pct, "reset_str": reset_str}
    return result


_QUOTA_FETCHERS = {
    "antigravity": _fetch_quota_antigravity,
    "claude":      _fetch_quota_claude,
    "codex":       _fetch_quota_codex,
}


def _quota_cache_path(provider, auth_index):
    """Return /tmp cache file path for a given provider + auth_index."""
    import hashlib
    key = hashlib.md5("{}:{}".format(provider, auth_index).encode()).hexdigest()[:12]
    return "/tmp/cc-proxy-quota-{}-{}.json".format(provider, key)


def _quota_cache_load(provider, auth_index):
    """Return cached quota dict if fresh (< TTL), else None."""
    path = _quota_cache_path(provider, auth_index)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if time.time() - cached.get("fetched_at", 0) < QUOTA_CACHE_TTL:
            return cached["data"]
    except Exception:
        pass
    return None


def _quota_cache_save(provider, auth_index, data):
    """Persist quota dict to cache file with current timestamp."""
    path = _quota_cache_path(provider, auth_index)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": time.time(), "data": data}, f)
    except Exception:
        pass
