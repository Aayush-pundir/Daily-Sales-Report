import hashlib, json, os, secrets, sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  pw TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('sales','finance','admin')), sm_name TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sms(name TEXT PRIMARY KEY, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS estimates(id INTEGER PRIMARY KEY, number TEXT UNIQUE NOT NULL, est_date TEXT NOT NULL,
  customer TEXT NOT NULL, period TEXT, owners TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  closed_on TEXT, closed_approx INTEGER DEFAULT 0,
  drop_reason TEXT, drop_requested_by TEXT, drop_requested_on TEXT,
  invoice_no TEXT, invoice_date TEXT, payment_ref TEXT,
  notes TEXT DEFAULT '', version INTEGER NOT NULL DEFAULT 1, created_by TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS lines(id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
  category TEXT NOT NULL, amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, estimate_id INTEGER, at TEXT, user TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS snapshots(day TEXT PRIMARY KEY, published_by TEXT, at TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL, name TEXT, stored TEXT, mime TEXT, size INTEGER, uploaded_by TEXT, uploaded_at TEXT);
CREATE TABLE IF NOT EXISTS api_keys(id INTEGER PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL, prefix TEXT, role TEXT NOT NULL CHECK(role IN('read','sales','finance')),
  active INTEGER DEFAULT 1, created_at TEXT, last_used TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS followups(id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
  on_date TEXT NOT NULL, kind TEXT NOT NULL, contact TEXT, note TEXT NOT NULL, next_date TEXT, by_user TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_fu_est ON followups(estimate_id);
CREATE TABLE IF NOT EXISTS change_requests(id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL REFERENCES estimates(id) ON DELETE CASCADE,
  requested_by TEXT, requested_at TEXT, reason TEXT, changes TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  decided_by TEXT, decided_at TEXT, decision_note TEXT);
CREATE INDEX IF NOT EXISTS ix_cr_est ON change_requests(estimate_id, status);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, at TEXT, kind TEXT, estimate_id INTEGER, request_id INTEGER, actor TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS notif_reads(user_key TEXT PRIMARY KEY, last_id INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_lines_est ON lines(estimate_id);
CREATE INDEX IF NOT EXISTS ix_audit_est ON audit(estimate_id);
"""

DB_PATH = os.environ.get("DSR_DB", os.path.join(os.path.dirname(__file__), "..", "data", "dsr.sqlite3"))


FILES_DIR = os.path.join(os.path.dirname(DB_PATH), "files")


def connect(path=None):
    path = os.path.abspath(path or DB_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)      # a fresh clone has no data/ folder yet
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    if "period" not in [r[1] for r in c.execute("PRAGMA table_info(estimates)")]:
        c.execute("ALTER TABLE estimates ADD COLUMN period TEXT")
        c.execute("UPDATE estimates SET period=substr(est_date,1,7)")
    if "external_ref" not in [r[1] for r in c.execute("PRAGMA table_info(estimates)")]:
        c.execute("ALTER TABLE estimates ADD COLUMN external_ref TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_ext ON estimates(external_ref) WHERE external_ref IS NOT NULL")
    return c


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return salt.hex() + "$" + h.hex()


def check_pw(pw, stored):
    salt, h = stored.split("$")
    return secrets.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex(), h)


def now():
    return datetime.now().isoformat(timespec="seconds")


def log(c, est_id, user, action, detail=""):
    c.execute("INSERT INTO audit(estimate_id,at,user,action,detail) VALUES(?,?,?,?,?)", (est_id, now(), user, action, detail))


def notify(c, kind, est_id, req_id, actor, text):
    c.execute("INSERT INTO notifications(at,kind,estimate_id,request_id,actor,text) VALUES(?,?,?,?,?,?)", (now(), kind, est_id, req_id, actor, text))


def load_estimates(c, where="", args=()):
    rows = [dict(r) for r in c.execute(f"SELECT * FROM estimates {where} ORDER BY est_date DESC, id DESC", args)]
    if not rows: return rows
    by = {r["id"]: r for r in rows}
    for r in rows: r["lines"] = []
    for l in c.execute("SELECT estimate_id,category,amount FROM lines WHERE estimate_id IN (%s) ORDER BY id" % ",".join("?" * len(by)), list(by)):
        by[l["estimate_id"]]["lines"].append({"category": l["category"], "amount": l["amount"]})
    for r in rows: r["total"] = sum(l["amount"] for l in r["lines"])
    return rows


def save_lines(c, est_id, lines):
    c.execute("DELETE FROM lines WHERE estimate_id=?", (est_id,))
    c.executemany("INSERT INTO lines(estimate_id,category,amount) VALUES(?,?,?)", [(est_id, l["category"], l["amount"]) for l in lines])
