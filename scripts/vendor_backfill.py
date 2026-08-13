"""
Correct client_vendor values that the old parser got structurally wrong.

Two independent gates must both pass before a row is touched:

  1. UNTOUCHED - the stored value still equals what the old parser would have
     produced for that narration. If it differs, a human edited it: that edit
     carries knowledge the narration does not contain (the payee registered as
     'welder' who is really SATHEESH, the MB-WITHIN rows), so we leave it alone.

  2. CLEARLY WRONG - the stored value is not a name at all: a transaction
     reference, an IFSC code, a masked account number, a bare number, one of
     our own [SPLIT n/m] markers, or Unknown/blank while the new parser does
     resolve a real name.

A row that merely reads differently - spacing, a longer form of the same name,
a self-transfer spelled 'VISMAASS' instead of 'VISMA ASSOCIATES' - is NOT
wrong, so it is reported and skipped unless explicitly opted into.

Dry run by default; --apply is required to write. Every run writes a full CSV
audit of the proposed changes before touching anything.

    python scripts/vendor_backfill.py --prod                    # preview
    python scripts/vendor_backfill.py --prod --apply            # write
    python scripts/vendor_backfill.py --prod --include-cosmetic # + spacing fixes
"""

import argparse
import collections
import csv
import os
import re
import sys
from datetime import datetime

import pymysql
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from legacy_vendor import legacy_extract_vendor  # noqa: E402
from vendor_extractor import _squash, match_vendor  # noqa: E402

TABLES = {'axis': 'axis_transactions', 'kvb': 'kvb_transactions'}

# Shapes that are definitively not a counterparty name
_TXN_REF = re.compile(r'^[A-Z]{4,5}[A-Z]?\d{8,}$')
_IFSC = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
_MASKED = re.compile(r'^x+\d*$', re.IGNORECASE)
_DIGITS = re.compile(r'^\d+$')
_SPLIT_LEFTOVER = re.compile(r'\[SPLIT', re.IGNORECASE)
_PLACEHOLDER = {'', 'UNKNOWN', 'NONE', 'NA', 'N/A', '-', '.'}


def why_wrong(stored: str) -> str:
    """Name the defect in a stored value, or '' if it looks like a real name."""
    value = (stored or '').strip()
    if value.upper() in _PLACEHOLDER:
        return 'placeholder'
    if _SPLIT_LEFTOVER.search(value):
        return 'split-marker captured'
    collapsed = value.replace(' ', '').upper()
    if _DIGITS.match(collapsed):
        return 'bare number'
    if _IFSC.match(collapsed):
        return 'IFSC code'
    if _TXN_REF.match(collapsed):
        return 'transaction reference'
    if _MASKED.match(collapsed):
        return 'masked account number'
    if len(re.findall(r'[A-Za-z]', value)) < 2:
        return 'no letters'
    return ''


def connect(env_file):
    cfg = dotenv_values(env_file)
    return pymysql.connect(
        host=cfg['DB_HOST'], port=int(cfg.get('DB_PORT', 3306)),
        user=cfg['DB_USER'], password=cfg['DB_PASSWORD'],
        database=cfg['DB_DATABASE'], charset='utf8mb4',
    )


def plan_changes(conn, bank, table, include_cosmetic):
    """Return (changes, skip_reasons) without writing anything."""
    with conn.cursor() as cur:
        cur.execute(
            f'SELECT id, transaction_description, client_vendor FROM {table}')
        rows = cur.fetchall()

    changes, skipped = [], collections.Counter()

    for row_id, desc, stored in rows:
        stored = (stored or '').strip()
        new = match_vendor(desc, bank).vendor

        if not new:
            skipped['new parser derives no name'] += 1
            continue
        if new.strip().upper() == stored.upper():
            skipped['already correct'] += 1
            continue

        # Gate 1 - has a human edited this row?
        legacy = (legacy_extract_vendor(desc, bank) or '').strip()
        machine_written = (
            _squash(stored) == _squash(legacy)
            or (stored.upper() in _PLACEHOLDER and not legacy)
        )
        if not machine_written:
            skipped['edited by hand - left untouched'] += 1
            continue

        # Gate 2 - is the stored value actually wrong?
        defect = why_wrong(stored)
        if not defect:
            if include_cosmetic and _squash(new) == _squash(stored):
                defect = 'spacing only'
            else:
                skipped['stored reads as a real name - not corrected'] += 1
                continue

        changes.append({
            'id': row_id, 'bank': bank, 'description': desc,
            'stored': stored, 'new': new, 'reason': defect,
        })

    return changes, skipped


