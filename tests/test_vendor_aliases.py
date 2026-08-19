"""Human vendor-identity rulings, overriding the name matcher.

The matcher gets ~97% of real spellings right on its own; these tests cover the
rest — the cases a person has to settle, and which must then stay settled. Both
directions matter: a link rescues a merge the names can't justify, a split
undoes one they wrongly justify.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.bill_reconcile import (
    NO_ALIASES,
    VendorAliasResolver,
    vendor_key,
    vendor_keys_match,
)
from helpers.material_recon import STATUS_OK, STATUS_UNPAID, reconcile_material
from test_material_recon import bill, group_for, txn


def matches(a, b, resolver=NO_ALIASES):
    return vendor_keys_match(vendor_key(a, resolver),
                             vendor_key(b, resolver), resolver)


# ── Links: "these are the same supplier" ──────────────────────────────

def test_a_link_merges_what_the_names_cannot_justify():
    """PANDP is the bank clerk's P&P ROOFING. Nothing in the two strings says
    so — this is exactly the case a person has to settle once."""
    assert not matches('PANDP', 'P&P ROOFING')
    resolver = VendorAliasResolver(links={'PANDP': 'P&P ROOFING'})
    assert matches('PANDP', 'P&P ROOFING', resolver)


def test_a_link_does_not_drag_in_a_third_supplier():
    """Folding PANDP into P&P must not also fold it into Hari Om, who shares
    ROOFING with P&P and is a different supplier."""
    resolver = VendorAliasResolver(links={'PANDP': 'P&P ROOFING'})
    assert not matches('PANDP', 'HARI OM ROOFING INDUSTRIES', resolver)


def test_the_link_key_ignores_case_and_spacing():
    resolver = VendorAliasResolver(links={'SURESH FAB/MANICKAM ASSOCIATES':
                                          'MANICKAM ASSOCIATES'})
    assert matches('  suresh   fab/manickam associates  ',
                   'MANICKAM ASSOCIATES', resolver)


def test_a_linked_alias_inherits_the_canonical_identity():
    """The rewrite happens before tokenising, so an alias anchors on the
    supplier it was linked to, not on its own spelling."""
    resolver = VendorAliasResolver(links={'PANDP': 'P&P ROOFING'})
    assert vendor_key('PANDP', resolver).anchor == 'PP'


# ── Splits: "these are NOT the same supplier" ─────────────────────────

def test_a_split_overrides_a_match_the_names_would_make():
    assert matches('ALPHA THREAD ROLLING', 'ALPHA')
    resolver = VendorAliasResolver(
        splits=[('ALPHA THREAD ROLLING', 'ALPHA')])
    assert not matches('ALPHA THREAD ROLLING', 'ALPHA', resolver)


def test_a_split_is_symmetric():
    """The pair is unordered — which name the auditor clicked must not decide
    whether the ruling applies."""
    resolver = VendorAliasResolver(splits=[('ALPHA', 'ALPHA THREAD ROLLING')])
    assert not matches('ALPHA THREAD ROLLING', 'ALPHA', resolver)
    assert not matches('ALPHA', 'ALPHA THREAD ROLLING', resolver)


def test_a_split_leaves_other_suppliers_alone():
    resolver = VendorAliasResolver(splits=[('ALPHA', 'ALPHA THREAD ROLLING')])
    assert matches('SOUTHERN TOOLS SUPPLIERS', 'SOUTHERN TOOLS', resolver)


# ── Through the panel ─────────────────────────────────────────────────

def test_a_link_makes_the_panel_reconcile_two_rows_as_one():
    r = reconcile_material([bill('P&P ROOFING', 3907)], [txn('PANDP', 3907)])
    assert len(r['groups']) == 2          # names alone can't see it

    resolver = VendorAliasResolver(links={'PANDP': 'P&P ROOFING'})
    r = reconcile_material([bill('P&P ROOFING', 3907)], [txn('PANDP', 3907)],
                           resolver=resolver)
    assert len(r['groups']) == 1
    assert r['groups'][0]['status'] == STATUS_OK


def test_a_split_separates_a_row_the_panel_had_merged():
    r = reconcile_material([bill('ZARON INDUSTRIES', 95045)],
                           [txn('ZARON YES', 95045)])
    assert len(r['groups']) == 1

    resolver = VendorAliasResolver(
        splits=[('ZARON INDUSTRIES', 'ZARON YES')])
    r = reconcile_material([bill('ZARON INDUSTRIES', 95045)],
                           [txn('ZARON YES', 95045)], resolver=resolver)
    assert len(r['groups']) == 2
    assert group_for(r, 'ZARON INDUSTRIES')['status'] == STATUS_UNPAID


def test_merging_a_row_needs_every_spelling_in_it():
    """Linking only a row's label would strand its other spellings: they were
    grouped by the matcher, and once the label resolves elsewhere they no
    longer match it. The API sends them all — this pins why."""
    bills = [bill('SOUTHERN TOOLS SUPPLIERS', 25000)]
    banks = [txn('SOUTHERN TOOLS', 15000), txn('SOUTHRN TOOLS', 10000)]

    label_only = VendorAliasResolver(
        links={'SOUTHERN TOOLS SUPPLIERS': 'MADHURA TRADERS'})
    r = reconcile_material(bills, banks, resolver=label_only)
    assert len(r['groups']) == 2          # the two bank spellings broke away

    all_names = VendorAliasResolver(links={
        'SOUTHERN TOOLS SUPPLIERS': 'MADHURA TRADERS',
        'SOUTHERN TOOLS': 'MADHURA TRADERS',
        'SOUTHRN TOOLS': 'MADHURA TRADERS',
    })
    r = reconcile_material(bills, banks, resolver=all_names)
    assert len(r['groups']) == 1
    assert r['groups'][0]['status'] == STATUS_OK


# ── Defaults ──────────────────────────────────────────────────────────

def test_no_rulings_means_the_matcher_alone():
    """Every caller may omit a resolver, and nothing about matching changes —
    that is what keeps this module pure and its other tests DB-free."""
    assert not NO_ALIASES
    assert NO_ALIASES.canonical('POWER STEELS') == 'POWER STEELS'
    assert not NO_ALIASES.are_split(('A',), ('B',))
    assert matches('SOUTHERN TOOLS SUPPLIERS', 'SOUTHERN TOOLS')


def test_a_self_referential_ruling_is_ignored():
    """The API rejects these, but a hand-edited row must not wedge the panel."""
    resolver = VendorAliasResolver(links={'ALPHA': 'ALPHA'},
                                   splits=[('ALPHA', 'ALPHA')])
    assert matches('ALPHA THREAD ROLLING', 'ALPHA', resolver)
