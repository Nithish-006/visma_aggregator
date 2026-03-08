"""
One-time database cleanup script for production DB.
Normalizes case, expands short forms, fixes typos and spacing
for category, project, and client_vendor fields.
"""

import sys
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


def get_conn():
    return mysql.connector.connect(**CONN_CONFIG)


def show_values(cursor, table, col):
    """Show all case-sensitive distinct values for a column"""
    cursor.execute(f"""
        SELECT CAST(TRIM({col}) AS BINARY) as bval, COUNT(*) as cnt
        FROM {table}
        WHERE {col} IS NOT NULL AND TRIM({col}) != ''
        GROUP BY CAST(TRIM({col}) AS BINARY)
        ORDER BY CAST(TRIM({col}) AS BINARY)
    """)
    rows = cursor.fetchall()
    print(f"\n  [{col}] {len(rows)} distinct values:")
    for bval, cnt in rows:
        label = bval.decode('utf-8') if isinstance(bval, bytes) else bval
        print(f"    '{label}' ({cnt})")
    return len(rows)


def show_all():
    conn = get_conn()
    cursor = conn.cursor()
    for table in TABLES:
        print(f"\n{'='*60}")
        print(f"  Table: {table}")
        print(f"{'='*60}")
        for col in ['category', 'project']:
            show_values(cursor, table, col)
    cursor.close()
    conn.close()


def apply_fix(cursor, table, col, old_val, new_val):
    """Apply a case-sensitive fix: match exact old_val, set to new_val"""
    cursor.execute(f"""
        UPDATE {table}
        SET {col} = %s
        WHERE CAST(TRIM({col}) AS BINARY) = CAST(%s AS BINARY)
    """, (new_val, old_val))
    if cursor.rowcount > 0:
        print(f"    '{old_val}' -> '{new_val}': {cursor.rowcount} rows")
        return cursor.rowcount
    return 0


def apply_fix_ci(cursor, table, col, old_val, new_val):
    """Apply a case-insensitive fix: match old_val in any case, set to new_val"""
    cursor.execute(f"""
        UPDATE {table}
        SET {col} = %s
        WHERE UPPER(TRIM({col})) = %s AND CAST(TRIM({col}) AS BINARY) != CAST(%s AS BINARY)
    """, (new_val, old_val.upper(), new_val))
    if cursor.rowcount > 0:
        print(f"    '{old_val}' (any case) -> '{new_val}': {cursor.rowcount} rows")
        return cursor.rowcount
    return 0


