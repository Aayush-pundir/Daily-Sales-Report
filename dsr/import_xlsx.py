"""One-time import of the legacy 'Revenue' workbook.

    python3 -m dsr.import_xlsx Revenue.xlsx --as-of 2026-10-13

Reads the three data sheets (Current Month, Previous Month, Dropped till last Month);
every summary/report sheet is recomputed by the app and is not imported. The
'Customisation' sheet is skipped: its rows are already in 'Previous Month'.
"""
import argparse
from datetime import date, datetime

import openpyxl

from . import db, rules

ALIASES = {"Arshdeep Singh": "Arshdeep"}


def d(v):
    if isinstance(v, datetime): return v.date().isoformat()
    return None


def owners_of(s):
    names = [ALIASES.get(rules.norm_name(p), rules.norm_name(p)) for p in str(s or "").split("&")]
    return "|".join(sorted({n for n in names if n}))


def read(ws, first_row, cols, status_override=None):
    for r in ws.iter_rows(min_row=first_row, values_only=True):
        if not r[cols["number"]] or not r[cols["amount"]]: continue
        yield {"est_date": d(r[0]), "number": rules.norm_number(r[cols["number"]]), "status": status_override or str(r[2]).strip().lower(),
               "customer": rules.norm_name(r[3]), "amount": float(r[4]), "owners": owners_of(r[5]),
               "category": rules.norm_category(r[cols["cat"]]) if cols["cat"] is not None and r[cols["cat"]] else None}


def run(path, as_of, dbpath=None):
    wb = openpyxl.load_workbook(path, data_only=True)
    c = db.connect(dbpath)
    recs, notes = [], []
    cur = dict(number=1, amount=4, cat=6)
    for r in read(wb["Current Month"], 2, cur): r["src"] = "cur"; recs.append(r)
    for r in read(wb["Previous Month"], 2, dict(number=1, amount=4, cat=7)): r["src"] = "prev"; recs.append(r)
    for r in read(wb["Dropped till last Month"], 3, dict(number=1, amount=4, cat=7), "dropped"): r["src"] = "old"; recs.append(r)

    by, blank = {}, set()
    for r in recs:
        e = by.setdefault(r["number"], {"hdr": r, "lines": {}})
        if (e["hdr"]["customer"], e["hdr"]["est_date"], e["hdr"]["status"]) != (r["customer"], r["est_date"], r["status"]):
            notes.append(f'{r["number"]}: rows disagree on customer/date/status; kept the first.')
        cat = r["category"] or "Set-up fees"
        if not r["category"]: blank.add(r["number"])
        e["lines"][cat] = e["lines"].get(cat, 0) + r["amount"]

    if blank: notes.append(f'{len(blank)} dropped estimates had no category in the legacy sheet; set to Set-up fees.')
    for n in sorted({n for e in by.values() for n in e["hdr"]["owners"].split("|")}):
        c.execute("INSERT OR IGNORE INTO sms(name,active) VALUES(?,?)", (n, 0 if n == "Martin" else 1))
    for num, e in by.items():
        h = e["hdr"]; status = h["status"]
        closed = None if status == "pending" else (as_of if h["src"] != "old" else "2026-09-30")
        c.execute("INSERT INTO estimates(number,est_date,customer,owners,status,closed_on,closed_approx,invoice_no,notes,created_by,created_at,updated_at)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (num, h["est_date"], h["customer"], h["owners"], status, closed, int(status != "pending"),
                   "(legacy)" if status == "received" else None,
                   "Imported from legacy workbook." + (" Drop date not recorded." if h["src"] == "old" else ""),
                   "import", db.now(), db.now()))
        eid = c.execute("SELECT id FROM estimates WHERE number=?", (num,)).fetchone()[0]
        db.save_lines(c, eid, [{"category": k, "amount": v} for k, v in e["lines"].items()])
        db.log(c, eid, "import", "imported", status)
    # Monthly targets / legacy actuals from the hidden Summary table (R4:T8). The Aug 'actual' there is a
    # live formula that tracks the current month, so only fixed numbers (Apr-Jul) are kept as history.
    s = wb["Summary"]
    for row in range(4, 9):
        m, tgt, act = s.cell(row, 18).value, s.cell(row, 19).value, s.cell(row, 20).value
        if isinstance(m, datetime) and tgt:
            c.execute("INSERT OR REPLACE INTO targets VALUES(?,?,?,?)", (m.strftime("%Y-%m"), int(tgt), None, int(act) if act and m.month < 8 else None))
    c.commit()
    print(f"Imported {len(by)} estimates ({len(recs)} rows).")
    for n in notes: print("  note:", n)


if __name__ == "__main__":
    a = argparse.ArgumentParser(); a.add_argument("xlsx"); a.add_argument("--as-of", default=date.today().isoformat())
    a.add_argument("--db"); x = a.parse_args(); run(x.xlsx, x.as_of, x.db)
