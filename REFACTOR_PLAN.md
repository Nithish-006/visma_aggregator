# app.py Decoupling Plan

**Goal:** Split the 7,121-line `app.py` (~140 routes) into an application-factory +
Flask-blueprints layout with clean separation of concerns, so each feature area can be
worked on in isolation without scrolling past unrelated code.

**Strategy (chosen):** Incremental — **one blueprint per PR**. The app stays fully
working between every step. Each PR touches ~600 lines, so review and `git bisect` stay
cheap.

**Non-goal:** No behavior changes. This is a pure structural move. Endpoint URLs stay
identical. Any change in response output is a bug.

---

## 1. Why the file is big but not knotted

The routes are already cleanly separated by URL prefix — there is almost no cross-feature
tangling. The only things that actually couple the file together are:

1. **Shared mutable global state** — `df_cache`, `df_global`, `db_manager`,
   `db_connected`. 174 references; rebound via `global` in 7 places
   (lines 68, 117, 127, 190, 687, 1684, 2346). This is the one real hazard in a split.
2. **Top-of-file helpers** (lines 33–647) used across many domains: data loading,
   dataframe filters, project-stem matching, formatting.
3. **One mega-route** — `export_project_summary` is ~1,290 lines (5828→7119).
4. **A few helpers shared by two domains** — bills and sales share invoice
   reprocess/validation logic (`_reprocess_invoice`, `_set_invoice_validation`,
   `_extraction_to_flat`, `_locate_invoice_file`).

Everything else is a straight cut-and-paste into a blueprint.

---

## 2. Target file layout

```
app.py                        # thin: create_app(), run server            (~40 lines)
extensions.py                 # db_manager singleton + shared state object
auth.py                       # login_required + login/logout/index/sw.js
helpers/
  __init__.py
  bankdata.py                 # load_bank_data_from_db, get_bank_df, reload_bank_data
  dataframe.py                # filter_by_date_range/category/vendor/project,
                              #   robust_filter_by_project, parse_month_filter,
                              #   filter_by_months, reload_data,
                              #   load_financial_data_from_db/excel
  projects.py                 # get_project_stems, normalize_project_stem,
                              #   build_smart_project_groups, match_bills_to_*,
                              #   match_labour_to_*, parse_project_selection,
                              #   project_value_matches_selection
  formatting.py               # format_indian_number, sanitize_for_excel, safe_col_width
  invoices.py                 # SHARED by bills+sales: _locate_invoice_file,
                              #   _extraction_to_flat, _reprocess_invoice,
                              #   _set_invoice_validation, extract_project_from_filename
blueprints/
  __init__.py
  banks.py                    # /dashboard, /charts, /edit-transactions, /api/<bank>/*
  projects.py                 # /projects, /api/projects/*, cash-payments, PO, admin
  personal.py                 # /personal-tracker, /api/personal/*
  bills.py                    # /bill-processor, /api/bills/*
  sales.py                    # /sales-processor, /api/sales/*
  legacy.py                   # /api/upload, /api/summary, /api/transactions, ...
  project_summary.py          # /project-summary, /api/project-summary/* (minus export)
reports/
  __init__.py
  project_summary_export.py   # the 1,290-line export, one builder fn per Excel sheet
```

---

## 3. The critical move — eliminate global-state coupling

Blueprints cannot do `from app import df_cache` without a circular import, and the four
globals are rebound with `global`, so a naive `from extensions import df_cache` would give
each blueprint a stale copy after the first reload.

**Fix:** put the singleton and a *mutable container* in `extensions.py`, and replace every
`global X` rebind with in-place mutation so all blueprints share one live object.

```python
# extensions.py
from database import DatabaseManager

db_manager = DatabaseManager()

class _State:
    def __init__(self):
        self.df_cache = {}       # bank_code -> DataFrame
        self.df_global = None    # legacy
        self.db_connected = False

state = _State()
```

Then, everywhere today does:

```python
global df_cache
df_cache[bank_code] = df          # mutation — fine
df_cache = {}                     # REBIND — the dangerous pattern
```

becomes:

```python
from extensions import state
state.df_cache[bank_code] = df    # mutation — unchanged semantics
state.df_cache.clear()            # replaces the rebind-to-{} (clear-cache route, 1684)
state.df_global = ...             # attribute set on shared object, not a module rebind
```

The 7 `global` sites map as:

| line | today | becomes |
|------|-------|---------|
| 68   | `global db_manager, db_connected` | `state.db_connected = True/False` |
| 117  | `global df_cache` (set key) | `state.df_cache[...] = ...` |
| 127  | `global df_cache` (set key) | `state.df_cache[...] = ...` |
| 190  | `global df_global` | `state.df_global = ...` |
| 687  | `global db_connected` | `state.db_connected = ...` |
| 1684 | `global df_cache, df_global` (clear-cache) | `state.df_cache.clear(); state.df_global = None` |
| 2346 | `global db_connected` | `state.db_connected = ...` |

