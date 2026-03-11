"""
Tests for core/constants.py — validates integrity of shared constants.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from constants import PORTS, PRESETS, PROVIDERS, LOGIN_FLAGS


class TestPorts(unittest.TestCase):
    def test_all_providers_have_ports(self):
        for p in PROVIDERS:
            self.assertIn(p, PORTS, "Provider {} missing from PORTS".format(p))

    def test_ports_are_valid_range(self):
        for prov, port in PORTS.items():
            self.assertGreater(port, 1023, "Port {} for {} is below 1024".format(port, prov))
            self.assertLess(port, 65536, "Port {} for {} is above 65535".format(port, prov))

    def test_ports_are_unique(self):
        seen = {}
        for prov, port in PORTS.items():
            self.assertNotIn(port, seen,
                             "Duplicate port {}: {} and {}".format(port, prov, seen.get(port)))
            seen[port] = prov

    def test_ports_are_integers(self):
        for prov, port in PORTS.items():
            self.assertIsInstance(port, int)


class TestPresets(unittest.TestCase):
    def test_all_presets_reference_valid_providers(self):
        for name, (provider, opus, sonnet, haiku) in PRESETS.items():
            self.assertIn(provider, PROVIDERS,
                          "Preset '{}' references unknown provider '{}'".format(name, provider))

    def test_presets_have_four_elements(self):
        for name, val in PRESETS.items():
            self.assertEqual(len(val), 4,
                             "Preset '{}' should have 4 elements, got {}".format(name, len(val)))

    def test_presets_model_names_are_non_empty(self):
        for name, (provider, opus, sonnet, haiku) in PRESETS.items():
            self.assertTrue(opus, "Preset '{}' has empty opus model".format(name))
            self.assertTrue(sonnet, "Preset '{}' has empty sonnet model".format(name))
            self.assertTrue(haiku, "Preset '{}' has empty haiku model".format(name))


class TestLoginFlags(unittest.TestCase):
    def test_all_providers_have_login_flags(self):
        for p in PROVIDERS:
            self.assertIn(p, LOGIN_FLAGS)

    def test_login_flags_start_with_dash(self):
        for prov, flag in LOGIN_FLAGS.items():
            self.assertTrue(flag.startswith("-"),
                            "Login flag for {} should start with '-': {}".format(prov, flag))


class TestProviders(unittest.TestCase):
    def test_providers_is_tuple(self):
        self.assertIsInstance(PROVIDERS, tuple)

    def test_providers_not_empty(self):
        self.assertGreater(len(PROVIDERS), 0)

    def test_no_duplicate_providers(self):
        self.assertEqual(len(PROVIDERS), len(set(PROVIDERS)))


if __name__ == "__main__":
    unittest.main()
