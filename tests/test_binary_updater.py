"""Unit tests for core/binary_updater.py — repo-only binary updater."""

import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure core/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import binary_updater


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tar_archive(output_path, binary_name="cli-proxy-api", content=b"#!/bin/sh\necho fake\n"):
    """Create a minimal tar.gz archive containing a fake binary."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=binary_name)
        info.size = len(content)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(content))
    Path(output_path).write_bytes(buf.getvalue())


def make_zip_archive(output_path, binary_name="cli-proxy-api.exe", content=b"fake_exe"):
    """Create a minimal zip archive containing a fake binary."""
    with zipfile.ZipFile(str(output_path), "w") as zf:
        zf.writestr(binary_name, content)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTagToVersion(unittest.TestCase):
    def test_strips_v(self):
        self.assertEqual(binary_updater._tag_to_version("v6.8.54"), "6.8.54")

    def test_no_prefix(self):
        self.assertEqual(binary_updater._tag_to_version("6.8.54"), "6.8.54")


class TestGetLatestRelease(unittest.TestCase):

    @patch("binary_updater.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"tag_name": "v6.8.54"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        tag, err = binary_updater.get_latest_release()
        self.assertEqual(tag, "v6.8.54")
        self.assertIsNone(err)

    @patch("binary_updater.urllib.request.urlopen")
    def test_missing_tag_name(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"name": "release"}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        tag, err = binary_updater.get_latest_release()
        self.assertIsNone(tag)
        self.assertIn("missing", err.lower())

    @patch("binary_updater.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        tag, err = binary_updater.get_latest_release()
        self.assertIsNone(tag)
        self.assertIn("Network error", err)

    @patch("binary_updater.urllib.request.urlopen")
    def test_rate_limit(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://api.github.com/...", 403, "rate limit", {}, None
        )
        tag, err = binary_updater.get_latest_release()
        self.assertIsNone(tag)
        self.assertIn("rate limit", err.lower())


class TestBuildDownloadUrl(unittest.TestCase):
    def test_linux_amd64(self):
        url = binary_updater.build_download_url("v6.8.54", "linux", "amd64", "tar.gz")
        self.assertEqual(
            url,
            "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
            "v6.8.54/CLIProxyAPI_6.8.54_linux_amd64.tar.gz",
        )

    def test_linux_arm64(self):
        url = binary_updater.build_download_url("v6.8.54", "linux", "arm64", "tar.gz")
        self.assertIn("linux_arm64.tar.gz", url)

    def test_windows_amd64(self):
        url = binary_updater.build_download_url("v6.8.54", "windows", "amd64", "zip")
        self.assertIn("windows_amd64.zip", url)


class TestDownloadAndPlace(unittest.TestCase):

    def test_extracts_tar_and_places_binary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            archive_path = td / "CLIProxyAPI_6.8.54_linux_amd64.tar.gz"
            make_tar_archive(archive_path)
            target = td / "output" / "cli-proxy-api"

            with patch("binary_updater.urllib.request.urlretrieve") as mock_dl:
                import shutil
                mock_dl.side_effect = lambda url, dest: shutil.copy(str(archive_path), dest)
                ok, err = binary_updater.download_and_place(
                    "https://example.com/CLIProxyAPI_6.8.54_linux_amd64.tar.gz",
                    target, "linux", "cli-proxy-api",
                )
            self.assertTrue(ok, err)
            self.assertTrue(target.exists())

    def test_extracts_zip_and_places_binary(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            archive_path = td / "CLIProxyAPI_6.8.54_windows_amd64.zip"
            make_zip_archive(archive_path)
            target = td / "output" / "cli-proxy-api.exe"

            with patch("binary_updater.urllib.request.urlretrieve") as mock_dl:
                import shutil
                mock_dl.side_effect = lambda url, dest: shutil.copy(str(archive_path), dest)
                ok, err = binary_updater.download_and_place(
                    "https://example.com/CLIProxyAPI_6.8.54_windows_amd64.zip",
                    target, "windows", "cli-proxy-api.exe",
                )
            self.assertTrue(ok, err)
            self.assertTrue(target.exists())

    def test_download_failure(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "output" / "cli-proxy-api"
            with patch("binary_updater.urllib.request.urlretrieve") as mock_dl:
                mock_dl.side_effect = Exception("timeout")
                ok, err = binary_updater.download_and_place(
                    "https://example.com/bad.tar.gz", target, "linux", "cli-proxy-api",
                )
            self.assertFalse(ok)
            self.assertIn("Download failed", err)

    def test_binary_not_in_archive(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # Create tar with wrong binary name
            archive_path = td / "CLIProxyAPI_6.8.54_linux_amd64.tar.gz"
            make_tar_archive(archive_path, binary_name="wrong-binary")
            target = td / "output" / "cli-proxy-api"

            with patch("binary_updater.urllib.request.urlretrieve") as mock_dl:
                import shutil
                mock_dl.side_effect = lambda url, dest: shutil.copy(str(archive_path), dest)
                ok, err = binary_updater.download_and_place(
                    "https://example.com/CLIProxyAPI_6.8.54_linux_amd64.tar.gz",
                    target, "linux", "cli-proxy-api",
                )
            self.assertFalse(ok)
            self.assertIn("not found", err)


class TestCmdUpdateAll(unittest.TestCase):

    def _setup_repo(self, td, existing_binaries=True):
        """Set up a mock repo directory structure."""
        base = Path(td)
        for os_name, arch, _, binary_name in binary_updater.PLATFORMS:
            d = base / "CLIProxyAPI" / os_name / arch
            d.mkdir(parents=True)
            if existing_binaries:
                (d / binary_name).touch()
        return base

    @patch("binary_updater.get_latest_release")
    @patch("binary_updater.get_current_binary_version")
    def test_already_up_to_date(self, mock_ver, mock_release):
        mock_ver.return_value = ("6.8.54", None)
        mock_release.return_value = ("v6.8.54", None)

        with tempfile.TemporaryDirectory() as td:
            rc = binary_updater.cmd_update_all(Path(td))
        self.assertEqual(rc, 0)

    @patch("binary_updater.download_and_place")
    @patch("binary_updater.get_latest_release")
    @patch("binary_updater.get_current_binary_version")
    def test_downloads_all_platforms(self, mock_ver, mock_release, mock_dl):
        mock_ver.return_value = ("6.8.51", None)
        mock_release.return_value = ("v6.8.54", None)
        mock_dl.return_value = (True, None)

        with tempfile.TemporaryDirectory() as td:
            rc = binary_updater.cmd_update_all(self._setup_repo(td))

        self.assertEqual(rc, 0)
        # Called once per platform
        self.assertEqual(mock_dl.call_count, len(binary_updater.PLATFORMS))

    @patch("binary_updater.get_latest_release")
    @patch("binary_updater.get_current_binary_version")
    def test_network_error_returns_1(self, mock_ver, mock_release):
        mock_ver.return_value = ("6.8.51", None)
        mock_release.return_value = (None, "Network error: timeout")

        with tempfile.TemporaryDirectory() as td:
            rc = binary_updater.cmd_update_all(Path(td))
        self.assertEqual(rc, 1)

    @patch("binary_updater.download_and_place")
    @patch("binary_updater.get_latest_release")
    @patch("binary_updater.get_current_binary_version")
    def test_partial_failure_returns_1(self, mock_ver, mock_release, mock_dl):
        mock_ver.return_value = ("6.8.51", None)
        mock_release.return_value = ("v6.8.54", None)
        # Fail on arm64, succeed on others
        def _dl_side_effect(url, target, os_name, binary_name):
            if "arm64" in str(target):
                return False, "arm64 download failed"
            return True, None
        mock_dl.side_effect = _dl_side_effect

        with tempfile.TemporaryDirectory() as td:
            rc = binary_updater.cmd_update_all(self._setup_repo(td))
        self.assertEqual(rc, 1)

    @patch("binary_updater.download_and_place")
    @patch("binary_updater.get_latest_release")
    @patch("binary_updater.get_current_binary_version")
    def test_force_reinstall(self, mock_ver, mock_release, mock_dl):
        mock_ver.return_value = ("6.8.54", None)
        mock_release.return_value = ("v6.8.54", None)
        mock_dl.return_value = (True, None)

        with tempfile.TemporaryDirectory() as td:
            rc = binary_updater.cmd_update_all(self._setup_repo(td), force=True)

        self.assertEqual(rc, 0)
        self.assertEqual(mock_dl.call_count, len(binary_updater.PLATFORMS))


if __name__ == "__main__":
    unittest.main()
