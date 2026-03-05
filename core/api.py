"""
Management API client and secret key resolution.
Depends on: constants, paths
"""

import json
import os
import re

from constants import HOST, PORTS
from paths import get_config_file


def _management_api_request(provider, endpoint, secret="cc", method="GET", payload=None, timeout=8):
    """Call /v0/management/<endpoint> with Bearer auth.

    method: GET/POST/DELETE
    payload: dict -> JSON body (for POST/PUT)
    """
    import urllib.request

    port = PORTS[provider]
    url = "http://{}:{}/v0/management/{}".format(HOST, port, endpoint.lstrip("/"))
    headers = {"Authorization": "Bearer {}".format(secret)}
    raw = None
    if payload is not None:
        raw = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=raw, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if not body:
        return {}
    text = body.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def _management_api(provider, endpoint, secret="cc"):
    """GET /v0/management/<endpoint> from a running provider proxy."""
    return _management_api_request(provider, endpoint, secret, method="GET", payload=None, timeout=5)


def _proxy_api(provider, path, timeout=5):
    """GET arbitrary path from a running provider proxy (no management auth)."""
    import urllib.request
    port = PORTS[provider]
    url = "http://{}:{}/{}".format(HOST, port, path.lstrip("/"))
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _read_secret_key(base_dir, provider):
    """Return plaintext secret key for management API Bearer auth.

    Priority:
    1. CC_PROXY_SECRET env var (user override)
    2. config.yaml secret-key — only if it looks like plaintext (not a bcrypt hash)
    3. Default "cc"

    The CLIProxyAPI binary rewrites the secret-key in config.yaml as a bcrypt
    hash on startup, so config.yaml nearly always contains a hash, not the
    plaintext.  We cannot reverse a bcrypt hash, so we fall back to "cc".
    """
    env_secret = os.environ.get("CC_PROXY_SECRET")
    if env_secret:
        return env_secret
    config_path = get_config_file(base_dir, provider)
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        m = re.search(r'secret-key:\s*"([^"]*)"', text)
        if m:
            val = m.group(1)
            # bcrypt hashes start with $2a$, $2b$, $2y$ — not useful as Bearer token
            if not val.startswith("$2"):
                return val
    return "cc"
