"""
Tests for core/paths.py — path resolution and token file discovery.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from paths import (
    get_base_dir,
    get_binary_path,
    get_config_file,
    get_pid_file,
    get_provider_dir,
    get_token_dir,
    get_token_files,
    resolve_account_file_path,
    _resolve_token_root,
    _token_prefixes_for_provider,
)


class TestTokenPrefixes(unittest.TestCase):
    def test_antigravity_prefixes(self):
        self.assertIn("antigravity", _token_prefixes_for_provider("antigravity"))
        self.assertIn("ag", _token_prefixes_for_provider("antigravity"))

    def test_openai_prefixes(self):
        self.assertIn("openai", _token_prefixes_for_provider("openai"))
        self.assertIn("codex", _token_prefixes_for_provider("openai"))

    def test_simple_provider(self):
        self.assertEqual(_token_prefixes_for_provider("claude"), ["claude"])
        self.assertEqual(_token_prefixes_for_provider("gemini"), ["gemini"])


class TestGetBaseDir(unittest.TestCase):
    def test_returns_repo_root(self):
        base = get_base_dir()
        self.assertTrue(base.is_dir())
        self.assertTrue((base / "core").is_dir())


class TestGetBinaryPath(unittest.TestCase):
    def test_canonical_path_exists(self):
        """get_binary_path should return a Path (even if binary doesn't exist yet)."""
        base = get_base_dir()
        result = get_binary_path(base)
        self.assertIsInstance(result, Path)

    def test_repo_binary_fallback(self):
        """When canonical not present, should try repo CLIProxyAPI/ path."""
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_bin_"))
        try:
            # No canonical binary and no repo binary → returns canonical path
            result = get_binary_path(tmp)
            self.assertIsInstance(result, Path)
        finally:
            shutil.rmtree(tmp)


class TestGetTokenDir(unittest.TestCase):
    def test_default_token_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_td_"))
        try:
            result = _resolve_token_root(tmp)
            self.assertEqual(result, (tmp / "tokens").resolve())
        finally:
            shutil.rmtree(tmp)

    def test_env_var_override(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_td_"))
        env_dir = Path(tempfile.mkdtemp(prefix="ccproxy_env_"))
        try:
            os.environ["CC_PROXY_TOKEN_DIR"] = str(env_dir)
            result = _resolve_token_root(tmp)
            self.assertEqual(result, env_dir.resolve())
        finally:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            shutil.rmtree(tmp)
            shutil.rmtree(env_dir)

    def test_meta_file_override(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_td_"))
        custom_dir = Path(tempfile.mkdtemp(prefix="ccproxy_custom_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            (tmp / ".token-dir").write_text(str(custom_dir), encoding="utf-8")
            result = _resolve_token_root(tmp)
            self.assertEqual(result, custom_dir.resolve())
        finally:
            shutil.rmtree(tmp)
            shutil.rmtree(custom_dir)

    def test_create_flag(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_td_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            td = get_token_dir(tmp, create=True)
            self.assertTrue(td.is_dir())
        finally:
            shutil.rmtree(tmp)


class TestGetTokenFiles(unittest.TestCase):
    def test_finds_matching_tokens(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_tf_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            token_dir = tmp / "tokens"
            token_dir.mkdir(parents=True, exist_ok=True)
            (token_dir / "claude-alice.json").write_text('{"email":"alice"}')
            (token_dir / "claude-bob.json").write_text('{"email":"bob"}')
            (token_dir / "gemini-carol.json").write_text('{"email":"carol"}')
            (token_dir / "unrelated.txt").write_text("noise")

            result = get_token_files(tmp, "claude")
            self.assertEqual(len(result), 2)
            names = {p.name for p in result}
            self.assertIn("claude-alice.json", names)
            self.assertIn("claude-bob.json", names)
        finally:
            shutil.rmtree(tmp)

    def test_antigravity_matches_ag_prefix(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_tf_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            token_dir = tmp / "tokens"
            token_dir.mkdir(parents=True, exist_ok=True)
            (token_dir / "ag-dave.json").write_text('{"email":"dave"}')
            (token_dir / "antigravity-eve.json").write_text('{"email":"eve"}')

            result = get_token_files(tmp, "antigravity")
            self.assertEqual(len(result), 2)
        finally:
            shutil.rmtree(tmp)

    def test_empty_when_no_matches(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_tf_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            (tmp / "tokens").mkdir(parents=True, exist_ok=True)
            result = get_token_files(tmp, "claude")
            self.assertEqual(result, [])
        finally:
            shutil.rmtree(tmp)


class TestResolveAccountFilePath(unittest.TestCase):
    def test_rejects_path_outside_token_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_rap_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            (tmp / "tokens").mkdir(parents=True, exist_ok=True)
            result, err = resolve_account_file_path(tmp, "claude", "/etc/passwd")
            self.assertIsNone(result)
            self.assertIn("outside", err)
        finally:
            shutil.rmtree(tmp)

    def test_accepts_relative_path_inside_token_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_rap_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            token_dir = tmp / "tokens"
            token_dir.mkdir(parents=True, exist_ok=True)
            (token_dir / "claude-test.json").write_text("{}")
            result, err = resolve_account_file_path(tmp, "claude", "claude-test.json")
            self.assertIsNone(err)
            self.assertIsNotNone(result)
        finally:
            shutil.rmtree(tmp)


class TestProviderPaths(unittest.TestCase):
    def test_get_provider_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_pp_"))
        try:
            self.assertEqual(get_provider_dir(tmp, "claude"), tmp / "configs" / "claude")
        finally:
            shutil.rmtree(tmp)

    def test_get_pid_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_pp_"))
        try:
            pf = get_pid_file(tmp, "claude")
            self.assertEqual(pf.name, ".proxy.pid")
        finally:
            shutil.rmtree(tmp)

    def test_get_config_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_pp_"))
        try:
            cf = get_config_file(tmp, "claude")
            self.assertEqual(cf.name, "config.yaml")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
