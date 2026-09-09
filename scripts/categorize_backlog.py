"""Apply the vendor+remark categoriser to rows already sitting UNCATEGORIZED.

The categoriser runs at upload time, so statements loaded before it existed
never saw it. This walks the backlog and fills in what the memory is confident
about, exactly as an upload would.

What it will and will not touch
-------------------------------
* **Only rows whose category is UNCATEGORIZED or blank.** A row with any other
  category carries a decision someone made, and this script has no way to tell
  a considered ruling from a lucky keyword match — so it leaves every one of
  them alone. That is the same rule ``legacy_vendor.py`` protects vendors with.
* **Credits are skipped.** AMOUNT RECEIVED comes from the DR/CR flag at upload
  and is not this script's business.
* **Contested pairs stay UNCATEGORIZED**, gaining only the note that says why —
  which is what puts them in the dashboard's "Needs review" filter with an
  explanation instead of leaving them bare.

The memory is built from settled rows only, so the rows being written can never
have taught the answer they are about to receive.

Dry run by default. Nothing is written without --apply.

    python scripts/categorize_backlog.py --since 2026-09-01
    python scripts/categorize_backlog.py --since 2026-09-01 --apply
"""

import argparse
import collections
import os
import sys

import pymysql
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bank_statement_processor import decide_category  # noqa: E402
from helpers.bill_reconcile import VendorAliasResolver  # noqa: E402
from helpers.category_memory import (  # noqa: E402
    CategoryMemory,
    canonical_category,
    extract_purpose,
)
from vendor_extractor import match_vendor  # noqa: E402

TABLES = {'axis': 'axis_transactions', 'kvb': 'kvb_transactions'}

#: Categories that mean "nobody has decided yet" — the only ones we may write over.
_EMPTY = ('UNCATEGORIZED', '')


def connect(env_file):
    cfg = dotenv_values(env_file)
    return pymysql.connect(
        host=cfg['DB_HOST'], port=int(cfg.get('DB_PORT', 3306)),
        user=cfg['DB_USER'], password=cfg['DB_PASSWORD'],
        database=cfg['DB_DATABASE'], charset='utf8mb4',
    )


def load_alias_resolver(conn):
    links, splits = {}, []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT alias_norm, canonical_name FROM vendor_aliases")
            links = {a: c for a, c in cur.fetchall()}
            cur.execute("SELECT left_norm, right_norm FROM vendor_alias_splits")
            splits = list(cur.fetchall())
    except Exception as e:
        print(f"[!] No alias rules ({e}) — using name matching alone")
    return VendorAliasResolver(links=links, splits=splits)


