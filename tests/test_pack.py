"""PACK-01: packed-refs written after an update.

After a force-push update creates a timestamped backup ref, the script
runs pack-refs --all --prune, so packed-refs must exist and contain both
the live branch and the backup ref.
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


if __name__ == "__main__":
    unittest.main()
