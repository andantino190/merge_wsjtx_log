#!/usr/bin/env python3
import unittest
from adif_handler import (
    ADIFRecord,
    ADIFFile,
    parse_adif,
    select_oldest_header,
    merge_and_deduplicate,
    sort_records,
    build_adif,
)

SAMPLE_ADIF_1 = """WSJT-X ADIF Export<eoh>
<call:5>JA1AA <gridsquare:4>PM95 <mode:3>FT8 <rst_sent:3>-10 <rst_rcvd:3>-05 <qso_date:8>20230501 <time_on:6>100000 <band:3>40m <eor>
<call:5>JA2BB <gridsquare:4>PM85 <mode:3>FT8 <rst_sent:3>-08 <rst_rcvd:3>-02 <qso_date:8>20230501 <time_on:6>120000 <band:3>20m <eor>
"""

SAMPLE_ADIF_2 = """<created_timestamp:15>20220101 000000 <programid:6>WSJT-X <eoh>
<call:5>JA2BB <gridsquare:4>PM85 <mode:3>FT8 <rst_sent:3>-08 <rst_rcvd:3>-02 <qso_date:8>20230501 <time_on:6>120000 <band:3>20m <comment:9>Nice QSO! <eor>
<call:5>JA3CC <gridsquare:4>PM74 <mode:3>FT8 <rst_sent:3>-15 <rst_rcvd:3>-11 <qso_date:8>20230430 <time_on:6>230000 <band:3>15m <eor>
"""

class TestADIFHandler(unittest.TestCase):
    def test_parse_adif(self):
        f = parse_adif(SAMPLE_ADIF_1, mtime=100.0, file_path="host1:path")
        self.assertEqual(len(f.records), 2)
        self.assertIn("WSJT-X ADIF Export", f.header_raw)
        self.assertEqual(f.records[0].get("CALL"), "JA1AA")
        self.assertEqual(f.records[0].get("QSO_DATE"), "20230501")
        self.assertEqual(f.records[0].get("TIME_ON"), "100000")
        self.assertEqual(f.records[0].get("BAND"), "40m")

    def test_header_selection(self):
        f1 = parse_adif(SAMPLE_ADIF_1, mtime=1000.0)
        f2 = parse_adif(SAMPLE_ADIF_2, mtime=2000.0)
        # f2 has created_timestamp 20220101 000000, f1 does not have timestamp
        header = select_oldest_header([f1, f2])
        self.assertIn("<created_timestamp:15>20220101 000000", header)

    def test_deduplication_and_field_merge(self):
        f1 = parse_adif(SAMPLE_ADIF_1)
        f2 = parse_adif(SAMPLE_ADIF_2)
        all_recs = f1.records + f2.records
        self.assertEqual(len(all_recs), 4)

        deduped, dup_count = merge_and_deduplicate(all_recs)
        self.assertEqual(dup_count, 1)
        self.assertEqual(len(deduped), 3)

        # JA2BB should have merged comment
        ja2bb = [r for r in deduped if r.get("CALL") == "JA2BB"][0]
        self.assertEqual(ja2bb.get("COMMENT"), "Nice QSO!")
        self.assertEqual(ja2bb.get("RST_SENT"), "-08")

    def test_sorting(self):
        f1 = parse_adif(SAMPLE_ADIF_1)
        f2 = parse_adif(SAMPLE_ADIF_2)
        all_recs = f1.records + f2.records
        deduped, _ = merge_and_deduplicate(all_recs)
        sorted_recs = sort_records(deduped)

        dates_and_times = [(r.get("QSO_DATE"), r.get("TIME_ON")) for r in sorted_recs]
        expected = [
            ("20230430", "230000"), # JA3CC
            ("20230501", "100000"), # JA1AA
            ("20230501", "120000"), # JA2BB
        ]
        self.assertEqual(dates_and_times, expected)

    def test_build_adif(self):
        f1 = parse_adif(SAMPLE_ADIF_1)
        output = build_adif("Sample Header <eoh>", f1.records)
        self.assertTrue(output.startswith("Sample Header <eoh>"))
        self.assertIn("<call:5>JA1AA", output)
        self.assertIn("<eor>", output)

if __name__ == "__main__":
    unittest.main()
