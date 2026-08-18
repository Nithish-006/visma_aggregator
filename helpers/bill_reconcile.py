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
* **Vendor identity is the *anchor*, not any shared word.** ``bill_invoices``.
  ``vendor_name`` (from the invoice PDF) and ``kvb_transactions``.
  ``client_vendor`` (typed in the UI) are independent free text and are never
  spelled identically, so the comparison has to be fuzzy. But fuzziness over a
  bag of words is what let "HARI OM ROOFING INDUSTRIES" and "P&P ROOFING" read
  as one supplier: they share ROOFING, and nothing more was ever required.

  These names have a structure worth exploiting — a trade name is
  ``<who> <what they sell>``: *Hari Om* Roofing, *Balu* Iron, *Selvanayagi*
  Power Tools, *Ceyone* Fasteners. So we take the **anchor** — the first real
  word naming neither a courtesy (SRI, M/s) nor a trade (ROOFING, STEELS,
  TOOLS) — and require anchors to agree *before* any similarity score is
  consulted. A shared trade word can no longer marry two suppliers.

  The anchor comparison is itself forgiving — exact, prefix, fuzzy, or
  phonetic — because the drift we must absorb lives in the identity word too
  (MAHALAKSHMI/MAHALAXMI, SOUTHERN/SOUTHRN, INDLAZ/INDLAS).
* **The descriptor list is structural, not a blocklist.** Forgetting a trade
  word costs a *split* — two rows for one supplier, visible and fixable. It
  can no longer cost a *merge*, which is silent and destroys a real conflict.
  That asymmetry is the whole point: the old "any shared strong token proves
  identity" rule failed the other way round, and failed silently.
* **Initials are identity, and used to be deleted.** "P&P", "C S K", "Q" and
  the "M/s" courtesy prefix all vanished under the old ``len(tok) > 1`` rule —
  which is precisely why "P&P ROOFING" collapsed to the bare word ROOFING.
  Runs of short tokens are now welded into one initialism instead.
* **A project with zero purchase bills is never flagged.** We can't tell a
  genuine mis-tag from "bills simply aren't uploaded yet", so silence beats a
  storm of warnings.