This is the only step with behavioral subtlety. It lands in Phase 1 and is covered by the
Phase 0 smoke test plus a manual check of `/api/clear-cache` and an upload (which trigger
the rebind paths).

---

## 4. Application factory

`app.py` collapses to:

```python
from flask import Flask
from config import Config
import os

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.secret_key = os.environ.get('SECRET_KEY', 'visma-finance-secret-key-2024-secure')
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    from auth import bp as auth_bp
    from blueprints.banks import bp as banks_bp
    from blueprints.projects import bp as projects_bp
    from blueprints.personal import bp as personal_bp
    from blueprints.bills import bp as bills_bp
    from blueprints.sales import bp as sales_bp
    from blueprints.legacy import bp as legacy_bp
    from blueprints.project_summary import bp as ps_bp
    for bp in (auth_bp, banks_bp, projects_bp, personal_bp,
               bills_bp, sales_bp, legacy_bp, ps_bp):
        app.register_blueprint(bp)
    return app

app = create_app()   # keep module-level `app` so gunicorn `app:app` still works

if __name__ == '__main__':
    app.run(debug=True, port=5000)
```

`login_required` moves to `auth.py` and is imported by every blueprint. Blueprints are
created with `bp = Blueprint('bills', __name__)` and routes become `@bp.route(...)`.

---

## 5. Per-blueprint route assignments

Line numbers are from the current `app.py`.

### `auth.py`  (~120 ln)
- `login_required` decorator (33)
- `/login` (775), `/logout` (800), `/sw.js` (811), `/` index (816)

### `blueprints/banks.py`  (~700 ln)
- pages: `/dashboard/<bank_code>` (1634), `/edit-transactions/<bank_code>` (1648),
  `/charts/<bank_code>` (1662)
- `/api/clear-cache` (1680), `/api/hub/stats` (1690)
- `/api/<bank_code>/`: summary (1716), monthly_trend (1808), category_breakdown (1858),
  running_balance (1900), top_vendors (1959), categories (2000), date_range (2032),
  transactions (2052), transactions/paginated (2119), filter-options (2211),
  insights (2240), upload (2311), transaction/update (2412), transaction/split (2523),
  download_transactions (2659)

### `blueprints/projects.py`  (~800 ln)
- `/projects` (929)
- `/api/projects` GET (1000) / POST (1008); `/api/projects/<id>` PATCH (1100)
- cash-payments: GET (1159), POST (1169), DELETE (1207)
- `/api/projects/<id>/insights` (1222), `/upload-po` (1367), `/po` GET (1568),
  `/po-data` GET (1580) / PUT (1617), `/process-po` (1591)
- admin: `/api/admin/normalize-projects` (1411), `/api/admin/uppercase-canonical-stems` (1492)
- private helpers that move with it: `validate_project_value` (862),
  `_project_po_allowed` (849), `_canonical_project_set` (853),
  `_po_summary_for_response` (883), `_run_po_extraction` (892),
  `_attach_client_payments` (935), `_po_and_payments_for_project` (979),
  `_cash_payment_summary` (1146)

### `blueprints/personal.py`  (~570 ln)
- pages: `/personal-tracker` (2728), `/add` (2735), `/edit/<id>` (2742)
- `/api/personal/transactions` GET (2782) / POST (2858) / PUT (2914) / DELETE (2974)
- `/api/personal/`: export (3002), summary (3164), projects (3284), vendors (3308),
  descriptions (3330)

### `blueprints/bills.py`  (~700 ln)
- `/bill-processor` (3356)
- `/api/bills/`: process (3365), download (3455), stored (3485), stored/<id> (3526),
  DELETE (3545), project PUT (3561), projects (3582), summary (3597), stats (3693),
  file (3712), upload-files (3757), stored PUT (3831), revalidate (4027),
  reprocess (4041), `<id>/validation` (4080)
- uses shared `helpers/invoices.py`

### `blueprints/sales.py`  (~470 ln)
- `/sales-processor` (4106)
- `/api/sales/`: reprocess (4052), process (4117), download (4211), stored (4238),
  stored/<id> (4275), DELETE (4293), project PUT (4308), projects (4328),
  summary (4342), stats (4435), file (4453), upload-files (4492), stored PUT (4556),
  `<id>/validation` (4087)
- uses shared `helpers/invoices.py`

