"""Snapping a newly uploaded vendor to the spelling its bank table already uses.

Every narration below is verbatim from the production statements. The stored
spellings are the ones scripts/vendor_unify.py settled on in prod, so these
tests pin the drift that was actually seen: the same account spelled two ways
by one bank, and KVB cutting long names at the export width.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.vendor_spelling import (  # noqa: E402
    NO_SPELLINGS,
    VendorSpellings,
    is_annotated,
    sole_extension,
    tidy_vendor,
)
from vendor_extractor import SELF_CANONICAL, match_vendor  # noqa: E402


def stored(narration, bank, spellings):
    return spellings.snap(match_vendor(narration, bank))


# ── same letters: case / spacing / punctuation ────────────────────────

def test_axis_neft_spelling_snaps_to_the_upi_spelling_on_file():
    """Axis writes 'ARJUNAN  S' on UPI and 'Arjunan s' on NEFT for one payee."""
    spellings = VendorSpellings(['ARJUNAN S'] * 255)
    narration = 'INB/NEFT/AXODH04500451668/Arjunan s/STATE BANK OF INDIA//////'
    assert match_vendor(narration, 'axis').vendor == 'Arjunan s'
    assert stored(narration, 'axis', spellings) == 'ARJUNAN S'


def test_spacing_inside_initials_is_the_same_name():
    spellings = VendorSpellings(['SRIDHAR K M'] * 90)
    narration = 'IMPS/P2A/626821954261/Sridhar KM/X007517/BANKOFBARODA/'
    assert stored(narration, 'axis', spellings) == 'SRIDHAR K M'


def test_the_spelling_on_the_most_rows_wins():
    spellings = VendorSpellings(['Prime electrodss'] * 3 + ['PRIME ELECTRODSS'])
    narration = 'NEFT/CIUBH26216018058/PRIME ELECTRODSS/CITY UNION BANK LIMI//ATTN/'
    assert stored(narration, 'axis', spellings) == 'Prime electrodss'


def test_a_name_never_seen_is_stored_as_the_narration_spells_it():
    spellings = VendorSpellings(['ARJUNAN S', 'Unique products'])
    narration = 'UPI/P2M/600277011382/SHREE ANANDHAAS BAKER/UPI/YES BANK LIMITED YBS'
    assert stored(narration, 'axis', spellings) == 'SHREE ANANDHAAS BAKER'


# ── KVB names cut off at the export width ─────────────────────────────

def test_a_cut_off_kvb_name_takes_the_full_spelling_on_file():
    spellings = VendorSpellings(['SIRUVANI PILING AND DRILLING PVT LT'] * 4)
    narration = 'NEFT CR-HDFC0000001-SIRUVANI PILING AND DRILLING P'
    match = match_vendor(narration, 'kvb')
    assert match.truncated
    assert spellings.snap(match) == 'SIRUVANI PILING AND DRILLING PVT LT'


def test_a_fragment_that_fits_two_vendors_is_left_alone():
    """Which of the two it was cannot be read off the letters."""
    spellings = VendorSpellings(['THANGAMANI ENGINEERING INDUSTRY P',
                                 'THANGAMANI ENGINEERING INDUSTRIAL SUPPLIES'])
    narration = 'NEFT CR-BKID0000200-THANGAMANI ENGINEERING INDUSTR'
    assert match_vendor(narration, 'kvb').truncated
    assert stored(narration, 'kvb', spellings) == 'THANGAMANI ENGINEERING INDUSTR'


def test_a_shorter_name_is_not_lengthened_unless_the_narration_was_cut():
    """'SRIDHAR K M' could be a different person from 'SRIDHAR K M S'; only a
    narration the export truncated may borrow the longer spelling."""
    spellings = VendorSpellings(['SRIDHAR K M S'] * 5)
    narration = 'UPI/P2A/636719048195/SRIDHAR K M          /expens/BANK OF BARODA'
    assert not match_vendor(narration, 'axis').truncated
    assert stored(narration, 'axis', spellings) == 'SRIDHAR K M'


# ── what never counts as a spelling ───────────────────────────────────

def test_notes_and_placeholders_are_not_spellings():
    spellings = VendorSpellings(['SRIDHAR K M/ARJUN', 'Unknown', '', None])
    assert not spellings
    narration = 'IMPS/P2A/626821954261/Sridhar KM/X007517/BANKOFBARODA/'
    assert stored(narration, 'axis', spellings) == 'Sridhar KM'


def test_no_name_in_the_narration_stays_none():
    spellings = VendorSpellings(['ARJUNAN S'])
    assert stored('UPIP2PPAY/DECLINE/654070224194/23.06.2026', 'axis', spellings) is None
    assert stored('MB-WITHIN-DR:XXXX4008-CR:XXXX3188-9315711001260035',
                  'kvb', spellings) is None


# ── the account holder ────────────────────────────────────────────────

def test_own_account_transfers_use_the_canonical_holder_name():
    for narration, bank in (
            ('IMPS-600113230195-VISMAASSOCIATES-UTIB-xxxxxxxxxxx', 'kvb'),
            ('RTGS/KVBLR52026020763823588/VISMA ASSOCIATES/KARUR VYSYA BANK//FAST/', 'axis')):
        assert stored(narration, bank, NO_SPELLINGS) == SELF_CANONICAL


# ── helpers shared with scripts/vendor_unify.py ───────────────────────

def test_tidy_drops_padding_and_trailing_separators():
    assert tidy_vendor('Unique products/') == 'Unique products'
    assert tidy_vendor('Satheeshkumar  .') == 'Satheeshkumar'
    assert tidy_vendor('ARJUNAN  S') == 'ARJUNAN S'


def test_is_annotated():
    assert is_annotated('SRIDHAR K M/ARJUN')
    assert is_annotated('Google India Digital(eb bill)')
    assert not is_annotated('P&P ROOFING')


def test_sole_extension_needs_one_chain():
    assert sole_extension('VBALAJIRANGAN', {'VBALAJIRANGANATHAN'}) == 'VBALAJIRANGANATHAN'
    assert sole_extension('MAHALAKSH', {'MAHALAKSHMIELECTRICA',
                                        'MAHALAKSHMIAGENCIES'}) is None
    assert sole_extension('ARJUNANS', {'ARJUNANS'}) is None
