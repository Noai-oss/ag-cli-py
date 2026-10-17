"""Verify version parsing shared by update and release checks."""

import unittest

from scripts.common import canonical_version


class CommonTests(unittest.TestCase):
    def test_canonical_versions_preserve_upstream_spelling(self):
        """Accept canonical versions and reject text requiring normalization."""
        self.assertGreater(canonical_version("1.9.0.post1"), canonical_version("1.9.0"))
        for value in ("1.0rc1", "1.0.dev1", "1.0+local", "1!1.0"):
            with self.subTest(version=value):
                self.assertEqual(str(canonical_version(value)), value)
        for value in ("no-version", "01.0", "1.0-1", "v1.0", "1.0\n"):
            with self.subTest(version=value), self.assertRaises(ValueError):
                canonical_version(value)
