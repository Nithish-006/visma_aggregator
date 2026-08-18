"""Load the human vendor-identity rulings that override the name matcher.

``helpers/bill_reconcile`` decides whether two spellings name one supplier, and
it is deliberately free of any database so its rules stay testable and pure.
This module is the thin seam that fetches a person's saved rulings and hands
them down as a :class:`~helpers.bill_reconcile.VendorAliasResolver`.

Read once per request and memoised on Flask's ``g`` — the same contract as
``helpers/bankdata``: never cached across requests, so a ruling saved by any
gunicorn worker is visible from all of them on the very next page. The table is
one row per decision a human actually made, so reading it whole is cheap.
"""

from flask import g, has_request_context

from extensions import db_manager
from helpers.bill_reconcile import NO_ALIASES, VendorAliasResolver

_G_KEY = '_vendor_alias_resolver'


def get_vendor_alias_resolver():
    """The saved vendor-identity rulings, as a resolver.

    Falls back to :data:`~helpers.bill_reconcile.NO_ALIASES` if the rules can't
    be read — the matcher then behaves exactly as it did before aliases
    existed, which is a reasonable panel rather than a broken one.
    """
    if has_request_context():
        cached = g.get(_G_KEY, None)
        if cached is not None:
            return cached

    try:
        rules = db_manager.get_vendor_alias_rules()
        resolver = VendorAliasResolver(links=rules.get('links'),
                                       splits=rules.get('splits'))
    except Exception as e:
        print(f"[!] Vendor alias rules unavailable, using name matching only: {e}")
        resolver = NO_ALIASES

    if has_request_context():
        setattr(g, _G_KEY, resolver)
    return resolver
