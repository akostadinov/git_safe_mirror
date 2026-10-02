"""CFG-01..03: config file (orgs.txt) parsing in git_safe_mirror.sh.

Covers comment lines, blank/whitespace-only lines, and CRLF stripping.
"""

from tests.harness import MirrorTestCase, repo_json


class ConfigTestCase(MirrorTestCase):
    def org_lines(self, stderr):
        out = []
        for line in stderr.splitlines():
            _, sep, msg = line.partition(" | ")
            if sep and msg.startswith("ORG    "):
                out.append(msg)
        return out

    def test_CFG_01_comments_ignored(self):
        self.make_upstream("github.com", "acme/repo")
        self.runtime.configure_api(
            "acme", host="api.github.com",
            pages=[[repo_json("acme", "repo")]])

        r = self.run_script(
            orgs=["# leading comment", "acme", "#no-space", "  # indented"])
        self.assertEqual(self.org_lines(r.stderr), ["ORG    acme"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_done(r.stderr, 1, 0)
        self.assertIn("CLONE  https://github.com/acme/repo.git", r.stderr)
        api = [x for x in self.api_captured() if x["host"] == "api.github.com"]
        self.assertGreaterEqual(len(api), 1)
        self.assertEqual(
            api[0]["path"], "/orgs/acme/repos?per_page=100&page=1&type=public")

    def test_CFG_02_blank_lines_ignored(self):
        self.make_upstream("github.com", "acme/repo")
        self.runtime.configure_api(
            "acme", host="api.github.com",
            pages=[[repo_json("acme", "repo")]])

        r = self.run_script(orgs=["", "   ", "\t", "acme", "  \t  ", ""])
        self.assertEqual(self.org_lines(r.stderr), ["ORG    acme"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_done(r.stderr, 1, 0)
        self.assertIn("CLONE  https://github.com/acme/repo.git", r.stderr)

    def test_CFG_03_crlf_stripped(self):
        self.make_upstream("github.com", "acme/repo")
        self.runtime.configure_api(
            "acme", host="api.github.com",
            pages=[[repo_json("acme", "repo")]])

        r = self.run_script(orgs_raw="# comment\r\nacme\r\n\r\n   \r\n")
        self.assertEqual(self.org_lines(r.stderr), ["ORG    acme"])
        self.assertNotIn("\r", r.stderr)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_done(r.stderr, 1, 0)
        api = [x for x in self.api_captured() if x["host"] == "api.github.com"]
        self.assertGreaterEqual(len(api), 1)
        self.assertNotIn("%0D", api[0]["path"])
        self.assertNotIn("\r", api[0]["path"])
        self.assertTrue(api[0]["path"].startswith("/orgs/acme/repos"))

    def test_CFG_04_inline_comment_not_stripped(self):
        r = self.run_script(orgs_raw="acme # production org\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn(
            "WARN: listing failed for org acme # production org", r.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
