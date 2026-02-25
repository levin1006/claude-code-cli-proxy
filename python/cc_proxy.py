#!/usr/bin/env python3
"""
CLIProxyAPI + Claude Code helper — cross-platform core
Python 3.8+, stdlib only.

Usage:
  python3 cc_proxy.py run <preset> [-- claude-args...]
  python3 cc_proxy.py start <provider> | all
  python3 cc_proxy.py stop [provider]
  python3 cc_proxy.py status [provider]
  python3 cc_proxy.py links [provider]
  python3 cc_proxy.py auth <provider>
  python3 cc_proxy.py set-secret <secret>
  python3 cc_proxy.py install-profile [--hint-only]
  python3 cc_proxy.py clean [-- claude-args...]
"""

import os
import sys
import re
import time
import signal
import socket
import shutil
import subprocess
import tempfile
import json
from pathlib import Path
from datetime import datetime, timezone


IS_WINDOWS = sys.platform == "win32"

PROVIDERS = ("antigravity", "claude", "codex", "gemini")

PORTS = {
    "antigravity": 18417,
    "claude":      18418,
    "codex":       18419,
    "gemini":      18420,
}

HOST = "127.0.0.1"

PRESETS = {
    "ag-claude": ("antigravity",  "claude-opus-4-6-thinking",  "claude-sonnet-4-6",       "claude-sonnet-4-6"),
    "ag-gemini": ("antigravity",  "gemini-3.1-pro-high",       "gemini-3.1-pro-low",      "gemini-3-flash"),
    "claude":    ("claude",       "claude-opus-4-6",           "claude-sonnet-4-6",       "claude-haiku-4-5-20251001"),
    "codex":     ("codex",        "gpt-5.3-codex(xhigh)",      "gpt-5.3-codex(high)",     "gpt-5.3-codex-spark"),
    "gemini":    ("gemini",       "gemini-3-pro-preview",      "gemini-3-flash-preview",  "gemini-2.5-flash-lite"),
}

LOGIN_FLAGS = {
    "antigravity": "-antigravity-login",
    "claude":      "-claude-login",
    "codex":       "-codex-login",
    "gemini":      "-login",
}


def get_base_dir():
    return Path(__file__).resolve().parent.parent


def get_binary_path(base_dir):
    name = "cli-proxy-api.exe" if IS_WINDOWS else "cli-proxy-api"
    return base_dir / name


def get_provider_dir(base_dir, provider):
    return base_dir / "configs" / provider


def get_pid_file(base_dir, provider):
    return get_provider_dir(base_dir, provider) / ".proxy.pid"


def get_config_file(base_dir, provider):
    return get_provider_dir(base_dir, provider) / "config.yaml"


def read_pid(base_dir, provider):
    pid_file = get_pid_file(base_dir, provider)
    try:
        txt = pid_file.read_text().strip()
        return int(txt) if txt else None
    except Exception:
        return None


def write_pid(base_dir, provider, pid):
    get_pid_file(base_dir, provider).write_text(str(pid))


def remove_pid(base_dir, provider):
    try:
        get_pid_file(base_dir, provider).unlink()
    except FileNotFoundError:
        pass


def is_pid_alive(pid):
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "PID eq {}".format(pid), "/NH", "/FO", "CSV"],
                capture_output=True, text=True
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def kill_pid(pid):
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def kill_all_proxies():
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/IM", "cli-proxy-api.exe", "/F"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "cli-proxy-api"], capture_output=True)


def resolve_pid_by_port(port):
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if ":{}".format(port) in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        try:
                            return int(parts[-1])
                        except ValueError:
                            pass
        except Exception:
            pass
        return None
    else:
        pid = _resolve_pid_ss(port)
        if pid is None:
            pid = _resolve_pid_lsof(port)
        return pid


