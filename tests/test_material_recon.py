"""Unit tests for the material-purchase reconciliation math (no DB).

The panel is only as trustworthy as the vendor grouping underneath it: a wrong
merge hides a real conflict, and a wrong split invents one. These pin both.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.material_recon import (
    STATUS_OK, STATUS_OVER, STATUS_SHORT, STATUS_UNBILLED, STATUS_UNPAID,
    reconcile_material,
)


def bill(vendor, amount, number='INV-1'):
    return {'id': 1, 'invoice_number': number, 'invoice_date': '01-Mar-2026',
            'vendor_name': vendor, 'total_amount': amount}


def txn(vendor, amount, bank='kvb'):
    return {'date': '2026-03-05', 'vendor': vendor, 'description': '',
            'dr_amount': amount, 'bank': bank}


def group_for(result, vendor_fragment):
    for g in result['groups']:
        if vendor_fragment.lower() in g['vendor'].lower():
            return g
        if any(vendor_fragment.lower() in a.lower() for a in g['aliases']):
            return g
    raise AssertionError(f"no group for {vendor_fragment!r}: "
                         f"{[g['vendor'] for g in result['groups']]}")


# ── Grouping ──────────────────────────────────────────────────────────

def test_spelling_variants_are_one_supplier():
    """The invoice name and the typed bank name rarely match character for
    character; they must still land on one row."""
    r = reconcile_material([bill('BALU IRON PVT LTD', 100000)],
                           [txn('Balu Iron Co.', 100000)])
    assert len(r['groups']) == 1
    assert r['groups'][0]['status'] == STATUS_OK


def test_common_honorific_alone_does_not_merge_suppliers():
    """SRI is shared by half the suppliers in the book — merging on it would
    fold unrelated ledgers together and hide both conflicts."""
    r = reconcile_material([bill('SRI BALAJI STEELS', 50000)],
                           [txn('SRI KUMAR TRADERS', 90000)])
    assert len(r['groups']) == 2
    assert group_for(r, 'BALAJI')['status'] == STATUS_UNPAID
    assert group_for(r, 'KUMAR')['status'] == STATUS_UNBILLED


def test_bank_vendor_joins_only_its_best_match():
    """One loosely-named bank vendor must not chain two bill vendors into a
    single row."""
    r = reconcile_material(
        [bill('VENKATESH HARDWARE', 40000), bill('MURUGAN TRADERS', 60000)],
        [txn('Venkatesh Hardwares', 40000)],
    )
    assert len(r['groups']) == 2
    assert group_for(r, 'VENKATESH')['status'] == STATUS_OK
    assert group_for(r, 'MURUGAN')['status'] == STATUS_UNPAID


def test_a_shared_trade_word_does_not_fuse_two_suppliers_into_one_row():
    """Project 664, as reported: both suppliers roof, so both names carry
    ROOFING — and the panel showed them as one vendor, netting a ₹14,927 bill
    against an unrelated one and hiding both conflicts."""
    r = reconcile_material(
        [bill('HARI OM ROOFING INDUSTRIES', 14927), bill('P&P ROOFING', 1450)],
        [],
    )
    assert len(r['groups']) == 2
    assert group_for(r, 'HARI OM')['billed'] == 14927
    assert group_for(r, 'P&P')['billed'] == 1450


def test_a_trade_word_does_not_chain_three_suppliers_together():
    """POWER and TOOLS between them linked Power Steels, Selvanayagi and
    Southern Tools into a single ledger."""
    r = reconcile_material(
        [bill('POWER STEELS', 100000), bill('SELVANAYAGI POWER TOOLS', 50000),
         bill('SOUTHERN TOOLS SUPPLIERS', 25000)],
        [txn('POWER STEELS', 100000)],
    )
    assert len(r['groups']) == 3
    assert group_for(r, 'POWER STEELS')['status'] == STATUS_OK
    assert group_for(r, 'SELVANAYAGI')['status'] == STATUS_UNPAID
    assert group_for(r, 'SOUTHERN')['status'] == STATUS_UNPAID


def test_the_supplier_still_wins_over_the_trade_word():
    """Tightening must not cost the merges that make the panel readable: the
    bank's short spelling still joins the invoice's registered name."""
    r = reconcile_material(
        [bill('DEVA STEELS (KOCHI) PRIVATE LIMITED', 721304),
         bill('SRI KARPAGAM STEELS', 131107)],
        [txn('deva steel new', 721304), txn('karpagam steels canar', 131107)],
    )
    assert len(r['groups']) == 2
    assert all(g['status'] == STATUS_OK for g in r['groups'])


def test_two_spellings_of_one_unbilled_vendor_are_one_conflict():
    r = reconcile_material([], [txn('ZARON YES', 200000), txn('Zaron Yes.', 220000)])
    assert len(r['groups']) == 1
    g = r['groups'][0]
    assert g['status'] == STATUS_UNBILLED
    assert g['paid'] == 420000
    assert g['aliases']  # the merge is shown, not assumed


# ── Classification ────────────────────────────────────────────────────

def test_paid_without_a_bill_is_unbilled():
    r = reconcile_material([], [txn('ZARON YES', 420000)])
    g = r['groups'][0]
    assert g['status'] == STATUS_UNBILLED
    assert g['difference'] == 420000
    assert r['summary']['unbilled_total'] == 420000


def test_billed_without_a_payment_is_unpaid():
    r = reconcile_material([bill('KANNAN STEELS', 75000)], [])
    g = r['groups'][0]
    assert g['status'] == STATUS_UNPAID
    assert g['difference'] == -75000
    assert r['summary']['unpaid_total'] == 75000


def test_part_payment_is_short():
    r = reconcile_material([bill('KANNAN STEELS', 100000)],
                           [txn('Kannan Steels', 60000)])
    g = r['groups'][0]
    assert g['status'] == STATUS_SHORT
    assert g['difference'] == -40000


def test_advance_is_over():
    r = reconcile_material([bill('KANNAN STEELS', 100000)],
                           [txn('Kannan Steels', 130000)])
    assert r['groups'][0]['status'] == STATUS_OVER


def test_small_gap_is_within_tolerance():
    """Rounding and a few rupees of charge are not findings."""
    r = reconcile_material([bill('KANNAN STEELS', 100000)],
                           [txn('Kannan Steels', 100050)])
    assert r['groups'][0]['status'] == STATUS_OK
    assert r['summary']['conflict_count'] == 0


def test_tolerance_scales_with_size():
    """0.5% of a 40-lakh bill is ₹20,000 — judging that to the rupee would
    bury the real conflicts under rounding noise."""
    r = reconcile_material([bill('BIG SUPPLIER', 4000000)],
                           [txn('Big Supplier', 4015000)])
    assert r['groups'][0]['status'] == STATUS_OK


# ── Summary + ordering ────────────────────────────────────────────────

def test_conflicts_sort_above_agreeing_rows_biggest_first():
    r = reconcile_material(
        [bill('MATCHED VENDOR', 100000), bill('KANNAN STEELS', 500000)],
        [txn('Matched Vendor', 100000), txn('Kannan Steels', 100000),
         txn('ZARON YES', 900000)],
    )
    order = [g['vendor'].upper() for g in r['groups']]
    assert 'ZARON' in order[0]          # ₹9L unbilled
    assert 'KANNAN' in order[1]         # ₹4L short
    assert 'MATCHED' in order[2]        # agrees — last
    assert r['summary']['conflict_count'] == 2
    assert r['summary']['matched_count'] == 1


def test_summary_totals_are_the_two_sides():
    r = reconcile_material([bill('ALPHA CEMENTS', 100000), bill('BETA TIMBERS', 50000)],
                           [txn('Alpha Cements', 100000), txn('Gamma Paints', 25000)])
    s = r['summary']
    assert s['billed_total'] == 150000
    assert s['paid_total'] == 125000
    assert s['difference'] == -25000
    assert s['bill_count'] == 2
    assert s['txn_count'] == 2
    assert s['counts'][STATUS_UNPAID] == 1     # Beta, billed never paid
    assert s['counts'][STATUS_UNBILLED] == 1   # Gamma, paid never billed


def test_nothing_on_either_side_is_empty_not_an_error():
    r = reconcile_material([], [])
    assert r['groups'] == []
    assert r['summary']['conflict_count'] == 0
    assert r['summary']['billed_total'] == 0


def test_unnamed_vendors_do_not_all_collapse_together():
    """A blank vendor has no tokens to match on; blanks must not fuse into one
    row that reads as a single huge conflict."""
    r = reconcile_material([], [txn('', 1000), txn('', 2000)])
    assert r['summary']['paid_total'] == 3000
