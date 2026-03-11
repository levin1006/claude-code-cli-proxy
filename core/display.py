"""
ANSI formatting, box drawing, account helpers, and status dashboard rendering.
Depends on: constants, paths, config, api, quota, usage, proxy
"""

import json
import os
import re
import shutil
import unicodedata
import urllib.error
import urllib.parse
from datetime import datetime, timezone

from constants import (
    _C_BOLD, _C_DIM, _C_GREEN, _C_RED, _C_RESET,
    _PROVIDER_BRAND_COLORS,
    PORTS, PROVIDERS,
)
from paths import get_token_dir, _token_prefixes_for_provider
from config import _parse_iso
from api import _management_api, _proxy_api, _read_secret_key
from quota import _QUOTA_FETCHERS, _quota_cache_load, _quota_cache_save
from usage import (
    _usage_cumulative_apply_to_usage_data, _usage_cumulative_update_from_live,
    _usage_snapshot_load,
)
from proxy import get_status

# Module-level mutable state for box drawing edge color
_BOX_EDGE_COLOR = ""


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_tokens(n):
    """20484733 → '20.5M'"""
    if n >= 1_000_000:
        return "{:.1f}M".format(n / 1_000_000)
    if n >= 1_000:
        return "{:.1f}K".format(n / 1_000)
    return str(n)


def _time_ago(iso_str):
    """ISO timestamp → '23m ago', '2h ago'"""
    dt = _parse_iso(iso_str)
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (now - dt).total_seconds()
    if delta < 60:
        return "just now"
    if delta < 3600:
        return "{}m ago".format(int(delta / 60))
    if delta < 86400:
        return "{}h ago".format(int(delta / 3600))
    return "{}d ago".format(int(delta / 86400))


def _fmt_local_dt(iso_str):
    """ISO timestamp → local time 'YYYY-MM-DD HH:MM:SS'."""
    dt = _parse_iso(iso_str)
    if not dt:
        return ""
    local_dt = dt.astimezone()
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_quota_bar(used_pct):
    """0-100 → colored '████████░░  80%' (10-block bar + percentage). Shows used amount."""
    pct = max(0, min(100, int(used_pct)))
    filled = round(pct / 10)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    if pct >= 80:
        color = _C_RED      # heavy use → red
    elif pct >= 40:
        color = "\033[33m"  # yellow
    else:
        color = ""          # low use → default
    reset = _C_RESET if color else ""
    return "{}{}{} {:>3}%".format(color, bar, reset, pct)


def _quota_window_rank(model_id, info):
    """Sort key for quota rows: 5h windows first, then 7d, then others."""
    text = "{} {}".format(model_id or "", (info or {}).get("display", "")).lower()
    if "5h" in text or "five_hour" in text or "primary_window" in text:
        return 0
    if "7d" in text or "seven_day" in text or "secondary_window" in text:
        return 1
    return 2


# ---------------------------------------------------------------------------
# ANSI / terminal utilities
# ---------------------------------------------------------------------------

def _supports_truecolor():
    ct = (os.environ.get("COLORTERM") or "").lower()
    if "truecolor" in ct or "24bit" in ct:
        return True
    term = (os.environ.get("TERM") or "").lower()
    if "direct" in term:
        return True
    return False


def _provider_frame_color(provider):
    rgb, fallback = _PROVIDER_BRAND_COLORS.get(provider, ((0, 0, 0), ""))
    if not fallback:
        return ""
    if _supports_truecolor():
        r, g, b = rgb
        return "\033[38;2;{};{};{}m".format(r, g, b)
    return fallback


def _strip_ansi(s):
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _visible_len(s):
    """ANSI 제거 + 동아시아 전각폭 기준으로 실제 표시 폭 계산."""
    plain = _strip_ansi(s)
    w = 0
    for ch in plain:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _clip_visible(s, max_visible):
    """ANSI 코드 보존 상태로 표시 폭 max_visible까지 안전하게 자른다."""
    if max_visible <= 0:
        return ""
    out = []
    i = 0
    vis = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\033":
            m = re.match(r"\033\[[0-9;]*m", s[i:])
            if m:
                seq = m.group(0)
                out.append(seq)
                i += len(seq)
                continue
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if vis + ch_w > max_visible:
            break
        out.append(ch)
        vis += ch_w
        i += 1
    if not "".join(out).endswith(_C_RESET):
        out.append(_C_RESET)
    return "".join(out)


