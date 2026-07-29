"""Reconcile a project's purchase bills against its bank material spend.

Two independent records claim to describe the same thing — what this project
paid its material suppliers:

  * **Purchase bills** (``bill_invoices`` via the per-project allocation
    ledger) — the documents. This is what the money model actually charges as
    the project's material cost (see ``helpers/project_finance``, which
    deliberately EXCLUDES the bank's MATERIAL PURCHASE debits so the two can't
    double count).
  * **Bank MATERIAL PURCHASE debits** — the money that actually left.

When they disagree, one of them is wrong, and the money model is only as good
as the bills side. A payment with no bill means the project's cost is
understated (or the transaction is tagged to the wrong project); a bill with no
payment means it was settled in cash, is still outstanding, or the bill is
tagged to the wrong project. Neither can be resolved automatically — an auditor
has to look. This module's job is to lay the disagreement out per supplier so
that looking is cheap.

Design notes
------------
* **Bills are the anchor.** Distinct bill-vendor names are grouped first, then
  each bank vendor joins the *single best-matching* bill group, or forms its
  own "paid, never billed" group. Assigning to the best match rather than
  union-ing everything that matches is what stops one loosely-named bank vendor
  from chaining two genuinely different suppliers into one row.
* **Matching reuses ``helpers.bill_reconcile``'s vendor normalisation** — same
  stopwords, same fuzzy ratio — so the panel and the row-level "no bill" badge
  can never tell different stories. What's added here is a *score* (rather than
  a yes/no) so "best match" is well defined, and a small set of weak tokens
  (SRI, SAI, NEW, ...) that are too common to be evidence on their own.
* **Both sides are gross.** Bill totals are allocation totals including GST;
  bank debits are cash out. They are directly comparable.
* **Tolerance is relative and absolute.** Rounding, small round-offs and a few
  rupees of bank charge shouldn't read as a conflict, so a group is "ok" while
  the gap stays under ``max(abs, pct% of the larger side)``.
* **Whole-project only.** A month-scoped comparison would pair one month of
  payments against every bill and manufacture conflicts — the same mistake the
  project-summary KPI tiles used to make. Callers pass unfiltered data.
"""

from difflib import SequenceMatcher

from helpers.bill_reconcile import (
    MATERIAL_PURCHASE_CATEGORY,
    normalize_vendor_tokens,
    _FUZZY_RATIO_THRESHOLD,
)

# Tokens that appear across many unrelated suppliers — honorifics, generic
# qualifiers. bill_reconcile keeps them because for a *lenient* yes/no flag a
# false match only costs a missed warning. Here a false match silently merges
# two suppliers into one row and hides a real conflict, so they carry no weight
# on their own; a pair sharing only these has to clear the fuzzy ratio instead.
_WEAK_VENDOR_TOKENS = frozenset({
    'SRI', 'SHRI', 'SHREE', 'SREE', 'SAI', 'NEW', 'JAI', 'JAY', 'MS',
    'SUPER', 'ROYAL', 'NATIONAL', 'GLOBAL', 'UNITED', 'GENERAL', 'MODERN',
    'STEEL', 'STEELS', 'HARDWARE', 'HARDWARES', 'ENGINEERING', 'ENGINEERS',
    'CEMENT', 'CONSTRUCTION', 'CONSTRUCTIONS', 'BUILDERS', 'MATERIALS',
})

# Two vendors join the same group at or above this score. A shared *strong*
# token always clears it (see _match_score); anything less has to look alike.
_MATCH_THRESHOLD = 0.60

# A group is "ok" while the gap stays inside max(ABS, PCT% of the larger side).
# ₹100 absorbs rounding and small charges; 0.5% keeps large bills from being
# judged to the rupee.
DEFAULT_TOLERANCE_ABS = 100.0
DEFAULT_TOLERANCE_PCT = 0.5

# Statuses, worst-first — also the display order within an equal deviation.
STATUS_UNBILLED = 'unbilled'   # money went out, no bill on this project
STATUS_UNPAID = 'unpaid'       # bill on file, no matching payment
STATUS_SHORT = 'short'         # paid less than billed
STATUS_OVER = 'over'           # paid more than billed
STATUS_OK = 'ok'               # within tolerance

CONFLICT_STATUSES = (STATUS_UNBILLED, STATUS_UNPAID, STATUS_SHORT, STATUS_OVER)

