import unittest
from datetime import date
from dsr import rules

def est(n, d, owners, status="pending", closed=None, lines=(("Annual fees", 100),)):
    return {"number": n, "customer": n, "est_date": d, "owners": owners, "period": d[:7], "status": status, "closed_on": closed,
            "lines": [{"category": c, "amount": a} for c, a in lines]}

class Rollforward(unittest.TestCase):
    def setUp(self):
        self.E = [est("old-open", "2026-08-01", "A", lines=(("Annual fees", 1000),)),
                  est("old-conv", "2026-08-05", "A", "received", "2026-10-03", (("Set-up fees", 500),)),
                  est("old-drop", "2026-07-05", "B", "dropped", "2026-10-04", (("Set-up fees", 200),)),
                  est("closed-before", "2026-07-05", "B", "dropped", "2026-09-30"),
                  est("new-open", "2026-10-02", "A", lines=(("Annual fees", 300),)),
                  est("new-conv", "2026-10-02", "B", "received", "2026-10-10", (("Annual fees", 50),)),
                  est("future-close", "2026-10-02", "B", "received", "2026-10-20")]

    def test_identity(self):
        r = rules.build_report(self.E, {}, "2026-10", date(2026, 10, 13))["total"]
        self.assertEqual((r["opening"], r["new"], r["converted"], r["dropped"], r["closing"]), (1700, 450, 550, 200, 1400))
        self.assertEqual(r["opening"] + r["new"] - r["converted"] - r["dropped"], r["closing"])

    def test_as_on_in_past_reopens_later_closures(self):
        r = rules.build_report(self.E, {}, "2026-10", date(2026, 10, 3))["total"]
        self.assertEqual(r["converted"], 500)  # only the 3 Oct conversion had happened

    def test_period_differs_from_date(self):
        e = est("late-filed", "2026-10-08", "A"); e["period"] = "2026-09"
        t = rules.build_report([e], {}, "2026-10", date(2026, 10, 13))["total"]
        self.assertEqual((t["opening"], t["new"], t["closing"]), (100, 0, 100))

    def test_split_credit(self):
        e = [est("j", "2026-10-01", "A|B", lines=(("Annual fees", 100),))]
        r = rules.build_report(e, {}, "2026-10", date(2026, 10, 13), credit="split")
        self.assertEqual({t["team"]: t["new"] for t in r["teams"]}, {"A": 50, "B": 50})

    def test_primary_order_is_kept(self):
        e = [est("1", "2026-10-01", "A|B"), est("2", "2026-10-01", "B|A")]
        r = rules.build_report(e, {}, "2026-10", date(2026, 10, 13))
        self.assertEqual(sorted(t["team"] for t in r["teams"]), ["A & B", "B & A"])
        p = rules.build_report(e, {}, "2026-10", date(2026, 10, 13), credit="primary")
        self.assertEqual({t["team"]: t["new"] for t in p["teams"]}, {"A": 100, "B": 100})

    def test_buckets(self):
        self.assertEqual([rules.bucket(n) for n in (0, 30, 31, 60, 61, 90, 91)], ["0-30", "0-30", "31-60", "31-60", "61-90", "61-90", "90+"])

class Validation(unittest.TestCase):
    def test_rules(self):
        _, errs = rules.validate_estimate({"number": " EST 1 ", "est_date": "2999-01-01", "customer": "", "owners": ["Zed"],
            "lines": [{"category": "Annual fees", "amount": 0}]}, {"A"}, date(2026, 10, 13))
        self.assertTrue(len(errs) >= 4)
        c, errs = rules.validate_estimate({"number": " EST 1 ", "est_date": "2026-10-01", "customer": " X  Y ", "owners": ["A"],
            "lines": [{"category": "setup fees", "amount": "10"}]}, {"A"}, date(2026, 10, 13))
        self.assertEqual((errs, c["number"], c["customer"], c["lines"][0]["category"]), ([], "EST1", "X Y", "Set-up fees"))

if __name__ == "__main__":
    unittest.main()
