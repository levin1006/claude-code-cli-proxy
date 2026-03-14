"""
Tests for core/proxy.py — proxy lifecycle, version detection, status reporting.
Uses mocks for subprocess and HTTP calls.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from proxy import (
    get_binary_version,
    get_status,
)
from constants import PORTS, PROVIDERS


class TestGetBinaryVersion(unittest.TestCase):
    @patch("proxy.subprocess.run")
    def test_parses_version_line(self, mock_run):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_ver_"))
        try:
            # Create a fake binary
            if sys.platform == "win32":
                exe = tmp / "CLIProxyAPI" / "windows" / "amd64" / "cli-proxy-api.exe"
            else:
                exe = tmp / "CLIProxyAPI" / "linux" / "amd64" / "cli-proxy-api"
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("fake")

            mock_run.return_value = MagicMock(
                stdout="CLIProxyAPI Version: 6.8.51, Commit: cf74ed2f, BuiltAt: 2026-03-10T11:09:30",
                stderr=""
            )
            result = get_binary_version(tmp)
            self.assertIn("6.8.51", result)
        finally:
            shutil.rmtree(tmp)

    def test_binary_not_found(self):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_ver_"))
        try:
            result = get_binary_version(tmp)
            self.assertEqual(result, "Not found")
        finally:
            shutil.rmtree(tmp)


class TestGetStatus(unittest.TestCase):
    @patch("proxy.check_health", return_value=True)
    @patch("proxy.is_pid_alive", return_value=True)
    @patch("proxy.read_pid", return_value=12345)
    def test_running_and_healthy(self, *_):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_gs_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            (tmp / "configs" / "tokens").mkdir(parents=True, exist_ok=True)
            s = get_status(tmp, "claude")
            self.assertTrue(s["running"])
            self.assertTrue(s["healthy"])
            self.assertEqual(s["pid"], 12345)
        finally:
            shutil.rmtree(tmp)

    @patch("proxy.read_pid", return_value=None)
    @patch("proxy.resolve_pid_by_port", return_value=None)
    def test_not_running(self, *_):
        tmp = Path(tempfile.mkdtemp(prefix="ccproxy_gs_"))
        try:
            os.environ.pop("CC_PROXY_TOKEN_DIR", None)
            (tmp / "configs" / "tokens").mkdir(parents=True, exist_ok=True)
            s = get_status(tmp, "claude")
            self.assertFalse(s["running"])
            self.assertFalse(s["healthy"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