# ---------------------------------------------------------------------------
# Box drawing
# ---------------------------------------------------------------------------

def _box_line(text, width, edge_color=""):
    """║  text    ║ 형태로 패딩. ANSI + CJK 폭까지 고려해 정렬.

    edge_color가 주어지면 좌우 세로 테두리(║)에만 색을 적용한다.
    기본값은 _BOX_EDGE_COLOR.
    """
    edge_color = edge_color or _BOX_EDGE_COLOR
    max_visible = width - 4
    inner = _clip_visible(text, max_visible)
    pad = max_visible - _visible_len(inner)
    if edge_color:
        return "{}\u2551{} {}{} {}\u2551{}".format(
            edge_color, _C_RESET, inner, " " * max(0, pad), edge_color, _C_RESET
        )
    return "\u2551 {}{} \u2551".format(inner, " " * max(0, pad))


def _box_top(width):
    return "\u2554" + "\u2550" * (width - 2) + "\u2557"


def _box_bottom(width):
    return "\u255a" + "\u2550" * (width - 2) + "\u255d"


def _box_sep(width):
    return "\u2560" + "\u2550" * (width - 2) + "\u2563"


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

def _acct_status_label(f):
    """Compute (indicator_str, status_str, is_degraded) for an auth-file entry.

    Degraded = permanent errors (403, 401) or explicitly disabled.
    Temporary rate limits (429) are shown as 'limited' but NOT degraded.
    """
    disabled     = f.get("disabled", False)
    unavailable  = f.get("unavailable", False)
    status_field = f.get("status", "")
    msg          = f.get("status_message", "")

    # Extract upstream HTTP error code from status_message JSON if present
    http_code = None
    if msg:
        try:
            http_code = json.loads(msg).get("error", {}).get("code")
        except Exception:
            pass

    if disabled or status_field == "disabled":
        return _C_DIM + "\u25cb" + _C_RESET, _C_DIM + "disabled" + _C_RESET, False

    if unavailable or status_field == "error":
        if http_code == 429:
            return (_C_DIM + "\u26a1" + _C_RESET,
                    _C_DIM + "limited " + _C_RESET, False)
        elif http_code == 403:
            return _C_RED + "\u00d7" + _C_RESET, _C_RED + "denied  " + _C_RESET, True
        elif http_code == 401:
            return _C_RED + "\u00d7" + _C_RESET, _C_RED + "expired " + _C_RESET, True
        else:
            return _C_RED + "\u00d7" + _C_RESET, _C_RED + "error   " + _C_RESET, True

    return (_C_GREEN + "\u25cf" + _C_RESET,
            _C_GREEN + (status_field or "active") + _C_RESET, False)


def _account_identity(f):
    ai = (f.get("auth_index") or "").strip()
    if ai:
        return "auth_index:" + ai
    path = os.path.basename((f.get("path") or f.get("name") or "").strip())
    email = (f.get("email") or f.get("account") or "").strip()
    return "fallback:{}:{}".format(path, email)


def _dedupe_auth_files(auth_data, provider=None):
    """Deduplicate auth-files entries caused by mixed relative/absolute path reporting.
    If provider is given, also filter files to only those matching the provider's prefixes.

    Keep the newest record per auth_index (fallback: path/name/email tuple).
    """
    if not auth_data or "files" not in auth_data:
        return auth_data

    files = auth_data.get("files") or []
    if not files:
        return auth_data

    # prefix filter: only keep files belonging to this provider
    if provider:
        prefixes = tuple(
            "{}-".format(pfx) for pfx in _token_prefixes_for_provider(provider)
        )
        def _fname(f):
            name = (f.get("name") or f.get("id") or "").strip()
            if name:
                return name.split("/")[-1].split("\\")[-1]
            path = (f.get("path") or "").strip()
            return path.replace("\\", "/").split("/")[-1]
        files = [f for f in files if _fname(f).startswith(prefixes)]

    def _ts(f):
        return (
            f.get("updated_at")
            or f.get("last_refresh")
            or f.get("modtime")
            or f.get("created_at")
            or ""
        )

    picked = {}
    for f in files:
        k = _account_identity(f)
        cur = picked.get(k)
        if cur is None or _ts(f) >= _ts(cur):
            picked[k] = f

    out = dict(auth_data)
    out["files"] = sorted(picked.values(), key=lambda x: (x.get("email") or x.get("account") or x.get("name") or ""))
    return out


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------

