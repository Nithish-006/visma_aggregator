"""
Map axis_transactions / kvb_transactions `project` values onto the canonical
`projects` registry (display form: "<id> - <STEM_NAME>").

Mapping rules agreed with the user:
  - Stem matches the registry  -> rewrite to "<id> - <STEM_NAME>"
                                  (descriptors/sub-phases collapse to the parent
                                   project, e.g. RCH CB -> 655 - RCH)
  - SEMMOZHI-rooted / SHANMATHI -> 635 - SHANMATHI CONSTRUCTIONS
  - OFFICE* -> 1 - OFFICE EXPENSE,  FACTORY* -> 2 - FACTORY EXPENSE
                                  (GHEE FACTORY is the exception -> 639)
  - Multi-stem values            -> first/primary stem's code
  - Non-project bookkeeping values (AXIS BANK, LABOUR ADVANCE, TDS PAID, ...) -> LEFT AS-IS
  - Project-like names with no registry entry (KARUVALLUR MANDAPAM, ...)      -> LEFT AS-IS

Matching is case-insensitive on TRIM(project); only the exact values listed in
MAPPING are touched. Everything else is left untouched.

Usage:
  python migrate_projects_to_registry.py            # DRY RUN (no writes) + report
  python migrate_projects_to_registry.py --fix      # backup, then apply in a txn
"""

import sys
import json
import datetime
import mysql.connector

CONN_CONFIG = {
    'host': 'yamanote.proxy.rlwy.net',
    'port': 57844,
    'user': 'root',
    'password': 'uxozNadQzagwhWazsWnfDZMSNvKHRwvi',
    'database': 'visma_financial',
    'autocommit': False,
    'use_pure': True,
}

TABLES = ['axis_transactions', 'kvb_transactions']

