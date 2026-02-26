import argparse
import json
import stat
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

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


def download_core_files(repo: str, tag: str) -> None:
    for local_path, repo_path in CORE_FILES.items():
        url = raw_tag_url(repo, tag, repo_path)
        target = INSTALL_DIR / local_path
        download_file(url, target)


def download_binary(repo: str, tag: str, system: str, platform_key: str) -> None:
    relative_path = BINARY_PATHS.get(platform_key)
    if not relative_path:
        print(
            f"Error: No binary mapping for '{platform_key}'. "
            f"Supported: {', '.join(sorted(BINARY_PATHS.keys()))}"
        )
        sys.exit(1)

    binary_url = raw_tag_url(repo, tag, relative_path)
    canonical_name = CANONICAL_BINARY_NAME[system]
    target_path = INSTALL_DIR / canonical_name
    temp_target = INSTALL_DIR / f".{canonical_name}.tmp"

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


def setup_profile() -> None:
    import platform

    system = platform.system().lower()

    if system == "windows":
        print("\n--- Setup Profile ---")
        print("To complete setup, run the following in PowerShell:")
        print(f"  . {INSTALL_DIR}\\shell\\powershell\\cc-proxy.ps1")
        print("  Install-CCProxyProfile")
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


def write_install_metadata(repo: str, tag: str, platform_key: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    meta: Dict[str, Any] = {
        "repo": repo,
        "tag": tag,
        "platform": platform_key,
        "installed_at_utc": now_iso,
        "install_dir": str(INSTALL_DIR),
        "binary_source": "repo-tag-raw",
    }

    INSTALL_META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    INSTALLED_TAG_FILE.write_text(f"{tag}\n", encoding="utf-8")
    print(f"Wrote install metadata: {INSTALL_META_JSON}")
    print(f"Wrote installed tag file: {INSTALLED_TAG_FILE}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install cli-proxy runtime from repository tag")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("Starting cli-proxy-api installation...")
    check_python_version()
    create_directories()

    system, platform_key = normalize_system_and_arch()
    print(f"Using repository ref: {args.tag}")
    print(f"Detected platform: {platform_key}")

    download_core_files(args.repo, args.tag)
    download_binary(args.repo, args.tag, system, platform_key)

    write_install_metadata(args.repo, args.tag, platform_key)
    setup_profile()
    print("\n✅ Installation complete!")


if __name__ == "__main__":
    main()
