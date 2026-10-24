"""Build a :class:`~helpers.vendor_spelling.VendorSpellings` from a bank table.

``helpers/vendor_spelling`` is deliberately free of any database so its rules
stay testable and pure — the same contract ``helpers/category_memory`` keeps
with ``helpers/category_loader``. This module is the thin seam between them.

Read fresh per request and memoised on Flask's ``g``: never cached across
requests, so a vendor renamed in one gunicorn worker is the spelling the next
upload snaps to in all of them.
"""

from flask import g, has_request_context

from extensions import db_manager
from helpers.vendor_spelling import NO_SPELLINGS, VendorSpellings

_G_KEY = '_vendor_spellings_%s'


def get_vendor_spellings(bank_code='axis'):
    """How this bank's table already spells its vendors.

    Falls back to :data:`~helpers.vendor_spelling.NO_SPELLINGS` if the table
    can't be read — names are then stored as the narration spells them, which
    is the behaviour before this module, and never a reason to fail an upload.
    """
    cache_key = _G_KEY % bank_code
    if has_request_context():
        cached = g.get(cache_key, None)
        if cached is not None:
            return cached

    try:
        spellings = VendorSpellings(db_manager.get_vendor_names(bank_code))
    except Exception as e:
        print(f"[!] Vendor spellings unavailable for {bank_code}, "
              f"storing names as read: {e}")
        spellings = NO_SPELLINGS

    if has_request_context():
        setattr(g, cache_key, spellings)
    return spellings
