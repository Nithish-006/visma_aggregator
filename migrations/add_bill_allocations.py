"""
Migration: create the per-project split ledger for purchase bills.

Adds table `bill_project_allocations` and backfills one allocation per
existing bill (the unsplit default: the whole bill on its current project).
Then verifies that every bill's allocations sum to its own subtotal / GST /
total_amount to the paisa.

Additive and idempotent — safe to run repeatedly. Existing numbers are NOT
changed: the backfill only seeds bills that have no allocation yet, each with
the bill's own totals, so per-project reports read identically before and
after.

Usage (from repo root):
    # default: uses .env (local dev)
    python migrations/add_bill_allocations.py

    # target another environment without touching .env:
    python migrations/add_bill_allocations.py --env-file .env.prod
"""

import os
import sys

# Allow running as `python migrations/add_bill_allocations.py` from repo root.
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

    # --reset drops and recreates the ledger, then re-backfills from scratch.
    # Safe ONLY while no bill is split (each bill just gets its full-total
    # default back). Use it to pick up a schema change on an env that already
    # ran an earlier version of this migration.
    if '--reset' in sys.argv:
        print("[!] --reset: dropping bill_project_allocations and rebuilding "
              "(safe only while no bill is split).")
        try:
            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DROP TABLE IF EXISTS bill_project_allocations")
                conn.commit()
                cur.close()
            print("[+] Dropped existing bill_project_allocations.")
        except Exception as e:
            print(f"[!] Could not drop table: {e}")
            sys.exit(1)

    if not db.ensure_bill_allocations_table():
        print("[!] Migration failed while creating bill_project_allocations.")
        sys.exit(1)

    seeded = db.backfill_bill_allocations()
    if seeded < 0:
        print("[!] Migration failed while backfilling allocations.")
        sys.exit(1)
    print(f"[+] Backfill complete: {seeded} bill(s) seeded.")

    report = db.verify_bill_allocations()
    print("[i] Verification:")
    print(f"    bills total              : {report['bills_total']}")
    print(f"    bills with allocations   : {report['bills_with_allocations']}")
    print(f"    bills missing allocations: {report['bills_missing_allocations']}")

    mismatches = report.get('mismatches', [])
    if report.get('error'):
        print(f"[!] Verification error: {report['error']}")
        sys.exit(1)
    if mismatches:
        print(f"[!] {len(mismatches)} bill(s) do NOT reconcile:")
        for m in mismatches[:20]:
            print(f"      - invoice {m.get('invoice_number')} (id {m.get('invoice_id')}): {m}")
        if len(mismatches) > 20:
            print(f"      ... and {len(mismatches) - 20} more")
        sys.exit(1)

    print("[+] Migration complete: all bills reconcile to their allocations.")


if __name__ == '__main__':
    main()
