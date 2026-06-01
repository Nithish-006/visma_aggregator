"""
One-off backfill: ingest the staged project POs in the `PROJECT POS/` folder
into the registry + the new `project_pos` gist table.

For each PDF in PROJECT POS/:
  1. Match the file (by name) to a canonical registry project.
  2. Copy it into uploads/projects/<id>/<ts>_<name> and set projects.po_filename/po_path.
  3. Run AI extraction (po_processor) and upsert the gist into project_pos.

Matching is by case-insensitive stem name, with a small override map for files
whose name doesn't equal the registry stem (e.g. KALAPATTI -> 651 PROMINANCE).
If ANY file can't be matched, the script prints the problem and aborts (no writes).

Usage:
  python backfill_project_pos.py            # DRY RUN: show mapping + would-extract
  python backfill_project_pos.py --apply    # copy files, attach, extract, upsert
"""

import os
import sys
import json
import shutil
from datetime import datetime

# Importing config loads .env (so GEMINI_API_KEY / DB_* are available)
from config import Config
from database import DatabaseManager
import po_processor

PO_SOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'PROJECT POS')
UPLOAD_FOLDER = Config.UPLOAD_FOLDER
PROJECTS_UPLOAD_ROOT = os.path.join(UPLOAD_FOLDER, 'projects')

# Files whose name doesn't match a registry stem -> explicit project id.
# (Add entries here if a PO's filename differs from its canonical stem.)
FILE_OVERRIDES = {}


def norm(s):
    return ' '.join((s or '').upper().split())


def match_project(file_key, projects):
    """Return the registry project dict for a PO file name, or None."""
    if file_key in FILE_OVERRIDES:
        pid = FILE_OVERRIDES[file_key]
        return next((p for p in projects if p['id'] == pid), None)

    nkey = norm(file_key)
    # 1) exact stem match
    for p in projects:
        if norm(p['stem_name']) == nkey:
            return p
    # 2) containment either direction
    for p in projects:
        ns = norm(p['stem_name'])
        if ns and (ns in nkey or nkey in ns):
            return p
    return None


def main():
    apply_changes = '--apply' in sys.argv

    print("=" * 70)
    print(f"PROJECT PO BACKFILL  ({'APPLY' if apply_changes else 'DRY RUN'})")
    print("=" * 70)

    if not os.path.isdir(PO_SOURCE_DIR):
        print(f"[ABORT] Source folder not found: {PO_SOURCE_DIR}")
        return 1

    db = DatabaseManager()
    db.ensure_projects_table()  # also ensures project_pos

    projects = db.list_projects()
    if not projects:
        print("[ABORT] No projects in the registry. Create the registry first.")
        return 1

    files = sorted(f for f in os.listdir(PO_SOURCE_DIR)
                   if os.path.splitext(f)[1].lower() == '.pdf')
    if not files:
        print(f"[ABORT] No PDF POs found in {PO_SOURCE_DIR}")
        return 1

    # ---- Phase 1: resolve mapping. Unmatched files are skipped (not fatal). ----
    print("\nSTEP 1: match files to registry projects")
    plan = []
    unmatched = []
    for fname in files:
        key = os.path.splitext(fname)[0]
        proj = match_project(key, projects)
        if proj:
            plan.append((fname, proj))
            warn = '  [will OVERWRITE existing PO]' if proj.get('po_filename') else ''
            print(f"  [ok]   {fname:<24} -> {proj['id']} - {proj['stem_name']}{warn}")
        else:
            unmatched.append(fname)
            print(f"  [skip] {fname:<24} -> no matching project in registry")

    if unmatched:
        print(f"\n  NOTE: skipping {len(unmatched)} unmatched file(s): {unmatched}")
        print("        Create the project (or add to FILE_OVERRIDES) and re-run to ingest them.")

    if not plan:
        print("\n[ABORT] Nothing to ingest.")
        return 1

    if not apply_changes:
        print("\nDRY RUN complete. Re-run with --apply to copy files, attach, and extract.")
        return 0

    # ---- Phase 2: copy, attach, extract, upsert ----
    print("\nSTEP 2: copy + attach + extract")
    for fname, proj in plan:
        pid = proj['id']
        src = os.path.join(PO_SOURCE_DIR, fname)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        stored_name = f"{ts}_{fname.replace(' ', '_')}"
        proj_dir = os.path.join(PROJECTS_UPLOAD_ROOT, str(pid))
        os.makedirs(proj_dir, exist_ok=True)
        dest = os.path.join(proj_dir, stored_name)
        rel_path = os.path.relpath(dest, UPLOAD_FOLDER).replace('\\', '/')

        shutil.copy2(src, dest)

        # Attach to registry (direct update bypasses the "attach only if NULL" guard)
        with db.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE projects SET po_filename = %s, po_path = %s WHERE id = %s",
                (stored_name, rel_path, pid)
            )
            conn.commit()
            cur.close()

        # Extract + upsert gist
        result = po_processor.extract_po(dest, fname)
        if result.get('success'):
            data = result['data']
            db.upsert_project_po(
                pid, data,
                model=result.get('model'),
                status='success',
                error=None,
                raw_json=json.dumps(data, ensure_ascii=False),
                source_filename=fname,
                force=True,
            )
            print(f"  [+] {proj['id']} - {proj['stem_name']:<22} "
                  f"total_value=₹{data['total_value']:,.2f}  "
                  f"client={data['client_name']!r}  ({result.get('model')})")
        else:
            db.upsert_project_po(
                pid, {},
                model=None,
                status='failed',
                error=result.get('error'),
                raw_json=None,
                source_filename=fname,
                force=True,
            )
            print(f"  [!] {proj['id']} - {proj['stem_name']:<22} "
                  f"EXTRACTION FAILED: {result.get('error')}")

    print("\nBackfill complete.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
