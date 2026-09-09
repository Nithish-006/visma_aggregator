# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VISMA Financial App is a Flask-based web application for processing and categorizing bank statements with multi-bank support (Axis Bank and Karur Vysya Bank). It provides transaction management, financial analytics, and a personal expense tracker.

## Commands

### Local Development
```bash
# Install dependencies (use virtual environment)
pip install -r requirements.txt

# Initialize/reset database
python init_production_db.py

# Run development server
python app.py
# Server runs at http://localhost:5000

# Generate a new secret key
python generate_secret_key.py
```

### Production
```bash
# Uses Gunicorn with nixpacks.toml config
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
```

## Architecture

### Backend Structure
- **app.py**: Main Flask application with all routes and API endpoints
  - Authentication via session-based login (`login_required` decorator)
  - Multi-bank support with bank-specific API endpoints (`/api/<bank_code>/...`)
  - Legacy API endpoints for backwards compatibility (`/api/summary`, `/api/transactions`)
  - Personal transaction tracker endpoints (`/api/personal/...`)
  - Bank/legacy dataframes are read fresh from the DB per request (memoized only within a request via Flask `g`), so all gunicorn workers stay consistent after an edit — see `helpers/bankdata.py` (`get_bank_df`) and `helpers/dataframe.py` (`get_legacy_df`)

- **config.py**: Configuration and bank settings
  - `BANK_CONFIG` dict defines banks (currently `axis` and `kvb`) with table names and colors
  - Helper functions: `get_bank_config()`, `get_bank_table()`, `allowed_file()`
  - Environment variables for database connection (DB_HOST, DB_USER, etc.)
  - `USE_DATABASE` toggle between MySQL and Excel file modes

- **database.py**: `DatabaseManager` class handles MySQL operations
  - Per-request connection pattern via `get_connection()` context manager
  - Bank-specific table routing via `get_table_name(bank_code)`
  - Bulk transaction insertion with duplicate detection

- **bank_statement_processor.py**: Parses bank statement Excel files
  - Auto-detects header row in Excel files
  - Fuzzy column name matching for various statement formats
  - Transaction categorization based on keyword patterns in `CATEGORY_PATTERNS`
  - Extracts vendor names from UPI/IMPS/NEFT transaction descriptions

### Database Schema
- Bank-specific transaction tables: `axis_transactions`, `kvb_transactions`
- Legacy `transactions` table for backwards compatibility
- `personal_transactions` for personal expense tracker
- `bank_upload_history` logs file uploads per bank
- `categories` reference table with 10 expense categories
- Analytics views: `v_axis_transaction_summary`, `v_kvb_transaction_summary`

### Frontend Structure
- **Templates** (`/templates`): 6 HTML files with dark theme
- **Static** (`/static`): CSS and JS files paired by feature (e.g., `personal_tracker.css` + `personal_tracker.js`)
- Uses Chart.js for analytics visualizations

### Key Routes
- `/` → Hub (bank selection)
- `/dashboard/<bank_code>` → Bank transactions: filter/search/page **and** edit in place
  (click-to-edit cells, bulk apply, split). Rendered by `templates/index.html`,
  driven by `static/edit_transactions.{css,js}`.
- `/edit-transactions/<bank_code>` → retired; redirects to the dashboard, preserving the
  query string (the material-reconciliation panel deep-links pre-filtered)
- `/charts/<bank_code>` → Analytics charts
- `/personal-tracker` → Personal expense entry

### Key Patterns
- API endpoints return Indian rupee formatting via `format_indian_number()` (lakhs/crores format)
- Date filtering uses `filter_by_date_range()` helper
- All protected routes use `@login_required` decorator
- Bank code validation via `VALID_BANK_CODES` from config

## Environment Variables

Required in `.env`:
```
SECRET_KEY=<flask-secret-key>
DB_HOST=<mysql-host>
DB_DATABASE=visma_financial
DB_USER=<mysql-user>
DB_PASSWORD=<mysql-password>
DB_PORT=3306

# Bill Processor AI Keys (at least one required)
OPENROUTER_API_KEY=<openrouter-key>  # Primary: Nemotron (free, OCR-optimized)
GEMINI_API_KEY=<gemini-key>          # Fallback: Gemini 2.0 Flash
```

## Adding a New Bank

1. Add entry to `BANK_CONFIG` in `config.py` with name, code, table, and color
2. Create transaction table in `database_schema.sql` (copy from existing bank table)
3. Add corresponding analytics view

## Transaction Categories

Categories are defined in `bank_statement_processor.py` with pattern matching:
- OFFICE EXP (OE), FACTORY EXP (FE), SITE EXP (SE), TRANSPORT EXP (TE)
- MATERIAL PURCHASE (MP), DUTIES & TAX (DT), SALARY AC (SA), BANK CHARGES (BC)
- AMOUNT RECEIVED (AR) - auto-assigned to all credit transactions

Users have since typed many more (CRANE RENT, AUTO RENT, CAPITAL AC, LABOUR
PAYMENT, ...) that appear in no keyword list, so keyword scoring alone cannot
reach them. See below.

### Categorisation on upload

`decide_category()` in `bank_statement_processor.py` decides one row, in order:

1. **Credit → AMOUNT RECEIVED**, structurally, from the DR/CR flag.
2. **Vendor + payment-remark history** (`helpers/category_memory.py`), when
   confident enough. This is the only path that can produce the typed-in
   categories above.
3. **Keyword scoring** (`categorize_transaction`), unchanged, as fallback.

The memory is built once per upload by `helpers/category_loader.py` from rows
already settled in the bank table, grouped by the vendor-identity rules in
`helpers/bill_reconcile.py` — so vendor aliases taught to the material
reconciler improve categorisation too. The second signal is the remark the
payer typed, which both banks carry in a family-specific narration slot
(`extract_purpose`); NEFT/RTGS narrations end in a *branch*, not a remark.

Provenance is stored per row in `category_source` / `category_confidence` /
`category_note` (migration: `migrations/add_category_source.py`). A human edit
stamps `'manual'`, which is what stops the memory learning from its own
guesses. Rows scored between `REVIEW_CONFIDENCE` and `AUTO_APPLY_CONFIDENCE`
stay UNCATEGORIZED and surface under the dashboard's "Needs review" filter.

**Some categories are never auto-applied.** SITE vs FACTORY EXPENSES (and the
TRANSPORT/rent family) are separated by *which job the work was for*, which
appears nowhere in a bank statement — the same payee, same remark, same amount,
days apart, goes both ways. `CONTESTED_CATEGORY_GROUPS` lists them; when the
winner and runner-up sit in one group and the runner-up holds a real share, the
row is held for the user to assign however high the score. They are still
learned from — only genuinely divided payees stop.

Thresholds are measured, not chosen — re-run
`python scripts/category_memory_dryrun.py --prod` after new statements land.
