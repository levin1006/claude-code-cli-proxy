"""
Smoke tests — require the actual CLIProxyAPI binary to be present.
These are heavier integration checks, not mock-based.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from paths import get_base_dir, get_binary_path


class TestBinaryExists(unittest.TestCase):
    def test_binary_file_present(self):
        """The CLIProxyAPI binary should be present under the repo."""
        base = get_base_dir()
        exe = get_binary_path(base)
        self.assertTrue(
            exe.exists(),
            "Binary not found at {}. Smoke tests require the binary.".format(exe),
        )


class TestBinaryHelp(unittest.TestCase):
    def test_help_output_contains_version(self):
        """Running cli-proxy-api -h should print a version line."""
        base = get_base_dir()
        exe = get_binary_path(base)
        if not exe.exists():
            self.skipTest("Binary not found: {}".format(exe))

        result = subprocess.run(
            [str(exe), "-h"],
            capture_output=True, text=True, timeout=5,
        )
        combined = result.stdout + result.stderr
        self.assertIn(
            "CLIProxyAPI Version:",
            combined,
            "Expected 'CLIProxyAPI Version:' in -h output",
        )

    def test_help_shows_login_flags(self):
        """Binary help should list the login flags we depend on."""
        base = get_base_dir()
        exe = get_binary_path(base)
        if not exe.exists():
            self.skipTest("Binary not found")

        result = subprocess.run(
            [str(exe), "-h"],
            capture_output=True, text=True, timeout=5,
        )
        combined = result.stdout + result.stderr
        for flag in ["-antigravity-login", "-claude-login", "-codex-login", "-login"]:
            # The -login flag is shared/generic, may appear as substring
            self.assertIn(
                flag.lstrip("-"),
                combined.replace(" ", "").lower(),
                "Expected flag '{}' in -h output".format(flag),
            )


class TestCoreImports(unittest.TestCase):
    """Verify that all core modules can be imported without errors."""

    def test_import_constants(self):
        import constants  # noqa: F401

    def test_import_paths(self):
        import paths  # noqa: F401

    def test_import_config(self):
        import config  # noqa: F401

    def test_import_process(self):
        import process  # noqa: F401

    def test_import_api(self):
        import api  # noqa: F401

    def test_import_proxy(self):
        import proxy  # noqa: F401

    def test_import_usage(self):
        import usage  # noqa: F401

    def test_import_commands(self):
        import commands  # noqa: F401

    def test_import_display(self):
        import display  # noqa: F401

    def test_import_quota(self):
        import quota  # noqa: F401

    def test_import_tui(self):
        import tui  # noqa: F401

    def test_import_cc_proxy(self):
        import cc_proxy  # noqa: F401


if __name__ == "__main__":
    unittest.main()
