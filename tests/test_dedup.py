"""DEDUP-01..03: URL deduplication in git_safe_mirror.sh.

Dedup is by exact URL string (no normalization): the same URL from
repos.txt and from org discovery is synced once, duplicates within
repos.txt are synced once, and "owner/repo.git" vs "owner/repo" are
two distinct URL strings that map to the same mirror directory.

See tests/TEST_CATALOG.md for the exact assertions.
"""

from tests.harness import MirrorTestCase, repo_json


class DedupTestCase(MirrorTestCase):
    def test_DEDUP_01_same_url_from_org_and_repos_txt(self):
        url = "https://github.com/acme/repo.git"
        up = self.make_upstream("github.com", "acme/repo")
        self.runtime.configure_api(
            "acme", host="api.github.com",
            pages=[[repo_json("acme", "repo")]])

        r = self.run_script(orgs=["acme"], repos=[url])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("CLONE  %s" % url), 1, r.stderr)
        self.assertNotIn("UPDATE ", r.stderr)
        self.assert_done(r.stderr, 1, 0)
        self.assertEqual(self.refs(url)["refs/heads/main"], up.tip("main"))
        api = [x for x in self.api_captured() if x["host"] == "api.github.com"]
        self.assertGreaterEqual(len(api), 1)

    def test_DEDUP_02_duplicate_within_repos_txt(self):
        url = "https://github.com/acme/repo.git"
        up = self.make_upstream("github.com", "acme/repo")

        r = self.run_script(repos=[url, url])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("CLONE  %s" % url), 1, r.stderr)
        self.assertNotIn("UPDATE ", r.stderr)
        self.assert_done(r.stderr, 1, 0)
        self.assertEqual(self.refs(url)["refs/heads/main"], up.tip("main"))

    def test_DEDUP_03_exact_string_key_same_mirror_dir(self):
        url_git = "https://github.com/acme/repo.git"
        url_plain = "https://github.com/acme/repo"
        up = self.make_upstream("github.com", "acme/repo")

        # Both spellings map to the same mirror directory but are distinct
        # exact-string keys, so both are attempted (DONE counts 2 repos).
        # The first clones; the second finds objects/ already present and
        # takes the UPDATE path. Its branch staging fetch succeeds (main is
        # unchanged) but the tag fetch fails because the dumb-HTTP info/refs
        # does not advertise HEAD. Observed outcome: one CLONE, one UPDATE,
        # DONE: 2 repos, 1 failures.
        self.assertEqual(self.mirror_dir(url_git), self.mirror_dir(url_plain))

        r = self.run_script(repos=[url_git, url_plain])
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stderr.count("CLONE  %s" % url_git), 1, r.stderr)
        self.assertIn("UPDATE %s" % url_plain, r.stderr)
        self.assertIn(
            "WARN: tag fetch failed: %s" % url_plain, r.stderr)
        self.assert_done(r.stderr, 2, 1)
        self.assertEqual(self.refs(url_git)["refs/heads/main"], up.tip("main"))


if __name__ == "__main__":
    import unittest
    unittest.main()
