# Daily Sales Report

A small web dashboard that replaces the daily "Revenue" Excel + email. **Sales** enter estimates, **Finance** records
receipts/drops and targets, and everyone sees the same live roll-forward, ageing and sales-manager matrix.
No dependencies to run (Python 3.10+ standard library, SQLite, vanilla JS). `openpyxl` is only needed for the one-time import.

## Run

```bash
python3 -m dsr                      # http://localhost:8080 ; first run prints the admin password once
PORT=9000 HOST=0.0.0.0 python3 -m dsr
pip install openpyxl && python3 -m dsr.import_xlsx Revenue.xlsx --as-of 2026-10-13   # one-time legacy load
python3 -m unittest discover -s tests -t .
```
Then sign in as `admin`, add users (Admin tab): `sales` users are linked to a sales manager, `finance` users are not.
Data lives in `data/dsr.sqlite3` (git-ignored; back it up). Put it behind HTTPS (reverse proxy) before exposing it.

## Who does what
| | Sales | Finance | Admin |
|---|---|---|---|
| View dashboard / all estimates | ✔ | ✔ | ✔ |
| Raise / edit pending estimate | own only | – | ✔ |
| Propose a drop (reason required) | own only | – | – |
| Record payment + tax invoice | – | ✔ | ✔ |
| Approve/reject/make a drop | – | ✔ | ✔ |
| Monthly targets, publish daily report | – | ✔ | ✔ |
| Reopen closed estimate, users, SM list | – | – | ✔ |

## Rules
See `dsr/rules.py` and the in-app **Rules** tab. In short: unique estimate numbers; one estimate has one status and several
fee lines (Annual / Set-up / Integration / Customisation); no future dates; invoice number mandatory to mark received;
closed estimates locked; every change audited; optimistic locking on edits.
**Closing = Opening + New − Converted − Dropped**, computed from each estimate's report month and close date, so any month / as-on date works.

## Layout
`dsr/` server, rules, importer · `web/` UI · `tests/` rule tests.
