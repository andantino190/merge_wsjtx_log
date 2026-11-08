#!/usr/bin/env python3
import os
import shutil
import tempfile
import unittest
from remote_sync import LogTarget

class TestRemoteSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_target_parsing(self):
        t1 = LogTarget("w541u.local:/home/shitoh/.local/share/WSJT-X/wsjtx_log.adi")
        self.assertTrue(t1.is_remote)
        self.assertEqual(t1.host, "w541u.local")
        self.assertEqual(t1.path, "/home/shitoh/.local/share/WSJT-X/wsjtx_log.adi")

        t2 = LogTarget("m1p.local:/Users/shitoh/Library/Application Support/WS/wsjtx_log.adi")
        self.assertTrue(t2.is_remote)
        self.assertEqual(t2.host, "m1p.local")
        self.assertEqual(t2.path, "/Users/shitoh/Library/Application Support/WS/wsjtx_log.adi")

        t3 = LogTarget("/Users/shitoh/wsjtx_log.adi")
        self.assertFalse(t3.is_remote)
        self.assertEqual(t3.host, "")
        self.assertEqual(t3.path, "/Users/shitoh/wsjtx_log.adi")

    def test_local_operations(self):
        src_file = os.path.join(self.test_dir, "original.adi")
        with open(src_file, "w") as f:
            f.write("test adif content")

        dest_fetch = os.path.join(self.test_dir, "fetched.adi")
        target = LogTarget(src_file)

        # 1. Fetch
        mtime = target.fetch(dest_fetch)
        self.assertTrue(os.path.exists(dest_fetch))
        self.assertGreater(mtime, 0)

        # 2. Backup
        bak_path = target.create_backup("20230101_120000")
        self.assertTrue(os.path.exists(bak_path))
        self.assertTrue(bak_path.endswith(".bak_20230101_120000"))

        # 3. Deploy
        new_content_file = os.path.join(self.test_dir, "new.adi")
        with open(new_content_file, "w") as f:
            f.write("updated content")

        target.deploy(new_content_file)
        with open(src_file, "r") as f:
            self.assertEqual(f.read(), "updated content")

if __name__ == "__main__":
    unittest.main()
