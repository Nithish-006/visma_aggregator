"""
Vendor / counterparty extraction from bank statement narrations.

Axis narrations are '/'-delimited, KVB narrations are '-'-delimited (with ':'
variants in the clearing rows).  Neither bank puts the counterparty name in a
fixed slot: the index depends on how many routing tokens the channel emits
before the name.  So we match the transaction *family* first by an anchored
prefix, then read the name from that family's known slot.

Every rule below was derived from the live production statement corpus
(1,783 Axis rows + 720 KVB rows); tests/test_vendor_extractor.py pins each
family to real narrations from that corpus.
"""

import re
from dataclasses import dataclass
from typing import Optional


# ============================================================================
# NORMALISATION
# ============================================================================

# The app appends these when a transaction is split across projects.  They are
# our own annotation, not bank data, and they shift the field count.
_SPLIT_MARKER = re.compile(r'\s*\[SPLIT\s+\d+\s*/\s*\d+\]', re.IGNORECASE)

# Axis pads unused trailing fields with empty slashes: 'NAME/BANK//////'
_TRAILING_SEPARATORS = re.compile(r'[/\-\s]+$')

_WHITESPACE = re.compile(r'\s+')

# KVB's older export truncates the narration at exactly this width, cutting
# names mid-word ('FACILITIES AND BUILDING SOLUTI').  Regex cannot recover the
# tail; we only flag it so a downstream canonicaliser can merge the fragment.
KVB_TRUNCATION_WIDTH = 50


def normalize_narration(particulars: str) -> str:
    """Strip our own split markers and trailing padding; collapse whitespace."""
    if not particulars or not isinstance(particulars, str):
        return ""
    text = _SPLIT_MARKER.sub('', particulars)
    text = _TRAILING_SEPARATORS.sub('', text)
    return _WHITESPACE.sub(' ', text).strip()


# ============================================================================
# REJECTION FILTERS - things that occupy a name slot but are not names
# ============================================================================

# Inter-bank transaction references: AXODH04500471353, KVBLR52026020763823588,
# UTIBR62026021957915875, FDRLH26061186898, ...
_TXN_REF = re.compile(r'^[A-Z]{4,5}[A-Z]?\d{8,}$')

# IFSC codes always have '0' as the fifth character: CNRB0004373, UTIB0000477
_IFSC = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')

# Masked account numbers: xxxxxxxxx6686, X007517, XXXX4008
_MASKED_ACCOUNT = re.compile(r'^x+\d*$', re.IGNORECASE)

# Bare account numbers appear in the name slot of some UPI credits
_ALL_DIGITS = re.compile(r'^\d+$')

# The account holder itself - a self-transfer between their own banks is not a
# vendor.  Matched on an alphanumeric-only, upper-cased form so that
# 'VISMAASSOCIATES', 'VISMA ASSOCIATES' and the truncated 'VISMAASS' all hit.
_SELF_PREFIXES = ('VISMAASS', 'VISMAASSOCIAT')
SELF_CANONICAL = 'VISMA ASSOCIATES'

_ALNUM_ONLY = re.compile(r'[^A-Za-z0-9]')


def _squash(name: str) -> str:
    return _ALNUM_ONLY.sub('', name or '').upper()


def is_self_name(name: str) -> bool:
    squashed = _squash(name)
    return any(squashed.startswith(p) for p in _SELF_PREFIXES)


def _is_not_a_name(candidate: str) -> bool:
    """True when the captured slot holds routing data rather than a name."""
    if not candidate:
        return True
    stripped = candidate.strip().strip('.-_/')
    if len(stripped) < 2:
        return True
    # Needs at least two letters to be a plausible name
    if len(re.findall(r'[A-Za-z]', stripped)) < 2:
        return True
    collapsed = stripped.replace(' ', '')
    return bool(
        _ALL_DIGITS.match(collapsed)
        or _MASKED_ACCOUNT.match(collapsed)
        or _IFSC.match(collapsed.upper())
        or _TXN_REF.match(collapsed.upper())
    )


def _clean(name: str) -> str:
    """Tidy a captured name without changing its casing."""
    cleaned = _WHITESPACE.sub(' ', (name or '').replace('\xa0', ' ')).strip()
    # Axis right-pads names with spaces then a stray separator
    return cleaned.strip('.-_/ ').strip()


# ============================================================================
# RESULT
# ============================================================================

@dataclass
class VendorMatch:
    """Structured outcome of parsing one narration."""

    vendor: Optional[str]       # cleaned display name, None when not derivable
    family: str                 # e.g. 'axis.upi.p2a' - which rule fired
    raw: Optional[str] = None   # the slot exactly as it appeared
    is_self: bool = False       # counterparty is the account holder
    is_reversal: bool = False   # returned/reversed transaction
    is_internal: bool = False   # movement between the holder's own accounts
    truncated: bool = False     # source narration was cut off mid-name

    def __bool__(self) -> bool:
        return self.vendor is not None


