"""Org discovery tests (curl+jq path, no gh) for git_safe_mirror.sh.

Covers ORG-01..09:

- ORG-01 pagination: pages of 100,100,5 then []. All cloned, ``DONE: 205 repos,
  0 failures``, 4 API GETs with page=1..4, Accept header present.
- ORG-02 empty org ([]): exit 0, no CLONE, ``DONE: 0 repos, 0 failures``,
  1 API request.
- ORG-03 non-array ({"message":"Not Found"}): exit 1,
  ``WARN: listing failed for org <org>``, ``DONE: 0 repos, 1 failures``.
- ORG-04 transport failure (500): exit 1,
  ``WARN: listing failed for org <org>``.
- ORG-05 GH_TOKEN -> ``Authorization: Bearer <token>`` header captured.
- ORG-06 no GH_TOKEN -> no Authorization header.
- ORG-07 clone_url extraction: repo objects with distinct
  clone_url/ssh_url/html_url/git_url -> cloned URL == clone_url.
- ORG-08 invalid org name (``bad_org!``): exit 1,
  ``WARN: listing failed for org bad_org!``, ZERO API requests.
- ORG-09 org listing failure does not block explicit repos: broken org +
  good repo -> exit 1, good cloned, ``DONE: 1 repos, 1 failures``.
"""

import os
import subprocess

from tests.harness import MirrorTestCase, repo_json


class TestOrgDiscovery(MirrorTestCase):

    def _clone_urls(self, stderr):
        urls = []
        for line in stderr.splitlines():
            if "CLONE  " in line:
                urls.append(line.split("CLONE  ", 1)[1].strip())
        return urls

    def test_org_01_pagination(self):
        org = "org01"
        names = ["repo%03d" % i for i in range(205)]
        pages = [
            [repo_json(org, n) for n in names[0:100]],
            [repo_json(org, n) for n in names[100:200]],
            [repo_json(org, n) for n in names[200:205]],
        ]
        self.runtime.configure_api(org, host="api.github.com", pages=pages)

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_done(proc.stderr, 205, 0)

        api = self.api_captured()
        self.assertEqual(len(api), 4)
        for i, req in enumerate(api, start=1):
            self.assertEqual(req["method"], "GET")
            self.assertEqual(req["host"], "api.github.com")
            self.assertEqual(req["path"].split("?")[0], "/orgs/%s/repos" % org)
            self.assertEqual(self.page_of(req), str(i))
            self.assertEqual(
                self.header(req, "Accept"), "application/vnd.github+json")

        expected_urls = [
            "https://github.com/%s/%s.git" % (org, n) for n in names
        ]
        cloned = self._clone_urls(proc.stderr)
        self.assertEqual(len(cloned), 205)
        self.assertEqual(sorted(cloned), sorted(expected_urls))

        for url in expected_urls:
            md = self.mirror_dir(url)
            self.assertTrue(os.path.isdir(md), md)
            self.assertTrue(os.path.isfile(os.path.join(md, "HEAD")), md)
            self.assertTrue(os.path.isdir(os.path.join(md, "objects")), md)
            self.assertTrue(os.path.isdir(os.path.join(md, "refs")), md)
            self.assertTrue(self.ref_exists(url, "refs/heads/main"))

    def test_org_02_empty_org(self):
        org = "empty-org"
        self.runtime.configure_api(org, host="api.github.com", pages=[[]])

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("CLONE", proc.stderr)
        self.assert_done(proc.stderr, 0, 0)
        self.assertEqual(len(self.api_captured()), 1)

    def test_org_03_non_array_response(self):
        org = "nonarray-org"
        self.runtime.configure_api(
            org, host="api.github.com", body=b'{"message":"Not Found"}')

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 1)
        self.assertIn("WARN: listing failed for org %s" % org, proc.stderr)
        self.assert_done(proc.stderr, 0, 1)

    def test_org_04_transport_failure(self):
        org = "down-org"
        self.runtime.configure_api(
            org, host="api.github.com", status=500, body=b"boom")

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 1)
        self.assertIn("WARN: listing failed for org %s" % org, proc.stderr)
        self.assert_done(proc.stderr, 0, 1)

    def test_org_05_token_authorization_header(self):
        org = "tok-org"
        token = "test-token-abc123"
        self.runtime.configure_api(org, host="api.github.com", pages=[[]])

        proc = self.run_script(orgs=(org,), token=token)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        api = self.api_captured()
        self.assertEqual(len(api), 1)
        self.assertEqual(
            self.header(api[0], "Authorization"), "Bearer %s" % token)

    def test_org_06_no_token_no_authorization(self):
        org = "notok-org"
        self.runtime.configure_api(org, host="api.github.com", pages=[[]])

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        api = self.api_captured()
        self.assertEqual(len(api), 1)
        self.assertIsNone(self.header(api[0], "Authorization"))

    def test_org_07_clone_url_extraction(self):
        org = "extract-org"
        repo = repo_json("owner", "name")
        self.runtime.configure_api(org, host="api.github.com", pages=[[repo]])

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        clone_url = repo["clone_url"]
        self.assertIn("CLONE  %s" % clone_url, proc.stderr)
        self.assertNotIn(repo["ssh_url"], proc.stderr)
        self.assertNotIn(repo["git_url"], proc.stderr)

        md = self.mirror_dir(clone_url)
        self.assertTrue(os.path.isdir(md), md)
        out = subprocess.run(
            ["git", "--git-dir", md, "config", "remote.origin.url"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(out, clone_url)

    def test_org_08_invalid_org_name(self):
        org = "bad_org!"

        proc = self.run_script(orgs=(org,))

        self.assertEqual(proc.returncode, 1)
        self.assertIn("WARN: listing failed for org %s" % org, proc.stderr)
        self.assertEqual(self.api_captured(), [])

    def test_org_09_org_failure_does_not_block_repos(self):
        org = "broken-org"
        self.runtime.configure_api(
            org, host="api.github.com", status=500, body=b"boom")
        self.make_upstream("github.com", "owner/good")
        good_url = "https://github.com/owner/good.git"

        proc = self.run_script(orgs=(org,), repos=(good_url,))

        self.assertEqual(proc.returncode, 1)
        self.assertIn("WARN: listing failed for org %s" % org, proc.stderr)
        self.assertIn("CLONE  %s" % good_url, proc.stderr)
        self.assert_done(proc.stderr, 1, 1)
        self.assertTrue(os.path.isdir(self.mirror_dir(good_url)))
