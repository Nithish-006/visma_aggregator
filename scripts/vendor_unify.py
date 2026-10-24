"""
Unify client_vendor spellings to the name the bank statement itself carries.

One supplier had piled up as many spellings as there were people typing it -
'UNIQUE PRODUCT', 'unique product', 'Unique products/', ... - while every one of
those rows' narrations says 'Unique products'. The vendor filter, the project
summary and the category memory all group on the exact string, so each
spelling was a separate vendor to them.

The rule is: the narration decides. Per bank table:

  1. The statement name of a row is what vendor_extractor reads off its
     narration. Statement names differing only in case/spacing/punctuation are
     one name, spelled the way the statement spells it most often. A KVB
     narration cut off at the export width resolves to the full statement name
     it is a fragment of, when that is unambiguous.

  2. A row whose typed value names the same party as its own narration gets
     the statement name - 'UNIQUE PRODUCT', 'arjun', 'MAHENDREN'. The narration
     is strong evidence here: it is this very payment's payee. One exception:
     if the typed value is itself a *fuller* statement name that this row's
     narration merely cuts short ('SURESH KUMAR D' where the narration reads
     'SURESH'), the fuller name stays, or one vendor would become two.

  3. Own-account moves ('VISMAASS', 'VISMAASSOCIATES') become VISMA ASSOCIATES.

  4. A row whose narration names no one (KVB outward IMPS reads 'IMPSP2A', cash,
     own-account moves) takes the statement name its spelling matches exactly,
     or that the same spelling was resolved to on rows whose narration does
     name the payee.

Left alone, and reported:

  * typed values carrying a note after the name ('SRIDHAR K M/ARJUN',
    'Google India Digital(eb bill)') - the note is human knowledge;
  * typed values naming someone other than the narration does - the payee
    registered as 'welder' who is really SATHEESH, 'PANDP' typed out as
    'P&P ROOFING'. A person resolved those; the narration cannot overrule them.
    Only their case/spacing is aligned.

Held for review, written only with --include-review:

  * fuzzy matches for rows whose narration names no one ('SAMUDEESHWARI');
  * vendors the statement itself spells two ways, one a prefix of the other
    ('V BALAJI RANGAN' / 'V BALAJI RANGANATHAN') - merged to the spelling on
    the most rows.

Dry run by default; --apply is required to write. Every run writes a full CSV
audit of the proposed changes before touching anything, and --revert undoes a
run from that CSV.

    python scripts/vendor_unify.py --prod                       # preview
    python scripts/vendor_unify.py --prod --apply               # write
    python scripts/vendor_unify.py --prod --include-review      # + the review set
    python scripts/vendor_unify.py --prod --revert AUDIT_CSV --apply
"""

import argparse
import collections
import csv
import os
import sys
from datetime import datetime

import pymysql
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.bill_reconcile import (  # noqa: E402
    vendor_anchor, vendor_anchors_agree, vendor_key, vendor_keys_match)
# The same tidy / note / fragment rules every upload snaps names with, so this
# cleanup and the upload path can never disagree about a spelling.
from helpers.vendor_spelling import is_annotated, sole_extension  # noqa: E402
from helpers.vendor_spelling import tidy_vendor as tidy  # noqa: E402
from vendor_extractor import SELF_CANONICAL, _squash, is_self_name, match_vendor  # noqa: E402

TABLES = {'axis': 'axis_transactions', 'kvb': 'kvb_transactions'}

# Occupies KVB's name slot on outward IMPS when the beneficiary was saved
# without a name: IMPS-614309611715-IMPSP2A-UTIB-xxxxxxxxxxx3306-Exp
_NAMELESS = {'IMPSP2A'}

_PLACEHOLDER = {'', 'UNKNOWN', 'NONE', 'NA', 'N/A', '-', '.'}

# A statement name this short is a first name ('SURESH', 'REVATHI'), shared by
# too many people to merge into a longer one on the prefix alone.
_MIN_PREFIX_MERGE = 6


def connect(env_file):
    cfg = dotenv_values(env_file)
    return pymysql.connect(
        host=cfg['DB_HOST'], port=int(cfg.get('DB_PORT', 3306)),
        user=cfg['DB_USER'], password=cfg['DB_PASSWORD'],
        database=cfg['DB_DATABASE'], charset='utf8mb4',
    )


def statement_name(desc, bank):
    """(name, truncated) as the narration carries it; name None if none."""
    m = match_vendor(desc, bank)
    name = tidy(m.vendor) if m.vendor else ''
    if not name or name.upper() in _NAMELESS:
        return None, False
    return name, m.truncated


