"""Vendor identity matching — the layer that decides "is this the same supplier?".

Every name in the corpus below is a real spelling taken from production
(``bill_invoices.vendor_name`` and ``kvb_transactions.client_vendor``), so
these tests are not hypotheticals: each pair either did merge when it must not,
or must keep merging as the rules tighten.

The asymmetry that shapes these tests: a **false merge is silent** — two
suppliers become one row and a genuine billed-vs-paid conflict disappears — so
MUST_NOT_MATCH is the half that protects real money. A false split only shows
the auditor two rows instead of one, which they can see and act on.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from helpers.bill_reconcile import (
    vendor_anchor,
    vendor_key,
    vendor_keys_match,
    vendor_name_tokens,
)


def matches(a, b):
    return vendor_keys_match(vendor_key(a), vendor_key(b))


# ── Normalisation ─────────────────────────────────────────────────────

@pytest.mark.parametrize('name, expected', [
    # Initials are identity and must survive: the old rule deleted every token
    # of length 1, which is how "P&P ROOFING" became the bare word ROOFING.
    ('P&P ROOFING', ['PP', 'ROOFING']),
    ('C S K TUBE CORPORATION', ['CSK', 'TUBE']),
    ('CS K TUBE CORPORATION', ['CSK', 'TUBE']),
    ('Q SPACE HOME SOLUTIONS', ['Q', 'SPACE', 'HOME', 'SOLUTIONS']),
    # Courtesy prefix and company forms carry no identity.
    ('M/s. TOPLINE ELECTRICALS', ['TOPLINE', 'ELECTRICALS']),
    ('SHANMUGAM & CO', ['SHANMUGAM']),
    # A financial-year suffix is bookkeeping, not a different supplier.
    ('POWER STEELS - 2026-2027', ['POWER', 'STEELS']),
])
def test_normalisation_keeps_what_identifies_and_drops_what_does_not(name, expected):
    assert vendor_name_tokens(name) == expected


# ── The anchor ────────────────────────────────────────────────────────

@pytest.mark.parametrize('name, anchor', [
    ('HARI OM ROOFING INDUSTRIES', 'HARI'),      # not ROOFING
    ('P&P ROOFING', 'PP'),                       # not ROOFING
    ('BALU IRON AND STEEL COMPANY', 'BALU'),     # not IRON
    ('SELVANAYAGI POWER TOOLS', 'SELVANAYAGI'),  # not POWER, not TOOLS
    ('SRI KARPAGAM STEELS', 'KARPAGAM'),         # honorific skipped
    ('Shri Selvanayagi Associates', 'SELVANAYAGI'),
    ('M/s, MANKU STORES', 'MANKU'),
    ('Q SPACE HOME SOLUTIONS', 'SPACE'),         # bare initial is not the identity
    ('C S K TUBE CORPORATION', 'CSK'),           # ...but an initialism alone is
    ('deva steel new', 'DEVA'),
])
def test_anchor_is_who_the_supplier_is_not_what_it_sells(name, anchor):
    assert vendor_anchor(name) == anchor


def test_a_name_made_only_of_trade_words_still_yields_an_anchor():
    """"PAINT" identifies nobody, but it must not crash or match everything."""
    assert vendor_anchor('PAINT') == 'PAINT'
    assert not matches('PAINT', 'ASIAN PAINTS')


# ── Must NOT merge: different suppliers in the same trade ─────────────

@pytest.mark.parametrize('a, b, shared_word', [
    # The reported bug: both roof, neither is the other. Project 664.
    ('HARI OM ROOFING INDUSTRIES', 'P&P ROOFING', 'ROOFING'),
    # Two iron merchants, five shared words between them. Project 648.
    ('BALU IRON AND STEEL COMPANY',
     'RAMESH IRON AND STEEL COMPANY INDIA PVT LTD', 'IRON'),
    # These three chained into ONE row under the old rule: Power Steels shares
    # POWER with Selvanayagi, which shares TOOLS with Southern Tools. Breaking
    # either link is enough to keep all three apart — hence both are pinned.
    # (The chain itself is exercised end-to-end in test_material_recon.)
    ('POWER STEELS', 'SELVANAYAGI POWER TOOLS', 'POWER'),
    ('SELVANAYAGI POWER TOOLS', 'SOUTHERN TOOLS SUPPLIERS', 'TOOLS'),
    ('M/s. TOPLINE ELECTRICALS', 'SRI POOJA HARDWARES AND ELECTRICALS',
     'ELECTRICALS'),
    ('MADHURA EQUIPMENTS', 'PIONEER WELDING EQUIPMENTS', 'EQUIPMENTS'),
    ('METAL TEST POINT (Unit of HEMA METAL WORKS)', 'MARVEL METAL CRAFTS',
     'METAL'),
    ('DEVA STEELS (KOCHI) PRIVATE LIMITED', 'SRI KARPAGAM STEELS', 'STEELS'),
])
def test_a_shared_trade_word_never_merges_two_suppliers(a, b, shared_word):
    assert shared_word in vendor_name_tokens(a)
    assert shared_word in vendor_name_tokens(b)
    assert not matches(a, b), f"{a!r} and {b!r} merged on {shared_word!r}"


def test_a_shared_honorific_never_merges_two_suppliers():
    assert not matches('SRI BALAJI STEELS', 'SRI KUMAR TRADERS')


# ── Must merge: one supplier, spelled by different hands ──────────────

@pytest.mark.parametrize('a, b', [
    # Bank vendors are typed short; invoices carry the registered name.
    ('ALPHA THREAD ROLLING', 'Alpha Thread'),
    ('ALPHA THREAD ROLLING', 'ALPHA'),
    ('HARI OM ROOFING INDUSTRIES', 'HARI OM'),
    ('FINE WORTH ENGINEERS', 'FINE WORTH'),
    ('TECH TREE SOLUTIONS', 'TECH TREE'),
    ('SOUTHERN TOOLS SUPPLIERS', 'SOUTHERN TOOLS'),
    ('BALU IRON AND STEEL COMPANY', 'BALU IRON'),
    ('RAMESH IRON AND STEEL COMPANY INDIA PVT LTD', 'RAMESH IRON'),
    ('ZARON INDUSTRIES', 'ZARON'),
    ('Q SPACE HOME SOLUTIONS', 'Q  SPACE'),
    ('Q SPACE HOME SOLUTIONS', 'SPACE HOME SOLUTIONS'),
    # Legal form and case differ, identity does not.
    ('CEYONE FASTENERS PRIVATE LIMITED', 'Ceyone Fastners pvt ltd'),
    ('BALU IRON PVT LTD', 'Balu Iron Co.'),
    ('SHANMUGAM & CO', 'shanmugam co'),
    # Initialism written three ways.
    ('C S K TUBE CORPORATION', 'CSK TUBE CORPORATION'),
    ('CS K TUBE CORPORATION', 'CSK TUBE CORPOR'),
    # Typos and transliteration drift in the identity word itself.
    ('SOUTHERN TOOLS SUPPLIERS', 'SOUTHRN TOOLS'),
    ('MANICKAM ASSOCIATES', 'MANICKAM ASSOCITES'),
    ('INDLAZ', 'INDLAS'),
    ('Mahalakshmi Electricals and Hardwares', 'Mahalaxmi Electricals and Hardwares'),
    ('PRIME ELECTORDSS', 'Prime Electrodss'),
    ('ZARON INDUSTRIES', 'ZARON INDUSTRIESS'),
    # An honorific on one side only.
    ('SRI KARPAGAM STEELS', 'karpagam steels canar'),
    ('SELVANAYAGI POWER TOOLS', 'Shri Selvanayagi Associates'),
    # Financial-year suffix on the invoice side.
    ('POWER STEELS - 2026-2027', 'POWER STEELS'),
    ('POWER STEELS-2026-2027', 'POWER STEELS - 2025-2026'),
    # A trailing word the bank clerk added.
    ('DEVA STEELS (KOCHI) PRIVATE LIMITED', 'deva steel new'),
    ('ZARON INDUSTRIES', 'ZARON YES'),
])
def test_one_supplier_spelled_two_ways_still_matches(a, b):
    assert matches(a, b), f"{a!r} and {b!r} split apart"


# ── Edge cases ────────────────────────────────────────────────────────

def test_a_blank_vendor_matches_nothing():
    assert not matches('', 'POWER STEELS')
    assert not matches('', '')


def test_matching_is_symmetric():
    """Grouping walks the candidate list in arbitrary order, so an asymmetric
    rule would make the result depend on row order."""
    corpus = ['HARI OM ROOFING INDUSTRIES', 'P&P ROOFING', 'POWER STEELS',
              'SELVANAYAGI POWER TOOLS', 'ALPHA', 'ALPHA THREAD ROLLING',
              'C S K TUBE CORPORATION', 'CSK TUBE CORPOR', 'SRI KARPAGAM STEELS']
    for a in corpus:
        for b in corpus:
            assert matches(a, b) == matches(b, a), f"{a!r} vs {b!r}"


def test_known_aliases_the_heuristic_cannot_infer():
    """Documented residue, pending the vendor-alias table.

    Neither can be derived from the names alone: "PANDP" spells out an
    ampersand the invoice writes as "&", and "SURESH FAB/..." leads with a
    person, not the firm. They are recorded here so the gap is a known,
    listed one rather than a surprise — and so that adding the alias table
    has an obvious place to prove itself.
    """
    assert not matches('P&P ROOFING', 'PANDP')
    assert not matches('MANICKAM ASSOCIATES', 'SURESH FAB/MANICKAM ASSOCIATES')
