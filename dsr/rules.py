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
FOLLOWUP_KINDS = ["Call", "Email", "WhatsApp", "Meeting", "Other"]
TRACK_AFTER_DAYS = 30        # pending estimates older than this are tracked on the follow-up board
FOLLOWUP_EVERY_DAYS = 7      # with no "next follow-up" date set, a follow-up is due this many days after the last one

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


def followup_flag(age, followups, today):
    """none = never followed up, overdue = the promised next date has passed (or the last one is over a week old
    with no next date), ok = otherwise."""
    if not followups: return "none"
    last = max(f["on_date"] for f in followups)
    latest_next = next((f["next_date"] for f in sorted(followups, key=lambda f: (f["on_date"], f["id"]), reverse=True)), None)
    if latest_next: return "overdue" if latest_next < today.isoformat() else "ok"
    return "overdue" if (today - date.fromisoformat(last)).days > FOLLOWUP_EVERY_DAYS else "ok"


def validate_followup(d, est_date, today):
    errs, c = [], {}
    try:
        on = date.fromisoformat(d.get("on_date") or today.isoformat())
        if on > today: errs.append("Follow-up date can't be in the future.")
        if on < date.fromisoformat(est_date): errs.append("Follow-up can't be before the estimate date.")
        c["on_date"] = on.isoformat()
    except ValueError: errs.append("Follow-up date is required.")
    c["kind"] = d.get("kind") if d.get("kind") in FOLLOWUP_KINDS else None
    if not c["kind"]: errs.append("Pick how you followed up (call, email, ...).")
    c["note"] = (d.get("note") or "").strip()[:1000]
    if len(c["note"]) < 5: errs.append("Write what was discussed (min 5 characters).")
    c["contact"] = norm_name(d.get("contact"))[:120]
    nd = d.get("next_date")
    if nd:
        try:
            n = date.fromisoformat(nd)
            if "on_date" in c and n < date.fromisoformat(c["on_date"]): errs.append("Next follow-up can't be before this one.")
            c["next_date"] = n.isoformat()
        except ValueError: errs.append("Next follow-up date is not a valid date.")
    c.setdefault("next_date", None)
    return c, errs


DIFF_FIELDS = ("number", "est_date", "period", "customer", "owners", "notes", "lines")


def current_values(e):
    return {"number": e["number"], "est_date": e["est_date"], "period": e["period"] or e["est_date"][:7], "customer": e["customer"],
            "owners": e["owners"].split("|") if e["owners"] else [], "notes": e["notes"] or "",
            "lines": [{"category": l["category"], "amount": l["amount"]} for l in e["lines"]]}


def _norm(field, v):
    if field == "lines": return sorted([l["category"], round(float(l["amount"]), 2)] for l in v)
    if field == "owners": return list(v) if isinstance(v, list) else (v.split("|") if v else [])
    return v


def diff_estimate(e, clean):
    """Field-level changes between the stored estimate `e` and the validated proposal `clean`."""
    cur = current_values(e)
    new = {**clean, "owners": clean["owners"].split("|") if clean["owners"] else [], "lines": clean["lines"]}
    return {f: {"old": _norm(f, cur[f]), "new": _norm(f, new[f])} for f in DIFF_FIELDS if _norm(f, cur[f]) != _norm(f, new[f])}


def inr(n):
    s, neg = f"{abs(round(n)):d}", n < 0
    head, tail = (s[:-3], s[-3:]) if len(s) > 3 else ("", s)
    groups = []
    while len(head) > 2: groups.insert(0, head[-2:]); head = head[:-2]
    if head: groups.insert(0, head)
    return ("-" if neg else "") + ",".join(groups + [tail])


def describe_diff(changes):
    label = {"number": "estimate number", "est_date": "estimate date", "period": "report month", "customer": "customer", "owners": "sales manager", "notes": "notes", "lines": "fees"}
    out = []
    for f, ch in changes.items():
        if f == "lines":
            o, n = sum(a for _, a in ch["old"]), sum(a for _, a in ch["new"])
            out.append(f"fees ₹{inr(o)} → ₹{inr(n)}")
        elif f == "owners": out.append("sales manager " + " & ".join(ch["old"]) + " → " + " & ".join(ch["new"]))
        elif f == "notes": out.append("notes")
        else: out.append(f"{label[f]} {ch['old']} → {ch['new']}")
    return "; ".join(out)


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


