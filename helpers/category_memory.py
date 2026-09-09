"""What a vendor's category has been before — the evidence for guessing it now.

``bank_statement_processor.categorize_transaction`` scores keywords against the
narration and knows nothing about history, so every upload re-guesses suppliers
the user has already ruled on hundreds of times. Worse, it *cannot* produce most
of the categories actually in use: CRANE RENT, AUTO RENT, CAPITAL AC and their
siblings were typed by a person and appear in no keyword list. Only history can
supply them.

This module is that history, and nothing else — it decides what category a
vendor has earned, not how to parse a statement. ``helpers/bill_reconcile``
supplies the vendor-identity rules it groups on, so a supplier spelled three
ways across three years counts as one body of evidence.

Design notes
------------
* **Vendors are grouped by anchor, not by string.** ``ARJUNAN  S`` /
  ``ARJUNAN S`` and ``V BALAJI RANGANATHAN`` / ``V BALAJI RANGAN`` are the same
  payee, and the bank spells them differently between statements. Reusing
  ``vendor_key``/``vendor_keys_match`` means every alias the user teaches the
  material reconciler improves categorisation too, with no second rule set to
  maintain.
* **A suggestion is a distribution, not an answer.** A vendor split between
  SITE EXPENSES and FACTORY EXPENSES should decline to guess rather than pick
  the marginal winner, so purity is carried through to the caller and the
  caller sets the bar.
* **Recency is weighted, history is not discarded.** A supplier that moved from
  one category to another converges on the new answer over roughly a year
  instead of flipping on a single row.
* **Credits are never learned from and never predicted.** ``AMOUNT RECEIVED``
  is assigned structurally from the DR/CR flag; letting it into the memory
  would teach every client's name a category that the flag already settles.
* **The account holder is not a vendor.** Self-transfers and internal movements
  carry no supplier identity, so they are excluded from both sides.
"""

import re
from collections import namedtuple

from helpers.bill_reconcile import (
    NO_ALIASES,
    vendor_key,
    vendor_keys_match,
)
from vendor_extractor import is_self_name

#: Categories that are decided structurally and must not be learned.
STRUCTURAL_CATEGORIES = frozenset({'AMOUNT RECEIVED'})

#: Stored placeholders that name no supplier.
_NON_VENDORS = frozenset({'', 'UNKNOWN', 'INTERNAL TRANSFER', 'SELF'})

#: Payment-rail tokens that occupy the name slot when the bank sent no name.
#: KVB in particular emits ``IMPS-614309611715-IMPSP2A-UTIB-xxxx3306-Exp``,
#: where the "name" is the rail itself — the narration identifies no supplier,
#: and the user typed one from knowledge we do not have. Learning from these
#: welds a dozen unrelated payees into one bucket and then answers confidently
#: from it, so they are rejected on both sides. A row like this must produce no
#: suggestion; that is the honest outcome, not a failure.
_RAIL_TOKENS = frozenset({
    'IMPS', 'IMPSP2A', 'IMPSP2M', 'NEFT', 'RTGS', 'UPI', 'UPIP2A', 'UPIP2M',
    'P2A', 'P2M', 'ECS', 'NACH', 'ACH', 'CASHDEP', 'CASH', 'ATM', 'POS',
    'MB', 'IB', 'INB', 'CHQ', 'CHEQUE', 'CLG', 'CLEARING', 'TRANSFER',
})

#: Banks are counterparties on a self-transfer, never suppliers. On KVB the
#: user's own Axis account shows up as "AXIS BANK" and its category follows
#: whatever the money was for, so it carries no signal.
_BANK_NAMES = frozenset({
    'AXISBANK', 'AXIS', 'KVB', 'KARURVYSYABANK', 'KARURVYSYA', 'HDFCBANK',
    'ICICIBANK', 'SBI', 'STATEBANKOFINDIA', 'CANARABANK', 'UNIONBANK',
    'INDIANBANK', 'IDBI', 'YESBANK', 'KOTAK', 'INDUSINDBANK', 'BANK',
})

#: Categories that mean "nobody has decided yet" — not evidence of anything.
_EMPTY_CATEGORIES = frozenset({'', 'UNCATEGORIZED'})

#: Evidence halves in weight over this many days. A year: slow enough that a
#: long-standing supplier keeps its identity, fast enough that a deliberate
#: change of treatment wins within a couple of statements.
DEFAULT_HALF_LIFE_DAYS = 365.0

#: Effective weight at which support stops adding confidence. Three consistent
#: prior rows is where a vendor stops being anecdote.
DEFAULT_SATURATION = 3.0