# One line of guidance per status: what the auditor is actually being asked to
# check. Kept server-side so the panel, a future export, and any other surface
# word it identically.
STATUS_HINTS = {
    STATUS_UNBILLED: ('Money left the bank for this vendor but no purchase bill '
                      'is tagged to this project. Either the bill is missing, or '
                      'the payment belongs to another project.'),
    STATUS_UNPAID: ('A purchase bill is on file but no bank payment to this '
                    'vendor is tagged to this project. Either it was paid in '
                    'cash, is still outstanding, or the payment is tagged '
                    'elsewhere.'),
    STATUS_SHORT: ('Paid less than billed. Expect a part-payment or retention — '
                   'otherwise a payment is missing or tagged to another project.'),
    STATUS_OVER: ('Paid more than billed. Expect an advance — otherwise a bill '
                  'is missing or the payment belongs to another project.'),
    STATUS_OK: 'Bills and payments agree within tolerance.',
}


def is_material_purchase(category):
    """True for the bank category this reconciliation is about."""
    return str(category or '').strip().upper() == MATERIAL_PURCHASE_CATEGORY


def _match_score(a_tokens, b_tokens):
    """How strongly two vendor token-sets name the same supplier (0.0 - 1.0).

    A shared *strong* token is real evidence, so it floors the score above the
    threshold and is then graded by how much of the two names overlap — that
    grading is what makes "best match" meaningful when several bill vendors
    share a token with one bank vendor. With no strong token in common the pair
    has to look alike as whole strings, at bill_reconcile's own ratio.
    """
    if not a_tokens or not b_tokens:
        return 0.0
    ratio = SequenceMatcher(None,
                            ' '.join(sorted(a_tokens)),
                            ' '.join(sorted(b_tokens))).ratio()
    strong_a = a_tokens - _WEAK_VENDOR_TOKENS
    strong_b = b_tokens - _WEAK_VENDOR_TOKENS
    shared = strong_a & strong_b
    if shared:
        overlap = len(shared) / len(strong_a | strong_b)
        return max(_MATCH_THRESHOLD + (1.0 - _MATCH_THRESHOLD) * overlap, ratio)
    return ratio if ratio >= _FUZZY_RATIO_THRESHOLD else 0.0


def _tolerance_for(billed, paid, tol_abs, tol_pct):
    return max(tol_abs, max(abs(billed), abs(paid)) * tol_pct / 100.0)


def _classify(billed, paid, tolerance):
    """Status for one supplier ledger."""
    diff = paid - billed
    if abs(diff) <= tolerance:
        return STATUS_OK
    if billed <= tolerance:      # nothing meaningful billed
        return STATUS_UNBILLED
    if paid <= tolerance:        # nothing meaningful paid
        return STATUS_UNPAID
    return STATUS_OVER if diff > 0 else STATUS_SHORT


class _Group:
    """One supplier's two-sided ledger while it is being assembled."""

    __slots__ = ('tokens', 'names', 'bills', 'txns')

    def __init__(self, tokens, name):
        self.tokens = set(tokens)
        self.names = [name]
        self.bills = []
        self.txns = []

    def absorb(self, other):
        self.tokens |= other.tokens
        self.names.extend(other.names)
        self.bills.extend(other.bills)
        self.txns.extend(other.txns)

    @property
    def label(self):
        """The longest name we've seen for this supplier.

        Bank vendors are typed by hand and tend to be abbreviated; the invoice
        carries the registered name. Longest is a cheap proxy for "most
        complete", and every alias is returned alongside so the grouping stays
        auditable.
        """
        return max(self.names, key=lambda n: (len(n), n)) if self.names else 'Unknown'


def _group_bill_vendors(bill_rows):
    """Group purchase-bill rows by supplier.

    Distinct invoice spellings of one supplier ("BALU IRON PVT LTD" / "Balu
    Iron Co.") merge; unrelated suppliers stay apart.
    """
    groups = []
    by_name = {}
    for row in bill_rows:
        raw = str(row.get('vendor_name') or '').strip()
        key = raw.upper()
        group = by_name.get(key)
        if group is None:
            tokens = normalize_vendor_tokens(raw)
            group = None
            if tokens:
                # Merge into the best-matching existing bill group, if any.
                best, best_score = None, 0.0
                for g in groups:
                    score = _match_score(tokens, g.tokens)
                    if score > best_score:
                        best, best_score = g, score
                if best is not None and best_score >= _MATCH_THRESHOLD:
                    group = best
                    group.tokens |= tokens
                    group.names.append(raw or 'Unknown')
            if group is None:
                group = _Group(tokens, raw or 'Unknown')
                groups.append(group)
            by_name[key] = group
        group.bills.append(row)
    return groups


