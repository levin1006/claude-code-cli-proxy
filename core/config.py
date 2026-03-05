"""
YAML config rewriting, token parsing/validation, and date formatting utilities.
Also provides _parse_iso and _fmt_reset_time used by quota.py and display.py.
Depends on: constants, paths
"""

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from constants import LOGIN_FLAGS
from paths import (
    get_binary_path, get_config_file, get_token_dir, get_token_files,
)


def rewrite_port_in_config(config_path, port):
    text = config_path.read_text(encoding="utf-8")
    if re.search(r"^\s*port\s*:\s*\d+", text, re.MULTILINE):
        text = re.sub(r"(?m)^(\s*port\s*:\s*)\d+", r"\g<1>{}".format(port), text)
    else:
        text = "port: {}\n".format(port) + text
    config_path.write_text(text, encoding="utf-8")


def rewrite_auth_dir_in_config(config_path, auth_dir):
    text = config_path.read_text(encoding="utf-8")
    auth_dir = str(Path(auth_dir).expanduser().resolve())
    if re.search(r"^\s*auth-dir\s*:", text, re.MULTILINE):
        text = re.sub(
            r"(?m)^(\s*auth-dir\s*:\s*).*$",
            r'\g<1>"{}"'.format(auth_dir),
            text,
        )
    else:
        text = "auth-dir: \"{}\"\n".format(auth_dir) + text
    config_path.write_text(text, encoding="utf-8")


def rewrite_secret_in_config(config_path, secret):
    text = config_path.read_text(encoding="utf-8")
    text = re.sub(
        r'(?m)^(\s*secret-key:\s*)"[^"]*"',
        r'\g<1>"{}"'.format(secret),
        text
    )
    config_path.write_text(text, encoding="utf-8")


def _parse_iso(s):
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    try:
        s2 = re.sub(r"Z$", "+00:00", s)
        m = re.match(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)", s2)
        if m:
            return datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def _fmt_reset_time(value):
    """seconds (int) or ISO string → '2h14m', '6d14h', '' on failure."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        secs = int(value)
    else:
        dt = _parse_iso(str(value))
        if not dt:
            return ""
        secs = int((dt - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "now"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return "{}d{}h".format(days, hours)
    if hours:
        return "{}h{}m".format(hours, mins)
    return "{}m".format(mins)


def _parse_token_expiry(expiry_str):
    """Parse RFC3339 expiry string. Returns datetime or None."""
    # Truncate sub-second to 6 digits for Python <3.11 compatibility
    s = re.sub(r'(\.\d{6})\d+', r'\1', expiry_str)
    # Python 3.8-3.10: fromisoformat doesn't support timezone offset '+HH:MM'
    try:
        from datetime import timedelta
        m = re.match(r'(.+?)([+-])(\d{2}):(\d{2})$', s)
        if m:
            dt_str, sign, hh, mm = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            offset = timedelta(hours=hh, minutes=mm)
            if sign == '-':
                offset = -offset
            dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone(offset))
        else:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_token_infos(base_dir, provider):
    """Return list of dicts with token file info for a provider."""
    results = []
    now = datetime.now(timezone.utc)
    for token_path in get_token_files(base_dir, provider):
        info = {
            "file": token_path.name,
            "path": str(token_path),
            "email": None,
            "status": "unknown",
            "expiry": None,
        }
        try:
            with open(token_path, encoding="utf-8") as f:
                data = json.load(f)
            info["email"] = data.get("email")
            if data.get("disabled"):
                info["status"] = "disabled"
            else:
                # Both formats use a timestamp string for expiry:
                # - claude/antigravity/codex: top-level "expired" field (timestamp str)
                # - gemini: "token.expiry" field (timestamp str)
                expiry_str = data.get("expired") or data.get("token", {}).get("expiry")
                if expiry_str:
                    exp = _parse_token_expiry(expiry_str)
                    info["expiry"] = exp
                    if exp is None:
                        info["status"] = "unknown"
                    elif exp < now:
                        info["status"] = "expired"
                    else:
                        mins = int((exp - now).total_seconds() / 60)
                        info["status"] = "ok (expires in {}m)".format(mins) if mins < 120 else "ok"
                else:
                    info["status"] = "ok"
        except Exception as e:
            info["status"] = "error ({})".format(e)
        results.append(info)
    return results


def ensure_tokens(base_dir, provider):
    exe = get_binary_path(base_dir)
    login_flag = LOGIN_FLAGS[provider]
    auth_hint = "  {} -config configs/{}/config.yaml {}".format(
        exe.name, provider, login_flag)

    token_dir = get_token_dir(base_dir, create=True)

    config_path = get_config_file(base_dir, provider)
    if config_path.exists():
        rewrite_auth_dir_in_config(config_path, token_dir)

    tokens = get_token_infos(base_dir, provider)

    if not tokens:
        print("[cc-proxy] WARNING: No token files found for '{}'.".format(provider))
        print("[cc-proxy] token-dir: {}".format(token_dir))
        print("[cc-proxy] To authenticate, run:")
        print("[cc-proxy] {}".format(auth_hint))
        print("[cc-proxy] Proceeding anyway...")
        return True

    # Print token status table so user can see auth state before claude launches
    any_expired = any("expired" in t["status"] for t in tokens)
    print("[cc-proxy] Tokens for '{}':".format(provider))
    print("[cc-proxy] token-dir: {}".format(token_dir))
    for t in tokens:
        label = t["email"] or t["file"]
        marker = "  <-- re-auth needed" if "expired" in t["status"] else ""
        print("[cc-proxy]   {:<40}  {}{}".format(label, t["status"], marker))
    if any_expired:
        print("[cc-proxy] WARNING: Some tokens are expired. To re-authenticate:")
        print("[cc-proxy] {}".format(auth_hint))
    return True
