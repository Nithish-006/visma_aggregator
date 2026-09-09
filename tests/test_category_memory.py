"""Learning a transaction's category from what the vendor and the remark meant.

Every narration below is a real one from production, and each case here is a
behaviour that measurement on the live tables showed to matter: the rail token
that masqueraded as a supplier, the branch name that masqueraded as a remark,
the three-rows-and-pure vendor that was not actually settled.

The asymmetry that shapes these tests: a **confident wrong answer is worse than
no answer**, because it gets auto-applied and the person never looks. So the
cases that pin the low end — declining to guess — carry as much weight as the
ones that pin a correct suggestion.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from helpers.category_memory import (
    CategoryMemory,
    canonical_category,
    extract_purpose,
    is_learnable_vendor,
)


def row(vendor, category, purpose=None, when=date(2026, 1, 1), code=None):
    return {'vendor': vendor, 'category': category, 'purpose': purpose,
            'date': when, 'code': code, 'is_credit': False}


def memory(rows, **kw):
    kw.setdefault('reference_date', date(2026, 1, 1))
    return CategoryMemory(rows, **kw)


# ============================================================================
# THE PURPOSE SLOT
# ============================================================================

@pytest.mark.parametrize('narration, family, expected', [
    # Axis truncates the UPI remark to six characters — that is the vocabulary.
    ('UPI/P2A/605464043606/DHANAPAL             /site a/AXIS BANK',
     'axis.upi.p2a', 'SITE A'),
    ('UPI/P2A/616722827402/Mr MURUGESAN  K      /grindi/CITY UNION BANK LTD',
     'axis.upi.p2a', 'GRINDI'),
    # KVB writes the remark last, after the masked account.
    ('IMPS-621418484856-RAJU-SBIN-xxxxxxx4901-labour adv',
     'kvb.imps', 'LABOUR ADV'),
    ('IMPS-622123172054-IMPSP2A-KKBK-xxxxxx8020-salary',
     'kvb.imps', 'SALARY'),
    ('MB-WITHIN-DR:XXXX4008-CR:XXXX1039-931571030326532135-MATERIAL PURCHASE',
     'kvb.mb_within', 'MATERIAL PURCHASE'),
])
def test_reads_the_remark_the_payer_typed(narration, family, expected):
    assert extract_purpose(narration, family) == expected


@pytest.mark.parametrize('narration, family', [
    # "UPI" is the placeholder Axis writes when the P2M payment carried no
    # remark. Learning from it blends every merchant payment into one bucket.
    ('UPI/P2M/611491744441/ANNAISAKTHISTORES    /UPI/CANARA BANK',
     'axis.upi.p2m'),
    # NEFT and RTGS end in a BRANCH, not a purpose. Reading the last segment
    # here taught FORT to mean MATERIAL PURCHASE.
    ('NEFT DR-KVBLH00257322176-CSK TUBE CORPORATION-ICIC0006053-MUMBAI-FORT',
     'kvb.neft.dr'),
    ('RTGS DR-UTIB0001748-POWER STEELS-CBE-RAMANATH-KVBL',
     'kvb.rtgs.dr'),
    # Truncated narration: the slot holds the masked account, not a remark.
    ('IMPS-604514467215-VISMAASSOCIATES-UTIB-xxxxxxxxxxx', 'kvb.imps'),
    # A family with no remark slot at all.
    ('Monthly Avg Bal Chrgs', 'axis.bank_charges'),
])
def test_declines_when_the_slot_holds_no_remark(narration, family):
    assert extract_purpose(narration, family) is None


# ============================================================================
# WHAT IS NOT A VENDOR
# ============================================================================

@pytest.mark.parametrize('name', [
    # KVB puts the rail itself in the name slot when no name was sent. This one
    # had absorbed a dozen unrelated payees before it was excluded.
    'IMPSP2A',
    'NEFT',
    # The account holder is not their own supplier.
    'VISMAASSOCIATES',
    'VISMA ASSOCIATES',
    'VISMAASS',
    # A bank is the counterparty on a self-transfer.
    'AXIS BANK',
    'Unknown',
    'Internal Transfer',
    '',
])
def test_rejects_things_that_are_not_suppliers(name):
    assert not is_learnable_vendor(name)


def test_accepts_a_real_supplier():
    assert is_learnable_vendor('POWER STEELS')
    assert is_learnable_vendor('Mr Karthik Chinnadurai')


# ============================================================================
# WHAT THE MEMORY WILL AND WILL NOT CLAIM
# ============================================================================

def test_learns_a_category_no_keyword_list_could_produce():
    """CRANE RENT appears in no CATEGORY_PATTERNS list — only history has it."""
    mem = memory([row('CHINNAKALAI', 'CRANE RENT')] * 6)
    assert mem.suggest('CHINNAKALAI').category == 'CRANE RENT'


def test_folds_the_spellings_of_one_payee():
    """The bank spells the same payee differently between statements."""
    mem = memory([row('ARJUNAN  S', 'SITE EXPENSES')] * 5)
    assert mem.suggest('ARJUNAN S').category == 'SITE EXPENSES'


def test_says_nothing_about_a_vendor_it_has_never_seen():
    mem = memory([row('POWER STEELS', 'MATERIAL PURCHASE')] * 5)
    assert mem.suggest('SOME NEW SUPPLIER') is None


def test_three_agreeing_rows_do_not_reach_certainty():
    """A payee settled three times is evidence, not proof.

    Every confident miss in the first measurement was a many-sided payee whose
    opening rows happened to agree, so this must stay below the auto bar.
    """
    mem = memory([row('SURENTHAR', 'SITE EXPENSES')] * 3)
    assert mem.suggest('SURENTHAR').confidence < 0.80


def test_a_long_settled_payee_does_reach_the_auto_bar():
    mem = memory([row('POWER STEELS', 'MATERIAL PURCHASE')] * 20)
    assert mem.suggest('POWER STEELS').confidence >= 0.80


def test_a_divided_payee_declines_to_guess():
    """Paid for site work as often as factory work — no answer is the answer."""
    mem = memory([row('THAMBURAJAN R', 'SITE EXPENSES')] * 8
                 + [row('THAMBURAJAN R', 'FACTORY EXPENSES')] * 7)
    assert mem.suggest('THAMBURAJAN R').confidence < 0.60


def test_credits_are_never_learned_from():
    """AMOUNT RECEIVED comes from the DR/CR flag, not from who paid."""
    credit = row('A CLIENT', 'AMOUNT RECEIVED')
    credit['is_credit'] = True
    assert memory([credit] * 10).suggest('A CLIENT') is None


def test_recent_rulings_outweigh_old_ones():
    """A payee whose treatment changed converges on the new answer."""
    mem = CategoryMemory(
        [row('KALISAMY S', 'TRANSPORT EXPENSES', when=date(2023, 1, 1))] * 10
        + [row('KALISAMY S', 'TRUCK RENT', when=date(2026, 1, 1))] * 6,
        reference_date=date(2026, 1, 1))
    assert mem.suggest('KALISAMY S').category == 'TRUCK RENT'


# ============================================================================
# THE TWO SIGNALS TOGETHER
# ============================================================================

def test_the_remark_answers_when_the_narration_names_nobody():
    """The KVB IMPS rows that carry a rail token instead of a payee."""
    mem = memory([row('RAJU', 'LABOUR PAYMENT', purpose='LABOUR ADV')] * 8)
    suggestion = mem.suggest('IMPSP2A', 'LABOUR ADV')
    assert suggestion.category == 'LABOUR PAYMENT'
    assert suggestion.signal == 'purpose'


def test_agreement_raises_confidence_without_manufacturing_it():
    """Pooled, not noisy-or: the two signals are correlated, not independent.

    Treating agreement as two independent witnesses inflated ≥0.80 precision
    on Axis from 90.5% down to 84.5% while reporting higher confidence.
    """
    rows = [row('POWER STEELS', 'MATERIAL PURCHASE', purpose='PUR')] * 10
    mem = memory(rows)
    alone = mem.suggest('POWER STEELS')
    together = mem.suggest('POWER STEELS', 'PUR')
    assert together.signal == 'both'
    assert alone.confidence <= together.confidence < 1.0


def test_a_conflict_falls_out_of_the_auto_band():
    """Usually paid for site work, but this remark says crane — go and look."""
    mem = memory([row('SURENTHAR', 'SITE EXPENSES')] * 12
                 + [row('CHINNAKALAI', 'CRANE RENT', purpose='CRANE')] * 4)
    suggestion = mem.suggest('SURENTHAR', 'CRANE')
    assert suggestion.signal == 'conflict'
    assert suggestion.confidence < 0.80


# ============================================================================
# CATEGORIES THE STATEMENT CANNOT SEPARATE
# ============================================================================
#
# The client's answer to "when is a labour payment SITE and when is it
# FACTORY?" was: it depends which job it was for. That fact is in no part of
# the statement -- the same man, paid for LABOUR, four days apart, ₹300 each
# time, is SITE one week and FACTORY the next. So the evidence can say which
# way this payee usually goes, and still not say which way THIS payment goes.

def test_a_divided_payee_on_a_contested_pair_is_held_back():
    """Two-thirds SITE would otherwise sail past the auto bar on support."""
    mem = memory([row('ARJUNAN S', 'SITE EXPENSES')] * 103
                 + [row('ARJUNAN S', 'FACTORY EXPENSES')] * 54)
    suggestion = mem.suggest('ARJUNAN S')
    assert suggestion.contested
    assert suggestion.runner_up == 'FACTORY EXPENSES'


def test_a_settled_payee_on_a_contested_pair_is_not_held_back():
    """58 SITE to 4 FACTORY is a decision the user has made in practice."""
    mem = memory([row('DHANAPAL', 'SITE EXPENSES')] * 58
                 + [row('DHANAPAL', 'FACTORY EXPENSES')] * 4)
    suggestion = mem.suggest('DHANAPAL')
    assert not suggestion.contested
    assert suggestion.confidence >= 0.80


def test_a_divided_payee_on_an_UNcontested_pair_is_not_held_back():
    """The rule must not quietly become "never answer when unsure".

    MATERIAL PURCHASE and OFFICE EXPENSES are separable from the statement, so
    a divided payee there is ordinary uncertainty, handled by the score alone.
    """
    mem = memory([row('SOME SHOP', 'MATERIAL PURCHASE')] * 70
                 + [row('SOME SHOP', 'OFFICE EXPENSES')] * 30)
    assert not mem.suggest('SOME SHOP').contested


def test_contested_rows_still_teach_the_memory():
    """Holding a row back is about answering, not about learning."""
    mem = memory([row('ARJUNAN S', 'SITE EXPENSES')] * 103
                 + [row('ARJUNAN S', 'FACTORY EXPENSES')] * 54)
    assert mem.rows_learned == 157


# ============================================================================
# CATEGORY SPELLING
# ============================================================================

@pytest.mark.parametrize('typed, expected', [
    ('TRAILLER RENT', 'TRAILER RENT'),
    ('TRUCT RENT AC', 'TRUCK RENT'),
    ('  cess  ', 'CESS AC'),
    ('MATERIAL PURCHASE', 'MATERIAL PURCHASE'),
])
def test_folds_the_typos_in_typed_category_names(typed, expected):
    assert canonical_category(typed) == expected


# ============================================================================
# THE DECISION THE UPLOAD ACTUALLY MAKES
# ============================================================================

from bank_statement_processor import decide_category  # noqa: E402
from vendor_extractor import match_vendor  # noqa: E402


def decide(narration, bank, mem, drcr='DR'):
    return decide_category(narration, drcr, match_vendor(narration, bank), bank, mem)


def test_a_settled_supplier_is_applied():
    mem = memory([row('POWER STEELS', 'MATERIAL PURCHASE', purpose='PUR', code='MP')] * 20)
    d = decide('IMPS-615319937985-POWER STEELS-UTIB-xxxxxxxxxxx0657-PUR', 'kvb', mem)
    assert (d.category, d.code, d.source) == ('MATERIAL PURCHASE', 'MP', 'learned')


def test_a_contested_row_is_left_for_the_user_however_strong_the_evidence():
    """157 prior payments, and it still must not choose — the deciding fact
    (which job) is not in the statement, so the score is not about this row."""
    mem = memory([row('ARJUNAN S', 'SITE EXPENSES', purpose='LABOUR')] * 103
                 + [row('ARJUNAN S', 'FACTORY EXPENSES', purpose='LABOUR')] * 54)
    d = decide('UPI/P2A/608304124225/ARJUNAN S           /labour/AXIS BANK', 'axis', mem)
    assert d.category == 'UNCATEGORIZED'
    assert d.source == 'suggested'
    assert 'depends which job' in d.explanation


def test_credits_are_still_settled_by_the_flag():
    mem = memory([row('ANY', 'SITE EXPENSES')] * 20)
    d = decide('NEFT CR-CNRB0000967-SV CONSTRUCTIONS-VISMA ASSOCIA', 'kvb', mem, drcr='CR')
    assert (d.category, d.source) == ('AMOUNT RECEIVED', 'credit')


def test_without_a_memory_nothing_changes():
    """The CLI and Excel-only paths must behave exactly as they did before."""
    narration = 'UPI/P2A/608304124225/PUSHPARAJ R          /porter/CANARA BANK'
    d = decide(narration, 'axis', None)
    assert d.source == 'keyword'
    assert d.confidence is None
