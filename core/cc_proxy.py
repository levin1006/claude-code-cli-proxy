#!/usr/bin/env python3
"""
CLIProxyAPI + Claude Code helper — cross-platform core
Python 3.8+, stdlib only.

Usage:
  python3 core/cc_proxy.py run <preset> [-- claude-args...]
  python3 core/cc_proxy.py start <provider> | all
  python3 core/cc_proxy.py stop [provider]
  python3 core/cc_proxy.py status [provider ...]
  python3 core/cc_proxy.py ui [provider]
  python3 core/cc_proxy.py links [provider]
  python3 core/cc_proxy.py auth <provider>
  python3 core/cc_proxy.py token-dir [path|--reset]
  python3 core/cc_proxy.py token-list [provider]
  python3 core/cc_proxy.py token-delete <provider> <token-file-or-path> [--yes]
  python3 core/cc_proxy.py set-secret <secret>
  python3 core/cc_proxy.py usage-clear [provider]
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
import unicodedata
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

TOKEN_DIR_ENV = "CC_PROXY_TOKEN_DIR"
TOKEN_DIR_META_FILE = ".token-dir"


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


def _token_prefixes_for_provider(provider):
    if provider == "antigravity":
        return ["antigravity", "ag"]
    return [provider]


def _token_file_sort_key(path_obj):
    try:
        st = path_obj.stat()
        return (st.st_mtime, path_obj.name)
    except Exception:
        return (0, path_obj.name)


def _resolve_token_root(base_dir):
    """Resolve shared token directory.

    Priority:
    1) CC_PROXY_TOKEN_DIR env var
    2) <base_dir>/.token-dir file contents
    3) default <base_dir>/configs/tokens
    """
    env_dir = (os.environ.get(TOKEN_DIR_ENV) or "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    meta_path = base_dir / TOKEN_DIR_META_FILE
    if meta_path.exists():
        try:
            txt = meta_path.read_text(encoding="utf-8").strip()
            if txt:
                return Path(txt).expanduser().resolve()
        except Exception:
            pass

    return (base_dir / "configs" / "tokens").resolve()


def get_token_dir(base_dir, create=False):
    token_dir = _resolve_token_root(base_dir)
    if create:
        token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir



def _save_token_dir_metadata(base_dir, token_dir):
    meta_path = base_dir / TOKEN_DIR_META_FILE
    payload = str(Path(token_dir).expanduser().resolve()) + "\n"
    tmp = str(meta_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, str(meta_path))


def get_token_files(base_dir, provider):
    """Return token file paths for a provider from the shared token directory."""
    token_dir = get_token_dir(base_dir, create=False)
    prefixes = _token_prefixes_for_provider(provider)
    token_files = []
    for pfx in prefixes:
        for p in token_dir.glob("{}-*.json".format(pfx)):
            if p.is_file():
                token_files.append(p)
    token_files.sort(key=_token_file_sort_key, reverse=True)
    return token_files


def _is_path_under(path_obj, root_obj):
    try:
        path_obj.resolve().relative_to(root_obj.resolve())
        return True
    except Exception:
        return False


def resolve_account_file_path(base_dir, provider, rel_or_abs_path):
    """Resolve account file path safely against the shared token directory."""
    rel_path = (rel_or_abs_path or "").strip()
    if not rel_path:
        return None, "no file path"

    token_dir = get_token_dir(base_dir, create=False).resolve()

    cand = Path(rel_path).expanduser()
    if cand.is_absolute():
        target = cand.resolve()
    else:
        target = (token_dir / cand).resolve()

    if _is_path_under(target, token_dir):
        return target, None
    return None, "path outside allowed token dir"


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


def start_proxy(base_dir, provider, quiet=False):
    exe = get_binary_path(base_dir)
    if not exe.exists():
        if not quiet:
            print("[cc-proxy] Binary not found: {}".format(exe), file=sys.stderr)
        return False

    wd = get_provider_dir(base_dir, provider)
    if not wd.is_dir():
        if not quiet:
            print("[cc-proxy] Provider config directory not found: {}".format(wd), file=sys.stderr)
        return False

    config_path = get_config_file(base_dir, provider)
    if not config_path.exists():
        root_bootstrap = base_dir / "config.yaml"
        if not root_bootstrap.exists():
            if not quiet:
                print("[cc-proxy] No config.yaml found for {}".format(provider), file=sys.stderr)
            return False
        shutil.copy(root_bootstrap, config_path)

    token_dir = get_token_dir(base_dir, create=True)
    rewrite_auth_dir_in_config(config_path, token_dir)

    existing_pid = resolve_pid_by_port(PORTS[provider])
    if existing_pid:
        write_pid(base_dir, provider, existing_pid)
        if check_health(provider):
            if not quiet:
                print("[cc-proxy] Reusing healthy proxy for {} (pid={})".format(provider, existing_pid))
                status = get_status(base_dir, provider)
                print_management_links(base_dir, provider, statuses={provider: status})
            return True
        if not quiet:
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

    if not quiet:
        print("[cc-proxy] Starting {} proxy...".format(provider))
    for _ in range(15):
        if check_health(provider):
            if not quiet:
                print("[cc-proxy] Proxy ready at http://{}:{}/".format(HOST, PORTS[provider]))
                status = get_status(base_dir, provider)
                print_management_links(base_dir, provider, statuses={provider: status})
            return True
        time.sleep(0.2)

    if not quiet:
        print("[cc-proxy] Failed to become healthy at http://{}:{}/".format(HOST, PORTS[provider]), file=sys.stderr)
    return False


def stop_proxy(base_dir, provider, quiet=False):
    if provider:
        _capture_usage_snapshot_before_stop(base_dir, provider, quiet=quiet)
        pid = read_pid(base_dir, provider)
        if pid and is_pid_alive(pid):
            kill_pid(pid)
            time.sleep(0.25)
        remove_pid(base_dir, provider)
        pid2 = resolve_pid_by_port(PORTS[provider])
        if pid2:
            kill_pid(pid2)
            time.sleep(0.25)
        if not quiet:
            print("[cc-proxy] Stopped {}.".format(provider))
    else:
        for pvd in PROVIDERS:
            _capture_usage_snapshot_before_stop(base_dir, pvd, quiet=True)
            pid = read_pid(base_dir, pvd)
            if pid and is_pid_alive(pid):
                kill_pid(pid)
            remove_pid(base_dir, pvd)
            pid2 = resolve_pid_by_port(PORTS[pvd])
            if pid2:
                kill_pid(pid2)
        kill_all_proxies()
        time.sleep(0.25)
        if not quiet:
            print("[cc-proxy] All proxies stopped.")

    if stop_dashboard_server() and (not quiet):
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
    from datetime import datetime, timezone
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


def _management_api_request(provider, endpoint, secret="cc", method="GET", payload=None, timeout=8):
    """Call /v0/management/<endpoint> with Bearer auth.

    method: GET/POST/DELETE
    payload: dict -> JSON body (for POST/PUT)
    """
    import urllib.request

    port = PORTS[provider]
    url = "http://{}:{}/v0/management/{}".format(HOST, port, endpoint.lstrip("/"))
    headers = {"Authorization": "Bearer {}".format(secret)}
    raw = None
    if payload is not None:
        raw = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=raw, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if not body:
        return {}
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _management_api(provider, endpoint, secret="cc"):
    """GET /v0/management/<endpoint> from a running provider proxy."""
    return _management_api_request(provider, endpoint, secret, method="GET", payload=None, timeout=5)


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


def _fmt_local_dt(iso_str):
    """ISO timestamp → local time 'YYYY-MM-DD HH:MM:SS'."""
    dt = _parse_iso(iso_str)
    if not dt:
        return ""
    local_dt = dt.astimezone()
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


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
        from datetime import datetime, timezone
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
    """Sort key for quota rows: 5h windows first, then 7d, then others.

    Returns lower value for higher priority.
    """
    text = "{} {}".format(model_id or "", (info or {}).get("display", "")).lower()
    if "5h" in text or "five_hour" in text or "primary_window" in text:
        return 0
    if "7d" in text or "seven_day" in text or "secondary_window" in text:
        return 1
    return 2


def _management_api_call(provider, secret, auth_index, method, url, headers, body=None):
    """POST /v0/management/api-call → (upstream_status_code, parsed_body_dict).

    Returns (None, None) on network/management error.
    Upstream 4xx/5xx returned as-is so callers can handle them.
    """
    import urllib.request, urllib.error
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
        "five_hour":      "5h window",
        "seven_day":      "7d window",
        "seven_day_opus": "7d opus",
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

QUOTA_CACHE_TTL = 60  # seconds
USAGE_SNAPSHOT_SCHEMA_VERSION = 1
USAGE_CUMULATIVE_SCHEMA_VERSION = 1


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


def _capture_usage_snapshot_before_stop(base_dir, provider, quiet=False):
    """Capture /usage snapshot before stopping running provider; never raises."""
    try:
        status = get_status(base_dir, provider)
        if not status.get("running"):
            return False
        secret = _read_secret_key(base_dir, provider)
        usage_data = _management_api(provider, "usage", secret)
        if not isinstance(usage_data, dict):
            return False
        ok = _usage_snapshot_save(provider, usage_data, reason="stop")
        if (not quiet) and ok:
            print("[cc-proxy] Saved usage snapshot: {}".format(provider))
        return ok
    except Exception:
        return False


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
        "success_count": int(u.get("success_count", 0) or 0),
        "failure_count": int(u.get("failure_count", 0) or 0),
        "total_tokens": int(u.get("total_tokens", 0) or 0),
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


# ANSI color codes (empty string fallback keeps output clean when piped)
_C_GREEN  = "\033[32m"
_C_RED    = "\033[31m"
_C_BLUE   = "\033[34m"
_C_MAGENTA = "\033[35m"
_C_CYAN   = "\033[36m"
_C_YELLOW = "\033[33m"
_C_DIM    = "\033[2m"
_C_BOLD   = "\033[1m"
_C_RESET  = "\033[0m"

_PROVIDER_BRAND_COLORS = {
    # Brand-first pastel palette with TrueColor + xterm-256 fallback
    # (truecolor_rgb, fallback_256)
    "antigravity": ((152, 190, 220), "\033[38;5;110m"),  # pastel cyan-blue
    "claude": ((233, 168, 142), "\033[38;5;216m"),       # pastel orange
    "codex": ((137, 197, 175), "\033[38;5;114m"),        # pastel mint
    "gemini": ((176, 157, 236), "\033[38;5;147m"),       # pastel violet
}


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

# TUI screen/key constants
_TUI_ALT_ON = "\033[?1049h"
_TUI_ALT_OFF = "\033[?1049l"
_TUI_CURSOR_HIDE = "\033[?25l"
_TUI_CURSOR_SHOW = "\033[?25h"
_TUI_CLEAR = "\033[2J"
_TUI_CLEAR_EOS = "\033[J"
_TUI_HOME = "\033[H"
_TUI_KEY_LEFT = "left"
_TUI_KEY_RIGHT = "right"
_TUI_KEY_UP = "up"
_TUI_KEY_DOWN = "down"
_TUI_KEY_ESC = "esc"

# Linux/Unix stdin sequence buffer (ESC sequence may arrive split)
_TUI_STDIN_BUF = ""
# Windows key event buffer (preserve order: navigation then toggle)
_TUI_WIN_BUF = []

# Optional default edge color for box vertical borders
_BOX_EDGE_COLOR = ""


def _strip_ansi(s):
    return re.sub(r"\033\[[0-9;]*m", "", s)


def _visible_len(s):
    """ANSI 제거 + 동아시아 전각폭 기준으로 실제 표시 폭 계산."""
    plain = _strip_ansi(s)
    w = 0
    for ch in plain:
        # CJK/box-drawing/emoji 계열은 보통 2칸 폭
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
                ts  = detail.get("timestamp", "")
                failed = detail.get("failed", False)
                if src not in account_stats:
                    account_stats[src] = {"requests": 0, "tokens": 0, "fails": 0, "last_time": "", "last_tok": 0}
                account_stats[src]["requests"] += 1
                account_stats[src]["tokens"] += tok
                if failed:
                    account_stats[src]["fails"] += 1
                if ts > account_stats[src]["last_time"]:
                    account_stats[src]["last_time"] = ts
                    account_stats[src]["last_tok"] = tok
    return account_stats


def _prefetch_provider_data(base_dir, provider, fetch_quota=False, fetch_check=False):
    """Fetch all management data for a provider (designed for parallel threading).

    fetch_quota: also call upstream provider quota APIs (slower, ~3-5s per account)
    fetch_check: also fetch per-account model lists from management API
    """
    import threading
    import urllib.error
    import urllib.parse
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
                    name = f.get("name", "")
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
                    name = f.get("name", "")
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
            token_dir_path = "…" + token_dir_path[-(max_path_w - 1):]
        token_dir_line = "  " + _C_DIM + "token-dir: {}".format(token_dir_path) + _C_RESET
        print(_box_line("", W))
        print(_box_line("  Accounts", W))
        print(_box_line(token_dir_line, W))
        print(_box_line(divider, W))
        for f in files:
            email = f.get("email", f.get("name", "?"))
            name = f.get("name", "")
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
            cursor = "▸" if is_selected else " "
            row = "{} {:<26}  {:>9}  {:>8}  {} {}".format(
                cursor, label[:26], mc_str, time_str, indicator, acct_status
            )
            print(_box_line(row, W))

    if not has_usage:
        print(_box_line("", W))
        _BOX_EDGE_COLOR = prev_edge_color
        return

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
            total    = adata["requests"]
            fails    = adata["fails"]
            ok       = total - fails
            tok      = adata["tokens"]
            last_tok = adata["last_tok"]
            dt_str   = _fmt_local_dt(adata["last_time"]) if adata["last_time"] else ""

            # req: right-aligned columns  total  ok  fail (no parentheses)
            req_vis = "{:>3}  {:>3}  {:>3}".format(total, ok, fails)
            req_str = "{:>3}  {}{:>3}{}  {}{:>3}{}".format(
                total,
                _C_GREEN, ok,    _C_RESET,
                _C_RED,   fails, _C_RESET,
            )

            # Format: dim(last_tok) / total_tok  dim(· datetime)
            # last_tok and datetime share dim color for visual grouping;
            # total_tok is default color as the primary value.
            last_tok_s  = _fmt_tokens(last_tok)
            total_tok_s = _fmt_tokens(tok)
            if dt_str:
                tok_vis = "{} / {} · {}".format(last_tok_s, total_tok_s, dt_str)
                tok_str = "{}{}{} / {}{} · {}{}".format(
                    _C_DIM, last_tok_s, _C_RESET,
                    total_tok_s,
                    _C_DIM, dt_str, _C_RESET,
                )
            else:
                tok_vis = total_tok_s
                tok_str = total_tok_s
            row = "    {:<20}  {}  {}".format(
                acct[:20], req_str, tok_str
            )
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
            name = f.get("name", "")
            email = f.get("email", f.get("name", "?"))
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
            # __error__: upstream returned non-200
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
            # Force 5h first, then 7d, then others; tie-break by higher used_pct.
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
        # Use per-account model union (matches the "N models" count shown per account row).
        # Fall back to proxy_models only if per-account data isn't available.
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



def _tui_write(s):
    sys.stdout.write(s)


def _tui_flush():
    sys.stdout.flush()


def _tui_enter_screen():
    _tui_write(_TUI_ALT_ON + _TUI_CURSOR_HIDE + _TUI_HOME + _TUI_CLEAR)
    _tui_flush()


def _tui_leave_screen():
    _tui_write(_TUI_CURSOR_SHOW + _TUI_ALT_OFF)
    _tui_flush()


def _tui_key_to_action(key):
    if not key:
        return None
    if key in (_TUI_KEY_ESC,):
        return key
    if key == "\x1b":
        return _TUI_KEY_ESC
    if key == " ":
        return "toggle"

    lk = unicodedata.normalize("NFKC", key.lower())
    # Support Korean 2-set layout without switching to English:
    # ㅁ/ㄴ/ㅈ/ㅇ → a/s/w/d, ㄱ/ㅂ → r/q
    lk = {
        "ㅁ": "a", "ᄆ": "a",
        "ㄴ": "s", "ᄂ": "s",
        "ㅈ": "w", "ᄌ": "w",
        "ㅇ": "d", "ᄋ": "d",
        "ㄱ": "r", "ᄀ": "r",
        "ㅂ": "q", "ᄇ": "q",
    }.get(lk, lk)

    if lk in ("q", "r"):
        return lk
    if lk in ("a", "s", "w", "d"):
        return {
            "a": _TUI_KEY_LEFT,
            "s": _TUI_KEY_DOWN,
            "w": _TUI_KEY_UP,
            "d": _TUI_KEY_RIGHT,
        }[lk]
    if lk in ("1", "2", "3", "4"):
        return lk
    return None


def _read_key_timeout(timeout_sec=0.5):
    global _TUI_STDIN_BUF, _TUI_WIN_BUF

    if IS_WINDOWS:
        import msvcrt

        # return buffered key first (preserve exact order)
        if _TUI_WIN_BUF:
            return _TUI_WIN_BUF.pop(0)

        end = time.time() + max(0.0, timeout_sec)
        while time.time() < end:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                action = None
                if ch in (b"\x00", b"\xe0"):
                    ch2 = msvcrt.getch()
                    mapping = {
                        b"K": _TUI_KEY_LEFT,
                        b"M": _TUI_KEY_RIGHT,
                        b"H": _TUI_KEY_UP,
                        b"P": _TUI_KEY_DOWN,
                    }
                    action = mapping.get(ch2)
                elif ch == b"\x1b":
                    action = _TUI_KEY_ESC
                else:
                    try:
                        action = ch.decode("utf-8", errors="ignore")
                    except Exception:
                        action = None

                if action is not None:
                    _TUI_WIN_BUF.append(action)

                # drain additional pending keys quickly into buffer
                drain_deadline = time.time() + 0.01
                while time.time() < drain_deadline and msvcrt.kbhit():
                    chx = msvcrt.getch()
                    ax = None
                    if chx in (b"\x00", b"\xe0"):
                        chx2 = msvcrt.getch()
                        ax = {
                            b"K": _TUI_KEY_LEFT,
                            b"M": _TUI_KEY_RIGHT,
                            b"H": _TUI_KEY_UP,
                            b"P": _TUI_KEY_DOWN,
                        }.get(chx2)
                    elif chx == b"\x1b":
                        ax = _TUI_KEY_ESC
                    else:
                        try:
                            ax = chx.decode("utf-8", errors="ignore")
                        except Exception:
                            ax = None
                    if ax is not None:
                        _TUI_WIN_BUF.append(ax)

                return _TUI_WIN_BUF.pop(0) if _TUI_WIN_BUF else None

            time.sleep(0.002)

        return None

    import termios
    import tty
    import select

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)

        # fill local stdin buffer with all currently available bytes
        r, _, _ = select.select([sys.stdin], [], [], max(0.0, timeout_sec))
        if r:
            while True:
                r2, _, _ = select.select([sys.stdin], [], [], 0)
                if not r2:
                    break
                _TUI_STDIN_BUF += sys.stdin.read(1)

        if not _TUI_STDIN_BUF:
            return None

        # If ESC starts a sequence, wait a tiny bit for the remaining bytes.
        if _TUI_STDIN_BUF.startswith("\x1b") and len(_TUI_STDIN_BUF) == 1:
            r3, _, _ = select.select([sys.stdin], [], [], 0.03)
            if r3:
                _TUI_STDIN_BUF += sys.stdin.read(1)
                while True:
                    r4, _, _ = select.select([sys.stdin], [], [], 0)
                    if not r4:
                        break
                    _TUI_STDIN_BUF += sys.stdin.read(1)

        # Parse known sequences first (longest match first)
        seq_map = {
            "\x1b[A": _TUI_KEY_UP,
            "\x1b[B": _TUI_KEY_DOWN,
            "\x1b[C": _TUI_KEY_RIGHT,
            "\x1b[D": _TUI_KEY_LEFT,
            "\x1bOA": _TUI_KEY_UP,
            "\x1bOB": _TUI_KEY_DOWN,
            "\x1bOC": _TUI_KEY_RIGHT,
            "\x1bOD": _TUI_KEY_LEFT,
        }
        for seq in sorted(seq_map.keys(), key=len, reverse=True):
            if _TUI_STDIN_BUF.startswith(seq):
                _TUI_STDIN_BUF = _TUI_STDIN_BUF[len(seq):]
                return seq_map[seq]

        # single-byte fallback
        ch = _TUI_STDIN_BUF[0]
        _TUI_STDIN_BUF = _TUI_STDIN_BUF[1:]
        if ch == "\x1b":
            return _TUI_KEY_ESC
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


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
            name = (f.get("name") or "").strip()
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


def _tui_clear_input_buffer():
    global _TUI_STDIN_BUF, _TUI_WIN_BUF
    _TUI_STDIN_BUF = ""
    _TUI_WIN_BUF = []


def _tui_discard_pending_input(settle_ms=0):
    """Discard queued key events (local + OS buffer).

    settle_ms>0이면 짧은 시간 동안 반복적으로 비워서 토글 직후 key repeat 꼬임을 줄인다.
    """
    _tui_clear_input_buffer()

    def _flush_once():
        try:
            if IS_WINDOWS:
                import msvcrt
                while msvcrt.kbhit():
                    msvcrt.getch()
            else:
                import termios
                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        except Exception:
            pass
        _tui_clear_input_buffer()

    _flush_once()
    if settle_ms and settle_ms > 0:
        end = time.time() + (float(settle_ms) / 1000.0)
        while time.time() < end:
            _flush_once()
            time.sleep(0.005)


def _tui_fetch_provider(base_dir, provider):
    d = _prefetch_provider_data(
        base_dir,
        provider,
        fetch_quota=True,
        fetch_check=True,
    )
    d["auth_data"] = _dedupe_auth_files(d.get("auth_data"), provider=provider)
    return d


def _tui_fetch_provider_light(base_dir, provider):
    """Faster refresh path: skip quota/check heavy calls."""
    d = _prefetch_provider_data(
        base_dir,
        provider,
        fetch_quota=False,
        fetch_check=False,
    )
    d["auth_data"] = _dedupe_auth_files(d.get("auth_data"), provider=provider)
    return d


def _tui_toggle_account(base_dir, provider, account, progress_cb=None):
    """Toggle disabled flag by directly editing the selected account JSON file.

    원칙:
    - 반드시 선택된 account의 path 파일만 수정
    - runtime-only/non-file 계정은 수정하지 않음
    - atomic write(임시파일 + replace)로 파일 손상 방지
    """
    def _progress(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if not account:
        return False, "no account selected"

    if account.get("runtime_only"):
        return False, "toggle unsupported: runtime-only account"
    if account.get("source") and account.get("source") != "file":
        return False, "toggle unsupported: non-file account"

    rel_path = (account.get("path") or "").strip()
    if not rel_path:
        return False, "toggle unsupported: no file path"

    file_path, err = resolve_account_file_path(base_dir, provider, rel_path)
    if err:
        return False, "toggle blocked: {}".format(err)
    if file_path is None:
        return False, "toggle unsupported: file path resolve failed"

    if not file_path.exists() or not file_path.is_file():
        return False, "toggle unsupported: file not found"

    _progress(_C_DIM + "파일 읽는 중..." + _C_RESET)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, "read failed: {}".format(e)

    try:
        obj = json.loads(raw)
    except Exception as e:
        return False, "json parse failed: {}".format(e)

    if not isinstance(obj, dict):
        return False, "json shape invalid"

    obj["disabled"] = not bool(obj.get("disabled", False))

    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    if not payload.endswith("\n"):
        payload += "\n"

    _progress(_C_DIM + "파일 저장 중..." + _C_RESET)
    tmp = file_path.with_name(file_path.name + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(str(tmp), str(file_path))
    except Exception as e:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False, "write failed: {}".format(e)

    # binary가 파일 변경을 즉시 반영하지 않는 환경이 있어 provider 재기동으로 확정 반영
    try:
        status = get_status(base_dir, provider)
        if status.get("running"):
            _progress(_C_DIM + "provider 재시작 중..." + _C_RESET)
            stop_proxy(base_dir, provider, quiet=True)
            if not start_proxy(base_dir, provider, quiet=True):
                return False, "toggle saved but restart failed"
    except Exception as e:
        return False, "toggle saved but reload failed: {}".format(e)

    return True, "toggled"


def _tui_render(base_dir, state):
    provider = state["providers"][state["provider_idx"]]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    term_w = shutil.get_terminal_size(fallback=(100, 24)).columns
    W = max(84, min(term_w - 2, 140))

    data = state["data"].get(provider)
    if data is None:
        data = _tui_fetch_provider(base_dir, provider)
        state["data"][provider] = data

    files = (data.get("auth_data") or {}).get("files", [])
    if files:
        state["account_idx"] = max(0, min(state["account_idx"], len(files) - 1))
        selected = files[state["account_idx"]]
        selected_name = selected.get("name")
        selected_key = _account_identity(selected)
    else:
        state["account_idx"] = 0
        selected = None
        selected_name = None
        selected_key = None

    tabs = []
    for i, pvd in enumerate(state["providers"]):
        label = "{} {}".format(i + 1, pvd)
        if i == state["provider_idx"]:
            label = _C_BOLD + "[{}]".format(label) + _C_RESET
        tabs.append(label)
    tab_line = "  " + "   ".join(tabs)

    footer_keys = "  a/d provider   w/s account   space toggle   r refresh   q quit"
    if state.get("message"):
        msg = "  " + state["message"]
    else:
        msg = "  " + _C_DIM + "ready" + _C_RESET

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        frame_color = _provider_frame_color(provider)
        if frame_color:
            print(frame_color + _box_top(W) + _C_RESET)
        else:
            print(_box_top(W))
        title = "  cc-proxy ui"
        padding = W - 4 - len(re.sub(r"\033\[[0-9;]*m", "", title)) - len(now_str)
        if frame_color:
            print(frame_color + _box_line(title + " " * max(1, padding) + now_str, W) + _C_RESET)
            print(frame_color + _box_sep(W) + _C_RESET)
            print(frame_color + _box_line(tab_line, W) + _C_RESET)
        else:
            print(_box_line(title + " " * max(1, padding) + now_str, W))
            print(_box_sep(W))
            print(_box_line(tab_line, W))

        _print_status_dashboard(
            base_dir,
            provider,
            data.get("status") or get_status(base_dir, provider),
            W,
            auth_data=data.get("auth_data"),
            usage_data=data.get("usage_data"),
            auth_error=data.get("auth_error", False),
            usage_source=data.get("usage_source", "none"),
            usage_snapshot_at=data.get("usage_snapshot_at"),
            models_per_account=data.get("models_per_account"),
            quota_data=data.get("quota_data"),
            proxy_models=data.get("proxy_models"),
            show_check=True,
            selected_account_name=selected_name,
            selected_account_key=selected_key,
            frame_color=frame_color,
        )

        if frame_color:
            print(frame_color + _box_sep(W) + _C_RESET)
        else:
            print(_box_sep(W))
        if frame_color:
            print(frame_color + _box_line(msg, W) + _C_RESET)
            print(frame_color + _box_line(footer_keys, W) + _C_RESET)
            print(frame_color + _box_bottom(W) + _C_RESET)
        else:
            print(_box_line(msg, W))
            print(_box_line(footer_keys, W))
            print(_box_bottom(W))

    rendered = buf.getvalue()

    # Full-frame repaint for stable terminal compatibility.
    _tui_write(_TUI_HOME + _TUI_CLEAR)
    _tui_write(rendered)
    _tui_flush()

    return selected


def _tui_main_loop(base_dir, provider=None):
    state = {
        "providers": [provider] if provider else list(PROVIDERS),
        "provider_idx": 0,
        "account_idx": 0,
        "data": {},
        "last_fetch": {},
        "message": "",
        "busy": False,
        "toggle_cooldown_until": 0.0,
    }

    def _mark_busy(on):
        state["busy"] = bool(on)

    refresh_interval = 5.0

    def _refresh_provider(pvd, force=False, heavy=False):
        last = state["last_fetch"].get(pvd, 0)
        if force or (time.time() - last) >= refresh_interval:
            if heavy:
                fresh = _tui_fetch_provider(base_dir, pvd)
                state["data"][pvd] = fresh
            else:
                fresh = _tui_fetch_provider_light(base_dir, pvd)
                cur = state["data"].get(pvd, {})
                # keep previously fetched heavy sections (quota/models) to avoid flicker/latency
                if cur.get("quota_data") and not fresh.get("quota_data"):
                    fresh["quota_data"] = cur.get("quota_data")
                if cur.get("models_per_account") and not fresh.get("models_per_account"):
                    fresh["models_per_account"] = cur.get("models_per_account")
                if cur.get("proxy_models") and not fresh.get("proxy_models"):
                    fresh["proxy_models"] = cur.get("proxy_models")
                state["data"][pvd] = fresh
            state["last_fetch"][pvd] = time.time()
            return True
        return False

    def _refresh_current(force=False, heavy=False):
        pvd = state["providers"][state["provider_idx"]]
        return _refresh_provider(pvd, force=force, heavy=heavy)

    def _prefetch_all_once():
        import threading

        results = {}
        ts = time.time()

        def _one(pvd):
            try:
                results[pvd] = _tui_fetch_provider(base_dir, pvd)
            except Exception:
                results[pvd] = {"status": get_status(base_dir, pvd)}

        threads = [threading.Thread(target=_one, args=(pvd,)) for pvd in state["providers"]]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        for pvd in state["providers"]:
            if pvd in results:
                state["data"][pvd] = results[pvd]
                state["last_fetch"][pvd] = ts

    _tui_enter_screen()
    try:
        _prefetch_all_once()
        selected = _tui_render(base_dir, state)

        while True:
            action = _tui_key_to_action(_read_key_timeout(0.03))
            dirty = False

            # auto refresh is disabled in TUI loop to keep key responsiveness stable.
            # use 'r' for explicit refresh.

            if action is None:
                if dirty:
                    selected = _tui_render(base_dir, state)
                continue

            if action == "q":
                return 0
            if action == _TUI_KEY_ESC:
                # Windows Terminal에서 화살표 시퀀스가 ESC로 축약되는 경우가 있어
                # 오동작 종료를 방지하기 위해 ESC 단독 종료는 임시 비활성화.
                state["message"] = _C_DIM + "press q to quit" + _C_RESET
                dirty = True

            # when busy (toggle in-flight), ignore all inputs except quit.
            if state.get("busy"):
                state["message"] = _C_DIM + "toggle in progress..." + _C_RESET
                dirty = True
                if dirty:
                    selected = _tui_render(base_dir, state)
                continue

            if action == _TUI_KEY_LEFT:
                state["provider_idx"] = (state["provider_idx"] - 1) % len(state["providers"])
                state["account_idx"] = 0
                state["message"] = ""
                _refresh_current(force=True, heavy=False)
                dirty = True
            elif action == _TUI_KEY_RIGHT:
                state["provider_idx"] = (state["provider_idx"] + 1) % len(state["providers"])
                state["account_idx"] = 0
                state["message"] = ""
                _refresh_current(force=True, heavy=False)
                dirty = True
            elif action == _TUI_KEY_UP:
                prev = state["account_idx"]
                state["account_idx"] = max(0, state["account_idx"] - 1)
                state["message"] = ""
                dirty = (state["account_idx"] != prev)
            elif action == _TUI_KEY_DOWN:
                pvd = state["providers"][state["provider_idx"]]
                files = (state["data"].get(pvd, {}).get("auth_data") or {}).get("files", [])
                prev = state["account_idx"]
                if files:
                    state["account_idx"] = min(len(files) - 1, state["account_idx"] + 1)
                state["message"] = ""
                dirty = (state["account_idx"] != prev)
            elif action in ("1", "2", "3", "4"):
                idx = int(action) - 1
                if idx < len(state["providers"]) and idx != state["provider_idx"]:
                    state["provider_idx"] = idx
                    state["account_idx"] = 0
                    state["message"] = ""
                    _refresh_current(force=True, heavy=False)
                    dirty = True
            elif action == "r":
                _mark_busy(True)
                _tui_discard_pending_input(settle_ms=20)
                _refresh_current(force=True, heavy=True)
                _tui_discard_pending_input(settle_ms=20)
                _mark_busy(False)
                state["message"] = _C_DIM + "refreshed" + _C_RESET
                dirty = True
            elif action == "toggle":
                now = time.time()
                if now < state.get("toggle_cooldown_until", 0.0):
                    state["message"] = _C_DIM + "toggle cooldown..." + _C_RESET
                    dirty = True
                else:
                    pvd = state["providers"][state["provider_idx"]]
                    files = (state["data"].get(pvd, {}).get("auth_data") or {}).get("files", [])
                    if not files:
                        state["message"] = _C_DIM + "no account" + _C_RESET
                        dirty = True
                    else:
                        idx = max(0, min(state["account_idx"], len(files) - 1))
                        target = files[idx]
                        target_key = _account_identity(target)
                        target_email = target.get("email") or target.get("account") or target.get("name") or "?"

                        # 안정성 우선 모드: old-stable 토글 시퀀스 + 진행 로그
                        _mark_busy(True)
                        state["toggle_cooldown_until"] = time.time() + 1.0

                        try:
                            def _progress(msg):
                                state["message"] = msg
                                _tui_render(base_dir, state)

                            state["message"] = _C_DIM + "[1/3] toggling file: {}".format(target_email[:24]) + _C_RESET
                            selected = _tui_render(base_dir, state)
                            ok, m = _tui_toggle_account(base_dir, pvd, target, progress_cb=_progress)

                            state["message"] = _C_DIM + "[2/3] refreshing provider data..." + _C_RESET
                            selected = _tui_render(base_dir, state)

                            # old-stable behavior: heavy refresh for definitive state
                            _refresh_current(force=True, heavy=True)
                            files2 = (state["data"].get(pvd, {}).get("auth_data") or {}).get("files", [])
                            if files2:
                                restored = None
                                for i2, f2 in enumerate(files2):
                                    if _account_identity(f2) == target_key:
                                        restored = i2
                                        break
                                if restored is None:
                                    for i2, f2 in enumerate(files2):
                                        em2 = f2.get("email") or f2.get("account") or f2.get("name") or ""
                                        if em2 == target_email:
                                            restored = i2
                                            break
                                if restored is not None:
                                    state["account_idx"] = restored
                                else:
                                    state["account_idx"] = min(idx, len(files2) - 1)

                            if ok:
                                state["message"] = _C_GREEN + "[3/3] toggled: {}".format(target_email[:24]) + _C_RESET
                            else:
                                state["message"] = _C_RED + m + _C_RESET
                            dirty = True
                        finally:
                            _tui_discard_pending_input(settle_ms=120)
                            _mark_busy(False)

            if dirty:
                selected = _tui_render(base_dir, state)

    finally:
        _tui_leave_screen()


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

    token_dir = get_token_dir(base_dir, create=True)
    rewrite_auth_dir_in_config(config_path, token_dir)

    extra_flags = []
    if not should_open_auth_browser():
        extra_flags.append("-no-browser")

    free_port = 54545 if provider == "claude" else find_free_port(3000, 3020)
    extra_flags += ["-oauth-callback-port", str(free_port)]

    login_flag = LOGIN_FLAGS[provider]
    print("[cc-proxy] Starting auth for provider '{}' (callback port {})...".format(provider, free_port))
    print("[cc-proxy] Token file will be saved to: {}".format(token_dir))

    cmd = [str(exe), "-config", str(config_path), login_flag] + extra_flags
    env = os.environ.copy()
    env["CLIPROXY_AUTH_DIR"] = str(token_dir)
    env["AUTH_DIR"] = str(token_dir)
    result = subprocess.run(cmd, cwd=str(wd), env=env)
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


def _propagate_token_dir(base_dir, resolved):
    """Update all provider configs and restart running providers with new token-dir."""
    updated = 0
    for pvd in PROVIDERS:
        config_path = get_config_file(base_dir, pvd)
        if config_path.exists():
            rewrite_auth_dir_in_config(config_path, resolved)
            updated += 1
    if updated:
        print("[cc-proxy] Updated auth-dir in {} provider config(s).".format(updated))

    restarted = 0
    for pvd in PROVIDERS:
        if resolve_pid_by_port(PORTS[pvd]):
            print("[cc-proxy] Restarting provider: {}".format(pvd))
            stop_proxy(base_dir, pvd, quiet=True)
            if start_proxy(base_dir, pvd, quiet=True):
                restarted += 1
            else:
                print("[cc-proxy] Failed to restart: {}".format(pvd), file=sys.stderr)
    if restarted:
        print("[cc-proxy] Restarted {} running provider(s).".format(restarted))
    else:
        print("[cc-proxy] No running providers — new token-dir takes effect on next start.")


def cmd_token_dir(base_dir, token_dir=None, reset=False):
    if reset:
        meta_path = base_dir / TOKEN_DIR_META_FILE
        if meta_path.exists():
            meta_path.unlink()
            print("[cc-proxy] token-dir reset to default.")
        else:
            print("[cc-proxy] token-dir is already using the default (no override set).")
        default_dir = base_dir / "configs" / "tokens"
        _propagate_token_dir(base_dir, default_dir)
        print("[cc-proxy] token-dir: {}".format(default_dir))
        return 0

    if token_dir:
        resolved = Path(token_dir).expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        _save_token_dir_metadata(base_dir, resolved)
        print("[cc-proxy] token-dir set: {}".format(resolved))
        print("[cc-proxy] Hint: export {}='{}' to override per session.".format(TOKEN_DIR_ENV, resolved))
        _propagate_token_dir(base_dir, resolved)
        return 0

    current = get_token_dir(base_dir, create=False)
    print("[cc-proxy] token-dir: {}".format(current))
    env_dir = (os.environ.get(TOKEN_DIR_ENV) or "").strip()
    if env_dir:
        print("[cc-proxy] source: env ({})".format(TOKEN_DIR_ENV))
    elif (base_dir / TOKEN_DIR_META_FILE).exists():
        print("[cc-proxy] source: {}".format(TOKEN_DIR_META_FILE))
    else:
        print("[cc-proxy] source: default (configs/tokens)")
    return 0


def cmd_token_list(base_dir, provider=None):
    targets = [provider] if provider else list(PROVIDERS)
    for pvd in targets:
        infos = get_token_infos(base_dir, pvd)
        print("[cc-proxy] token-list {} ({}):".format(pvd, len(infos)))
        if not infos:
            print("[cc-proxy]   (none)")
            continue
        for i, t in enumerate(infos, start=1):
            label = t.get("email") or t.get("file") or "?"
            print("[cc-proxy]   {:>2}. {:<36}  {:<18} {}".format(
                i, label[:36], t.get("status", "unknown"), t.get("path", "")
            ))
    return 0


def cmd_token_delete(base_dir, provider, token_name_or_path, yes=False):
    provider = (provider or "").strip()
    target = (token_name_or_path or "").strip()

    if provider not in PROVIDERS:
        print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
        return 1
    if not target:
        print("[cc-proxy] Usage: token-delete <provider> <token-file-or-path> [--yes]", file=sys.stderr)
        return 1

    infos = get_token_infos(base_dir, provider)
    if not infos:
        print("[cc-proxy] No token files for provider '{}'".format(provider), file=sys.stderr)
        return 1

    matched = None
    for t in infos:
        p = t.get("path") or ""
        name = Path(p).name if p else (t.get("file") or "")
        stem = Path(name).stem if name else ""
        email = (t.get("email") or "").strip()
        if target in (name, stem, p, email):
            matched = t
            break

    if matched is None:
        # absolute/relative path fallback resolve (still guarded)
        resolved, err = resolve_account_file_path(base_dir, provider, target)
        if err:
            print("[cc-proxy] token-delete blocked: {}".format(err), file=sys.stderr)
            return 1
        if resolved is None:
            print("[cc-proxy] token-delete failed: cannot resolve target", file=sys.stderr)
            return 1
        for t in infos:
            if (t.get("path") or "") == str(resolved):
                matched = t
                break

    if matched is None:
        print("[cc-proxy] token-delete failed: token not found for provider '{}'".format(provider), file=sys.stderr)
        return 1

    token_path = Path(matched.get("path") or "")
    if not token_path.exists() or not token_path.is_file():
        print("[cc-proxy] token-delete failed: file not found", file=sys.stderr)
        return 1

    # provider prefix guard
    stem = token_path.name
    prefixes = tuple("{}-".format(pfx) for pfx in _token_prefixes_for_provider(provider))
    if not stem.startswith(prefixes):
        print("[cc-proxy] token-delete blocked: filename prefix mismatch ({})".format(stem), file=sys.stderr)
        return 1

    if not yes:
        print("[cc-proxy] Refusing to delete without --yes")
        print("[cc-proxy] target: {}".format(token_path))
        return 1

    try:
        token_path.unlink()
        print("[cc-proxy] token deleted: {}".format(token_path))
        return 0
    except Exception as e:
        print("[cc-proxy] token-delete failed: {}".format(e), file=sys.stderr)
        return 1


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

    elif cmd == "ui":
        provider = args[1] if len(args) > 1 else None
        if provider and provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        return _tui_main_loop(base_dir, provider)

    elif cmd in ("status", "check"):
        # Parse flags and optional provider list from remaining args
        rest = args[1:]
        show_quota = "--quota" in rest
        show_check = (cmd == "check") or ("--check" in rest)
        show_short = "--short" in rest or "-s" in rest
        positional = [a for a in rest if not a.startswith("--") and a != "-s"]
        invalid = [p for p in positional if p not in PROVIDERS]
        if invalid:
            print("[cc-proxy] Invalid provider: {}".format(", ".join(invalid)), file=sys.stderr)
            return 1
        # preserve user order while deduplicating
        targets = list(dict.fromkeys(positional)) if positional else list(PROVIDERS)

        import threading
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefetched = {}

        def _do_fetch(pvd, out):
            out[pvd] = _prefetch_provider_data(
                base_dir, pvd,
                fetch_quota=show_quota,
                fetch_check=show_check,
            )

        fetch_threads = [threading.Thread(target=_do_fetch, args=(pvd, prefetched))
                         for pvd in targets]
        for t in fetch_threads:
            t.start()
        for t in fetch_threads:
            t.join(timeout=15)

        # Compute minimum width from actual email lengths
        term_w = shutil.get_terminal_size(fallback=(80, 24)).columns
        min_content = 72
        for pvd in targets:
            d = prefetched.get(pvd, {})
            for f in (d.get("auth_data") or {}).get("files", []):
                email = f.get("email") or f.get("name") or ""
                min_content = max(min_content, len(email) + 24)
        W = max(min_content + 4, min(term_w - 2, 120))

        flags = ("--quota " if show_quota else "") + ("--check" if show_check else "") + ("-s" if show_short else "")
        title = "  cc-proxy status {}".format(flags).rstrip()

        if show_short:
            # Compact: one summary line per provider
            W = max(72, min(term_w - 2, 120))
            print(_box_top(W))
            padding = W - 4 - len(title) - len(now_str)
            print(_box_line(title + " " * max(1, padding) + now_str, W))
            print(_box_sep(W))
            for pvd in targets:
                data   = prefetched.get(pvd, {})
                s      = data.get("status") or get_status(base_dir, pvd)
                port   = PORTS[pvd]
                files  = (data.get("auth_data") or {}).get("files", [])
                n_acct = len(files)
                u      = (data.get("usage_data") or {}).get("usage", {})
                t_req  = u.get("total_requests", 0)
                t_tok  = _fmt_tokens(u.get("total_tokens", 0))
                usage_src = data.get("usage_source", "none")
                if s.get("running"):
                    dot = _C_GREEN + "\u25cf" + _C_RESET
                    state = "running"
                    snap_tag = ""
                else:
                    dot = _C_DIM + "\u25cb" + _C_RESET
                    state = "stopped"
                    snap_tag = " [snap]" if usage_src == "snapshot" else ""
                row = "  {:<13} :{:5d}  {} {:<7}{}  {:>2} accts  {:>5} req  {:>6} tok".format(
                    pvd, port, dot, state, snap_tag, n_acct, t_req, t_tok
                )
                print(_box_line(row, W))
            print(_box_bottom(W))
        else:
            print(_box_top(W))
            padding = W - 4 - len(title) - len(now_str)
            print(_box_line(title + " " * max(1, padding) + now_str, W))
            for pvd in targets:
                data = prefetched.get(pvd, {})
                s = data.get("status") or get_status(base_dir, pvd)
                _print_status_dashboard(
                    base_dir, pvd, s, W,
                    auth_data=data.get("auth_data"),
                    usage_data=data.get("usage_data"),
                    auth_error=data.get("auth_error", False),
                    usage_source=data.get("usage_source", "none"),
                    usage_snapshot_at=data.get("usage_snapshot_at"),
                    models_per_account=data.get("models_per_account"),
                    quota_data=data.get("quota_data") if show_quota else None,
                    proxy_models=data.get("proxy_models"),
                    show_check=show_check,
                    frame_color=_provider_frame_color(pvd),
                )
            print(_box_bottom(W))
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

    elif cmd == "token-dir":
        rest = args[1:]
        if rest and rest[0] == "--reset":
            return cmd_token_dir(base_dir, reset=True)
        token_dir = rest[0] if rest else None
        return cmd_token_dir(base_dir, token_dir)

    elif cmd == "token-list":
        if len(args) > 2:
            print("[cc-proxy] Usage: token-list [provider]", file=sys.stderr)
            return 1
        provider = args[1] if len(args) > 1 else None
        if provider and provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        return cmd_token_list(base_dir, provider)

    elif cmd == "token-delete":
        if len(args) < 3:
            print("[cc-proxy] Usage: token-delete <provider> <token-file-or-path> [--yes]", file=sys.stderr)
            return 1
        provider = args[1]
        target = args[2]
        yes = "--yes" in args[3:]
        return cmd_token_delete(base_dir, provider, target, yes=yes)

    elif cmd == "set-secret":
        if len(args) < 2:
            print("[cc-proxy] Usage: set-secret <secret>", file=sys.stderr)
            return 1
        cmd_set_secret(base_dir, args[1])
        return 0

    elif cmd == "usage-clear":
        provider = args[1] if len(args) > 1 else None
        if provider:
            if provider not in PROVIDERS:
                print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
                return 1
            _usage_cumulative_clear(provider)
            print("[cc-proxy] Cleared cumulative usage: {}".format(provider))
        else:
            for pvd in PROVIDERS:
                _usage_cumulative_clear(pvd)
            print("[cc-proxy] Cleared cumulative usage: all providers")
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
