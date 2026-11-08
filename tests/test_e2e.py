#!/usr/bin/env python3
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SAMPLE_LOG_1 = """WSJT-X ADIF Export<eoh>
<call:4>W1AW <qso_date:8>20230601 <time_on:6>101500 <band:3>20m <mode:3>FT8 <rst_sent:3>-05 <rst_rcvd:3>-08 <eor>
<call:6>JH1XYZ <qso_date:8>20230602 <time_on:6>012000 <band:3>40m <mode:3>FT8 <rst_sent:3>-12 <rst_rcvd:3>-10 <eor>
"""

SAMPLE_LOG_2 = """<created_timestamp:15>20210101 000000 <programid:6>WSJT-X <eoh>
<call:6>JH1XYZ <qso_date:8>20230602 <time_on:6>012000 <band:3>40m <mode:3>FT8 <rst_sent:3>-12 <rst_rcvd:3>-10 <comment:7>QSO OK! <eor>
<call:6>VK2XXX <qso_date:8>20230530 <time_on:6>220000 <band:3>15m <mode:3>FT8 <rst_sent:3>-15 <rst_rcvd:3>-14 <eor>
"""

class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.file1 = os.path.join(self.test_dir, "wsjtx_1.adi")
        self.file2 = os.path.join(self.test_dir, "wsjtx_2.adi")

        with open(self.file1, "w", encoding="utf-8") as f:
            f.write(SAMPLE_LOG_1)
        with open(self.file2, "w", encoding="utf-8") as f:
            f.write(SAMPLE_LOG_2)

        self.script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "merge_wsjtx_log.py")
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_dry_run(self):
        cmd = [sys.executable, self.script_path, "--dry-run", self.file1, self.file2]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Total records fetched : 4", res.stdout)
        self.assertIn("Duplicates eliminated : 1", res.stdout)
        self.assertIn("Final unique records  : 3", res.stdout)
        self.assertIn("[DRY-RUN]", res.stdout)

        # Ensure original files are untouched
        with open(self.file1, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), SAMPLE_LOG_1)

    def test_actual_merge_and_backup(self):
        cmd = [sys.executable, self.script_path, self.file1, self.file2]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("All targets synchronized successfully!", res.stdout)

        # Check backups exist
        bak1 = glob.glob(f"{self.file1}.bak_*")
        bak2 = glob.glob(f"{self.file2}.bak_*")
        self.assertEqual(len(bak1), 1)
        self.assertEqual(len(bak2), 1)

        # Check merged content
        with open(self.file1, "r", encoding="utf-8") as f:
            content1 = f.read()
        with open(self.file2, "r", encoding="utf-8") as f:
            content2 = f.read()

        # Both files should now be identical and contain 3 records
        self.assertEqual(content1, content2)
        self.assertIn("<created_timestamp:15>20210101 000000", content1) # Oldest header
        self.assertIn("<call:6>VK2XXX", content1) # 20230530
        self.assertIn("<call:4>W1AW", content1)   # 20230601
        self.assertIn("<call:6>JH1XYZ", content1) # 20230602
        self.assertIn("<comment:7>QSO OK!", content1) # Merged comment from duplicate

        # Check sorted order: VK2XXX (0530) -> W1AW (0601) -> JH1XYZ (0602)
        idx_vk = content1.find("VK2XXX")
        idx_w1 = content1.find("W1AW")
        idx_jh = content1.find("JH1XYZ")
        self.assertTrue(idx_vk < idx_w1 < idx_jh)

if __name__ == "__main__":
    unittest.main()