def _resolve_pid_ss(port):
    if not shutil.which("ss"):
        return None
    try:
        result = subprocess.run(
            ["ss", "-tlnp", "sport = :{}".format(port)],
            capture_output=True, text=True
        )
        m = re.search(r"pid=(\d+)", result.stdout)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def _resolve_pid_lsof(port):
    if not shutil.which("lsof"):
        return None
    try:
        result = subprocess.run(
            ["lsof", "-iTCP:{}".format(port), "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True
        )
        lines = result.stdout.strip().splitlines()
        return int(lines[0]) if lines else None
    except Exception:
        return None


def find_free_port(start=3000, end=3020):
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, port))
                return port
        except OSError:
            pass
    return start


def check_health(provider):
    import urllib.request
    import urllib.error
    port = PORTS[provider]
    url = "http://{}:{}/".format(HOST, port)
    try:
        with urllib.request.urlopen(url, timeout=1) as resp:
            return resp.status < 500
    except Exception:
        return False


def get_management_url(provider):
    return "http://{}:{}/management.html#/quota".format(HOST, PORTS[provider])


def get_dashboard_file_path():
    return Path(tempfile.gettempdir()) / "cc_proxy_management_dashboard.html"


def get_dashboard_server_state_path():
    return Path(tempfile.gettempdir()) / "cc_proxy_dashboard_server.json"


def _read_dashboard_server_state():
    state_path = get_dashboard_server_state_path()
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_dashboard_server_state(state):
    state_path = get_dashboard_server_state_path()
    try:
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def _remove_dashboard_server_state():
    state_path = get_dashboard_server_state_path()
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def stop_dashboard_server():
    state = _read_dashboard_server_state()
    pid = state.get("pid")
    stopped = False

    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid = None

    if pid and is_pid_alive(pid):
        kill_pid(pid)
        time.sleep(0.1)
        stopped = True

    _remove_dashboard_server_state()
    return stopped


def _is_dashboard_server_alive(port):
    if not port:
        return False
    try:
        with socket.create_connection((HOST, int(port)), timeout=0.5):
            return True
    except Exception:
        return False


def _start_dashboard_server(dashboard_path):
    script = (
        "import functools, http.server, socketserver\n"
        "handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=r'{}')\n"
        "with socketserver.TCPServer(('127.0.0.1', 0), handler) as httpd:\n"
        "    print(httpd.server_address[1], flush=True)\n"
        "    httpd.serve_forever()\n"
    ).format(str(dashboard_path.parent))

    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "text": True,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen([sys.executable, "-c", script], **kwargs)
    port_line = ""
    for _ in range(30):
        port_line = proc.stdout.readline().strip() if proc.stdout else ""
        if port_line:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    if not port_line:
        return None

    try:
        port = int(port_line)
    except ValueError:
        return None

    if not _is_dashboard_server_alive(port):
        return None

    _write_dashboard_server_state({"pid": proc.pid, "port": port})
    return port


def get_dashboard_http_url():
    dashboard_path = get_dashboard_file_path()
    state = _read_dashboard_server_state()
    port = state.get("port")

    if _is_dashboard_server_alive(port):
        return "http://{}:{}/{}".format(HOST, int(port), dashboard_path.name)

    port = _start_dashboard_server(dashboard_path)
    if port:
        return "http://{}:{}/{}".format(HOST, int(port), dashboard_path.name)

    return dashboard_path.resolve().as_uri()


