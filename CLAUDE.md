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
# Uses Gunicorn (defined in Procfile)
gunicorn app:app
```

## Architecture

### Backend Structure
- **app.py**: Main Flask application with all routes and API endpoints
  - Authentication via session-based login (`login_required` decorator)
  - Multi-bank support with bank-specific API endpoints (`/api/<bank_code>/...`)
  - Legacy API endpoints for backwards compatibility (`/api/summary`, `/api/transactions`)
  - Personal transaction tracker endpoints (`/api/personal/...`)
  - Data caching with `df_cache` for bank dataframes, `df_global` for legacy support

- **config.py**: Configuration and bank settings
  - `BANK_CONFIG` dict defines banks (currently `axis` and `kvb`) with table names and colors
  - Environment variables for database connection (DB_HOST, DB_USER, etc.)
  - `USE_DATABASE` toggle between MySQL and Excel file modes

- **database.py**: `DatabaseManager` class handles MySQL operations
  - Connection resilience with auto-reconnect (`ensure_connected()`, `execute_with_retry()`)
  - Bank-specific table routing via `get_table_name(bank_code)`
  - Bulk transaction insertion with duplicate detection

- **bank_statement_processor.py**: Parses bank statement Excel files
  - Auto-detects header row in Excel files
  - Fuzzy column name matching for various statement formats
  - Transaction categorization based on keyword patterns
  - Extracts vendor names from UPI/IMPS/NEFT transaction descriptions

### Database Schema
- Bank-specific transaction tables: `axis_transactions`, `kvb_transactions`
- Legacy `transactions` table for backwards compatibility
- `personal_transactions` for personal expense tracker
- `bank_upload_history` logs file uploads per bank
- `categories` reference table with 10 expense categories (OFFICE EXP, FACTORY EXP, etc.)

### Frontend Pages
- **Hub** (`/`): Bank selection page showing transaction counts per bank
- **Dashboard** (`/dashboard/<bank_code>`): Financial analytics with charts
- **Edit Transactions** (`/edit-transactions/<bank_code>`): Bulk transaction editing
- **Personal Tracker** (`/personal-tracker`): Manual expense entry

### Key Patterns
- API endpoints return Indian rupee formatting via `format_indian_number()` (lakhs/crores format)
- Date filtering uses `filter_by_date_range()` helper
- All protected routes use `@login_required` decorator
- Database queries use `execute_with_retry()` for connection resilience

## Environment Variables

Required in `.env`:
```
SECRET_KEY=<flask-secret-key>
DB_HOST=<mysql-host>
DB_DATABASE=visma_financial
DB_USER=<mysql-user>
DB_PASSWORD=<mysql-password>
DB_PORT=3306
```

## Transaction Categories

Categories are defined in `bank_statement_processor.py` with pattern matching:
- OFFICE EXP (OE), FACTORY EXP (FE), SITE EXP (SE), TRANSPORT EXP (TE)
- MATERIAL PURCHASE (MP), DUTIES & TAX (DT), SALARY AC (SA), BANK CHARGES (BC)
- AMOUNT RECEIVED (AR) - auto-assigned to all credit transactions
