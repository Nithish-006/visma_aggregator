"""
Migration: create the vendor-identity ruling tables.

Adds `vendor_aliases` (spellings a person has declared to be one supplier) and
`vendor_alias_splits` (pairs they have declared to be different suppliers).
Both feed helpers/bill_reconcile.py's matcher, which is good but cannot be
perfect: no rule reads off the names that "PANDP" is the bank clerk's spelling
of "P&P ROOFING", so a person settles those once and the answer is kept here.

Additive and idempotent — safe to run repeatedly, and it creates nothing that
existing reads depend on. With no rows present, matching behaves exactly as it
did before aliases existed.

The app also calls ensure_vendor_alias_tables() at startup, so a normal deploy
creates these without running this script. It is here for environments brought
up out of band, and to make the schema change reviewable on its own.

Usage (from repo root):
    # default: uses .env (local dev)
    python migrations/add_vendor_aliases.py

    # target another environment without touching .env:
    python migrations/add_vendor_aliases.py --env-file .env.prod
"""

import os
import sys

# Allow running as `python migrations/add_vendor_aliases.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Optional --env-file must be loaded (with override) BEFORE importing database,
# because config.py calls load_dotenv() at import time and won't overwrite vars
# already present in the environment.
if '--env-file' in sys.argv:
    idx = sys.argv.index('--env-file')
    try:
        env_path = sys.argv[idx + 1]
    except IndexError:
        print("[!] --env-file requires a path, e.g. --env-file .env.prod")
        sys.exit(2)
    if not os.path.exists(env_path):
        print(f"[!] Env file not found: {env_path}")
        sys.exit(2)
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    print(f"[i] Loaded environment from {env_path}")

from database import DatabaseManager


def main():
    db = DatabaseManager()
    if not db.ensure_connected():
        print("[!] Could not connect to the database. Check your .env settings.")
        sys.exit(1)

    if not db.ensure_vendor_alias_tables():
        print("[!] Could not create the vendor alias tables.")
        sys.exit(1)

    rules = db.get_vendor_alias_rules()
    print(f"[+] vendor_aliases and vendor_alias_splits ready "
          f"({len(rules.get('links') or {})} links, "
          f"{len(rules.get('splits') or [])} splits on file).")


if __name__ == '__main__':
    main()
