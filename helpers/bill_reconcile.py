"""Flag material-purchase bank debits that no purchase bill can account for.

A KVB ``MATERIAL PURCHASE`` debit tagged to a project is a claim that we paid
a supplier for that project — and that claim should be backed by a purchase
bill (``bill_invoices``) from the same supplier under the same project. When
the transaction's vendor matches *no* purchase-bill vendor for its project,
the tag is most likely a human slip (the ZARON YES on project 648 case: money
went out, but no bill was ever raised for it). We surface a gentle
"no corresponding purchase bill" heads-up so someone re-verifies — we do NOT
block or auto-correct.

Design notes
------------
* **Join key is the canonical project id.** Both sides carry a free-text
  ``"<id> - <Stem>"`` tag; the numeric prefix is the reliable link.
* **Vendor match is fuzzy, and deliberately lenient.** ``bill_invoices``.
  ``vendor_name`` (from the invoice PDF) and ``kvb_transactions``.
  ``client_vendor`` (typed in the UI) are independent free text and are never
  spelled identically. We normalise case/punctuation, drop company-form words
  (PVT, LTD, CO, ...), and match on a shared significant token or a high
  overall similarity. Leaning lenient means the failure mode is a *missed*
  warning rather than a false alarm on a legitimate payment — which fits the
  "don't scare the user" brief.
* **A project with zero purchase bills is never flagged.** We can't tell a
  genuine mis-tag from "bills simply aren't uploaded yet", so silence beats a
  storm of warnings.
"""

import re
from difflib import SequenceMatcher

# The one warning humans see. Kept here so every surface renders the same text.
NO_BILL_WARNING_TEXT = 'NO CORRESPONDING PURCHASE BILL FOUND'

# Only this category is a purchase we expect a bill for. Stored UPPERCASE on
# save (banks.py), so compare against the canonical upper form.
MATERIAL_PURCHASE_CATEGORY = 'MATERIAL PURCHASE'

# Leading "<id> -" of a canonical project tag — the same contract the rest of
# the app tags by (mirrors helpers.projects._CANONICAL_PROJECT_RE).
_PROJECT_ID_RE = re.compile(r'^\s*(\d+)\s*-')

# Company-form words carry no identity — "BALU IRON PVT LTD" and "Balu Iron
# Co." are the same supplier. Dropping them keeps the match on the words that
# actually name the vendor.
_VENDOR_STOPWORDS = frozenset({
    'PVT', 'PVTLTD', 'PRIVATE', 'LTD', 'LTDS', 'LIMITED', 'LLP', 'LLC',
    'CO', 'COS', 'COMPANY', 'COMPANIES', 'CORP', 'CORPN', 'CORPORATION',
    'INC', 'INDIA', 'INDIAN', 'THE', 'AND', 'OF', 'FOR', 'AT',
    'ENTERPRISE', 'ENTERPRISES', 'ENTERPRICES', 'TRADERS', 'TRADER',
    'TRADING', 'AGENCIES', 'AGENCY', 'INDUSTRIES', 'INDUSTRY', 'INDUSTRIAL',
    'ASSOCIATES', 'SONS', 'BROS', 'BROTHERS', 'STORES', 'STORE', 'MART',
    'GROUP', 'SUPPLIERS', 'SUPPLIER', 'SUPPLY', 'SUPPLIES', 'SERVICES',
    'SERVICE', 'SOLUTIONS',
})

# Below this SequenceMatcher ratio two token-strings are treated as different
# vendors. 0.82 tolerates minor spelling/abbreviation drift without letting
# unrelated names collide.
_FUZZY_RATIO_THRESHOLD = 0.82


def project_id_from_tag(tag):
    """Numeric project id from a "<id> - <Stem>" tag, or ``None``."""
    if not tag:
        return None
    m = _PROJECT_ID_RE.match(str(tag))
    return m.group(1) if m else None


def normalize_vendor_tokens(name):
    """Significant, upper-cased word tokens of a vendor name (a frozenset).

    Strips punctuation, single characters, and company-form stopwords so what
    remains is the naming part of the vendor.
    """
    if not name:
        return frozenset()
    cleaned = re.sub(r'[^A-Z0-9 ]+', ' ', str(name).upper())
    tokens = {
        tok for tok in cleaned.split()
        if len(tok) > 1 and tok not in _VENDOR_STOPWORDS
    }
    return frozenset(tokens)


def vendor_tokens_match(a_tokens, b_tokens):
    """True when two token-sets plausibly name the same vendor.

    A shared significant token is enough (leniency is intentional — see the
    module docstring); otherwise fall back to overall string similarity.
    """
    if not a_tokens or not b_tokens:
        return False
    if a_tokens & b_tokens:
        return True
    a = ' '.join(sorted(a_tokens))
    b = ' '.join(sorted(b_tokens))
    return SequenceMatcher(None, a, b).ratio() >= _FUZZY_RATIO_THRESHOLD


def build_bill_vendor_index(bill_rows):
    """Index purchase-bill vendors by project id: ``{id: [token_set, ...]}``.

    ``bill_rows`` is any iterable of dict-likes carrying ``project`` and
    ``vendor_name`` (e.g. rows from ``get_purchase_bill_vendors_by_project``
    or ``get_bills_for_canonical_project``). Vendors with no significant
    tokens are skipped.
    """
    index = {}
    for row in bill_rows:
        pid = project_id_from_tag(row.get('project'))
        if not pid:
            continue
        tokens = normalize_vendor_tokens(row.get('vendor_name'))
        if not tokens:
            continue
        index.setdefault(pid, []).append(tokens)
    return index


def is_unbilled_material_purchase(category, project_tag, vendor, bill_index,
                                  bank_code='kvb'):
    """True when this row deserves the NO-CORRESPONDING-PURCHASE-BILL warning.

    Flags only KVB ``MATERIAL PURCHASE`` rows whose project has purchase bills
    but none from a matching vendor. Callers still gate on ``dr_amount > 0`` —
    the category is a debit head, but we don't re-check the amount here.
    """
    if bank_code != 'kvb':
        return False
    if (category or '').strip().upper() != MATERIAL_PURCHASE_CATEGORY:
        return False
    pid = project_id_from_tag(project_tag)
    if not pid:
        return False
    bill_token_sets = bill_index.get(pid)
    if not bill_token_sets:
        # No bills for this project at all — can't distinguish a mis-tag from
        # bills-not-uploaded, so stay quiet.
        return False
    vendor_tokens = normalize_vendor_tokens(vendor)
    if not vendor_tokens:
        return False
    return not any(vendor_tokens_match(vendor_tokens, bset)
                   for bset in bill_token_sets)