def _aggregate_per_account(usage_data):
    """Aggregate usage stats per account from /v0/management/usage response."""
    account_stats = {}
    if not usage_data:
        return account_stats
    for api_data in usage_data.get("usage", {}).get("apis", {}).values():
        for model_data in api_data.get("models", {}).values():
            for detail in model_data.get("details", []):
                src = detail.get("source", "unknown")
                tokens = detail.get("tokens", {})
                tok = tokens.get("total_tokens", 0)
                ts  = detail.get("timestamp", "")
                failed = detail.get("failed", False)
                if src not in account_stats:
                    account_stats[src] = {
                        "requests": 0, "tokens": 0, "fails": 0,
                        "input": 0, "output": 0, "reasoning": 0,
                        "last_time": "", "last_tok": 0,
                        "last_input": 0, "last_output": 0, "last_reasoning": 0,
                    }
                account_stats[src]["requests"] += 1
                account_stats[src]["tokens"] += tok
                account_stats[src]["input"] += int(tokens.get("input_tokens", 0) or 0)
                account_stats[src]["output"] += int(tokens.get("output_tokens", 0) or 0)
                account_stats[src]["reasoning"] += int(tokens.get("reasoning_tokens", 0) or 0)
                if failed:
                    account_stats[src]["fails"] += 1
                if ts > account_stats[src]["last_time"]:
                    account_stats[src]["last_time"] = ts
                    account_stats[src]["last_tok"] = tok
                    account_stats[src]["last_input"] = int(tokens.get("input_tokens", 0) or 0)
                    account_stats[src]["last_output"] = int(tokens.get("output_tokens", 0) or 0)
                    account_stats[src]["last_reasoning"] = int(tokens.get("reasoning_tokens", 0) or 0)
    return account_stats


def _prefetch_provider_data(base_dir, provider, fetch_quota=False, fetch_check=False):
    """Fetch all management data for a provider (designed for parallel threading).

    fetch_quota: also call upstream provider quota APIs (slower, ~3-5s per account)
    fetch_check: also fetch per-account model lists from management API
    """
    import threading
    result = {
        "status": None, "auth_data": None, "usage_data": None,
        "auth_error": False, "models_per_account": {},
        "quota_data": {},   # {account_name: quota_dict or None}
        "proxy_models": None,
        "usage_source": "none",            # live | snapshot | none
        "usage_snapshot_at": None,          # ISO string when source=snapshot
    }
    result["status"] = get_status(base_dir, provider)
    if result["status"]["running"] and result["status"]["healthy"]:
        try:
            secret = _read_secret_key(base_dir, provider)
            result["auth_data"] = _dedupe_auth_files(
                _management_api(provider, "auth-files", secret), provider=provider)
            result["usage_data"] = _management_api(provider, "usage", secret)
            if isinstance(result["usage_data"], dict):
                _usage_cumulative_update_from_live(provider, result["usage_data"])
                result["usage_data"] = _usage_cumulative_apply_to_usage_data(provider, result["usage_data"])
                result["usage_source"] = "live"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                result["auth_error"] = True
        except Exception:
            pass

        if result["auth_data"] and not result["auth_error"]:
            files = result["auth_data"].get("files", [])
            secret = _read_secret_key(base_dir, provider)
            threads = []

            # per-account model lists (for routing-pool detection)
            if fetch_check:
                mpa = result["models_per_account"]

                def _fetch_models(f, out, _pvd=provider, _sec=secret):
                    name = f.get("name") or f.get("id") or ""
                    if not name:
                        return
                    try:
                        qs = "auth-files/models?name={}".format(
                            urllib.parse.quote(name, safe="@.-_")
                        )
                        data = _management_api(_pvd, qs, _sec)
                        out[name] = data.get("models", [])
                    except Exception:
                        out[name] = None

                threads += [threading.Thread(target=_fetch_models, args=(f, mpa))
                            for f in files]

            # per-account upstream quota
            if fetch_quota and provider in _QUOTA_FETCHERS:
                fetcher = _QUOTA_FETCHERS[provider]
                qpa = result["quota_data"]

                def _fetch_quota_one(f, out, _pvd=provider, _sec=secret, _fn=fetcher):
                    name = f.get("name") or f.get("id") or ""
                    auth_index = f.get("auth_index", "")
                    if not name or not auth_index:
                        return
                    cached = _quota_cache_load(_pvd, auth_index)
                    if cached is not None:
                        out[name] = cached
                        return
                    data = _fn(_pvd, _sec, auth_index)
                    if data is not None:
                        _quota_cache_save(_pvd, auth_index, data)
                    out[name] = data

                threads += [threading.Thread(target=_fetch_quota_one, args=(f, qpa))
                            for f in files]

            # proxy model list (for check panel)
            if fetch_check:
                def _fetch_proxy_models(_pvd=provider):
                    try:
                        result["proxy_models"] = _proxy_api(_pvd, "v1/models")
                    except Exception:
                        pass
                threads.append(threading.Thread(target=_fetch_proxy_models))

            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

    if result["usage_source"] == "none":
        snap = _usage_snapshot_load(provider)
        if snap:
            result["usage_data"] = _usage_cumulative_apply_to_usage_data(provider, snap.get("usage_data"))
            result["usage_source"] = "snapshot"
            result["usage_snapshot_at"] = snap.get("captured_at_iso")

    return result


