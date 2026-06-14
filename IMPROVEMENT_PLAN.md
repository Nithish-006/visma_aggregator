# Bill / PO Extraction — Improvement & Validation Plan

_Last updated: 2026-06-15. Owner: team@cogninest.ai._

## Status (2026-06-15)

Most of this plan has shipped. **The one remaining item is A2 (two-pass
self-consistency)** — see the marker in §A2 below.

| Item | Status | Notes |
|------|--------|-------|
| **A1** Reconciliation layer | ✅ Done | `extraction_validator.py`; persisted to `validation_status/diff/notes`; wired into insert + update paths. **Retuned on real data** — see "Tolerance, as shipped" below. |
| **A2** Two-pass self-consistency | ⏳ **PENDING** | Not built. The only open item. |
| **A3** Multi-page rasterization | ✅ Done | `extract_from_pdf` rasterizes pages via PyMuPDF (200 DPI, ordered), falls back to raw PDF. `PyMuPDF` in `requirements.txt`. |
| **A4** Review-queue UI | ✅ Done | Amber/green Check badge + notes tooltip, "Flagged only" filter, "Run Validation" button — both bill & sales processors. |
| **B** Parallel bulk | ✅ Done | Bounded pool (`MAX_CONCURRENT_UPLOADS=5`) in `bill_processor.js` + `sales_processor.js`, order-preserving. |
| **C1** Tier-1 re-check | ✅ Done | Two forms: standalone `validate_existing_bills.py` (`--prod/--dry-run`) and in-app `POST /api/bills/revalidate` (`db.revalidate_existing_bills()`). |
| **C2/C3** Re-extract & correct | ✅ Done | In-app, server-side (PDFs live only on the Railway container): `POST /api/bills/reprocess/<id>` + `/api/sales/reprocess/<id>`. Re-extracts via the improved pipeline, returns an old→new diff, applies **only when the re-extraction reconciles** (clean-only), and **always preserves the `project` tag**. Bulk via the frontend pool. |

**Tolerance, as shipped (A1 retuned):** the first prod dry-run flagged 80% — too
noisy. Two checks were dropped/fixed: (1) the line-`amount`-sum-vs-total check was
removed (the "amount" column is the pre-tax value in this data, so it was off by the
tax on every clean bill); (2) `line_tax_sum` was made **magnitude-aware** so it no
longer false-positives on correctly-handled freight (header tax legitimately includes
GST charged on the freight base) and fires only when a freight *base* lands in tax.
Final live rate: **~18% flagged** (48/234 purchase, 2/38 sales). Header-identity
alone surfaces the genuinely-wrong totals. `DEFAULT_TOLERANCE = ₹2`, configurable.

**Prod facts:** data is in the `visma_financial` DB (not `railway`); source PDFs are
on the Railway container volume at `/app/uploads` only — reprocessing must run
server-side. Validation columns auto-added via `ensure_validation_columns()` on page
load. `.env.prod` (gitignored) holds the Railway public-proxy creds for the C1 script.

---

## Context & Goal

The extraction pipeline (`bill_processor.py`, `po_processor.py`) uses Gemini 3 Flash
vision (paid tier now active, ₹1000 credit). Two recurring accuracy problems:

1. **Other charges (freight / packing / loading) get swept into the GST columns**
   (`total_cgst` / `total_sgst` / `total_igst`), inflating tax.
2. **Wrong total values**, mostly on **multi-page bills** — the model picks a
   page-1 subtotal instead of the final consolidated total on the last page.

Goal: get effective accuracy to ~100% with **minimal manual intervention** — not by
swapping the model, but by making the system **catch its own mistakes** and surface
only the few bad ones for a quick human glance.

> Decision already taken: **MarkItDown is NOT used** — it flattens table layout and
> would make both bugs worse (see research notes / memory
> `bill-extraction-markitdown-rejected`). Vision stays the extractor.

---

## Workstream A — Accuracy (do FIRST; no billing dependency)

### A1. Reconciliation layer (the core fix)

Add a pure-Python validator run **after** every extraction, before/at DB save. No
new dependencies. Lives in a new `extraction_validator.py`, called from
`bill_processor.process_bill_file` and the sales path.

**Checks (all in INR, with a small tolerance — propose ₹2 to absorb rounding):**

1. **Header identity:**
   `total_amount ≈ subtotal(taxable) + total_cgst + total_sgst + total_igst + other_charges + round_off`
   - Fails when freight is double-counted, dropped, or a wrong total was read.
