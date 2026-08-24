"""Sync bank statement rows into the personal expense tracker.

The tracker (`personal_transactions`) is normally typed by hand as a mirror of
the bank statement, so it drifts behind whatever has been uploaded. This module
closes that gap mechanically: it finds how far the tracker is synced for a bank
(the watermark), and turns every bank row from there onwards into tracker rows.

Mapping rules, derived from how the existing hand-typed rows were made:
  * one tracker row per bank row -- splits stay separate so each keeps its own
    project attribution (typing them by hand merged splits, losing that)
  * debit  -> transaction_type='expense'
  * credit -> transaction_type='income'
  * rows tagged project '4 - KVB' are skipped: those are the firm's own
    Axis<->KVB transfers (VISMAASS / VISMA ASSOCIATES), and no money leaves the
    business, so the tracker has never recorded them
  * vendor      = client_vendor (already the curated vendor name)
  * description = the bank category, plus the narration's free-text purpose
    when it has one ("Auto Rent - porter")
  * project     = the canonical project string ("659 - JAMUNA"); the tracker's
    project filter matches strictly on the "659 -" tag, so filtering still works
  * amount      = exact bank amount, paise kept

The watermark day is re-scanned rather than skipped, because it is usually only
part-entered by hand. Rows already in the tracker are matched on
(date, amount, type) and skipped -- counted, so two genuine same-amount payments
on one day both survive when only one was typed in.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

BANK_TABLES = {'axis': 'axis_transactions', 'kvb': 'kvb_transactions'}

# narration purpose token: UPI/P2A/<ref>/<name>/<purpose>/<bank>
_UPI_RE = re.compile(r'^(?:UPI|IMPS)/[^/]+/[^/]+/[^/]*/([^/]*)/', re.I)
_SPLIT_RE = re.compile(r'\s*\[SPLIT\s*\d+\s*/\s*\d+\]\s*$', re.I)
# tokens that carry no purpose: bank names, account masks, reference codes
_NOISE_RE = re.compile(r'^(upi|axb|barb|abank|[a-z]*bank[a-z]*|x?\d+|.*~.*|\w*\d{4,}\w*)$', re.I)

_CENT = Decimal('0.01')


def purpose(desc, category):
    """Bank category, plus the narration's free-text purpose when it has one.

    UPI/IMPS remarks are truncated by the rails ("traile", "consum"), so they
    supplement the category rather than replace it.
    """
    label = (category or '').title()
    m = _UPI_RE.match(_SPLIT_RE.sub('', desc or ''))
    if m:
        tok = m.group(1).strip()
        if tok and len(tok) >= 4 and not _NOISE_RE.match(tok) \
                and tok.lower() not in label.lower():
            return f"{label} - {tok}"
    return label


def own_account_transfer(row):
    """Money moved between the firm's own Axis and KVB accounts."""
    return (row.get('project') or '').strip().startswith('4 -')


def _as_date(value):
    """Bank tables carry DATE or DATETIME; the tracker only ever carries DATE."""
    if isinstance(value, datetime):
        return value.date()
    return value


def _as_money(value):
    """Compare amounts at paise precision, whatever type the driver hands back."""
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(_CENT)
    except (InvalidOperation, ValueError):
        return None


def get_watermark(cursor, bank_code):
    """The last date the tracker holds for this bank, or None if never synced."""
    cursor.execute("""SELECT MAX(transaction_date) AS d
                      FROM personal_transactions WHERE bank = %s""", (bank_code,))
    row = cursor.fetchone()
    return _as_date(row['d']) if row and row['d'] else None


def get_bank_latest(cursor, bank_code):
    """The last date the uploaded statement covers."""
    cursor.execute(f"""SELECT MAX(transaction_date) AS d
                       FROM {BANK_TABLES[bank_code]}""")
    row = cursor.fetchone()
    return _as_date(row['d']) if row and row['d'] else None


def get_bank_earliest(cursor, bank_code):
    cursor.execute(f"""SELECT MIN(transaction_date) AS d
                       FROM {BANK_TABLES[bank_code]}""")
    row = cursor.fetchone()
    return _as_date(row['d']) if row and row['d'] else None


