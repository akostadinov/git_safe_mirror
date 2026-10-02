"""URL-01..08: URL validation behaviour of git_safe_mirror.sh.

Covers rejection of file://, absolute-path, ./, ../, ~/, empty, and
scheme-less (plain host:path) repository URLs, plus the accepted-form
matrix (https://, scp-style, ssh://).
"""

import os
import subprocess
import tempfile
import unittest

from tests.harness import SCRIPT_PATH, MirrorTestCase


class UrlValidationTestCase(MirrorTestCase):
    def assert_rejected_url(self, url):
        r = self.run_script(repos=[url])
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("WARN: rejected repository URL: %s" % url, r.stderr)
        self.assert_done(r.stderr, 1, 1)
        self.assertEqual(r.stderr.count("WARN: "), 1, r.stderr)
        self.assertNotIn("CLONE  ", r.stderr)
        self.assertNotIn("UPDATE ", r.stderr)
        self.assertEqual(os.listdir(self.base_dir), [])

    def test_URL_01_file_scheme_rejected(self):
        self.assert_rejected_url("file:///etc/passwd")

    def test_URL_02_absolute_path_rejected(self):
        self.assert_rejected_url("/srv/git/repo.git")

    def test_URL_03_dot_relative_rejected(self):
        self.assert_rejected_url("./repo.git")

    def test_URL_04_dotdot_relative_rejected(self):
        self.assert_rejected_url("../repo.git")

    def test_URL_05_home_relative_rejected(self):
        self.assert_rejected_url("~/repo.git")

    def test_URL_06_empty_url_rejected(self):
        # read_list() strips blank lines before validate_url() is called,
        # so an empty URL is unreachable via the full script. Extract and
        # unit-test the function directly.
        fd, vu_path = tempfile.mkstemp(prefix="gsm-vu-", suffix=".sh")
        os.close(fd)
        try:
            with open(vu_path, "w") as f:
                subprocess.run(
                    ["sed", "-n", "/^validate_url()/,/^}/p", SCRIPT_PATH],
                    check=True, stdout=f,
                )
            with open(vu_path) as f:
                extracted = f.read()
            assert "validate_url" in extracted, "failed to extract validate_url() from script"
            r = subprocess.run(
                ["bash", "-c",
                 'source "%s"; validate_url "" && echo BAD || echo REJECTED'
                 % vu_path],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(r.stdout.strip(), "REJECTED")
        finally:
            os.unlink(vu_path)

    def test_URL_07_plain_host_path_rejected(self):
        self.assert_rejected_url("github.com:owner/repo")

    def test_URL_08_accepted_forms_matrix(self):
        urls = [
            "https://github.com/acme/repo.git",
            "git@github.com:acme/scp.git",
            "ssh://git@git.example.net:2222/group/project.git",
            "git://github.com/acme/gitproto.git",
        ]
        self.make_upstream("github.com", "acme/repo")
        self.make_upstream("github.com", "acme/scp")
        self.make_upstream("git.example.net", "group/project")
        self.make_upstream("github.com", "acme/gitproto")

        r = self.run_script(repos=urls)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("WARN: rejected repository URL", r.stderr)
        self.assert_done(r.stderr, 4, 0)
        for url in urls:
            self.assertIn("CLONE  %s" % url, r.stderr)
            self.assertTrue(os.path.isdir(self.mirror_dir(url)), url)
            self.assertIn("refs/heads/main", self.refs(url))


if __name__ == "__main__":
    unittest.main()
