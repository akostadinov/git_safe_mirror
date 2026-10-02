"""repo_dir_for_url: direct unit tests for URL-to-mirror-path extraction.

Sources git_safe_mirror.sh so all functions are available without sed
extraction. The script returns early when sourced.
"""

import os
import subprocess
import unittest

from tests.harness import SCRIPT_PATH, MirrorTestCase


def run_repo_dir(base_dir, url):
    r = subprocess.run(
        ["bash", "-c",
         'BASE_DIR="%s"; source "%s"; repo_dir_for_url "%s"'
         % (base_dir, SCRIPT_PATH, url)],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout.strip()


class RepoDirTestCase(MirrorTestCase):
    def assert_dir(self, url, expected_host, expected_path):
        rc, out = run_repo_dir(self.base_dir, url)
        self.assertEqual(rc, 0, "repo_dir_for_url failed for: %s" % url)
        self.assertEqual(out, os.path.join(self.base_dir, expected_host,
                                          *expected_path.split("/")) + ".git",
                         "mismatch for: %s" % url)

    def assert_rejects(self, url):
        rc, _ = run_repo_dir(self.base_dir, url)
        self.assertNotEqual(rc, 0, "should have rejected: %s" % url)

    # --- HTTPS ---
    def test_https_basic(self):
        self.assert_dir("https://github.com/owner/repo.git",
                        "github.com", "owner/repo")

    def test_https_subgroup(self):
        self.assert_dir("https://gitlab.com/group/subgroup/project.git",
                        "gitlab.com", "group/subgroup/project")

    def test_https_trailing_slash(self):
        self.assert_dir("https://github.com/owner/repo/",
                        "github.com", "owner/repo")

    def test_https_no_git_suffix(self):
        self.assert_dir("https://github.com/owner/repo",
                        "github.com", "owner/repo")

    # --- git:// ---
    def test_git_proto(self):
        self.assert_dir("git://github.com/owner/repo.git",
                        "github.com", "owner/repo")

    # --- ssh:// with user@host:port ---
    def test_ssh_url_with_user_and_port(self):
        self.assert_dir("ssh://git@git.example.net:2222/group/project.git",
                        "git.example.net", "group/project")

    def test_ssh_url_with_user_no_port(self):
        self.assert_dir("ssh://git@gitlab.com/group/project.git",
                        "gitlab.com", "group/project")

    def test_ssh_url_no_user(self):
        self.assert_dir("ssh://git.example.net/group/project.git",
                        "git.example.net", "group/project")

    def test_ssh_url_subgroup(self):
        self.assert_dir("ssh://git@gitlab.com/group/subgroup/project.git",
                        "gitlab.com", "group/subgroup/project")

    # --- SCP-like ---
    def test_scp_basic(self):
        self.assert_dir("git@github.com:owner/repo.git",
                        "github.com", "owner/repo")

    def test_scp_subgroup(self):
        self.assert_dir("git@gitlab.com:group/subgroup/project.git",
                        "gitlab.com", "group/subgroup/project")

    def test_scp_trailing_slash(self):
        self.assert_dir("git@github.com:owner/repo/",
                        "github.com", "owner/repo")

    def test_scp_no_git_suffix(self):
        self.assert_dir("git@github.com:owner/repo",
                        "github.com", "owner/repo")

    def test_scp_multiple_at_signs(self):
        self.assert_dir("user@internal@github.com:owner/repo.git",
                        "github.com", "owner/repo")

    # --- Rejections ---
    def test_rejects_single_component_path(self):
        self.assert_rejects("https://github.com/repo")

    def test_rejects_dot_component(self):
        self.assert_rejects("https://github.com/./repo.git")

    def test_rejects_dotdot_component(self):
        self.assert_rejects("https://github.com/owner/../repo.git")

    def test_rejects_file_scheme(self):
        self.assert_rejects("file:///etc/passwd")

    def test_rejects_absolute_path(self):
        self.assert_rejects("/srv/git/repo.git")

    def test_rejects_unsupported_scheme(self):
        self.assert_rejects("ftp://github.com/owner/repo.git")


if __name__ == "__main__":
    unittest.main()
