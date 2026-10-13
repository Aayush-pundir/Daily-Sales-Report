"""Bulk estimate upload (CSV / XLSX) and per-estimate document attachments."""
import csv, io, re
from datetime import date, datetime

from . import rules

HEAD = {"date": ("estimate date", "date"), "number": ("estimate number", "estimate no", "number"),
        "customer": ("customer name", "customer"), "amount": ("subtotal", "amount", "sub total"),
        "sm": ("sm", "sales manager", "salesperson", "owner"), "category": ("category", "catrgory", "fee type", "fee"),
        "period": ("month", "report month")}
TEMPLATE = "Estimate Date,Estimate Number,Customer Name,Subtotal,SM,Category,Report Month\n2026-10-13,EST-26-27/999,Example Pvt Ltd,50000,Arshdeep & Meisheil,Annual fees,2026-10\n"
MAX_BYTES = 10 * 1024 * 1024
FILE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".xlsx": "application/octet-stream", ".csv": "text/csv"}


def _date(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    s = str(v or "").strip()
    for f in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%d-%b-%y"):
        try: return datetime.strptime(s, f).date()
        except ValueError: pass
    return None


def _period(v):
    if isinstance(v, (datetime, date)): return v.strftime("%Y-%m")
    s = str(v or "").strip()
    for f in ("%Y-%m", "%b-%y", "%b %Y", "%B %Y"):
        try: return datetime.strptime(s, f).strftime("%Y-%m")
        except ValueError: pass
    return ""


def read_rows(filename, data):
    """-> list of lists (header first). XLSX needs the optional openpyxl package."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        try: import openpyxl
        except ImportError: raise ValueError("Excel upload needs 'pip install openpyxl' on the server; save as CSV instead.")
        ws = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True).worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.reader(io.StringIO(text)))


def parse(filename, data, sm_names, today, allowed_owner, existing_numbers):
    rows = [r for r in read_rows(filename, data) if any(str(c or "").strip() for c in r)]
    if not rows: raise ValueError("The file is empty.")
    head = [re.sub(r"\s+", " ", str(c or "")).strip().lower() for c in rows[0]]
    idx = {k: next((head.index(a) for a in al if a in head), None) for k, al in HEAD.items()}
    missing = [k for k in ("date", "number", "customer", "amount", "sm", "category") if idx[k] is None]
    if missing: raise ValueError("Missing column(s): " + ", ".join(missing) + ". Download the template for the expected headers.")
    est, order = {}, []
    for n, r in enumerate(rows[1:], start=2):
        g = lambda k: r[idx[k]] if idx[k] is not None and idx[k] < len(r) else None
        num = rules.norm_number(g("number"))
        e = est.get(num)
        if e is None:
            d = _date(g("date"))
            owners = [rules.norm_name(p) for p in str(g("sm") or "").split("&")]
            e = est[num] = {"row": n, "raw": {"number": num, "customer": g("customer"), "est_date": d.isoformat() if d else "",
                            "owners": owners, "period": _period(g("period")) or None, "lines": []}, "pre": []}
            if not d: e["pre"].append("Date not understood.")
            order.append(num)
        elif rules.norm_name(g("customer")) != rules.norm_name(e["raw"]["customer"]):
            e["pre"].append(f"Row {n}: same estimate number with a different customer.")
        amt = str(g("amount") or "").replace(",", "").replace("₹", "").strip()
        e["raw"]["lines"].append({"category": g("category"), "amount": amt})
    out = []
    for num in order:
        e = est[num]; clean, errs = rules.validate_estimate(e["raw"], sm_names, today, allowed_owner)
        errs = e["pre"] + [x for x in errs if not (e["pre"] and x.startswith("Estimate date"))]
        if num and num in existing_numbers: errs.append("Already exists.")
        out.append({"row": e["row"], "number": num, "customer": clean.get("customer"), "team": " & ".join(e["raw"]["owners"]),
                    "total": sum(l["amount"] for l in clean["lines"]), "ok": not errs, "errors": errs, "clean": clean if not errs else None})
    return out