"""

import re
from collections import namedtuple
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
    'SERVICE',
})

# Courtesy prefixes. "SRI KARPAGAM STEELS" is Karpagam; "Shri Selvanayagi
# Associates" and "SELVANAYAGI POWER TOOLS" are one supplier.
_VENDOR_HONORIFICS = frozenset({
    'SRI', 'SHRI', 'SHREE', 'SREE', 'MS', 'MESSRS', 'THIRU', 'TVL', 'NEW',
})

# What a supplier SELLS — never who it is. A trade name reads as
# "<identity> <descriptor>", so these are skipped when hunting for the anchor.
# Adding a word here makes matching stricter (a missed one costs a split, not a
# merge), so err towards listing it.
_VENDOR_DESCRIPTORS = frozenset({
    'STEEL', 'STEELS', 'IRON', 'IRONS', 'METAL', 'METALS', 'ALLOY', 'ALLOYS',
    'TUBE', 'TUBES', 'PIPE', 'PIPES', 'ROD', 'RODS', 'WIRE', 'WIRES',
    'SHEET', 'SHEETS', 'PLATE', 'PLATES', 'ANGLE', 'ANGLES', 'SCRAP',
    'ROOF', 'ROOFS', 'ROOFING', 'ROOFINGS', 'CEMENT', 'CEMENTS', 'CONCRETE',
    'BRICK', 'BRICKS', 'SAND', 'STONE', 'STONES', 'GRANITE', 'MARBLE',
    'TIMBER', 'TIMBERS', 'WOOD', 'PLYWOOD', 'GLASS', 'PAINT', 'PAINTS',
    'CHEMICAL', 'CHEMICALS', 'ELECTRIC', 'ELECTRICAL', 'ELECTRICALS',
    'ELECTRONICS', 'ELECTROD', 'ELECTRODS', 'ELECTRODE', 'ELECTRODES',
    'ELECTRODSS', 'ELECTORDS', 'ELECTORDSS', 'HARDWARE', 'HARDWARES',
    'TOOL', 'TOOLS', 'EQUIPMENT', 'EQUIPMENTS', 'MACHINE', 'MACHINES',
    'MACHINERY', 'SPARES', 'FASTENER', 'FASTENERS', 'FASTNER', 'FASTNERS',
    'BOLT', 'BOLTS', 'NUT', 'NUTS', 'SCREW', 'SCREWS', 'BEARING', 'BEARINGS',
    'THREAD', 'THREADS', 'ROLLING', 'WELDING', 'WELD', 'CUTTING',
    'FABRICATION', 'FAB', 'FABS', 'ENGINEERING', 'ENGINEER', 'ENGINEERS',
    'CONSTRUCTION', 'CONSTRUCTIONS', 'BUILDER', 'BUILDERS', 'BUILDING',
    'INFRA', 'INFRASTRUCTURE', 'MATERIAL', 'MATERIALS', 'PRODUCT', 'PRODUCTS',
    'CRAFT', 'CRAFTS', 'WORK', 'WORKS', 'PLUMBING', 'SANITARY',
    'SANITARYWARE', 'TILE', 'TILES', 'AIR', 'HOME', 'HOMES', 'SOLUTION',
    'SOLUTIONS', 'SYSTEM', 'SYSTEMS', 'CENTRE', 'CENTER', 'POINT', 'LINKS',
    'QUALITY',
})

# Financial-year suffixes on bill vendor names ("POWER STEELS - 2026-2027").
_YEAR_RE = re.compile(r'^(19|20)\d{2}$')

# "M/s", "M/s.", "M / S" — the Indian Messrs courtesy prefix.
_MESSRS_RE = re.compile(r'\bM\s*/\s*S\b\.?')

# Ampersand between two initials: "P&P" is one initialism, not "P AND P".
_INITIAL_AMP_RE = re.compile(r'(?<=\b[A-Z])\s*&\s*(?=[A-Z]\b)')

# Below this SequenceMatcher ratio two token-strings are treated as different
# vendors. 0.82 tolerates minor spelling/abbreviation drift without letting
# unrelated names collide.
_FUZZY_RATIO_THRESHOLD = 0.82

# Anchors this alike name the same supplier (SOUTHERN/SOUTHRN, INDLAZ/INDLAS).
_ANCHOR_RATIO_THRESHOLD = 0.82

# Consonant-skeleton comparison may be looser: it has already discarded the
# vowels and transliteration noise that caused the drift in the first place.
_SKELETON_RATIO_THRESHOLD = 0.85

# One anchor abbreviating the other ("MANICKAM" / "MANICK"). Short prefixes are
# too weak to trust — "CS" would swallow "CSK" — so both sides need length.
_MIN_PREFIX_ANCHOR_LEN = 4

# Transliteration equivalences seen in Tamil/Malayalam trade names romanised by
# different hands: Mahalakshmi/Mahalaxmi, Indlaz/Indlas.
_PHONETIC_SUBSTITUTIONS = (
    ('KSH', 'X'), ('SH', 'S'), ('CH', 'S'), ('PH', 'F'), ('TH', 'T'),
    ('DH', 'D'), ('BH', 'B'), ('GH', 'G'), ('KH', 'K'), ('JH', 'J'),
    ('CK', 'K'), ('Z', 'S'), ('V', 'W'), ('Q', 'K'),
)


#: A vendor name reduced to what identifies it: the significant word tokens,
#: plus the one ``anchor`` word naming *who* the supplier is.
VendorKey = namedtuple('VendorKey', ('tokens', 'anchor'))


def project_id_from_tag(tag):
    """Numeric project id from a "<id> - <Stem>" tag, or ``None``."""
    if not tag:
        return None
    m = _PROJECT_ID_RE.match(str(tag))
    return m.group(1) if m else None


def vendor_name_tokens(name):
    """Significant word tokens of a vendor name, **in reading order**.

    Punctuation, financial-year suffixes and company-form words go. Runs of
    one- and two-letter tokens are welded into a single initialism, so
    "C S K TUBE" and "CSK TUBE" agree and "P&P" survives as PP rather than
    being discarded for being too short.
    """
    if not name:
        return []
    text = str(name).upper()
    text = _INITIAL_AMP_RE.sub('', text)
    text = text.replace('&', ' AND ')
    text = _MESSRS_RE.sub(' ', text)
    text = re.sub(r'[^A-Z0-9]+', ' ', text)

    merged, initials = [], []
    for raw in text.split():
        if raw.isalpha() and len(raw) <= 2 and raw != 'AND':
            initials.append(raw)
            continue
        if initials:
            merged.append(''.join(initials))
            initials = []
        merged.append(raw)
    if initials:
        merged.append(''.join(initials))

    return [tok for tok in merged
            if not tok.isdigit()
            and not _YEAR_RE.match(tok)
            and tok != 'AND'
            and tok not in _VENDOR_STOPWORDS]


def normalize_vendor_tokens(name):
    """Significant, upper-cased word tokens of a vendor name (a frozenset)."""
    return frozenset(vendor_name_tokens(name))


def vendor_anchor(name):
    """The one word naming *who* this supplier is.

    The first token that is neither a courtesy prefix nor a trade descriptor,
    preferring a real word over an initialism. Falls back through initialisms
    to the bare descriptor, so a name made only of trade words ("PAINT") still
    yields something — it simply can't then match anything but another such
    name, which is the correct amount of caution for a name that identifies
    nobody.
    """
    tokens = [t for t in vendor_name_tokens(name) if t not in _VENDOR_HONORIFICS]
    for tok in tokens:
        if len(tok) >= 3 and tok not in _VENDOR_DESCRIPTORS:
            return tok
    for tok in tokens:
        if tok not in _VENDOR_DESCRIPTORS:
            return tok
    return tokens[0] if tokens else ''


def _phonetic_skeleton(token):
    """Consonant skeleton, blind to transliteration and vowel choices."""
    out = token
    for src, dst in _PHONETIC_SUBSTITUTIONS:
        out = out.replace(src, dst)
    out = re.sub(r'(.)\1+', r'\1', out)        # doubled letters
    return re.sub(r'(?<=.)[AEIOU]', '', out)   # every vowel but the first


def vendor_anchors_agree(a, b):
    """True when two anchor words name the same supplier.

    Exact, abbreviated, mis-spelled or merely transliterated differently — all
    four kinds of drift appear in this data, and none may be mistaken for a
    different supplier that happens to sell the same thing.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    if ((a.startswith(b) or b.startswith(a))
            and min(len(a), len(b)) >= _MIN_PREFIX_ANCHOR_LEN):
        return True
    if SequenceMatcher(None, a, b).ratio() >= _ANCHOR_RATIO_THRESHOLD:
        return True
    skeleton_a, skeleton_b = _phonetic_skeleton(a), _phonetic_skeleton(b)
    if skeleton_a and skeleton_a == skeleton_b:
        return True
    return (len(skeleton_a) >= 4 and len(skeleton_b) >= 4
            and SequenceMatcher(None, skeleton_a, skeleton_b).ratio()
            >= _SKELETON_RATIO_THRESHOLD)