#: Smoothing added to the denominator when scoring purity, so that a vendor
#: seen three times and categorised the same way three times reads as 0.75
#: rather than a certain 1.00. Measured against real statements this is the
#: single most valuable correction: the confident misses were nearly all
#: many-sided payees — a person paid variously for site work, crane hire and
#: contract labour — whose first few rows happened to agree.
DEFAULT_SMOOTHING = 1.0

#: A vendor reached by fuzzy anchor agreement rather than an identical
#: canonical name is slightly less certain, and says so.
_FUZZY_MATCH_FACTOR = 0.9

# ---------------------------------------------------------------------------
# Thresholds, measured rather than chosen
# ---------------------------------------------------------------------------
# scripts/category_memory_dryrun.py holds out the most recent quarter of each
# bank table and scores the bands. At the time of writing, on production, with
# the contested-pair rule below in force:
#
#            rows >= AUTO   precision   held: contested   unseen   (was keyword)
#   KVB       111 of 181      97.3%          4.4%          12.7%      15.5%
#   Axis       71 of 436      91.5%         28.4%          15.1%      12.4%
#
# Axis applies to far fewer rows than KVB, and that is the intended shape
# rather than a shortfall: most of the difference is the contested pairs,
# where the client has said the answer is not in the statement at all.
#
# Re-run it after a few more statements land; if precision above AUTO drifts
# below ~85% the bar should move up, not the expectations.

#: Categories a bank statement cannot separate, because the fact that decides
#: between them never reaches it.
#:
#: The client's own words: which of these a labour payment belongs to "depends
#: which job it was for" — and the job is not in the narration, the vendor, the
#: remark or the amount. The same man, paid for LABOUR, four days apart, ₹300
#: each time, is SITE one week and FACTORY the next. There is no rule to learn,
#: so a confident guess here is a coin flip wearing a percentage.
#:
#: When the winner and runner-up sit in one group and the runner-up holds a
#: real share, the row is held for review instead of applied. It is *not*
#: excluded from learning: a payee who is 94% SITE is still settled, and only
#: the genuinely divided ones stop.
#:
#: This costs coverage on purpose. Leaving a row blank for a person to assign
#: is recoverable; filing it to the wrong job silently is not.
CONTESTED_CATEGORY_GROUPS = (
    frozenset({'SITE EXPENSES', 'FACTORY EXPENSES'}),
    frozenset({'TRANSPORT EXPENSES', 'TRUCK RENT', 'AUTO RENT',
               'TRAILER RENT', 'HYDRA RENT', 'CRANE RENT'}),
    frozenset({'SITE EXPENSES', 'LABOUR PAYMENT', 'CONTRACT PAYMENT'}),
)

#: How much of the evidence the runner-up must hold before a contested pair
#: counts as genuinely divided. Below this the winner is simply the answer —
#: a payee who is 58 SITE to 4 FACTORY has been settled by the user in
#: practice, and holding those rows back would be noise, not caution.
#:
#: Swept against the Axis holdout at the auto-apply bar:
#:
#:   share   applied  wrong  precision   held  (of which right)
#:   off          77      9      88.3%      0
#:   0.20         77      9      88.3%      0
#:   0.15         74      7      90.5%      3   1
#:   0.10         71      6      91.5%      6   3
#:   0.05         69      6      91.3%      8   5
#:
#: 0.10 buys the last avoidable error; 0.05 only starts holding back correct
#: answers. The differences here are one or two rows, so this is chosen as
#: much on the client's stated preference — when in doubt leave it blank and
#: they will assign it — as on the margin in the table.
CONTESTED_RUNNER_UP_SHARE = 0.10

#: At or above this, the category is written as if a person had chosen it.
AUTO_APPLY_CONFIDENCE = 0.80

#: Between this and AUTO_APPLY_CONFIDENCE the guess is recorded but the row is
#: left UNCATEGORIZED, so it surfaces in the dashboard's review filter. Below
#: it, the suggestion is discarded and keyword scoring decides.
REVIEW_CONFIDENCE = 0.55

#: Masked account numbers occupying a remark slot: xxxxxxxxxxx3306, X007517.
_MASKED_RE = re.compile(r'^x+\d*$', re.IGNORECASE)


#: What the memory has to say about one vendor.
#:
#: ``confidence`` folds purity, support and match quality into one number for
#: thresholding; the parts stay visible so the UI can explain itself and so the
#: dry-run can tune the bands against real data.
CategorySuggestion = namedtuple(
    'CategorySuggestion',
    'category code confidence purity support match_kind matched_vendor runner_up '
    'signal contested')


