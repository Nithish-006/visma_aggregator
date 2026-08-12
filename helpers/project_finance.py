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
    third_party_total     of what the client paid us, the part we forwarded to
                          someone else on their behalf (civil, design, transport)
    net_received          received - third party (what actually stayed with us)
    receivable            contract total - net received (what the client still
                          owes against our own work)
    cash_position         net received - cost total (money in hand vs money spent)
    profit                contract total - cost total (what the job earns)
    billed_profit         sales bills total - cost total (earned on invoices raised)

Third-party payments are a **pass-through**, and that word decides where they do
and don't appear. Money the client sends us earmarked for a civil contractor or
a designer was never payment against our contract: it arrived in our account and
left again, settling their obligation to someone else, not to us. So everything
that asks "how much of this project has been paid for" reads the **net** —
`receivable` and `cash_position` both. What is left owing on our own work is the
contract less the part of the receipts that actually stayed with us.

What the pass-through must never touch is the earning side. The money was ours
neither to earn nor to spend, so it is not revenue and not a cost line:
`profit`, `billed_profit` and `spend_total` don't see it at all, and it must
never appear in `cost_lines`.

`receivable` and the three bottom-line figures answer different questions and
must not be conflated. The client committed to the contract — the PO plus any
agreed variations, or the actuals once the work has been finally measured (see
resolve_contract) — so what they still owe is the contract less what they've
paid, and what the job earns is that same contract less what it cost, however
much of it we've invoiced so far. Billing is a schedule; a part-billed project
is not a part-earned one. A project with no PO has no contract to measure
against, so `receivable` and `profit` fall back to the billed total.

`cash_position` and `billed_profit` are the same subtraction struck against cash
received and invoices raised instead. All three are returned rather than one
being chosen: which one matters depends on whether you're asking about the bank,
the contract, or the invoices, and a single figure called "balance" hid that.

