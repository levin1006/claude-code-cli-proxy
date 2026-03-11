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
    get_local_port_offset,
    get_management_port,
    get_management_url,
    get_status,
    render_dashboard_html,
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


class TestLocalPortOffset(unittest.TestCase):
    @patch.dict(os.environ, {"CC_PROXY_LOCAL_PORT_OFFSET": "10000"})
    def test_env_override(self):
        self.assertEqual(get_local_port_offset(), 10000)

    @patch.dict(os.environ, {}, clear=False)
    def test_default_zero(self):
        os.environ.pop("CC_PROXY_LOCAL_PORT_OFFSET", None)
        self.assertEqual(get_local_port_offset(), 0)

    @patch.dict(os.environ, {"CC_PROXY_LOCAL_PORT_OFFSET": "invalid"})
    def test_invalid_returns_zero(self):
        self.assertEqual(get_local_port_offset(), 0)


class TestGetManagementPort(unittest.TestCase):
    @patch("proxy.get_local_port_offset", return_value=0)
    def test_no_offset(self, _):
        for prov in PROVIDERS:
            self.assertEqual(get_management_port(prov), PORTS[prov])

    @patch("proxy.get_local_port_offset", return_value=10000)
    def test_with_offset(self, _):
        self.assertEqual(get_management_port("claude"), PORTS["claude"] + 10000)


class TestGetManagementUrl(unittest.TestCase):
    @patch("proxy.get_local_port_offset", return_value=0)
    def test_url_format(self, _):
        url = get_management_url("claude")
        self.assertIn("127.0.0.1", url)
        self.assertIn(str(PORTS["claude"]), url)
        self.assertIn("management.html", url)


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


class TestRenderDashboardHtml(unittest.TestCase):
    @patch("proxy.get_local_port_offset", return_value=0)
    def test_contains_all_providers(self, _):
        html = render_dashboard_html()
        for prov in PROVIDERS:
            self.assertIn(prov, html)

    @patch("proxy.get_local_port_offset", return_value=0)
    def test_contains_iframes(self, _):
        html = render_dashboard_html()
        self.assertIn("<iframe", html)

    @patch("proxy.get_local_port_offset", return_value=0)
    def test_valid_html(self, _):
        html = render_dashboard_html()
        self.assertIn("<!doctype html>", html)
        self.assertIn("</html>", html)


if __name__ == "__main__":
    unittest.main()