def estimate_events(e, month, start, end):
    """Which dashboard columns an estimate falls into for `month`, as of `end`.
    An estimate belongs to the report month (`period`) it was booked in; that can differ from its date
    (e.g. raised on 8 Oct but filed under September), as in the legacy Reporting sheet."""
    per = e["period"] or e["est_date"][:7]
    if per > month: return []
    cl = parse_date(e["closed_on"]) if e["status"] != "pending" else None
    ev = []
    if per < month and (cl is None or cl >= start): ev.append("opening")
    if per == month: ev.append("new")
    if cl and start <= cl <= end: ev.append("converted" if e["status"] == "received" else "dropped")
    if cl is None or cl > end: ev.append("closing")
    return ev


def credit_keys(e, credit):
    """Rows an estimate counts towards, and the share each gets. The first name is the primary salesperson."""
    names = e["owners"].split("|")
    keys = {"team": [e["owners"]], "primary": names[:1], "split": names}[credit]
    return keys, (1 / len(keys) if credit == "split" else 1)


METRICS = ("opening", "new", "converted", "dropped", "closing")


def drill(estimates, month, as_on, credit, key, metric, age_bucket=None, category=None):
    """The estimates behind one number on the dashboard (same rules as build_report, so the list always adds up to it).
    key=None means all sales managers; age_bucket narrows 'closing' to one ageing column; category narrows to one fee
    type (then `counted` is just that fee type's lines, as in the fee-type tables)."""
    start, mend = month_bounds(month)
    end = min(mend, as_on)
    out = []
    for e in estimates:
        if metric not in estimate_events(e, month, start, end): continue
        keys, w = credit_keys(e, credit)
        if key and key not in keys: continue
        age = (end - parse_date(e["est_date"])).days
        b = bucket(age)
        if age_bucket and (metric != "closing" or b != age_bucket): continue
        total = sum(l["amount"] for l in e["lines"])
        part = total
        if category:
            part = sum(l["amount"] for l in e["lines"] if l["category"] == category)
            if not part: continue
        if not key: w = 1          # across everyone, a split estimate counts in full (its shares add back up to 100%)
        out.append({"id": e["id"], "number": e["number"], "customer": e["customer"], "owners": e["owners"], "team": team_label(e["owners"]),
                    "est_date": e["est_date"], "period": e["period"], "status": e["status"], "closed_on": e["closed_on"], "invoice_no": e.get("invoice_no"),
                    "categories": [l["category"] for l in e["lines"]], "total": total, "part": part, "counted": part * w, "share": w, "age": age, "bucket": b})
    out.sort(key=lambda r: (-r["counted"], r["number"]))
    return out


def build_report(estimates, month, as_on, credit="team"):
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
        amount = sum(l["amount"] for l in e["lines"])
        keys, w = credit_keys(e, credit)
        events = estimate_events(e, month, start, end)
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
            top_pending.append({"id": e.get("id"), "number": e["number"], "customer": e["customer"], "owners": e["owners"],
                                "amount": amount, "age": (end - ed).days, "bucket": b})
    top_pending.sort(key=lambda r: -r["age"] * 0 - r["amount"])
    # Conversions per month (count + value): from the first month with a conversion up to the selected month, max 7.
    first_conv = min((parse_date(e["closed_on"]) for e in estimates if e["status"] == "received" and e["closed_on"]), default=None)
    months, y, m = [], start.year, start.month
    for _ in range(7):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m < 1: m, y = 12, y - 1
    months.reverse()
    if first_conv: months = [x for x in months if x >= first_conv.strftime("%Y-%m")] or months[-1:]
    else: months = months[-1:]
    trend = []
    for ym in months:
        s_, e_ = month_bounds(ym)
        hit = [e for e in estimates if e["status"] == "received" and e["closed_on"] and s_ <= parse_date(e["closed_on"]) <= e_]
        trend.append({"month": ym, "actual": len(hit), "actual_amount": sum(sum(l["amount"] for l in e["lines"]) for e in hit)})
    rows = [{"team": team_label(k) if credit == "team" else k, **v} for k, v in teams.items()]
    rows.sort(key=lambda r: -r["closing"])
    return {"month": month, "as_on": end.isoformat(), "credit": credit, "total": total, "teams": rows,
            "segments": seg, "ageing_segments": ageing_seg, "ageing_count": ageing_n,
            "trend": trend, "pending_by_value": sorted(top_pending, key=lambda r: -r["amount"])[:10]}
