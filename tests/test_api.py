"""
Tests for core/api.py — management API client and secret key resolution.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from api import _management_api_request, _management_api, _proxy_api, _read_secret_key


# api.py imports urllib.request inside functions, so we patch the global module
class TestManagementApiRequest(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_get_json_response(self, mock_urlopen):
        body = json.dumps({"status": "ok"}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _management_api_request("claude", "usage", "secret123")
        self.assertEqual(result, {"status": "ok"})

    @patch("urllib.request.urlopen")
    def test_empty_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _management_api_request("claude", "usage")
        self.assertEqual(result, {})

    @patch("urllib.request.urlopen")
    def test_non_json_body(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"plain text response"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _management_api_request("claude", "health")
        self.assertIn("raw", result)

    @patch("urllib.request.urlopen", side_effect=Exception("connection refused"))
    def test_connection_error(self, _):
        with self.assertRaises(Exception):
            _management_api_request("claude", "usage")


class TestManagementApi(unittest.TestCase):
    @patch("api._management_api_request", return_value={"usage": {}})
    def test_delegates_to_request(self, mock_req):
        result = _management_api("claude", "usage", "secret")
        mock_req.assert_called_once_with("claude", "usage", "secret", method="GET", payload=None, timeout=5)
        self.assertEqual(result, {"usage": {}})


class TestProxyApi(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_get_models(self, mock_urlopen):
        body = json.dumps({"data": [{"id": "claude-3"}]}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _proxy_api("claude", "v1/models")
        self.assertIn("data", result)


class TestReadSecretKey(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ccproxy_sk_"))
        (self.tmp / "configs" / "claude").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        os.environ.pop("CC_PROXY_SECRET", None)
        shutil.rmtree(self.tmp)

    def test_env_var_takes_priority(self):
        os.environ["CC_PROXY_SECRET"] = "env-secret"
        result = _read_secret_key(self.tmp, "claude")
        self.assertEqual(result, "env-secret")

    def test_plaintext_from_config(self):
        os.environ.pop("CC_PROXY_SECRET", None)
        cfg = self.tmp / "configs" / "claude" / "config.yaml"
        cfg.write_text('remote-management:\n  secret-key: "my-plain-secret"\n', encoding="utf-8")
        result = _read_secret_key(self.tmp, "claude")
        self.assertEqual(result, "my-plain-secret")

    def test_bcrypt_hash_falls_back_to_default(self):
        os.environ.pop("CC_PROXY_SECRET", None)
        cfg = self.tmp / "configs" / "claude" / "config.yaml"
        cfg.write_text('remote-management:\n  secret-key: "$2b$10$hashedvalue"\n', encoding="utf-8")
        result = _read_secret_key(self.tmp, "claude")
        self.assertEqual(result, "cc")

    def test_no_config_returns_default(self):
        os.environ.pop("CC_PROXY_SECRET", None)
        result = _read_secret_key(self.tmp, "claude")
        self.assertEqual(result, "cc")


if __name__ == "__main__":
    unittest.main()
