# Factory Data Follow-up Dashboard

A Django dashboard that lets factory managers, supervisors and operators track
**production, quality, downtime and inventory** in near real time - and spot a
problem before it becomes a lost shift.

The dashboard covers six pages (Overview, Production, Downtime, Quality,
Inventory, Reports), a data-entry screen with bulk import, a token-authenticated
ingestion API for machines/PLCs, and an alert engine that mails out when a KPI
crosses its limit. The UI is bilingual (English / Arabic) with a real RTL
layout and works on a shop-floor tablet.

---

## 1. Contents

| Path | What it is |
|------|------------|
| `factory_dashboard/` | Django project: settings, URLs, Celery app |
| `apps/core/` | Domain models, permissions, KPI maths, alert engine, seed command |
| `apps/api/` | DRF serializers, viewsets, IoT ingestion endpoints |
| `apps/dashboard/` | Pages, forms, imports, exports, Celery tasks, templates |
| `templates/` | Base layout (`base.html`) |
| `static/` | CSS, JS and the vendored Bootstrap / Chart.js / HTMX |
| `locale/` | Arabic translation catalogue (`.po` + compiled `.mo`) |
| `assets/fonts/` | DejaVuSans + Noto Naskh Arabic (for the PDF export) |
| `tests/` | pytest suite (81 tests) |
| `deploy/` | gunicorn + nginx configuration |
| `tools/i18n.py` | Portable `extract` / `compile` for the translation catalogue |

---

## 2. Tech stack

* **Django 5.1** + **Django REST Framework 3.15** (+ SimpleJWT)
* **PostgreSQL 16** (SQLite is used automatically when no Postgres env vars are set)
* **Celery 5 + Redis 7** for the background jobs (threshold evaluation, mail)
* **Django templates + HTMX 1.9 + Chart.js 4.4 + Bootstrap 5.3** (vendored, no CDN needed on the shop floor)
* **pytest + pytest-django** for the tests
* **openpyxl** (Excel export) and **reportlab** (PDF export, Arabic aware)

---

## 3. Quick start (laptop, no Postgres)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env

python manage.py migrate
python manage.py seed_demo_data --days 30
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in.

Without `POSTGRES_DB` / `POSTGRES_HOST` the project stores everything in
`db.sqlite3`, and without `REDIS_URL` it uses the local-memory cache - so the
dashboard runs with **zero infrastructure**.

### Demo accounts

`seed_demo_data` creates five users. **Every one of them uses the same
password: `factory123`** (change it with `--password`).

| User | Role | What they can do |
|------|------|------------------|
| `admin` | Admin | Everything: users, factories, lines, machines, thresholds |
| `manager` | Manager | All dashboards + export to Excel/PDF |
| `supervisor` | Supervisor | Only **LINE-A** and the **morning shift**; can enter data |
| `operator` | Operator | Enters data only (production, downtime, defects) |
| `operator2` | Operator | Same, unscoped |

The `admin` account is also a Django superuser, so it is the one account that
can open the Django admin site at <http://127.0.0.1:8000/django-admin/> -
that is where the raw factories, lines, machines, thresholds and users are
edited. The other four roles only ever touch the dashboard itself.

Change a password any time with the standard command:

```bash
python manage.py changepassword admin
```

---

## 4. The pages