_UNRESOLVED = 'unresolved'


def _hit(name, family, *, self_ok=False, **flags) -> VendorMatch:
    raw = name
    cleaned = _clean(name) if name else ''
    if not cleaned or _is_not_a_name(cleaned):
        return VendorMatch(None, family, raw=raw, **flags)
    if is_self_name(cleaned):
        return VendorMatch(
            cleaned if self_ok else SELF_CANONICAL, family,
            raw=raw, is_self=True, **flags
        )
    return VendorMatch(cleaned, family, raw=raw, **flags)


def _literal(vendor, family, **flags) -> VendorMatch:
    return VendorMatch(vendor, family, raw=vendor, **flags)


# ============================================================================
# AXIS BANK - '/' delimited
# ============================================================================
#
#   UPI/P2A/636719048195/SRIDHAR K M          /expens/BANK OF BARODA
#    0   1        2             3               4          5
#   INB/NEFT/AXODH04500471353/Prime electrodss/CITY UNION BANK LIMI//////
#    0   1          2                3                  4
#   NEFT/KVBLH00251999866/VISMA ASSOCIATES/KARUR VYSYA BANK/NA/...
#    0          1                 2                3
#
# The last shape is one token short - no subtype - which is exactly why the
# slot index has to follow from the matched family, not from a fixed number.

_AXIS_RULES = [
    # UPI collect-request declines carry no counterparty at all
    (re.compile(r'^UPIP2PPAY/DECLINE/', re.IGNORECASE),
     lambda m, s: _literal(None, 'axis.upi.decline')),

    # UPI person-to-person and person-to-merchant
    (re.compile(r'^UPI/P2A/\d+/([^/]*)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.upi.p2a')),
    (re.compile(r'^UPI/P2M/\d+/([^/]*)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.upi.p2m')),

    # IMPS - name slot is occasionally empty (only the masked a/c survives)
    (re.compile(r'^IMPS/P2[AM]/\d+/([^/]*)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.imps')),

    # Returns/reversals put the original beneficiary one slot further along,
    # behind a narration code (NARR, AC01, ...)
    (re.compile(r'^(?:NEFT|RTGS)/RETURN/[A-Z0-9]+/[A-Z0-9]{2,6}/([^/]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.return', is_reversal=True)),

    # Internet-banking NEFT/RTGS: INB / channel / reference / NAME / bank
    (re.compile(r'^INB/(?:NEFT|RTGS)/[A-Z0-9]+/([^/]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.inb.neft')),

    # Branch-originated NEFT: NEFT / DH / reference / NAME / bank
    (re.compile(r'^NEFT/DH/[A-Z0-9]+/([^/]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.neft.dh')),

    # Internal fund transfer to a saved payee nickname (no reference field)
    (re.compile(r'^INB/IFT/([^/]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.inb.ift', self_ok=True)),

    # Tax payments: INB / challan number / GST TAX PAYMENT
    (re.compile(r'^INB/\d+/([^/]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.inb.tax')),

    # Inward NEFT/RTGS - no subtype token, so the name sits at index 2
    (re.compile(r'^(?:NEFT|RTGS)/[A-Z]{4}[A-Z0-9]{6,}/([^/]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.inward', self_ok=True)),

    # 'RTGS PAID TO SURESH' / 'PAID TO SURESH' - free-text manual narration
    (re.compile(r'^(?:RTGS\s+)?PAID\s+TO\s+(.+)$', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'axis.paid_to')),

    # Bank's own charges - the counterparty is the bank
    (re.compile(r'(Monthly\s+(?:Avg\s+Bal|Service)\s+Chrgs|Card\s+Charges|^GST\s*@)', re.IGNORECASE),
     lambda m, s: _literal('AXIS BANK', 'axis.bank_charges')),
]


# ============================================================================
# KARUR VYSYA BANK - '-' delimited
# ============================================================================
#
#   IMPS-600221478795-PRABHU FAB-CNRB-xxxxxxxxx6686-BL
#    0          1          2       3        4        5
#   NEFT CR-CBIN0283507-AUTHORIZED OFFICERS ACCOUNT-VISMA ASSOCIATES-...
#      0          1                   2                    3
#
# For the CR variants field 2 is the *payer*; field 3 is the account holder.

