"""
Vendor extraction tests.

Every narration below is a verbatim string from the production statement
corpus (1,783 Axis + 720 KVB rows), so a passing suite means the parser
handles what the banks actually emit rather than an idealised format.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vendor_extractor import (  # noqa: E402
    SELF_CANONICAL,
    extract_vendor,
    match_vendor,
    normalize_narration,
)


# ============================================================================
# AXIS
# ============================================================================

AXIS_CASES = [
    # UPI person-to-person: name at index 3, right-padded with spaces
    ('UPI/P2A/636719048195/SRIDHAR K M          /expens/BANK OF BARODA',
     'SRIDHAR K M', 'axis.upi.p2a'),
    ('UPI/P2A/600260911839/ARJUNAN  S           /factor/State Bank Of India',
     'ARJUNAN S', 'axis.upi.p2a'),
    # UPI credit: bank code replaces the note field, name still at index 3
    ('UPI/P2A/637163692809/BENZ ASSO/UBIN/UPI/', 'BENZ ASSO', 'axis.upi.p2a'),

    # UPI merchant
    ('UPI/P2M/600277011382/SHREE ANANDHAAS BAKER/UPI/YES BANK LIMITED YBS',
     'SHREE ANANDHAAS BAKER', 'axis.upi.p2m'),
    # A merchant name containing the delimiter must not be truncated early by
    # a greedier rule - but the field itself legitimately ends at the '/'
    ('UPI/P2M/651741824800/Pump 3 / Ace Petropro/UPI/YES BANK LIMITED YBS',
     'Pump 3', 'axis.upi.p2m'),

    # IMPS
    ('IMPS/P2A/606142515660/SURESH KUMAR D/X141821/KARURVYSYABANKLTD/Ci',
     'SURESH KUMAR D', 'axis.imps'),

    # INB/NEFT - the regression this rewrite targets.  The old rule captured
    # the AXODH reference because it matched 'NEFT/' inside 'INB/NEFT/'.
    ('INB/NEFT/AXODH04500471353/Prime electrodss/CITY UNION BANK LIMI//////',
     'Prime electrodss', 'axis.inb.neft'),
    ('INB/NEFT/AXODH04500466770/SUMAN YADAV/UNION BANK OF INDIA//////',
     'SUMAN YADAV', 'axis.inb.neft'),
    ('INB/NEFT/AXODH05278124003/S MAHENDRAN/HDFC BANK//////',
     'S MAHENDRAN', 'axis.inb.neft'),
    ('INB/RTGS/UTIBR62026021957915875/Reserve Bank of/RESERVE BANK OF INDI//////',
     'Reserve Bank of', 'axis.inb.neft'),

    # Branch NEFT
    ('NEFT/DH/AXODH00348491402/MURUGESAN/CITY UNION BANK LIMI//////',
     'MURUGESAN', 'axis.neft.dh'),
    ('NEFT/DH/AXODH00348328118/PRM ENGINEERING WORKS/UNION BANK OF INDIA//////',
     'PRM ENGINEERING WORKS', 'axis.neft.dh'),

    # Payee nickname, no reference field
    ('INB/IFT/Dhanapalvisma/TPARTY TRANSFER', 'Dhanapalvisma', 'axis.inb.ift'),

    # Tax payment
    ('INB/932523231/GST TAX PAYMENT/', 'GST TAX PAYMENT', 'axis.inb.tax'),

    # Free-text manual narration
    ('RTGS PAID TO SURESH', 'SURESH', 'axis.paid_to'),
    ('PAID TO SURESH', 'SURESH', 'axis.paid_to'),

    # Bank charges resolve to the bank, not None
    ('Monthly Avg Bal Chrgs', 'AXIS BANK', 'axis.bank_charges'),
    ('GST @18% on Monthly Service Chrgs', 'AXIS BANK', 'axis.bank_charges'),
    ('Monthly Service Chrgs APR/26', 'AXIS BANK', 'axis.bank_charges'),
    ('Dr Card Charges GST ANNUAL 4632XXXXXXXX2440', 'AXIS BANK', 'axis.bank_charges'),
]


@pytest.mark.parametrize('narration,expected,family', AXIS_CASES)
def test_axis_vendor(narration, expected, family):
    result = match_vendor(narration, 'axis')
    assert result.vendor == expected
    assert result.family == family


AXIS_NO_VENDOR = [
    # Collect-request decline carries no counterparty
    ('UPIP2PPAY/DECLINE/654070224194/23.06.2026', 'axis.upi.decline'),
    # Name slot empty, only a masked account survives
    ('IMPS/P2A/618820835031//X007517/AXB/', 'axis.imps'),
    # Account number in the name slot instead of a name
    ('UPI/P2A/615000259552/922020054193306/300526/KARUR VYSA BANK', 'axis.upi.p2a'),
]


@pytest.mark.parametrize('narration,family', AXIS_NO_VENDOR)
def test_axis_yields_no_vendor(narration, family):
    result = match_vendor(narration, 'axis')
    assert result.vendor is None
    assert result.family == family


def test_axis_reference_is_never_returned_as_vendor():
    """No Axis family may surface a transaction reference or IFSC as a name."""
    for narration, expected, _ in AXIS_CASES:
        vendor = extract_vendor(narration, 'axis')
        assert not (vendor or '').startswith('AXODH')
        assert not (vendor or '').startswith('UTIBR')


def test_axis_inward_transfer_flags_self():
    result = match_vendor(
        'RTGS/KVBLR52026020763823588/VISMA ASSOCIATES/KARUR VYSYA BANK//FAST/', 'axis')
    assert result.family == 'axis.inward'
    assert result.is_self is True
    # self_ok families keep the literal name rather than rewriting it
    assert result.vendor == 'VISMA ASSOCIATES'


def test_axis_return_is_flagged_as_reversal():
    result = match_vendor(
        'NEFT/RETURN/AXODH20022860288/AC01/Satheeshkumar ps/DCMIB970934414', 'axis')
    assert result.vendor == 'Satheeshkumar ps'
    assert result.is_reversal is True


# ============================================================================
# KVB
# ============================================================================

KVB_CASES = [
    ('IMPS-600221478795-PRABHU FAB-CNRB-xxxxxxxxx6686-BL',
     'PRABHU FAB', 'kvb.imps'),
    ('IMPS-600118282709-RAJEEB KUMAR SAHANI-SBIN-xxxxxxx',
     'RAJEEB KUMAR SAHANI', 'kvb.imps'),
    # Name runs to the end of a truncated narration, with no trailing delimiter
    ('IMPS-611609834027-VETHAM KUZHUMAM SPRIRITUAL TRUST',
     'VETHAM KUZHUMAM SPRIRITUAL TRUST', 'kvb.imps'),

    # NEFT/RTGS, both directions.  On the CR rows field 2 is the payer and the
    # account holder sits at field 3 - taking the wrong one yields 'VISMA'.
    ('NEFT DR-KVBLH00252470290-V BALAJI RANGANATHAN-UTIB',
     'V BALAJI RANGANATHAN', 'kvb.neft.dr'),
    ('NEFT DR-KVBLH00256636895-Ceyone Fastners pvt ltd-HDFC0000031-MUMBAI-FORT',
     'Ceyone Fastners pvt ltd', 'kvb.neft.dr'),
    ('NEFT CR-SBIN0004266-INFINIUM SHELTERS LLP-Visma As',
     'INFINIUM SHELTERS LLP', 'kvb.neft.cr'),
    ('RTGS DR-SIBL0000111-SURESH FAB-MUMBAI-FORT-KVBLR52',
     'SURESH FAB', 'kvb.rtgs.dr'),
    ('RTGS DR-CNRB0001204-karpagam steels canar-MUMBAI-F',
     'karpagam steels canar', 'kvb.rtgs.dr'),
    # Punctuation-heavy company names must survive the filters
    ('RTGS CR-ICIC0000011-R.R.C.O.R.P. CONSTRUCTIONS PRI',
     'R.R.C.O.R.P. CONSTRUCTIONS PRI', 'kvb.rtgs.cr'),
    ('RTGS CR-CIUB0000732-JAMUNA PALGOVA Gokulan K S-VIS',
     'JAMUNA PALGOVA Gokulan K S', 'kvb.rtgs.cr'),

    # Standing instructions - three sub-forms, one tail
    ('To Clg:ECS BD-TATA MF - NACH', 'TATA MF', 'kvb.ecs_nach'),
    ('To Clg:ECS TP ACH NIPPON IND MF - NACH', 'NIPPON IND MF', 'kvb.ecs_nach'),
    ('To Clg:ECS UGRO CAPITAL - NACH', 'UGRO CAPITAL', 'kvb.ecs_nach'),
    ('To Clg:ECS CHOLAMANDALAM INVEST - NACH', 'CHOLAMANDALAM INVEST', 'kvb.ecs_nach'),

    # Clearing, cash, cheque, UPI, FT
    ('BY CLG:HEMA:HDFC Bank - 02-MAY-26', 'HEMA', 'kvb.clearing.inward'),
    ('CASH DEP-SELF-SEETHALAKSHMI-CBE-RAMANATH', 'SEETHALAKSHMI', 'kvb.cash.counter'),
    ('CASH DEPOSIT AT CDM-S1ECD162001', 'Cash Deposit', 'kvb.cash.cdm'),
    ('CHQ PAID-TP-S SEETHALAKSHMI - CBE-RAMANATH', 'S SEETHALAKSHMI', 'kvb.cheque.paid'),
    ('UPI-CR-602303850734-RAGURAM  KARTHIKASIVAGANESH-UT',
     'RAGURAM KARTHIKASIVAGANESH', 'kvb.upi'),
    ('FT - CR - 1181155000201420 - ANUSUYA A - KVB', 'ANUSUYA A', 'kvb.ft'),
    ('FT - DR - 1674115000003188 - MANICKAM ASSOCIATES', 'MANICKAM ASSOCIATES', 'kvb.ft'),

    # Bank charges
    ('SMS Charges for MAR2026', 'KVB', 'kvb.bank_charges'),
    ('SAFE  1620 1620009B012 I-00684733 CSTP', 'KVB', 'kvb.bank_charges'),
]


@pytest.mark.parametrize('narration,expected,family', KVB_CASES)
def test_kvb_vendor(narration, expected, family):
    result = match_vendor(narration, 'kvb')
    assert result.vendor == expected
    assert result.family == family


KVB_NO_VENDOR = [
    # Only masked account numbers - needs the account map, not a regex
    ('MB-WITHIN-DR:XXXX4008-CR:XXXX3188-9315711001260035', 'kvb.mb_within'),
    ('MB-WITHIN-DR:XXXX4008-CR:XXXX1039-931571030326532135-MATERIAL PURCHASE',
     'kvb.mb_within'),
    # Field 2 is the literal channel name 'IMPSP2A', not a counterparty
    ('REV IMPS-616213037411-IMPSP2A-HDFC-xxxxxxx5259-pur', 'kvb.imps.reversal'),
    ('O/W CHQ RTN::gefu chq return:-02-MAY-26-Alteration', 'kvb.cheque_return'),
    ('NEW A/C BALAJI RANGANATHAN OPENING BAL CBE-RAMANATH', 'kvb.opening_balance'),
]


@pytest.mark.parametrize('narration,family', KVB_NO_VENDOR)
def test_kvb_yields_no_vendor(narration, family):
    result = match_vendor(narration, 'kvb')
    assert result.vendor is None
    assert result.family == family


def test_kvb_self_transfer_is_flagged():
    result = match_vendor('IMPS-600113230195-VISMAASSOCIATES-UTIB-xxxxxxxxxxx', 'kvb')
    assert result.is_self is True
    assert result.vendor == SELF_CANONICAL


def test_kvb_truncated_name_is_flagged():
    """50-char narrations lose the tail of the name; callers must know."""
    result = match_vendor('NEFT CR-UBIN0903418-FACILITIES AND BUILDING SOLUTI', 'kvb')
    assert result.vendor == 'FACILITIES AND BUILDING SOLUTI'
    assert result.truncated is True

    # A name followed by more fields was not cut off
    full = match_vendor('IMPS-600221478795-PRABHU FAB-CNRB-xxxxxxxxx6686-BL', 'kvb')
    assert full.truncated is False


# ============================================================================
# NORMALISATION
# ============================================================================

def test_split_markers_are_stripped_before_parsing():
    """Our own [SPLIT n/m] annotation must not shift the field indices."""
    assert normalize_narration('RTGS DR-HDFC0000031-RAMESH IRON [SPLIT 1/2]') == \
        'RTGS DR-HDFC0000031-RAMESH IRON'

    plain = 'INB/NEFT/AXODH05278124003/S MAHENDRAN/HDFC BANK//////'
    for suffix in (' [SPLIT 1/3]', ' [SPLIT 2/2] [SPLIT 1/2]'):
        assert extract_vendor(plain + suffix, 'axis') == 'S MAHENDRAN'

    assert extract_vendor(
        'UPI/P2A/601039676678/KALISAMY S           /truck/BANK OF BARODA [SPLIT 1/2]',
        'axis') == 'KALISAMY S'


def test_blank_and_garbage_input():
    for value in ('', '   ', None, 123):
        assert extract_vendor(value, 'axis') is None
        assert extract_vendor(value, 'kvb') is None


def test_unmatched_narration_reports_unresolved():
    result = match_vendor('SOME BRAND NEW FORMAT 12345', 'kvb')
    assert result.vendor is None
    assert result.family == 'unresolved'
