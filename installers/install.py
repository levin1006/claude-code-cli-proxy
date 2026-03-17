import argparse
import json
import shutil
import stat
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# --- Configuration ---
MIN_PYTHON_VERSION = (3, 8)
DEFAULT_REPO = "levin1006/claude-code-cli-proxy"
DEFAULT_TAG = "main"

INSTALL_DIR = Path.home() / ".cli-proxy"
DIRECTORIES_TO_CREATE = [
    "shell/bash",
    "shell/powershell",
    "core",
    "configs/antigravity",
    "configs/claude",
    "configs/openai",
    "configs/gemini",
]

ARCH_ALIASES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
}

SUPPORTED_PLATFORM_KEYS = {
    "linux-amd64",
    "linux-arm64",
    "windows-amd64",
}

CORE_FILES = {
    "config.yaml": "config.yaml",
    "shell/bash/cc-proxy.sh": "shell/bash/cc-proxy.sh",
    "shell/powershell/cc-proxy.ps1": "shell/powershell/cc-proxy.ps1",
    "core/cc_proxy.py": "core/cc_proxy.py",
    "core/constants.py": "core/constants.py",
    "core/paths.py": "core/paths.py",
    "core/process.py": "core/process.py",
    "core/config.py": "core/config.py",
    "core/api.py": "core/api.py",
    "core/quota.py": "core/quota.py",
    "core/usage.py": "core/usage.py",
    "core/proxy.py": "core/proxy.py",
    "core/display.py": "core/display.py",
    "core/tui.py": "core/tui.py",
    "core/commands.py": "core/commands.py",
    "core/updater.py": "core/updater.py",
    "core/binary_updater.py": "core/binary_updater.py",
}

BINARY_PATHS = {
    "linux-amd64": "CLIProxyAPI/linux/amd64/cli-proxy-api",
    "linux-arm64": "CLIProxyAPI/linux/arm64/cli-proxy-api",
    "windows-amd64": "CLIProxyAPI/windows/amd64/cli-proxy-api.exe",
}

CANONICAL_BINARY_NAME = {
    "linux": "cli-proxy-api",
    "windows": "cli-proxy-api.exe",
}

INSTALL_META_JSON = INSTALL_DIR / ".install-meta.json"
INSTALLED_TAG_FILE = INSTALL_DIR / ".installed-tag"


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON_VERSION:
        print(
            f"Error: Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher is required."
        )
        sys.exit(1)
    print(f"Python version check passed: {sys.version.split(' ')[0]}")


def create_directories() -> None:
    for directory in DIRECTORIES_TO_CREATE:
        (INSTALL_DIR / directory).mkdir(parents=True, exist_ok=True)
    print(f"Created directories under {INSTALL_DIR}")


def download_file(url: str, target_path: Path) -> None:
    print(f"Downloading {url} ...")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, target_path)
        print(f"  -> Saved to {target_path}")
    except Exception as exc:
        print(f"Error downloading {url}: {exc}")
        sys.exit(1)


def raw_tag_url(repo: str, tag: str, relative_path: str) -> str:
    # Append timestamp to bypass GitHub's raw CDN caching which can hold stale files for ~5 minutes.
    ts = int(datetime.now(timezone.utc).timestamp())
    return f"https://raw.githubusercontent.com/{repo}/{tag}/{relative_path}?v={ts}"


def is_local_source_tree(root: Path) -> bool:
    required = [
        root / "config.yaml",
        root / "core" / "cc_proxy.py",
        root / "shell" / "bash" / "cc-proxy.sh",
        root / "shell" / "powershell" / "cc-proxy.ps1",
    ]
    return all(path.exists() for path in required)


