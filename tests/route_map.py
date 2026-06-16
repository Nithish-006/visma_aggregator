"""Shared helper for the route-map smoke test (Phase 0 of the app.py refactor).

The contract the refactor must preserve is *the exact set of URLs served, with the
exact HTTP methods*. Endpoint names intentionally change under blueprints
(``login`` -> ``auth.login``), so we deliberately key on ``(rule, methods)`` and
NOT on ``rule.endpoint``.

HEAD and OPTIONS are auto-added by Werkzeug and carry no app meaning, so they are
stripped to keep the snapshot stable.
"""

AUTO_METHODS = {"HEAD", "OPTIONS"}


def route_signature(url_map):
    """Return a sorted, JSON-serializable snapshot of the URL map.

    Each entry is ``[rule_string, [sorted_methods]]``. The whole list is sorted so
    the snapshot is deterministic regardless of registration order.
    """
    sig = []
    for rule in url_map.iter_rules():
        methods = sorted(m for m in rule.methods if m not in AUTO_METHODS)
        sig.append([rule.rule, methods])
    sig.sort(key=lambda entry: (entry[0], entry[1]))
    return sig