def _attach_bank_vendors(groups, bank_rows):
    """Attach each bank debit to its best-matching bill group, or a new one.

    A bank vendor never merges two bill groups: it picks the single strongest
    match and joins that one. Unmatched vendors group among themselves so two
    spellings of the same unbilled supplier read as one conflict, not two.
    """
    billed_groups = list(groups)   # frozen: candidates for the "best match" scan
    by_name = {}
    unmatched = []
    for row in bank_rows:
        raw = str(row.get('vendor') or '').strip()
        key = raw.upper()
        group = by_name.get(key)
        if group is None:
            tokens = normalize_vendor_tokens(raw)
            group = None
            if tokens:
                best, best_score = None, 0.0
                for g in billed_groups + unmatched:
                    score = _match_score(tokens, g.tokens)
                    if score > best_score:
                        best, best_score = g, score
                if best is not None and best_score >= _MATCH_THRESHOLD:
                    group = best
                    group.tokens |= tokens
                    group.names.append(raw or 'Unknown')
            if group is None:
                group = _Group(tokens, raw or 'Unknown')
                unmatched.append(group)
                groups.append(group)
            by_name[key] = group
        group.txns.append(row)
    return groups


def _bill_amount(row):
    return float(row.get('total_amount') or 0)


def _txn_amount(row):
    return float(row.get('dr_amount') or 0)


def reconcile_material(bill_rows, bank_rows, *,
                       tolerance_abs=DEFAULT_TOLERANCE_ABS,
                       tolerance_pct=DEFAULT_TOLERANCE_PCT):
    """Match one project's purchase bills against its bank material debits.

    ``bill_rows``  dicts with ``vendor_name``, ``total_amount`` and whatever
                   identifying fields the caller wants echoed back
                   (``invoice_number``, ``invoice_date``, ``id``).
    ``bank_rows``  dicts with ``vendor``, ``dr_amount``, ``date``, ``bank``,
                   ``description``.

    Both are expected to be already scoped to the project and unfiltered
    otherwise (see the module docstring on why).

    Returns ``{'summary': {...}, 'groups': [...]}`` with groups ordered
    conflicts-first by size of deviation — the auditor's work queue.
    """
    groups = _attach_bank_vendors(_group_bill_vendors(bill_rows), bank_rows)

    out = []
    for g in groups:
        billed = round(sum(_bill_amount(b) for b in g.bills), 2)
        paid = round(sum(_txn_amount(t) for t in g.txns), 2)
        tolerance = _tolerance_for(billed, paid, tolerance_abs, tolerance_pct)
        status = _classify(billed, paid, tolerance)
        aliases = sorted({n for n in g.names if n and n != g.label})
        out.append({
            'vendor': g.label,
            'aliases': aliases,
            'status': status,
            'billed': billed,
            'paid': paid,
            'difference': round(paid - billed, 2),
            'tolerance': round(tolerance, 2),
            'hint': STATUS_HINTS.get(status, ''),
            'bill_count': len(g.bills),
            'txn_count': len(g.txns),
            'bills': sorted(g.bills, key=lambda b: _bill_amount(b), reverse=True),
            'txns': sorted(g.txns, key=lambda t: _txn_amount(t), reverse=True),
        })

    # Conflicts first, biggest deviation first inside each half. A ₹4L unbilled
    # payment must not sit below a ₹900 rounding difference.
    out.sort(key=lambda r: (r['status'] == STATUS_OK, -abs(r['difference'])))

    billed_total = round(sum(r['billed'] for r in out), 2)
    paid_total = round(sum(r['paid'] for r in out), 2)
    counts = {s: 0 for s in (CONFLICT_STATUSES + (STATUS_OK,))}
    for r in out:
        counts[r['status']] += 1

    conflicts = [r for r in out if r['status'] != STATUS_OK]
    summary = {
        'billed_total': billed_total,
        'paid_total': paid_total,
        # Signed, payments-first: positive = paid more than billed (cost
        # understated), negative = billed more than paid.
        'difference': round(paid_total - billed_total, 2),
        'bill_count': sum(r['bill_count'] for r in out),
        'txn_count': sum(r['txn_count'] for r in out),
        'vendor_count': len(out),
        'conflict_count': len(conflicts),
        'matched_count': counts[STATUS_OK],
        # How much money each kind of conflict accounts for — the headline
        # number for "how bad is this project", per bucket.
        'unbilled_total': round(sum(r['paid'] for r in out
                                    if r['status'] == STATUS_UNBILLED), 2),
        'unpaid_total': round(sum(r['billed'] for r in out
                                  if r['status'] == STATUS_UNPAID), 2),
        'mismatch_total': round(sum(abs(r['difference']) for r in out
                                    if r['status'] in (STATUS_SHORT, STATUS_OVER)), 2),
        'counts': counts,
    }
    return {'summary': summary, 'groups': out}
