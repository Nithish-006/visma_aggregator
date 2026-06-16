"""Phase 0 smoke test for the app.py -> blueprints refactor.

Two guarantees, checked on every phase:

1. ``app:app`` still imports and exposes a module-level ``app`` (so ``gunicorn
   app:app`` and ``python app.py`` keep working).
2. The set of served URLs + their HTTP methods is byte-for-byte identical to the
   pre-refactor snapshot in ``route_map_snapshot.json``.

Runs under pytest *or* standalone: ``python -m tests.test_route_map``.
"""

import json
import os

from tests.route_map import route_signature

SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "route_map_snapshot.json")


def _load_snapshot():
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as fh:
        # JSON has no tuples; normalize inner lists for comparison.
        return [[rule, methods] for rule, methods in json.load(fh)]


def _live_signature():
    import app

    assert hasattr(app, "app"), "app.py must expose a module-level `app` object"
    return route_signature(app.app.url_map)


def test_app_boots():
    """`import app` succeeds and `app.app` is a Flask app."""
    import app

    assert app.app is not None
    assert app.app.url_map is not None


def test_route_map_unchanged():
    """The live URL+method set equals the committed snapshot."""
    expected = _load_snapshot()
    actual = _live_signature()

    exp_set = {(r, tuple(m)) for r, m in expected}
    act_set = {(r, tuple(m)) for r, m in actual}

    missing = sorted(exp_set - act_set)
    added = sorted(act_set - exp_set)

    msg_parts = []
    if missing:
        msg_parts.append("ROUTES DROPPED (in snapshot, not served):\n  " +
                         "\n  ".join(f"{r} {m}" for r, m in missing))
    if added:
        msg_parts.append("ROUTES ADDED (served, not in snapshot):\n  " +
                         "\n  ".join(f"{r} {m}" for r, m in added))

    assert not msg_parts, "\n\n".join(msg_parts)


def _run_standalone():
    failures = 0
    for name, fn in (("test_app_boots", test_app_boots),
                     ("test_route_map_unchanged", test_route_map_unchanged)):
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {name}\n{exc}")
    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nAll route-map smoke tests passed")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_standalone())
