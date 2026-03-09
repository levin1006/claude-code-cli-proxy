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
    "configs/codex",
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
    return f"https://raw.githubusercontent.com/{repo}/{tag}/{relative_path}"


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
            print(f"Error: missing local binary for platform {platform_key}: {source_binary}")
            sys.exit(1)
        copy_local_file(source_binary, temp_target)
    else:
        binary_url = raw_tag_url(repo, tag, relative_path)
        download_file(binary_url, temp_target)

    if system == "linux":
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
    ("cc-proxy-links",  "links"),
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

    source_line = f"source {INSTALL_DIR}/shell/bash/cc-proxy.sh"

    for rc_file in [".bashrc", ".zshrc"]:
        rc_path = Path.home() / rc_file
        if not rc_path.exists():
            continue

        content = rc_path.read_text(encoding="utf-8")
        if source_line in content:
            print(f"Source line already exists in ~/{rc_file}")
            continue

        with open(rc_path, "a", encoding="utf-8") as file_handle:
            file_handle.write(f"\n# Added by cli-proxy installer\n{source_line}\n")

        print(f"Added source line to ~/{rc_file}")

    print("\n--- Setup Profile ---")
    print("To apply changes immediately, run:")
    print(f"  source {INSTALL_DIR}/shell/bash/cc-proxy.sh")
    print("Or restart your terminal.")


def write_install_metadata(
    repo: str,
    tag: str,
    platform_key: str,
    source_mode: str,
    local_root: Optional[Path],
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    meta: Dict[str, Any] = {
        "repo": repo,
        "tag": tag,
        "platform": platform_key,
        "installed_at_utc": now_iso,
        "install_dir": str(INSTALL_DIR),
        "source_mode": source_mode,
        "binary_source": "local-tree-copy" if source_mode == "local" else "repo-tag-raw",
    }
    if local_root is not None:
        meta["local_source_root"] = str(local_root)

    INSTALL_META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    INSTALLED_TAG_FILE.write_text(f"{tag}\n", encoding="utf-8")
    print(f"Wrote install metadata: {INSTALL_META_JSON}")
    print(f"Wrote installed tag file: {INSTALLED_TAG_FILE}")


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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

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

    install_core_files(source_mode, args.repo, args.tag, local_root)
    install_binary(source_mode, args.repo, args.tag, local_root, system, platform_key)
    install_shims(system)

    write_install_metadata(args.repo, args.tag, platform_key, source_mode, local_root)
    setup_profile()
    print("\nInstallation complete!")


if __name__ == "__main__":
    main()