# ============================================================================
# THE PURPOSE SLOT — what the payer typed to say why
# ============================================================================
#
# Both banks carry a free-text remark the sender filled in, and neither
# categoriser has ever read it. It is the strongest signal available for the
# rows a vendor name cannot explain: the KVB IMPS narrations that name no payee
# at all, and the Axis UPI payments to people who get paid for many different
# things.
#
# The slot is family-specific and must be taken exactly, never as "the last
# segment". NEFT and RTGS narrations end in a *branch* — MUMBAI-FORT,
# CBE-RAMANATH — which reads like a purpose and is not one; treating it as one
# taught FORT to mean MATERIAL PURCHASE at 0.47 purity.
#
# Axis truncates the UPI remark to six characters, so the vocabulary is
# "SITE E", "FACTOR", "TRAILE", "GRINDI". That is fine — the tokens are learned
# from history, not matched against a word list, so a truncated remark is just
# a token like any other.

#: family -> (separator, slot index). A negative index counts from the end.
_PURPOSE_SLOTS = {
    'axis.upi.p2a': ('/', 4),
    'axis.upi.p2m': ('/', 4),
    'axis.inb.ift': ('/', 3),
    'axis.inb.tax': ('/', 2),
    'kvb.imps': ('-', 5),
    'kvb.mb_within': ('-', -1),
}

#: Placeholders that occupy the remark slot when nothing was typed. Axis writes
#: a literal "UPI" into the P2M remark on 466 debit rows — learning from it
#: blends every merchant payment into one meaningless bucket.
_NON_PURPOSES = frozenset({'UPI', 'NA', 'N/A', 'NONE', 'OTHERS', 'OTHER', ''})


def extract_purpose(particulars, family):
    """The remark the payer typed, or ``None`` when the slot holds no remark.

    ``family`` is ``VendorMatch.family`` from :func:`vendor_extractor.match_vendor`
    — the narration has already been identified there, and re-deriving it here
    would be a second parser to keep in step with the first.
    """
    slot = _PURPOSE_SLOTS.get(family)
    if not slot or not particulars:
        return None

    separator, index = slot
    parts = [p.strip() for p in str(particulars).split(separator)]
    try:
        candidate = parts[index]
    except IndexError:
        return None

    return _clean_purpose(candidate)


def _clean_purpose(candidate):
    cleaned = ' '.join((candidate or '').split()).upper()
    if cleaned in _NON_PURPOSES or len(cleaned) < 2:
        return None
    squashed = cleaned.replace(' ', '')
    # Account numbers, masked accounts, IFSC codes and rail references share
    # the slot on truncated narrations.
    if squashed.isdigit() or squashed in _RAIL_TOKENS:
        return None
    if squashed.upper().strip('X').strip('x') == '' or _MASKED_RE.match(squashed):
        return None
    # A remark needs letters; "3 LOAD" qualifies, "26061186898" does not.
    if sum(ch.isalpha() for ch in squashed) < 2:
        return None
    return cleaned


#: Typed-in categories that are plainly one category spelled two ways. Folding
#: them is what stops the memory reporting a miss when it was in fact right —
#: and stops the dashboard filter listing a category twice. Keys and values are
#: compared upper-cased; the value is the spelling that wins.
CATEGORY_SYNONYMS = {
    'TRAILLER RENT': 'TRAILER RENT',
    'TRUCT RENT AC': 'TRUCK RENT',
    'TRUCK RENT AC': 'TRUCK RENT',
    'CESS': 'CESS AC',
}


def canonical_category(category):
    """The agreed spelling of a typed-in category."""
    cleaned = (category or '').strip().upper()
    return CATEGORY_SYNONYMS.get(cleaned, cleaned)


def is_learnable_vendor(name):
    """True when this vendor string names a supplier we can learn about."""
    if not name:
        return False
    cleaned = str(name).strip()
    if cleaned.upper() in _NON_VENDORS:
        return False
    squashed = ''.join(ch for ch in cleaned.upper() if ch.isalnum())
    if squashed in _RAIL_TOKENS or squashed in _BANK_NAMES:
        return False
    return not is_self_name(cleaned)


