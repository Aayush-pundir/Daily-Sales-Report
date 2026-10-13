import unittest
from datetime import date
from dsr import uploads

CSV = b"""Estimate Date,Estimate Number,Customer Name,Subtotal,SM,Category,Month
2026-10-13, EST 1 ,Alpha,"1,00,000",Arshdeep & Meisheil,Annual fees,
13/10/2026,EST 1,Alpha,5000,Arshdeep & Meisheil,setup fees,Sep-26
12-10-2026,EST-2,Beta,0,Arshdeep,Annual fees,
2026-10-12,EST-3,Gamma,10,Zed,Annual fees,
2026-10-12,OLD,Delta,10,Arshdeep,Annual fees,
"""

class Parse(unittest.TestCase):
    def test_parse(self):
        rows = uploads.parse("a.csv", CSV, {"Arshdeep", "Meisheil"}, date(2026, 10, 13), None, {"OLD"})
        by = {r["number"]: r for r in rows}
        self.assertTrue(by["EST1"]["ok"]); self.assertEqual(by["EST1"]["total"], 105000)
        self.assertEqual(by["EST1"]["clean"]["owners"], "Arshdeep|Meisheil")   # order kept: Arshdeep is primary
        self.assertFalse(by["EST-2"]["ok"]); self.assertFalse(by["EST-3"]["ok"]); self.assertEqual(by["OLD"]["errors"], ["Already exists."])

    def test_sales_user_must_be_on_the_estimate(self):
        r = uploads.parse("a.csv", CSV, {"Arshdeep", "Meisheil"}, date(2026, 10, 13), "Meisheil", set())
        self.assertTrue({x["number"]: x for x in r}["EST1"]["ok"])
        self.assertFalse({x["number"]: x for x in r}["OLD"]["ok"])

    def test_missing_columns(self):
        with self.assertRaises(ValueError): uploads.parse("a.csv", b"a,b\n1,2\n", set(), date(2026, 10, 13), None, set())

if __name__ == "__main__": unittest.main()
