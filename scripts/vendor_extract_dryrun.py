"""
Read-only comparison of the new vendor extractor against what is stored today.

Reads the transaction tables, re-parses every narration and reports the family
breakdown, the unresolved rows and the disagreements with the stored
client_vendor.  Writes nothing back to the database.

    python scripts/vendor_extract_dryrun.py            # local DB (.env)
    python scripts/vendor_extract_dryrun.py --prod     # Railway DB (.env.prod)
"""

import argparse
import collections
import os
import sys

import pymysql
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vendor_extractor import match_vendor  # noqa: E402

TABLES = {'axis': 'axis_transactions', 'kvb': 'kvb_transactions'}


def connect(env_file):
    cfg = dotenv_values(env_file)
    return pymysql.connect(
        host=cfg['DB_HOST'], port=int(cfg.get('DB_PORT', 3306)),
        user=cfg['DB_USER'], password=cfg['DB_PASSWORD'],
        database=cfg['DB_DATABASE'], charset='utf8mb4',
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prod', action='store_true', help='use .env.prod')
    parser.add_argument('--show', type=int, default=15,
                        help='sample rows to print per section')
    args = parser.parse_args()

    conn = connect('.env.prod' if args.prod else '.env')
    print(f"[*] Source: {'PROD (Railway)' if args.prod else 'LOCAL'} — read-only\n")

    with conn.cursor() as cur:
        for bank, table in TABLES.items():
            cur.execute(
                f'SELECT transaction_description, client_vendor FROM {table}')
            rows = cur.fetchall()

            families = collections.Counter()
            unresolved = collections.Counter()
            changed = []
            flags = collections.Counter()

            for desc, stored in rows:
                result = match_vendor(desc, bank)
                families[result.family] += 1
                if result.vendor is None:
                    unresolved[(result.family, (desc or '')[:60])] += 1
                elif (result.vendor or '').strip().upper() != (stored or '').strip().upper():
                    changed.append((desc, stored, result.vendor))
                for flag in ('is_self', 'is_reversal', 'is_internal', 'truncated'):
                    if getattr(result, flag):
                        flags[flag] += 1

            resolved = sum(n for f, n in families.items()) - sum(unresolved.values())
            print(f'=== {table}  ({len(rows)} rows)')
            print(f'    resolved to a name : {resolved} '
                  f'({resolved / max(len(rows), 1):.1%})')
            print(f'    no name derivable  : {sum(unresolved.values())}')
            print(f'    flags              : {dict(flags)}')

            print('    families:')
            for family, n in families.most_common():
                print(f'      {n:5d}  {family}')

            print(f'    rows with no derivable name (top {args.show}):')
            for (family, sample), n in unresolved.most_common(args.show):
                print(f'      {n:4d}  [{family}] {sample}')

            print(f'    differs from stored client_vendor: {len(changed)} '
                  f'(showing {min(args.show, len(changed))})')
            for desc, stored, new in changed[:args.show]:
                print(f'      {desc[:64]}')
                print(f'         stored: {stored!r}  ->  new: {new!r}')
            print()

    conn.close()


if __name__ == '__main__':
    main()