class _Evidence:
    """One thing's category history, as accumulated weight per category.

    Used for both signals: keyed on a :class:`VendorKey` for suppliers and on
    the remark token for purposes. Only the lookup differs — the accumulation
    and scoring are the same, and sharing them keeps the two signals directly
    comparable when they have to be weighed against each other.
    """

    __slots__ = ('key', 'display', 'weights', 'codes')

    def __init__(self, key, display):
        self.key = key
        self.display = display
        self.weights = {}
        self.codes = {}

    def add(self, category, code, weight):
        self.weights[category] = self.weights.get(category, 0.0) + weight
        if code:
            self.codes[category] = code

    def merge(self, other):
        for category, weight in other.weights.items():
            self.weights[category] = self.weights.get(category, 0.0) + weight
        for category, code in other.codes.items():
            self.codes.setdefault(category, code)


class CategoryMemory:
    """The category each vendor has earned, learned from settled transactions.

    Built from rows already in the bank tables — which the user has curated
    heavily, so a stored category that is not ``UNCATEGORIZED`` is taken as
    their ruling. Construction is a single pass; lookup is a dict hit on the
    vendor's anchor with a short fuzzy scan as fallback.
    """

    def __init__(self, rows, resolver=NO_ALIASES, reference_date=None,
                 half_life_days=DEFAULT_HALF_LIFE_DAYS,
                 saturation=DEFAULT_SATURATION,
                 smoothing=DEFAULT_SMOOTHING):
        self._resolver = resolver
        self._saturation = float(saturation)
        self._smoothing = float(smoothing)
        self._by_anchor = {}
        self._by_purpose = {}
        self._rows_learned = 0
        self._purposes_learned = 0

        decay = _decay_fn(reference_date, half_life_days)

        for row in rows:
            category = canonical_category(row.get('category'))
            if category in _EMPTY_CATEGORIES or category in STRUCTURAL_CATEGORIES:
                continue
            if row.get('is_credit'):
                continue

            code = (row.get('code') or '').strip().upper() or None
            weight = decay(row.get('date'))

            vendor = row.get('vendor')
            if is_learnable_vendor(vendor):
                key = vendor_key(vendor, resolver)
                if key.tokens and key.anchor:
                    bucket = self._by_anchor.setdefault(key.anchor, [])
                    entry = _find_entry(bucket, key, resolver)
                    if entry is None:
                        entry = _Evidence(key, str(vendor).strip())
                        bucket.append(entry)
                    entry.add(category, code, weight)
                    self._rows_learned += 1

            # The two signals are learned independently and from the same row:
            # a payment can teach both who the supplier is and what the money
            # was for, and either may be the only one available next time.
            purpose = row.get('purpose')
            if purpose:
                entry = self._by_purpose.get(purpose)
                if entry is None:
                    entry = self._by_purpose[purpose] = _Evidence(purpose, purpose)
                entry.add(category, code, weight)
                self._purposes_learned += 1

    # -- introspection -----------------------------------------------------

    def __len__(self):
        return sum(len(bucket) for bucket in self._by_anchor.values())

    @property
    def rows_learned(self):
        """How many transactions became vendor evidence."""
        return self._rows_learned

    @property
    def purposes_learned(self):
        """How many transactions carried a usable payer remark."""
        return self._purposes_learned

    @property
    def purpose_count(self):
        """Distinct remark tokens known."""
        return len(self._by_purpose)

    # -- lookup ------------------------------------------------------------

    def suggest(self, vendor, purpose=None):
        """The best-supported category, or ``None`` when nothing is known.

        Weighs the two independent signals — who was paid, and what the payer
        said the money was for. Either can be absent: a KVB IMPS narration
        often names no supplier but carries a remark, and a NEFT payment names
        the supplier but carries no remark.

        Never filters on confidence — the caller owns that policy, because the
        right bar differs between auto-applying a category and merely offering
        it for review.
        """
        vendor_evidence, match_kind, display = self._vendor_evidence(vendor)
        purpose_evidence = self._by_purpose.get(purpose) if purpose else None

        if vendor_evidence is None and purpose_evidence is None:
            return None
        if purpose_evidence is None:
            return self._score(vendor_evidence, match_kind, display, 'vendor')
        if vendor_evidence is None:
            return self._score(purpose_evidence, 'purpose', purpose, 'purpose')

        # Combine as evidence, not as two finished probabilities.
        #
        # The tempting move is a noisy-or over the two confidences, and it is
        # wrong here: the signals are correlated, not independent. The remark
        # "TRUCK" and the haulier's name are one fact observed twice, so
        # treating them as two witnesses inflates agreement into near-certainty
        # — measured, it pushed ≥0.80 precision on Axis down from 90.5% to
        # 84.5% while looking more confident.
        #
        # Pooling the weights instead lets agreement raise *support* (which
        # saturates) without ever manufacturing purity, and lets disagreement
        # dilute purity honestly, so a genuine conflict falls out of the
        # auto-apply band on its own.
        merged = _Evidence(vendor_evidence.key, display)
        merged.merge(vendor_evidence)
        merged.merge(purpose_evidence)

        agree = _top_category(vendor_evidence) == _top_category(purpose_evidence)
        return self._score(merged, match_kind, display,
                           'both' if agree else 'conflict')

    def _vendor_evidence(self, vendor):
        """Pooled evidence for every stored spelling of this supplier."""
        if not is_learnable_vendor(vendor):
            return None, None, None

        key = vendor_key(vendor, self._resolver)
        if not key.tokens or not key.anchor:
            return None, None, None

        match_kind = 'anchor'
        entries = [e for e in self._by_anchor.get(key.anchor, ())
                   if vendor_keys_match(key, e.key, self._resolver)]
        if entries:
            match_kind = 'exact' if any(e.key.canon == key.canon for e in entries) else 'anchor'
        else:
            # The anchor comparison is itself forgiving (prefix, phonetic), so a
            # miss on the exact bucket is not a miss on the vendor. Few hundred
            # anchors at most, so the scan is cheap.
            match_kind = 'fuzzy'
            entries = [e for anchor, bucket in self._by_anchor.items()
                       if anchor != key.anchor
                       for e in bucket
                       if vendor_keys_match(key, e.key, self._resolver)]
        if not entries:
            return None, None, None

        merged = _Evidence(key, str(vendor).strip())
        for entry in entries:
            merged.merge(entry)

        return merged, match_kind, entries[0].display

    def _score(self, evidence, match_kind, display, signal):
        """Turn accumulated weight into a scored suggestion."""
        ranked = sorted(evidence.weights.items(), key=lambda kv: kv[1], reverse=True)
        if not ranked:
            return None
        category, weight = ranked[0]
        total = sum(evidence.weights.values())
        if total <= 0:
            return None

        # Smoothed purity: a vendor agreeing with itself three times out of
        # three is strong evidence, but not proof — the many-sided payees that
        # produced the worst misses all looked pure over their first few rows.
        smoothed = weight / (total + self._smoothing)
        support = min(1.0, total / self._saturation) if self._saturation else 1.0
        factor = _FUZZY_MATCH_FACTOR if match_kind in ('anchor', 'fuzzy') else 1.0

        runner_up = ranked[1][0] if len(ranked) > 1 else None
        contested = bool(
            runner_up
            and ranked[1][1] / total >= CONTESTED_RUNNER_UP_SHARE
            and any({category, runner_up} <= group
                    for group in CONTESTED_CATEGORY_GROUPS)
        )

        return CategorySuggestion(
            category=category,
            code=evidence.codes.get(category),
            confidence=smoothed * support * factor,
            # Reported unsmoothed, because "9 of 10 past rows" is what a person
            # needs to see; the smoothing is a scoring device, not a fact.
            purity=weight / total,
            support=total,
            match_kind=match_kind,
            matched_vendor=display,
            runner_up=runner_up,
            signal=signal,
            contested=contested,
        )


# ============================================================================
# INTERNALS
# ============================================================================

def _top_category(evidence):
    """The category this evidence favours, before any pooling."""
    if not evidence or not evidence.weights:
        return None
    return max(evidence.weights.items(), key=lambda kv: kv[1])[0]


def _find_entry(bucket, key, resolver):
    for entry in bucket:
        if entry.key.canon == key.canon:
            return entry
    for entry in bucket:
        if vendor_keys_match(key, entry.key, resolver):
            return entry
    return None


def _decay_fn(reference_date, half_life_days):
    """Weight for a row of a given age — 1.0 today, 0.5 one half-life back.

    Rows without a usable date get full weight rather than being dropped: an
    undated ruling is still a ruling.
    """
    if not reference_date or not half_life_days:
        return lambda _date: 1.0

    ref = _as_date(reference_date)
    if ref is None:
        return lambda _date: 1.0

    def weight(date):
        when = _as_date(date)
        if when is None:
            return 1.0
        age = (ref - when).days
        if age <= 0:
            return 1.0
        return 0.5 ** (age / half_life_days)

    return weight


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, 'date') and not isinstance(value, type(None)):
        try:
            return value.date()
        except (AttributeError, TypeError):
            pass
    return value if hasattr(value, 'toordinal') else None
