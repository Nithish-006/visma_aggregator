"""Regenerate the route-map snapshot fixture.

Run this ONLY against the pre-refactor code (or after an intentional, reviewed
route change) to capture the canonical set of URLs the app serves:

    python -m tests.generate_route_snapshot

The refactor itself must never need to regenerate this file — if a phase changes
the snapshot, that is a bug (a route was dropped, added, or its methods changed).
"""

import json
import os

from tests.route_map import route_signature

SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "route_map_snapshot.json")


def main():
    import app  # imported here so import-time output doesn't pollute `import tests`

    sig = route_signature(app.app.url_map)
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump(sig, fh, indent=2)
        fh.write("\n")
    print(f"Wrote {len(sig)} routes to {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