def build_memory(conn, bank, table, resolver, reference_date):
    """Evidence from settled rows only — never from the ones we are about to write."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT transaction_date, transaction_description, client_vendor, "
            f"category, code, cr_amount FROM {table} "
            f"WHERE category IS NOT NULL AND category <> '' "
            f"AND UPPER(category) <> 'UNCATEGORIZED'")
        rows = []
        for date, desc, vendor, category, code, cr in cur.fetchall():
            rows.append({
                'date': date, 'vendor': vendor,
                'category': canonical_category(category), 'code': code,
                'is_credit': float(cr or 0) > 0,
                'purpose': extract_purpose(desc, match_vendor(desc or '', bank).family),
            })
    return CategoryMemory(rows, resolver=resolver, reference_date=reference_date)


def targets(conn, table, since):
    placeholders = ','.join(['%s'] * len(_EMPTY))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, transaction_date, transaction_description, client_vendor, "
            f"dr_amount, cr_amount FROM {table} "
            f"WHERE transaction_date >= %s "
            f"AND (category IS NULL OR UPPER(TRIM(category)) IN ({placeholders})) "
            f"ORDER BY transaction_date, id",
            (since,) + _EMPTY)
        return cur.fetchall()


def run(conn, bank, table, since, apply, show):
    resolver = load_alias_resolver(conn)
    memory = build_memory(conn, bank, table, resolver, reference_date=None)
    rows = targets(conn, table, since)

    print(f"\n=== {table}")
    print(f"    uncategorised rows on/after {since} : {len(rows)}")
    print(f"    memory                              : {len(memory)} vendors, "
          f"{memory.purpose_count} remarks")
    if not rows:
        return 0

    writes, held, untouched = [], [], 0
    for rid, date, desc, vendor, dr, cr in rows:
        if float(cr or 0) > 0:
            untouched += 1          # credits belong to the DR/CR rule, not here
            continue
        decision = decide_category(desc or '', 'DR', match_vendor(desc or '', bank),
                                   bank, memory)
        if decision.source == 'learned':
            writes.append((rid, date, vendor, decision))
        elif decision.source == 'suggested':
            held.append((rid, date, vendor, decision))
        else:
            untouched += 1

    print(f"    -> would categorise                 : {len(writes)}")
    print(f"    -> would flag for review (contested/unsure) : {len(held)}")
    print(f"    -> left untouched (no evidence)     : {untouched}")

    if writes:
        by_cat = collections.Counter(d.category for _, _, _, d in writes)
        print(f"\n    categories to be written:")
        for cat, n in by_cat.most_common():
            print(f"        {cat:<22} {n:>3}")
        print(f"\n    sample ({min(show, len(writes))} of {len(writes)}):")
        for rid, date, vendor, d in writes[:show]:
            print(f"        #{rid} {date}  {str(vendor)[:20]:<20} -> "
                  f"{d.category:<20} {d.confidence}")
            print(f"              {d.explanation}")
    if held and show:
        print(f"\n    sample of review flags ({min(3, len(held))} of {len(held)}):")
        for rid, date, vendor, d in held[:3]:
            print(f"        #{rid} {date}  {str(vendor)[:20]:<20}  {d.explanation}")

    if not apply:
        print(f"\n    [dry run] nothing written. Re-run with --apply to commit.")
        return 0

    with conn.cursor() as cur:
        for rid, _, _, d in writes:
            cur.execute(
                f"UPDATE {table} SET category=%s, code=%s, category_source=%s, "
                f"category_confidence=%s, category_note=%s, "
                f"updated_at=CURRENT_TIMESTAMP WHERE id=%s AND "
                f"(category IS NULL OR UPPER(TRIM(category)) IN ('UNCATEGORIZED',''))",
                (d.category, d.code, 'learned', d.confidence, d.explanation, rid))
        for rid, _, _, d in held:
            # Category deliberately unchanged: the note and source are what put
            # the row in the review filter with a reason attached.
            cur.execute(
                f"UPDATE {table} SET category_source=%s, category_confidence=%s, "
                f"category_note=%s WHERE id=%s AND "
                f"(category IS NULL OR UPPER(TRIM(category)) IN ('UNCATEGORIZED',''))",
                ('suggested', d.confidence, d.explanation, rid))
    conn.commit()
    print(f"\n    [applied] {len(writes)} categorised, {len(held)} flagged for review.")
    return len(writes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--since', required=True,
                        help='only rows with transaction_date on/after this (YYYY-MM-DD)')
    parser.add_argument('--prod', action='store_true', help='use .env.prod')
    parser.add_argument('--env', help='explicit path to the env file to read')
    parser.add_argument('--bank', choices=sorted(TABLES), help='limit to one bank')
    parser.add_argument('--apply', action='store_true',
                        help='actually write (default is a dry run)')
    parser.add_argument('--show', type=int, default=10, help='sample rows to print')
    args = parser.parse_args()

    env = args.env or ('.env.prod' if args.prod else '.env')
    conn = connect(env)
    print(f"[*] Source: {env}   mode: {'APPLY' if args.apply else 'DRY RUN'}")

    total = 0
    for bank, table in TABLES.items():
        if args.bank and bank != args.bank:
            continue
        total += run(conn, bank, table, args.since, args.apply, args.show)
    conn.close()
    print(f"\n[+] {'Wrote' if args.apply else 'Would write'} {total} categories.")


if __name__ == '__main__':
    main()