_KVB_RULES = [
    # Reversal of an IMPS debit - field 2 is the literal 'IMPSP2A', no name
    (re.compile(r'^REV\s+IMPS-\d+-', re.IGNORECASE),
     lambda m, s: _literal(None, 'kvb.imps.reversal', is_reversal=True)),

    # IMPS - name may run to the end of a truncated narration
    (re.compile(r'^IMPS-\d+-([^-]+)(?:-|$)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.imps')),

    # NEFT / RTGS in both directions: prefix, IFSC or reference, then the name
    (re.compile(r'^(NEFT|RTGS)\s+(DR|CR)-[A-Z0-9]+-([^-]+)(?:-|$)', re.IGNORECASE),
     lambda m, s: _hit(m.group(3), f'kvb.{m.group(1).lower()}.{m.group(2).lower()}')),

    # Mobile-banking transfer between the holder's own accounts.  Carries only
    # masked account numbers - resolving it needs the account->vendor map.
    (re.compile(r'^MB-WITHIN-DR:(\w+)-CR:(\w+)', re.IGNORECASE),
     lambda m, s: _literal(None, 'kvb.mb_within', is_internal=True)),

    # Standing-instruction debits.  Three sub-forms share one tail:
    #   To Clg:ECS BD-TATA MF - NACH
    #   To Clg:ECS TP ACH NIPPON IND MF - NACH
    #   To Clg:ECS UGRO CAPITAL - NACH
    (re.compile(r'^To\s+Clg:ECS\s+(?:BD-|TP\s+ACH\s+)?(.+?)\s*-\s*NACH\s*$', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.ecs_nach')),

    # Inward cheque clearing: BY CLG:HEMA:HDFC Bank - 02-MAY-26
    (re.compile(r'^BY\s+CLG:([^:]+):', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.clearing.inward')),

    # Outward cheque return: O/W CHQ RTN::gefu chq return:-02-MAY-26-Alteration
    (re.compile(r'^O/W\s+CHQ\s+RTN', re.IGNORECASE),
     lambda m, s: _literal(None, 'kvb.cheque_return', is_reversal=True)),

    # Cash deposited at a machine - no depositor recorded
    (re.compile(r'^CASH\s+DEPOSIT\s+AT\s+CDM', re.IGNORECASE),
     lambda m, s: _literal('Cash Deposit', 'kvb.cash.cdm')),

    # Cash deposited at a counter: CASH DEP-SELF-SEETHALAKSHMI-CBE-RAMANATH
    (re.compile(r'^CASH\s+DEP-(?:SELF|TP)-([^-]+)-', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.cash.counter') or _literal('Cash Deposit', 'kvb.cash.counter')),

    # Cheque paid: CHQ PAID-TP-S SEETHALAKSHMI - CBE-RAMANATH
    (re.compile(r'^CHQ\s+PAID-(?:SELF|TP)-(.+?)\s*-\s*CBE', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.cheque.paid')),

    # KVB's UPI form differs from Axis: UPI-CR-<ref>-NAME-<BANK4>-...
    (re.compile(r'^UPI-(?:CR|DR)-\d+-([^-]+)(?:-|$)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.upi')),

    # Funds transfer: FT - CR - 1181155000201420 - ANUSUYA A - KVB
    (re.compile(r'^FT\s*-\s*(?:DR|CR)\s*-\s*\d+\s*-\s*([^-]+)', re.IGNORECASE),
     lambda m, s: _hit(m.group(1), 'kvb.ft')),

    # Account opening balance carry-forward, not a payment
    (re.compile(r'^NEW\s+A/C\s+.*OPENING\s+BAL', re.IGNORECASE),
     lambda m, s: _literal(None, 'kvb.opening_balance')),

    # Bank's own charges
    (re.compile(r'^(?:SMS\s+Charges|SAFE\s)', re.IGNORECASE),
     lambda m, s: _literal('KVB', 'kvb.bank_charges')),
]


_RULES_BY_BANK = {'axis': _AXIS_RULES, 'kvb': _KVB_RULES}


# ============================================================================
# PUBLIC API
# ============================================================================

def match_vendor(particulars: str, bank_code: str = 'axis') -> VendorMatch:
    """Parse a narration into a structured VendorMatch."""
    text = normalize_narration(particulars)
    if not text:
        return VendorMatch(None, 'empty')

    # A KVB narration sitting exactly on the export width was almost certainly
    # cut off; flag it so callers can reconcile the fragment against full names.
    truncated = bank_code == 'kvb' and len(text) == KVB_TRUNCATION_WIDTH

    for pattern, build in _RULES_BY_BANK.get(bank_code, _AXIS_RULES):
        m = pattern.search(text)
        if m:
            result = build(m, text)
            if truncated and result.vendor:
                # Only a name that runs to the end of the string lost characters
                result.truncated = text.rstrip().endswith((result.raw or '').rstrip())
            return result

    return VendorMatch(None, _UNRESOLVED)


def extract_vendor(particulars: str, bank_code: str = 'axis') -> Optional[str]:
    """Backwards-compatible string API: the vendor name, or None."""
    return match_vendor(particulars, bank_code).vendor
