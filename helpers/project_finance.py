"""The per-project money model, in one place.

The registry detail pop-up (blueprints/projects.py) and the Excel export
(reports/project_summary_export.py) both present the same picture: a value
ladder, a GST position, and a cost breakdown. They used to compute it twice and
drifted. Everything here is pure arithmetic over primitives so both callers can
share it regardless of how they fetched their numbers.

The model (verified against the client's own summary sheet):

    basic / GST / total   from sales bills — what we actually billed the client;
                          the PO is the contract and only a fallback.
    GST extra             sales GST - purchase GST: the amount remitted. It is
                          both a headline figure and a real cost line. Negative
                          means input GST exceeds output — a credit carried
                          forward, never a cost.
    cost total            material (purchase bills, gross) + other bank debits
                          + labour + GST extra + overhead.
    receivable            contract total - received (what the client still owes)
    profit                total value - cost total (what the project makes)

`receivable` and `profit` are different questions and must not be conflated,
and they deliberately read off different figures. The client committed to the
contract — the PO plus any agreed variations — so what they still owe is the
contract less what they've paid, however much of it we've invoiced so far.
Profit stays on the sales bills: the PO is the promise, the bills are the
revenue. A project with no PO has no contract to measure against, so its
receivable falls back to the billed total.
"""

# Variations are quoted at a flat 18% — the rate every contract this app has
# seen runs at. Kept as one named constant so a project at some other rate is a
# one-line change rather than a hunt for scattered literals.
PO_VARIATION_GST_RATE = 18.0

# Categories excluded from the "other" bank-debit bucket: material and labour
# arrive from bills and the attendance API respectively, so counting the bank
# rows too would double count. The rest are internal heads.
LABOUR_CATS = {'LABOUR PAYMENT', 'LABOR PAYMENT', 'LABOUR', 'LABOR'}
OTHER_EXCLUDE_CATS = {'MATERIAL PURCHASE', 'AMOUNT RECEIVED', 'SALARY AC',
                      'BANK CHARGES', 'DUTIES & TAX'}


def is_other_expense_category(category) -> bool:
    """True when a bank-debit category feeds the "other expense" bucket."""
    cat = str(category or '').upper().strip()
    return cat not in OTHER_EXCLUDE_CATS and cat not in LABOUR_CATS


def compute_variation_amounts(quantity, rate, gst_rate=PO_VARIATION_GST_RATE):
    """Price one PO variation: (basic, tax, total), each rounded to paise.

    A reduction is just a negative quantity, so every figure flips sign together
    and a reduction subtracts exactly what the same addition would have added.
    Rounding basic before taxing it keeps the three figures self-consistent —
    tax is charged on the amount actually shown, so basic + tax == total to the
    paisa rather than drifting by half a unit.
    """
    basic = round(float(quantity or 0) * float(rate or 0), 2)
    tax = round(basic * float(gst_rate or 0) / 100.0, 2)
    return basic, tax, round(basic + tax, 2)


