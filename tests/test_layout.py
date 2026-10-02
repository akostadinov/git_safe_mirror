"""LAYOUT-01..04: mirror directory layout of git_safe_mirror.sh."""

import os
import subprocess
import unittest

from tests.harness import MirrorTestCase


class LayoutTest(MirrorTestCase):
    def _head_symref(self, url):
        return subprocess.run(
            ["git", "--git-dir", self.mirror_dir(url), "symbolic-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def _is_bare(self, url):
        return subprocess.run(
            ["git", "--git-dir", self.mirror_dir(url), "rev-parse", "--is-bare-repository"],
            capture_output=True, text=True, check=True,
        ).stdout.strip() == "true"

    def test_layout_01_basic_layout(self):
        url = "https://github.com/owner/repo.git"
        self.make_upstream("github.com", "owner/repo")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        expected = os.path.join(self.base_dir, "github.com", "owner", "repo.git")
        self.assertEqual(self.mirror_dir(url), expected)
        self.assertTrue(os.path.isdir(expected))
        self.assertTrue(self._is_bare(url))
        self.assertEqual(self._head_symref(url), "refs/heads/main")

    def test_layout_02_subgroup_full_path(self):
        url = "git@gitlab.com:group/subgroup/project.git"
        self.make_upstream("gitlab.com", "group/subgroup/project")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        expected = os.path.join(
            self.base_dir, "gitlab.com", "group", "subgroup", "project.git")
        self.assertEqual(self.mirror_dir(url), expected)
        self.assertTrue(os.path.isdir(expected))

    def test_layout_03_ssh_port_omitted_from_path(self):
        url = "ssh://git@git.example.net:2222/group/project.git"
        self.make_upstream("git.example.net", "group/project")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        expected = os.path.join(self.base_dir, "git.example.net", "group", "project.git")
        self.assertEqual(self.mirror_dir(url), expected)
        self.assertTrue(os.path.isdir(expected))
        self.assertEqual(self.remote_url(url), url)

    def test_layout_04_dot_components_rejected(self):
        for url in ("https://github.com/owner/../repo.git",
                    "https://github.com/./repo.git"):
            with self.subTest(url=url):
                result = self.run_script(repos=[url])
                self.assertEqual(result.returncode, 1)
                self.assertIn(
                    "WARN: rejected repository destination: " + url, result.stderr)
                self.assert_done(result.stderr, 1, 1)
        self.assertEqual(os.listdir(self.base_dir), [])

    def test_LAYOUT_05_ssh_without_user(self):
        url = "ssh://git.example.net/group/project.git"
        self.make_upstream("git.example.net", "group/project")
        result = self.run_script(repos=[url])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_done(result.stderr, 1, 0)
        expected = os.path.join(self.base_dir, "git.example.net", "group", "project.git")
        self.assertEqual(self.mirror_dir(url), expected)
        self.assertTrue(os.path.isdir(expected))
        self.assertEqual(self.remote_url(url), url)


if __name__ == "__main__":
    unittest.main()
