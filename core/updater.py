"""
Self-update logic for CLIProxyAPI + Claude Code helper.
Python 3.8+, stdlib only.

Compares installed commit SHA with the latest remote main branch commit
via the GitHub API, then optionally pulls changes and re-runs the installer.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

from constants import INSTALL_META_JSON_NAME


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def _read_install_meta(base_dir):
    """Read .install-meta.json and return parsed dict (or empty dict)."""
    meta_path = base_dir / INSTALL_META_JSON_NAME
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_installed_commit(base_dir):
    """Return the commit SHA recorded at install time, or None."""
    meta = _read_install_meta(base_dir)
    return meta.get("commit_sha") or None


def get_installed_repo(base_dir):
    """Return the repo slug (owner/name) from install metadata."""
    meta = _read_install_meta(base_dir)
    return meta.get("repo") or "levin1006/claude-code-cli-proxy"


def get_local_source_root(base_dir):
    """Return the local source root Path if recorded, else None."""
    meta = _read_install_meta(base_dir)
    raw = meta.get("local_source_root")
    if raw:
        p = Path(raw)
        if p.is_dir():
            return p
    return None


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def get_remote_commit(repo, branch="main", timeout=15):
    """Fetch the latest commit SHA for *branch* via the GitHub API.

    Returns (sha_string, None) on success or (None, error_string) on failure.
    """
    url = "https://api.github.com/repos/{}/commits/{}".format(repo, branch)
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "cc-proxy-updater/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")
            if sha:
                return sha, None
            return None, "GitHub API response missing 'sha' field"
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            return None, "GitHub API rate limit exceeded (HTTP 403). Try again later."
        return None, "GitHub API HTTP error: {} {}".format(exc.code, exc.reason)
    except urllib.error.URLError as exc:
        return None, "Network error: {}".format(exc.reason)
    except Exception as exc:
        return None, "Failed to query GitHub API: {}".format(exc)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_available():
    return shutil.which("git") is not None


def _git_rev_parse(repo_dir):
    """Return current HEAD commit SHA of a local git repo, or None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _git_is_dirty(repo_dir):
    """Return True if the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_dir),
            capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _git_fetch(repo_dir, remote="origin", branch="main"):
    """Run git fetch. Returns (success, stderr)."""
    try:
        result = subprocess.run(
            ["git", "fetch", remote, branch],
            cwd=str(repo_dir),
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0, result.stderr.strip()
    except Exception as exc:
        return False, str(exc)


def _git_pull_ff_only(repo_dir, remote="origin", branch="main"):
    """Run git pull --ff-only. Returns (success, stderr)."""
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only", remote, branch],
            cwd=str(repo_dir),
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0, (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Installer invocation
# ---------------------------------------------------------------------------

def _run_installer(source_mode, local_root=None):
    """Run installers/install.py as a subprocess.

    For 'local' mode the installer is at <local_root>/installers/install.py.
    For 'remote' mode we use the installed copy at <base_dir>/installers/install.py
    or fall back to the install.py that ships with the installed runtime.
    """
    if source_mode == "local" and local_root:
        installer = local_root / "installers" / "install.py"
    else:
        # Remote fallback: use the installed installer in ~/.cli-proxy
        installer = Path.home() / ".cli-proxy" / "installers" / "install.py"
        if not installer.exists():
            # Try downloading a fresh installer (very unlikely path)
            print("[cc-proxy] ERROR: installer not found at {}".format(installer), file=sys.stderr)
            return False

    if not installer.exists():
        print("[cc-proxy] ERROR: installer not found: {}".format(installer), file=sys.stderr)
        return False

    cmd = [sys.executable, str(installer), "--source", source_mode]
    if source_mode == "local" and local_root:
        cmd.extend(["--local-path", str(local_root)])

    print("[cc-proxy] Running installer: {}".format(" ".join(cmd)))
    try:
        result = subprocess.run(cmd, timeout=300)
        return result.returncode == 0
    except Exception as exc:
        print("[cc-proxy] Installer failed: {}".format(exc), file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Public command entry point
# ---------------------------------------------------------------------------

def cmd_update(base_dir, force=False):
    """Check for updates and apply if available.

    Returns exit code (0 = success/up-to-date, 1 = error).
    """
    repo = get_installed_repo(base_dir)
    installed_sha = get_installed_commit(base_dir)
    local_root = get_local_source_root(base_dir)

    # 1. Fetch remote commit
    print("[cc-proxy] Checking for updates from {}...".format(repo))
    remote_sha, err = get_remote_commit(repo)
    if err:
        print("[cc-proxy] ERROR: {}".format(err), file=sys.stderr)
        return 1

    short_remote = remote_sha[:10]
    short_installed = installed_sha[:10] if installed_sha else "(unknown)"

    # 2. Compare
    if installed_sha and installed_sha == remote_sha:
        print("[cc-proxy] Already up to date. (commit: {})".format(short_remote))
        return 0

    print("[cc-proxy] Update available: {} -> {}".format(short_installed, short_remote))

    # 3. Determine update path
    if local_root and local_root.is_dir():
        # Local repo mode
        if not _git_available():
            print("[cc-proxy] ERROR: git is not installed. Cannot pull updates.", file=sys.stderr)
            print("[cc-proxy] Install git or run: python installers/install.py --source remote", file=sys.stderr)
            return 1

        # Check dirty state
        if _git_is_dirty(local_root):
            if not force:
                print("[cc-proxy] WARNING: Local repo has uncommitted changes: {}".format(local_root))
                print("[cc-proxy] Use 'cc-proxy-update --force' to update anyway, or commit/stash first.")
                return 1
            print("[cc-proxy] WARNING: Proceeding despite dirty working tree (--force)")

        # Fetch & pull
        print("[cc-proxy] Fetching from origin...")
        ok, msg = _git_fetch(str(local_root))
        if not ok:
            print("[cc-proxy] git fetch failed: {}".format(msg), file=sys.stderr)
            return 1

        print("[cc-proxy] Pulling changes (fast-forward only)...")
        ok, msg = _git_pull_ff_only(str(local_root))
        if not ok:
            print("[cc-proxy] git pull --ff-only failed: {}".format(msg), file=sys.stderr)
            print("[cc-proxy] Hint: resolve diverged history manually, then re-run cc-proxy-update.")
            return 1
        if msg:
            print("[cc-proxy] {}".format(msg))

        # Run local install
        print("[cc-proxy] Installing from local source...")
        if not _run_installer("local", local_root):
            print("[cc-proxy] ERROR: Installation failed.", file=sys.stderr)
            return 1

    else:
        # Remote install mode (no local repo)
        print("[cc-proxy] No local repository found. Installing from remote...")
        if not _run_installer("remote"):
            print("[cc-proxy] ERROR: Remote installation failed.", file=sys.stderr)
            return 1

    print("[cc-proxy] Update complete! (commit: {})".format(short_remote))
    return 0