def compute_project_finance(*, sales, purchase, po, received_total,
                            other_expense_total, labour_total, overhead,
                            other_cat_totals=None, has_sales_bills=None,
                            has_po=None):
    """Return the full money picture for one project.

    sales / purchase: {'taxable', 'gst', 'total'} — summed bill figures.
    po:               {'taxable', 'gst', 'total'} — the contract (PO + agreed
                      variations; the caller folds those in).
    other_cat_totals: {category: amount} for the cost breakdown (optional).
    has_sales_bills:  override for whether this project has sales bills at all.
                      Period-scoped callers (the Excel export) pass the
                      *unfiltered* answer so a date range that happens to
                      exclude every sales bill can't silently flip the ladder
                      over to the full PO value.
    has_po:           whether a contract exists at all, which is NOT the same
                      question as whether it is worth anything. Variations can
                      cancel a PO down to zero (a cancelled order), and that
                      contract still governs the receivable — inferring
                      existence from `total > 0` would quietly hand such a
                      project back to the sales-bill rule.
    """
    sales_total = float(sales.get('total') or 0)
    po_total = float(po.get('total') or 0)

    # Presence of a sales bill isn't enough to make it the source: a bill whose
    # amounts failed extraction is tagged but worth 0, and taking it would zero
    # the ladder and report the project as fully overpaid. So the default test
    # is on value, not count.
    #
    # Once a project is known to have sales bills, though, they stay the source
    # even if the caller's (period-scoped) figures sum to zero — falling back to
    # the full PO there would compare a whole-contract value against
    # period-scoped costs and invent a profit.
    if has_sales_bills is None:
        has_sales_bills = sales_total > 0

    if has_sales_bills:
        value_basic = float(sales.get('taxable') or 0)
        value_gst = float(sales.get('gst') or 0)
        value_total = sales_total
        value_source = 'sales_bills'
    elif po_total > 0:
        value_basic = float(po.get('taxable') or 0)
        value_gst = float(po.get('gst') or 0)
        value_total = po_total
        value_source = 'po'
    else:
        value_basic = value_gst = value_total = 0.0
        value_source = 'none'

    gst_extra = float(sales.get('gst') or 0) - float(purchase.get('gst') or 0)
    gst_extra_cost = max(0.0, gst_extra)

    material_total = float(purchase.get('total') or 0)
    overhead = float(overhead or 0)
    other_expense_total = float(other_expense_total or 0)
    labour_total = float(labour_total or 0)

    spend_total = (material_total + other_expense_total + labour_total
                   + gst_extra_cost + overhead)
    # Measured against the contract (PO + agreed variations), not the invoices:
    # billing 92% of the contract doesn't mean the client owes 92% of it. With
    # no PO there is no contract, so the billed total is the only promise there
    # is to measure against.
    if has_po is None:
        has_po = po_total > 0
    contract_total = po_total if has_po else value_total
    contract_source = 'po' if has_po else value_source
    receivable = contract_total - float(received_total or 0)
    profit = value_total - spend_total
    margin_pct = (profit / value_total * 100) if value_total > 0 else None

    # Built here so it always sums to spend_total, whatever the caller does.
    cost_lines = [
        {'label': 'MATERIAL PURCHASE', 'amount': material_total, 'source': 'purchase_bills'},
        {'label': 'LABOUR PAYMENT', 'amount': labour_total, 'source': 'labour'},
        {'label': 'GST PAYABLE', 'amount': gst_extra_cost, 'source': 'gst'},
    ]
    cost_lines += [{'label': cat, 'amount': amt, 'source': 'expenses'}
                   for cat, amt in (other_cat_totals or {}).items()]
    cost_lines = [l for l in cost_lines if l['amount'] > 0]
    cost_lines.sort(key=lambda l: l['amount'], reverse=True)
    # Overhead is pinned last rather than sorted in by size: it is the one line
    # entered by hand, so it sits with the totals it feeds. It is always listed
    # even at zero — the other zero-valued lines are filtered out, and a missing
    # row would leave nothing to edit for a project that has no overhead yet.
    cost_lines.append({'label': 'OVERHEAD', 'amount': overhead,
                       'source': 'manual', 'editable': True})

    return {
        'value': {
            'basic': value_basic,
            'gst': value_gst,
            'total': value_total,
            'source': value_source,
        },
        'gst': {
            'purchase_basic': float(purchase.get('taxable') or 0),
            'purchase_gst': float(purchase.get('gst') or 0),
            'purchase_total': material_total,
            'sales_basic': float(sales.get('taxable') or 0),
            'sales_gst': float(sales.get('gst') or 0),
            'sales_total': sales_total,
            'extra': gst_extra,
            'extra_cost': gst_extra_cost,
        },
        'contract': {
            'total': contract_total,
            'source': contract_source,
        },
        'receivable': receivable,
        'profit': profit,
        'margin_pct': margin_pct,
        'material_total': material_total,
        'other_expense_total': other_expense_total,
        'labour_total': labour_total,
        'overhead': overhead,
        'spend_total': spend_total,
        'cost_lines': cost_lines,
    }
