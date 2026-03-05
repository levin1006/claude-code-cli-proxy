"""
Auth, invoke, profile install, and token/secret commands.
Depends on: constants, paths, process, proxy, config, api, usage
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from constants import HOST, IS_WINDOWS, LOGIN_FLAGS, PORTS, PROVIDERS, TOKEN_DIR_ENV, TOKEN_DIR_META_FILE
from paths import (
    _save_token_dir_metadata, _token_prefixes_for_provider,
    get_binary_path, get_config_file, get_provider_dir, get_token_dir,
    resolve_account_file_path,
)
from process import find_free_port, resolve_pid_by_port
from proxy import should_open_auth_browser, start_proxy, stop_proxy
from config import get_token_infos, rewrite_auth_dir_in_config, rewrite_secret_in_config
from usage import _usage_cumulative_clear


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
