"""Build a :class:`~helpers.category_memory.CategoryMemory` from the live tables.

``helpers/category_memory`` is deliberately free of any database so its rules
stay testable and pure — the same contract ``helpers/bill_reconcile`` keeps.
This module is the thin seam that reads a bank's settled transactions and hands
them down as a memory, and it is the only place the two meet.

Read fresh per request and memoised on Flask's ``g``, exactly like
``helpers/bankdata`` and ``helpers/vendor_aliases``: never cached across
requests, so a category the user fixed in one gunicorn worker is evidence in
all of them on the very next upload.

Cost note: this reads the bank's categorised rows and re-parses each narration.
At a few thousand rows that is milliseconds, and it happens once per upload —
not once per transaction — because the memory is built before the statement is
processed and passed in.
"""

from flask import g, has_request_context

from extensions import db_manager
from helpers.category_memory import CategoryMemory, extract_purpose
from helpers.vendor_aliases import get_vendor_alias_resolver
from vendor_extractor import match_vendor

_G_KEY = '_category_memory_%s'


def get_category_memory(bank_code='axis', reference_date=None):
    """What this bank's vendors and payment remarks have meant so far.

    Returns an empty memory rather than raising if the history cannot be read —
    the processor then falls back to keyword scoring, which is exactly the
    behaviour that existed before this module.
    """
    cache_key = _G_KEY % bank_code
    if has_request_context():
        cached = g.get(cache_key, None)
        if cached is not None:
            return cached

    try:
        rows = db_manager.get_categorization_history(bank_code)
        for row in rows:
            # The remark is read off the narration, so it needs the family that
            # vendor_extractor already determined — no second parser.
            row['purpose'] = extract_purpose(
                row['description'], match_vendor(row['description'], bank_code).family)
        memory = CategoryMemory(
            rows,
            resolver=get_vendor_alias_resolver(),
            reference_date=reference_date,
        )
    except Exception as e:
        print(f"[!] Category memory unavailable for {bank_code}, "
              f"falling back to keyword categorisation: {e}")
        memory = CategoryMemory([])

    if has_request_context():
        setattr(g, cache_key, memory)
    return memory
