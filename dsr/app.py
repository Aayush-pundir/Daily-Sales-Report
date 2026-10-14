"""Daily Sales Report server: stdlib only (http.server + sqlite3)."""
import csv, io, json, os, re, secrets, sys, threading
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import base64, hashlib, hmac, traceback, urllib.request
import mimetypes
from . import db, rules, uploads

WEB = os.path.join(os.path.dirname(__file__), "..", "web")
LOCK = threading.Lock()
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}


def today():
    return date.fromisoformat(os.environ["DSR_TODAY"]) if os.environ.get("DSR_TODAY") else date.today()


def passwordless():
    """Quick sign-in (click a name, no password). On by default only when the server listens on this computer
    alone; set DSR_PASSWORDLESS=1 / 0 to force it on / off."""
    v = os.environ.get("DSR_PASSWORDLESS", "").lower()
    if v in ("1", "true", "yes", "on"): return True
    if v in ("0", "false", "no", "off"): return False
    return os.environ.get("HOST", "127.0.0.1") in ("127.0.0.1", "localhost", "::1")


class Err(Exception):
    def __init__(self, code, msg, extra=None):
        self.code, self.msg, self.extra = code, msg, extra or {}


def need(user, *roles):
    if user["role"] not in roles and user["role"] != "admin":
        raise Err(403, "Your role cannot do this.")