def render_dashboard_html():
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    panels = []
    for provider in PROVIDERS:
        port = PORTS[provider]
        url = get_management_url(provider)
        panels.append(
            """    <section class=\"panel\">
      <div class=\"panel-header\">
        <div class=\"panel-title\">{provider}</div>
        <div class=\"panel-meta\">port {port}</div>
        <a class=\"panel-link\" href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">Open directly</a>
      </div>
      <iframe src=\"{url}\" loading=\"lazy\" title=\"{provider} dashboard\"></iframe>
      <p class=\"fallback\">If this panel is blank, embedding was blocked (X-Frame-Options/CSP). Use the direct link above.</p>
    </section>""".format(provider=provider, port=port, url=url)
        )

    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>CC Proxy Management Dashboards</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #10141b;
      --card: #1b2230;
      --border: #2d3a50;
      --text: #e8edf7;
      --muted: #a8b3c7;
      --link: #7fb5ff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
    }}
    header h1 {{
      margin: 0 0 4px 0;
      font-size: 18px;
    }}
    header p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    main {{
      display: grid;
      grid-template-columns: repeat(2, minmax(360px, 1fr));
      gap: 12px;
      padding: 12px;
      min-height: calc(100vh - 70px);
    }}
    .panel {{
      border: 1px solid var(--border);
      background: var(--card);
      border-radius: 10px;
      display: grid;
      grid-template-rows: auto 1fr auto;
      min-height: 42vh;
      overflow: hidden;
    }}
    .panel-header {{
      display: grid;
      grid-template-columns: auto auto 1fr;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
    }}
    .panel-title {{
      font-weight: 700;
      text-transform: capitalize;
    }}
    .panel-meta {{
      color: var(--muted);
      font-size: 12px;
    }}
    .panel-link {{
      justify-self: end;
      color: var(--link);
      font-size: 12px;
      text-decoration: none;
    }}
    .panel-link:hover {{ text-decoration: underline; }}
    iframe {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #fff;
    }}
    .fallback {{
      margin: 0;
      padding: 8px 12px;
      font-size: 12px;
      color: var(--muted);
      border-top: 1px solid var(--border);
    }}
    @media (max-width: 980px) {{
      main {{ grid-template-columns: 1fr; }}
      .panel {{ min-height: 50vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>CC Proxy management dashboards</h1>
    <p>Generated at {generated_at}. Provider panels: antigravity, claude, codex, gemini.</p>
  </header>
  <main>
{panels}
  </main>
</body>
</html>
""".format(generated_at=generated_at, panels="\n".join(panels))


def ensure_dashboard_html():
    dashboard_path = get_dashboard_file_path()
    content = render_dashboard_html()
    try:
        if dashboard_path.exists():
            current = dashboard_path.read_text(encoding="utf-8")
            if current == content:
                return dashboard_path
        dashboard_path.write_text(content, encoding="utf-8")
    except Exception as exc:
        print("[cc-proxy] WARNING: Failed to update dashboard HTML: {}".format(exc), file=sys.stderr)
    return dashboard_path


def should_open_auth_browser():
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if not IS_WINDOWS:
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return False
    return True


def print_management_links(base_dir, provider=None, statuses=None):
    targets = [provider] if provider else list(PROVIDERS)
    ensure_dashboard_html()
    print("[cc-proxy] Management links:")
    status_map = statuses if statuses is not None else {}
    for pvd in targets:
        status = status_map.get(pvd)
        if status is None:
            status = get_status(base_dir, pvd)
        healthy = str(status["healthy"]) if status["running"] else "n/a"
        print("[cc-proxy]   {:<12} running={:<5} healthy={:<5} {}".format(
            pvd,
            str(status["running"]),
            healthy,
            get_management_url(pvd),
        ))
    print("[cc-proxy]   dashboard(all): {}".format(get_dashboard_http_url()))


def cmd_links(base_dir, provider=None):
    targets = [provider] if provider else list(PROVIDERS)
    statuses = {}
    for pvd in targets:
        statuses[pvd] = get_status(base_dir, pvd)
    print_management_links(base_dir, provider, statuses=statuses)
    return 0


def rewrite_port_in_config(config_path, port):
    text = config_path.read_text(encoding="utf-8")
    if re.search(r"^\s*port\s*:\s*\d+", text, re.MULTILINE):
        text = re.sub(r"(?m)^(\s*port\s*:\s*)\d+", r"\g<1>{}".format(port), text)
    else:
        text = "port: {}\n".format(port) + text
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


def ensure_tokens(base_dir, provider):
    exe = get_binary_path(base_dir)
    login_flag = LOGIN_FLAGS[provider]
    auth_hint = "  {} -config configs/{}/config.yaml {}".format(
        exe.name, provider, login_flag)

    tokens = get_token_infos(base_dir, provider)

    if not tokens:
        print("[cc-proxy] WARNING: No token files found for '{}'.".format(provider))
        print("[cc-proxy] To authenticate, run:")
        print("[cc-proxy] {}".format(auth_hint))
        print("[cc-proxy] Proceeding anyway...")
        return True

    # Print token status table so user can see auth state before claude launches
    any_expired = any("expired" in t["status"] for t in tokens)
    print("[cc-proxy] Tokens for '{}':".format(provider))
    for t in tokens:
        label = t["email"] or t["file"]
        marker = "  <-- re-auth needed" if "expired" in t["status"] else ""
        print("[cc-proxy]   {:<40}  {}{}".format(label, t["status"], marker))
    if any_expired:
        print("[cc-proxy] WARNING: Some tokens are expired. To re-authenticate:")
        print("[cc-proxy] {}".format(auth_hint))
    return True


def start_proxy(base_dir, provider):
    exe = get_binary_path(base_dir)
    if not exe.exists():
        print("[cc-proxy] Binary not found: {}".format(exe), file=sys.stderr)
        return False

    wd = get_provider_dir(base_dir, provider)
    if not wd.is_dir():
        print("[cc-proxy] Provider config directory not found: {}".format(wd), file=sys.stderr)
        return False

    config_path = get_config_file(base_dir, provider)
    if not config_path.exists():
        root_bootstrap = base_dir / "config.yaml"
        if not root_bootstrap.exists():
            print("[cc-proxy] No config.yaml found for {}".format(provider), file=sys.stderr)
            return False
        shutil.copy(root_bootstrap, config_path)

    existing_pid = resolve_pid_by_port(PORTS[provider])
    if existing_pid:
        write_pid(base_dir, provider, existing_pid)
        if check_health(provider):
            print("[cc-proxy] Reusing healthy proxy for {} (pid={})".format(provider, existing_pid))
            status = get_status(base_dir, provider)
            print_management_links(base_dir, provider, statuses={provider: status})
            return True
        print("[cc-proxy] Process on port {} is unhealthy. Stop it first.".format(PORTS[provider]), file=sys.stderr)
        return False

    rewrite_port_in_config(config_path, PORTS[provider])

    log_path = str(wd / "main.log")
    if IS_WINDOWS:
        CREATE_NO_WINDOW = 0x08000000
        proc = subprocess.Popen(
            [str(exe), "-config", str(config_path)],
            cwd=str(wd),
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
    else:
        log_file = open(log_path, "a")
        proc = subprocess.Popen(
            [str(exe), "-config", str(config_path)],
            cwd=str(wd),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    time.sleep(0.3)
    actual_pid = resolve_pid_by_port(PORTS[provider])
    write_pid(base_dir, provider, actual_pid if actual_pid else proc.pid)

    print("[cc-proxy] Starting {} proxy...".format(provider))
    for _ in range(15):
        if check_health(provider):
            print("[cc-proxy] Proxy ready at http://{}:{}/".format(HOST, PORTS[provider]))
            status = get_status(base_dir, provider)
            print_management_links(base_dir, provider, statuses={provider: status})
            return True
        time.sleep(0.2)

    print("[cc-proxy] Failed to become healthy at http://{}:{}/".format(HOST, PORTS[provider]), file=sys.stderr)
    return False


def stop_proxy(base_dir, provider):
    if provider:
        pid = read_pid(base_dir, provider)
        if pid and is_pid_alive(pid):
            kill_pid(pid)
            time.sleep(0.25)
        remove_pid(base_dir, provider)
        pid2 = resolve_pid_by_port(PORTS[provider])
        if pid2:
            kill_pid(pid2)
            time.sleep(0.25)
        print("[cc-proxy] Stopped {}.".format(provider))
    else:
        for pvd in PROVIDERS:
            pid = read_pid(base_dir, pvd)
            if pid and is_pid_alive(pid):
                kill_pid(pid)
            remove_pid(base_dir, pvd)
            pid2 = resolve_pid_by_port(PORTS[pvd])
            if pid2:
                kill_pid(pid2)
        kill_all_proxies()
        time.sleep(0.25)
        print("[cc-proxy] All proxies stopped.")

    if stop_dashboard_server():
        print("[cc-proxy] Dashboard link server stopped.")


def _parse_token_expiry(expiry_str):
    """Parse RFC3339 expiry string. Returns datetime or None."""
    import re as _re
    # Truncate sub-second to 6 digits for Python <3.11 compatibility
    s = _re.sub(r'(\.\d{6})\d+', r'\1', expiry_str)
    # Python 3.8-3.10: fromisoformat doesn't support timezone offset '+HH:MM'
    # Replace '+HH:MM' or '-HH:MM' suffix with UTC offset calculation
    try:
        from datetime import datetime, timezone, timedelta
        m = _re.match(r'(.+?)([+-])(\d{2}):(\d{2})$', s)
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
    import glob as _glob, json as _json
    from datetime import datetime, timezone
    token_dir = get_provider_dir(base_dir, provider)
    files = sorted(_glob.glob(str(token_dir / "{}-*.json".format(provider))))
    results = []
    now = datetime.now(timezone.utc)
    for fpath in files:
        info = {"file": Path(fpath).name, "email": None, "status": "unknown", "expiry": None}
        try:
            with open(fpath) as f:
                data = _json.load(f)
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


def get_status(base_dir, provider):
    pid = read_pid(base_dir, provider)
    if not pid:
        pid = resolve_pid_by_port(PORTS[provider])
        if pid:
            write_pid(base_dir, provider, pid)

    running = bool(pid and is_pid_alive(pid))
    healthy = check_health(provider) if running else False
    tokens = get_token_infos(base_dir, provider)
    return {
        "provider": provider,
        "running": running,
        "pid": pid if running else None,
        "healthy": healthy,
        "url": "http://{}:{}".format(HOST, PORTS[provider]),
        "tokens": tokens,
    }


def run_auth(base_dir, provider):
    exe = get_binary_path(base_dir)
    if not exe.exists():
        print("[cc-proxy] Binary not found: {}".format(exe), file=sys.stderr)
        return False

    wd = get_provider_dir(base_dir, provider)
    config_path = get_config_file(base_dir, provider)
    if not config_path.exists():
        root_bootstrap = base_dir / "config.yaml"
        if root_bootstrap.exists():
            shutil.copy(root_bootstrap, config_path)

    extra_flags = []
    if not should_open_auth_browser():
        extra_flags.append("-no-browser")

    free_port = 54545 if provider == "claude" else find_free_port(3000, 3020)
    extra_flags += ["-oauth-callback-port", str(free_port)]

    login_flag = LOGIN_FLAGS[provider]
    print("[cc-proxy] Starting auth for provider '{}' (callback port {})...".format(provider, free_port))
    print("[cc-proxy] Token file will be saved to: {}".format(wd))

    cmd = [str(exe), "-config", str(config_path), login_flag] + extra_flags
    result = subprocess.run(cmd, cwd=str(wd))
    return result.returncode == 0


def invoke_claude(provider, opus, sonnet, haiku, claude_args):
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = "http://{}:{}".format(HOST, PORTS[provider])
    env["ANTHROPIC_AUTH_TOKEN"] = "sk-dummy"
    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus
    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet
    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku

    claude_bin = shutil.which("claude") or "claude"
    sys.stdout.flush()
    sys.stderr.flush()
    result = subprocess.run([claude_bin] + claude_args, env=env)
    return result.returncode


def install_profile(base_dir, hint_only=False):
    if IS_WINDOWS:
        _install_profile_windows(base_dir, hint_only)
    else:
        _install_profile_linux(base_dir, hint_only)


def _install_profile_linux(base_dir, hint_only):
    src_line = 'source "{}/bash/cc-proxy.sh"'.format(base_dir)
    rcfiles = []
    for name in (".bashrc", ".zshrc"):
        p = Path.home() / name
        if p.exists():
            rcfiles.append(p)

    already_installed = any(
        src_line in p.read_text(errors="replace")
        for p in rcfiles
    )

    if already_installed:
        if not hint_only:
            print("[cc-proxy] Shell profile already contains cc-proxy loader.")
        return

    if hint_only:
        print("[cc-proxy] First-time setup detected.")
        try:
            answer = input("[cc-proxy] Add loader to your shell profile now? (Y/N) ")
        except (EOFError, KeyboardInterrupt):
            return
        if not answer.strip().lower().startswith("y"):
            print("[cc-proxy] Skipped. Run cc_proxy_install_profile later.")
            return

    if not rcfiles:
        rcfiles = [Path.home() / ".bashrc"]

    for rc in rcfiles:
        content = rc.read_text(errors="replace") if rc.exists() else ""
        if src_line not in content:
            with rc.open("a") as f:
                f.write("\n{}\n".format(src_line))
            print("[cc-proxy] Added loader to {}.".format(rc))
        else:
            print("[cc-proxy] {} already contains cc-proxy loader.".format(rc))

    print("[cc-proxy] New terminals will auto-load helpers.")


def _install_profile_windows(base_dir, hint_only):
    script_path = base_dir / "powershell" / "cc-proxy.ps1"
    profile_line = '. "{}"'.format(script_path)

    try:
        res = subprocess.run(
            ["powershell", "-Command", "echo $PROFILE"],
            capture_output=True, text=True
        )
        profile_path = Path(res.stdout.strip())
    except Exception:
        print("[cc-proxy] Could not determine PowerShell profile path.", file=sys.stderr)
        return

    already = profile_path.exists() and profile_line in profile_path.read_text(errors="replace")
    if already:
        if not hint_only:
            print("[cc-proxy] PowerShell profile already contains cc-proxy loader.")
        return

    if hint_only:
        print("[cc-proxy] First-time setup detected.")
        try:
            answer = input("[cc-proxy] Add loader to your PowerShell profile now? (Y/N) ")
        except (EOFError, KeyboardInterrupt):
            return
        if not answer.strip().lower().startswith("y"):
            print("[cc-proxy] Skipped. Run Install-CCProxyProfile later.")
            return

    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with profile_path.open("a") as f:
        f.write("\r\n{}\r\n".format(profile_line))
    print("[cc-proxy] Added loader to {}.".format(profile_path))


def cmd_set_secret(base_dir, secret):
    config_files = [base_dir / "config.yaml"] + [
        get_config_file(base_dir, pvd) for pvd in PROVIDERS
    ]
    updated = 0
    for f in config_files:
        if f.exists():
            rewrite_secret_in_config(f, secret)
            print("[cc-proxy] Updated: {}".format(f))
            updated += 1
    print("[cc-proxy] Secret key set in {} file(s).".format(updated))

    restarted = 0
    for pvd in PROVIDERS:
        if resolve_pid_by_port(PORTS[pvd]):
            print("[cc-proxy] Restarting provider: {}".format(pvd))
            stop_proxy(base_dir, pvd)
            if start_proxy(base_dir, pvd):
                restarted += 1
            else:
                print("[cc-proxy] Failed to restart: {}".format(pvd), file=sys.stderr)

    if restarted == 0:
        print("[cc-proxy] No running providers found. Run cc-<provider> when needed.")
    else:
        print("[cc-proxy] Restarted {} running provider(s).".format(restarted))


def print_usage():
    print(__doc__)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print_usage()
        return 0

    base_dir = get_base_dir()
    cmd = args[0]

    if cmd == "run":
        if len(args) < 2:
            print("[cc-proxy] Usage: run <preset> [-- claude-args...]", file=sys.stderr)
            return 1
        preset = args[1]
        if preset not in PRESETS:
            print("[cc-proxy] Unknown preset: {}".format(preset), file=sys.stderr)
            print("[cc-proxy] Valid presets: {}".format(", ".join(PRESETS)), file=sys.stderr)
            return 1
        rest = args[2:]
        if "--" in rest:
            idx = rest.index("--")
            claude_args = rest[idx + 1:]
        else:
            claude_args = rest

        provider, opus, sonnet, haiku = PRESETS[preset]
        if not ensure_tokens(base_dir, provider):
            return 1
        if not start_proxy(base_dir, provider):
            return 1
        return invoke_claude(provider, opus, sonnet, haiku, claude_args)

    elif cmd == "start":
        if len(args) < 2:
            print("[cc-proxy] Usage: start <provider> | all", file=sys.stderr)
            return 1
        provider = args[1]

        if provider == "all":
            all_ok = True
            for pvd in PROVIDERS:
                if not start_proxy(base_dir, pvd):
                    all_ok = False
            return 0 if all_ok else 1

        if provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        return 0 if start_proxy(base_dir, provider) else 1

    elif cmd == "stop":
        provider = args[1] if len(args) > 1 else None
        if provider and provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        stop_proxy(base_dir, provider)
        return 0

    elif cmd == "status":
        provider = args[1] if len(args) > 1 else None
        targets = [provider] if provider else list(PROVIDERS)
        if provider and provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        print("[cc-proxy] Status:")
        for pvd in targets:
            s = get_status(base_dir, pvd)
            pid_str = str(s["pid"]) if s["pid"] else "-"
            running_str = "Running" if s["running"] else "Stopped"
            healthy_str = str(s["healthy"])
            print("  {:<14}  {:<8}  PID={:<7}  Healthy={:<5}  {}".format(
                pvd, running_str, pid_str, healthy_str, s["url"]))
            if s["tokens"]:
                for t in s["tokens"]:
                    label = t["email"] or t["file"]
                    status = t["status"]
                    marker = "  [expired]" if "expired" in status else ""
                    print("    Token: {:<40}  {}{}".format(label, status, marker))
            else:
                print("    Token: (none — run: cc-proxy-auth {})".format(pvd))
        return 0

    elif cmd == "links":
        if len(args) > 2:
            print("[cc-proxy] Usage: links [provider]", file=sys.stderr)
            return 1
        provider = args[1] if len(args) > 1 else None
        if provider and provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        return cmd_links(base_dir, provider)

    elif cmd == "auth":
        if len(args) < 2:
            print("[cc-proxy] Usage: auth <provider>", file=sys.stderr)
            return 1
        provider = args[1]
        if provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1

        was_running = bool(resolve_pid_by_port(PORTS[provider]))
        if not run_auth(base_dir, provider):
            return 1

        if not was_running:
            print("[cc-proxy] {} proxy is not running. Auto-restart skipped.".format(provider))
            return 0

        print("[cc-proxy] Restarting {} proxy to reload tokens...".format(provider))
        stop_proxy(base_dir, provider)
        if not start_proxy(base_dir, provider):
            print("[cc-proxy] Failed to restart {} after auth.".format(provider), file=sys.stderr)
            return 1
        return 0

    elif cmd == "set-secret":
        if len(args) < 2:
            print("[cc-proxy] Usage: set-secret <secret>", file=sys.stderr)
            return 1
        cmd_set_secret(base_dir, args[1])
        return 0

    elif cmd == "install-profile":
        hint_only = "--hint-only" in args
        install_profile(base_dir, hint_only)
        return 0

    elif cmd == "clean":
        rest = args[1:]
        if "--" in rest:
            idx = rest.index("--")
            claude_args = rest[idx + 1:]
        else:
            claude_args = rest
        env = os.environ.copy()
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
            env.pop(key, None)
        claude_bin = shutil.which("claude") or "claude"
        result = subprocess.run([claude_bin] + claude_args, env=env)
        return result.returncode

    else:
        print("[cc-proxy] Unknown command: {}".format(cmd), file=sys.stderr)
        print_usage()
        return 1


if __name__ == "__main__":
    sys.exit(main())
