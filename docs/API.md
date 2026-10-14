# Integration API (for the CRM or any other system)

Base URL: your server, e.g. `https://dsr.example.com`. JSON in, JSON out.

## Authentication
An admin creates a key under **Admin → API access** (shown once). Send it on every call:

```
Authorization: Bearer dsr_xxxxxxxx
```
Roles: `read` (GET only) · `sales` (+ create/edit estimates, bulk upload, attach files, propose drops) · `finance` (+ record payment, approve/make drops).
Everything an API key does is written to the estimate's history as `API: <key name>`. Keys never act as admin.

## Create an estimate (idempotent)
```bash
curl -X POST $BASE/api/estimates -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{
  "external_ref": "CRM-DEAL-1042",            # your id; replaying the same ref returns the same estimate
  "number": "EST-26-27/264", "est_date": "2026-10-13", "period": "2026-10",   # period optional (defaults to date's month)
  "customer": "Acme Pvt Ltd",
  "owners": ["Arshdeep", "Meisheil"],         # first = primary salesperson; must exist in the SM list
  "lines": [{"category": "Annual fees", "amount": 90000}, {"category": "Set-up fees", "amount": 10000}]
}'
# 200 {"id": 131}   |   200 {"id": 131, "existing": true}   |   422 {"error": "...", "errors": [...]}
```
Categories: `Annual fees`, `Set-up fees`, `Integration`, `Customisation`.

## Changing an estimate after it is saved
Sales keys cannot edit an estimate directly (that returns 403). They ask finance:
```bash
curl -X POST $BASE/api/estimates/131/change-requests -H "Authorization: Bearer $SALES_KEY" -H "Content-Type: application/json" -d '{
  "reason": "Revised PDF shows ₹2,60,000",                         # required, min 5 characters
  "lines": [{"category": "Annual fees", "amount": 260000}]      # send only what changes; other fields stay as they are
}'
# 200 {"id": 7}  | 409 if a request is already open on that estimate | 422 if nothing would change
```
A finance key (or an admin) decides, which applies the change immediately:
```bash
curl -X POST $BASE/api/change-requests/7/decision -H "Authorization: Bearer $FINANCE_KEY" -H "Content-Type: application/json" -d '{"decision": "approve"}'
# or {"decision": "reject", "note": "Must match the GST registration"}   # note required for a rejection
curl -X POST $BASE/api/change-requests/7/withdraw ...                  # by whoever asked
```
`GET /api/change-requests?status=open` lists them with the field-by-field changes. A request goes stale (409 on approve) if the estimate was changed after it was raised.
Finance and admin keys can still `PUT /api/estimates/{id}` directly. `GET /api/notifications` returns the shared notification feed.

## Other calls
| | |
|---|---|
| `GET /api/estimates?status=pending&sm=Arshdeep&category=…&bucket=90%2B&q=text` | list (adds `age`, `bucket`, `team`) |
| `GET /api/estimates/{id}` | detail with `lines`, `audit`, `files`, `version` |
| `PUT /api/estimates/{id}` | **finance/admin only**: edit a pending estimate; body as create **plus `"version"`** (sales use change requests) |
| `POST /api/estimates/{id}/receive` | finance: `{version, invoice_no, invoice_date, received_on, payment_ref}` |
| `POST /api/estimates/{id}/drop-request` | `{version, reason}` |
| `POST /api/estimates/{id}/drop-decision` | finance: `{version, decision: "approve"\|"reject", reason}` |
| `POST /api/estimates/upload` | `{filename, content: <base64 CSV/XLSX>, commit: false\|true}` — preview, then commit |
| `POST /api/estimates/{id}/files` | `{filename, content: <base64 pdf/png/jpg>}` |
| `POST /api/estimates/{id}/followups` | `{on_date, kind: Call\|Email\|WhatsApp\|Meeting\|Other, contact, note, next_date}` (sales/finance keys; pending estimates only) |
| `GET /api/followups?min_age=30&sm=&flag=none\|overdue\|ok` | pending estimates older than `min_age` days with their follow-up timelines |
| `GET /api/report/drill?month=2026-10&credit=team&team=Arshdeep&metric=converted` | the estimates behind one dashboard number. `metric` = opening / new / converted / dropped / closing; add `&bucket=31-60` to narrow *closing* to one age group, and `&category=Annual fees` to narrow to one fee type (then each row's `counted` is just that fee type's part); omit `team` for everyone (in team mode a team is `Arshdeep\|Meisheil`, primary first). The rows' `counted` values add up to the figure on the dashboard. |
| `GET /api/report?month=2026-10&credit=team\|primary\|split` | the dashboard numbers |
| `GET /api/export.csv` | all estimates |

`version` is optimistic locking: a stale value returns **409**; re-read and retry.

## Webhook
Admin sets a URL and secret. Events: `estimate.created`, `estimate.updated`, `estimate.drop_requested`, `estimate.followup`, `estimate.change_requested`, `estimate.change_approved`, `estimate.change_rejected`, `estimate.change_withdrawn`, `estimate.received`, `estimate.dropped`, `estimate.reopened`.
```json
{"event": "estimate.received", "at": "2026-10-13T15:02:11",
 "estimate": {"id": 131, "number": "EST-26-27/264", "status": "received", "external_ref": "CRM-DEAL-1042", "total": 100000, "closed_on": "2026-10-13", "invoice_no": "INV-1", "owners": "Arshdeep|Meisheil", "lines": [...]}}
```
Verify: `X-DSR-Signature: sha256=` + HMAC-SHA256(secret, raw body). Delivery is best-effort (one attempt, 8 s timeout, failures are logged), so treat the CRM as eventually consistent and re-sync with `GET /api/estimates` if needed.
