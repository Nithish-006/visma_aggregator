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
    receivable            total value - received  (what the client still owes)
    profit                total value - cost total (what the project makes)

`receivable` and `profit` are different questions and must not be conflated.
"""

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


def compute_project_finance(*, sales, purchase, po, received_total,
                            other_expense_total, labour_total, overhead,
                            other_cat_totals=None, has_sales_bills=None):
    """Return the full money picture for one project.

    sales / purchase: {'taxable', 'gst', 'total'} — summed bill figures.
    po:               {'taxable', 'gst', 'total'} — the purchase order.
    other_cat_totals: {category: amount} for the cost breakdown (optional).
    has_sales_bills:  override for whether this project has sales bills at all.
                      Period-scoped callers (the Excel export) pass the
                      *unfiltered* answer so a date range that happens to
                      exclude every sales bill can't silently flip the ladder
                      over to the full PO value.
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
    receivable = value_total - float(received_total or 0)
    profit = value_total - spend_total
    margin_pct = (profit / value_total * 100) if value_total > 0 else None

    # Built here so it always sums to spend_total, whatever the caller does.
    cost_lines = [
        {'label': 'MATERIAL PURCHASE', 'amount': material_total, 'source': 'purchase_bills'},
        {'label': 'LABOUR PAYMENT', 'amount': labour_total, 'source': 'labour'},
        {'label': 'GST PAYABLE', 'amount': gst_extra_cost, 'source': 'gst'},
        {'label': 'OVERHEAD', 'amount': overhead, 'source': 'manual'},
    ]
    cost_lines += [{'label': cat, 'amount': amt, 'source': 'expenses'}
                   for cat, amt in (other_cat_totals or {}).items()]
    cost_lines = sorted([l for l in cost_lines if l['amount'] > 0],
                        key=lambda l: l['amount'], reverse=True)

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