def resolve_source_mode(source: str, local_path: Optional[str]) -> Tuple[str, Optional[Path]]:
    if source == "remote":
        return "remote", None

    if local_path:
        candidate = Path(local_path).expanduser().resolve()
        if not is_local_source_tree(candidate):
            print(f"Error: --local-path does not look like a valid repo root: {candidate}")
            sys.exit(1)
        return "local", candidate

    inferred = Path(__file__).resolve().parent.parent

    if source == "local":
        if is_local_source_tree(inferred):
            return "local", inferred
        print("Error: local source mode requested but repo root could not be inferred.")
        print("Hint: rerun with --local-path <repo-root>.")
        sys.exit(1)

    if source == "auto":
        if is_local_source_tree(inferred):
            return "local", inferred
        return "remote", None

    return "remote", None


def normalize_system_and_arch() -> Tuple[str, str]:
    import platform

    system = platform.system().lower()
    machine = platform.machine().lower()

    if system not in {"linux", "windows"}:
        print(
            "Error: Unsupported OS. Supported combinations are linux-amd64, linux-arm64, windows-amd64."
        )
        sys.exit(1)

    normalized_arch = ARCH_ALIASES.get(machine)
    if not normalized_arch:
        print(
            f"Error: Unsupported architecture '{machine}'. Supported architectures: amd64, arm64."
        )
        sys.exit(1)

    platform_key = f"{system}-{normalized_arch}"
    if platform_key not in SUPPORTED_PLATFORM_KEYS:
        print(
            f"Error: Unsupported platform combination '{platform_key}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_PLATFORM_KEYS))}"
        )
        sys.exit(1)

    return system, platform_key


def copy_local_file(source_path: Path, target_path: Path) -> None:
    print(f"Copying {source_path} ...")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_path, target_path)
        print(f"  -> Saved to {target_path}")
    except Exception as exc:
        print(f"Error copying {source_path}: {exc}")
        sys.exit(1)


def install_core_files(
    source_mode: str,
    repo: str,
    tag: str,
    local_root: Optional[Path],
) -> None:
    for local_path, repo_path in CORE_FILES.items():
        target = INSTALL_DIR / local_path
        if source_mode == "local":
            assert local_root is not None
            source = local_root / repo_path
            if not source.exists():
                print(f"Error: missing local source file: {source}")
                sys.exit(1)
            copy_local_file(source, target)
        else:
            url = raw_tag_url(repo, tag, repo_path)
            download_file(url, target)