| Page | URL | Content |
|------|-----|---------|
| Overview | `/` | 5 KPI cards (today's output, OEE, downtime, defect rate, active alerts), output-vs-target trend, OEE breakdown, output per line, downtime Pareto, open alerts, output per shift |
| Production | `/production/` | Hourly / daily / weekly trend, per-line, per-shift and per-product comparison, latest records table |
| Downtime | `/downtime/` | Pareto by reason, downtime by machine, per-machine timeline, events table |
| Quality | `/quality/` | Defect rate per product and per line, defect-type breakdown (doughnut + table), latest checks |
| Inventory | `/inventory/` | Stock value, low-stock warnings, stock levels, stock movements |
| Reports | `/reports/` | Filter-driven preview + export to **Excel** and **PDF** |
| Data entry | `/data-entry/` | Four HTMX forms: production, downtime, quality, stock |
| Bulk import | `/import/` | CSV / XLSX upload with per-row error report + template downloads |
| Alerts | `/alerts/` | Open / acknowledged / resolved alerts, acknowledge + resolve actions |
| Thresholds | `/thresholds/` | Admin only: create and delete the alert rules |

Every page has the same filter bar (date range, factory, line, shift, product).
The filters live in the query string, so a filtered view can be bookmarked or
shared, and the Excel/PDF exports use exactly the same selection.

### Auto refresh

The KPI cards on the Overview page poll themselves every
`DASHBOARD_REFRESH_SECONDS` (default 45) via HTMX - no page reload, and the
rest of the page stays exactly where the user left it.

---

## 5. Roles and permissions

Four Django groups are created automatically (`Admin`, `Manager`, `Supervisor`,
`Operator`).

| Action | Admin | Manager | Supervisor | Operator |
|--------|:-----:|:-------:|:----------:|:--------:|
| See every factory | ✅ | ✅ | own line only | own line only |
| Data entry | ✅ | ✅ | ✅ | ✅ |
| Export reports | ✅ | ✅ | ❌ | ❌ |
| Manage factories / lines / thresholds | ✅ | ❌ | ❌ | ❌ |

The scoping is **not** only a check in the view: `UserProfile` pins a
supervisor (or an operator) to one factory / line / shift, and every query -
HTML *and* API - is filtered through `scope_for_user()`. A supervisor cannot
read another line's numbers even by changing the query string.

---

## 6. Data entry and bulk import

The four data-entry forms are plain Django forms with server-side validation
(good + defect may never exceed produced, end time after start time, the
machine must belong to the selected line, ...). They post over HTMX, so the
record is saved without a page reload.

Bulk import accepts `.csv` and `.xlsx` (max 10 MB). Column names are matched
loosely - `Line Code`, `line_code` and `line` all work. A template for each
data type can be downloaded from `/import/`.

| Data type | Required columns | Optional |
|-----------|------------------|----------|
| `production` | `line_code`, `shift_code`, `product_code`, `date`, `hour`, `qty_produced` | `machine_code`, `qty_good`, `qty_defect`, `target_qty`, `notes` |
| `downtime` | `machine_code`, `started_at` | `ended_at`, `duration_minutes`, `reason_category`, `reason_code`, `reason_note` |
| `quality` | `line_code`, `product_code`, `checked_at`, `qty_checked` | `machine_code`, `shift_code`, `qty_passed`, `qty_defected`, `defect_type`, `defect_count` |
| `stock` | `product_code`, `warehouse_code`, `movement_type`, `quantity` | `reference_no`, `reason`, `moved_at` |

Dates accept `YYYY-MM-DD`, `DD/MM/YYYY`, `MM/DD/YYYY`; timestamps also accept
`YYYY-MM-DD HH:MM[:SS]`. Rows that fail are reported with their row number -
one bad row never stops the import.

---

## 7. IoT / machine ingestion API

The ingestion endpoints are **token authenticated only** (a session cookie is
rejected) and are **idempotent**: posting the same record twice updates it
instead of creating a duplicate.

Create a token:

```bash
python manage.py create_api_token --username operator --name "PLC line A"
# -> 9f2c1ab4...
```

Send data:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ingest/production/ \
     -H "Authorization: Token 9f2c1ab4..." \
     -H "Content-Type: application/json" \
     -d '{
           "records": [
             {
               "line_code": "LINE-A",
               "machine_code": "LINE-A-M01",
               "shift_code": "M",
               "product_code": "PRD-100",
               "date": "2026-11-07",
               "hour": 9,
               "qty_produced": 120,
               "qty_good": 118,
               "qty_defect": 2,
               "target_qty": 130
             }
           ]
         }'
