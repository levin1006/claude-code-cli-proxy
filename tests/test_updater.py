"""Unit tests for core/updater.py — self-update logic."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure core/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import updater


class TestGetInstalledCommit(unittest.TestCase):
    """Tests for get_installed_commit()."""

    def test_returns_sha_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {"commit_sha": "abc123def456", "repo": "owner/repo"}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertEqual(updater.get_installed_commit(base), "abc123def456")

    def test_returns_none_when_missing_key(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {"repo": "owner/repo"}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertIsNone(updater.get_installed_commit(base))

    def test_returns_none_when_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self.assertIsNone(updater.get_installed_commit(base))

    def test_returns_none_when_empty_sha(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {"commit_sha": "", "repo": "owner/repo"}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertIsNone(updater.get_installed_commit(base))


class TestGetInstalledRepo(unittest.TestCase):
    """Tests for get_installed_repo()."""

    def test_returns_repo_from_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {"repo": "custom/repo"}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertEqual(updater.get_installed_repo(base), "custom/repo")

    def test_returns_default_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self.assertEqual(updater.get_installed_repo(base), "levin1006/claude-code-cli-proxy")


class TestGetLocalSourceRoot(unittest.TestCase):
    """Tests for get_local_source_root()."""

    def test_returns_path_when_dir_exists(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_root = base / "local_repo"
            source_root.mkdir()
            meta = {"local_source_root": str(source_root)}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertEqual(updater.get_local_source_root(base), source_root)

    def test_returns_none_when_dir_missing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {"local_source_root": "/nonexistent/path/foo/bar"}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertIsNone(updater.get_local_source_root(base))

    def test_returns_none_when_key_missing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            meta = {"repo": "owner/repo"}
            (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
            self.assertIsNone(updater.get_local_source_root(base))


class TestGetRemoteCommit(unittest.TestCase):
    """Tests for get_remote_commit() with mocked HTTP."""

    @patch("updater.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"sha": "deadbeef1234"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        sha, err = updater.get_remote_commit("owner/repo")
        self.assertEqual(sha, "deadbeef1234")
        self.assertIsNone(err)

    @patch("updater.urllib.request.urlopen")
    def test_missing_sha_field(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"message": "not found"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        sha, err = updater.get_remote_commit("owner/repo")
        self.assertIsNone(sha)
        self.assertIn("missing", err)

    @patch("updater.urllib.request.urlopen")
    def test_rate_limit(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.github.com/...", 403, "rate limit", {}, None
        )
        sha, err = updater.get_remote_commit("owner/repo")
        self.assertIsNone(sha)
        self.assertIn("rate limit", err.lower())

    @patch("updater.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        sha, err = updater.get_remote_commit("owner/repo")
        self.assertIsNone(sha)
        self.assertIn("Network error", err)


class TestGitHelpers(unittest.TestCase):
    """Tests for internal git helper functions."""

    @patch("updater.shutil.which")
    def test_git_available_true(self, mock_which):
        mock_which.return_value = "/usr/bin/git"
        self.assertTrue(updater._git_available())

    @patch("updater.shutil.which")
    def test_git_available_false(self, mock_which):
        mock_which.return_value = None
        self.assertFalse(updater._git_available())

    @patch("updater.subprocess.run")
    def test_git_rev_parse_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")
        result = updater._git_rev_parse("/some/repo")
        self.assertEqual(result, "abc123")

    @patch("updater.subprocess.run")
    def test_git_rev_parse_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        result = updater._git_rev_parse("/some/repo")
        self.assertIsNone(result)

    @patch("updater.subprocess.run")
    def test_git_is_dirty_clean(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        self.assertFalse(updater._git_is_dirty("/some/repo"))

    @patch("updater.subprocess.run")
    def test_git_is_dirty_dirty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=" M file.py\n")
        self.assertTrue(updater._git_is_dirty("/some/repo"))


class TestCmdUpdate(unittest.TestCase):
    """Tests for cmd_update() end-to-end with mocking."""

    def _make_base(self, commit_sha=None, local_source=None, repo=None):
        td = tempfile.mkdtemp()
        base = Path(td)
        meta = {"repo": repo or "owner/repo"}
        if commit_sha is not None:
            meta["commit_sha"] = commit_sha
        if local_source is not None:
            meta["local_source_root"] = str(local_source)
        (base / ".install-meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return base

    @patch("updater.get_remote_commit")
    def test_already_up_to_date(self, mock_remote):
        base = self._make_base(commit_sha="aaa111")
        mock_remote.return_value = ("aaa111", None)
        rc = updater.cmd_update(base)
        self.assertEqual(rc, 0)

    @patch("updater.get_remote_commit")
    def test_network_error_returns_1(self, mock_remote):
        base = self._make_base(commit_sha="aaa111")
        mock_remote.return_value = (None, "Network error: timeout")
        rc = updater.cmd_update(base)
        self.assertEqual(rc, 1)

    @patch("updater._run_installer")
    @patch("updater._git_pull_ff_only")
    @patch("updater._git_fetch")
    @patch("updater._git_is_dirty")
    @patch("updater._git_available")
    @patch("updater.get_remote_commit")
    def test_local_update_success(self, mock_remote, mock_git_avail,
                                   mock_dirty, mock_fetch, mock_pull, mock_install):
        with tempfile.TemporaryDirectory() as td_src:
            base = self._make_base(commit_sha="aaa111", local_source=td_src)
            mock_remote.return_value = ("bbb222", None)
            mock_git_avail.return_value = True
            mock_dirty.return_value = False
            mock_fetch.return_value = (True, "")
            mock_pull.return_value = (True, "Already up to date.")
            mock_install.return_value = True

            rc = updater.cmd_update(base)
            self.assertEqual(rc, 0)
            mock_install.assert_called_once_with("local", Path(td_src))

    @patch("updater._git_is_dirty")
    @patch("updater._git_available")
    @patch("updater.get_remote_commit")
    def test_dirty_repo_blocks_without_force(self, mock_remote, mock_git_avail, mock_dirty):
        with tempfile.TemporaryDirectory() as td_src:
            base = self._make_base(commit_sha="aaa111", local_source=td_src)
            mock_remote.return_value = ("bbb222", None)
            mock_git_avail.return_value = True
            mock_dirty.return_value = True

            rc = updater.cmd_update(base, force=False)
            self.assertEqual(rc, 1)

    @patch("updater._run_installer")
    @patch("updater.get_remote_commit")
    def test_remote_fallback_when_no_local_repo(self, mock_remote, mock_install):
        base = self._make_base(commit_sha="aaa111")
        mock_remote.return_value = ("bbb222", None)
        mock_install.return_value = True

        rc = updater.cmd_update(base)
        self.assertEqual(rc, 0)
        mock_install.assert_called_once_with("remote")


if __name__ == "__main__":
    unittest.main()