def install_binary(
    source_mode: str,
    repo: str,
    tag: str,
    local_root: Optional[Path],
    system: str,
    platform_key: str,
) -> None:
    relative_path = BINARY_PATHS.get(platform_key)
    if not relative_path:
        print(
            f"Error: No binary mapping for '{platform_key}'. "
            f"Supported: {', '.join(sorted(BINARY_PATHS.keys()))}"
        )
        sys.exit(1)

    canonical_name = CANONICAL_BINARY_NAME[system]
    target_path = INSTALL_DIR / canonical_name
    temp_target = INSTALL_DIR / f".{canonical_name}.tmp"

    if source_mode == "local":
        assert local_root is not None
        source_binary = local_root / relative_path
        if not source_binary.exists():
            print(f"Notice: local binary missing for platform {platform_key}.")
            print("Auto-fetching binaries using core/binary_updater.py ...")
            updater_script = local_root / "core" / "binary_updater.py"
            if updater_script.exists():
                import subprocess
                res = subprocess.run([sys.executable, str(updater_script)])
                if res.returncode != 0:
                    print("Error: auto-fetch failed.")
                    sys.exit(1)
            else:
                print(f"Error: missing local binary and updater script not found: {updater_script}")
                sys.exit(1)

            if not source_binary.exists():
                print(f"Error: binary still missing after auto-fetch: {source_binary}")
                sys.exit(1)

        copy_local_file(source_binary, temp_target)
    else:
        # --- Self-contained GitHub Releases binary downloader ---
        # Does NOT import binary_updater.py so it works even when install.py is cached.
        import json as _json
        import tarfile as _tarfile
        import tempfile as _tempfile
        import zipfile as _zipfile
        import urllib.error as _uerr

        BINARY_RELEASE_REPO = "router-for-me/CLIProxyAPI"

        def _get_latest_tag(release_repo, timeout=15):
            # Try GitHub REST API first
            api_url = f"https://api.github.com/repos/{release_repo}/releases/latest"
            req = urllib.request.Request(api_url, headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "cc-proxy-installer/1.0",
            })
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = _json.loads(r.read().decode())
                    tag = data.get("tag_name")
                    if tag:
                        return tag, None
            except _uerr.HTTPError as exc:
                if exc.code != 403:
                    return None, f"GitHub API error: {exc.code}"
            except Exception as exc:
                return None, str(exc)
            # Fallback: parse redirect from browser URL (no API quota)
            try:
                html_req = urllib.request.Request(
                    f"https://github.com/{release_repo}/releases/latest", method="HEAD"
                )
                with urllib.request.urlopen(html_req, timeout=timeout) as r:
                    final = r.url
                    if "releases/tag/" in final:
                        return final.split("/")[-1], None
            except Exception as exc:
                pass
            return None, "Could not resolve latest release tag"

        def _download_binary(release_repo, platform_k, target_tmp, timeout=120):
            tag, err = _get_latest_tag(release_repo)
            if err or not tag:
                return False, f"Failed to get latest release tag: {err}"

            version = tag.lstrip("v")
            os_name, arch = platform_k.split("-")
            ext = "zip" if os_name == "windows" else "tar.gz"
            bin_name = "cli-proxy-api.exe" if os_name == "windows" else "cli-proxy-api"
            filename = f"CLIProxyAPI_{version}_{os_name}_{arch}.{ext}"
            url = f"https://github.com/{release_repo}/releases/download/{tag}/{filename}"

            print(f"Downloading binary from {url} ...")
            try:
                with _tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tf:
                    tmp_arc = tf.name
                urllib.request.urlretrieve(url, tmp_arc)
            except Exception as exc:
                return False, f"Download failed: {exc}"

            try:
                target_tmp.parent.mkdir(parents=True, exist_ok=True)
                if ext == "tar.gz":
                    with _tarfile.open(tmp_arc, "r:gz") as arc:
                        member = next(
                            (m for m in arc.getmembers() if m.name.endswith(bin_name) and not m.isdir()),
                            None
                        )
                        if not member:
                            return False, f"Binary '{bin_name}' not found in archive"
                        member.name = target_tmp.name
                        arc.extract(member, path=str(target_tmp.parent))
                else:
                    with _zipfile.ZipFile(tmp_arc) as arc:
                        member = next(
                            (n for n in arc.namelist() if n.endswith(bin_name)),
                            None
                        )
                        if not member:
                            return False, f"Binary '{bin_name}' not found in archive"
                        data = arc.read(member)
                        target_tmp.write_bytes(data)
            except Exception as exc:
                return False, f"Extraction failed: {exc}"
            finally:
                try:
                    Path(tmp_arc).unlink()
                except Exception:
                    pass
            return True, None

        ok, dl_err = _download_binary(BINARY_RELEASE_REPO, platform_key, temp_target)
        if not ok:
            print(f"Error: {dl_err}")
            sys.exit(1)


    if system == "linux" and temp_target.exists():
        temp_target.chmod(temp_target.stat().st_mode | stat.S_IEXEC)

    try:
        temp_target.replace(target_path)
    except OSError as exc:
        print(f"Error replacing binary at {target_path}: {exc}")
        print("Hint: stop running proxies before reinstall (e.g., cc-proxy-stop).")
        if temp_target.exists():
            temp_target.unlink(missing_ok=True)
        sys.exit(1)

    if system == "linux":
        bash_script = INSTALL_DIR / "shell/bash/cc-proxy.sh"
        if bash_script.exists():
            bash_script.chmod(bash_script.stat().st_mode | stat.S_IEXEC)

    print(f"Installed canonical binary: {target_path}")