```

**Response** (`200` when everything was accepted, `207` when only part of the
batch was):

```json
{
  "created": 1,
  "updated": 0,
  "failed": 0
}
```

With a broken row, the response also carries the per-row errors:

```json
{
  "created": 1,
  "updated": 0,
  "failed": 1,
  "errors": [
    {"index": 0, "errors": {"detail": "Unknown line code: 'NOPE'"}}
  ]
}
```

| Endpoint | Body |
|----------|------|
| `POST /api/v1/ingest/production/` | `records[]` as above |
| `POST /api/v1/ingest/downtime/` | `machine_code`, `started_at`, `ended_at?`, `duration_minutes?`, `reason_category?`, `reason_code?`, `reason_note?` |
| `POST /api/v1/ingest/quality/` | `line_code`, `product_code`, `checked_at`, `qty_checked`, `qty_passed?`, `qty_defected?`, `defect_type?`, `machine_code?`, `shift_code?` |
| `POST /api/v1/ingest/stock/` | `product_code`, `warehouse_code`, `movement_type`, `quantity`, `reference_no?`, `reason?`, `moved_at?` |

A bare JSON array is accepted as well as `{"records": [...]}`.

---

## 8. REST API (read)

Base URL `/api/v1/`. Authentication: **token** (`Authorization: Token <key>`),
**JWT** (`Authorization: Bearer <access>`) or **session** cookie.

| Endpoint | Methods | Notes |
|----------|---------|-------|
| `/api/v1/factories/` | GET, POST/PUT/PATCH/DELETE (Admin) | |
| `/api/v1/lines/` | GET, writes (Admin) | filtered by the user's scope |
| `/api/v1/machines/` | GET, writes (Admin) | |
| `/api/v1/shifts/` | GET, writes (Admin) | |
| `/api/v1/products/` | GET, writes (Admin) | |
| `/api/v1/production-logs/` | GET, POST (Supervisor+) | POST fills `recorded_by` + `source` |
| `/api/v1/downtime-events/` | GET, POST (Supervisor+) | |
| `/api/v1/quality-checks/` | GET, POST (Supervisor+) | |
| `/api/v1/inventory/` | GET, writes (Admin) | |
| `/api/v1/stock-movements/` | GET, POST (Supervisor+) | |
| `/api/v1/thresholds/` | GET, writes (Admin) | |
| `/api/v1/alerts/` | GET, POST/PATCH (Admin) | `POST /alerts/{id}/acknowledge/`, `POST /alerts/{id}/resolve/` |
| `/api/v1/me/` | GET | current user, roles and scope |
| `/api/v1/dashboard/summary/` | GET | the KPI cards + OEE + inventory as JSON |
| `/api/v1/health/` | GET | liveness probe (no auth) |

Filter parameters accepted by the list endpoints and by
`/api/v1/dashboard/summary/`:

```
date_from=2026-11-01&date_to=2026-11-07&factory=1&line=2&shift=1&product=3&machine=4
```

Pagination: `?page=2&page_size=100` (max 1000).

**Error envelope** (identical for every endpoint):

```json
{
  "error": {
    "code": 400,
    "message": "Validation failed",
    "fields": {"qty_produced": ["Ensure this value is greater than or equal to 0."]}
  }
}
```

**`GET /api/v1/dashboard/summary/`** returns:

```json
{
  "kpis": [
    {"key": "output", "label": "Today output", "value": 1261, "unit": "pcs",
     "sub": "Target 1308 pcs", "trend": 96.4, "tone": "primary"}
  ],
  "oee": {"availability": 93.36, "performance": 96.03, "quality": 99.66,
          "oee": 89.35, "planned_minutes": 16800, "downtime_minutes": 1115,
          "downtime_hours": 18.58, "ongoing_downtime_events": 1,
          "target": 14901, "produced": 14310, "lines": 5, "days": 7},
  "production": {"produced": 14310, "good": 14265, "defect": 45, "target": 14901,
                 "records": 3720, "defect_rate": 0.31, "good_rate": 99.69,
                 "attainment": 96.03},
  "downtime": {"minutes": 1115, "hours": 18.58, "events": 32, "ongoing": 1,
               "avg_minutes": 34.8},
  "quality": {"checked": 1720, "passed": 1687, "defected": 33, "checks": 255,
               "occurrences": 41, "defect_rate": 1.92, "pass_rate": 98.08},
  "inventory": {"items": 12, "total_qty": 4382.0, "total_value": 512340.55,
                "low_stock": 3, "movements": 135, "qty_in": 2130.0,
                "qty_out": 1844.0},
  "filters": {"date_from": "2026-11-01", "date_to": "2026-11-07"}
}
```

The chart series are also available as plain JSON for a separate frontend:

```
GET /charts/<dataset>/?<filters>
datasets: hourly | daily | weekly | line | shift | product | pareto |
           defect_type | quality_product | quality_line | machine_downtime
