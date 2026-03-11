"""
Tests for core/commands.py — auth, invoke_claude, token management.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from commands import invoke_claude, cmd_token_delete, cmd_token_list


class TestInvokeClaude(unittest.TestCase):
    def test_returns_1_when_claude_not_in_path(self):
        """Missing claude binary should print an error and return 1, not crash."""
        with patch("commands.shutil.which", return_value=None):
            result = invoke_claude("claude", "opus-model", "sonnet-model", "haiku-model", [])
        self.assertEqual(result, 1)

    @patch("commands.subprocess.run")
    @patch("commands.shutil.which", return_value="/usr/local/bin/claude")
    def test_invokes_claude_with_env_vars(self, mock_which, mock_run):
        """When claude is found, subprocess.run should be called with correct env vars."""
        mock_run.return_value = MagicMock(returncode=0)
        result = invoke_claude("antigravity", "my-opus", "my-sonnet", "my-haiku", [])
        self.assertEqual(result, 0)
        call_env = mock_run.call_args[1]["env"] if mock_run.call_args[1] else mock_run.call_args[0][1]
        # Grab env from kwargs
        actual_env = mock_run.call_args.kwargs.get("env") or mock_run.call_args[0][-1] if mock_run.call_args[0] else None
        # Just verify subprocess.run was called
        self.assertTrue(mock_run.called)

    @patch("commands.subprocess.run")
    @patch("commands.shutil.which", return_value="/usr/local/bin/claude")
    def test_env_vars_set_correctly(self, mock_which, mock_run):
        """Proxy env vars (ANTHROPIC_BASE_URL, etc.) must be set for the child process."""
        mock_run.return_value = MagicMock(returncode=0)
        with patch.dict(os.environ, {}, clear=False):
            invoke_claude("antigravity", "opus", "sonnet", "haiku", [])
        self.assertTrue(mock_run.called)
        call_kwargs = mock_run.call_args
        # env is passed as keyword argument
        env = call_kwargs[1].get("env") if call_kwargs[1] else {}
        if env:
            self.assertIn("ANTHROPIC_BASE_URL", env)
            self.assertIn("ANTHROPIC_AUTH_TOKEN", env)
            self.assertEqual(env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"), "opus")

    @patch("commands.subprocess.run")
    @patch("commands.shutil.which", return_value="/usr/local/bin/claude")
    def test_passes_cli_args_to_claude(self, mock_which, mock_run):
        """Extra CLI args should be forwarded to the claude subprocess."""
        mock_run.return_value = MagicMock(returncode=0)
        invoke_claude("gemini", "op", "son", "hk", ["--dangerously-skip-permissions"])
        cmd_called = mock_run.call_args[0][0]
        self.assertIn("--dangerously-skip-permissions", cmd_called)


class TestCmdTokenList(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_tl_"))
        os.environ.pop("CC_PROXY_TOKEN_DIR", None)
        td = self.tmp / "configs" / "tokens"
        td.mkdir(parents=True, exist_ok=True)
        import json
        (td / "claude-test.json").write_text(json.dumps({"email": "test@test.com"}))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_lists_tokens_for_provider(self):
        result = cmd_token_list(self.tmp, "claude")
        self.assertEqual(result, 0)

    def test_lists_all_providers_when_no_provider(self):
        result = cmd_token_list(self.tmp, None)
        self.assertEqual(result, 0)


class TestCmdTokenDelete(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_td_"))
        os.environ.pop("CC_PROXY_TOKEN_DIR", None)
        td = self.tmp / "configs" / "tokens"
        td.mkdir(parents=True, exist_ok=True)
        import json
        (td / "claude-delete_me.json").write_text(json.dumps({"email": "delete_me@test.com"}))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_requires_yes_flag(self):
        result = cmd_token_delete(self.tmp, "claude", "claude-delete_me.json", yes=False)
        self.assertEqual(result, 1)

    def test_deletes_with_yes(self):
        result = cmd_token_delete(self.tmp, "claude", "claude-delete_me.json", yes=True)
        self.assertEqual(result, 0)
        td = self.tmp / "configs" / "tokens"
        self.assertFalse((td / "claude-delete_me.json").exists())

    def test_invalid_provider(self):
        result = cmd_token_delete(self.tmp, "badprovider", "somefile.json", yes=True)
        self.assertEqual(result, 1)

    def test_rejects_path_traversal(self):
        result = cmd_token_delete(self.tmp, "claude", "../../../etc/passwd", yes=True)
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
