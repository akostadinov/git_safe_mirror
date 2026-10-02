"""PACK-01..02: packed-refs handling in git_safe_mirror.sh.

PACK-01: after a force-push update creates a timestamped backup ref, the
script runs pack-refs --all --prune, so packed-refs must exist and contain
both the live branch and the backup ref.

PACK-02: pack-refs failure increments FAILS but does not abort sync_repo.
"""

import os
import unittest

from tests.harness import MirrorTestCase, BACKUP_RE


class PackTestCase(MirrorTestCase):
    def test_PACK_01_packed_refs_after_update(self):
        url = "https://github.com/acme/pack.git"
        up = self.make_upstream("github.com", "acme/pack")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)

        up.rewrite_main("rewrite")

        r2 = self.run_script(repos=[url])
        self.assertEqual(r2.returncode, 0, r2.stderr)

        packed = os.path.join(self.mirror_dir(url), "packed-refs")
        self.assertTrue(os.path.isfile(packed), "packed-refs missing")
        with open(packed) as f:
            content = f.read()
        self.assertIn("refs/heads/main\n", content)
        self.assertIsNotNone(
            BACKUP_RE.search(content),
            "backup ref missing from packed-refs",
        )

    def test_PACK_02_pack_refs_failure_nonfatal(self):
        url = "https://github.com/acme/packfail.git"
        up = self.make_upstream("github.com", "acme/packfail")

        r1 = self.run_script(repos=[url])
        self.assertEqual(r1.returncode, 0, r1.stderr)

        up.commit("second")

        wrapper_dir = self.git_wrapper(['pack-refs'])

        r2 = self.run_script(repos=[url], path_prefix=wrapper_dir)
        self.assertEqual(r2.returncode, 1)
        self.assertIn("WARN: pack-refs failed: %s" % url, r2.stderr)
        self.assert_done(r2.stderr, 1, 1)
        self.assertEqual(
            self.refs(url)["refs/heads/main"], up.tip("main"))
        self.assert_no_staging(url)


if __name__ == "__main__":
    unittest.main()