```

---

## 9. Alerts and thresholds

A **threshold** is a rule (`metric` + `operator` + `value`) on a scope
(global / factory / line / machine / product). The Celery beat job evaluates
every active threshold **every minute**:

* measured value breaks the rule → an **Alert** is created
* the same rule does not fire again inside its `cooldown_minutes`
* when the KPI recovers, the open alert is **auto-resolved**
* if `notify_email` is on, the alert is mailed to the threshold recipients
  (`ALERTS_RECIPIENTS` always receives a copy)

Supported metrics: `oee`, `availability`, `performance`, `quality`,
`defect_rate`, `downtime_minutes`, `line_stopped_minutes`,
`output_attachment`, `low_stock`.

The seed script installs six realistic rules, e.g. *"Defect rate above 3%"*
(warning, per line) and *"Line stopped for more than 15 minutes"* (critical).

---

## 10. Arabic and RTL

* `LANGUAGES = [("en", "English"), ("ar", "Arabic")]`, `LocaleMiddleware` is
  enabled, and the language can be switched from the sidebar or the login page.
* The template switches between `bootstrap.min.css` and `bootstrap.rtl.min.css`
  and sets `dir="rtl"` on `<html>`.
* The stylesheet uses **logical properties** (`margin-inline-start`,
  `text-align: start/end`, `border-inline-start`), so the layout mirrors
  itself without a second stylesheet.
* Chart.js is told about the direction (`legend.rtl`, `tooltip.rtl`).
* All **407** translatable strings are translated in
  `locale/ar/LC_MESSAGES/django.po`.

GNU `gettext` is not always installed (notably on Windows), so the project
ships a portable replacement:

```bash
python tools/i18n.py extract     # collect the strings into django.po
python tools/i18n.py compile     # write django.mo
python tools/i18n.py stats       # what is still untranslated
```

---

## 11. Tests

```bash
python -m pytest              # 91 tests
python -m pytest tests/test_api.py -v
```

| File | Covers |
|------|--------|
| `tests/test_models.py` | downtime duration, check constraints, defect rate, stock status, shifts |
| `tests/test_permissions.py` | the four roles, supervisor scoping, blocked pages, API scoping |
| `tests/test_kpi_filters.py` | production summary, OEE, measurement window, Pareto, trends, comparisons, filter round-trip, translated labels |
| `tests/test_api.py` | ingestion auth, batch handling, idempotency, per-row errors, summary endpoint |
| `tests/test_views.py` | every page, the HTMX partial, the entry forms, CSV import, Excel/PDF export, export translations |
| `tests/test_alerts.py` | threshold maths, cooldown, auto-resolve, e-mail, Celery tasks |
| `tests/test_i18n.py` | language switch, RTL direction, catalogue completeness |

The suite runs against SQLite by default, so no Postgres is needed for CI.

---

## 12. Deployment

### 12.1 Docker (everything in one command)

```bash
cp .env.example .env          # then edit the secrets
docker compose up -d --build
docker compose exec web python manage.py seed_demo_data --days 30
```

Services: `db` (Postgres 16), `redis` (7), `web` (gunicorn), `worker`
(Celery), `beat` (Celery beat - this is what raises the alerts), `nginx`.

### 12.2 Manual (systemd + nginx)

```bash
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn factory_dashboard.wsgi:application -c deploy/gunicorn.conf.py
```

`deploy/nginx.conf` proxies to the app and serves `/static/` and `/media/`
directly. Point it at your host and add TLS with certbot:

```bash
sudo ln -sf /etc/nginx/sites-available/factory-dashboard /etc/nginx/sites-enabled/
sudo certbot --nginx -d dashboard.example.com
```

### 12.3 Environment variables

Everything is environment driven - see `.env.example` for the full list. The
important ones:

| Variable | Default | Meaning |
|----------|---------|---------|
| `DJANGO_SECRET_KEY` | dev key | **change in production** |
| `DJANGO_DEBUG` | `True` | set to `False` in production |
| `DJANGO_ALLOWED_HOSTS` | localhost | comma separated hostnames |
| `POSTGRES_*` | unset | when `POSTGRES_DB` + `POSTGRES_HOST` are set, Postgres is used |
| `REDIS_URL` | redis://127.0.0.1:6379/0 | cache + Celery broker |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | derived from `REDIS_URL` | |
| `EMAIL_*` | console backend | SMTP for the alert mails |
| `ALERTS_RECIPIENTS` | empty | comma separated, always notified |
| `PLANNED_SHIFT_MINUTES` | `480` | planned time per shift, used for OEE availability |
| `DASHBOARD_REFRESH_SECONDS` | `45` | KPI auto-refresh interval |
| `TIME_ZONE` | `Africa/Cairo` | plant timezone |

### 12.4 Celery

```bash
celery -A factory_dashboard worker -l info
celery -A factory_dashboard beat   -l info
```

`beat` runs the threshold evaluation every minute and refreshes the duration of
ongoing downtime events every five minutes.

### 12.5 Share the running demo on the internet (free)

To let somebody see the dashboard without installing anything, put it behind a
**Cloudflare Quick Tunnel**. It needs no account, no domain and no credit card,
and it costs nothing.

```powershell
winget install Cloudflare.cloudflared          # once
powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1
```

The script prints a public URL such as
`https://virtual-charger-soviet-traditions.trycloudflare.com`. Anybody with
that link can sign in with `admin` / `factory123`.

