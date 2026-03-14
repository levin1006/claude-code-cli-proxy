"""
Proxy lifecycle (start/stop/status).
Also provides _capture_usage_snapshot_before_stop (called from stop_proxy).
Depends on: constants, paths, process, config, api, usage
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from constants import HOST, IS_WINDOWS, PORTS, PROVIDERS
from paths import (
    get_binary_path, get_config_file, get_provider_dir, get_token_dir,
)
from process import (
    check_health, is_pid_alive, kill_all_proxies, kill_pid,
    read_pid, remove_pid, resolve_pid_by_port, write_pid,
)
from config import (
    get_token_infos, rewrite_auth_dir_in_config, rewrite_port_in_config,
)
from api import _management_api, _read_secret_key
from usage import (
    _usage_cumulative_apply_to_usage_data, _usage_snapshot_save,
)


def get_binary_version(base_dir):
    """Run cli-proxy-api -h and extract the CLIProxyAPI Version line."""
    exe = get_binary_path(base_dir)
    if not exe.exists():
        return "Not found"
    try:
        res = subprocess.run([str(exe), "-h"], capture_output=True, text=True, timeout=2)
        out = res.stdout + res.stderr
        for line in out.splitlines():
            if line.startswith("CLIProxyAPI Version:"):
                return line.strip()
    except Exception:
        pass
    return "Unknown"


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
        wd.mkdir(parents=True, exist_ok=True)

    config_path = get_config_file(base_dir, provider)
    if not config_path.exists():
        root_bootstrap = base_dir / "config.yaml"
        if not root_bootstrap.exists():
            if not quiet:
                print("[cc-proxy] No config.yaml found for {}".format(provider), file=sys.stderr)
            return False
        shutil.copy(root_bootstrap, config_path)

    token_dir = get_token_dir(base_dir, create=True)
    rewrite_port_in_config(config_path, PORTS[provider])
    rewrite_auth_dir_in_config(config_path, token_dir)

    existing_pid = resolve_pid_by_port(PORTS[provider])
    if existing_pid:
        write_pid(base_dir, provider, existing_pid)
        if check_health(provider):
            if not quiet:
                print("[cc-proxy] Reusing healthy proxy for {} (pid={})".format(provider, existing_pid))
            return True
        if not quiet:
            print("[cc-proxy] Process on port {} is unhealthy. Stop it first.".format(PORTS[provider]), file=sys.stderr)
        return False

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