# Keys are the EXACT current value (as stored, trimmed). Matching is done
# case-insensitively on TRIM(project), so keys are written in their stored form.
MAPPING = {
    # --- SEMMOZHI / SHANMATHI -> 635 ---
    'SEMMOZHI':                         '635 - SHANMATHI CONSTRUCTIONS',
    'SHANMATHI':                        '635 - SHANMATHI CONSTRUCTIONS',

    # --- RCH (+ sub-phases, + multi-stem first=RCH) -> 655 ---
    'RCH':                              '655 - RCH',
    'RCH CB':                           '655 - RCH',
    'RCH CB/CET':                       '655 - RCH',
    'RCH CT':                           '655 - RCH',
    'RCH CT EXT':                       '655 - RCH',
    'RCH SVEM':                         '655 - RCH',

    # --- SVEM (+ multi-stem first=SVEM) -> 649 ---
    'SVEM':                             '649 - SVEM',
    'SVEM SHEETING LABOUR':             '649 - SVEM',

    # --- POLSONS (alias POLSON) -> 647 ---
    'POLSONS':                          '647 - POLSONS',
    'POLSONS,':                         '647 - POLSONS',
    'POLSON DISTILLERY':                '647 - POLSONS',
    'POLSONS TRANSPORT':                '647 - POLSONS',

    # --- MARVEL -> 658 ---
    'MARVEL':                           '658 - MARVEL',
    'MARVEL CASH':                      '658 - MARVEL',
    'MARVEL FOOD':                      '658 - MARVEL',
    'MARVEL CASH PAYMNET':              '658 - MARVEL',

    # --- BLVL -> 652 FABS/BLVL ---
    'BLVL':                             '652 - FABS/BLVL',

    # --- PROMINANCE -> 651 ---
    'PROMINANCE':                       '651 - PROMINANCE',
    'PROMINANCE KALAPATTI':             '651 - PROMINANCE',

    # --- PRAKALATHAN -> 660 ---
    'PRAKALATHAN SITE':                 '660 - SUN ASSOCIATES/PRAKALATHAN',

    # --- NARNE -> 30 ---
    'NARNE HOTELS':                     '30 - NARNE HOTEL/MADIKERI',

    # --- COLORTONE -> 1557 ---
    'COLORTONE GARMENTS P LTD':         '1557 - COLORTONE GARMENTS',

    # --- D PLUS Y -> 1558 ---
    'D PLUS Y':                         '1558 - D PLUS Y',

    # --- SREE DEVI -> 1537 ---
    'SREE DEVI TEXTILE':                '1537 - SREE DEVI',

    # --- GHEE FACTORY -> 639 (exception to FACTORY rollup) ---
    'GHEE FACTORY':                     '639 - GHEE FACTORY',

    # --- FACTORY* -> 2 FACTORY EXPENSE ---
    'FACTORY':                          '2 - FACTORY EXPENSE',
    'FACTORY  FIRE WOOD':               '2 - FACTORY EXPENSE',
    'FACTORY / EB':                     '2 - FACTORY EXPENSE',
    'FACTORY FLOWER':                   '2 - FACTORY EXPENSE',
    'FACTORY MEDICAL EXP':              '2 - FACTORY EXPENSE',
    'FACTORY NEW LABOUR PAYMENT':       '2 - FACTORY EXPENSE',
    'FACTORY POOJA':                    '2 - FACTORY EXPENSE',
    'FACTORY RAJU MEDICAL EXP':         '2 - FACTORY EXPENSE',
    'FACTORY RAJU POLICE STATION EXP':  '2 - FACTORY EXPENSE',
    'FACTORY RENT':                     '2 - FACTORY EXPENSE',
    'FACTORY STAFF RENT':               '2 - FACTORY EXPENSE',
    'FACTORY TEA':                      '2 - FACTORY EXPENSE',

    # --- OFFICE* (+ multi-stem first=OFFICE) -> 1 OFFICE EXPENSE ---
    'OFFICE':                           '1 - OFFICE EXPENSE',
    'OFFICE GST INPUT':                 '1 - OFFICE EXPENSE',
    'OFFICE PRINTER SERVICE':           '1 - OFFICE EXPENSE',
    'OFFICE TDS':                       '1 - OFFICE EXPENSE',
    'OFFICE TOILET CLEANING & WATER':   '1 - OFFICE EXPENSE',
    'OFFICE TRIP ADVANCE':              '1 - OFFICE EXPENSE',
    'OFFICE/TEKLA':                     '1 - OFFICE EXPENSE',
    'OFFICE (SCHOOL FEES)':             '1 - OFFICE EXPENSE',
    'OFFICE RENT':                      '1 - OFFICE EXPENSE',

    # --- id-prefixed formatting drift (id matches registry, just mis-spaced) ---
    '2-FACTORY':                        '2 - FACTORY EXPENSE',
    '659-JAMUNA':                       '659 - JAMUNA',
    '662 INFINIUM':                     '662 - INFINIUM',
    '663-SIRUVANI':                     '663 - SIRUVANI',
    '665-TITAN PAINTS':                 '665 - TITAN PAINTS',

    # --- ambiguous bare names collapsed to canonical (user-approved 2026-06-02) ---
    'KVB':                              '4 - KVB',
    'SRIDHAR SIR':                      '5 - SRIDHAR',
}


def get_conn():
    return mysql.connector.connect(**CONN_CONFIG)


def load_registry(cursor):
    """Return set of valid canonical display strings '<id> - <stem_name>'."""
    cursor.execute("SELECT id, stem_name FROM projects")
    return {f"{pid} - {stem}" for pid, stem in cursor.fetchall()}


def verify_mapping_targets(cursor):
    """Abort if any MAPPING target is not a real registry display value."""
    registry = load_registry(cursor)
    bad = sorted({v for v in MAPPING.values() if v not in registry})
    if bad:
        print("  [ABORT] These mapping targets are NOT in the canonical registry:")
        for b in bad:
            print(f"    - {b!r}")
        return False
    print(f"  [ok] all {len(set(MAPPING.values()))} distinct targets exist in the registry")
    return True