def build_plan(cursor, bank_code, start=None, end=None):
    """Work out exactly which bank rows should become tracker rows.

    `cursor` must be a dictionary cursor. Returns a plan dict; nothing is
    written. Pass start/end to override the automatic watermark window.

    Plan keys:
        bank, watermark, start, end, scanned,
        rows     -- list of insertable row dicts, in statement order
        skipped  -- list of {date, amount, vendor, reason}
        totals   -- {expense, income, count}
    """
    if bank_code not in BANK_TABLES:
        raise ValueError(f'unknown bank: {bank_code}')

    watermark = get_watermark(cursor, bank_code)
    if start is None:
        # Re-scan the watermark day itself: it is usually only part-entered by
        # hand, and the dedup below stops anything already there coming twice.
        start = watermark or get_bank_earliest(cursor, bank_code)
    if end is None:
        end = get_bank_latest(cursor, bank_code)

    plan = {'bank': bank_code, 'watermark': watermark, 'start': start, 'end': end,
            'scanned': 0, 'rows': [], 'skipped': [],
            'totals': {'expense': Decimal('0'), 'income': Decimal('0'), 'count': 0}}
    if start is None or end is None or start > end:
        return plan

    cursor.execute(f"""SELECT id, transaction_date, transaction_description, client_vendor,
                              category, dr_amount, cr_amount, project
                       FROM {BANK_TABLES[bank_code]}
                       WHERE transaction_date BETWEEN %s AND %s
                       ORDER BY transaction_date, id""", (start, end))
    bank_rows = cursor.fetchall()
    plan['scanned'] = len(bank_rows)

    # How many tracker rows already exist per (date, amount, type). Counting
    # rather than set-membership keeps two genuine same-amount payments apart.
    cursor.execute("""SELECT transaction_date, amount, transaction_type
                      FROM personal_transactions
                      WHERE bank = %s AND transaction_date BETWEEN %s AND %s""",
                   (bank_code, start, end))
    seen = {}
    for r in cursor.fetchall():
        key = (_as_date(r['transaction_date']), _as_money(r['amount']), r['transaction_type'])
        seen[key] = seen.get(key, 0) + 1

    for r in bank_rows:
        txn_date = _as_date(r['transaction_date'])
        is_credit = (r['cr_amount'] or 0) > 0
        amount = _as_money(r['cr_amount'] if is_credit else r['dr_amount'])
        vendor = (r['client_vendor'] or '').strip()

        def skip(reason):
            plan['skipped'].append({'date': txn_date, 'amount': amount,
                                    'vendor': vendor, 'reason': reason})

        if own_account_transfer(r):
            skip('own-account transfer')
            continue
        if not amount or amount <= 0:
            skip('zero amount')
            continue

        ttype = 'income' if is_credit else 'expense'
        key = (txn_date, amount, ttype)
        if seen.get(key, 0) > 0:
            seen[key] -= 1
            skip('already in tracker')
            continue

        plan['rows'].append({
            'date': txn_date,
            'vendor': vendor or 'Unknown',
            'description': purpose(r['transaction_description'], r['category']),
            'project': (r['project'] or '').strip() or 'General',
            'amount': amount,
            'transaction_type': ttype,
            'bank': bank_code,
        })
        plan['totals'][ttype] += amount

    plan['totals']['count'] = len(plan['rows'])
    return plan


def insert_plan(cursor, plan):
    """Write a plan's rows into the tracker. Caller commits."""
    if not plan['rows']:
        return 0
    cursor.executemany("""INSERT INTO personal_transactions
                          (transaction_date, vendor, description, project, amount,
                           transaction_type, bank)
                          VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                       [(r['date'], r['vendor'], r['description'], r['project'],
                         r['amount'], r['transaction_type'], r['bank'])
                        for r in plan['rows']])
    return len(plan['rows'])


def jsonify_plan(plan, row_limit=None):
    """Plan as plain JSON types, for the preview endpoint."""
    def d(v):
        return v.isoformat() if isinstance(v, (date, datetime)) else v

    rows = plan['rows'] if row_limit is None else plan['rows'][:row_limit]
    return {
        'bank': plan['bank'],
        'watermark': d(plan['watermark']),
        'start': d(plan['start']),
        'end': d(plan['end']),
        'scanned': plan['scanned'],
        'rows': [{**r, 'date': d(r['date']), 'amount': float(r['amount'])} for r in rows],
        'rows_truncated': row_limit is not None and len(plan['rows']) > row_limit,
        'skipped': [{**s, 'date': d(s['date']),
                     'amount': float(s['amount']) if s['amount'] is not None else None}
                    for s in plan['skipped']],
        'totals': {'expense': float(plan['totals']['expense']),
                   'income': float(plan['totals']['income']),
                   'count': plan['totals']['count']},
    }