Stop it again with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1 -Stop
```

**Why the script does more than run `cloudflared`.** The public host name is
only known once the tunnel is up, so the tunnel starts first and Django is
started afterwards with that exact name in `DJANGO_ALLOWED_HOSTS` and
`CSRF_TRUSTED_ORIGINS`. Without the second one the browser rejects the POST
of the login form (and of every data-entry form) as a cross-site request.

Check a running share from anywhere:

```bash
python tools/check_share.py https://xxx.trycloudflare.com --user admin --password factory123
```

It verifies the login page, the health endpoint and a real sign-in, and prints
`RESULT: ok` when the whole chain works.

Two things to know before you use it: the URL is random and dies with the
process, and Cloudflare scopes Quick Tunnels to testing and development - there
is no SLA. For a permanent link use §12.1 (a VPS) instead.

---

## 13. Design notes

**One filter object, everywhere.** `apps/core/services/filters.py` holds a
single `FilterParams` class. Every page, every chart endpoint and both exports
build the same object, so a filter can never behave differently on two pages.

**One place computes the numbers.** `apps/core/services/kpi.py` returns plain
dictionaries - the HTML view, the JSON API and the PDF export all use the same
code, so the PDF can never disagree with the screen.

**OEE** is `Availability x Performance x Quality`:
availability = `(planned - downtime) / planned` (planned = lines x days x
`PLANNED_SHIFT_MINUTES`), performance = `output / target`, quality =
`good / produced`.

The *measurement window* is what the planned time is counted over. Every page
and every API call sends a closed range (`date_from` .. `date_to`), so the
window is simply the number of days in that range. When a caller leaves the
range open - which the export tools and ad-hoc API calls may do - the window
is derived from the data itself (first .. last day of the filtered production
and downtime), so the planned time always matches the downtime it is compared
with. Without that, availability and OEE would collapse to zero for a
"whole history" query.

**The PDF is Arabic aware.** `arabic-reshaper` + `python-bidi` reshape the text
and `DejaVuSans` (bundled in `assets/fonts/`) carries both the Latin glyphs and
the Arabic presentation forms, so a mixed Arabic/English report renders
correctly.

**The alert engine is plain Python.** `evaluate_thresholds()` can be called by
the Celery beat, by the "Run check now" button, or from a test - the Celery
task is a five-line wrapper.

**Vendored front-end assets.** Bootstrap, Chart.js and HTMX are committed under
`static/vendor/`, so the shop floor does not need internet access.

---

## 14. Common tasks

```bash
python manage.py seed_demo_data --days 60 --reset   # fresh demo data
python manage.py create_api_token --username operator --name "PLC"
python tools/i18n.py extract && python tools/i18n.py compile
python -m pytest
python manage.py runserver
```

Share it with somebody (see §12.5):

```powershell
powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1        # start
powershell -ExecutionPolicy Bypass -File tools/share_demo.ps1 -Stop  # stop
```

### Visual QA without signing in

`tools/_preview.py` renders every authenticated page to static HTML (English
and Arabic) under `static/_preview/`, and `tools/_preview_pdf.py` writes the
Excel/PDF exports next to it. Handy to check a layout or a translation in the
browser without logging in:

```bash
python tools/_preview.py        # -> static/_preview/*.html  (EN + AR)
python tools/_preview_pdf.py    # -> static/_preview/report_en.pdf, report_ar.pdf
```

The output folder is git-ignored; the helpers need the demo users to exist,
so run `seed_demo_data` first.
