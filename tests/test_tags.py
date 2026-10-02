"""TAG-01..05: tag sync behaviour of git_safe_mirror.sh.

Covers lightweight tag sync, tag retention (no pruning), moved tag
updates, annotated tags, and tag-fetch failure isolation.
"""
import subprocess

from tests.harness import MirrorTestCase


class TagsTests(MirrorTestCase):
    def _git(self, url, *args):
        return subprocess.run(
            ["git", "--git-dir", self.mirror_dir(url), *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_TAG_01_new_lightweight_tag_synced(self):
        url = "https://github.com/owner/tag01.git"
        up = self.make_upstream("github.com", "owner/tag01")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertFalse(self.ref_exists(url, "refs/tags/v2"))

        up.tag("v2")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % url, r2.stderr)
        self.assertTrue(self.ref_exists(url, "refs/tags/v2"))
        self.assertEqual(self.refs(url)["refs/tags/v2"], up.tip("main"))

    def test_TAG_02_tags_not_pruned(self):
        url = "https://github.com/owner/tag02.git"
        up = self.make_upstream("github.com", "owner/tag02")
        up.tag("v1")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertTrue(self.ref_exists(url, "refs/tags/v1"))

        up.delete_tag("v1")

        main_tip = up.tip("main")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue(self.ref_exists(url, "refs/tags/v1"))
        self.assertEqual(self.refs(url)["refs/heads/main"], main_tip)
        self.assert_done(r2.stderr, 1, 0)

    def test_TAG_03_moved_tag_updated_no_backup(self):
        url = "https://github.com/owner/tag03.git"
        up = self.make_upstream("github.com", "owner/tag03")
        up.tag("v1")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)
        a = self.refs(url)["refs/tags/v1"]

        b = up.commit("second")
        up.move_tag("v1", b)

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("UPDATE %s" % url, r2.stderr)
        self.assert_done(r2.stderr, 1, 0)
        self.assertNotEqual(a, b)
        self.assertEqual(self.refs(url)["refs/tags/v1"], b)
        self.assertNotIn("FORCE PUSH", r2.stderr)
        for ref in self.refs(url):
            self.assertFalse(ref.startswith("refs/tags/v1-"), ref)

    def test_TAG_04_annotated_tag(self):
        url = "https://github.com/owner/tag04.git"
        up = self.make_upstream("github.com", "owner/tag04")
        up.tag("release-1", annotated=True)
        expected = up.tip("main")

        r = self.run_script(repos=[url])
        self.assertEqual(r.returncode, 0, r.stderr)

        kind = self._git(url, "cat-file", "-t", "refs/tags/release-1")
        self.assertEqual(kind, "tag")
        deref = self._git(url, "rev-parse", "refs/tags/release-1^{commit}")
        self.assertEqual(deref, expected)

    def test_TAG_05_tag_fetch_failure_branch_still_updated(self):
        url = "https://github.com/owner/tag05.git"
        up = self.make_upstream("github.com", "owner/tag05")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)

        new = up.commit("second")
        self.runtime.fail_nth_info_refs(
            "github.com", "/github.com/owner/tag05.git/info/refs", 2, 500
        )

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 1, r2.stderr)
        self.assertIn("WARN: tag fetch failed: %s" % url, r2.stderr)
        self.assertEqual(self.refs(url)["refs/heads/main"], new)
        self.assert_no_staging(url)
