"""
Tests for core/process.py — PID management, port resolution, health check.
Uses mocks for external process commands.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from process import (
    read_pid,
    write_pid,
    remove_pid,
    is_pid_alive,
    resolve_pid_by_port,
    check_health,
    is_ssh_session,
)
from constants import IS_WINDOWS


class TestPidFileOperations(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_pid_"))
        (self.tmp / "configs" / "claude").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_write_and_read_pid(self):
        write_pid(self.tmp, "claude", 12345)
        self.assertEqual(read_pid(self.tmp, "claude"), 12345)

    def test_read_missing_pid(self):
        self.assertIsNone(read_pid(self.tmp, "claude"))

    def test_remove_pid(self):
        write_pid(self.tmp, "claude", 99999)
        remove_pid(self.tmp, "claude")
        self.assertIsNone(read_pid(self.tmp, "claude"))

    def test_remove_nonexistent_pid_no_error(self):
        remove_pid(self.tmp, "claude")  # should not raise


class TestIsPidAlive(unittest.TestCase):
    @patch("process.subprocess.run")
    def test_alive_pid_windows(self, mock_run):
        if not IS_WINDOWS:
            self.skipTest("Windows-only test")
        mock_run.return_value = MagicMock(stdout='"process.exe","12345","Console","1","10,000 K"')
        self.assertTrue(is_pid_alive(12345))

    @patch("process.subprocess.run")
    def test_dead_pid_windows(self, mock_run):
        if not IS_WINDOWS:
            self.skipTest("Windows-only test")
        mock_run.return_value = MagicMock(stdout="INFO: No tasks are running which match the specified criteria.")
        self.assertFalse(is_pid_alive(99999))


class TestResolvePidByPort(unittest.TestCase):
    @patch("process.subprocess.run")
    def test_windows_netstat_parse(self, mock_run):
        if not IS_WINDOWS:
            self.skipTest("Windows-only test")
        mock_run.return_value = MagicMock(
            stdout=(
                "  TCP    127.0.0.1:18418       0.0.0.0:0          LISTENING       5678\n"
                "  TCP    0.0.0.0:8080          0.0.0.0:0          LISTENING       1111\n"
            )
        )
        pid = resolve_pid_by_port(18418)
        self.assertEqual(pid, 5678)

    @patch("process.subprocess.run")
    def test_returns_none_when_not_found(self, mock_run):
        if not IS_WINDOWS:
            self.skipTest("Windows-only test")
        mock_run.return_value = MagicMock(stdout="  TCP    0.0.0.0:8080   0.0.0.0:0  LISTENING  1111\n")
        pid = resolve_pid_by_port(18418)
        self.assertIsNone(pid)


class TestCheckHealth(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_healthy(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        self.assertTrue(check_health("claude"))

    @patch("urllib.request.urlopen")
    def test_unhealthy_500(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        self.assertFalse(check_health("claude"))

    @patch("urllib.request.urlopen", side_effect=Exception("connection refused"))
    def test_unreachable(self, mock_urlopen):
        self.assertFalse(check_health("claude"))


class TestIsSSHSession(unittest.TestCase):
    @patch.dict(os.environ, {"SSH_CONNECTION": "1.2.3.4 5678 5.6.7.8 22"}, clear=False)
    def test_ssh_detected(self):
        self.assertTrue(is_ssh_session())

    @patch.dict(os.environ, {}, clear=True)
    def test_no_ssh(self):
        # Clear SSH vars: set a minimal env
        env_backup = os.environ.copy()
        os.environ.pop("SSH_CONNECTION", None)
        os.environ.pop("SSH_TTY", None)
        try:
            self.assertFalse(is_ssh_session())
        finally:
            os.environ.update(env_backup)


if __name__ == "__main__":
    unittest.main()
