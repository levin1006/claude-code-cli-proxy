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

Module structure (core/):
  constants.py  — shared constants, ANSI codes, TUI key codes
  paths.py      — path resolution, token directory helpers
  process.py    — PID management, port lookup, health check, clipboard
  config.py     — YAML config rewriting, token parsing/validation
  api.py        — management API client, secret key resolution
  quota.py      — upstream quota fetching and caching
  usage.py      — usage snapshot and cumulative tracking
  proxy.py      — proxy lifecycle (start/stop/status), dashboard server
  display.py    — ANSI formatting, box drawing, status dashboard rendering
  tui.py        — terminal UI main loop
  commands.py   — auth, invoke, profile install, token/secret commands
"""

import shutil
import sys
import threading
from datetime import datetime

from constants import PORTS, PRESETS, PROVIDERS
from paths import get_base_dir
from proxy import cmd_links, get_status, start_proxy, stop_proxy
from config import ensure_tokens
from tui import _tui_main_loop
from display import (
    _box_bottom, _box_line, _box_sep, _box_top,
    _fmt_tokens, _prefetch_provider_data, _print_status_dashboard,
    _provider_frame_color,
)
from usage import _usage_cumulative_clear
from commands import (
    cmd_set_secret, cmd_token_delete, cmd_token_dir, cmd_token_list,
    install_profile, invoke_claude, run_auth,
)


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

    elif cmd == "version":
        from proxy import get_binary_version
        v = get_binary_version(base_dir)
        print("[cc-proxy] core helper loaded. Binary status: {}".format(v))
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
                from constants import _C_DIM, _C_GREEN, _C_RESET
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

        from process import resolve_pid_by_port
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
        import os
        import shutil as _shutil
        env = os.environ.copy()
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL"):
            env.pop(key, None)
        import subprocess
        claude_bin = _shutil.which("claude") or "claude"
        result = subprocess.run([claude_bin] + claude_args, env=env)
        return result.returncode

    else:
        print("[cc-proxy] Unknown command: {}".format(cmd), file=sys.stderr)
        print_usage()
        return 1


if __name__ == "__main__":
    sys.exit(main())