2. **Line-items vs header:**
   - `sum(line_items.taxable_value) ≈ subtotal`
   - `sum(line_items.cgst_amount) ≈ total_cgst` (same for sgst / igst)
   - `sum(line_items.amount) ≈ total_amount − other_charges` (approx)
3. **Per-line GST-rate sanity (catches the freight-in-GST bug directly):**
   - For each line: `cgst_amount ≈ taxable_value × cgst_rate / 100`.
   - A freight charge misclassified as tax won't satisfy a clean rate → flagged.
4. **Sign / range sanity:** no negative taxes; `total_amount > 0`; tax ≤ subtotal.

**Output:** a `validation` block attached to each result:
```json
{ "status": "ok" | "review", "score": 0-100,
  "failures": ["header_identity off by 1180.00", "cgst sum mismatch", ...] }
```

**Persist it:** add columns to `bill_invoices` (and the sales invoices table):
- `validation_status` ENUM('ok','review') DEFAULT 'review'
- `validation_diff` DECIMAL(12,2)  — the header-identity gap
- `validation_notes` TEXT          — human-readable failure list
Migration: additive `ALTER TABLE`, safe on existing rows (default 'review' until
re-checked). Script: `migrations/add_validation_columns.py`.

### A2. Two-pass self-consistency on flagged bills  ⏳ **PENDING — the only open item**

> This is the single remaining piece of the plan. Everything else (A1, A3, A4, B,
> C1, C2/C3) has shipped. Pick this up next.

When A1 returns `review`, automatically re-extract **once** (retry same model, or
fall to `gemini-2.5-flash`) and diff the two results:
- Both passes agree **and** reconcile → auto-promote to `ok`.
- They disagree or still fail → keep `review`, store both for the UI.

Keeps cost near-zero (only the ~10–20% flagged bills get a 2nd call).

**Build notes (what now exists to lean on):**
- The reconciliation verdict is already computed in `process_bill_file`
  (`result['validation']`) and by `validate_extraction` / `validate_db_row`.
- A working re-extract-and-diff path already exists: `_reprocess_invoice` in
  `app.py` re-runs the pipeline and produces an old→new diff. A2 is the *automatic*
  variant — trigger a second pass at extraction time when the first is `review`,
  rather than on a user click.
- Natural home: inside `process_bill_file` (or its callers) — if `validation.status
  == 'review'`, run one more extraction, compare the two, and promote to `ok` only on
  agreement + reconciliation. Store both passes for the A4 review modal when they
  disagree.
- Cost stays bounded because only the ~18% flagged bills incur the 2nd call; respect
  the same paid-tier headroom as the B concurrency cap.

### A3. Multi-page handling (fixes the page-1-subtotal bug)

Instead of handing Gemini raw PDF bytes, **rasterize each page to an ordered image
sequence** and pass them in page order with an explicit "page N of M; totals come
from the LAST page" instruction.

- Use **PyMuPDF (`pymupdf` / `fitz`)** at ~200 DPI — pip-only, **no system
  dependencies** (important: works on Railway without poppler). Add to
  `requirements.txt`.
- Change `extract_from_pdf` to render `page.get_pixmap(dpi=200)` → list of image
  Parts, in order, then the prompt.
- Keep the current single-call consolidation logic; we're only improving the input
  representation. The "ONE invoice, merge line items, final totals from last page"
  prompt rules (RULE 3) stay.

### A4. UI: review queue

In `templates/bill_processor.html` + `static/bill_processor.js` and the stored-bills
list:
- Badge bills with `validation_status = 'review'` (amber) vs `ok` (green).
- Filter/sort to show `review` first; show `validation_notes` on the row.
- This is what delivers "minimal manual intervention" — you confirm only the amber
  minority, not all 200.

**A acceptance:** a known-bad multi-page bill and a known freight-in-GST bill both
get flagged `review`; clean bills stay `ok`; flagged count is small.

---

## Workstream B — Speed (parallel bulk processing; needs paid tier — now READY)

Current bulk flow is **sequential**: `static/bill_processor.js:1279`
`for (const file of fileQueue) { await uploadAndProcessFile(file) }` — each PDF waits
for the previous full Gemini round-trip. 5 PDFs ≈ 5× one call.

