"""Backfill the personal expense tracker from a bank's statement rows.

The app now does this from the bank dashboard's "Sync Expense Tracker" button
(`/api/<bank>/tracker-sync`). This script is the same engine on the command
line, for backfilling an explicit historic window against any environment.

The mapping rules live in `helpers/tracker_sync.py` -- one implementation, so
the button and the script can never drift apart.

    python scripts/tracker_backfill.py                              # auto window
    python scripts/tracker_backfill.py --start 2026-08-03 --end 2026-08-18
    python scripts/tracker_backfill.py --start ... --end ... --commit

With no --start/--end it uses the same window the button does: from the
tracker's watermark for that bank (re-scanned, since that day is usually only
part-entered by hand) through the last date the statement covers. Default is a
dry-run preview; --commit writes. --env picks the dotenv file (.env.prod for
production).
"""

import argparse
import os
import sys

import mysql.connector
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.tracker_sync import BANK_TABLES, build_plan, insert_plan  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bank', default='axis', choices=sorted(BANK_TABLES))
    ap.add_argument('--start', help='default: the tracker watermark for this bank')
    ap.add_argument('--end', help='default: the last date the statement covers')
    ap.add_argument('--env', default='.env.prod')
    ap.add_argument('--commit', action='store_true')
    args = ap.parse_args()

    cfg = dotenv_values(args.env)
    conn = mysql.connector.connect(
        host=cfg['DB_HOST'], port=int(cfg['DB_PORT']), user=cfg['DB_USER'],
        password=cfg['DB_PASSWORD'], database=cfg['DB_DATABASE'])
    cur = conn.cursor(dictionary=True)

    plan = build_plan(cur, args.bank, start=args.start, end=args.end)

    print(f"{args.bank}  watermark {plan['watermark']}  "
          f"window {plan['start']}..{plan['end']}  scanned: {plan['scanned']}   "
          f"to insert: {plan['totals']['count']}   skipped: {len(plan['skipped'])}")
    print(f"expense {plan['totals']['expense']}   income {plan['totals']['income']}\n")
    print(f"{'date':12}{'type':9}{'amount':>12}  {'vendor':30}{'description':24}project")
    print('-' * 110)
    for r in plan['rows']:
        print(f"{str(r['date']):12}{r['transaction_type']:9}{r['amount']:>12}  "
              f"{r['vendor'][:29]:30}{r['description'][:23]:24}{r['project']}")
    print('\nSKIPPED')
    for s in plan['skipped']:
        print(f"  {str(s['date']):12}{s['amount']:>12}  {s['vendor'][:28]:30}{s['reason']}")

    if not args.commit:
        print('\nDRY RUN -- nothing written. Re-run with --commit to insert.')
    else:
        inserted = insert_plan(cur, plan)
        conn.commit()
        print(f'\nINSERTED {inserted} rows.')
    conn.close()


if __name__ == '__main__':
    main()
