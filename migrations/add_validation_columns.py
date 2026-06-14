"""
Migration: add reconciliation/validation columns to bill_invoices and
sales_invoices.

Additive and idempotent — safe to run repeatedly and safe on existing rows
(they default to validation_status='review' until re-checked by the validator
or the C1 batch script `validate_existing_bills.py`).

Columns added to BOTH tables:
  - validation_status ENUM('ok','review') DEFAULT 'review'
  - validation_diff   DECIMAL(12,2) DEFAULT 0     (signed header-identity gap)
  - validation_notes  TEXT                         (human-readable failure list)

Usage (from repo root, with .env configured for the target DB):
    python migrations/add_validation_columns.py
"""

import os
import sys

# Allow running as `python migrations/add_validation_columns.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager


def main():
    db = DatabaseManager()
    if not db.ensure_connected():
        print("[!] Could not connect to the database. Check your .env settings.")
        sys.exit(1)

    ok = db.ensure_validation_columns()
    if ok:
        print("[+] Migration complete: validation columns present on "
              "bill_invoices and sales_invoices.")
    else:
        print("[!] Migration failed — see error above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