def same_party(typed, stmt):
    """True when a typed value plausibly names the narration's own payee.

    Looser than the bill matcher, because the narration is not some other
    document's spelling - it is this payment's payee. Agreeing identity words
    are enough ('arjun' / 'Arjunan s', 'bishnu' / 'BISHNUNARAYANAN M').
    """
    if vendor_keys_match(vendor_key(typed), vendor_key(stmt)):
        return True
    if vendor_anchors_agree(vendor_anchor(typed), vendor_anchor(stmt)):
        return True
    a, b = _squash(typed), _squash(stmt)
    return min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a))


def build_canon(rows):
    """{squash: canonical spelling} over the statement names of one table.

    Squash-equal spellings collapse to the statement's most frequent one; a
    truncated fragment then points at the single full name extending it.
    """
    spellings = collections.defaultdict(collections.Counter)
    fragments = set()
    for r in rows:
        if r['stmt']:
            spellings[_squash(r['stmt'])][r['stmt']] += 1
            if r['truncated']:
                fragments.add(_squash(r['stmt']))

    canon = {sq: c.most_common(1)[0][0] for sq, c in spellings.items()}

    for frag in fragments:
        full = sole_extension(frag, canon)
        if full:
            canon[frag] = canon[full]
    return canon


def plan_changes(conn, bank, table):
    """Return (changes, review, skipped) without writing anything."""
    with conn.cursor() as cur:
        cur.execute(
            f'SELECT id, transaction_description, client_vendor FROM {table}')
        raw = cur.fetchall()

    rows = []
    for row_id, desc, stored in raw:
        stmt, truncated = statement_name(desc, bank)
        rows.append({'id': row_id, 'desc': desc or '', 'stored': stored or '',
                     'value': tidy(stored), 'stmt': stmt, 'truncated': truncated,
                     'new': None, 'reason': None})

    canon = build_canon(rows)
    skipped = collections.Counter()
    # typed spelling (squashed) -> statement names it was resolved to
    learned = collections.defaultdict(collections.Counter)
    typed_rows = []

    # --- pass 1: rows whose narration names the payee -----------------------
    for r in rows:
        value = r['value']
        if value.upper() in _PLACEHOLDER:
            skipped['blank / Unknown'] += 1
            continue
        if is_annotated(value):
            skipped['note after the name - left untouched'] += 1
            continue
        if not r['stmt']:
            continue

        target = canon[_squash(r['stmt'])]
        fuller = canon.get(_squash(value))
        if is_self_name(value) and is_self_name(target):
            r['new'], r['reason'] = SELF_CANONICAL, 'own account'
        elif _squash(value) == _squash(target):
            r['new'], r['reason'] = target, 'statement spelling'
        elif _squash(value) == _squash(r['stmt']):
            r['new'], r['reason'] = target, 'truncated in statement'
        elif fuller and _squash(fuller).startswith(_squash(target)):
            r['new'], r['reason'] = fuller, 'fuller statement name kept'
        elif same_party(value, target):
            r['new'], r['reason'] = target, 'variant of statement name'
        else:
            typed_rows.append(r)
            continue
        learned[_squash(value)][r['new']] += 1

    # --- pass 2: rows whose narration names no one --------------------------
    for r in rows:
        value = r['value']
        if r['stmt'] or r['new'] or value.upper() in _PLACEHOLDER \
                or is_annotated(value):
            continue
        sq = _squash(value)
        if is_self_name(value):
            r['new'], r['reason'] = SELF_CANONICAL, 'own account'
        elif sq in canon:
            r['new'], r['reason'] = canon[sq], 'no name in statement - same spelling'
        elif len(learned.get(sq, ())) == 1:
            r['new'] = next(iter(learned[sq]))
            r['reason'] = 'no name in statement - spelling resolved elsewhere'
        else:
            typed_rows.append(r)

    # --- typed names kept: align case/spacing, to the statement's spelling
    # where it has one ('CASH DEPOSIT' -> 'Cash Deposit'), else among themselves
    spelled = collections.defaultdict(collections.Counter)
    for r in typed_rows:
        spelled[_squash(r['value'])][r['value']] += 1
    for r in typed_rows:
        sq = _squash(r['value'])
        r['new'] = canon.get(sq) or spelled[sq].most_common(1)[0][0]
        r['reason'] = ('typed name kept - spacing/case' if r['stmt']
                       else 'typed name - spacing/case')

    # --- review: fuzzy no-name matches + statement prefix merges ------------
    review = []
    canon_names = set(canon.values())
    canon_keys = {name: vendor_key(name) for name in canon_names}
    for r in typed_rows:
        if r['stmt']:
            continue
        key = vendor_key(r['new'])
        hits = [n for n, k in canon_keys.items() if vendor_keys_match(key, k)]
        if len(hits) == 1:
            r['review'] = (hits[0], 'fuzzy - no name in statement')

    final_counts = collections.Counter(r['new'] or r['value'] for r in rows)
    by_squash = {_squash(n): n for n in canon_names}
    merge_into = {}
    for sq, name in by_squash.items():
        if len(sq) < _MIN_PREFIX_MERGE:
            continue
        full = sole_extension(sq, by_squash)
        if not full:
            continue
        chain = [s for s in by_squash if full.startswith(s) and len(s) >= len(sq)]
        winner = max((by_squash[s] for s in chain), key=lambda n: final_counts[n])
        for s in chain:
            if by_squash[s] != winner:
                merge_into.setdefault(by_squash[s], winner)
    for r in rows:
        current = r['new'] or r['value']
        if current in merge_into and r.get('review') is None:
            r['review'] = (merge_into[current], 'statement spells it two ways')

    changes = []
    for r in rows:
        entry = {'id': r['id'], 'bank': bank, 'description': r['desc'],
                 'stored': r['stored']}
        if r['new'] and r['new'] != r['stored']:
            changes.append({**entry, 'new': r['new'], 'reason': r['reason']})
        elif r['reason'] == 'typed name kept - spacing/case':
            skipped['typed name differs from statement - kept'] += 1
        elif r['new']:
            skipped['already unified'] += 1
        if r.get('review') and r['review'][0] != r['stored']:
            review.append({**entry, 'new': r['review'][0], 'reason': r['review'][1]})

    return changes, review, skipped


