"""CLONE-01..08: initial clone behavior of git_safe_mirror.sh."""

import os
import subprocess
import unittest

from tests.harness import MirrorTestCase


class CloneTest(MirrorTestCase):
    def _is_bare(self, url):
        return subprocess.run(
            ["git", "--git-dir", self.mirror_dir(url), "rev-parse", "--is-bare-repository"],
            capture_output=True, text=True, check=True,
        ).stdout.strip() == "true"

    def _info_refs_requests(self, url):
        return [r for r in self.git_captured(url) if "info/refs" in r["path"]]

    def test_clone_01_https_clone(self):
        url = "https://github.com/owner/repo.git"
        upstream = self.make_upstream("github.com", "owner/repo")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLONE  " + url, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        self.assertTrue(os.path.isdir(self.mirror_dir(url)))
        self.assertTrue(self._is_bare(url))
        self.assertEqual(self.refs(url).get("refs/heads/main"), upstream.tip())
        self.assertEqual(self.remote_url(url), url)
        info_refs = self._info_refs_requests(url)
        self.assertEqual(len(info_refs), 1)
        self.assertTrue(all(r["method"] == "GET" for r in self.git_captured(url)))

    def test_clone_02_scp_style_subgroup(self):
        url = "git@gitlab.com:group/subgroup/project.git"
        self.make_upstream("gitlab.com", "group/subgroup/project")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLONE  " + url, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        self.assertEqual(
            self.mirror_dir(url),
            os.path.join(self.base_dir, "gitlab.com", "group", "subgroup", "project.git"),
        )
        self.assertTrue(os.path.isdir(self.mirror_dir(url)))
        self.assertEqual(self.remote_url(url), url)

    def test_clone_03_ssh_url_port_stripped(self):
        url = "ssh://git@git.example.net:2222/group/project.git"
        self.make_upstream("git.example.net", "group/project")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLONE  " + url, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        self.assertEqual(
            self.mirror_dir(url),
            os.path.join(self.base_dir, "git.example.net", "group", "project.git"),
        )
        self.assertTrue(os.path.isdir(self.mirror_dir(url)))
        self.assertEqual(self.remote_url(url), url)

    def test_clone_04_git_suffix_and_trailing_slash(self):
        url_git = "https://github.com/owner/repo.git"
        url_slash = "https://github.com/owner/repo2.git/"
        self.make_upstream("github.com", "owner/repo")
        self.make_upstream("github.com", "owner/repo2")
        result = self.run_script(repos=[url_git, url_slash])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 2, 0)
        self.assertTrue(os.path.isdir(self.mirror_dir(url_git)))
        self.assertEqual(
            self.mirror_dir(url_slash),
            os.path.join(self.base_dir, "github.com", "owner", "repo2.git"),
        )
        self.assertTrue(os.path.isdir(self.mirror_dir(url_slash)))
        self.assertEqual(self.remote_url(url_git), url_git)
        self.assertEqual(self.remote_url(url_slash), url_slash)

    def test_clone_05_host_collision_distinct_mirrors(self):
        url_gh = "https://github.com/owner/repo.git"
        url_other = "https://git.example.net/owner/repo.git"
        self.make_upstream("github.com", "owner/repo")
        other = self.make_upstream("git.example.net", "owner/repo")
        other.branch("extra")
        result = self.run_script(repos=[url_gh, url_other])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 2, 0)
        self.assertTrue(os.path.isdir(self.mirror_dir(url_gh)))
        self.assertTrue(os.path.isdir(self.mirror_dir(url_other)))
        self.assertNotEqual(self.mirror_dir(url_gh), self.mirror_dir(url_other))
        self.assertFalse(self.ref_exists(url_gh, "refs/heads/extra"))
        self.assertTrue(self.ref_exists(url_other, "refs/heads/extra"))
        self.assertNotEqual(
            self.refs(url_gh).get("refs/heads/main"),
            self.refs(url_other).get("refs/heads/main"),
        )

    def test_clone_06_clone_failure_silent(self):
        url = "https://github.com/owner/repo.git"
        self.make_upstream("github.com", "owner/repo")
        self.runtime.fail_nth_info_refs("github.com", "/github.com/owner/repo.git", 1, 404)
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 1)
        self.assertIn("CLONE  " + url, result.stderr)
        self.assert_done(result.stderr, 1, 1)
        self.assertNotIn("WARN", result.stderr)
        self.assertFalse(os.path.isdir(self.mirror_dir(url)), "mirror dir should not exist after failed clone")

    def test_clone_07_empty_dir_treated_as_clone(self):
        url = "https://github.com/owner/repo.git"
        upstream = self.make_upstream("github.com", "owner/repo")
        os.makedirs(self.mirror_dir(url))
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CLONE  " + url, result.stderr)
        self.assertNotIn("UPDATE " + url, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        self.assertEqual(self.refs(url).get("refs/heads/main"), upstream.tip())

    def test_clone_08_no_staging_refs_after_clone(self):
        url = "https://github.com/owner/repo.git"
        self.make_upstream("github.com", "owner/repo")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        out = subprocess.run(
            ["git", "--git-dir", self.mirror_dir(url), "for-each-ref", "refs/git-mirror"],
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(out, "")
        self.assert_done(result.stderr, 1, 0)


if __name__ == "__main__":
    unittest.main()
