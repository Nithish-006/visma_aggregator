"""Read-only measurement of vendor-history categorisation against real data.

Holds out the most recent slice of each bank table, builds a
:class:`~helpers.category_memory.CategoryMemory` from everything before it, then
predicts the held-out rows and reports accuracy per confidence band — next to
today's keyword categoriser on the same rows, so the comparison is like for
like. Writes nothing back to the database.

Two prediction modes are reported, because they differ in a way that matters:

* **stored vendor** — the memory is asked about ``client_vendor`` as it sits in
  the table. This is the ceiling: what the memory could do given a perfect
  vendor name.
* **parsed vendor** — the vendor is re-derived from the narration with
  ``match_vendor()``, exactly as it would be during an upload of a fresh
  statement. This is the number that will actually be delivered.

    python scripts/category_memory_dryrun.py            # local DB (.env)
    python scripts/category_memory_dryrun.py --prod     # Railway DB (.env.prod)
"""

import argparse
import collections
import os
import sys

import pymysql
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bank_statement_processor import categorize_transaction  # noqa: E402
from helpers.bill_reconcile import VendorAliasResolver  # noqa: E402
from helpers.category_memory import (  # noqa: E402
    STRUCTURAL_CATEGORIES,
    CategoryMemory,
    canonical_category,
    extract_purpose,
)
from vendor_extractor import match_vendor  # noqa: E402

TABLES = {'axis': 'axis_transactions', 'kvb': 'kvb_transactions'}

# Confidence cut points to report. The aim is to find where precision stops
# being good enough to auto-apply without a person checking.
BANDS = [(0.95, 1.01), (0.90, 0.95), (0.80, 0.90), (0.60, 0.80),
         (0.40, 0.60), (0.0, 0.40)]


def connect(env_file):
    cfg = dotenv_values(env_file)
    return pymysql.connect(
        host=cfg['DB_HOST'], port=int(cfg.get('DB_PORT', 3306)),
        user=cfg['DB_USER'], password=cfg['DB_PASSWORD'],
        database=cfg['DB_DATABASE'], charset='utf8mb4',
    )


def load_alias_resolver(conn):
    """The human vendor-identity rulings, read straight from the tables."""
    links, splits = {}, []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT alias_norm, canonical_name FROM vendor_aliases")
            links = {a: c for a, c in cur.fetchall()}
            cur.execute("SELECT left_norm, right_norm FROM vendor_alias_splits")
            splits = list(cur.fetchall())
    except Exception as e:
        print(f"[!] No alias rules ({e}) — measuring name matching alone")
    return VendorAliasResolver(links=links, splits=splits)


def load_rows(conn, table, bank):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT transaction_date, transaction_description, client_vendor, "
            f"category, code, dr_amount, cr_amount FROM {table} "
            f"ORDER BY transaction_date")
        out = []
        for date, desc, vendor, category, code, dr, cr in cur.fetchall():
            match = match_vendor(desc or '', bank)
            out.append({
                'date': date,
                'description': desc or '',
                'vendor': vendor,
                'parsed_vendor': match.vendor,
                # The remark is read off the narration, so it is identical at
                # training time and at upload time — unlike the vendor, which
                # has a stored (hand-corrected) form and a parsed form.
                'purpose': extract_purpose(desc, match.family),
                'category': canonical_category(category),
                'code': code,
                'is_credit': float(cr or 0) > 0,
                'dr': float(dr or 0),
            })
        return out


def evaluate(bank, table, rows, resolver, holdout_frac, show):
    # Only debits with a settled category can be scored: credits are decided by
    # the DR/CR flag, and an UNCATEGORIZED row has no answer to check against.
    scorable = [r for r in rows
                if not r['is_credit']
                and r['category']
                and r['category'] != 'UNCATEGORIZED'
                and r['category'] not in STRUCTURAL_CATEGORIES]

    split = int(len(scorable) * (1 - holdout_frac))
    train, test = scorable[:split], scorable[split:]
    if not test:
        print(f"=== {table}: not enough scorable rows to hold out\n")
        return

    cutoff = test[0]['date']
    memory = CategoryMemory(train, resolver=resolver, reference_date=cutoff)

    print(f"=== {table}")
    print(f"    scorable debit rows      : {len(scorable)} of {len(rows)} total")
    print(f"    train / test             : {len(train)} / {len(test)}"
          f"  (cutoff {cutoff})")
    print(f"    vendors learned          : {len(memory)} "
          f"from {memory.rows_learned} rows")
    print(f"    purpose remarks learned  : {memory.purpose_count} tokens "
          f"from {memory.purposes_learned} rows")
    with_purpose = sum(1 for r in test if r['purpose'])
    print(f"    test rows with a remark  : {with_purpose}/{len(test)}"
          f" = {pct(with_purpose, len(test))}")

    # -- today's behaviour, on exactly these rows --------------------------
    kw_right = sum(1 for r in test
                   if canonical_category(
                       categorize_transaction(r['description'], 'DR', r['vendor'])[0])
                   == r['category'])
    print(f"\n    BASELINE  keyword categoriser : "
          f"{kw_right}/{len(test)} = {pct(kw_right, len(test))} correct")

    # Each mode isolates one signal so their contributions stay separable; the
    # last is what an upload would actually do.
    modes = [
        ('vendor only, re-parsed from narration',
         lambda r: memory.suggest(r['parsed_vendor'], None)),
        ('purpose remark only',
         lambda r: memory.suggest(None, r['purpose'])),
        ('COMBINED — vendor + purpose (real upload)',
         lambda r: memory.suggest(r['parsed_vendor'], r['purpose'])),
    ]
    for label, predict in modes:
        report_mode(label, test, predict, show)
    print()