def count_planned(cursor, table):
    """Return list of (old, new, count) for rows that WOULD change."""
    planned = []
    for old, new in MAPPING.items():
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE UPPER(TRIM(project)) = UPPER(%s)
              AND CAST(TRIM(project) AS BINARY) != CAST(%s AS BINARY)
            """,
            (old, new),
        )
        cnt = cursor.fetchone()[0]
        if cnt:
            planned.append((old, new, cnt))
    return planned


def untouched_values(cursor, table):
    """Distinct non-empty project values that the mapping does NOT cover."""
    cursor.execute(
        f"""
        SELECT TRIM(project) AS p, COUNT(*) AS cnt
        FROM {table}
        WHERE project IS NOT NULL AND TRIM(project) != ''
        GROUP BY TRIM(project)
        ORDER BY p
        """
    )
    keys_upper = {k.upper() for k in MAPPING}
    out = []
    for p, cnt in cursor.fetchall():
        if p.upper() not in keys_upper:
            out.append((p, cnt))
    return out


def dry_run():
    conn = get_conn()
    cursor = conn.cursor()
    print("=" * 72)
    print("STEP 0: verify mapping targets against canonical registry")
    print("=" * 72)
    if not verify_mapping_targets(cursor):
        cursor.close(); conn.close()
        sys.exit(1)

    grand = 0
    for table in TABLES:
        print("\n" + "=" * 72)
        print(f"PLANNED CHANGES: {table}")
        print("=" * 72)
        planned = count_planned(cursor, table)
        subtotal = 0
        for old, new, cnt in planned:
            print(f"  '{old}'  ->  '{new}'   ({cnt} rows)")
            subtotal += cnt
        print(f"  -- {subtotal} rows would change in {table}")
        grand += subtotal

        leftover = untouched_values(cursor, table)
        print(f"\n  LEFT UNTOUCHED in {table} ({len(leftover)} distinct values):")
        for p, cnt in leftover:
            print(f"    '{p}' ({cnt})")

    print("\n" + "=" * 72)
    print(f"TOTAL rows that would change: {grand}")
    print("Run with --fix to back up and apply.")
    print("=" * 72)
    cursor.close()
    conn.close()


def backup(cursor):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"project_backup_{stamp}.json"
    data = {}
    for table in TABLES:
        cursor.execute(f"SELECT id, project FROM {table}")
        data[table] = [{"id": rid, "project": proj} for rid, proj in cursor.fetchall()]
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [backup] wrote {fname} "
          f"({sum(len(v) for v in data.values())} rows across {len(TABLES)} tables)")
    return fname


def apply_fix():
    conn = get_conn()
    cursor = conn.cursor()

    print("=" * 72)
    print("STEP 0: verify mapping targets against canonical registry")
    print("=" * 72)
    if not verify_mapping_targets(cursor):
        cursor.close(); conn.close()
        sys.exit(1)

    print("\nSTEP 1: backup current (id, project) for both tables")
    backup(cursor)

    print("\nSTEP 2: apply mapping")
    total = 0
    for table in TABLES:
        print(f"\n  -- {table} --")
        sub = 0
        for old, new in MAPPING.items():
            cursor.execute(
                f"""
                UPDATE {table}
                SET project = %s
                WHERE UPPER(TRIM(project)) = UPPER(%s)
                  AND CAST(TRIM(project) AS BINARY) != CAST(%s AS BINARY)
                """,
                (new, old, new),
            )
            if cursor.rowcount > 0:
                print(f"    '{old}' -> '{new}': {cursor.rowcount} rows")
                sub += cursor.rowcount
        print(f"    subtotal: {sub} rows")
        total += sub

    conn.commit()
    print(f"\n  COMMITTED. Total rows updated: {total}")
    cursor.close()
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fix':
        apply_fix()
    else:
        dry_run()
