"""The third-party ledger's effect on the money model (pure math, no DB).

The ledger runs both ways — money we forwarded to a contractor out of the
client's payment, and money someone other than the client paid us against the
job — and the whole point of these tests is the boundary: both legs move what
has been received, and neither one may touch what the job earns or costs.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.project_finance import compute_project_finance


def _fin(**over):
    """A project billed 10,00,000 against a 10,00,000 PO, 4,00,000 spent."""
    kwargs = dict(
        sales={'taxable': 0, 'gst': 0, 'total': 0},
        purchase={'taxable': 0, 'gst': 0, 'total': 0},
        po={'taxable': 1000000, 'gst': 0, 'total': 1000000},
        received_total=600000,
        other_expense_total=400000,
        labour_total=0,
        overhead=0,
    )
    kwargs.update(over)
    return compute_project_finance(**kwargs)


def test_no_ledger_leaves_received_alone():
    f = _fin()
    assert f['net_received'] == 600000
    assert f['third_party_net'] == 0
    assert f['receivable'] == 400000


def test_paid_out_reduces_what_counts_as_received():
    f = _fin(third_party_total=100000)
    assert f['third_party_out_total'] == 100000
    assert f['net_received'] == 500000
    # The client's ₹1,00,000 never paid down our own contract.
    assert f['receivable'] == 500000
    assert f['cash_position'] == 100000


def test_received_from_third_party_adds_to_what_was_received():
    f = _fin(third_party_in_total=150000)
    assert f['third_party_in_total'] == 150000
    assert f['third_party_out_total'] == 0
    assert f['net_received'] == 750000
    assert f['receivable'] == 250000
    assert f['cash_position'] == 350000


def test_both_legs_net_against_each_other():
    f = _fin(third_party_total=100000, third_party_in_total=250000)
    assert f['third_party_net'] == -150000  # net addition
    assert f['net_received'] == 750000
    assert f['receivable'] == 250000


def test_neither_leg_touches_cost_or_profit():
    plain = _fin()
    both = _fin(third_party_total=100000, third_party_in_total=250000)
    assert both['spend_total'] == plain['spend_total']
    assert both['profit'] == plain['profit']
    assert both['billed_profit'] == plain['billed_profit']
    # And nothing from the ledger may appear as a cost line.
    labels = {l['label'] for l in both['cost_lines']}
    assert not any('THIRD' in l.upper() for l in labels)


def test_out_leg_may_exceed_receipts():
    """Paying the contractor before the client pays us is a real state."""
    f = _fin(received_total=50000, third_party_total=200000)
    assert f['net_received'] == -150000
    assert f['receivable'] == 1150000


def test_third_party_total_still_means_the_out_leg():
    """Readers that predate the incoming leg keep their meaning."""
    f = _fin(third_party_total=100000, third_party_in_total=250000)
    assert f['third_party_total'] == 100000
