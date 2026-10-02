"""FAIL-01..05: failure handling and summary reporting.

Covers silent clone failures, update fetch failures leaving live refs
untouched, the DONE summary line format for mixed runs, all-green runs,
and rejected mirror destinations.

See tests/TEST_CATALOG.md for the exact assertions.
"""

import unittest

from tests.harness import MirrorTestCase


class FailuresTestCase(MirrorTestCase):
    # FAIL-01: covered by CLONE-06 (test_clone_06_clone_failure_silent)
    # def test_FAIL_01_clone_failure_silent(self):
    #     url = "https://github.com/acme/clonefail.git"
    #     self.make_upstream("github.com", "acme/clonefail")
    #     self.runtime.fail_nth_info_refs(
    #         "github.com", "/github.com/acme/clonefail.git", 1, 404)
    #
    #     r = self.run_script(repos=[url])
    #     self.assertEqual(r.returncode, 1, r.stderr)
    #     self.assertIn("CLONE  %s" % url, r.stderr)
    #     self.assertIn("DONE: 1 repos, 1 failures", r.stderr)
    #     self.assertNotIn("WARN:", r.stderr)

    # FAIL-02: covered by UPDATE-07 (test_update_07_fetch_failure_live_refs_unchanged)
    # def test_FAIL_02_update_fetch_failure_live_refs_unchanged(self):
    #     url = "https://github.com/acme/updatefail.git"
    #     up = self.make_upstream("github.com", "acme/updatefail")
    #
    #     r1 = self.run_script(repos=[url])
    #     self.assertEqual(r1.returncode, 0, r1.stderr)
    #     a = up.tip("main")
    #     refs_before = self.refs(url)
    #
    #     up.commit("second")
    #     self.runtime.fail_nth_info_refs(
    #         "github.com", "/github.com/acme/updatefail.git", 1, 500)
    #
    #     r2 = self.run_script(repos=[url])
    #     self.assertEqual(r2.returncode, 1, r2.stderr)
    #     self.assertIn("DONE: 1 repos, 1 failures", r2.stderr)
    #     self.assertIn(
    #         "WARN: branch staging fetch failed: %s" % url, r2.stderr)
    #     self.assertEqual(self.refs(url), refs_before)
    #     self.assertEqual(self.refs(url)["refs/heads/main"], a)

    def test_FAIL_03_summary_format_mixed_run(self):
        good = "https://github.com/acme/good.git"
        bad1 = "https://github.com/acme/bad1.git"
        bad2 = "https://github.com/acme/bad2.git"
        self.make_upstream("github.com", "acme/good")
        self.make_upstream("github.com", "acme/bad1")
        self.make_upstream("github.com", "acme/bad2")
        self.runtime.fail_nth_info_refs(
            "github.com", "/github.com/acme/bad1.git", 1, 404)
        self.runtime.fail_nth_info_refs(
            "github.com", "/github.com/acme/bad2.git", 1, 404)

        r = self.run_script(
            repos=[good, bad1, bad2, "file:///etc/passwd"])
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assert_done(r.stderr, 4, 3)
        self.assertIn("CLONE  %s" % good, r.stderr)
        self.assertIn(
            "WARN: rejected repository URL: file:///etc/passwd", r.stderr)

    def test_FAIL_04_all_green(self):
        url1 = "https://github.com/acme/one.git"
        url2 = "https://github.com/acme/two.git"
        self.make_upstream("github.com", "acme/one")
        self.make_upstream("github.com", "acme/two")

        r = self.run_script(repos=[url1, url2])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_done(r.stderr, 2, 0)

    def test_FAIL_05_rejected_destination(self):
        url = "https://github.com/repo"
        r = self.run_script(repos=[url])
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(
            "WARN: rejected repository destination: %s" % url, r.stderr)
        self.assert_done(r.stderr, 1, 1)
        self.assertIsNone(self.mirror_dir(url))


if __name__ == "__main__":
    unittest.main()
