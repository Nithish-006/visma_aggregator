"""
Regression proof for the Phase-2 allocation reroute.

Every per-project bill report now reads from bill_project_allocations instead
of bill_invoices. While no bill is split, each bill has exactly one allocation
that mirrors it, so the new reads MUST equal the old ones to the paisa. This
script asserts that, three ways:

  1. Global sums (taxable / cgst / sgst / igst / total) over allocations vs bills.
  2. Per-project grouped sums over allocations vs bills (same projects, same money).
  3. The reconciliation (project, vendor) set over allocations vs bills.

Exits non-zero on any mismatch. Run on dev, then prod, BEFORE trusting the push.

Usage (from repo root):
    python scripts/verify_allocation_reads.py                 # uses .env (dev)
    python scripts/verify_allocation_reads.py --env-file .env.prod
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if '--env-file' in sys.argv:
    idx = sys.argv.index('--env-file')
    try:
        env_path = sys.argv[idx + 1]
    except IndexError:
        print("[!] --env-file requires a path, e.g. --env-file .env.prod")
        sys.exit(2)
    if not os.path.exists(env_path):
        print(f"[!] Env file not found: {env_path}")
        sys.exit(2)
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    print(f"[i] Loaded environment from {env_path}")

from database import DatabaseManager

TOL = 0.01


def _f(x):
    return float(x or 0)


def _close(a, b):
    return abs(_f(a) - _f(b)) <= TOL


def main():
    db = DatabaseManager()
    if not db.ensure_connected():
        print("[!] Could not connect to the database.")
        sys.exit(1)

    failures = []

    with db.get_connection() as conn:
        cur = conn.cursor(dictionary=True)

        # 1) Global sums --------------------------------------------------
        cur.execute(
            "SELECT COALESCE(SUM(subtotal),0) t, COALESCE(SUM(total_cgst),0) c, "
            "COALESCE(SUM(total_sgst),0) s, COALESCE(SUM(total_igst),0) i, "
            "COALESCE(SUM(total_amount),0) g FROM bill_invoices"
        )
        b = cur.fetchone()
        cur.execute(
            "SELECT COALESCE(SUM(alloc_taxable),0) t, COALESCE(SUM(alloc_cgst),0) c, "
            "COALESCE(SUM(alloc_sgst),0) s, COALESCE(SUM(alloc_igst),0) i, "
            "COALESCE(SUM(alloc_total),0) g FROM bill_project_allocations"
        )
        a = cur.fetchone()
        for k, label in [('t', 'taxable'), ('c', 'cgst'), ('s', 'sgst'),
                         ('i', 'igst'), ('g', 'total')]:
            if not _close(b[k], a[k]):
                failures.append(f"GLOBAL {label}: bills={_f(b[k])} alloc={_f(a[k])}")
        print(f"[i] Global totals: bills total={_f(b['g'])}, alloc total={_f(a['g'])}")

        # 2) Per-project grouped sums ------------------------------------
        def grouped(table, proj, cols):
            cur.execute(
                f"SELECT COALESCE({proj},'<none>') p, "
                f"COALESCE(SUM({cols[0]}),0) t, COALESCE(SUM({cols[1]}),0) c, "
                f"COALESCE(SUM({cols[2]}),0) s, COALESCE(SUM({cols[3]}),0) i, "
                f"COALESCE(SUM({cols[4]}),0) g FROM {table} GROUP BY COALESCE({proj},'<none>')"
            )
            return {r['p']: r for r in cur.fetchall()}

        gb = grouped('bill_invoices', 'project',
                     ['subtotal', 'total_cgst', 'total_sgst', 'total_igst', 'total_amount'])
        ga = grouped('bill_project_allocations', 'project',
                     ['alloc_taxable', 'alloc_cgst', 'alloc_sgst', 'alloc_igst', 'alloc_total'])

        all_projects = set(gb) | set(ga)
        for p in sorted(all_projects):
            rb, ra = gb.get(p), ga.get(p)
            if rb is None or ra is None:
                failures.append(f"PROJECT '{p}': present in only one side "
                                f"(bills={rb is not None}, alloc={ra is not None})")
                continue
            for k, label in [('t', 'taxable'), ('c', 'cgst'), ('s', 'sgst'),
                             ('i', 'igst'), ('g', 'total')]:
                if not _close(rb[k], ra[k]):
                    failures.append(f"PROJECT '{p}' {label}: bills={_f(rb[k])} alloc={_f(ra[k])}")
        print(f"[i] Compared {len(all_projects)} project group(s).")

        # 3) Reconciliation (project, vendor) set ------------------------
        cur.execute("SELECT project, vendor_name FROM bill_invoices "
                    "WHERE project IS NOT NULL AND project <> ''")
        set_b = {(r['project'], r['vendor_name']) for r in cur.fetchall()}
        cur.execute("SELECT a.project project, bi.vendor_name vendor_name "
                    "FROM bill_project_allocations a JOIN bill_invoices bi "
                    "ON bi.id = a.invoice_id WHERE a.project IS NOT NULL AND a.project <> ''")
        set_a = {(r['project'], r['vendor_name']) for r in cur.fetchall()}
        if set_b != set_a:
            only_b = set_b - set_a
            only_a = set_a - set_b
            failures.append(f"RECONCILE set differs: only-in-bills={sorted(only_b)[:5]} "
                            f"only-in-alloc={sorted(only_a)[:5]}")
        print(f"[i] Reconcile (project,vendor) pairs: bills={len(set_b)}, alloc={len(set_a)}.")

        cur.close()

    if failures:
        print(f"\n[!] {len(failures)} MISMATCH(ES) — the reroute is NOT regression-safe:")
        for f in failures[:40]:
            print(f"      - {f}")
        sys.exit(1)

    print("\n[+] PASS: allocation-based reads match bill-based reads to the paisa.")


if __name__ == '__main__':
    main()
