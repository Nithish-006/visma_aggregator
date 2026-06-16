# Tests

## Route-map smoke test (refactor safety net)

`test_route_map.py` is the guardrail for the `app.py` -> blueprints refactor
(see `REFACTOR_PLAN.md`). It asserts that:

1. `app:app` still imports and exposes a module-level `app` object.
2. The exact set of served URLs + HTTP methods matches the committed snapshot
   `route_map_snapshot.json`.

It keys on `(url, methods)` **not** endpoint name, because blueprint endpoints
intentionally get renamed (`login` -> `auth.login`).

### Run it (no pytest needed)

```bash
python -m tests.test_route_map      # standalone runner, exit code 0 = pass
python -m pytest tests/             # also works if pytest is installed
```

Run it after **every** refactor phase. A diff in the output means a route was
dropped, added, or had its methods changed — which is a bug, since the refactor
is a pure structural move.

### Regenerating the snapshot

Only when a route is *intentionally* changed (and reviewed):

```bash
python -m tests.generate_route_snapshot
```

The refactor itself must never need this.
