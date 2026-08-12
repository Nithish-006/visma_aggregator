# ============================================================================
# EXTRACTION VALIDATOR — Reconciliation layer for bill/invoice extraction
# ============================================================================
# Pure-Python, no external dependencies. Run AFTER every Gemini extraction and
# before/at DB save. Catches the two recurring extraction bugs:
#   1. Freight / packing / loading swept into GST totals (inflated tax).
#   2. Wrong totals on multi-page bills (page-1 subtotal instead of final total).
#
# It does this by checking the extracted numbers against each other (header
# identity, line-item sums, per-line GST-rate math). Internally inconsistent
# bills get flagged 'review'; clean bills stay 'ok'. This is what lets the
# system catch its own mistakes and surface only the few bad ones.
# ============================================================================

import re

# Default rounding tolerance in INR. Vendors round line totals differently, so
# a couple of rupees of drift is normal. Tunable per-call / configurable.
DEFAULT_TOLERANCE = 2.0


def _num(value):
    """Coerce an extracted value to float, tolerating strings with commas,
    currency symbols, blanks and None. Returns 0.0 when uncoercible."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    # Strip everything that isn't part of a number (₹, commas, spaces, etc.),
    # keeping digits, a leading sign and the decimal point.
    cleaned = re.sub(r'[^0-9.\-]', '', s)
    if cleaned in ('', '-', '.', '-.'):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _other_charges_total(data):
    """Sum of genuine other-charge entries (freight/packing/etc.)."""
    total = 0.0
    for c in data.get('other_charges', []) or []:
        # Only count entries that actually describe a charge — mirrors how the
        # rest of the app (Excel export, DB save) treats other_charges.
        if c.get('description'):
            total += _num(c.get('amount'))
    return total


def _issue(code, title, severity, actual_label, actual, expected_label, expected,
           meaning, fix, terms=None, line_no=None, equation=True):
    """One structured deviation, shaped for the review dialog.

    actual/expected are the two sides of the equation that failed; `terms` is
    the optional breakdown of the expected side so the UI can show the working
    line by line. `meaning` says what this usually indicates in these bills and
    `fix` proposes the concrete next step. `equation` is False for sanity checks
    (a missing or negative figure) where there is no two-sided sum to show.
    """
    return {
        'equation': equation,
        'code': code,
        'title': title,
        'severity': severity,
        'line_no': line_no,
        'actual_label': actual_label,
        'actual': round(actual, 2),
        'expected_label': expected_label,
        'expected': round(expected, 2),
        'delta': round(actual - expected, 2),
        'terms': terms or [],
        'meaning': meaning,
        'fix': fix,
    }


def validate_extraction(data, tolerance=DEFAULT_TOLERANCE):
    """
    Reconcile an extracted invoice's numbers against each other.

    Args:
        data: the inner extraction dict (the value of result['data']) with
              keys 'taxes', 'line_items', 'other_charges'. Accepts the stored
              DB-shaped dict too (see validate_db_row for that adapter).
        tolerance: INR rounding tolerance absorbed before a check fails.

    Returns a dict:
        {
          "status": "ok" | "review",
          "score": 0-100,
          "diff": <header-identity gap in INR, signed>,
          "failures": ["header_identity off by 1180.00", ...],
          "issues": [ {...structured deviation, see _issue()...} ],
          "worksheet": {...the header-identity terms, for display...}
        }

    'failures' is the terse one-line-per-problem form that goes into the
    validation_notes column. 'issues' is the same information expanded for the
    auditor-facing review dialog: what deviated, by how much, what it usually
    means and what to do about it. Both are produced from the same checks, so
    they can never disagree.
    """
    taxes = data.get('taxes', {}) or {}

    subtotal = _num(taxes.get('subtotal')) or _num(taxes.get('taxable_amount'))
    cgst = _num(taxes.get('total_cgst')) or _num(taxes.get('cgst_amount'))
    sgst = _num(taxes.get('total_sgst')) or _num(taxes.get('sgst_amount'))
    igst = _num(taxes.get('total_igst')) or _num(taxes.get('igst_amount'))
    round_off = _num(taxes.get('round_off'))
    total_amount = _num(taxes.get('total_amount'))
    other_charges = _other_charges_total(data)

    line_items = data.get('line_items', []) or []

    failures = []
    issues = []
    # Track how many checks were applicable and how many passed, for scoring.
    checks_applicable = 0
    checks_passed = 0

    # --- Check 1: Header identity ------------------------------------------
    # total ≈ subtotal + cgst + sgst + igst + other_charges + round_off
    # This is the single most informative check: it breaks when freight is
    # double-counted/dropped or when a wrong (page-1) total was read.
    expected_total = subtotal + cgst + sgst + igst + other_charges + round_off
    header_diff = total_amount - expected_total
    if total_amount > 0:
        checks_applicable += 1
        if abs(header_diff) <= tolerance:
            checks_passed += 1
        else:
            failures.append(f"header_identity off by {header_diff:+.2f} "
                            f"(total {total_amount:.2f} vs sum {expected_total:.2f})")
            if header_diff > 0:
                meaning = ("The printed grand total is HIGHER than its own parts. "
                           "Usually a charge on the bill was never captured — "
                           "freight, packing, loading or a handling fee that "
                           "belongs in Other charges — or the subtotal was read "
                           "from a page-1 sub-total on a multi-page bill.")
                fix = (f"Add the missing {abs(header_diff):,.2f} as an Other charge "
                       f"(check the bill for freight/packing/loading), or correct the "
                       f"subtotal if this is a multi-page bill and the last page "
                       f"carries the real taxable value.")
            else:
                meaning = ("The parts add up to MORE than the printed grand total. "
                           "Usually a figure has been counted twice — a freight "
                           "line captured both as Other charges and inside the "
                           "taxable value, or a discount that was not deducted.")
                fix = (f"Remove the duplicated {abs(header_diff):,.2f} — check whether "
                       f"Other charges is already included in the subtotal, or whether "
                       f"a discount/round-off on the bill is missing here.")
            issues.append(_issue(
                'header_identity',
                'Grand total does not equal the sum of its parts',
                'high',
                'Total printed on the bill', total_amount,
                'Subtotal + taxes + other charges + round off', expected_total,
                meaning, fix,
                terms=[
                    {'label': 'Subtotal (taxable value)', 'value': round(subtotal, 2)},
                    {'label': 'CGST', 'value': round(cgst, 2)},
                    {'label': 'SGST', 'value': round(sgst, 2)},
                    {'label': 'IGST', 'value': round(igst, 2)},
                    {'label': 'Other charges (freight, packing…)', 'value': round(other_charges, 2)},
                    {'label': 'Round off', 'value': round(round_off, 2)},
                ]))

    # --- Check 2: Line-items vs header --------------------------------------
    # NOTE: a deliberate non-check is the sum of the line "amount" column vs the
    # grand total. In this data the per-line "amount" is the PRE-TAX value (it
    # equals taxable_value), so its sum is the subtotal, never the tax-inclusive
    # total — comparing the two flags virtually every clean bill. The taxable
    # sum below already covers "are all line items present", so the amount-sum
    # check is omitted on purpose.
    if line_items:
        li_taxable = sum(_num(li.get('taxable_value')) for li in line_items)
        li_cgst = sum(_num(li.get('cgst_amount')) for li in line_items)
        li_sgst = sum(_num(li.get('sgst_amount')) for li in line_items)
        li_igst = sum(_num(li.get('igst_amount')) for li in line_items)

        # 2a. taxable sum vs subtotal — catches a missing / misread line item
        # (taxable values don't round, so any real gap means line detail is off).
        if subtotal > 0 and li_taxable > 0:
            checks_applicable += 1
            d = li_taxable - subtotal
            if abs(d) <= tolerance:
                checks_passed += 1
            else:
                failures.append(f"line_taxable sum off by {d:+.2f} "
                                f"(items {li_taxable:.2f} vs subtotal {subtotal:.2f})")
                if d < 0:
                    meaning = ("The line items add up to LESS than the subtotal, so "
                               "at least one line was not read — typically a line "
                               "that continues onto the next page, or a row printed "
                               "across a page break.")
                    fix = (f"Open the source PDF and look for the missing "
                           f"{abs(d):,.2f} of line detail; re-extract the bill, or "
                           f"add the missing line manually in Edit.")
                else:
                    meaning = ("The line items add up to MORE than the subtotal — a "
                               "line was read twice (common when the same table "
                               "header repeats on each page) or the subtotal itself "
                               "was picked up from an intermediate page.")
                    fix = (f"Check for a duplicated line worth {abs(d):,.2f}, or "
                           f"correct the subtotal to the figure on the final page.")
                issues.append(_issue(
                    'line_taxable_sum',
                    'Line items do not add up to the subtotal',
                    'high',
                    f'Sum of {len(line_items)} line items (taxable value)', li_taxable,
                    'Subtotal on the bill', subtotal,
                    meaning, fix))

        # 2b. line tax sums vs header tax totals — MAGNITUDE-AWARE.
        # A correctly-handled freight bill legitimately shows header tax that is
        # slightly higher than the line tax (it includes the GST charged on the
        # freight, whose BASE sits in other_charges and has no line of its own).
        # That benign gap is at most ~GST-rate of other_charges, plus per-line
        # rounding. We only flag a gap LARGER than that — which is what happens
        # when a freight BASE is wrongly swept into total_cgst/sgst/igst, or the
        # header tax is otherwise gross-wrong. Only meaningful when the line
        # items actually carry a tax breakdown.
        if (li_cgst + li_sgst + li_igst) > 0:
            for label, li_tax, hdr_tax in (
                ('cgst', li_cgst, cgst),
                ('sgst', li_sgst, sgst),
                ('igst', li_igst, igst),
            ):
                if hdr_tax > 0 or li_tax > 0:
                    checks_applicable += 1
                    d = li_tax - hdr_tax
                    # Benign budget: GST plausibly charged on other_charges
                    # (use the max 18% slab), a per-line rounding floor, and 1%
                    # of the larger tax figure.
                    benign = max(2.5 * tolerance,
                                 other_charges * 0.18,
                                 0.01 * max(hdr_tax, li_tax))
                    if abs(d) <= benign:
                        checks_passed += 1
                    else:
                        failures.append(f"line_{label} sum off by {d:+.2f} "
                                        f"(items {li_tax:.2f} vs header {hdr_tax:.2f})")
                        up = label.upper()
                        if d < 0:
                            meaning = (f"The {up} shown in the bill's tax summary is "
                                       f"larger than the {up} on the lines by more "
                                       f"than freight tax and rounding can explain. "
                                       f"The classic cause is a freight/packing "
                                       f"charge swept into the {up} total instead of "
                                       f"sitting in Other charges.")
                            fix = (f"Move the extra {abs(d):,.2f} out of {up}: put the "
                                   f"charge into Other charges and leave only the real "
                                   f"tax in {up}. Re-extract first — this is usually "
                                   f"fixed automatically on a second pass.")
                        else:
                            meaning = (f"The lines carry more {up} than the bill's tax "
                                       f"summary shows, so the summary {up} was "
                                       f"misread or a line's tax was over-read.")
                            fix = (f"Compare the {up} figure in the bill's tax summary "
                                   f"with the lines and correct whichever side is "
                                   f"wrong (gap {abs(d):,.2f}).")
                        issues.append(_issue(
                            f'line_{label}_sum',
                            f'{up} on the lines does not match the {up} in the tax summary',
                            'high',
                            f'Sum of line {up}', li_tax,
                            f'{up} in the bill tax summary', hdr_tax,
                            meaning, fix))

        # --- Check 3: Per-line GST-rate sanity ------------------------------
        # Catches the freight-in-GST bug directly: a charge misclassified as
        # tax won't satisfy cgst_amount ≈ taxable × cgst_rate/100.
        for idx, li in enumerate(line_items, 1):
            tv = _num(li.get('taxable_value'))
            if tv <= 0:
                continue
            for label, rate_key, amt_key in (
                ('cgst', 'cgst_rate', 'cgst_amount'),
                ('sgst', 'sgst_rate', 'sgst_amount'),
                ('igst', 'igst_rate', 'igst_amount'),
            ):
                rate = _num(li.get(rate_key))
                amt = _num(li.get(amt_key))
                if rate <= 0 and amt <= 0:
                    continue  # this tax type not applicable to this line
                checks_applicable += 1
                expected_amt = tv * rate / 100.0
                # Per-line tolerance scales with the line value (rounding adds up).
                line_tol = max(tolerance, tv * 0.01)
                if abs(amt - expected_amt) <= line_tol:
                    checks_passed += 1
                else:
                    failures.append(
                        f"line {idx} {label} {amt:.2f} != {tv:.2f}x{rate:.1f}% "
                        f"(expected {expected_amt:.2f})")
                    up = label.upper()
                    desc = (li.get('description') or li.get('item_description')
                            or li.get('particulars') or '')
                    where = f"Line {idx}" + (f" — {str(desc)[:60]}" if desc else "")
                    issues.append(_issue(
                        f'line_rate_{label}',
                        f'{where}: {up} amount does not match its own rate',
                        'medium',
                        f'{up} shown on the line', amt,
                        f'{tv:,.2f} x {rate:.1f}%', expected_amt,
                        (f"On this line the {up} amount and the {up} rate disagree. "
                         f"Either the rate was misread (a 9% line read as 14%, say), "
                         f"or a charge that is not tax was written into the {up} "
                         f"column, or the taxable value of the line is wrong."),
                        (f"Check line {idx} on the bill: confirm the {up} rate is "
                         f"{rate:.1f}% and the taxable value is {tv:,.2f}. Correct "
                         f"whichever is wrong in Edit, or re-extract the bill."),
                        line_no=idx))

    # --- Check 4: Sign / range sanity --------------------------------------
    checks_applicable += 1
    range_ok = True
    if total_amount <= 0:
        range_ok = False
        failures.append("total_amount is not positive")
        issues.append(_issue(
            'total_not_positive', 'No grand total was read from this bill', 'high',
            'Total on record', total_amount, 'Any positive amount', 0.0,
            "The bill was saved without a usable grand total — normally a scan "
            "the model could not read, or a page that is not an invoice at all.",
            "Open the source file and check it is the right page. Re-extract; if "
            "the scan is unreadable, key the totals in manually via Edit.",
            equation=False))
    if cgst < 0 or sgst < 0 or igst < 0:
        range_ok = False
        failures.append("negative tax amount")
        issues.append(_issue(
            'negative_tax', 'A tax amount is negative', 'high',
            'CGST + SGST + IGST', cgst + sgst + igst, 'Zero or more', 0.0,
            "A negative tax figure usually means a credit note was processed as "
            "an invoice, or a minus sign was picked up from the layout.",
            "Confirm whether this document is a credit note. If it is an invoice, "
            "re-extract or correct the tax figures in Edit.",
            equation=False))
    if subtotal < 0:
        range_ok = False
        failures.append("negative subtotal")
        issues.append(_issue(
            'negative_subtotal', 'Subtotal is negative', 'high',
            'Subtotal', subtotal, 'Zero or more', 0.0,
            "A negative taxable value normally means a credit note, or a "
            "discount row read as the subtotal.",
            "Confirm the document type and correct the subtotal in Edit.",
            equation=False))
    # Total tax should never exceed the taxable base on a real GST invoice.
    total_tax = cgst + sgst + igst
    if subtotal > 0 and total_tax > subtotal:
        range_ok = False
        failures.append(f"total tax {total_tax:.2f} exceeds subtotal {subtotal:.2f}")
        issues.append(_issue(
            'tax_exceeds_subtotal', 'Tax is larger than the taxable value', 'high',
            'CGST + SGST + IGST', total_tax, 'Subtotal (tax can never exceed it)', subtotal,
            "On a GST invoice tax is at most 28% of the taxable value, so tax "
            "above the subtotal means either the subtotal was read far too low "
            "(a single line instead of the total) or a non-tax amount landed in "
            "the tax fields.",
            "Re-read the bill's tax summary: correct the subtotal to the full "
            "taxable value, and move any freight/packing out of the tax fields."))
    if range_ok:
        checks_passed += 1

    # --- Score & status -----------------------------------------------------
    if checks_applicable == 0:
        score = 0
    else:
        score = round(100 * checks_passed / checks_applicable)

    status = 'ok' if not failures else 'review'

    return {
        'status': status,
        'score': score,
        'diff': round(header_diff, 2),
        'failures': failures,
        'issues': issues,
        # The header-identity working, always returned (even when clean) so the
        # review dialog can show the auditor the full reconciliation, not only
        # the lines that failed.
        'worksheet': {
            'subtotal': round(subtotal, 2),
            'cgst': round(cgst, 2),
            'sgst': round(sgst, 2),
            'igst': round(igst, 2),
            'other_charges': round(other_charges, 2),
            'round_off': round(round_off, 2),
            'expected_total': round(expected_total, 2),
            'total_amount': round(total_amount, 2),
            'line_item_count': len(line_items),
            'checks_applicable': checks_applicable,
            'checks_passed': checks_passed,
            'tolerance': tolerance,
        },
    }


def validate_db_row(invoice_row, line_item_rows, tolerance=DEFAULT_TOLERANCE):
    """
    Adapter: run the same reconciliation on a stored DB row (flat columns)
    instead of the nested extraction dict. Used by C1 (validate the existing
    ~200 bills) and any re-check on stored data.

    Args:
        invoice_row: dict-like row from bill_invoices / sales_invoices with
                     flat columns (subtotal, total_cgst, ..., other_charges).
        line_item_rows: list of dict-like rows from *_line_items.
    """
    data = {
        'taxes': {
            'subtotal': invoice_row.get('subtotal'),
            'total_cgst': invoice_row.get('total_cgst'),
            'total_sgst': invoice_row.get('total_sgst'),
            'total_igst': invoice_row.get('total_igst'),
            'round_off': invoice_row.get('round_off'),
            'total_amount': invoice_row.get('total_amount'),
        },
        # In the DB, other_charges is a single pre-summed column, not a list.
        # Represent it as one synthetic entry so _other_charges_total picks it up.
        'other_charges': [{'description': 'other_charges',
                           'amount': invoice_row.get('other_charges')}]
        if _num(invoice_row.get('other_charges')) else [],
        'line_items': [
            {
                # Carried through only so a per-line deviation can name the item
                # it refers to in the review dialog.
                'description': li.get('description'),
                'taxable_value': li.get('taxable_value'),
                'cgst_rate': li.get('cgst_rate'),
                'cgst_amount': li.get('cgst_amount'),
                'sgst_rate': li.get('sgst_rate'),
                'sgst_amount': li.get('sgst_amount'),
                'igst_rate': li.get('igst_rate'),
                'igst_amount': li.get('igst_amount'),
                'amount': li.get('amount'),
            }
            for li in (line_item_rows or [])
        ],
    }
    return validate_extraction(data, tolerance=tolerance)


def notes_from_result(validation):
    """Render the failures list into a single human-readable string for the
    validation_notes TEXT column. Empty string when clean."""
    failures = validation.get('failures') or []
    return '; '.join(failures)