def revert(args):
    """Restore the stored values recorded in a previous run's audit CSV."""
    conn = connect('.env.prod' if args.prod else '.env')
    with open(args.revert, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))

    print(f'[*] Reverting {len(rows)} rows from {args.revert}')
    if not args.apply:
        for r in rows[:10]:
            print(f'      #{r["id"]} {r["new"]!r} -> {r["stored"]!r}')
        print('[=] Dry run — nothing written. Add --apply to commit.')
        conn.close()
        return

    restored = 0
    with conn.cursor() as cur:
        for r in rows:
            # Only revert rows still holding the value this run wrote, so a
            # later manual correction is never clobbered.
            cur.execute(
                f'UPDATE {TABLES[r["bank"]]} SET client_vendor = %s '
                f'WHERE id = %s AND client_vendor = %s',
                (r['stored'], r['id'], r['new']))
            restored += cur.rowcount
    conn.commit()
    print(f'[+] Restored {restored} rows ({len(rows) - restored} had changed since).')
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prod', action='store_true', help='use .env.prod')
    parser.add_argument('--apply', action='store_true',
                        help='write the changes (default is a dry run)')
    parser.add_argument('--include-cosmetic', action='store_true',
                        help='also normalise spacing in machine-written values')
    parser.add_argument('--revert', metavar='AUDIT_CSV',
                        help='undo a previous run using its audit CSV')
    args = parser.parse_args()

    if args.revert:
        revert(args)
        return

    conn = connect('.env.prod' if args.prod else '.env')
    target = 'PROD (Railway)' if args.prod else 'LOCAL'
    mode = 'APPLY' if args.apply else 'DRY RUN'
    print(f'[*] {target} — {mode}\n')

    all_changes = []
    for bank, table in TABLES.items():
        changes, skipped = plan_changes(conn, bank, table, args.include_cosmetic)
        all_changes.extend(changes)

        print(f'=== {table}')
        print(f'    to correct : {len(changes)}')
        for reason, n in collections.Counter(
                c['reason'] for c in changes).most_common():
            print(f'       {n:5d}  {reason}')
        print('    left alone :')
        for reason, n in skipped.most_common():
            print(f'       {n:5d}  {reason}')
        for c in changes[:8]:
            print(f'      #{c["id"]} {c["description"][:52]}')
            print(f'         {c["stored"]!r} -> {c["new"]!r}  ({c["reason"]})')
        print()

    if not all_changes:
        print('[=] Nothing to correct.')
        conn.close()
        return

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audit = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         f'vendor_backfill_{stamp}.csv')
    with open(audit, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(
            fh, fieldnames=['id', 'bank', 'description', 'stored', 'new', 'reason'])
        writer.writeheader()
        writer.writerows(all_changes)
    print(f'[+] Audit of all {len(all_changes)} proposed changes: {audit}')

    if not args.apply:
        print('[=] Dry run — nothing written. Re-run with --apply to commit.')
        conn.close()
        return

    with conn.cursor() as cur:
        for c in all_changes:
            cur.execute(
                f'UPDATE {TABLES[c["bank"]]} SET client_vendor = %s WHERE id = %s',
                (c['new'], c['id']))
    conn.commit()
    print(f'[+] Updated {len(all_changes)} rows.')
    conn.close()


if __name__ == '__main__':
    main()