# ---------------------------------------------------------------------------
# Status dashboard rendering
# ---------------------------------------------------------------------------

def _print_status_dashboard(base_dir, provider, status, W,
                            auth_data=None, usage_data=None, auth_error=False,
                            models_per_account=None, quota_data=None,
                            proxy_models=None, show_check=False,
                            selected_account_name=None,
                            selected_account_key=None,
                            frame_color="",
                            usage_source="none",
                            usage_snapshot_at=None):
    global _BOX_EDGE_COLOR
    """Print rich dashboard panel for a provider.

    quota_data:    {account_name: quota_dict} — show Quota section when present
    show_check:    show Account Validation + Available Models section (replaces cc-proxy-check)
    """
    running = status["running"]
    healthy = status["healthy"]
    port = PORTS[provider]

    if running:
        dot_str = _C_GREEN + "\u25cf" + _C_RESET
        state_str = "running"
    else:
        dot_str = _C_DIM + "\u25cb" + _C_RESET
        state_str = _C_DIM + "stopped" + _C_RESET

    files = auth_data.get("files", []) if auth_data else []
    acct_suffix = "  {} accounts".format(len(files)) if files else ""
    header = "  {}  :{}   {} {}{}".format(provider, port, dot_str, state_str, acct_suffix)
    prev_edge_color = _BOX_EDGE_COLOR
    if frame_color:
        _BOX_EDGE_COLOR = frame_color
        print(frame_color + _box_sep(W) + _C_RESET)
        print(_box_line(header, W))
    else:
        _BOX_EDGE_COLOR = ""
        print(_box_sep(W))
        print(_box_line(header, W))

    if auth_error:
        hint = _C_RED + "  auth failed" + _C_RESET + " \u2014 set CC_PROXY_SECRET env var"
        print(_box_line(hint, W))
        _BOX_EDGE_COLOR = prev_edge_color
        return

    # No data to display: compact view
    u = usage_data.get("usage", {}) if usage_data else {}
    has_accounts = bool(files)
    has_usage = bool(usage_data and isinstance(u, dict))
    if not has_accounts and not has_usage:
        _BOX_EDGE_COLOR = prev_edge_color
        return

    divider = "  " + "\u2500" * (W - 6)

    all_ok = True
    if has_accounts:
        # --- accounts section ---
        token_dir_path = str(get_token_dir(base_dir, create=False))
        max_path_w = W - 22
        if len(token_dir_path) > max_path_w:
            token_dir_path = "\u2026" + token_dir_path[-(max_path_w - 1):]
        token_dir_line = "  " + _C_DIM + "token-dir: {}".format(token_dir_path) + _C_RESET
        print(_box_line("", W))
        print(_box_line("  Accounts", W))
        print(_box_line(token_dir_line, W))
        print(_box_line(divider, W))
        for f in files:
            email = f.get("email", f.get("name") or f.get("id", "?"))
            name = f.get("name") or f.get("id", "")
            last_refresh = f.get("last_refresh", "")
            plan_type = (f.get("id_token") or {}).get("plan_type", "")
            time_str = _time_ago(last_refresh) if last_refresh else ""
            model_list = models_per_account.get(name) if models_per_account else None
            mc_str = "       \u2014" if model_list is None else (
                "{:>2} models".format(len(model_list)) if len(model_list) > 0 else " 0 models"
            )
            indicator, acct_status, is_degraded = _acct_status_label(f)

            # Override: proxy-active but 0 models → not in routing pool
            if (not f.get("disabled", False)
                    and f.get("status", "") not in ("error",)
                    and not f.get("unavailable", False)
                    and model_list is not None
                    and len(model_list) == 0):
                indicator = _C_DIM + "\u26a0" + _C_RESET
                acct_status = _C_DIM + "no models" + _C_RESET
                is_degraded = True

            if is_degraded:
                all_ok = False

            label = email
            if plan_type:
                suffix = " [{}]".format(plan_type)
                label = email[:max(0, 26 - len(suffix))] + suffix
            if selected_account_key:
                is_selected = (_account_identity(f) == selected_account_key)
            else:
                is_selected = bool(selected_account_name and name == selected_account_name)
            cursor = "\u25b8" if is_selected else " "
            row = "{} {:<26}  {:>9}  {:>8}  {} {}".format(
                cursor, label[:26], mc_str, time_str, indicator, acct_status
            )
            print(_box_line(row, W))

    pass

    # --- usage section ---
    total_req = u.get("total_requests", 0)
    ok_req = u.get("success_count", 0)
    fail_req = u.get("failure_count", 0)
    total_tok = u.get("total_tokens", 0)

    print(_box_line("", W))
    if usage_source == "live":
        usage_title = "  Usage (live)"
    elif usage_source == "snapshot":
        age = _time_ago(usage_snapshot_at) if usage_snapshot_at else ""
        usage_title = "  Usage (snapshot, {})".format(age) if age else "  Usage (snapshot)"
    else:
        usage_title = "  Usage"
    print(_box_line(usage_title, W))
    print(_box_line(divider, W))

    fail_str = (
        _C_RED + "{} fail".format(fail_req) + _C_RESET if fail_req > 0
        else "{} fail".format(fail_req)
    )
    summary = "  Total: {} requests ({} ok, {})  \u00b7  {} tokens".format(
        total_req, ok_req, fail_str, _fmt_tokens(total_tok)
    )
    print(_box_line(summary, W))

    # Models
    apis = u.get("apis", {})
    model_stats = {}
    for api_data in apis.values():
        for model_name, model_data in api_data.get("models", {}).items():
            details = model_data.get("details", [])
            if model_name not in model_stats:
                model_stats[model_name] = {
                    "requests": 0, "fails": 0,
                    "input": 0, "output": 0, "reasoning": 0,
                    "last_time": "",
                    "last_input": 0, "last_output": 0, "last_reasoning": 0,
                }
            s = model_stats[model_name]
            for d in details:
                toks = d.get("tokens", {})
                s["requests"] += 1
                s["input"]    += int(toks.get("input_tokens",     0) or 0)
                s["output"]   += int(toks.get("output_tokens",    0) or 0)
                s["reasoning"] += int(toks.get("reasoning_tokens", 0) or 0)
                if d.get("failed", False):
                    s["fails"] += 1
                ts = d.get("timestamp", "")
                if ts > s["last_time"]:
                    s["last_time"]      = ts
                    s["last_input"]     = int(toks.get("input_tokens",     0) or 0)
                    s["last_output"]    = int(toks.get("output_tokens",    0) or 0)
                    s["last_reasoning"] = int(toks.get("reasoning_tokens", 0) or 0)

    _C_CYAN   = "\033[36m"
    _C_YELLOW = "\033[33m"
    _C_TEAL   = "\033[38;5;73m"   # muted blue-green for input
    _C_PURPLE = "\033[38;5;139m" # muted purple for output
    _DOT      = " \u00b7 "
    _DIM_DOT  = _C_DIM + _DOT + _C_RESET

    def _p(text, width):
        return text + " " * max(0, width - _visible_len(text))

    def _fmt_tok_compact(inp, out, rsn):
        i_s = _C_TEAL   + _fmt_tokens(inp) + _C_RESET
        o_s = _C_PURPLE + _fmt_tokens(out) + _C_RESET
        r_val = _fmt_tokens(rsn) if rsn > 0 else "0"
        _C_AMBER = "\033[38;5;136m"   # soft amber for reasoning
        r_s = (_C_AMBER + r_val + _C_RESET) if rsn > 0 else (_C_DIM + r_val + _C_RESET)
        return "i{}/o{}/r{}".format(i_s, o_s, r_s)

    # Daily stats (shown before models)
    requests_by_day = u.get("requests_by_day", {})
    tokens_by_day = u.get("tokens_by_day", {})
    all_days = sorted(set(list(requests_by_day.keys()) + list(tokens_by_day.keys())))
    if all_days:
        print(_box_line("", W))
        print(_box_line("  Daily:", W))
        for day in all_days[-7:]:
            day_req = requests_by_day.get(day, 0)
            day_tok = tokens_by_day.get(day, 0)
            tok_str = _C_TEAL + _fmt_tokens(day_tok) + _C_RESET + " tokens"
            row = "    {}{}{}{}{}{}{}".format(
                day, _DIM_DOT, "{:>3}".format(day_req), " req", _DIM_DOT, tok_str, ""
            )
            print(_box_line(row, W))

    if model_stats:
        print(_box_line("", W))
        print(_box_line("  Models:", W))

        W_MODEL = 22
        W_MREQ  = 3
        W_MTOK  = 15
        W_MLAST = 15

        h_model = _p(_C_BOLD + "model" + _C_RESET, W_MODEL)
        h_mreq  = _p(_C_BOLD + "req" + _C_RESET, W_MREQ)
        h_mtok  = _p(_C_BOLD + "total token" + _C_RESET, W_MTOK)
        h_mlast = _p(_C_BOLD + "last token" + _C_RESET, W_MLAST)
        h_mtime = _C_BOLD + "last req." + _C_RESET
        mheader = "    " + h_model + _DIM_DOT + h_mreq + _DIM_DOT + h_mtok + _DIM_DOT + h_mlast + _DIM_DOT + h_mtime
        print(_box_line(mheader, W))
        print(_box_line(divider, W))

        for mname, mdata in sorted(model_stats.items(), key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["reasoning"])):
            fails     = mdata["fails"]
            total     = mdata["requests"]
            req_color = _C_RED if fails > 0 else _C_GREEN
            req_str   = req_color + str(total) + _C_RESET
            tok_str   = _fmt_tok_compact(mdata["input"],      mdata["output"],      mdata["reasoning"])
            last_str  = _fmt_tok_compact(mdata["last_input"], mdata["last_output"], mdata["last_reasoning"])
            dt_str    = _C_DIM + (_fmt_local_dt(mdata["last_time"]) if mdata["last_time"] else "") + _C_RESET
            col1 = _p(_C_CYAN + mname[:W_MODEL] + _C_RESET, W_MODEL)
            col2 = _p(req_str, W_MREQ)
            col3 = _p(tok_str, W_MTOK)
            col4 = _p(last_str, W_MLAST)
            row = "    " + col1 + _DIM_DOT + col2 + _DIM_DOT + col3 + _DIM_DOT + col4 + _DIM_DOT + dt_str
            print(_box_line(row, W))


    # Per-account stats
    acct_stats = _aggregate_per_account(usage_data)
    if acct_stats:
        print(_box_line("", W))
        print(_box_line("  Per-account:", W))

        W_ACCT = 22
        W_REQ  = 3
        W_TOT  = 15
        W_LAST = 15

        # Header
        h_acct = _p(_C_BOLD + "account" + _C_RESET, W_ACCT)
        h_req  = _p(_C_BOLD + "req" + _C_RESET, W_REQ)
        h_tot  = _p(_C_BOLD + "total token" + _C_RESET, W_TOT)
        h_last = _p(_C_BOLD + "last token" + _C_RESET, W_LAST)
        h_time = _C_BOLD + "last req." + _C_RESET
        header = "    " + h_acct + _DIM_DOT + h_req + _DIM_DOT + h_tot + _DIM_DOT + h_last + _DIM_DOT + h_time
        print(_box_line(header, W))
        print(_box_line(divider, W))

        for acct, adata in sorted(acct_stats.items(), key=lambda x: -x[1]["tokens"]):
            total  = adata["requests"]
            fails  = adata["fails"]
            dt_str = _fmt_local_dt(adata["last_time"]) if adata["last_time"] else ""

            req_color = _C_RED if fails > 0 else _C_GREEN
            req_str = req_color + str(total) + _C_RESET

            tot_tok  = _fmt_tok_compact(adata.get("input", 0), adata.get("output", 0), adata.get("reasoning", 0))
            last_tok = _fmt_tok_compact(adata.get("last_input", 0), adata.get("last_output", 0), adata.get("last_reasoning", 0))

            col1 = _p(_C_CYAN + acct[:W_ACCT] + _C_RESET, W_ACCT)
            col2 = _p(req_str, W_REQ)
            col3 = _p(tot_tok, W_TOT)
            col4 = _p(last_tok, W_LAST)
            col5 = _C_DIM + dt_str + _C_RESET

            row = "    " + col1 + _DIM_DOT + col2 + _DIM_DOT + col3 + _DIM_DOT + col4 + _DIM_DOT + col5
            print(_box_line(row, W))


    # --- quota section (shown when --quota flag used) ---
    if quota_data and files:
        QUOTA_MODELS = {
            "antigravity": {"gemini-3.1-pro-high", "gemini-3.1-pro-low",
                            "gemini-3-flash", "claude-sonnet-4-6",
                            "claude-opus-4-6-thinking", "gpt-oss-120b-medium"},
        }
        shown_models = QUOTA_MODELS.get(provider, None)  # None = show all
        print(_box_line("", W))
        qdiv = "  \u2500\u2500 quota " + "\u2500" * max(0, W - 16)
        print(_box_line(qdiv, W))
        for f in files:
            name = f.get("name") or f.get("id", "")
            email = f.get("email", f.get("name") or f.get("id", "?"))
            plan_type = (f.get("id_token") or {}).get("plan_type", "")
            label = email
            if plan_type:
                suffix = " [{}]".format(plan_type)
                label = email[:max(0, 28 - len(suffix))] + suffix
            qd = quota_data.get(name)
            if qd is None:
                print(_box_line("  {}  {}(unavailable){}".format(
                    label[:30], _C_DIM, _C_RESET), W))
                continue
            if "__error__" in qd:
                einfo = qd["__error__"]
                msg = einfo.get("reset_str", "error")
                print(_box_line("  {}  {}\u00d7 {}{}".format(
                    label[:26], _C_RED, msg[:35], _C_RESET), W))
                continue
            if not qd:
                print(_box_line("  {}  {}(no quota data){}".format(
                    label[:26], _C_DIM, _C_RESET), W))
                continue
            print(_box_line("  {}".format(label[:34]), W))
            items = []
            for model_id, info in qd.items():
                if shown_models and model_id not in shown_models:
                    continue
                items.append((model_id, info))
            items.sort(key=lambda x: (_quota_window_rank(x[0], x[1]), -x[1]["used_pct"]))
            for model_id, info in items:
                display = info.get("display", model_id)
                bar = _fmt_quota_bar(info["used_pct"])
                reset = info["reset_str"]
                reset_col = "  resets {}".format(reset) if reset else ""
                row = "    {:<26}  {}{}".format(display[:26], bar, reset_col)
                print(_box_line(row, W))

    # --- check section (shown when --check flag used) ---
    if show_check and files:
        cdiv = "  " + "\u2500" * (W - 6)
        print(_box_line("", W))
        if not files:
            verdict = "  No accounts configured"
        elif all_ok:
            verdict = _C_GREEN + "  \u2714 All accounts OK" + _C_RESET
        else:
            verdict = _C_RED + "  \u26a0 Some accounts degraded" + _C_RESET
        print(_box_line(verdict, W))
        if models_per_account:
            def _mid(m):
                return m.get("id", "") if isinstance(m, dict) else str(m)
            acct_model_ids = sorted(
                {_mid(m) for mlist in models_per_account.values() if mlist for m in mlist
                 if _mid(m)}
            )
        else:
            acct_model_ids = None

        model_ids = acct_model_ids if acct_model_ids is not None else (
            sorted(m.get("id", "") for m in (proxy_models or {}).get("data", []))
        )
        if model_ids:
            print(_box_line("", W))
            print(_box_line("  Available Models ({})".format(len(model_ids)), W))
            print(_box_line(cdiv, W))
            for mid in model_ids:
                print(_box_line("    {}".format(mid[:60]), W))

    print(_box_line("", W))
    _BOX_EDGE_COLOR = prev_edge_color
