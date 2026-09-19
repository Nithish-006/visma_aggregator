"""Bring an already-synced tracker window back in line with the bank statement.

The sync button copies each bank row as it stands at that moment. Anything
tagged afterwards -- a project attributed, a category corrected, a payment
split across projects -- leaves the tracker holding the stale version
("General", "Uncategorized"). This re-pairs the two sides over a window and
makes the tracker say exactly what the bank now says.

    python scripts/tracker_resync.py --start 2026-08-18                # preview
    python scripts/tracker_resync.py --start 2026-08-18 --commit       # write

Orphans (tracker rows with no bank row left behind them -- typically the
pre-split single payment whose parts now appear as inserts) are left alone
unless --delete-orphans is passed. Default is a dry-run; --env picks the
dotenv file (.env.prod for production).
"""

import argparse
import os
import sys

import mysql.connector
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.tracker_sync import (  # noqa: E402
    BANK_TABLES, apply_refresh, build_refresh_plan, get_bank_latest,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bank', default='axis', choices=sorted(BANK_TABLES))
    ap.add_argument('--start', required=True, help='first date to reconcile (YYYY-MM-DD)')
    ap.add_argument('--end', help='default: the last date the statement covers')
    ap.add_argument('--env', default='.env.prod')
    ap.add_argument('--commit', action='store_true')
    ap.add_argument('--delete-orphans', action='store_true',
                    help='delete tracker rows the bank no longer backs')
    args = ap.parse_args()

    cfg = dotenv_values(args.env)
    conn = mysql.connector.connect(
        host=cfg['DB_HOST'], port=int(cfg['DB_PORT']), user=cfg['DB_USER'],
        password=cfg['DB_PASSWORD'], database=cfg['DB_DATABASE'])
    cur = conn.cursor(dictionary=True)

    end = args.end or get_bank_latest(cur, args.bank)
    plan = build_refresh_plan(cur, args.bank, args.start, end)

    print(f"{args.bank}  window {plan['start']}..{plan['end']}   "
          f"update {len(plan['updates'])}   insert {len(plan['inserts'])}   "
          f"orphan {len(plan['orphans'])}\n")

    print("UPDATE   (* = paired by statement order; another bank row that day "
          "carries the same amount)")
    for u in plan['updates']:
        print(f"  {'*' if u['ordered'] else ' '}#{u['tracker_id']}  {u['date']}  "
              f"{u['amount']:>11}  {u['transaction_type']}")
        for field, (was, now) in u['changes'].items():
            print(f"       {field:<12} {was!r}  ->  {now!r}")

    print('\nINSERT (in the bank, missing from the tracker)')
    for r in plan['inserts']:
        print(f"  {r['date']}  {r['amount']:>11}  {r['transaction_type']:<8}"
              f"{r['vendor'][:28]:30}{r['description'][:22]:24}{r['project']}")

    print('\nORPHAN (in the tracker, no bank row behind it)'
          + ('' if args.delete_orphans else '  -- kept; pass --delete-orphans to remove'))
    for o in plan['orphans']:
        print(f"  #{o['tracker_id']}  {o['date']}  {o['amount']:>11}  "
              f"{o['transaction_type']:<8}{o['vendor'][:28]:30}{o['project']}")

    if not args.commit:
        print('\nDRY RUN -- nothing written. Re-run with --commit.')
        return

    counts = apply_refresh(cur, plan, delete_orphans=args.delete_orphans)
    conn.commit()
    print(f"\nCOMMITTED  updated {counts['updated']}  inserted {counts['inserted']}  "
          f"deleted {counts['deleted']}")


if __name__ == '__main__':
    main()
