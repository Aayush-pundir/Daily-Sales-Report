import unittest
from datetime import date
from dsr import uploads

CSV = b"""Estimate Date,Estimate Number,Customer Name,Subtotal,SM,Category,Month
2026-10-13, EST 1 ,Alpha,"1,00,000",Asha & Rohan,Annual fees,
13/10/2026,EST 1,Alpha,5000,Asha & Rohan,setup fees,Sep-26
12-10-2026,EST-2,Beta,0,Asha,Annual fees,
2026-10-12,EST-3,Gamma,10,Zed,Annual fees,
2026-10-12,OLD,Delta,10,Asha,Annual fees,
"""

class Parse(unittest.TestCase):
    def test_parse(self):
        rows = uploads.parse("a.csv", CSV, {"Asha", "Rohan"}, date(2026, 10, 13), None, {"OLD"})
        by = {r["number"]: r for r in rows}
        self.assertTrue(by["EST1"]["ok"]); self.assertEqual(by["EST1"]["total"], 105000)
        self.assertEqual(by["EST1"]["clean"]["owners"], "Asha|Rohan")   # order kept: Asha is primary
        self.assertFalse(by["EST-2"]["ok"]); self.assertFalse(by["EST-3"]["ok"]); self.assertEqual(by["OLD"]["errors"], ["Already exists."])

    def test_sales_user_must_be_on_the_estimate(self):
        r = uploads.parse("a.csv", CSV, {"Asha", "Rohan"}, date(2026, 10, 13), "Rohan", set())
        self.assertTrue({x["number"]: x for x in r}["EST1"]["ok"])
        self.assertFalse({x["number"]: x for x in r}["OLD"]["ok"])

    def test_missing_columns(self):
        with self.assertRaises(ValueError): uploads.parse("a.csv", b"a,b\n1,2\n", set(), date(2026, 10, 13), None, set())

class FreshInstall(unittest.TestCase):
    def test_database_folder_is_created(self):
        import os, tempfile
        from dsr import db
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "does", "not", "exist", "x.sqlite3")
            db.connect(p).close()
            self.assertTrue(os.path.isfile(p))

if __name__ == "__main__": unittest.main()
