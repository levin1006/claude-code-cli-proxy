"""
Proxy lifecycle (start/stop/status), dashboard server, and management link helpers.
Also provides _capture_usage_snapshot_before_stop (called from stop_proxy).
Depends on: constants, paths, process, config, api, usage
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from constants import HOST, IS_WINDOWS, PORTS, PROVIDERS
from paths import (
    get_binary_path, get_config_file, get_provider_dir, get_token_dir,
)
from process import (
    check_health, is_pid_alive, kill_all_proxies, kill_pid,
    read_pid, remove_pid, resolve_pid_by_port, try_copy_to_clipboard,
    write_pid,
)
from config import (
    get_token_infos, rewrite_auth_dir_in_config, rewrite_port_in_config,
)
from api import _management_api, _read_secret_key
from usage import (
    _usage_cumulative_apply_to_usage_data, _usage_snapshot_save,
)


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