def cleanup():
    conn = get_conn()
    cursor = conn.cursor()
    total_fixed = 0

    for table in TABLES:
        print(f"\n{'='*60}")
        print(f"  Cleaning: {table}")
        print(f"{'='*60}")

        # ============================================================
        # STEP 1: Trim whitespace from all columns
        # ============================================================
        print("\n  [Step 1] Trimming whitespace...")
        for col in ['category', 'project', 'client_vendor']:
            cursor.execute(f"""
                UPDATE {table}
                SET {col} = TRIM({col})
                WHERE {col} IS NOT NULL AND {col} != TRIM({col})
            """)
            if cursor.rowcount > 0:
                print(f"    [{col}] trimmed: {cursor.rowcount} rows")
                total_fixed += cursor.rowcount

        # ============================================================
        # STEP 2: UPPERCASE all categories and projects
        # ============================================================
        print("\n  [Step 2] Uppercasing categories & projects...")
        for col in ['category', 'project']:
            cursor.execute(f"""
                UPDATE {table}
                SET {col} = UPPER(TRIM({col}))
                WHERE {col} IS NOT NULL AND {col} != ''
                  AND CAST({col} AS BINARY) != CAST(UPPER(TRIM({col})) AS BINARY)
            """)
            if cursor.rowcount > 0:
                print(f"    [{col}] uppercased: {cursor.rowcount} rows")
                total_fixed += cursor.rowcount

        # ============================================================
        # STEP 3: Fix double spaces in projects
        # ============================================================
        print("\n  [Step 3] Fixing double spaces in projects...")
        # Keep running until no more double spaces
        while True:
            cursor.execute(f"""
                UPDATE {table}
                SET project = REPLACE(project, '  ', ' ')
                WHERE project LIKE '%  %'
            """)
            if cursor.rowcount > 0:
                print(f"    Removed double spaces: {cursor.rowcount} rows")
                total_fixed += cursor.rowcount
            else:
                break

        # ============================================================
        # STEP 4: Expand short forms
        # ============================================================
        print("\n  [Step 4] Expanding short forms...")
        short_forms = {
            # AR -> AMOUNT RECEIVED
            'AR': 'AMOUNT RECEIVED',
            # AT -> AMOUNT TRANSFER
            'AT': 'AMOUNT TRANSFER',
            # MP -> MATERIAL PURCHASE
            'MP': 'MATERIAL PURCHASE',
            # CP -> CONTRACT PAYMENT
            'CP': 'CONTRACT PAYMENT',
            # VE -> VISMA ENG
            'VE': 'VISMA ENG',
            # CAP -> CAPITAL AC
            'CAP': 'CAPITAL AC',
            # SEM (standalone only) -> SEMMOZHI
            'SEM': 'SEMMOZHI',
            # SVM -> SVEM
            'SVM': 'SVEM',
            # A (likely typo for AR) -> AMOUNT RECEIVED
            'A': 'AMOUNT RECEIVED',
        }
        for old_val, new_val in short_forms.items():
            total_fixed += apply_fix_ci(cursor, table, 'project', old_val, new_val)

        # ============================================================
        # STEP 5: Fix typos and misspellings in projects
        # ============================================================
        print("\n  [Step 5] Fixing project typos...")
        project_typos = {
            # Baashyaam variants
            'BASSHYAAM': 'BAASHYAAM',
            'BAASHYAM': 'BAASHYAAM',
            # Joveens variants
            'JOVEEEN': 'JOVEENS',
            'JOVEEN': 'JOVEENS',
            'JOVEENA': 'JOVEENS',
            # Semmozhi variants
            'SEMM': 'SEMMOZHI',
            'SEMOZHI': 'SEMMOZHI',
            # Prominance
            'PROMINANACE': 'PROMINANCE',
            # Sri Ram variants
            'SREE RAM': 'SRI RAM',
            'SRE RAM': 'SRI RAM',
            # Karuvallur
            'KARUVALUR MANDAPAM': 'KARUVALLUR MANDAPAM',
            # Polson -> Polsons (singular to plural)
            'POLSON': 'POLSONS',
            # GHEE FAC -> GHEE FACTORY
            'GHEE FAC': 'GHEE FACTORY',
            'GEE FACTORY': 'GHEE FACTORY',
            # Goole -> Google
            'GOOLE INDIA': 'GOOGLE INDIA',
            # Capital AC typos
            'CCAPITAL AC': 'CAPITAL AC',
            'CA[PITAL AC': 'CAPITAL AC',
            'CAPITAL': 'CAPITAL AC',
            # Labour typos
            'LABOUR ADAVANCE': 'LABOUR ADVANCE',
            'LABOUR ADAVNCE': 'LABOUR ADVANCE',
            'LABOUR PAYMET': 'LABOUR PAYMENT',
            # Samrudha typo
            'SAMRUTHA': 'SAMRUDHA',
            # Purcase typo
            'PURCASE': 'PURCHASE',
            # RN Puram variants
            'RMPURAM': 'RN PURAM',
            'RN PURAM SITE': 'RN PURAM',
            # Visma variants
            'VISMA ENGG': 'VISMA ENG',
            'VISMAASSOCIATES': 'VISMA ASSOCIATES',
            'VISMA ASSOCIATE': 'VISMA ASSOCIATES',
            # Factory AC -> Factory
            'FACTORY AC': 'FACTORY',
            # SAKTHI COLL -> SAKTHI COLLEGE
            'SAKTHI COLL': 'SAKTHI COLLEGE',
            # SITE EXP -> SITE EXPENSES
            'SITE EXP': 'SITE EXPENSES',
            # OFFICE EXP -> OFFICE EXPENSES (standalone in kvb)
            'OFFICE EXP': 'OFFICE EXPENSES',
            # Welding typo
            'WELDING MECHINE SERVICE': 'WELDING MACHINE SERVICE',
            # SVEM Labour typo
            'SVEM LABOUR APYMENT': 'SVEM LABOUR PAYMENT',
            # Tips typo
            'TIPS EXCELLANCE': 'TIPS EXCELLENCE',
            # Chit amount
            'CHIT AMOUNT': 'CHIT',
            # Thamburai typo
            'THAMBURAI RECEIVED AND DEPOSIT': 'THAMBUDURAI RECEIVED AND DEPOSIT',
            # HARI OM
            'HARI OM': 'HARI OM',  # already uppercased, but was HarI OM
            # RCH variants (spacing/separator normalization)
            'RCH - CB': 'RCH CB',
            'RCH-CB': 'RCH CB',
            'RCH CB/': 'RCH CB',
            # RCH CT variants
            'RCH CT EX': 'RCH CT EXT',
            'RCH CTEX': 'RCH CT EXT',
            # RCH Connection Bridge
            'RCH CONNECTION BRIDGE': 'RCH CONNECTING BRIDGE',
            # SABARI variants (kvb)
            'SABARI - RCH': 'SABARI/RCH',
            'SABARI -RCH': 'SABARI/RCH',
            'SABARI-RCH': 'SABARI/RCH',
            'SABARI @RCH': 'SABARI/RCH',
            # OFFICE CHIT variants
            'OFFICE -CHIT': 'OFFICE/CHIT',
            'OFFICE CHIT': 'OFFICE/CHIT',
            # Rajesh/Joveen
            'RAJESH/JOVEEN': 'RAJESH/JOVEENS',
            # SRI RAM /POLSON
            'SRI RAM /POLSON': 'SRI RAM/POLSONS',
            # SVEM/POLSON
            'SVEM/POLSON': 'SVEM/POLSONS',
            # FAC/POLSONS
            'FAC/POLSONS': 'FACTORY/POLSONS',
            # VISMA ENGG-TIPS
            'VISMA ENGG-TIPS': 'VISMA ENG/TIPS',
            # SATHI GEERS
            'SVEM & SATHI GEERS': 'SVEM/SANTHI GEARS',
            # SOUTHERN -FACTORY
            'SOUTHERN -FACTORY': 'SOUTHERN/FACTORY',
            # RCH SABARI
            'RCH SABARI': 'RCH/SABARI',
            # Erection work double space (already handled but just in case)
            'ERECTION WORK FOR BLVL': 'ERECTION WORK FOR BLVL',
            # DESIGN BILLAMOUNT
            'DESIGN BILLAMOUNT': 'DESIGN BILL AMOUNT',
            # GYM@ NAMBIYUR
            'GYM@ NAMBIYUR': 'GYM/NAMBIYUR',
            # SPK @GYM
            'SPK @GYM': 'SPK/GYM',
            # SALARY -> SALARY AC (standalone only)
            'AUG SALARY': 'AUG SALARY',
            # RCH/SRI RAM /SVEM spacing
            'RCH/SRI RAM /SVEM': 'RCH/SRI RAM/SVEM',
            # RCH / SVEM spacing
            'RCH / SVEM': 'RCH/SVEM',
            'RCH /SEMMOZHI': 'RCH/SEMMOZHI',
            'RCH CB /SVEM': 'RCH CB/SVEM',
            'RCHCB /SVEM': 'RCH CB/SVEM',
            # SEM compound forms -> SEMMOZHI
            'SEM/ RCH': 'SEMMOZHI/RCH',
            'SEM/RCH': 'SEMMOZHI/RCH',
            'SEM/ SRI RAM': 'SEMMOZHI/SRI RAM',
            'SEM/SRI RAM': 'SEMMOZHI/SRI RAM',
            'SEM/RCH /SAK': 'SEMMOZHI/RCH/SAKTHI',
            # RCH/PROMINANACE
            'RCH/PROMINANACE': 'RCH/PROMINANCE',
            # RCH/SAKTHI vs SAKTHI/RCH -> normalize to SAKTHI/RCH
            'RCH/SAKTHI': 'SAKTHI/RCH',
            # SVEM /BLVL spacing
            'SVEM /BLVL': 'SVEM/BLVL',
            'SVEM /POLSONS': 'SVEM/POLSONS',
            # BLVL compound case fixes (already uppercased but fix specific patterns)
            'BLVL/RCH CB': 'BLVL/RCH CB',
            'BLVL/SVEM/RCH CB': 'BLVL/SVEM/RCH CB',
            # RCH /SRI RAM
            'RCH /SRI RAM': 'RCH/SRI RAM',
            # SREE RAM -> SRI RAM in kvb
            'SREE RAM': 'SRI RAM',
            'SRE RAM': 'SRI RAM',
            # A3 (likely typo)
            'A3': 'AMOUNT RECEIVED',
            # VISMA ENG BY PREMIER AMOUNT - fix double space
            'VISMA ENG BY PREMIER AMOUNT': 'VISMA ENG BY PREMIER AMOUNT',
            # RCH DINNING HALL -> RCH DINNING (normalize)
            # Keep as-is since it might be different
        }
        for old_val, new_val in project_typos.items():
            if old_val.upper() != new_val:  # Skip no-ops
                total_fixed += apply_fix_ci(cursor, table, 'project', old_val, new_val)

        # ============================================================
        # STEP 6: Fix category values
        # ============================================================
        print("\n  [Step 6] Fixing category values...")
        category_fixes = {
            'CEES AC': 'CESS AC',
            'CESS AC': 'CESS AC',
            'SOUTHERN TOOLS': 'MATERIAL PURCHASE',
        }
        for old_val, new_val in category_fixes.items():
            total_fixed += apply_fix_ci(cursor, table, 'category', old_val, new_val)

        # ============================================================
        # STEP 7: Uppercase vendor case-duplicates only
        # ============================================================
        print("\n  [Step 7] Uppercasing vendor duplicates...")
        cursor.execute(f"""
            UPDATE {table} t
            INNER JOIN (
                SELECT UPPER(TRIM(client_vendor)) as upper_val
                FROM {table}
                WHERE client_vendor IS NOT NULL AND TRIM(client_vendor) != ''
                GROUP BY UPPER(TRIM(client_vendor))
                HAVING COUNT(DISTINCT CAST(TRIM(client_vendor) AS BINARY)) > 1
            ) dup ON UPPER(TRIM(t.client_vendor)) = dup.upper_val
            SET t.client_vendor = UPPER(TRIM(t.client_vendor))
            WHERE CAST(t.client_vendor AS BINARY) != CAST(UPPER(TRIM(t.client_vendor)) AS BINARY)
        """)
        if cursor.rowcount > 0:
            print(f"    Uppercased vendor duplicates: {cursor.rowcount} rows")
            total_fixed += cursor.rowcount

        conn.commit()

    cursor.close()
    conn.close()
    print(f"\n{'='*60}")
    print(f"  Total rows fixed: {total_fixed}")
    print(f"{'='*60}")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fix':
        print("=== BEFORE CLEANUP ===")
        show_all()
        print("\n\n=== APPLYING CLEANUP ===")
        cleanup()
        print("\n\n=== AFTER CLEANUP ===")
        show_all()
    else:
        print("DRY RUN - showing current values. Pass --fix to clean up.\n")
        show_all()
        print("\n\nRun with --fix to apply changes.")
