#!/usr/bin/env python3
"""
CLIProxyAPI + Claude Code helper — cross-platform core
Python 3.8+, stdlib only.

Usage:
  python3 cc_proxy.py run <preset> [-- claude-args...]
  python3 cc_proxy.py start <provider>
  python3 cc_proxy.py stop [provider]
  python3 cc_proxy.py status [provider]
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
import webbrowser
from pathlib import Path
from datetime import datetime, timezone


IS_WINDOWS = sys.platform == "win32"

PROVIDERS = ("claude", "gemini", "codex", "antigravity")

PORTS = {
    "claude":      18417,
    "gemini":      18418,
    "codex":       18419,
    "antigravity": 18420,
}

HOST = "127.0.0.1"

PRESETS = {
    "claude":    ("claude",       "claude-opus-4-6",           "claude-sonnet-4-6",       "claude-haiku-4-5-20251001"),
    "gemini":    ("gemini",       "gemini-3-pro-preview",      "gemini-3-flash-preview",  "gemini-2.5-flash-lite"),
    "codex":     ("codex",        "gpt-5.3-codex(xhigh)",      "gpt-5.3-codex(high)",     "gpt-5.3-codex-spark"),
    "ag-claude": ("antigravity",  "claude-opus-4-6-thinking",  "claude-sonnet-4-6",       "claude-sonnet-4-6"),
    "ag-gemini": ("antigravity",  "gemini-3.1-pro-high",       "gemini-3.1-pro-low",      "gemini-3-flash"),
}

LOGIN_FLAGS = {
    "claude":      "-claude-login",
    "gemini":      "-login",
    "codex":       "-codex-login",
    "antigravity": "-antigravity-login",
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


def should_open_browser():
    mode = os.environ.get("CC_PROXY_MANAGEMENT_AUTO_OPEN", "auto").lower()
    if mode in ("never", "false", "0"):
        return False
    if mode in ("always", "true", "1"):
        return True
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if not IS_WINDOWS:
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return False
    return True


def open_management_ui(provider):
    if not should_open_browser():
        return
    marker = Path(tempfile.gettempdir()) / "cc_proxy_mgmt_{}_{}".format(os.getppid(), provider)
    if marker.exists():
        return
    marker.touch()
    url = "http://{}:{}/management.html".format(HOST, PORTS[provider])
    try:
        webbrowser.open(url)
    except Exception:
        print("[cc-proxy] Management UI: {}".format(url))


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
    import json
    import glob as glob_mod

    token_dir = get_provider_dir(base_dir, provider)
    if not token_dir.is_dir():
        print("[cc-proxy] Config directory for {} does not exist. Running auth...".format(provider))
        return run_auth(base_dir, provider)

    pattern = str(token_dir / "{}-*.json".format(provider))
    token_files = sorted(glob_mod.glob(pattern))

    if not token_files:
        print("[cc-proxy] No token files found for {}. Running auth...".format(provider))
        return run_auth(base_dir, provider)

    print("[cc-proxy] Checking tokens for provider: {}".format(provider))
    now = datetime.now(tz=timezone.utc)
    valid = 0
    expired = 0

    for tf in token_files:
        try:
            with open(tf, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            print("[cc-proxy]   SKIP  {}  (parse error)".format(os.path.basename(tf)))
            continue

        label = data.get("email") or os.path.basename(tf)

        expire_raw = data.get("expired")
        if expire_raw is None:
            tok = data.get("token", {})
            if isinstance(tok, dict):
                expire_raw = tok.get("expiry")

        if expire_raw is None:
            print("[cc-proxy]   SKIP  {}  (no expiry field)".format(label))
            continue

        expire_dt = _parse_iso(str(expire_raw))
        if expire_dt is None:
            print("[cc-proxy]   SKIP  {}  (cannot parse expiry: {})".format(label, expire_raw))
            continue

        if expire_dt.tzinfo is None:
            expire_dt = expire_dt.replace(tzinfo=timezone.utc)

        if expire_dt > now:
            valid += 1
            remaining_h = int((expire_dt - now).total_seconds() / 3600) + 1
            print("[cc-proxy]   OK    {}  (expires in {}h)".format(label, remaining_h))
        else:
            expired += 1
            print("[cc-proxy]   EXPIRED  {}  (expired: {})".format(label, expire_raw))

    print("[cc-proxy] Result: {} valid, {} expired".format(valid, expired))

    if valid == len(token_files):
        return True

    print("[cc-proxy] Some tokens for {} are invalid or expired. Running auth...".format(provider))
    return run_auth(base_dir, provider)


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
            open_management_ui(provider)
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


def get_status(base_dir, provider):
    pid = read_pid(base_dir, provider)
    if not pid:
        pid = resolve_pid_by_port(PORTS[provider])
        if pid:
            write_pid(base_dir, provider, pid)

    running = bool(pid and is_pid_alive(pid))
    healthy = check_health(provider) if running else False
    return {
        "provider": provider,
        "running": running,
        "pid": pid if running else None,
        "healthy": healthy,
        "url": "http://{}:{}".format(HOST, PORTS[provider]),
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
    if not should_open_browser():
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

    claude_bin = shutil.which("cc-ag-claude") or "cc-ag-claude"
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
            print("[cc-proxy] Usage: start <provider>", file=sys.stderr)
            return 1
        provider = args[1]
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
        return 0

    elif cmd == "auth":
        if len(args) < 2:
            print("[cc-proxy] Usage: auth <provider>", file=sys.stderr)
            return 1
        provider = args[1]
        if provider not in PROVIDERS:
            print("[cc-proxy] Invalid provider: {}".format(provider), file=sys.stderr)
            return 1
        return 0 if run_auth(base_dir, provider) else 1

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
        claude_bin = shutil.which("cc-ag-claude") or "cc-ag-claude"
        result = subprocess.run([claude_bin] + claude_args, env=env)
        return result.returncode

    else:
        print("[cc-proxy] Unknown command: {}".format(cmd), file=sys.stderr)
        print_usage()
        return 1


if __name__ == "__main__":
    sys.exit(main())