def vendor_key(name):
    """``VendorKey`` for a raw vendor name — tokens plus identity anchor."""
    return VendorKey(normalize_vendor_tokens(name), vendor_anchor(name))


def vendor_keys_match(a, b):
    """True when two ``VendorKey``s plausibly name the same vendor.

    The anchors must agree — that is what stops a shared trade word from
    marrying two suppliers. Given agreeing anchors we stay lenient about the
    rest of the name, because the remainder is exactly where abbreviation
    noise lives ("Alpha Thread" vs "ALPHA THREAD ROLLING").
    """
    if not a.tokens or not b.tokens:
        return False
    if not vendor_anchors_agree(a.anchor, b.anchor):
        return False
    if a.tokens & b.tokens:
        return True
    left = ' '.join(sorted(a.tokens))
    right = ' '.join(sorted(b.tokens))
    return SequenceMatcher(None, left, right).ratio() >= _FUZZY_RATIO_THRESHOLD


def build_bill_vendor_index(bill_rows):
    """Index purchase-bill vendors by project id: ``{id: [VendorKey, ...]}``.

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
        key = vendor_key(row.get('vendor_name'))
        if not key.tokens:
            continue
        index.setdefault(pid, []).append(key)
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
    bill_keys = bill_index.get(pid)
    if not bill_keys:
        # No bills for this project at all — can't distinguish a mis-tag from
        # bills-not-uploaded, so stay quiet.
        return False
    key = vendor_key(vendor)
    if not key.tokens:
        return False
    return not any(vendor_keys_match(key, bill_key) for bill_key in bill_keys)