# Commands that get shim executables in ~/.local/bin so they work in
# non-interactive shells (watch, cron, systemd, etc.)
SHIM_COMMANDS = [
    ("cc-proxy-status", "status"),
    ("cc-proxy-start",  "start all"),
    ("cc-proxy-stop",   "stop"),
]


def install_shims(system: str) -> None:
    """Create thin executable shims in ~/.local/bin for non-interactive use.

    Each shim calls: python3 ~/.cli-proxy/core/cc_proxy.py <subcommand> "$@"
    This allows commands like `watch -n 1 cc-proxy-status` to work.
    """
    if system == "windows":
        return  # Windows uses PowerShell functions; shims not applicable here

    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    proxy_script = INSTALL_DIR / "core" / "cc_proxy.py"

    for shim_name, subcmd in SHIM_COMMANDS:
        shim_path = local_bin / shim_name
        shim_body = (
            "#!/bin/sh\n"
            f'exec python3 "{proxy_script}" {subcmd} "$@"\n'
        )
        shim_path.write_text(shim_body, encoding="utf-8")
        shim_path.chmod(shim_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  Installed shim: {shim_path}")

    print(f"Installed {len(SHIM_COMMANDS)} shim(s) in {local_bin}")


def setup_profile() -> None:
    import platform
    import subprocess

    system = platform.system().lower()

    if system == "windows":
        profile_line = f". \"{INSTALL_DIR}\\shell\\powershell\\cc-proxy.ps1\""
        try:
            # Resolves the current user's $PROFILE for the default PowerShell host
            # and appends the line if it doesn't already exist.
            ps_cmd = (
                "$p = $PROFILE;"
                "if (-Not (Test-Path -Path $p)) {"
                "    New-Item -Path $p -Type File -Force | Out-Null;"
                "}"
                "$c = Get-Content -Path $p -Raw -ErrorAction SilentlyContinue;"
                f"if (-not $c -or -not $c.Contains('{profile_line}')) {{"
                f"    Out-File -FilePath $p -Append -Encoding utf8 -InputObject '`n{profile_line}';"
                "    Write-Host \"Added profile line to $p\";"
                "} else {"
                "    Write-Host \"Profile line already exists in $p\";"
                "}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)
        except Exception as e:
            print(f"Warning: Failed to auto-configure PowerShell profile: {e}")
            print("\n--- Setup Profile ---")
            print("To complete setup, run the following in PowerShell:")
            print(f"  . {INSTALL_DIR}\\shell\\powershell\\cc-proxy.ps1")
            print("  Install-CCProxyProfile")

        print("\n--- Setup Profile ---")
        print("To apply changes immediately in the current Windows session, run:")
        print(f"  . {INSTALL_DIR}\\shell\\powershell\\cc-proxy.ps1")
        print("Or restart your PowerShell terminal.")
        return

    src_path = f"{INSTALL_DIR}/shell/bash/cc-proxy.sh"
    source_line = f'source "{src_path}"'

    for rc_file in [".bashrc", ".zshrc"]:
        rc_path = Path.home() / rc_file
        if not rc_path.exists():
            continue

        content = rc_path.read_text(encoding="utf-8")
        if src_path in content:
            print(f"Source line already exists in ~/{rc_file}")
            continue

        with open(rc_path, "a", encoding="utf-8") as file_handle:
            file_handle.write(f"\n# Added by cli-proxy installer\n{source_line}\n")

        print(f"Added source line to ~/{rc_file}")


def _resolve_commit_sha(
    source_mode: str,
    local_root: Optional[Path],
    repo: str,
    tag: str,
) -> str:
    """Best-effort commit SHA resolution for install metadata."""
    import subprocess as _sp
    if source_mode == "local" and local_root:
        try:
            result = _sp.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(local_root),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
    # Remote mode fallback: query GitHub API
    try:
        api_url = f"https://api.github.com/repos/{repo}/commits/{tag}"
        req = urllib.request.Request(api_url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "cc-proxy-installer/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha", "")
            if sha:
                return sha
    except Exception:
        pass
    return "unknown"


def write_install_metadata(
    repo: str,
    tag: str,
    platform_key: str,
    source_mode: str,
    local_root: Optional[Path],
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    commit_sha = _resolve_commit_sha(source_mode, local_root, repo, tag)

    meta: Dict[str, Any] = {
        "repo": repo,
        "tag": tag,
        "platform": platform_key,
        "installed_at_utc": now_iso,
        "install_dir": str(INSTALL_DIR),
        "source_mode": source_mode,
        "binary_source": "local-tree-copy" if source_mode == "local" else "repo-tag-raw",
        "commit_sha": commit_sha,
    }
    if local_root is not None:
        meta["local_source_root"] = str(local_root)

    INSTALL_META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    INSTALLED_TAG_FILE.write_text(f"{tag}\n", encoding="utf-8")
    print(f"Wrote install metadata: {INSTALL_META_JSON}")
    print(f"Committed SHA: {commit_sha}")
    print(f"Wrote installed tag file: {INSTALLED_TAG_FILE}")


def setup_autostart(system: str, uninstall: bool = False) -> None:
    import os
    if system == "linux":
        systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
        service_file = systemd_user_dir / "cli-proxy.service"
        
        import subprocess
        if uninstall:
            if service_file.exists():
                subprocess.run(["systemctl", "--user", "stop", "cli-proxy.service"], check=False, capture_output=True)
                subprocess.run(["systemctl", "--user", "disable", "cli-proxy.service"], check=False, capture_output=True)
                service_file.unlink()
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
                print(f"Removed Linux systemd autostart: {service_file}")
            return

        systemd_user_dir.mkdir(parents=True, exist_ok=True)
        python_exe = sys.executable
        cc_proxy_py = INSTALL_DIR / "core" / "cc_proxy.py"
        
        service_content = f"""[Unit]
Description=CLIProxy API Service
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={python_exe} {cc_proxy_py} start all
ExecStop={python_exe} {cc_proxy_py} stop

[Install]
WantedBy=default.target
"""
        service_file.write_text(service_content, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "cli-proxy.service"], check=False, capture_output=True)
        print(f"Enabled Linux systemd autostart: {service_file}")

    elif system == "windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            if not uninstall:
                print("Warning: APPDATA not found. Cannot configure Windows autostart.")
            return
        
        startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        vbs_path = startup_dir / "cli-proxy-autostart.vbs"
        
        if uninstall:
            if vbs_path.exists():
                vbs_path.unlink()
                print(f"Removed Windows autostart script: {vbs_path}")
            return

        startup_dir.mkdir(parents=True, exist_ok=True)
        python_exe = sys.executable
        cc_proxy_py = INSTALL_DIR / "core" / "cc_proxy.py"
        
        if python_exe.lower().endswith("python.exe"):
            pythonw_exe = python_exe[:-4] + "w.exe"
            if Path(pythonw_exe).exists():
                python_exe = pythonw_exe

        vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\n'
        vbs_content += f'WshShell.Run chr(34) & "{python_exe}" & chr(34) & " " & chr(34) & "{cc_proxy_py}" & chr(34) & " start all", 0, False\n'
        
        vbs_path.write_text(vbs_content, encoding="utf-8")
        print(f"Enabled Windows autostart: {vbs_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install cli-proxy runtime from repository tag or local source")
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help="Git tag or branch to install from (recommended: vX.Y.Z)",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="GitHub repository in owner/name form",
    )
    parser.add_argument(
        "--source",
        choices=["remote", "local", "auto"],
        default="auto",
        help="Install source: remote (GitHub tag), local (filesystem copy), or auto (prefer local when detectable)",
    )
    parser.add_argument(
        "--local-path",
        default="",
        help="Local repo root for --source local/auto. If omitted, infer from installers/install.py location.",
    )
    parser.add_argument(
        '--uninstall',
        action='store_true',
        help='Remove ~/.cli-proxy/, shims, and profile loader lines',
    )
    parser.add_argument(
        '--no-autostart',
        action='store_true',
        help='Disable OS boot autostart integration (systemd/Startup folder)',
    )
    return parser.parse_args()


def uninstall() -> None:
    import platform
    import subprocess

    system = platform.system().lower()

    # 1. Stop running proxies
    cc_proxy_py = INSTALL_DIR / "core" / "cc_proxy.py"
    if cc_proxy_py.exists():
        print("Stopping running proxies...")
        try:
            subprocess.run([sys.executable, str(cc_proxy_py), "stop"], check=False, capture_output=True)
        except Exception:
            pass

    # 2. Remove shims from ~/.local/bin (Linux)
    if system != "windows":
        local_bin = Path.home() / ".local" / "bin"
        for shim_name, _ in SHIM_COMMANDS:
            shim_path = local_bin / shim_name
            if shim_path.exists():
                shim_path.unlink()
                print(f"Removed shim: {shim_path}")

    # 3. Strip loader lines from shell profiles
    if system == "windows":
        profile_line = f'. "{INSTALL_DIR}\\shell\\powershell\\cc-proxy.ps1"'
        try:
            res = subprocess.run(
                ["powershell", "-Command", "echo $PROFILE"],
                capture_output=True, text=True
            )
            profile_path = Path(res.stdout.strip())
            if profile_path.exists():
                content = profile_path.read_text(encoding="utf-8", errors="replace")
                new_content = "\n".join(
                    line for line in content.splitlines()
                    if profile_line not in line
                ).strip() + "\n"
                if new_content != content:
                    profile_path.write_text(new_content, encoding="utf-8")
                    print(f"Removed loader line from {profile_path}")
        except Exception as e:
            print(f"Warning: could not clean PowerShell profile: {e}")
    else:
        src_path = f"{INSTALL_DIR}/shell/bash/cc-proxy.sh"
        for rc_name in (".bashrc", ".zshrc"):
            rc_path = Path.home() / rc_name
            if not rc_path.exists():
                continue
            content = rc_path.read_text(encoding="utf-8", errors="replace")
            new_lines = []
            skip_next_blank = False
            for line in content.splitlines():
                if src_path in line or "Added by cli-proxy installer" in line:
                    skip_next_blank = True
                    continue
                if skip_next_blank and line.strip() == "":
                    skip_next_blank = False
                    continue
                skip_next_blank = False
                new_lines.append(line)
            new_content = "\n".join(new_lines).strip() + "\n"
            if new_content != content:
                rc_path.write_text(new_content, encoding="utf-8")
                print(f"Removed loader line from ~/{rc_name}")

    # 3.5 Remove autostart hooks
    setup_autostart(system, uninstall=True)

    # 4. Remove ~/.cli-proxy/ directory
    if INSTALL_DIR.exists():
        tokens_dir = INSTALL_DIR / "tokens"
        keep_tokens = False
        
        if tokens_dir.exists() and any(tokens_dir.iterdir()):
            try:
                ans = input(f"\n[?] Found existing token files in {tokens_dir}.\nDo you want to delete them? (y/N) [Default: N]: ").strip().lower()
                if ans != 'y':
                    keep_tokens = True
            except (EOFError, KeyboardInterrupt):
                keep_tokens = True

        if keep_tokens:
            print(f"Preserving token files at {tokens_dir}...")
            for item in INSTALL_DIR.iterdir():
                if item.name == "tokens":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            print("Removed cli-proxy files, but kept your tokens safe.")
        else:
            print(f"Removing {INSTALL_DIR} ...")
            shutil.rmtree(INSTALL_DIR)
            print("Removed.")
    else:
        print(f"{INSTALL_DIR} not found — nothing to remove.")

    print("\nUninstall complete.")
    if system == "windows":
        print("Restart your PowerShell terminal to clean up lingering aliases.")



def stop_existing_proxies() -> None:
    import subprocess
    cc_proxy_py = INSTALL_DIR / "core" / "cc_proxy.py"
    if cc_proxy_py.exists():
        print("Stopping running proxies before update...")
        try:
            subprocess.run([sys.executable, str(cc_proxy_py), "stop"], check=False, capture_output=True)
        except Exception:
            pass

def start_proxies_after_install() -> None:
    import subprocess
    cc_proxy_py = INSTALL_DIR / "core" / "cc_proxy.py"
    if cc_proxy_py.exists():
        print("Starting proxies...")
        try:
            subprocess.run([sys.executable, str(cc_proxy_py), "start", "all"], check=False)
        except Exception:
            pass


def install_claude_code(system: str) -> None:
    """Install Claude Code CLI if not already present.

    Linux/macOS : official installer (curl ... | bash) — standalone Bun binary.
    Windows     : npm install (Node.js runtime) — avoids Bun ConPTY crash in
                  IDE-embedded terminals (VSCode, Antigravity, etc.).
    """
    import subprocess

    if shutil.which("claude"):
        print("Claude Code already installed -- skipping.")
        return

    if system == "linux":
        print("Claude Code not found. Installing via official installer...")
        try:
            result = subprocess.run(
                ["bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash"],
                check=False,
            )
            if result.returncode != 0:
                print("Warning: Claude Code installation may have failed.")
                print("Please install manually: https://claude.ai/download")
            else:
                print("Claude Code installation completed.")
        except Exception as exc:
            print(f"Warning: failed to run Claude Code installer: {exc}")
            print("Please install manually: https://claude.ai/download")
        return

    # Windows — npm install (Node.js runtime, no Bun crash)
    npm_bin = shutil.which("npm")
    if not npm_bin:
        print("Warning: npm not found. Cannot install Claude Code automatically.")
        print("Please install Node.js (https://nodejs.org/) then run:")
        print("  npm install -g @anthropic-ai/claude-code")
        return

    print("Claude Code not found. Installing via npm (Node.js runtime)...")
    try:
        result = subprocess.run(
            [npm_bin, "install", "-g", "@anthropic-ai/claude-code"],
            check=False,
        )
        if result.returncode != 0:
            print("Warning: Claude Code npm installation may have failed.")
            print("Please install manually: npm install -g @anthropic-ai/claude-code")
        else:
            print("Claude Code installation completed (npm).")
    except Exception as exc:
        print(f"Warning: failed to install Claude Code via npm: {exc}")
        print("Please install manually: npm install -g @anthropic-ai/claude-code")


def main() -> None:
    args = parse_args()

    if args.uninstall:
        uninstall()
        return

    print("Starting cli-proxy-api installation...")
    check_python_version()
    create_directories()

    system, platform_key = normalize_system_and_arch()

    source_mode, local_root = resolve_source_mode(args.source, args.local_path)

    if source_mode == "local":
        print(f"Using local source tree: {local_root}")
    else:
        print(f"Using repository ref: {args.tag}")

    print(f"Detected platform: {platform_key}")

    install_claude_code(system)

    stop_existing_proxies()

    install_core_files(source_mode, args.repo, args.tag, local_root)
    install_binary(source_mode, args.repo, args.tag, local_root, system, platform_key)
    install_shims(system)

    write_install_metadata(args.repo, args.tag, platform_key, source_mode, local_root)
    setup_profile()

    if not args.no_autostart:
        setup_autostart(system, uninstall=False)
    else:
        setup_autostart(system, uninstall=True)

    print("\nInstallation complete!")
    start_proxies_after_install()


if __name__ == "__main__":
    main()