### `blueprints/legacy.py`  (~520 ln)  — non-bank-scoped, backwards-compat
- `/api/upload` (649), `/api/upload_history` (757)
- `/api/`: summary (4585), monthly_trend (4661), category_breakdown (4701),
  running_balance (4733), top_vendors (4783), categories (4816), months (4823),
  date_range (4840), transactions (4858), transaction/update (4922),
  download_transactions (5037), insights (5106)

### `blueprints/project_summary.py`  (~650 ln)
- `/project-summary` (5169)
- `/api/project-summary/`: combined (5176), bank-transactions (5455), vendors (5511),
  project-cards (5576), projects (5628), filter-options (5664), bills (5730),
  sales-bills (5770), date-range (5810)
- `export` (5826) delegates to `reports/project_summary_export.py`

### `reports/project_summary_export.py`
- `export_project_summary` (5828–7119), refactored into one builder function per Excel
  sheet (summary tab, per-bank tabs, vendor tab, etc.), called by a thin orchestrator.

---

## 6. Migration sequence (one PR each)

| Phase | PR | Risk | Validation |
|-------|----|----|------------|
| 0 | **Route-map smoke test** — boot app, snapshot `{(rule.rule, tuple(sorted(rule.methods))) for rule in app.url_map.iter_rules()}` to a fixture; assert the live set equals it. **Key on URL + methods, NOT `rule.endpoint`** — endpoint names intentionally change under blueprints (`login`→`auth.login`), so including them would fail the test spuriously every phase. Plus a boot test that imports `app:app`. | none | new test passes on current code |
| 1 | **`extensions.py` + `helpers/*`** — move singleton, state object, and all pure helpers; convert the 7 `global` sites to `state.*`; `app.py` imports them back. | low (state semantics) | smoke test; manual `/api/clear-cache` + one upload |
| 2 | **`create_app()` factory + `auth` blueprint** — convert to factory, register `auth` as the proof blueprint. | low | smoke test; login/logout by hand |
| 3 | `personal` blueprint | low | smoke test |
| 4 | `sales` blueprint (+ `helpers/invoices.py`, shared) | med | smoke test; one sales reprocess |
| 5 | `bills` blueprint (reuses `helpers/invoices.py`) | med | smoke test; one bill reprocess + revalidate |
| 6 | `banks` blueprint | med | smoke test; load a dashboard |
| 7 | `legacy` blueprint | low | smoke test |
| 8 | `projects` blueprint | med | smoke test; create/patch a project, upload PO |
| 9 | `project_summary` blueprint | med | smoke test; open project summary |
| 10 | extract `reports/project_summary_export.py` | med | smoke test; download the Excel export, diff against a pre-refactor copy |

Ordering rationale: blueprints land in increasing-coupling order, so the first moves are
the safest and build confidence in the pattern before the project/summary code (which
leans hardest on the shared helpers).

---

## 7. The two known footguns

1. **Blueprint-namespaced endpoints.** `@bp.route` names become `auth.login`,
   `bills.process_bill`, etc., so existing `url_for('<name>')` calls must be rewritten.
   **Measured exposure (greps run):**
   - **Templates: zero risk.** All 34 `url_for` calls in `templates/` are
     `url_for('static', filename=...)`. `static` is Flask's built-in endpoint and is
     unaffected by blueprints. Nothing in templates needs to change.
   - **Python `app.py`: 9 call sites, 3 endpoints.** These *will* break and must be
     updated to absolute blueprint names:

     | call site(s) | today | becomes |
     |--------------|-------|---------|
     | 42 (`login_required`), 804 (logout) | `url_for('login')` | `url_for('auth.login')` |
     | 780, 793 (login), 1639/1653/1667 (bank pages) | `url_for('index')` | `url_for('auth.index')` |
     | 2776, 2779 (edit_expense_page) | `url_for('add_expense_page')` | `url_for('personal.add_expense_page')` |

     `index` is referenced cross-blueprint (from the bank pages in `banks.py`), so absolute
     naming — not the leading-dot relative form — is the rule everywhere. **The route-map
     smoke test does NOT catch this** (it's resolved at request time, not registration), so
     each phase that moves one of these targets or callers must update the strings by hand
     and exercise the redirect (e.g. hit a protected page logged-out → expect `/login`).
2. **The state rebind.** Covered in §3. The clear-cache route (1684) and the upload paths
   are the ones to exercise by hand after Phase 1.

---

## 8. Definition of done

- `app.py` ≤ ~50 lines; no blueprint > ~800 lines.
- `gunicorn app:app` and `python app.py` both still work (module-level `app` preserved).
- Route-map smoke test green — i.e. **the exact same set of URLs** is served.
- No `global` statements remain; shared state goes through `extensions.state`.
- Each feature area lives in one file you can open without scrolling past another feature.
