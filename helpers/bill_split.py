"""Pure math for splitting a purchase bill across projects.

A split divides the bill's grand total across N projects by rupee amount. Every
other money column (taxable, cgst, sgst, igst) is apportioned in the SAME
proportion, so each column sums back to the bill's own value to the paisa —
which is what keeps registry / P&L / summary totals exact after a split.

No DB or Flask state here; see database.set_bill_allocations for persistence and
blueprints/bills.py for the endpoint.
"""

import math

# Sentinel written to bill_invoices.project when a bill is split across projects.
# Per-project money is read from the allocation ledger, not this column, so the
# sentinel only affects legacy/display readers.
MULTI_PROJECT_TAG = 'MULTIPLE'


def apportion(total, weights):
    """Split `total` (rupees) into len(weights) parts proportional to `weights`,
    each rounded to paisa, summing EXACTLY to round(total, 2).

    Uses the largest-remainder (Hamilton) method: floor every share, then hand
    the leftover paisa out one at a time to the largest fractional remainders.
    Deterministic; ties break toward the earlier index.
    """
    n = len(weights)
    total_paise = int(round(float(total) * 100))
    wsum = float(sum(weights))

    if n == 0:
        return []
    if wsum <= 0:
        # Degenerate weights: fall back to an even split of the paise.
        base = total_paise // n
        parts = [base] * n
        for k in range(total_paise - base * n):
            parts[k] += 1
        return [p / 100.0 for p in parts]

    raw = [float(w) / wsum * total_paise for w in weights]
    floor = [int(math.floor(r)) for r in raw]
    leftover = total_paise - sum(floor)  # paise still to distribute (can be < 0)

    order = sorted(range(n), key=lambda i: (raw[i] - floor[i], -i), reverse=True)
    if leftover > 0:
        for k in range(leftover):
            floor[order[k % n]] += 1
    elif leftover < 0:
        # Negative total (e.g. credit note): pull paise from the smallest remainders.
        for k in range(-leftover):
            floor[order[n - 1 - (k % n)]] -= 1

    return [p / 100.0 for p in floor]


def compute_split_allocations(bill, targets):
    """Build allocation rows for a bill split across projects.

    bill:    dict with float keys subtotal, total_cgst, total_sgst, total_igst,
             total_amount (the bill's own money columns).
    targets: list of {'project': str, 'amount': float} — the per-project grand
             total the user entered. Must already be validated (see
             validate_split_targets).

    Returns a list of dicts, one per target, with keys project, alloc_taxable,
    alloc_cgst, alloc_sgst, alloc_igst, alloc_total. Every alloc_* column sums
    across the list to the matching bill column, to the paisa.
    """
    weights = [float(t['amount']) for t in targets]

    taxable = apportion(bill.get('subtotal', 0) or 0, weights)
    cgst = apportion(bill.get('total_cgst', 0) or 0, weights)
    sgst = apportion(bill.get('total_sgst', 0) or 0, weights)
    igst = apportion(bill.get('total_igst', 0) or 0, weights)
    # Apportion the bill's own grand total by the same weights, rather than
    # trusting the raw entered amounts, so the shares always sum to total_amount
    # exactly even if the entries were off by a rounding paisa.
    total = apportion(bill.get('total_amount', 0) or 0, weights)

    out = []
    for i, t in enumerate(targets):
        out.append({
            'project': t['project'],
            'alloc_taxable': taxable[i],
            'alloc_cgst': cgst[i],
            'alloc_sgst': sgst[i],
            'alloc_igst': igst[i],
            'alloc_total': total[i],
        })
    return out


def validate_split_targets(bill_total, targets, tolerance=0.01):
    """Validate a split request. Returns (ok, error_message).

    Rules: at least 2 targets, each with a project and a positive amount, and
    the amounts must sum to the bill's grand total within `tolerance` rupees.
    A zero-total bill cannot be split by amount.
    """
    if not isinstance(targets, list) or len(targets) < 2:
        return False, "A split needs at least 2 projects."

    if abs(float(bill_total or 0)) < tolerance:
        return False, "This bill has no total amount to split."

    seen = set()
    total = 0.0
    for t in targets:
        project = (t.get('project') or '').strip()
        if not project:
            return False, "Every split row needs a project."
        if project in seen:
            return False, f"Project '{project}' appears more than once — combine it into one row."
        seen.add(project)
        try:
            amount = float(t.get('amount'))
        except (TypeError, ValueError):
            return False, "Every split row needs a valid amount."
        if amount <= 0:
            return False, "Every split amount must be greater than zero."
        total += amount

    if abs(total - float(bill_total)) >= tolerance:
        return False, (f"Split amounts (₹{total:,.2f}) must add up to the bill total "
                       f"(₹{float(bill_total):,.2f}).")

    return True, None
