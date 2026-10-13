"""Business rules for the Daily Sales Report.

Everything the legacy workbook did with SUMIFS over hand-maintained sheets is
derived here from estimate records plus their status-change dates, so any month
or "as on" date can be reported without anyone re-pasting sheets.
"""
import re
from datetime import date, timedelta

CATEGORIES = ["Annual fees", "Set-up fees", "Integration", "Customisation"]
BUCKETS = ["0-30", "31-60", "61-90", "90+"]
STATUSES = ("pending", "received", "dropped")

_CAT_ALIASES = {"annual fees": "Annual fees", "set-up fees": "Set-up fees", "setup fees": "Set-up fees",
                "set up fees": "Set-up fees", "integration": "Integration", "customisation": "Customisation",
                "customization": "Customisation"}


def norm_category(s):
    return _CAT_ALIASES.get(re.sub(r"\s+", " ", str(s or "")).strip().lower())


def norm_number(s):
    return re.sub(r"\s+", "", str(s or ""))


def norm_name(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def bucket(age_days):
    if age_days <= 30: return "0-30"
    if age_days <= 60: return "31-60"
    if age_days <= 90: return "61-90"
    return "90+"


def parse_date(s):
    return date.fromisoformat(s) if s else None


def month_bounds(ym):
    y, m = map(int, ym.split("-"))
    start = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def team_label(owners):
    return " & ".join(owners.split("|"))


def validate_estimate(d, sm_names, today, allowed_owner=None):
    """Return (clean, errors). `d` is the raw JSON from a client."""
    errs, c = [], {}
    c["number"] = norm_number(d.get("number"))
    if not c["number"]: errs.append("Estimate number is required.")
    c["customer"] = norm_name(d.get("customer"))
    if not c["customer"]: errs.append("Customer name is required.")
    try:
        ed = date.fromisoformat(d.get("est_date") or "")
        if ed > today: errs.append("Estimate date cannot be in the future.")
        c["est_date"] = ed.isoformat()
    except ValueError:
        errs.append("Estimate date is required (YYYY-MM-DD).")
    try:
        c["period"] = d.get("period") or c["est_date"][:7]
        py, pm = map(int, c["period"].split("-")); assert 1 <= pm <= 12
        if date(py, pm, 1) > today.replace(day=1): errs.append("Report month cannot be in the future.")
    except KeyError:
        pass  # no valid estimate date; already reported
    except (ValueError, AssertionError):
        errs.append("Report month must be YYYY-MM.")
    owners = list(dict.fromkeys(norm_name(o) for o in d.get("owners") or [] if norm_name(o)))  # first = primary
    if not owners: errs.append("Pick at least one sales manager.")
    if len(owners) > 3: errs.append("At most 3 sales managers per estimate.")
    bad = [o for o in owners if o not in sm_names]
    if bad: errs.append("Unknown sales manager: " + ", ".join(bad))
    if allowed_owner and allowed_owner not in owners:
        errs.append("You can only raise/edit estimates that include you as a sales manager.")
    c["owners"] = "|".join(owners)
    lines, seen = [], set()
    for ln in d.get("lines") or []:
        cat = norm_category(ln.get("category"))
        try: amt = round(float(ln.get("amount")), 2)
        except (TypeError, ValueError): amt = 0
        if not cat: errs.append("Unknown category on a line."); continue
        if amt <= 0: errs.append(f"{cat}: amount must be greater than zero."); continue
        if cat in seen: errs.append(f"{cat} appears twice; combine into one line."); continue
        seen.add(cat); lines.append({"category": cat, "amount": amt})
    if not lines: errs.append("Add at least one fee line.")
    c["lines"] = lines
    c["notes"] = (d.get("notes") or "").strip()[:500]
    return c, errs


def build_report(estimates, targets, month, as_on, credit="team"):
    """estimates: dicts with number, est_date, owners, status, closed_on, lines[{category, amount}].
    Roll-forward per workbook: Opening + New - Converted - Dropped = Closing (pending)."""
    start, mend = month_bounds(month)
    end = min(mend, as_on)
    zero = lambda: {"opening": 0.0, "new": 0.0, "converted": 0.0, "dropped": 0.0, "closing": 0.0,
                    "opening_n": 0.0, "new_n": 0.0, "converted_n": 0.0, "dropped_n": 0.0, "closing_n": 0.0,
                    "ageing": {b: 0.0 for b in BUCKETS}}
    teams, total = {}, zero()
    seg = {k: {c: 0.0 for c in CATEGORIES} for k in ("opening", "new", "converted", "dropped", "closing")}
    ageing_seg = {b: {c: 0.0 for c in CATEGORIES} for b in BUCKETS}
    ageing_n = {b: 0 for b in BUCKETS}
    top_pending = []
    for e in estimates:
        ed = parse_date(e["est_date"])
        cl = parse_date(e["closed_on"]) if e["status"] != "pending" else None
        amount = sum(l["amount"] for l in e["lines"])
        names = e["owners"].split("|")   # first name is the primary salesperson
        keys = {"team": [e["owners"]], "primary": names[:1], "split": names}[credit]
        w = 1 / len(keys) if credit == "split" else 1
        events = []
        # An estimate belongs to the report month (`period`) it was booked in; that can differ from
        # its date (e.g. raised on 8 Oct but filed under September), as in the legacy Reporting sheet.
        per = e["period"] or e["est_date"][:7]
        if per > month: continue
        if per < month and (cl is None or cl >= start): events.append("opening")
        if per == month: events.append("new")
        if cl and start <= cl <= end: events.append("converted" if e["status"] == "received" else "dropped")
        if cl is None or cl > end: events.append("closing")
        if not events: continue
        for ev in events:
            for k in keys:
                for target in (teams.setdefault(k, zero()), total):
                    target[ev] += amount * w; target[ev + "_n"] += w
            for l in e["lines"]: seg[ev][l["category"]] += l["amount"]
        if "closing" in events:
            b = bucket((end - ed).days)
            ageing_n[b] += 1
            for k in keys:
                for target in (teams[k], total): target["ageing"][b] += amount * w
            for l in e["lines"]: ageing_seg[b][l["category"]] += l["amount"]
            top_pending.append({"number": e["number"], "customer": e["customer"], "owners": e["owners"],
                                "amount": amount, "age": (end - ed).days, "bucket": b})
    top_pending.sort(key=lambda r: -r["age"] * 0 - r["amount"])
    # Monthly conversions (count) vs target: 7 months ending at the selected one.
    first_conv = min((parse_date(e["closed_on"]) for e in estimates if e["status"] == "received" and e["closed_on"]), default=None)
    trend, y, m = [], start.year, start.month
    months = []
    for i in range(6, -1, -1):
        mm = m - i; yy = y
        while mm < 1: mm += 12; yy -= 1
        months.append(f"{yy:04d}-{mm:02d}")
    for ym in months:
        s, e_ = month_bounds(ym)
        n = sum(1 for e in estimates if e["status"] == "received" and e["closed_on"] and s <= parse_date(e["closed_on"]) <= e_)
        amt = sum(sum(l["amount"] for l in e["lines"]) for e in estimates
                  if e["status"] == "received" and e["closed_on"] and s <= parse_date(e["closed_on"]) <= e_)
        t = targets.get(ym, {})
        legacy = t.get("legacy_actual")
        no_data = n == 0 and legacy is None and (first_conv is None or e_ < first_conv.replace(day=1))
        trend.append({"month": ym, "actual": None if no_data else (n if (n or legacy is None) else legacy), "actual_amount": amt,
                      "target": t.get("target_count"), "target_amount": t.get("target_amount"),
                      "from_legacy": bool(legacy is not None and not n)})
    rows = [{"team": team_label(k) if credit == "team" else k, **v} for k, v in teams.items()]
    rows.sort(key=lambda r: -r["closing"])
    return {"month": month, "as_on": end.isoformat(), "credit": credit, "total": total, "teams": rows,
            "segments": seg, "ageing_segments": ageing_seg, "ageing_count": ageing_n,
            "trend": trend, "pending_by_value": sorted(top_pending, key=lambda r: -r["amount"])[:10]}
