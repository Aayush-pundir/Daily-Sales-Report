"""Daily Sales Report server: stdlib only (http.server + sqlite3)."""
import csv, io, json, os, re, secrets, sys, threading
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import db, rules

WEB = os.path.join(os.path.dirname(__file__), "..", "web")
LOCK = threading.Lock()
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}


def today():
    return date.fromisoformat(os.environ["DSR_TODAY"]) if os.environ.get("DSR_TODAY") else date.today()


class Err(Exception):
    def __init__(self, code, msg, extra=None):
        self.code, self.msg, self.extra = code, msg, extra or {}


def need(user, *roles):
    if user["role"] not in roles and user["role"] != "admin":
        raise Err(403, "Your role cannot do this.")


def is_owner(user, est):
    return user["role"] == "admin" or (user["sm_name"] and user["sm_name"] in est["owners"].split("|"))


class H(BaseHTTPRequestHandler):
    server_version = "DSR"

    def log_message(self, *a): pass

    # ---- plumbing
    def send(self, code, body, ctype="application/json", headers=()):
        data = body if isinstance(body, bytes) else (json.dumps(body, default=str) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)

    def user_for(self, c):
        ck = SimpleCookie(self.headers.get("Cookie", ""))
        if "sid" not in ck: return None
        r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1",
                      (ck["sid"].value, db.now())).fetchone()
        return dict(r) if r else None

    def handle_any(self, method):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not u.path.startswith("/api/"):
            if method != "GET": return self.send(405, {"error": "method"})
            p = "index.html" if u.path == "/" else u.path.lstrip("/")
            f = os.path.normpath(os.path.join(WEB, p))
            if not f.startswith(os.path.normpath(WEB)) or not os.path.isfile(f): return self.send(404, {"error": "not found"})
            return self.send(200, open(f, "rb").read(), MIME.get(os.path.splitext(f)[1], "application/octet-stream"))
        body = {}
        if method in ("POST", "PUT"):
            if "application/json" not in self.headers.get("Content-Type", ""): return self.send(415, {"error": "JSON only"})
            try: body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError: return self.send(400, {"error": "Bad JSON"})
        try:
            with LOCK:
                c = db.connect()
                try:
                    user = self.user_for(c)
                    if u.path == "/api/login" and method == "POST": res = self.login(c, body)
                    else:
                        if not user: raise Err(401, "Please sign in.")
                        res = self.route(c, method, u.path, q, body, user)
                    c.commit()
                finally: c.close()
        except Err as e: return self.send(e.code, {"error": e.msg, **e.extra})
        if isinstance(res, tuple): return self.send(200, res[0], res[1], res[2] if len(res) > 2 else ())
        self.send(200, res)

    do_GET = lambda s: s.handle_any("GET")
    do_POST = lambda s: s.handle_any("POST")
    do_PUT = lambda s: s.handle_any("PUT")

    # ---- auth
    def login(self, c, b):
        r = c.execute("SELECT * FROM users WHERE username=? AND active=1", (str(b.get("username", "")).strip().lower(),)).fetchone()
        if not r or not db.check_pw(str(b.get("password", "")), r["pw"]): raise Err(401, "Wrong username or password.")
        tok = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, r["id"], (datetime.now() + timedelta(days=7)).isoformat(timespec="seconds")))
        c.execute("DELETE FROM sessions WHERE expires<?", (db.now(),))
        return {"ok": True}, "application/json", [("Set-Cookie", f"sid={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800")]

    # ---- routing
    def route(self, c, m, path, q, b, user):
        P = path[5:].strip("/").split("/")
        if P == ["logout"] and m == "POST":
            c.execute("DELETE FROM sessions WHERE token=?", (SimpleCookie(self.headers.get("Cookie", ""))["sid"].value,))
            return {"ok": True}, "application/json", [("Set-Cookie", "sid=; Max-Age=0; Path=/")]
        if P == ["me"]: return {k: user[k] for k in ("username", "name", "role", "sm_name")}
        if P == ["meta"]:
            return {"today": today().isoformat(), "categories": rules.CATEGORIES, "buckets": rules.BUCKETS,
                    "sms": [r["name"] for r in c.execute("SELECT name FROM sms WHERE active=1 ORDER BY name")]}
        if P == ["report"]: return self.report(c, q)
        if P == ["estimates"]:
            if m == "GET": return self.list_estimates(c, q)
            if m == "POST": return self.create(c, b, user)
        if P[0] == "estimates" and len(P) >= 2 and P[1].isdigit():
            return self.estimate_action(c, m, int(P[1]), P[2] if len(P) > 2 else "", b, user)
        if P == ["targets"]:
            if m == "GET": return [dict(r) for r in c.execute("SELECT * FROM targets ORDER BY month")]
            if m == "PUT": return self.set_target(c, b, user)
        if P[0] == "snapshots": return self.snapshots(c, m, P, b, user)
        if P == ["export.csv"]: return self.export(c, q)
        if P[0] in ("users", "sms"): return self.admin(c, m, P, b, user)
        raise Err(404, "No such endpoint.")

    # ---- reports
    def report(self, c, q):
        ym = q.get("month") or today().strftime("%Y-%m")
        if not re.fullmatch(r"\d{4}-\d{2}", ym): raise Err(400, "month must be YYYY-MM")
        as_on = date.fromisoformat(q["as_on"]) if q.get("as_on") else today()
        tg = {r["month"]: dict(r) for r in c.execute("SELECT * FROM targets")}
        r = rules.build_report(db.load_estimates(c), tg, ym, as_on, split=q.get("split") == "1")
        r["pending_drop_requests"] = c.execute("SELECT COUNT(*) FROM estimates WHERE status='pending' AND drop_requested_by IS NOT NULL").fetchone()[0]
        r["target"] = tg.get(ym)
        s = c.execute("SELECT day,published_by,at FROM snapshots ORDER BY day DESC LIMIT 1").fetchone()
        r["last_published"] = dict(s) if s else None
        return r

    def list_estimates(self, c, q):
        t = today(); out = []
        for e in db.load_estimates(c):
            e["age"] = (t - date.fromisoformat(e["est_date"])).days if e["status"] == "pending" else None
            e["bucket"] = rules.bucket(e["age"]) if e["age"] is not None else None
            e["team"] = rules.team_label(e["owners"]); e["categories"] = [l["category"] for l in e["lines"]]
            if q.get("status") and e["status"] != q["status"]: continue
            if q.get("sm") and q["sm"] not in e["owners"].split("|"): continue
            if q.get("category") and q["category"] not in e["categories"]: continue
            if q.get("bucket") and e["bucket"] != q["bucket"]: continue
            if q.get("drop_requested") == "1" and not (e["status"] == "pending" and e["drop_requested_by"]): continue
            if q.get("q") and q["q"].lower() not in (e["number"] + " " + e["customer"]).lower(): continue
            out.append(e)
        return out

    def export(self, c, q):
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["Estimate No", "Date", "Customer", "Sales Manager(s)", "Status", "Fee lines", "Total", "Age (days)", "Age bracket",
                    "Closed on", "Tax invoice no", "Invoice date", "Payment ref", "Drop reason"])
        for e in self.list_estimates(c, q):
            w.writerow([e["number"], e["est_date"], e["customer"], e["team"], e["status"],
                        "; ".join(f'{l["category"]}={l["amount"]:g}' for l in e["lines"]), f'{e["total"]:g}', e["age"] or "", e["bucket"] or "",
                        e["closed_on"] or "", e["invoice_no"] or "", e["invoice_date"] or "", e["payment_ref"] or "", e["drop_reason"] or ""])
        return buf.getvalue(), "text/csv", [("Content-Disposition", f'attachment; filename="estimates-{today()}.csv"')]

    def snapshots(self, c, m, P, b, user):
        if m == "GET" and len(P) == 1:
            return [dict(r) for r in c.execute("SELECT day,published_by,at FROM snapshots ORDER BY day DESC LIMIT 60")]
        if m == "GET":
            r = c.execute("SELECT * FROM snapshots WHERE day=?", (P[1],)).fetchone()
            if not r: raise Err(404, "No report published for that day.")
            return {**dict(r), "data": json.loads(r["data"])}
        need(user, "finance")
        d = today().isoformat()
        rep = self.report(c, {"month": d[:7], "as_on": d})
        c.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)", (d, user["name"], db.now(), json.dumps(rep, default=str)))
        return {"ok": True, "day": d}

    def set_target(self, c, b, user):
        need(user, "finance")
        if not re.fullmatch(r"\d{4}-\d{2}", str(b.get("month", ""))): raise Err(400, "month must be YYYY-MM")
        def num(k, cast):
            v = b.get(k)
            if v in (None, ""): return None
            try: v = cast(v)
            except ValueError: raise Err(400, f"{k} must be a number")
            if v < 0: raise Err(400, f"{k} cannot be negative")
            return v
        old = c.execute("SELECT legacy_actual FROM targets WHERE month=?", (b["month"],)).fetchone()
        c.execute("INSERT OR REPLACE INTO targets VALUES(?,?,?,?)", (b["month"], num("target_count", int), num("target_amount", float), old[0] if old else None))
        db.log(c, None, user["name"], "target", f'{b["month"]}: {b.get("target_count")} / {b.get("target_amount")}')
        return {"ok": True}

    # ---- estimates
    def sm_names(self, c): return {r[0] for r in c.execute("SELECT name FROM sms WHERE active=1")}

    def create(self, c, b, user):
        need(user, "sales")
        clean, errs = rules.validate_estimate(b, self.sm_names(c), today(), user["sm_name"] if user["role"] == "sales" else None)
        if not errs and c.execute("SELECT 1 FROM estimates WHERE number=?", (clean["number"],)).fetchone():
            errs.append(f'Estimate {clean["number"]} already exists.')
        if errs: raise Err(422, errs[0], {"errors": errs})
        cur = c.execute("INSERT INTO estimates(number,est_date,period,customer,owners,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (clean["number"], clean["est_date"], clean["period"], clean["customer"], clean["owners"], clean["notes"], user["name"], db.now(), db.now()))
        db.save_lines(c, cur.lastrowid, clean["lines"])
        db.log(c, cur.lastrowid, user["name"], "created", f'{sum(l["amount"] for l in clean["lines"]):g}')
        return {"id": cur.lastrowid}

    def estimate_action(self, c, m, eid, act, b, user):
        rows = db.load_estimates(c, "WHERE id=?", (eid,))
        if not rows: raise Err(404, "Estimate not found.")
        e = rows[0]
        if m == "GET":
            e["audit"] = [dict(r) for r in c.execute("SELECT at,user,action,detail FROM audit WHERE estimate_id=? ORDER BY id DESC", (eid,))]
            e["age"] = (today() - date.fromisoformat(e["est_date"])).days if e["status"] == "pending" else None
            return e
        if b.get("version") != e["version"]:
            raise Err(409, "Someone else changed this estimate. Reload and try again.")
        t = today(); who = user["name"]
        def bump(**f):
            f["version"] = e["version"] + 1; f["updated_at"] = db.now()
            c.execute("UPDATE estimates SET " + ",".join(f"{k}=?" for k in f) + " WHERE id=?", [*f.values(), eid])
        reason = (b.get("reason") or "").strip()

        if act == "" and m == "PUT":                       # edit (sales owner/admin, pending only)
            need(user, "sales")
            if e["status"] != "pending": raise Err(409, "Closed estimates can't be edited. Ask an admin to reopen it.")
            if user["role"] == "sales" and not is_owner(user, e): raise Err(403, "Only the estimate's sales manager can edit it.")
            clean, errs = rules.validate_estimate(b, self.sm_names(c), t, user["sm_name"] if user["role"] == "sales" else None)
            if not errs and clean["number"] != e["number"] and c.execute("SELECT 1 FROM estimates WHERE number=?", (clean["number"],)).fetchone():
                errs.append(f'Estimate {clean["number"]} already exists.')
            if errs: raise Err(422, errs[0], {"errors": errs})
            changes = [f'{k}: {e[k]} → {clean[k]}' for k in ("number", "est_date", "period", "customer", "owners", "notes") if e[k] != clean[k]]
            if sorted((l["category"], l["amount"]) for l in e["lines"]) != sorted((l["category"], l["amount"]) for l in clean["lines"]):
                changes.append(f'fees: {e["total"]:g} → {sum(l["amount"] for l in clean["lines"]):g}')
            bump(number=clean["number"], est_date=clean["est_date"], period=clean["period"], customer=clean["customer"], owners=clean["owners"], notes=clean["notes"])
            db.save_lines(c, eid, clean["lines"]); db.log(c, eid, who, "edited", "; ".join(changes) or "no change")
        elif act == "receive":                              # finance records payment => converted to tax invoice
            need(user, "finance")
            if e["status"] != "pending": raise Err(409, "This estimate is already closed.")
            inv = (b.get("invoice_no") or "").strip()
            try: rec = date.fromisoformat(b.get("received_on") or ""); idate = date.fromisoformat(b.get("invoice_date") or b["received_on"])
            except (ValueError, KeyError): raise Err(422, "Received-on and invoice dates are required.")
            if not inv: raise Err(422, "Tax invoice number is required.")
            if rec > t: raise Err(422, "Payment can't be dated in the future.")
            if rec < date.fromisoformat(e["est_date"]): raise Err(422, "Payment can't be before the estimate date.")
            bump(status="received", closed_on=rec.isoformat(), closed_approx=0, invoice_no=inv, invoice_date=idate.isoformat(),
                 payment_ref=(b.get("payment_ref") or "").strip(), drop_requested_by=None, drop_requested_on=None)
            db.log(c, eid, who, "received", f"{e['total']:g} · invoice {inv} · paid {rec}")
        elif act == "drop-request":                         # sales proposes
            need(user, "sales")
            if e["status"] != "pending": raise Err(409, "This estimate is already closed.")
            if user["role"] == "sales" and not is_owner(user, e): raise Err(403, "Only the estimate's sales manager can propose a drop.")
            if len(reason) < 5: raise Err(422, "Give a reason (min 5 characters).")
            bump(drop_requested_by=who, drop_requested_on=t.isoformat(), drop_reason=reason); db.log(c, eid, who, "drop requested", reason)
        elif act == "drop-decision":                        # finance approves / rejects (or drops directly)
            need(user, "finance")
            if e["status"] != "pending": raise Err(409, "This estimate is already closed.")
            if b.get("decision") == "approve":
                why = reason or e["drop_reason"]
                if not why or len(why) < 5: raise Err(422, "A drop needs a reason.")
                bump(status="dropped", closed_on=t.isoformat(), closed_approx=0, drop_reason=why); db.log(c, eid, who, "dropped", why)
            elif b.get("decision") == "reject":
                bump(drop_requested_by=None, drop_requested_on=None, drop_reason=None); db.log(c, eid, who, "drop rejected", reason)
            else: raise Err(400, "decision must be approve or reject")
        elif act == "reopen":
            if user["role"] != "admin": raise Err(403, "Only an admin can reopen a closed estimate.")
            if e["status"] == "pending": raise Err(409, "Already open.")
            if len(reason) < 5: raise Err(422, "Give a reason for reopening.")
            bump(status="pending", closed_on=None, closed_approx=0, invoice_no=None, invoice_date=None, payment_ref=None,
                 drop_requested_by=None, drop_requested_on=None, drop_reason=None); db.log(c, eid, who, "reopened", reason)
        else: raise Err(404, "No such action.")
        return {"ok": True, "version": e["version"] + 1}

    # ---- admin
    def admin(self, c, m, P, b, user):
        if user["role"] != "admin":
            if P[0] == "users" and m == "GET": raise Err(403, "Admins only.")
            if P[0] == "sms" and m == "GET": return [dict(r) for r in c.execute("SELECT * FROM sms ORDER BY name")]
            raise Err(403, "Admins only.")
        if P[0] == "sms":
            if m == "GET": return [dict(r) for r in c.execute("SELECT * FROM sms ORDER BY name")]
            n = rules.norm_name(b.get("name"))
            if not n or "&" in n or "|" in n: raise Err(422, "Name is required and can't contain & or |.")
            c.execute("INSERT INTO sms(name,active) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET active=excluded.active", (n, 0 if b.get("active") is False else 1))
            return {"ok": True}
        if m == "GET": return [{k: r[k] for k in ("id", "username", "name", "role", "sm_name", "active")} for r in c.execute("SELECT * FROM users ORDER BY id")]
        uname = str(b.get("username", "")).strip().lower()
        if m == "POST":
            if not re.fullmatch(r"[a-z0-9._-]{3,30}", uname): raise Err(422, "Username: 3-30 chars, letters/digits/._-")
            if len(b.get("password") or "") < 8: raise Err(422, "Password must be at least 8 characters.")
        role = b.get("role")
        if role not in ("sales", "finance", "admin"): raise Err(422, "Pick a role.")
        if role == "sales" and b.get("sm_name") not in self.sm_names(c): raise Err(422, "Sales users must be linked to a sales manager.")
        sm = b.get("sm_name") if role == "sales" else None
        if m == "POST":
            if c.execute("SELECT 1 FROM users WHERE username=?", (uname,)).fetchone(): raise Err(422, "Username taken.")
            c.execute("INSERT INTO users(username,name,pw,role,sm_name) VALUES(?,?,?,?,?)", (uname, rules.norm_name(b.get("name")) or uname, db.hash_pw(b["password"]), role, sm))
        else:
            if b.get("id") == user["id"] and (b.get("active") is False or role != "admin"): raise Err(422, "You can't demote or deactivate yourself.")
            c.execute("UPDATE users SET name=?,role=?,sm_name=?,active=? WHERE id=?", (rules.norm_name(b.get("name")), role, sm, 0 if b.get("active") is False else 1, b.get("id")))
            if b.get("password"):
                if len(b["password"]) < 8: raise Err(422, "Password must be at least 8 characters.")
                c.execute("UPDATE users SET pw=? WHERE id=?", (db.hash_pw(b["password"]), b["id"]))
        return {"ok": True}


def bootstrap():
    """First run: create an admin with a one-time random password, printed once."""
    c = db.connect()
    if not c.execute("SELECT 1 FROM users").fetchone():
        pw = os.environ.get("DSR_ADMIN_PASSWORD") or secrets.token_urlsafe(9)
        c.execute("INSERT INTO users(username,name,pw,role) VALUES('admin','Administrator',?, 'admin')", (db.hash_pw(pw),))
        c.commit(); print(f"\n  First run: sign in as  admin  /  {pw}   (create real users from the Admin tab)\n")
    c.close()


def main():
    bootstrap()
    port = int(os.environ.get("PORT", 8080))
    print(f"Daily Sales Report on http://localhost:{port}")
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), port), H).serve_forever()


if __name__ == "__main__":
    main()