def report_mode(label, test, predict, show):
    band_hits = collections.defaultdict(lambda: [0, 0])
    by_signal = collections.defaultdict(lambda: [0, 0])
    misses = []
    no_suggestion = 0
    contested_held = contested_would_be_right = 0

    for row in test:
        suggestion = predict(row)
        if suggestion is None:
            no_suggestion += 1
            continue
        if suggestion.contested:
            # Never applied by decide_category(), so it must not be scored as
            # though it were — it goes to the review queue like an unseen row.
            contested_held += 1
            contested_would_be_right += int(suggestion.category == row['category'])
            continue
        band = band_for(suggestion.confidence)
        correct = suggestion.category == row['category']
        band_hits[band][0] += 1
        band_hits[band][1] += int(correct)
        by_signal[suggestion.signal][0] += 1
        by_signal[suggestion.signal][1] += int(correct)
        if not correct:
            misses.append((suggestion.confidence,
                           suggestion.matched_vendor, suggestion.category,
                           row['category'], suggestion.support, suggestion.purity,
                           suggestion.signal))

    print(f"\n    --- {label}")
    print(f"        no suggestion at all          : {no_suggestion}/{len(test)}"
          f" = {pct(no_suggestion, len(test))}")
    if contested_held:
        # The cost of the contested rule, stated plainly: how many rows it
        # holds back, and how often it was holding back a correct answer.
        print(f"        held: contested pair          : {contested_held}/{len(test)}"
              f" = {pct(contested_held, len(test))}"
              f"  (would have been right {pct(contested_would_be_right, contested_held)})")
    print(f"        {'band':>12}  {'n':>5}  {'correct':>8}  {'precision':>10}"
          f"  {'cum n':>6}  {'cum prec':>9}")

    cum_n = cum_c = 0
    for lo, hi in BANDS:
        n, c = band_hits[(lo, hi)]
        cum_n += n
        cum_c += c
        if n == 0 and cum_n == 0:
            continue
        print(f"        {lo:>5.2f}-{hi if hi <= 1 else 1.0:<5.2f}  {n:>5}  {c:>8}"
              f"  {pct(c, n):>10}  {cum_n:>6}  {pct(cum_c, cum_n):>9}")

    total = len(test)
    print(f"        overall accuracy over ALL test rows "
          f"(no suggestion counts as wrong): {pct(cum_c, total)}")

    if len(by_signal) > 1:
        print(f"        by signal: " + '  '.join(
            f"{sig}={c}/{n} ({pct(c, n)})"
            for sig, (n, c) in sorted(by_signal.items())))

    if misses and show:
        print(f"        worst misses (highest confidence first):")
        for conf, who, guess, truth, sup, pur, sig in sorted(
                misses, key=lambda m: -m[0])[:show]:
            print(f"          {conf:.2f} sup={sup:5.1f} pur={pur:.2f} {sig:<8} "
                  f"{str(who)[:24]:<24} guessed {guess:<20} actual {truth}")


def band_for(conf):
    for lo, hi in BANDS:
        if lo <= conf < hi:
            return (lo, hi)
    return BANDS[-1]


def pct(num, den):
    return f"{100.0 * num / den:.1f}%" if den else "  n/a"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prod', action='store_true', help='use .env.prod')
    parser.add_argument('--env', help='explicit path to the env file to read '
                                      '(overrides --prod; for running from a worktree)')
    parser.add_argument('--holdout', type=float, default=0.25,
                        help='fraction of the most recent rows to hold out')
    parser.add_argument('--show', type=int, default=10,
                        help='miss examples to print per mode')
    args = parser.parse_args()

    env = args.env or ('.env.prod' if args.prod else '.env')
    conn = connect(env)
    print(f"[*] Source: {'PROD (Railway)' if args.prod or args.env else 'LOCAL'}"
          f" — read-only\n")

    resolver = load_alias_resolver(conn)
    for bank, table in TABLES.items():
        evaluate(bank, table, load_rows(conn, table, bank), resolver,
                 args.holdout, args.show)
    conn.close()


if __name__ == '__main__':
    main()