**Change:** process with a bounded concurrency pool (e.g. **4–5 in flight**) instead
of one-at-a-time.
- Frontend: replace the serial `for…await` with a worker-pool pattern (N promises
  draining the queue), preserving per-file progress logs and the results order.
- Respect paid-tier limits — cap at 5 concurrent; well under Tier-1 RPM, leaves room
  for the A2 re-extraction calls.
- Keep each file's existing `/api/bills/process` call as-is (server already
  stateless per file). No server change strictly required; optional: a batch
  endpoint later.

**B acceptance:** 5 mixed PDFs finish in ≈ the time of the slowest one (~10–12s),
not the sum (~60s). No 429s in logs.

---

## Workstream C — Validate the existing ~200 bills

We have ~200 already-processed bills in the DB and their source PDFs in Railway block
storage (`UPLOAD_FOLDER`). Validate in two tiers.

### Mapping a DB row → its PDF
- DB stores original `filename`; the file on disk is `bill_{timestamp}_{filename}`
  (purchase) / `sales_{timestamp}_{filename}` (sales). Locate via glob
  `bill_*_{filename}` — same approach as the serve route (`app.py:3705`).
- **Risk:** duplicate original filenames → multiple matches. Disambiguate by
  matching invoice_number / date / total against the file's extraction, or by
  nearest timestamp. Log unresolved ones for manual mapping.

### C1. Tier 1 — arithmetic re-check (no Gemini, instant, free)
Script `validate_existing_bills.py`:
- Read every row from `bill_invoices` (+ `bill_line_items`) and the sales tables.
- Run the **A1 reconciliation checks** on the stored numbers.
- Write `validation_status / validation_diff / validation_notes` back to each row.
- Emit a report: `validation_report_tier1.xlsx` — columns: invoice no, vendor,
  total, header-gap, failure list, PDF found (Y/N).
- **This alone surfaces every internally-inconsistent bill** (freight-in-GST and
  most wrong-totals break the identity).

### C2. Tier 2 — re-extract & diff against source PDF (Gemini, ~₹160 total)
For bills that (a) failed Tier 1, **or** (b) are multi-page (highest-risk group):
- Re-run the **improved** A3 pipeline on the stored PDF.
- Diff re-extracted vs stored values field-by-field (totals, each tax, line count).
- Classify: `confirmed_ok` / `auto-correctable` (propose new values) /
  `needs_human`.
- Report `validation_report_tier2.xlsx` with old vs new side by side and a
  one-click "accept new values" path (or a SQL update script for approved rows).
- Cost: 200 × ~₹0.8 ≈ **₹160** even if we re-extract *all* of them; Tier-2-on-
  flagged-only is far less. Trivial against the ₹1000 credit.

### C3. Correction
- For `auto-correctable` rows the user approves, update the DB (and re-derive any
  project summaries that depend on totals).
- For `needs_human`, list them in the A4 review queue.

**C acceptance:** every one of the 200 bills ends in a known state — `ok`,
`corrected`, or `needs_human` — with a report the user can audit. No silent passes.

---

## Sequencing

Original plan (all done except A2): A1+A3 → C1 → A4 → C2/C3 → B.

**Remaining: A2 only.** It builds directly on the shipped pieces (the validation
verdict and the `_reprocess_invoice` re-extract/diff path already exist) — see the
build notes in §A2.

---

## New dependencies
- `pymupdf` (PDF→image rasterization for A3). Pip-only, no system libs — Railway-safe.

## Risks / watch-outs
- **Volume persistence:** confirm Railway volume is mounted at `UPLOAD_FOLDER` and
  the original PDFs are actually present (not just temp-and-deleted). Spot-check a
  few before C2.
- **Duplicate filenames** when mapping DB→PDF (see C mapping note).
- **Tolerance tuning:** ₹2 may be too tight/loose for some vendors' rounding — make
  it configurable; review the first Tier-1 report before trusting thresholds.
- **Sales vs purchase vs PO:** A/C cover purchase + sales invoices. POs
  (`po_processor.py`) use a different "gist" shape — apply a lighter total-only
  reconciliation there if needed (separate, lower priority).

## Cost summary
- Ongoing extraction: ~₹0.8/bill; your volume ≈ 40 bills/mo ⇒ **~₹30–50/mo**.
- One-time validation of 200 bills (Tier 2, worst case all re-extracted): **~₹160**.
- Comfortably inside the ₹1000 credit.
