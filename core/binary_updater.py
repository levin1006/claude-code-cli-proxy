"""
CLIProxyAPI binary updater — repository tool only.
Python 3.8+, stdlib only.

Downloads the latest CLIProxyAPI binary for ALL managed platforms from
GitHub Releases and places them under CLIProxyAPI/{os}/{arch}/ in the
repository. This script is NOT installed to ~/.cli-proxy; it is executed
directly from the repository root.

Managed platforms:
  linux  / amd64  ->  CLIProxyAPI/linux/amd64/cli-proxy-api
  linux  / arm64  ->  CLIProxyAPI/linux/arm64/cli-proxy-api
  windows/ amd64  ->  CLIProxyAPI/windows/amd64/cli-proxy-api.exe

Usage (from repo root):
  python3 core/binary_updater.py [--force]
"""

import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

BINARY_REPO = "router-for-me/CLIProxyAPI"

# All managed platform combinations: (os_name, arch, archive_ext, binary_name)
PLATFORMS = [
    ("linux",   "amd64", "tar.gz", "cli-proxy-api"),
    ("linux",   "arm64", "tar.gz", "cli-proxy-api"),
    ("windows", "amd64", "zip",    "cli-proxy-api.exe"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tag_to_version(tag):
    """'v6.8.54' -> '6.8.54'"""
    return tag.lstrip("v")


def get_latest_release(repo=None, timeout=15):
    """Return (tag_name, None) or (None, error_string) from GitHub Releases API."""
    repo = repo or BINARY_REPO
    url = "https://api.github.com/repos/{}/releases/latest".format(repo)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "cc-proxy-binary-updater/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name")
            if tag:
                return tag, None
            return None, "GitHub API response missing 'tag_name'"
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return None, "GitHub API rate limit exceeded (HTTP 403)"
        return None, "GitHub API HTTP error: {} {}".format(exc.code, exc.reason)
    except urllib.error.URLError as exc:
        return None, "Network error: {}".format(exc.reason)
    except Exception as exc:
        return None, "Failed to query GitHub API: {}".format(exc)


def build_download_url(tag, os_name, arch, ext):
    """Build GitHub release download URL for a given platform."""
    version = _tag_to_version(tag)
    filename = "CLIProxyAPI_{}_{}_{}.{}".format(version, os_name, arch, ext)
    return "https://github.com/{}/releases/download/{}/{}".format(
        BINARY_REPO, tag, filename
    )


def get_current_binary_version(repo_root, os_name="linux", arch="amd64"):
    """Run the linux/amd64 binary -h and parse the version string.

    Returns (version_string, None) or (None, error_string).
    Falls back to None if the platform binary cannot be executed (e.g. on Windows host).
    """
    bin_path = repo_root / "CLIProxyAPI" / os_name / arch / "cli-proxy-api"
    if not bin_path.exists():
        return None, "Binary not found: {}".format(bin_path)
    try:
        res = subprocess.run(
            [str(bin_path), "-h"],
            capture_output=True, text=True, timeout=5,
        )
        out = res.stdout + res.stderr
        for line in out.splitlines():
            m = re.search(r"CLIProxyAPI Version:\s*(\S+)", line)
            if m:
                return m.group(1).rstrip(","), None
        return None, "Could not parse version from binary output"
    except Exception as exc:
        return None, "Failed to run binary: {}".format(exc)


def _find_binary_in_dir(directory, binary_name):
    """Search recursively for *binary_name* inside *directory*."""
    for root, _dirs, files in os.walk(str(directory)):
        if binary_name in files:
            return Path(root) / binary_name
    return None


def download_and_place(url, target_path, os_name, binary_name):
    """Download archive, extract *binary_name*, and place at *target_path* atomically.

    Returns (True, None) on success or (False, error_string).
    """
    target_path = Path(target_path)
    archive_name = url.rsplit("/", 1)[-1]

    with tempfile.TemporaryDirectory(prefix="ccproxy_bin_") as tmpdir:
        tmpdir = Path(tmpdir)
        archive_path = tmpdir / archive_name

        # Download
        try:
            urllib.request.urlretrieve(url, str(archive_path))
        except Exception as exc:
            return False, "Download failed: {}".format(exc)

        # Extract
        extract_dir = tmpdir / "extracted"
        extract_dir.mkdir()
        try:
            if archive_name.endswith(".tar.gz") or archive_name.endswith(".tgz"):
                with tarfile.open(str(archive_path), "r:gz") as tf:
                    tf.extractall(str(extract_dir))
            elif archive_name.endswith(".zip"):
                with zipfile.ZipFile(str(archive_path), "r") as zf:
                    zf.extractall(str(extract_dir))
            else:
                return False, "Unknown archive format: {}".format(archive_name)
        except Exception as exc:
            return False, "Extraction failed: {}".format(exc)

        # Find binary inside extracted content
        binary = _find_binary_in_dir(extract_dir, binary_name)
        if not binary:
            return False, "{} not found inside archive".format(binary_name)

        # Set executable bit (Linux binaries)
        if os_name != "windows":
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        # Atomic replace
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target_path.with_suffix(".tmp")
        try:
            import shutil
            shutil.copy2(str(binary), str(tmp_target))
            if os_name != "windows":
                tmp_target.chmod(tmp_target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            tmp_target.replace(target_path)
        except OSError as exc:
            tmp_target.unlink(missing_ok=True)
            return False, "Failed to place binary: {}".format(exc)

    return True, None


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------

def cmd_update_all(repo_root, force=False):
    """Download all platform binaries from the latest GitHub release.

    Returns exit code (0 = success, 1 = error).
    """
    repo_root = Path(repo_root)

    # 1. Get current version (using linux/amd64 as reference)
    cur_ver, ver_err = get_current_binary_version(repo_root)
    if ver_err:
        print("[binary-updater] WARNING: {}".format(ver_err))
        cur_ver = None
    print("[binary-updater] Current version: {}".format(cur_ver or "(unknown)"))

    # 2. Get latest release from GitHub
    print("[binary-updater] Checking latest release from {}...".format(BINARY_REPO))
    tag, err = get_latest_release()
    if err:
        print("[binary-updater] ERROR: {}".format(err), file=sys.stderr)
        return 1

    latest_ver = _tag_to_version(tag)
    print("[binary-updater] Latest release: {} ({})".format(tag, latest_ver))

    # 3. Compare versions
    if cur_ver and cur_ver == latest_ver and not force:
        print("[binary-updater] Already up to date.")
        return 0
    if cur_ver and cur_ver == latest_ver and force:
        print("[binary-updater] Forcing reinstall of same version.")

    # 4. Download all platforms
    errors = []
    for os_name, arch, ext, binary_name in PLATFORMS:
        url = build_download_url(tag, os_name, arch, ext)
        target = repo_root / "CLIProxyAPI" / os_name / arch / binary_name
        print("[binary-updater] Downloading {} ({}/{})...".format(tag, os_name, arch))
        ok, dl_err = download_and_place(url, target, os_name, binary_name)
        if ok:
            print("[binary-updater]   -> {}".format(target))
        else:
            print("[binary-updater]   ERROR: {}".format(dl_err), file=sys.stderr)
            errors.append("{}/{}: {}".format(os_name, arch, dl_err))

    if errors:
        print("[binary-updater] {} platform(s) failed:".format(len(errors)), file=sys.stderr)
        for e in errors:
            print("  - {}".format(e), file=sys.stderr)
        return 1

    print("[binary-updater] All platforms updated: {} -> {}".format(
        cur_ver or "(unknown)", latest_ver
    ))
    return 0


# ---------------------------------------------------------------------------
# Entry point (direct execution from repo root)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Update CLIProxyAPI binaries for all platforms (repo tool)."
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Reinstall even if already at the latest version.",
    )
    args = parser.parse_args()

    # Resolve repo root from this file's location: core/binary_updater.py -> repo root
    _repo_root = Path(__file__).resolve().parent.parent
    sys.exit(cmd_update_all(_repo_root, force=args.force))
