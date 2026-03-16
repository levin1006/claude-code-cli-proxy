"""
Tests for core/config.py — YAML rewriting, token parsing, and time formatting.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from config import (
    rewrite_port_in_config,
    rewrite_auth_dir_in_config,
    rewrite_secret_in_config,
    _parse_token_expiry,
    _fmt_reset_time,
    get_token_infos,
)


class TestRewritePortInConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_cfg_"))
        self.cfg = self.tmp / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_replaces_existing_port(self):
        self.cfg.write_text('host: "127.0.0.1"\nport: 8317\nauth-dir: "./"\n', encoding="utf-8")
        rewrite_port_in_config(self.cfg, 18418)
        text = self.cfg.read_text(encoding="utf-8")
        self.assertIn("port: 18418", text)
        self.assertNotIn("8317", text)

    def test_inserts_port_when_missing(self):
        self.cfg.write_text('host: "127.0.0.1"\nauth-dir: "./"\n', encoding="utf-8")
        rewrite_port_in_config(self.cfg, 18419)
        text = self.cfg.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("port: 18419"))

    def test_preserves_other_content(self):
        self.cfg.write_text('host: "127.0.0.1"\nport: 9999\ndebug: true\n', encoding="utf-8")
        rewrite_port_in_config(self.cfg, 18420)
        text = self.cfg.read_text(encoding="utf-8")
        self.assertIn("debug: true", text)
        self.assertIn("host:", text)


class TestRewriteAuthDirInConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_cfg_"))
        self.cfg = self.tmp / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_replaces_existing_auth_dir(self):
        self.cfg.write_text('auth-dir: "./"\nport: 8317\n', encoding="utf-8")
        new_dir = self.tmp / "tokens"
        new_dir.mkdir()
        rewrite_auth_dir_in_config(self.cfg, new_dir)
        text = self.cfg.read_text(encoding="utf-8")
        expected = str(new_dir.resolve()).replace("\\", "/")
        self.assertIn(expected, text)

    def test_inserts_auth_dir_when_missing(self):
        self.cfg.write_text('port: 8317\n', encoding="utf-8")
        new_dir = self.tmp / "tokens"
        new_dir.mkdir()
        rewrite_auth_dir_in_config(self.cfg, new_dir)
        text = self.cfg.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("auth-dir:"))


class TestRewriteSecretInConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_cfg_"))
        self.cfg = self.tmp / "config.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_replaces_secret_key(self):
        self.cfg.write_text('remote-management:\n  secret-key: "cc"\n', encoding="utf-8")
        rewrite_secret_in_config(self.cfg, "new-secret")
        text = self.cfg.read_text(encoding="utf-8")
        self.assertIn('"new-secret"', text)
        self.assertNotIn('"cc"', text)


class TestParseTokenExpiry(unittest.TestCase):
    def test_valid_rfc3339_utc(self):
        dt = _parse_token_expiry("2026-03-15T12:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 3)

    def test_valid_rfc3339_with_offset(self):
        dt = _parse_token_expiry("2026-03-15T12:00:00+09:00")
        self.assertIsNotNone(dt)

    def test_long_subsecond_truncation(self):
        dt = _parse_token_expiry("2026-03-15T12:00:00.123456789+00:00")
        self.assertIsNotNone(dt)

    def test_invalid_string(self):
        dt = _parse_token_expiry("not-a-time")
        self.assertIsNone(dt)


class TestFmtResetTime(unittest.TestCase):
    def test_seconds_to_hours_minutes(self):
        result = _fmt_reset_time(7200 + 840)  # 2h14m
        self.assertIn("2h", result)
        self.assertIn("14m", result)

    def test_large_seconds_to_days(self):
        result = _fmt_reset_time(86400 * 2 + 3600 * 3)  # 2d3h
        self.assertIn("2d", result)

    def test_zero_seconds(self):
        result = _fmt_reset_time(0)
        self.assertEqual(result, "now")

    def test_none_returns_empty(self):
        result = _fmt_reset_time(None)
        self.assertEqual(result, "")

    def test_small_minutes(self):
        result = _fmt_reset_time(300)  # 5m
        self.assertEqual(result, "5m")


class TestGetTokenInfos(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_ti_"))
        os.environ.pop("CC_PROXY_TOKEN_DIR", None)
        self.token_dir = self.tmp / "tokens"
        self.token_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ok_status(self):
        (self.token_dir / "claude-test.json").write_text(
            json.dumps({"email": "test@test.com"}), encoding="utf-8"
        )
        infos = get_token_infos(self.tmp, "claude")
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0]["status"], "ok")
        self.assertEqual(infos[0]["email"], "test@test.com")

    def test_disabled_status(self):
        (self.token_dir / "claude-dis.json").write_text(
            json.dumps({"email": "dis@test.com", "disabled": True}), encoding="utf-8"
        )
        infos = get_token_infos(self.tmp, "claude")
        self.assertEqual(infos[0]["status"], "disabled")

    def test_expired_status(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        (self.token_dir / "claude-exp.json").write_text(
            json.dumps({"email": "exp@test.com", "expired": past}), encoding="utf-8"
        )
        infos = get_token_infos(self.tmp, "claude")
        self.assertEqual(infos[0]["status"], "expired")

    def test_future_expiry_shows_ok(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        (self.token_dir / "claude-fut.json").write_text(
            json.dumps({"email": "fut@test.com", "expired": future}), encoding="utf-8"
        )
        infos = get_token_infos(self.tmp, "claude")
        self.assertEqual(infos[0]["status"], "ok")

    def test_empty_directory(self):
        infos = get_token_infos(self.tmp, "claude")
        self.assertEqual(infos, [])


if __name__ == "__main__":
    unittest.main()
