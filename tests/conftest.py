"""
Shared test fixtures for CLIProxyAPI wrapper tests.
Works with both unittest and pytest (auto-detected).
"""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Ensure core/ is importable ──
REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# ── pytest fixtures (graceful skip when running under pure unittest) ──
try:
    import pytest

    @pytest.fixture
    def tmp_base_dir(tmp_path):
        """Create a temporary base directory that mirrors the repo layout."""
        dirs = [
            tmp_path / "core",
            tmp_path / "configs" / "tokens",
            tmp_path / "configs" / "antigravity",
            tmp_path / "configs" / "claude",
            tmp_path / "configs" / "openai",
            tmp_path / "configs" / "gemini",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
        return tmp_path

    @pytest.fixture
    def sample_config_yaml(tmp_base_dir):
        """Write a minimal config.yaml to the tmp base dir."""
        config = tmp_base_dir / "config.yaml"
        config.write_text(
            'host: "127.0.0.1"\n'
            'port: 8317\n'
            'auth-dir: "./"\n'
            'remote-management:\n'
            '  secret-key: "cc"\n',
            encoding="utf-8",
        )
        return config

    @pytest.fixture
    def fake_token_file(tmp_base_dir):
        """Factory to create a fake token JSON in the shared token dir."""
        def _create(provider, email, expired=None, disabled=False):
            prefix = "ag" if provider == "antigravity" else provider
            if provider == "openai":
                prefix = "codex"
            filename = "{}-{}.json".format(prefix, email.replace("@", "_at_"))
            token_dir = tmp_base_dir / "configs" / "tokens"
            fpath = token_dir / filename
            data = {"email": email}
            if disabled:
                data["disabled"] = True
            if expired is not None:
                data["expired"] = expired
            fpath.write_text(json.dumps(data), encoding="utf-8")
            return fpath
        return _create

except ImportError:
    pass


# ── Helpers for unittest-based tests ──
def make_tmp_base_dir():
    """Create a temp base dir for unittest.TestCase tests."""
    tmp = Path(tempfile.mkdtemp(prefix="ccproxy_test_"))
    for sub in [
        "core", "configs/tokens",
        "configs/antigravity", "configs/claude",
        "configs/openai", "configs/gemini",
    ]:
        (tmp / sub).mkdir(parents=True, exist_ok=True)
    return tmp


def write_sample_config(base_dir):
    """Write minimal config.yaml in *base_dir*."""
    cfg = base_dir / "config.yaml"
    cfg.write_text(
        'host: "127.0.0.1"\n'
        'port: 8317\n'
        'auth-dir: "./"\n'
        'remote-management:\n'
        '  secret-key: "cc"\n',
        encoding="utf-8",
    )
    return cfg


def make_token_file(base_dir, provider, email, expired=None, disabled=False):
    """Create a fake token JSON and return its path."""
    prefix_map = {"antigravity": "ag", "openai": "codex"}
    prefix = prefix_map.get(provider, provider)
    filename = "{}-{}.json".format(prefix, email.replace("@", "_at_"))
    token_dir = base_dir / "configs" / "tokens"
    fpath = token_dir / filename
    data = {"email": email}
    if disabled:
        data["disabled"] = True
    if expired is not None:
        data["expired"] = expired
    fpath.write_text(json.dumps(data), encoding="utf-8")
    return fpath
