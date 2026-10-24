"""Write a newly uploaded vendor the way this bank's table already spells it.

``vendor_extractor`` reads the payee off each narration exactly as that
narration spells it, and the banks are not consistent with themselves: Axis
writes 'ARJUNAN  S' on UPI and 'Arjunan s' on NEFT for one account, and KVB
cuts long names at the export width ('SIRUVANI PILING AND DRILLING P'). Stored
verbatim, every upload re-introduced spellings that ``scripts/vendor_unify.py``
had already merged — and the vendor filter, the project summary and the
category memory all group on the exact string.

So the extracted name is *snapped* to an existing spelling, and only in the two
cases where that is a fact about the letters rather than a judgement:

* **same letters** — equal once case, spacing and punctuation are ignored. The
  spelling on the most rows wins;
* **cut-off fragment** — a narration ``vendor_extractor`` flagged as truncated,
  whose name is the start of exactly one longer spelling already on file.

Anything else — a name the table has never seen, or a fragment that could
belong to more than one vendor ('MAHALAKSH') — is written as extracted. Merging
names that merely look alike is a human decision; ``scripts/vendor_unify.py``
holds those for review rather than guessing.

Pure by design, like ``helpers/category_memory``: the spellings are handed in,
so the rules stay testable without a database. ``helpers/vendor_spelling_loader``
is the seam that reads them.
"""

import collections
import re

from vendor_extractor import SELF_CANONICAL, _squash

# Values that name nobody, so are never a spelling to snap to.
_PLACEHOLDERS = frozenset({'', 'UNKNOWN', 'NONE', 'NA', 'N/A', '-', '.'})

# A note typed after the name: 'SRIDHAR K M/ARJUN', 'Google India Digital(eb bill)'.
# The note is someone's knowledge about one payment, not a spelling of the vendor.
_ANNOTATION = re.compile(r'[/(,]')

# Stray trailing separators are typing noise, not a note: 'Unique products/'
_TRAILING_NOISE = re.compile(r'[\s/.\-_]+$')

_WHITESPACE = re.compile(r'\s+')


def tidy_vendor(value):
    """Collapse whitespace and drop trailing separators."""
    text = _WHITESPACE.sub(' ', str(value or '').replace('\xa0', ' ')).strip()
    return _TRAILING_NOISE.sub('', text).strip()


def is_annotated(value):
    """True when a stored value carries a note after the name."""
    return bool(_ANNOTATION.search(value or ''))


def sole_extension(short, names):
    """The longest of ``names`` extending ``short``, if they form one chain.

    ``names`` are squashed forms. Every candidate must be a prefix of the
    longest, or the fragment could belong to more than one vendor
    ('MAHALAKSH' -> MAHALAKSHMI ELECTRICA / MAHALAKSHMI AGENCIES).
    """
    longer = [sq for sq in names if sq != short and sq.startswith(short)]
    if not longer:
        return None
    full = max(longer, key=len)
    return full if all(full.startswith(sq) for sq in longer) else None


class VendorSpellings:
    """How one bank's table spells its vendors, for snapping new uploads.

    Built from the stored ``client_vendor`` values — one per row, so the count
    of each spelling is the number of rows using it. Immutable snapshot, built
    once per upload and passed into the processor.
    """

    __slots__ = ('_by_squash',)

    def __init__(self, names=()):
        counts = collections.defaultdict(collections.Counter)
        for name in names:
            value = tidy_vendor(name)
            if value.upper() in _PLACEHOLDERS or is_annotated(value):
                continue
            counts[_squash(value)][value] += 1
        # {squashed: the spelling on the most rows}
        self._by_squash = {sq: c.most_common(1)[0][0]
                           for sq, c in counts.items() if sq}

    def snap(self, match):
        """The name to store for a ``VendorMatch``; None when it names nobody."""
        name = tidy_vendor(match.vendor) if match.vendor else ''
        if not name:
            return None
        if match.is_self:
            return SELF_CANONICAL

        squashed = _squash(name)
        if squashed in self._by_squash:
            return self._by_squash[squashed]
        if match.truncated:
            full = sole_extension(squashed, self._by_squash)
            if full:
                return self._by_squash[full]
        return name

    def __len__(self):
        return len(self._by_squash)

    def __bool__(self):
        return bool(self._by_squash)


#: No spellings on file — snapping then only tidies whitespace and rewrites the
#: account holder to its canonical name.
NO_SPELLINGS = VendorSpellings()
