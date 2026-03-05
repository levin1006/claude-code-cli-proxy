"""
Path resolution utilities for CLIProxyAPI + Claude Code helper.
Depends only on constants.
"""

import os
import platform
from pathlib import Path

from constants import IS_WINDOWS, TOKEN_DIR_ENV, TOKEN_DIR_META_FILE


def get_base_dir():
    return Path(__file__).resolve().parent.parent


def get_host_arch():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return "amd64"


def get_repo_binary_path(base_dir):
    if IS_WINDOWS:
        return base_dir / "CLIProxyAPI" / "windows" / "amd64" / "cli-proxy-api.exe"
    return base_dir / "CLIProxyAPI" / "linux" / get_host_arch() / "cli-proxy-api"


def get_binary_path(base_dir):
    name = "cli-proxy-api.exe" if IS_WINDOWS else "cli-proxy-api"
    canonical_path = base_dir / name
    if canonical_path.exists():
        return canonical_path

    repo_binary_path = get_repo_binary_path(base_dir)
    if repo_binary_path.exists():
        return repo_binary_path

    return canonical_path


def get_provider_dir(base_dir, provider):
    return base_dir / "configs" / provider


def _token_prefixes_for_provider(provider):
    if provider == "antigravity":
        return ["antigravity", "ag"]
    return [provider]


def _token_file_sort_key(path_obj):
    try:
        st = path_obj.stat()
        return (st.st_mtime, path_obj.name)
    except Exception:
        return (0, path_obj.name)


def _resolve_token_root(base_dir):
    """Resolve shared token directory.

    Priority:
    1) CC_PROXY_TOKEN_DIR env var
    2) <base_dir>/.token-dir file contents
    3) default <base_dir>/configs/tokens
    """
    env_dir = (os.environ.get(TOKEN_DIR_ENV) or "").strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    meta_path = base_dir / TOKEN_DIR_META_FILE
    if meta_path.exists():
        try:
            txt = meta_path.read_text(encoding="utf-8").strip()
            if txt:
                return Path(txt).expanduser().resolve()
        except Exception:
            pass

    return (base_dir / "configs" / "tokens").resolve()


def get_token_dir(base_dir, create=False):
    token_dir = _resolve_token_root(base_dir)
    if create:
        token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir


def _save_token_dir_metadata(base_dir, token_dir):
    meta_path = base_dir / TOKEN_DIR_META_FILE
    payload = str(Path(token_dir).expanduser().resolve()) + "\n"
    tmp = str(meta_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, str(meta_path))


def get_token_files(base_dir, provider):
    """Return token file paths for a provider from the shared token directory."""
    token_dir = get_token_dir(base_dir, create=False)
    prefixes = _token_prefixes_for_provider(provider)
    token_files = []
    for pfx in prefixes:
        for p in token_dir.glob("{}-*.json".format(pfx)):
            if p.is_file():
                token_files.append(p)
    token_files.sort(key=_token_file_sort_key, reverse=True)
    return token_files


def _is_path_under(path_obj, root_obj):
    try:
        path_obj.resolve().relative_to(root_obj.resolve())
        return True
    except Exception:
        return False


def resolve_account_file_path(base_dir, provider, rel_or_abs_path):
    """Resolve account file path safely against the shared token directory."""
    rel_path = (rel_or_abs_path or "").strip()
    if not rel_path:
        return None, "no file path"

    token_dir = get_token_dir(base_dir, create=False).resolve()

    cand = Path(rel_path).expanduser()
    if cand.is_absolute():
        target = cand.resolve()
    else:
        target = (token_dir / cand).resolve()

    if _is_path_under(target, token_dir):
        return target, None
    return None, "path outside allowed token dir"


def get_pid_file(base_dir, provider):
    return get_provider_dir(base_dir, provider) / ".proxy.pid"


def get_config_file(base_dir, provider):
    return get_provider_dir(base_dir, provider) / "config.yaml"