def is_owner(user, est):
    return user["role"] == "admin" or user.get("api") or (user["sm_name"] and user["sm_name"] in est["owners"].split("|"))


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
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            h = hashlib.sha256(auth[7:].strip().encode()).hexdigest()
            k = c.execute("SELECT * FROM api_keys WHERE key_hash=? AND active=1", (h,)).fetchone()
            if not k: return None
            c.execute("UPDATE api_keys SET last_used=? WHERE id=?", (db.now(), k["id"]))
            return {"id": -k["id"], "username": "api", "name": "API: " + k["name"], "role": k["role"], "sm_name": None, "api": True}
        ck = SimpleCookie(self.headers.get("Cookie", ""))
        if "sid" not in ck: return None
        r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1",
                      (ck["sid"].value, db.now())).fetchone()
        return dict(r) if r else None

    def emit(self, event, est_id, c):
        self._events = getattr(self, "_events", [])
        self._events.append((event, est_id))

    def fire_webhooks(self):
        c = db.connect()
        try:
            cfg = {r["k"]: r["v"] for r in c.execute("SELECT k,v FROM settings WHERE k IN('webhook_url','webhook_secret')")}
            if not cfg.get("webhook_url"): return
            for ev, eid in self._events:
                rows = db.load_estimates(c, "WHERE id=?", (eid,))
                if not rows: continue
                e = rows[0]; payload = json.dumps({"event": ev, "at": db.now(), "estimate": {k: e[k] for k in
                    ("id", "number", "customer", "est_date", "period", "owners", "status", "closed_on", "invoice_no", "external_ref", "total", "lines")}}, default=str).encode()
                sig = hmac.new(cfg.get("webhook_secret", "").encode(), payload, hashlib.sha256).hexdigest()
                threading.Thread(target=self._post_hook, args=(cfg["webhook_url"], payload, sig), daemon=True).start()
        finally: c.close()

    @staticmethod
    def _post_hook(url, payload, sig):
        try: urllib.request.urlopen(urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "X-DSR-Signature": "sha256=" + sig}), timeout=8).read()
        except Exception as ex: print("webhook failed:", url, ex)

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
                    elif u.path == "/api/quick-users" and method == "GET": res = self.quick_users(c)
                    elif u.path == "/api/quick-login" and method == "POST": res = self.quick_login(c, body)
                    else:
                        if not user: raise Err(401, "Please sign in.")
                        res = self.route(c, method, u.path, q, body, user)
                    c.commit()
                finally: c.close()
            if getattr(self, "_events", None): self.fire_webhooks()
        except Err as e: return self.send(e.code, {"error": e.msg, **e.extra})
        except Exception:                      # never drop the connection: that shows up in the browser as "Failed to fetch"
            traceback.print_exc()
            return self.send(500, {"error": "Something went wrong inside the app. The technical details are printed in the Terminal window where the app is running."})
        if isinstance(res, tuple): return self.send(200, res[0], res[1], res[2] if len(res) > 2 else ())
        self.send(200, res)

    do_GET = lambda s: s.handle_any("GET")
    do_POST = lambda s: s.handle_any("POST")
    do_PUT = lambda s: s.handle_any("PUT")

    # ---- auth
    def _session(self, c, user_id):
        tok = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (tok, user_id, (datetime.now() + timedelta(days=7)).isoformat(timespec="seconds")))
        c.execute("DELETE FROM sessions WHERE expires<?", (db.now(),))
        return {"ok": True}, "application/json", [("Set-Cookie", f"sid={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800")]

    def login(self, c, b):
        r = c.execute("SELECT * FROM users WHERE username=? AND active=1", (str(b.get("username", "")).strip().lower(),)).fetchone()
        if not r or not db.check_pw(str(b.get("password", "")), r["pw"]): raise Err(401, "Wrong username or password.")
        return self._session(c, r["id"])

    def quick_users(self, c):
        """Quick sign-in: pick a name, no password. Only offered when passwordless() is true."""
        if not passwordless(): return {"enabled": False, "users": []}
        return {"enabled": True, "users": [dict(r) for r in c.execute(
            "SELECT id,name,role,sm_name FROM users WHERE active=1 ORDER BY CASE role WHEN 'admin' THEN 0 WHEN 'finance' THEN 1 ELSE 2 END, name")]}

    def quick_login(self, c, b):
        if not passwordless(): raise Err(403, "Quick sign-in is switched off on this server.")
        r = c.execute("SELECT id FROM users WHERE id=? AND active=1", (b.get("user_id"),)).fetchone()
        if not r: raise Err(404, "No such user.")
        return self._session(c, r["id"])

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
        if P == ["estimates", "template.csv"]: return uploads.TEMPLATE, "text/csv", [("Content-Disposition", 'attachment; filename="estimate-upload-template.csv"')]
        if P == ["estimates", "upload"] and m == "POST": return self.bulk_upload(c, b, user)
        if P == ["estimates"]:
            if m == "GET": return self.list_estimates(c, q)
            if m == "POST": return self.create(c, b, user)
        if P == ["followups"]: return self.followup_board(c, q)
        if P == ["change-requests"] and m == "GET": return self.list_change_requests(c, q)
        if P[0] == "change-requests" and len(P) == 3 and P[1].isdigit() and P[2] in ("decision", "withdraw") and m == "POST":
            return self.change_decision(c, int(P[1]), P[2], b, user)
        if P[0] == "estimates" and len(P) == 3 and P[1].isdigit() and P[2] == "change-requests" and m == "POST":
            return self.request_change(c, int(P[1]), b, user)
        if P[0] == "notifications": return self.notifications(c, m, P, q, user)
        if P[0] == "estimates" and len(P) == 3 and P[1].isdigit() and P[2] == "followups" and m == "POST":
            return self.add_followup(c, int(P[1]), b, user)
        if P[0] == "estimates" and len(P) >= 3 and P[1].isdigit() and P[2] == "files":
            return self.files(c, m, int(P[1]), P[3:], b, user)
        if P[0] == "estimates" and len(P) >= 2 and P[1].isdigit():
            return self.estimate_action(c, m, int(P[1]), P[2] if len(P) > 2 else "", b, user)
        if P[0] == "snapshots": return self.snapshots(c, m, P, b, user)
        if P == ["export.csv"]: return self.export(c, q)
        if P[0] in ("users", "sms", "keys", "webhook"): return self.admin(c, m, P, b, user)
        raise Err(404, "No such endpoint.")

    # ---- reports
    def report(self, c, q):
        ym = q.get("month") or today().strftime("%Y-%m")
        if not re.fullmatch(r"\d{4}-\d{2}", ym): raise Err(400, "month must be YYYY-MM")
        try: as_on = date.fromisoformat(q["as_on"]) if q.get("as_on") else today()
        except ValueError: raise Err(400, "as_on must be YYYY-MM-DD")
        r = rules.build_report(db.load_estimates(c), ym, as_on, credit=q.get("credit") if q.get("credit") in ("primary", "split") else "team")
        r["pending_drop_requests"] = c.execute("SELECT COUNT(*) FROM estimates WHERE status='pending' AND drop_requested_by IS NOT NULL").fetchone()[0]
        r["open_change_requests"] = c.execute("SELECT COUNT(*) FROM change_requests WHERE status='open'").fetchone()[0]
        r["followups_needed"] = sum(1 for x in self.followup_board(c, {}) if x["flag"] != "ok")
        s = c.execute("SELECT day,published_by,at FROM snapshots ORDER BY day DESC LIMIT 1").fetchone()
        r["last_published"] = dict(s) if s else None
        return r

    def list_estimates(self, c, q):
        t = today(); out = []
        with_cr = {r[0] for r in c.execute("SELECT estimate_id FROM change_requests WHERE status='open'")}
        for e in db.load_estimates(c):
            e["change_requested"] = e["id"] in with_cr
            if q.get("change_requested") == "1" and not e["change_requested"]: continue
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

    # ---- follow-ups
    def followups_for(self, c, ids):
        out = {i: [] for i in ids}
        if ids:
            for r in c.execute("SELECT * FROM followups WHERE estimate_id IN (%s) ORDER BY on_date, id" % ",".join("?" * len(ids)), list(ids)):
                out[r["estimate_id"]].append({k: r[k] for k in ("id", "on_date", "kind", "contact", "note", "next_date", "by_user")})
        return out

    def followup_board(self, c, q):
        t = today(); min_age = int(q.get("min_age") or rules.TRACK_AFTER_DAYS) if str(q.get("min_age") or "0").isdigit() else rules.TRACK_AFTER_DAYS
        ests = [e for e in db.load_estimates(c, "WHERE status='pending'") if (t - date.fromisoformat(e["est_date"])).days > min_age]
        fu = self.followups_for(c, [e["id"] for e in ests]); out = []
        for e in ests:
            f = fu[e["id"]]; age = (t - date.fromisoformat(e["est_date"])).days
            flag = rules.followup_flag(age, f, t)
            if q.get("sm") and q["sm"] not in e["owners"].split("|"): continue
            if q.get("flag") and q["flag"] != flag: continue
            out.append({"id": e["id"], "number": e["number"], "customer": e["customer"], "owners": e["owners"], "team": rules.team_label(e["owners"]),
                        "total": e["total"], "age": age, "flag": flag, "followups": f, "version": e["version"],
                        "last": f[-1]["on_date"] if f else None, "next": next((x["next_date"] for x in reversed(f) if x["next_date"]), None) if f else None})
        order = {"none": 0, "overdue": 1, "ok": 2}
        out.sort(key=lambda r: (order[r["flag"]], -r["age"]))
        return out

    def add_followup(self, c, eid, b, user):
        need(user, "sales", "finance")
        rows = db.load_estimates(c, "WHERE id=?", (eid,))
        if not rows: raise Err(404, "Estimate not found.")
        e = rows[0]
        if e["status"] != "pending": raise Err(409, "Follow-ups are only for pending estimates.")
        if user["role"] == "sales" and not is_owner(user, e): raise Err(403, "Only the estimate's sales manager (or finance) can log follow-ups.")
        f, errs = rules.validate_followup(b, e["est_date"], today())
        if errs: raise Err(422, errs[0], {"errors": errs})
        c.execute("INSERT INTO followups(estimate_id,on_date,kind,contact,note,next_date,by_user,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (eid, f["on_date"], f["kind"], f["contact"], f["note"], f["next_date"], user["name"], db.now()))
        db.log(c, eid, user["name"], "follow-up", f'{f["kind"]}: {f["note"][:80]}' + (f' · next {f["next_date"]}' if f["next_date"] else ""))
        self.emit("estimate.followup", eid, c)
        return {"ok": True}

    # ---- bulk upload + attachments
    def bulk_upload(self, c, b, user):
        need(user, "sales")
        try:
            data = base64.b64decode(b.get("content") or "", validate=True)
            if not data or len(data) > uploads.MAX_BYTES: raise ValueError("File is empty or larger than 10 MB.")
            existing = {r[0] for r in c.execute("SELECT number FROM estimates")}
            res = uploads.parse(str(b.get("filename") or "upload.csv"), data, self.sm_names(c), today(),
                                user["sm_name"] if user["role"] == "sales" else None, existing)
        except ValueError as e: raise Err(422, str(e))
        good = [r for r in res if r["ok"]]
        if b.get("commit"):
            for r in good:
                cl = r["clean"]
                cur = c.execute("INSERT INTO estimates(number,est_date,period,customer,owners,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (cl["number"], cl["est_date"], cl["period"], cl["customer"], cl["owners"], "", user["name"], db.now(), db.now()))
                db.save_lines(c, cur.lastrowid, cl["lines"]); db.log(c, cur.lastrowid, user["name"], "created", f'bulk upload {b.get("filename")}')
        for r in res: r.pop("clean")
        return {"committed": bool(b.get("commit")), "imported": len(good) if b.get("commit") else 0, "valid": len(good), "invalid": len(res) - len(good), "rows": res}

    def files(self, c, m, eid, rest, b, user):
        e = db.load_estimates(c, "WHERE id=?", (eid,))
        if not e: raise Err(404, "Estimate not found.")
        e = e[0]
        if m == "GET" and not rest: return [dict(r) for r in c.execute("SELECT id,name,size,uploaded_by,uploaded_at FROM files WHERE estimate_id=? ORDER BY id", (eid,))]
        if m == "GET":
            r = c.execute("SELECT * FROM files WHERE estimate_id=? AND id=?", (eid, rest[0])).fetchone()
            path = r and os.path.join(db.FILES_DIR, r["stored"])
            if not r or not os.path.isfile(path): raise Err(404, "File not found.")
            return open(path, "rb").read(), r["mime"], [("Content-Disposition", 'attachment; filename="%s"' % re.sub(r'[^\w.\- ]', "_", r["name"]))]
        if m == "POST":
            need(user, "sales", "finance")
            if user["role"] == "sales" and not is_owner(user, e): raise Err(403, "Only the estimate's sales manager can attach files.")
            name = os.path.basename(str(b.get("filename") or "")).strip()
            ext = os.path.splitext(name)[1].lower()
            if ext not in (".pdf", ".png", ".jpg", ".jpeg"): raise Err(422, "Attach a PDF, PNG or JPG.")
            try: data = base64.b64decode(b.get("content") or "", validate=True)
            except ValueError: raise Err(422, "Bad file data.")
            if not data or len(data) > uploads.MAX_BYTES: raise Err(422, "File is empty or larger than 10 MB.")
            os.makedirs(db.FILES_DIR, exist_ok=True)
            stored = f"{eid}-{secrets.token_hex(8)}{ext}"
            open(os.path.join(db.FILES_DIR, stored), "wb").write(data)
            c.execute("INSERT INTO files(estimate_id,name,stored,mime,size,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?)",
                      (eid, name, stored, uploads.FILE_TYPES[ext], len(data), user["name"], db.now()))
            db.log(c, eid, user["name"], "file attached", name)
            return {"ok": True}
        raise Err(405, "Not allowed.")

    # ---- estimates
    def sm_names(self, c): return {r[0] for r in c.execute("SELECT name FROM sms WHERE active=1")}

    def create(self, c, b, user):
        need(user, "sales")
        ref = str(b.get("external_ref") or "").strip()[:100] or None
        if ref:   # idempotent for integrations: replaying the same CRM record returns the same estimate
            old = c.execute("SELECT id FROM estimates WHERE external_ref=?", (ref,)).fetchone()
            if old: return {"id": old[0], "existing": True}
        clean, errs = rules.validate_estimate(b, self.sm_names(c), today(), user["sm_name"] if user["role"] == "sales" else None)
        if not errs and c.execute("SELECT 1 FROM estimates WHERE number=?", (clean["number"],)).fetchone():
            errs.append(f'Estimate {clean["number"]} already exists.')
        if errs: raise Err(422, errs[0], {"errors": errs})
        cur = c.execute("INSERT INTO estimates(number,est_date,period,customer,owners,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (clean["number"], clean["est_date"], clean["period"], clean["customer"], clean["owners"], clean["notes"], user["name"], db.now(), db.now()))
        db.save_lines(c, cur.lastrowid, clean["lines"])
        db.log(c, cur.lastrowid, user["name"], "created", f'{sum(l["amount"] for l in clean["lines"]):g}')
        if ref: c.execute("UPDATE estimates SET external_ref=? WHERE id=?", (ref, cur.lastrowid))
        self.emit("estimate.created", cur.lastrowid, c)
        return {"id": cur.lastrowid}

    def estimate_action(self, c, m, eid, act, b, user):
        rows = db.load_estimates(c, "WHERE id=?", (eid,))
        if not rows: raise Err(404, "Estimate not found.")
        e = rows[0]
        if m == "GET":
            e["audit"] = [dict(r) for r in c.execute("SELECT at,user,action,detail FROM audit WHERE estimate_id=? ORDER BY id DESC", (eid,))]
            e["age"] = (today() - date.fromisoformat(e["est_date"])).days if e["status"] == "pending" else None
            e["followups"] = self.followups_for(c, [eid])[eid]
            e["change_requests"] = [self._cr_row(r) for r in c.execute("SELECT * FROM change_requests WHERE estimate_id=? ORDER BY id DESC", (eid,))]
            e["files"] = [dict(r) for r in c.execute("SELECT id,name,size,uploaded_by FROM files WHERE estimate_id=? ORDER BY id", (eid,))]
            return e
        if b.get("version") != e["version"]:
            raise Err(409, "Someone else changed this estimate. Reload and try again.")
        t = today(); who = user["name"]
        def bump(**f):
            f["version"] = e["version"] + 1; f["updated_at"] = db.now()
            c.execute("UPDATE estimates SET " + ",".join(f"{k}=?" for k in f) + " WHERE id=?", [*f.values(), eid])
        reason = (b.get("reason") or "").strip()

        if act == "" and m == "PUT":                       # direct edit: finance/admin only; sales request changes instead
            if user["role"] == "sales": raise Err(403, "Changes to an estimate are requested from finance: use “Request change”.")
            need(user, "finance")
            if e["status"] != "pending": raise Err(409, "Closed estimates can't be edited. Ask an admin to reopen it.")
            clean, errs = rules.validate_estimate(b, self.sm_names(c), t, None)
            if not errs and clean["number"] != e["number"] and c.execute("SELECT 1 FROM estimates WHERE number=?", (clean["number"],)).fetchone():
                errs.append(f'Estimate {clean["number"]} already exists.')
            if errs: raise Err(422, errs[0], {"errors": errs})
            self._apply(c, e, clean, who, "edited", rules.describe_diff(rules.diff_estimate(e, clean)) or "no change")
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
        ev = {"receive": "estimate.received", "drop-decision": "estimate.dropped" if b.get("decision") == "approve" else None,
              "reopen": "estimate.reopened", "": "estimate.updated", "drop-request": "estimate.drop_requested"}.get(act)
        if ev: self.emit(ev, eid, c)
        return {"ok": True, "version": e["version"] + 1}

    def _apply(self, c, e, clean, who, action, detail):
        c.execute("UPDATE estimates SET number=?,est_date=?,period=?,customer=?,owners=?,notes=?,version=?,updated_at=? WHERE id=?",
                  (clean["number"], clean["est_date"], clean["period"], clean["customer"], clean["owners"], clean["notes"], e["version"] + 1, db.now(), e["id"]))
        db.save_lines(c, e["id"], clean["lines"]); db.log(c, e["id"], who, action, detail)

    # ---- change requests (sales ask, any finance person decides) + notifications
    def _cr_row(self, r):
        d = dict(r); d["changes"] = json.loads(d["changes"]); d["summary"] = rules.describe_diff(d["changes"]); return d

    def request_change(self, c, eid, b, user):
        if user["role"] != "sales": raise Err(403, "Finance and admin edit estimates directly; only sales request changes.")
        rows = db.load_estimates(c, "WHERE id=?", (eid,))
        if not rows: raise Err(404, "Estimate not found.")
        e = rows[0]
        if e["status"] != "pending": raise Err(409, "Closed estimates can't be changed. Ask finance/admin to reopen it.")
        if user["role"] == "sales" and not is_owner(user, e): raise Err(403, "Only the estimate's sales manager can request a change.")
        if c.execute("SELECT 1 FROM change_requests WHERE estimate_id=? AND status='open'", (eid,)).fetchone():
            raise Err(409, "A change request is already waiting for finance on this estimate. Withdraw it first to send a new one.")
        reason = (b.get("reason") or "").strip()
        if len(reason) < 5: raise Err(422, "Tell finance why the change is needed (min 5 characters).")
        proposal = {**rules.current_values(e), **{k: b[k] for k in rules.DIFF_FIELDS if k in b}}   # unspecified fields stay as they are
        clean, errs = rules.validate_estimate(proposal, self.sm_names(c), today(), None)
        if not errs and clean["number"] != e["number"] and c.execute("SELECT 1 FROM estimates WHERE number=?", (clean["number"],)).fetchone():
            errs.append(f'Estimate {clean["number"]} already exists.')
        if errs: raise Err(422, errs[0], {"errors": errs})
        changes = rules.diff_estimate(e, clean)
        if not changes: raise Err(422, "Nothing to change: the request matches the estimate as it is.")
        cur = c.execute("INSERT INTO change_requests(estimate_id,requested_by,requested_at,reason,changes) VALUES(?,?,?,?,?)",
                        (eid, user["name"], db.now(), reason, json.dumps(changes)))
        summary = rules.describe_diff(changes)
        db.log(c, eid, user["name"], "change requested", f"{summary} — {reason}")
        db.notify(c, "change_requested", eid, cur.lastrowid, user["name"], f'{user["name"]} asked finance to change {e["number"]} ({e["customer"][:30]}): {summary}')
        self.emit("estimate.change_requested", eid, c)
        return {"id": cur.lastrowid}

    def list_change_requests(self, c, q):
        sql = "SELECT cr.*, e.number, e.customer, e.owners FROM change_requests cr JOIN estimates e ON e.id=cr.estimate_id"
        args = []
        if q.get("status"): sql += " WHERE cr.status=?"; args.append(q["status"])
        if q.get("estimate_id", "").isdigit(): sql += (" AND" if args else " WHERE") + " cr.estimate_id=?"; args.append(int(q["estimate_id"]))
        return [self._cr_row(r) for r in c.execute(sql + " ORDER BY cr.id DESC LIMIT 200", args)]

    def change_decision(self, c, rid, act, b, user):
        r = c.execute("SELECT * FROM change_requests WHERE id=?", (rid,)).fetchone()
        if not r: raise Err(404, "Change request not found.")
        if r["status"] != "open": raise Err(409, f'This request was already {r["status"]}' + (f' by {r["decided_by"]}.' if r["decided_by"] else "."))
        e = db.load_estimates(c, "WHERE id=?", (r["estimate_id"],))[0]
        note = (b.get("note") or "").strip(); who = user["name"]
        if act == "withdraw":
            if user["role"] != "admin" and who != r["requested_by"]: raise Err(403, "Only the person who asked can withdraw it.")
            status, kind, word = "withdrawn", "change_withdrawn", "withdrew the change request for"
        else:
            need(user, "finance")                                  # any finance person (or admin) can decide
            if b.get("decision") == "reject":
                if len(note) < 5: raise Err(422, "Say why it is rejected (min 5 characters) so sales know what to fix.")
                status, kind, word = "rejected", "change_rejected", "rejected the change to"
            elif b.get("decision") == "approve":
                if e["status"] != "pending": raise Err(409, "The estimate is closed now; reject this request.")
                changes = json.loads(r["changes"]); cur = rules.current_values(e)
                stale = [f for f, ch in changes.items() if rules._norm(f, cur[f]) != ch["old"]]
                if stale: raise Err(409, "The estimate changed after this was requested (" + ", ".join(stale) + "). Reject it and ask sales to send it again.")
                prop = {**cur, **{f: ch["new"] if f != "lines" else [{"category": c_, "amount": a_} for c_, a_ in ch["new"]] for f, ch in changes.items()}}
                clean, errs = rules.validate_estimate(prop, self.sm_names(c), today(), None)
                if not errs and clean["number"] != e["number"] and c.execute("SELECT 1 FROM estimates WHERE number=?", (clean["number"],)).fetchone():
                    errs.append(f'Estimate {clean["number"]} already exists.')
                if errs: raise Err(422, errs[0], {"errors": errs})
                self._apply(c, e, clean, who, "edited", f'approved request #{rid} by {r["requested_by"]}: ' + rules.describe_diff(changes))
                status, kind, word = "approved", "change_approved", "approved the change to"
            else: raise Err(400, "decision must be approve or reject")
        c.execute("UPDATE change_requests SET status=?,decided_by=?,decided_at=?,decision_note=? WHERE id=?", (status, who, db.now(), note, rid))
        if status != "approved": db.log(c, e["id"], who, f"change request {status}", note)
        db.notify(c, kind, e["id"], rid, who, f'{who} {word} {e["number"]} ({e["customer"][:30]})' + (f': {note}' if note else "") + (f' — {rules.describe_diff(json.loads(r["changes"]))}' if status == "approved" else "") + (f' (requested by {r["requested_by"]})' if status != "withdrawn" else ""))
        self.emit({"approved": "estimate.change_approved", "rejected": "estimate.change_rejected", "withdrawn": "estimate.change_withdrawn"}[status], e["id"], c)
        return {"ok": True, "status": status}

    def notifications(self, c, m, P, q, user):
        key = str(user["id"])
        if m == "POST" and P[1:] == ["read"]:
            top = c.execute("SELECT COALESCE(MAX(id),0) FROM notifications").fetchone()[0]
            c.execute("INSERT INTO notif_reads(user_key,last_id) VALUES(?,?) ON CONFLICT(user_key) DO UPDATE SET last_id=excluded.last_id", (key, top)); return {"ok": True}
        last = (c.execute("SELECT last_id FROM notif_reads WHERE user_key=?", (key,)).fetchone() or [0])[0]
        rows = [dict(r) for r in c.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (min(int(q.get("limit") or 30), 100),))]
        open_ids = {r[0] for r in c.execute("SELECT id FROM change_requests WHERE status='open'")}
        for r in rows: r["unread"] = r["id"] > last; r["open"] = r["request_id"] in open_ids and r["kind"] == "change_requested"
        return {"unread": c.execute("SELECT COUNT(*) FROM notifications WHERE id>?", (last,)).fetchone()[0], "items": rows}

    # ---- admin
    def admin(self, c, m, P, b, user):
        if P[0] in ("keys", "webhook") and user["role"] != "admin": raise Err(403, "Admins only.")
        if P[0] == "keys":
            if m == "GET": return [dict(r) for r in c.execute("SELECT id,name,prefix,role,active,created_at,last_used FROM api_keys ORDER BY id")]
            if m == "POST":
                name = rules.norm_name(b.get("name"))
                if not name or b.get("role") not in ("read", "sales", "finance"): raise Err(422, "Give the key a name and a role (read, sales or finance).")
                tok = "dsr_" + secrets.token_urlsafe(32)
                c.execute("INSERT INTO api_keys(name,key_hash,prefix,role,created_at) VALUES(?,?,?,?,?)", (name, hashlib.sha256(tok.encode()).hexdigest(), tok[:8], b["role"], db.now()))
                return {"token": tok, "note": "Shown once. Store it in the CRM's secret store."}
            c.execute("UPDATE api_keys SET active=? WHERE id=?", (0 if b.get("active") is False else 1, b.get("id"))); return {"ok": True}
        if P[0] == "webhook":
            if m == "PUT":
                url = str(b.get("url") or "").strip()
                if url and not re.match(r"https://|http://(localhost|127\.0\.0\.1)", url): raise Err(422, "Webhook URL must be https (http only for localhost).")
                c.execute("INSERT OR REPLACE INTO settings VALUES('webhook_url',?)", (url,))
                if b.get("secret"): c.execute("INSERT OR REPLACE INTO settings VALUES('webhook_secret',?)", (b["secret"],))
            return {"url": (c.execute("SELECT v FROM settings WHERE k='webhook_url'").fetchone() or [""])[0], "has_secret": bool(c.execute("SELECT 1 FROM settings WHERE k='webhook_secret'").fetchone())}
        if P == ["users", "bulk-sales"] and m == "POST":
            if user["role"] != "admin": raise Err(403, "Admins only.")
            made = []
            for sm in c.execute("SELECT name FROM sms WHERE active=1 ORDER BY name").fetchall():
                if c.execute("SELECT 1 FROM users WHERE role='sales' AND sm_name=?", (sm["name"],)).fetchone(): continue
                base = re.sub(r"[^a-z0-9]+", ".", sm["name"].lower()).strip(".")[:28] or "sales"
                uname, n = base, 1
                while c.execute("SELECT 1 FROM users WHERE username=?", (uname,)).fetchone(): n += 1; uname = f"{base}{n}"
                c.execute("INSERT INTO users(username,name,pw,role,sm_name) VALUES(?,?,?,?,?)", (uname, sm["name"], db.hash_pw(secrets.token_urlsafe(12)), "sales", sm["name"]))
                made.append(sm["name"])
            return {"created": made}
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
        c.commit()
        if passwordless(): print("\n  First run: just click  Administrator  on the sign-in page, then add your people in the Admin tab.\n")
        else: print(f"\n  First run: sign in as  admin  /  {pw}   (create real users from the Admin tab)\n")
    c.close()


def main():
    bootstrap()
    port = int(os.environ.get("PORT", 8080))
    print(f"Daily Sales Report is running.  Open  http://127.0.0.1:{port}  in your browser  (leave this window open; Ctrl+C stops it)")
    print("Sign-in: " + ("QUICK (click a name, no password) — only because this server is reachable from this computer alone" if passwordless() else "password"))
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), port), H).serve_forever()


if __name__ == "__main__":
    main()
