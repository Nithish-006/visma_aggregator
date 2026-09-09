"""
Migration: record where each transaction's category came from.

Additive and idempotent — safe to run repeatedly and safe on existing rows,
which stay NULL ("predates the memory") and keep their categories untouched.

Columns added to every bank transactions table:
  - category_source     VARCHAR(16)   'manual'|'learned'|'suggested'|'keyword'|'credit'
  - category_confidence DECIMAL(4,3)  score behind a learned/suggested answer
  - category_note       VARCHAR(255)  the explanation shown in the dashboard

Why it matters: without a source, the vendor-history categoriser cannot tell a
person's ruling from its own earlier guess, and would end up learning from
itself. That is the one failure mode that degrades quietly rather than visibly.

Usage (from repo root, with .env configured for the target DB):
    python migrations/add_category_source.py
"""

import os
import sys

# Allow running as `python migrations/add_category_source.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DatabaseManager


def main():
    db = DatabaseManager()
    if not db.ensure_connected():
        print("[!] Could not connect to the database. Check your .env settings.")
        sys.exit(1)

    if db.ensure_category_source_columns():
        print("[+] Migration complete: category source columns present on "
              "every bank transactions table.")
    else:
        print("[!] Migration failed — see error above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