Callers hand `compute_project_finance` the contract already resolved, as `po`.
It does not know the ledgers exist.
"""

# Both PO ledgers — variations and actuals — are quoted at a flat 18% when GST
# applies at all, the rate every contract this app has seen runs at. Kept as one
# named constant so a project at some other rate is a one-line change rather
# than a hunt for scattered literals.
PO_LEDGER_GST_RATE = 18.0

# Not every line carries GST: some items and services are outside it, and only
# the auditor entering the line knows which. That choice is stored as a zero
# rate rather than an is_exempt flag, so every figure downstream still follows
# from the same (quantity, rate, gst_rate) triple and there is no second code
# path for an exempt line to drift down.
PO_LEDGER_GST_EXEMPT = 0.0


def resolve_ledger_gst_rate(value):
    """The rate one ledger line is taxed at, from whatever the payload said.

    Returns (rate, error). Blank means "not stated", which is the standard rate:
    that is what every row written before the GST / N/A choice existed meant, so
    they keep pricing exactly as they always did. An explicit 0 is the exemption
    and is preserved — it must never be mistaken for a missing value.
    """
    if value is None or value == '':
        return PO_LEDGER_GST_RATE, None
    try:
        rate = float(value)
    except (ValueError, TypeError):
        return None, 'gst_rate must be a number'
    if rate < 0 or rate > 100:
        return None, 'gst_rate must be between 0 and 100'
    return rate, None

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


def compute_ledger_amounts(quantity, rate, gst_rate=PO_LEDGER_GST_RATE):
    """Price one PO ledger line — variation or actual: (basic, tax, total),
    each rounded to paise.

    Both ledgers price identically; they differ only in what the sum *means*
    (see compute_contract). For a variation, a reduction is just a negative
    quantity, so every figure flips sign together and a reduction subtracts
    exactly what the same addition would have added. Rounding basic before
    taxing it keeps the three figures self-consistent — tax is charged on the
    amount actually shown, so basic + tax == total to the paisa rather than
    drifting by half a unit.
    """
    basic = round(float(quantity or 0) * float(rate or 0), 2)
    tax = round(basic * float(gst_rate or 0) / 100.0, 2)
    return basic, tax, round(basic + tax, 2)


# The three keys every contract figure comes in. Named once so the folds below
# and their callers can't disagree about them.
CONTRACT_KEYS = ('taxable', 'tax', 'total')


def resolve_contract(base, variations, actuals, *, has_actuals):
    """Resolve the PO and its two ledgers into the contract actually in force.

    base / variations / actuals: {'taxable', 'tax', 'total'}. Missing keys read
    as zero, so a project with no PO gist can still be varied or measured.

    Two ledgers sit on top of the extracted PO and they compose differently:

      * **Variations are deltas.** Each is a change agreed after signing, so
        they *add* — revised = PO + variations, a reduction being a negative
        quantity that subtracts exactly what the same addition would add.

      * **Actuals are an absolute restatement.** They are the work as finally
        measured, so they *replace* — final = actuals, full stop. This exists
        because a project that comes in under its PO can't honestly be
        expressed as a delta: a large negative variation reads as a credit
        note against work that was never done, rather than as "this is what we
        actually built". Actuals supersede the variations too, not just the
        baseline — they measure everything executed, variation work included.

    The superseded rungs are still returned as `revised` because the PO section
    and the Excel export show the whole ladder: what was signed, what was
    agreed since, and what it finally came to. They are history, not inputs.

    `has_actuals` is passed rather than inferred from a non-zero total: a
    project genuinely measured at zero (cancelled after signing, nothing built)
    still has actuals in force, and testing `total > 0` would silently hand it
    back to the PO it never delivered against.

    Returns {'revised': {...}, 'final': {...}, 'source': 'actuals' | 'po'}.
    """
    revised = {k: round(float(base.get(k) or 0) + float(variations.get(k) or 0), 2)
               for k in CONTRACT_KEYS}
    if not has_actuals:
        return {'revised': revised, 'final': revised, 'source': 'po'}
    final = {k: round(float(actuals.get(k) or 0), 2) for k in CONTRACT_KEYS}
    return {'revised': revised, 'final': final, 'source': 'actuals'}


def compute_project_finance(*, sales, purchase, po, received_total,
                            other_expense_total, labour_total, overhead,
                            other_cat_totals=None, has_sales_bills=None,
                            has_po=None, third_party_total=0):
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
    third_party_total: of `received_total`, the part paid straight on to a third
                      party on the client's behalf. Subtracted from received to
                      get the cash that actually stayed with us, which is what
                      both `receivable` and `cash_position` are struck against;
                      see the module docstring for why it touches nothing else.
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
    # Gross, as the client paid it — then net, after the part forwarded straight
    # on to a third party. Deliberately not clamped at zero: a third-party total
    # exceeding what has been received is a real state — we paid the contractor
    # ahead of the client paying us — and a negative net is the honest reading of
    # it, not an error to hide.
    received = float(received_total or 0)
    third_party = float(third_party_total or 0)
    net_received = received - third_party
    # Struck against the net, not the gross: money that came in earmarked for a
    # contractor and went straight back out never paid down our contract, so
    # counting it here would report a project as settled on work the client has
    # not actually paid us for.
    receivable = contract_total - net_received

    # Three ways to read the same spend, and the difference between them is the
    # difference between cash, contract and invoices. All three are reported —
    # picking one and calling it "the balance" is what made the figure ambiguous:
    #
    #   cash_position  net received - cost. Money actually in hand against money
    #                  actually gone out. Ignores what is owed or promised, so a
    #                  profitable project reads negative until the client pays.
    #                  Net, not gross: money forwarded to a third party is not
    #                  in hand, and counting it here would report cash we no
    #                  longer hold as available to spend.
    #   profit         contract - cost. What the job earns. The client committed
    #                  to the PO (plus variations, or the actuals once measured),
    #                  so that is what the project is worth however much of it
    #                  has been invoiced so far — billing is a schedule, and a
    #                  part-billed project is not a part-earned one.
    #   billed_profit  sales bills - cost. The same question asked of what has
    #                  actually been invoiced; equals `profit` once the contract
    #                  is fully billed, and short of it before then.
    cash_position = net_received - spend_total
    profit = contract_total - spend_total
    billed_profit = sales_total - spend_total
    margin_pct = (profit / contract_total * 100) if contract_total > 0 else None

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
        'received_total': received,
        'third_party_total': third_party,
        'net_received': net_received,
        'cash_position': cash_position,
        'profit': profit,
        'billed_profit': billed_profit,
        # Whether anything was invoiced at all, so a caller can say "nothing
        # billed yet" instead of printing billed_profit as a bare loss.
        'has_sales_bills': bool(has_sales_bills),
        'margin_pct': margin_pct,
        'material_total': material_total,
        'other_expense_total': other_expense_total,
        'labour_total': labour_total,
        'overhead': overhead,
        'spend_total': spend_total,
        'cost_lines': cost_lines,
    }