def write_audit(changes, label):
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        f'vendor_unify_{label}_{stamp}.csv')
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(
            fh, fieldnames=['id', 'bank', 'description', 'stored', 'new', 'reason'])
        writer.writeheader()
        writer.writerows(changes)
    return path


def merge_review(changes, review):
    """Fold the review set in; a review row overrides a planned change."""
    by_key = {(c['bank'], c['id']): c for c in changes}
    for r in review:
        by_key[(r['bank'], r['id'])] = r
    return list(by_key.values())


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
    parser.add_argument('--include-review', action='store_true',
                        help='also write the matches held for review')
    parser.add_argument('--bank', choices=sorted(TABLES), action='append',
                        help='limit to one bank (repeatable); default both')
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

    all_changes, all_review = [], []
    for bank in args.bank or sorted(TABLES):
        table = TABLES[bank]
        changes, review, skipped = plan_changes(conn, bank, table)
        if args.include_review:
            changes, review = merge_review(changes, review), []
        all_changes.extend(changes)
        all_review.extend(review)

        print(f'=== {table}')
        print(f'    to unify   : {len(changes)} rows, '
              f'{len({c["stored"] for c in changes})} spellings -> '
              f'{len({c["new"] for c in changes})} names')
        for reason, n in collections.Counter(
                c['reason'] for c in changes).most_common():
            print(f'       {n:5d}  {reason}')
        print(f'    for review : {len(review)} (written only with --include-review)')
        for reason, n in collections.Counter(
                c['reason'] for c in review).most_common():
            print(f'       {n:5d}  {reason}')
        print('    left alone :')
        for reason, n in skipped.most_common():
            if n:
                print(f'       {n:5d}  {reason}')

        by_new = collections.defaultdict(collections.Counter)
        for c in changes:
            by_new[c['new']][c['stored']] += 1
        for new, olds in sorted(by_new.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
            was = ', '.join(f'{o!r} x{n}' for o, n in olds.most_common())
            print(f'      -> {new!r:28s} <- {was}')
        print()

    if not all_changes and not all_review:
        print('[=] Nothing to unify.')
        conn.close()
        return

    audit = write_audit(all_changes, 'changes')
    print(f'[+] Audit of all {len(all_changes)} proposed changes: {audit}')
    if all_review:
        print(f'[+] Held for review: {write_audit(all_review, "review")}')

    if not args.apply:
        print('[=] Dry run — nothing written. Re-run with --apply to commit.')
        conn.close()
        return

    written = 0
    with conn.cursor() as cur:
        for c in all_changes:
            # Guard on the value we planned against, so a row edited in the
            # app since the plan was built is skipped rather than overwritten.
            cur.execute(
                f'UPDATE {TABLES[c["bank"]]} SET client_vendor = %s '
                f'WHERE id = %s AND client_vendor = %s',
                (c['new'], c['id'], c['stored']))
            written += cur.rowcount
    conn.commit()
    print(f'[+] Updated {written} rows '
          f'({len(all_changes) - written} had changed since the plan).')
    conn.close()


if __name__ == '__main__':
    main()
