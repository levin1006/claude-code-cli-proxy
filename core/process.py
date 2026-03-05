"""
PID/process management, port resolution, health check, and clipboard utilities.
Depends on: constants, paths
"""

import os
import re
import signal
import socket
import shutil
import subprocess
import sys
import time

from constants import IS_WINDOWS, HOST, PORTS
from paths import get_pid_file


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
