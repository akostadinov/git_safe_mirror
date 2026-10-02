"""IDEM-01..02: idempotent re-runs with no upstream changes.

Covers the second-run UPDATE path (no CLONE), identical refs, no new
refs, and no leftover staging refs.
"""

import unittest

from tests.harness import MirrorTestCase


class IdempotencyTestCase(MirrorTestCase):
    def test_IDEM_01_second_run_no_change(self):
        url = "https://github.com/acme/idem.git"
        self.make_upstream("github.com", "acme/idem")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        refs_after_clone = self.refs(url)

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % url, r2.stderr)
        self.assertNotIn("CLONE", r2.stderr)
        self.assertEqual(self.refs(url), refs_after_clone)
        self.assert_no_staging(url)

    def test_IDEM_02_clone_appears_once(self):
        url = "https://github.com/acme/once.git"
        self.make_upstream("github.com", "acme/once")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)

        combined = r1.stderr + r2.stderr
        self.assertEqual(combined.count("CLONE  %s" % url), 1)


if __name__ == "__main__":
    unittest.main()
