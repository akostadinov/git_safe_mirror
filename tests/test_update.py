"""UPDATE-01..10: incremental update behaviour of git_safe_mirror.sh.

Covers fast-forward updates, new branches, non-fast-forward (force push)
backups, atomic staging/promotion transactions, no-prune semantics,
set-url switching, fetch-failure handling, and set-url failure.
"""

import re
import unittest

from tests.harness import MirrorTestCase


class UpdateTestCase(MirrorTestCase):

    def test_UPDATE_01_fast_forward(self):
        url = "https://github.com/acme/repo-u01.git"
        up = self.make_upstream("github.com", "acme/repo-u01")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertIn("CLONE  %s" % url, r1.stderr)

        a = up.tip("main")
        c = up.commit("second")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % url, r2.stderr)
        self.assertNotIn("FORCE PUSH", r2.stderr)
        self.assertEqual(self.refs(url)["refs/heads/main"], c)
        self.assertNotEqual(c, a)
        self.assertEqual(self.backup_refs(url, "main"), [])
        self.assert_no_staging(url)

    def test_UPDATE_02_new_upstream_branch(self):
        url = "https://github.com/acme/repo-u02.git"
        up = self.make_upstream("github.com", "acme/repo-u02")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        main_tip = up.tip("main")

        up.branch("feature")
        f = up.commit("feature commit", branch="feature")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % url, r2.stderr)

        refs = self.refs(url)
        self.assertEqual(refs["refs/heads/feature"], f)
        self.assertEqual(refs["refs/heads/main"], main_tip)
        self.assertEqual(self.backup_refs(url, "feature"), [])
        self.assert_no_staging(url)

    def test_UPDATE_03_force_push_backup(self):
        url = "https://github.com/acme/repo-u03.git"
        up = self.make_upstream("github.com", "acme/repo-u03")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        a = up.tip("main")

        b = up.rewrite_main("rewrite")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)

        m = re.search(
            r"FORCE PUSH on main: staging backup (refs/heads/main-\d{14})",
            r2.stderr,
        )
        self.assertIsNotNone(m, r2.stderr)
        backup = m.group(1)

        refs = self.refs(url)
        self.assertEqual(refs["refs/heads/main"], b)
        self.assertEqual(refs[backup], a)
        self.assertEqual(self.backup_refs(url, "main"), [backup])
        self.assert_no_staging(url)

    def test_UPDATE_04_transaction_force_and_fast_forward(self):
        url = "https://github.com/acme/repo-u04.git"
        up = self.make_upstream("github.com", "acme/repo-u04")
        up.branch("dev")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        a_main = up.tip("main")

        new_dev = up.commit("dev advance", branch="dev")
        b_main = up.rewrite_main("rewrite main")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("FORCE PUSH on main", r2.stderr)

        refs = self.refs(url)
        self.assertEqual(refs["refs/heads/main"], b_main)
        self.assertEqual(refs["refs/heads/dev"], new_dev)

        main_backups = self.backup_refs(url, "main")
        self.assertEqual(len(main_backups), 1)
        self.assertEqual(refs[main_backups[0]], a_main)
        self.assertEqual(self.backup_refs(url, "dev"), [])
        self.assert_no_staging(url)

    def test_UPDATE_05_multi_branch_fast_forward(self):
        url = "https://github.com/acme/repo-u05.git"
        up = self.make_upstream("github.com", "acme/repo-u05")
        up.branch("dev")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)

        new_main = up.commit("main advance", branch="main")
        new_dev = up.commit("dev advance", branch="dev")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % url, r2.stderr)
        self.assertNotIn("FORCE PUSH", r2.stderr)

        refs = self.refs(url)
        self.assertEqual(refs["refs/heads/main"], new_main)
        self.assertEqual(refs["refs/heads/dev"], new_dev)
        self.assertEqual(self.backup_refs(url, "main"), [])
        self.assertEqual(self.backup_refs(url, "dev"), [])
        self.assert_no_staging(url)

    def test_UPDATE_06_no_prune_of_deleted_branch(self):
        url = "https://github.com/acme/repo-u06.git"
        up = self.make_upstream("github.com", "acme/repo-u06")
        up.branch("feature")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        feature_tip = up.tip("feature")
        self.assertTrue(self.ref_exists(url, "refs/heads/feature"))

        up.delete_branch("feature")
        c = up.commit("main advance")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)

        refs = self.refs(url)
        self.assertEqual(refs["refs/heads/main"], c)
        self.assertIn("refs/heads/feature", refs)
        self.assertEqual(refs["refs/heads/feature"], feature_tip)
        self.assert_no_staging(url)

    def test_UPDATE_07_staging_fetch_failure(self):
        url = "https://github.com/acme/repo-u07.git"
        up = self.make_upstream("github.com", "acme/repo-u07")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        a = up.tip("main")

        up.commit("second")
        self.runtime.fail_nth_info_refs(
            "github.com", "/github.com/acme/repo-u07.git", 1, 500)

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 1, r2.stderr)
        self.assertIn(
            "WARN: branch staging fetch failed: %s" % url, r2.stderr)

        refs = self.refs(url)
        self.assertEqual(refs["refs/heads/main"], a)
        self.assertEqual(self.backup_refs(url, "main"), [])
        self.assert_no_staging(url)

    def test_UPDATE_08_set_url_switches_remote(self):
        https_url = "https://github.com/acme/repo-u08.git"
        scp_url = "git@github.com:acme/repo-u08.git"
        up = self.make_upstream("github.com", "acme/repo-u08")

        r1 = self.run_script(repos=[https_url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        a = up.tip("main")

        c = up.commit("second")

        r2 = self.run_script(repos=[scp_url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % scp_url, r2.stderr)
        self.assertNotIn("UPDATE %s" % https_url, r2.stderr)

        self.assertEqual(self.remote_url(scp_url), scp_url)
        self.assertEqual(self.refs(scp_url)["refs/heads/main"], c)
        self.assertNotEqual(c, a)
        self.assert_no_staging(scp_url)

    def test_UPDATE_09_multi_repo_mixed(self):
        good = "https://github.com/acme/good-u09.git"
        bad = "https://github.com/acme/bad-u09.git"
        up_good = self.make_upstream("github.com", "acme/good-u09")
        up_bad = self.make_upstream("github.com", "acme/bad-u09")

        r1 = self.run_script(repos=[good, bad])
        self.assertEqual(r1.returncode, 0, r1.stderr)

        bad_before = up_bad.tip("main")
        good_tip = up_good.commit("good advance")
        up_bad.commit("bad advance")

        self.runtime.fail_nth_info_refs(
            "github.com", "/github.com/acme/bad-u09.git", 1, 500)

        r2 = self.run_script(repos=[good, bad])
        self.assertEqual(r2.returncode, 1, r2.stderr)
        self.assertIn(
            "WARN: branch staging fetch failed: %s" % bad, r2.stderr)
        self.assert_done(r2.stderr, 2, 1)

        self.assertEqual(self.refs(good)["refs/heads/main"], good_tip)
        self.assertEqual(self.refs(bad)["refs/heads/main"], bad_before)
        self.assert_no_staging(good)
        self.assert_no_staging(bad)

    def test_UPDATE_10_set_url_failure(self):
        url = "https://github.com/acme/urlfail.git"
        up = self.make_upstream("github.com", "acme/urlfail")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        main_before = up.tip("main")

        up.commit("second")

        wrapper_dir = self.git_wrapper(['set-url'])

        r2 = self.run_script(repos=[url], path_prefix=wrapper_dir)
        self.assertEqual(r2.returncode, 1, r2.stderr)
        self.assert_done(r2.stderr, 1, 1)
        self.assertEqual(self.refs(url)["refs/heads/main"], main_before)
        self.assert_no_staging(url)


if __name__ == "__main__":
    unittest.main()
