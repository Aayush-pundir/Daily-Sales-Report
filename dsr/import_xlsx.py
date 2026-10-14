"""One-time import of the legacy 'Revenue' workbook.

    python3 -m dsr.import_xlsx Revenue.xlsx --as-of 2026-10-13

Reads the three data sheets (Current Month, Previous Month, Dropped till last Month);
every summary/report sheet is recomputed by the app. The legacy 'Reporting' sheet is the reference the app
reproduces; the 'Summary' sheet is ignored. The
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
    return "|".join(dict.fromkeys(n for n in names if n))  # keep order: first = primary


def period(v):
    if isinstance(v, datetime): return v.strftime("%Y-%m")
    try: return datetime.strptime(str(v).strip(), "%b-%y").strftime("%Y-%m")
    except ValueError: return None


def read(ws, first_row, cols, status_override=None):
    for r in ws.iter_rows(min_row=first_row, values_only=True):
        if not r[cols["number"]] or not r[cols["amount"]]: continue
        yield {"est_date": d(r[0]), "number": rules.norm_number(r[cols["number"]]), "status": status_override or str(r[2]).strip().lower(),
               "customer": rules.norm_name(r[3]), "amount": float(r[4]), "owners": owners_of(r[5]),
               "period": period(r[6]) if cols.get("per") else None,
               "category": rules.norm_category(r[cols["cat"]]) if cols["cat"] is not None and r[cols["cat"]] else None}


def valid_date(s):
    try: return date.fromisoformat(s).isoformat()
    except ValueError: raise argparse.ArgumentTypeError(f"'{s}' is not a date. Use YYYY-MM-DD, for example 2026-10-13 (check there is nothing typed after the day).")


def run(path, as_of, dbpath=None, reset=False):
    wb = openpyxl.load_workbook(path, data_only=True)
    c = db.connect(dbpath)
    if c.execute("SELECT 1 FROM estimates LIMIT 1").fetchone():
        if not reset:
            raise SystemExit("This database already contains estimates, so the import was not run.\n"
                             "To throw those estimates away and load the workbook again, add --reset to the command\n"
                             "(users and sales managers are kept; estimates, follow-ups, change requests and attachments are removed).")
        for t in ("followups", "change_requests", "files", "lines", "audit", "notifications", "estimates"):
            c.execute(f"DELETE FROM {t}")
        c.commit(); print("Removed the existing estimates.")
    recs, notes = [], []
    cur = dict(number=1, amount=4, cat=6)
    for r in read(wb["Current Month"], 2, cur): r["src"] = "cur"; recs.append(r)
    for r in read(wb["Previous Month"], 2, dict(number=1, amount=4, cat=7, per=True)): r["src"] = "prev"; recs.append(r)
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
        c.execute("INSERT INTO estimates(number,est_date,period,customer,owners,status,closed_on,closed_approx,invoice_no,notes,created_by,created_at,updated_at)"
                  " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (num, h["est_date"], h["period"] or h["est_date"][:7], h["customer"], h["owners"], status, closed, int(status != "pending"),
                   "(legacy)" if status == "received" else None,
                   "Imported from legacy workbook." + (" Drop date not recorded." if h["src"] == "old" else ""),
                   "import", db.now(), db.now()))
        eid = c.execute("SELECT id FROM estimates WHERE number=?", (num,)).fetchone()[0]
        db.save_lines(c, eid, [{"category": k, "amount": v} for k, v in e["lines"].items()])
        db.log(c, eid, "import", "imported", status)
    c.commit()
    print(f"Imported {len(by)} estimates ({len(recs)} rows).")
    for n in notes: print("  note:", n)


if __name__ == "__main__":
    a = argparse.ArgumentParser(description="One-time import of the legacy Revenue workbook.")
    a.add_argument("xlsx", help="path to the Excel file")
    a.add_argument("--as-of", type=valid_date, default=date.today().isoformat(), help="date of the report, YYYY-MM-DD (already-paid/dropped rows are dated this day)")
    a.add_argument("--reset", action="store_true", help="remove existing estimates first, then import")
    a.add_argument("--db"); x = a.parse_args(); run(x.xlsx, x.as_of, x.db, x.reset)
