#!/usr/bin/env python3
"""
CLIProxyAPI + Claude Code helper — cross-platform core
Python 3.8+, stdlib only.

Usage:
  python3 core/cc_proxy.py run <preset> [-- claude-args...]
  python3 core/cc_proxy.py start <provider> | all
  python3 core/cc_proxy.py stop [provider]
  python3 core/cc_proxy.py status [provider]
  python3 core/cc_proxy.py links [provider]
  python3 core/cc_proxy.py auth <provider>
  python3 core/cc_proxy.py set-secret <secret>
  python3 core/cc_proxy.py install-profile [--hint-only]
  python3 core/cc_proxy.py clean [-- claude-args...]
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
import base64
import platform
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


def get_host_arch():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return "amd64"


def get_repo_binary_path(base_dir):
    if IS_WINDOWS:
        return base_dir / "CLIProxyAPI" / "windows" / "amd64" / "cli-proxy-api.exe"
    return base_dir / "CLIProxyAPI" / "linux" / get_host_arch() / "cli-proxy-api"


def get_binary_path(base_dir):
    name = "cli-proxy-api.exe" if IS_WINDOWS else "cli-proxy-api"
    canonical_path = base_dir / name
    if canonical_path.exists():
        return canonical_path

    repo_binary_path = get_repo_binary_path(base_dir)
    if repo_binary_path.exists():
        return repo_binary_path

    return canonical_path


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


def is_ssh_session():
    return bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))


def try_copy_to_clipboard(text):
    """Try to copy text to the system clipboard. Returns True on success.

    Strategy:
    1. OSC 52 escape sequence — works over SSH through any modern terminal
       (iTerm2, WezTerm, Kitty, Windows Terminal, etc.) without extra tools.
    2. Platform clipboard commands (xclip, wl-copy, pbcopy, clip) — for
       local sessions where the terminal may not relay OSC 52.
    """
    import base64 as _b64

    # --- OSC 52 (preferred for SSH and modern terminals) ---
    osc52 = "\033]52;c;{}\007".format(_b64.b64encode(text.encode("utf-8")).decode("ascii"))
    try:
        # Write directly to /dev/tty so it reaches the terminal even when
        # stdout is piped or redirected.
        with open("/dev/tty", "w") as _tty:
            _tty.write(osc52)
        return True
    except Exception:
        pass
    try:
        sys.stdout.write(osc52)
        sys.stdout.flush()
        return True
    except Exception:
        pass

    # --- Platform clipboard tools (local sessions) ---
    if IS_WINDOWS:
        cmds = [["clip"]]
    else:
        cmds = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
            ["pbcopy"],
        ]
    for cmd in cmds:
        try:
            proc = subprocess.run(
                cmd, input=text.encode("utf-8"),
                timeout=2, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            )
            if proc.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    return False


def get_local_port_offset():
    raw = os.environ.get("CC_PROXY_LOCAL_PORT_OFFSET", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 0
    return 0


def get_management_port(provider):
    return PORTS[provider] + get_local_port_offset()


def get_management_url(provider):
    return "http://{}:{}/management.html#/quota".format(HOST, get_management_port(provider))


def get_dashboard_link_port():
    return 18500 + get_local_port_offset()


def get_dashboard_server_port():
    """The port the local HTTP server actually binds to (always the base port).
    SSH port-forwarding maps local:(18500+offset) → remote:18500, so the server
    must always bind to the base port regardless of offset."""
    return 18500


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

    dashboard_pid = resolve_pid_by_port(get_dashboard_server_port())
    if dashboard_pid and is_pid_alive(dashboard_pid):
        kill_pid(dashboard_pid)
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
    preferred_port = get_dashboard_server_port()
    script = (
        "import functools, http.server, socketserver\n"
        "handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=r'{}')\n"
        "class MyServer(socketserver.TCPServer):\n"
        "    allow_reuse_address = True\n"
        "httpd = MyServer(('127.0.0.1', {}), handler)\n"
        "print(httpd.server_address[1], flush=True)\n"
        "httpd.serve_forever()\n"
    ).format(str(dashboard_path.parent), preferred_port)

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
    server_port = get_dashboard_server_port()   # where the server actually binds
    link_port = get_dashboard_link_port()       # what appears in the URL (offset applied)

    if _is_dashboard_server_alive(server_port):
        return "http://{}:{}/{}".format(HOST, link_port, dashboard_path.name)

    port = _start_dashboard_server(dashboard_path)
    if port:
        return "http://{}:{}/{}".format(HOST, link_port, dashboard_path.name)

    print(
        "[cc-proxy] WARNING: Dashboard link server must use fixed port {} (already in use).".format(server_port),
        file=sys.stderr,
    )

    return dashboard_path.resolve().as_uri()


def render_dashboard_html():
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    panels = []
    for provider in PROVIDERS:
        port = get_management_port(provider)
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
    dashboard_url = get_dashboard_http_url()
    copied = try_copy_to_clipboard(dashboard_url)
    suffix = "  (copied to clipboard)" if copied else ""
    print("[cc-proxy]   dashboard(all): {}{}".format(dashboard_url, suffix))


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


def _management_api(provider, endpoint, secret="cc"):
    """GET /v0/management/<endpoint> from a running provider proxy."""
    import urllib.request
    import urllib.error
    port = PORTS[provider]
    url = "http://{}:{}/v0/management/{}".format(HOST, port, endpoint)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer {}".format(secret)})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _proxy_api(provider, path, timeout=5):
    """GET arbitrary path from a running provider proxy (no management auth)."""
    import urllib.request
    port = PORTS[provider]
    url = "http://{}:{}/{}".format(HOST, port, path.lstrip("/"))
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_secret_key(base_dir, provider):
    """Return plaintext secret key for management API Bearer auth.

    Priority:
    1. CC_PROXY_SECRET env var (user override)
    2. config.yaml secret-key — only if it looks like plaintext (not a bcrypt hash)
    3. Default "cc"

    The CLIProxyAPI binary rewrites the secret-key in config.yaml as a bcrypt
    hash on startup, so config.yaml nearly always contains a hash, not the
    plaintext.  We cannot reverse a bcrypt hash, so we fall back to "cc".
    """
    env_secret = os.environ.get("CC_PROXY_SECRET")
    if env_secret:
        return env_secret
    config_path = get_config_file(base_dir, provider)
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        m = re.search(r'secret-key:\s*"([^"]*)"', text)
        if m:
            val = m.group(1)
            # bcrypt hashes start with $2a$, $2b$, $2y$ — not useful as Bearer token
            if not val.startswith("$2"):
                return val
    return "cc"


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


# ANSI color codes (empty string fallback keeps output clean when piped)
_C_GREEN  = "\033[32m"
_C_RED    = "\033[31m"
_C_DIM    = "\033[2m"
_C_BOLD   = "\033[1m"
_C_RESET  = "\033[0m"


def _visible_len(s):
    """ANSI escape를 제거한 실제 보이는 문자 길이."""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _box_line(text, width):
    """║  text    ║ 형태로 패딩. ANSI escape 코드가 포함된 text도 정확히 정렬."""
    ansi_extra = len(text) - _visible_len(text)
    max_visible = width - 4
    inner = text[: max_visible + ansi_extra]
    pad = max_visible - _visible_len(inner)
    return "\u2551 {}{} \u2551".format(inner, " " * max(0, pad))


def _box_top(width):
    return "\u2554" + "\u2550" * (width - 2) + "\u2557"


def _box_bottom(width):
    return "\u255a" + "\u2550" * (width - 2) + "\u255d"


def _box_sep(width):
    return "\u2560" + "\u2550" * (width - 2) + "\u2563"


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
            # Temporary rate limit — account will recover
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


def _aggregate_per_account(usage_data):
    """Aggregate usage stats per account from /v0/management/usage response."""
    account_stats = {}
    for api_data in usage_data.get("usage", {}).get("apis", {}).values():
        for model_data in api_data.get("models", {}).values():
            for detail in model_data.get("details", []):
                src = detail.get("source", "unknown")
                tok = detail.get("tokens", {}).get("total_tokens", 0)
                if src not in account_stats:
                    account_stats[src] = {"requests": 0, "tokens": 0}
                account_stats[src]["requests"] += 1
                account_stats[src]["tokens"] += tok
    return account_stats


def _prefetch_provider_data(base_dir, provider):
    """Fetch all management data for a provider (designed for parallel threading)."""
    import urllib.error
    result = {"status": None, "auth_data": None, "usage_data": None, "auth_error": False}
    result["status"] = get_status(base_dir, provider)
    if result["status"]["running"] and result["status"]["healthy"]:
        try:
            secret = _read_secret_key(base_dir, provider)
            result["auth_data"] = _management_api(provider, "auth-files", secret)
            result["usage_data"] = _management_api(provider, "usage", secret)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                result["auth_error"] = True
        except Exception:
            pass
    return result


def _print_status_dashboard(base_dir, provider, status, W,
                            auth_data=None, usage_data=None, auth_error=False):
    """Print rich dashboard panel for a provider."""
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
    print(_box_sep(W))
    print(_box_line(header, W))

    if auth_error:
        hint = _C_RED + "  auth failed" + _C_RESET + " \u2014 set CC_PROXY_SECRET env var"
        print(_box_line(hint, W))
        return

    # No data to display: compact view
    u = usage_data.get("usage", {}) if usage_data else {}
    has_data = bool(files or u.get("total_requests", 0))
    if not running or not healthy or not has_data:
        return

    # --- accounts section ---
    print(_box_line("", W))
    print(_box_line("  Accounts", W))
    divider = "  " + "\u2500" * (W - 6)
    print(_box_line(divider, W))
    for f in files:
        email = f.get("email", f.get("name", "?"))
        last_refresh = f.get("last_refresh", "")
        plan_type = (f.get("id_token") or {}).get("plan_type", "")
        time_str = _time_ago(last_refresh) if last_refresh else ""
        _ind, acct_status, _deg = _acct_status_label(f)
        label = email
        if plan_type:
            suffix = " [{}]".format(plan_type)
            label = email[:max(0, 28 - len(suffix))] + suffix
        row = "  {:<34}  {:>8}  {}".format(label[:34], time_str, acct_status)
        print(_box_line(row, W))

    # --- usage section ---
    total_req = u.get("total_requests", 0)
    ok_req = u.get("success_count", 0)
    fail_req = u.get("failure_count", 0)
    total_tok = u.get("total_tokens", 0)

    print(_box_line("", W))
    print(_box_line("  Usage", W))
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
            req_count = len(details)
            tok_count = sum(d.get("tokens", {}).get("total_tokens", 0) for d in details)
            if model_name not in model_stats:
                model_stats[model_name] = {"requests": 0, "tokens": 0}
            model_stats[model_name]["requests"] += req_count
            model_stats[model_name]["tokens"] += tok_count

    if model_stats:
        print(_box_line("", W))
        print(_box_line("  Models:", W))
        for mname, mdata in sorted(model_stats.items(), key=lambda x: -x[1]["tokens"]):
            # content=64: "    " + name[:32] + "  " + count(5) + " req  " + tok(8) + " tokens"
            # = 4+32+2+5+6+8+7 = 64
            row = "    {:<32}  {:>5} req  {:>8} tokens".format(
                mname[:32], mdata["requests"], _fmt_tokens(mdata["tokens"])
            )
            print(_box_line(row, W))

    # Daily stats
    requests_by_day = u.get("requests_by_day", {})
    tokens_by_day = u.get("tokens_by_day", {})
    all_days = sorted(set(list(requests_by_day.keys()) + list(tokens_by_day.keys())))
    if all_days:
        print(_box_line("", W))
        print(_box_line("  Daily:", W))
        for day in all_days[-7:]:
            day_req = requests_by_day.get(day, 0)
            day_tok = tokens_by_day.get(day, 0)
            # content=64: "    " + day(10) + "  " + count(6) + " req  " + tok(8) + " tokens"
            # = 4+10+2+6+6+8+7 = 43
            row = "    {}  {:>6} req  {:>8} tokens".format(day, day_req, _fmt_tokens(day_tok))
            print(_box_line(row, W))

    # Per-account stats
    acct_stats = _aggregate_per_account(usage_data)
    if acct_stats:
        print(_box_line("", W))
        print(_box_line("  Per-account:", W))
        for acct, adata in sorted(acct_stats.items(), key=lambda x: -x[1]["tokens"]):
            # content=64: "    " + email[:32] + "  " + count(5) + " req  " + tok(8) + " tokens"
            # = 4+32+2+5+6+8+7 = 64
            row = "    {:<32}  {:>5} req  {:>8} tokens".format(
                acct[:32], adata["requests"], _fmt_tokens(adata["tokens"])
            )
            print(_box_line(row, W))

    print(_box_line("", W))


def _print_check_panel(provider, status, W, auth_data, models_per_account, proxy_models, auth_error):
    """Print per-credential validation panel for cc-proxy-check."""
    running = status["running"]
    healthy = status["healthy"]
    port = PORTS[provider]
    divider = "  " + "\u2500" * (W - 6)

    if running:
        dot_str = _C_GREEN + "\u25cf" + _C_RESET
        state_str = "running"
    else:
        dot_str = _C_DIM + "\u25cb" + _C_RESET
        state_str = _C_DIM + "stopped" + _C_RESET

    files = auth_data.get("files", []) if auth_data else []
    acct_suffix = "  {} accounts".format(len(files)) if files else ""
    header = "  {}  :{}   {} {}{}".format(provider, port, dot_str, state_str, acct_suffix)
    print(_box_sep(W))
    print(_box_line(header, W))

    if not running or not healthy:
        return

    if auth_error:
        hint = _C_RED + "  auth failed" + _C_RESET + " \u2014 set CC_PROXY_SECRET env var"
        print(_box_line(hint, W))
        return

    if not files and not proxy_models:
        print(_box_line("  No credentials found", W))
        return

    # --- account validation section ---
    print(_box_line("", W))
    print(_box_line("  Account Validation", W))
    print(_box_line(divider, W))

    all_ok = True
    for f in files:
        email = f.get("email", f.get("name", "?"))
        name = f.get("name", "")
        last_refresh = f.get("last_refresh", "")
        plan_type = (f.get("id_token") or {}).get("plan_type", "")
        time_str = _time_ago(last_refresh) if last_refresh else ""

        model_list = models_per_account.get(name)
        if model_list is None:
            mc_str = "       \u2014"  # fetch failed
        else:
            mc = len(model_list)
            mc_str = "{:>2} models".format(mc) if mc > 0 else " 0 models"

        indicator, st_str, is_degraded = _acct_status_label(f)

        # Active account with 0 models: not in proxy routing pool -> flag as warning
        if (not f.get("disabled", False)
                and f.get("status", "") not in ("error",)
                and not f.get("unavailable", False)
                and model_list is not None
                and len(model_list) == 0):
            indicator = _C_DIM + "\u26a0" + _C_RESET   # ⚠
            st_str = _C_DIM + "no models" + _C_RESET
            is_degraded = True

        if is_degraded:
            all_ok = False

        label = email
        if plan_type:
            suffix = " [{}]".format(plan_type)
            label = email[:max(0, 26 - len(suffix))] + suffix

        row = "  {:<26}  {:>9}  {:>8}  {} {}".format(
            label[:26], mc_str, time_str, indicator, st_str
        )
        print(_box_line(row, W))

    # verdict
    print(_box_line("", W))
    if not files:
        verdict = "  No accounts configured"
    elif all_ok:
        verdict = _C_GREEN + "  \u2714 All accounts OK" + _C_RESET
    else:
        verdict = _C_RED + "  \u26a0 Some accounts degraded" + _C_RESET
    print(_box_line(verdict, W))

    # --- available models section ---
    if proxy_models:
        model_ids = sorted(m.get("id", "") for m in proxy_models.get("data", []))
        if model_ids:
            print(_box_line("", W))
            print(_box_line("  Available Models ({})".format(len(model_ids)), W))
            print(_box_line(divider, W))
            for mid in model_ids:
                print(_box_line("    {}".format(mid[:60]), W))

    print(_box_line("", W))


def cmd_check(base_dir, provider=None):
    """Validate credentials and show per-account model availability."""
    import threading
    import urllib.request
    import urllib.error
    import urllib.parse

    targets = [provider] if provider else list(PROVIDERS)
    W = 68
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(_box_top(W))
    title = "  cc-proxy check"
    padding = W - 4 - len(title) - len(now_str)
    print(_box_line(title + " " * max(1, padding) + now_str, W))

    for pvd in targets:
        s = get_status(base_dir, pvd)
        auth_data = None
        models_per_account = {}
        proxy_models = None
        auth_error = False

        if s["running"] and s["healthy"]:
            secret = _read_secret_key(base_dir, pvd)

            try:
                auth_data = _management_api(pvd, "auth-files", secret)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    auth_error = True
            except Exception:
                pass

            if auth_data and not auth_error:
                files = auth_data.get("files", [])

                def _fetch_models(f, out, _pvd=pvd, _secret=secret):
                    name = f.get("name", "")
                    if not name:
                        return
                    try:
                        qs = "auth-files/models?name={}".format(
                            urllib.parse.quote(name, safe="@.-_")
                        )
                        data = _management_api(_pvd, qs, _secret)
                        out[name] = data.get("models", [])
                    except Exception:
                        out[name] = None

                fetch_threads = [
                    threading.Thread(target=_fetch_models, args=(f, models_per_account))
                    for f in files
                ]
                for t in fetch_threads:
                    t.start()
                for t in fetch_threads:
                    t.join(timeout=8)

            try:
                proxy_models = _proxy_api(pvd, "v1/models")
            except Exception:
                pass

        _print_check_panel(pvd, s, W, auth_data, models_per_account, proxy_models, auth_error)

    print(_box_bottom(W))
    return 0


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
    src_line = 'source "{}/shell/bash/cc-proxy.sh"'.format(base_dir)
    ssh_offset_marker = "CC_PROXY_LOCAL_PORT_OFFSET"
    ssh_offset_block = (
        "# cc-proxy: apply local port offset when connecting via SSH\n"
        '[ -n "${SSH_CONNECTION}" ] && export CC_PROXY_LOCAL_PORT_OFFSET=10000\n'
    )

    rcfiles = []
    for name in (".bashrc", ".zshrc"):
        p = Path.home() / name
        if p.exists():
            rcfiles.append(p)

    if not rcfiles:
        rcfiles = [Path.home() / ".bashrc"]

    missing_src = [p for p in rcfiles if src_line not in p.read_text(errors="replace")]
    missing_offset = [p for p in rcfiles if ssh_offset_marker not in p.read_text(errors="replace")]

    if not missing_src and not missing_offset:
        if not hint_only:
            print("[cc-proxy] Shell profile already contains cc-proxy loader.")
        return

    if hint_only and missing_src:
        print("[cc-proxy] First-time setup detected.")
        try:
            answer = input("[cc-proxy] Add loader to your shell profile now? (Y/N) ")
        except (EOFError, KeyboardInterrupt):
            return
        if not answer.strip().lower().startswith("y"):
            print("[cc-proxy] Skipped. Run cc_proxy_install_profile later.")
            return

    for rc in missing_src:
        with rc.open("a") as f:
            f.write("\n{}\n".format(src_line))
        print("[cc-proxy] Added loader to {}.".format(rc))

    for rc in missing_offset:
        with rc.open("a") as f:
            f.write("\n{}".format(ssh_offset_block))
        print("[cc-proxy] Added SSH port offset config to {}.".format(rc))

    print("[cc-proxy] New terminals will auto-load helpers.")


def _install_profile_windows(base_dir, hint_only):
    script_path = base_dir / "shell" / "powershell" / "cc-proxy.ps1"
    profile_line = '. "{}"'.format(script_path)
    ssh_offset_marker = "CC_PROXY_LOCAL_PORT_OFFSET"
    ssh_offset_block = (
        "# cc-proxy: apply local port offset when connecting via SSH\r\n"
        "if ($env:SSH_CONNECTION) { $env:CC_PROXY_LOCAL_PORT_OFFSET = 10000 }\r\n"
    )

    try:
        res = subprocess.run(
            ["powershell", "-Command", "echo $PROFILE"],
            capture_output=True, text=True
        )
        profile_path = Path(res.stdout.strip())
    except Exception:
        print("[cc-proxy] Could not determine PowerShell profile path.", file=sys.stderr)
        return

    profile_text = profile_path.read_text(errors="replace") if profile_path.exists() else ""
    already_src = profile_line in profile_text
    already_offset = ssh_offset_marker in profile_text

    if already_src and already_offset:
        if not hint_only:
            print("[cc-proxy] PowerShell profile already contains cc-proxy loader.")
        return

    if hint_only and not already_src:
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
        if not already_src:
            f.write("\r\n{}\r\n".format(profile_line))
            print("[cc-proxy] Added loader to {}.".format(profile_path))
        if not already_offset:
            f.write("\r\n{}".format(ssh_offset_block))
            print("[cc-proxy] Added SSH port offset config to {}.".format(profile_path))


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
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        W = 68
        print(_box_top(W))
        title = "  cc-proxy status"
        padding = W - 4 - len(title) - len(now_str)
        print(_box_line(title + " " * max(1, padding) + now_str, W))
        import threading
        prefetched = {}
        def _do_fetch(pvd, out):
            out[pvd] = _prefetch_provider_data(base_dir, pvd)
        fetch_threads = [threading.Thread(target=_do_fetch, args=(pvd, prefetched)) for pvd in targets]
        for t in fetch_threads:
            t.start()
        for t in fetch_threads:
            t.join(timeout=10)
        for pvd in targets:
            data = prefetched.get(pvd, {})
            s = data.get("status") or get_status(base_dir, pvd)
            _print_status_dashboard(base_dir, pvd, s, W,
                                    auth_data=data.get("auth_data"),
                                    usage_data=data.get("usage_data"),
                                    auth_error=data.get("auth_error", False))
        print(_box_bottom(W))
        return 0

    elif cmd == "check":
        provider = args[1] if len(args) > 1 else None
        if provider and provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        return cmd_check(base_dir, provider)

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
