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
        r = rules.build_report(self.E, "2026-10", date(2026, 10, 13))["total"]
        self.assertEqual((r["opening"], r["new"], r["converted"], r["dropped"], r["closing"]), (1700, 450, 550, 200, 1400))
        self.assertEqual(r["opening"] + r["new"] - r["converted"] - r["dropped"], r["closing"])

    def test_as_on_in_past_reopens_later_closures(self):
        r = rules.build_report(self.E, "2026-10", date(2026, 10, 3))["total"]
        self.assertEqual(r["converted"], 500)  # only the 3 Oct conversion had happened

    def test_period_differs_from_date(self):
        e = est("late-filed", "2026-10-08", "A"); e["period"] = "2026-09"
        t = rules.build_report([e], "2026-10", date(2026, 10, 13))["total"]
        self.assertEqual((t["opening"], t["new"], t["closing"]), (100, 0, 100))

    def test_split_credit(self):
        e = [est("j", "2026-10-01", "A|B", lines=(("Annual fees", 100),))]
        r = rules.build_report(e, "2026-10", date(2026, 10, 13), credit="split")
        self.assertEqual({t["team"]: t["new"] for t in r["teams"]}, {"A": 50, "B": 50})

    def test_primary_order_is_kept(self):
        e = [est("1", "2026-10-01", "A|B"), est("2", "2026-10-01", "B|A")]
        r = rules.build_report(e, "2026-10", date(2026, 10, 13))
        self.assertEqual(sorted(t["team"] for t in r["teams"]), ["A & B", "B & A"])
        p = rules.build_report(e, "2026-10", date(2026, 10, 13), credit="primary")
        self.assertEqual({t["team"]: t["new"] for t in p["teams"]}, {"A": 100, "B": 100})

    def test_buckets(self):
        self.assertEqual([rules.bucket(n) for n in (0, 30, 31, 60, 61, 90, 91)], ["0-30", "0-30", "31-60", "31-60", "61-90", "61-90", "90+"])

class DrillMatchesReport(unittest.TestCase):
    """Every number on the dashboard must equal the sum of the estimates its drill-down lists."""
    def data(self):
        E = []
        def add(n, d, owners, status="pending", closed=None, per=None, lines=(("Annual fees", 100),)):
            e = est(n, d, owners, status, closed, lines); e["id"] = len(E) + 1; e["period"] = per or d[:7]; E.append(e)
        add("a1", "2026-06-10", "A"); add("a2", "2026-08-05", "A|B", "received", "2026-10-03", lines=(("Annual fees", 70), ("Set-up fees", 30)))
        add("a3", "2026-09-20", "B|A"); add("a4", "2026-07-01", "B", "dropped", "2026-10-09"); add("a5", "2026-10-02", "A"); add("a6", "2026-10-04", "C|A|B", "received", "2026-10-11")
        add("a7", "2026-10-08", "B", per="2026-09"); add("a8", "2026-04-01", "A", "dropped", "2026-09-30"); add("a9", "2026-10-12", "A|B", per="2026-10", lines=(("Integration", 55),))
        return E

    def test_every_cell(self):
        E = self.data()
        for month, as_on in (("2026-10", date(2026, 10, 13)), ("2026-10", date(2026, 10, 5)), ("2026-09", date(2026, 10, 13))):
            for credit in ("team", "primary", "split"):
                rep = rules.build_report(E, month, as_on, credit)
                rows = [(None, rep["total"])] + [(t["team"] if credit != "team" else "|".join(t["team"].split(" & ")), t) for t in rep["teams"]]
                for key, cell in rows:
                    for m in rules.METRICS:
                        got = rules.drill(E, month, as_on, credit, key, m)
                        self.assertAlmostEqual(sum(r["counted"] for r in got), cell[m], msg=f"{credit} {month} {as_on} {key} {m}")
                        self.assertAlmostEqual(sum(r["share"] for r in got), cell[m + "_n"], msg=f"count {credit} {key} {m}")
                    for b in rules.BUCKETS:
                        got = rules.drill(E, month, as_on, credit, key, "closing", b)
                        self.assertAlmostEqual(sum(r["counted"] for r in got), cell["ageing"][b], msg=f"age {credit} {key} {b}")

class Followups(unittest.TestCase):
    T = date(2026, 10, 13)
    def fu(self, on, nxt=None, i=1): return {"id": i, "on_date": on, "next_date": nxt}

    def test_flags(self):
        f = lambda l: rules.followup_flag(40, l, self.T)
        self.assertEqual(f([]), "none")
        self.assertEqual(f([self.fu("2026-10-10")]), "ok")                         # 3 days ago, no next date
        self.assertEqual(f([self.fu("2026-10-01")]), "overdue")                    # 12 days ago, no next date
        self.assertEqual(f([self.fu("2026-09-01", "2026-10-20")]), "ok")           # promised date still ahead
        self.assertEqual(f([self.fu("2026-09-01", "2026-10-12")]), "overdue")      # promised date passed
        self.assertEqual(f([self.fu("2026-09-01", "2026-10-12", 1), self.fu("2026-10-12", None, 2)]), "ok")  # newer one supersedes

    def test_validate(self):
        _, errs = rules.validate_followup({"on_date": "2026-10-20", "kind": "Fax", "note": "x"}, "2026-08-01", self.T)
        self.assertEqual(len(errs), 3)
        c, errs = rules.validate_followup({"on_date": "2026-10-12", "kind": "Call", "note": "Spoke to AP team", "next_date": "2026-10-20"}, "2026-08-01", self.T)
        self.assertEqual((errs, c["next_date"]), ([], "2026-10-20"))

class ChangeDiff(unittest.TestCase):
    E = {"number": "EST-1", "est_date": "2026-10-01", "period": "2026-10", "customer": "Acme", "owners": "A|B", "notes": "",
         "lines": [{"category": "Annual fees", "amount": 250000.0}]}

    def clean(self, **kw):
        c = {"number": "EST-1", "est_date": "2026-10-01", "period": "2026-10", "customer": "Acme", "owners": "A|B", "notes": "",
             "lines": [{"category": "Annual fees", "amount": 250000.0}]}
        c.update(kw); return c

    def test_no_change(self):
        self.assertEqual(rules.diff_estimate(self.E, self.clean()), {})

    def test_diff_and_text(self):
        d = rules.diff_estimate(self.E, self.clean(owners="B|A", lines=[{"category": "Annual fees", "amount": 260000.0}]))
        self.assertEqual(set(d), {"owners", "lines"})                      # order of owners matters: the first is the primary

        self.assertIn("₹2,50,000 → ₹2,60,000", rules.describe_diff(d))

    def test_indian_grouping(self):
        self.assertEqual([rules.inr(n) for n in (999, 1000, 100000, 12345678)], ["999", "1,000", "1,00,000", "1,23,45,678"])

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
