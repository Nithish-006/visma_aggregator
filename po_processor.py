# ============================================================================
# PROJECT PO PROCESSOR MODULE - Gemini Vision AI Integration
# ============================================================================
# Extracts the *gist* of a project Purchase Order (the figures that matter:
# PO number, date, client, and the grand-total project value) from a PDF or
# image using Google Gemini, with the same model-fallback chain as
# bill_processor.py.
#
# Unlike invoices (one per page), a project PO is ONE document that may span
# several pages, with the consolidated grand total on the LAST page. So we
# extract the whole document in a single call and ask for the final totals.
# ============================================================================

import os

from google.genai import types
from PIL import Image

# PO extraction reuses bill_processor's hardened extraction runner wholesale:
# the verified model-fallback chain (GEMINI_MODELS), multi-key round-robin,
# per-call timeout, transient-overload backoff, and the key-specific-404
# failover fix all live there. Importing it means PO and bill extraction can
# never again drift apart (this module previously pinned nonexistent models and
# used a SINGLE, now-banned API key with no rotation, so PO extraction failed
# 100% of the time). See bill_processor.GEMINI_MODELS for the chain rationale.
from bill_processor import run_model_chain, get_gemini_api_keys

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}

# ----------------------------------------------------------------------------
# PO extraction prompt — minimal "gist" only.
# ----------------------------------------------------------------------------
PO_EXTRACTION_PROMPT = """
You are an expert at reading Purchase Orders (POs) for a structural-steel / civil
construction contractor in India. You are given a SINGLE purchase order document
(it may span multiple pages). Extract ONLY the high-level gist of the PO — do NOT
list individual line items.

WHO IS WHO (important):
- "Invoice To" / "Bill To" / "To" / "Buyer" / "Customer" is the CLIENT who placed
  the order. Put that party's name in "client_name".
- "Supplier (Bill from)" is the contractor receiving the order (usually VISMA
  ASSOCIATES). Do NOT use the supplier as the client.

WHICH TABLE DEFINES THE PROJECT VALUE (critical — read carefully):
- A single PO often contains MORE THAN ONE table. You must tell two kinds apart:
    1. The ORDER / WORK ORDER table — lists the actual scope of work or goods being
       ordered (Design/Supply/Fabrication/Roofing rows, etc.) and ends in a
       "Total Amount" / "Grand Total". THIS table defines the project value.
    2. A PAYMENT SCHEDULE / PAYMENT PLAN table — describes only HOW the amount will
       be settled (instalments, or just the part routed through the bank). Its
       total is often LOWER than the order total because a portion is paid
       separately (e.g. in cash) and is intentionally left out of the schedule.
- ALWAYS take total_value, taxable_value, total_tax and line_items from the
  ORDER / WORK ORDER table. NEVER take any of them from a payment schedule.
- If two tables exist and their totals differ, the ORDER table's (higher,
  full-scope) total is the correct project value. Do NOT pick the smaller
  payment-schedule figure — that understates the project.

GRAND TOTAL (from the ORDER / WORK ORDER table only):
- The PO may have per-page subtotals. Return the FINAL CONSOLIDATED figure of the
  ORDER table (typically its "Total Amount" / "Grand Total" line):
    * total_value = the full ordered value from the ORDER table.
        - If that table's grand total already INCLUDES taxes (CGST/SGST/IGST),
          use that tax-inclusive figure.
        - If taxes are shown as "extra"/separate (e.g. a note like "18% Tax
          Extra") and NO tax-inclusive grand total is printed, use the table's
          stated "Total Amount" as total_value as-is (do NOT gross it up, and do
          NOT fall back to a lower payment-schedule total).
    * taxable_value = the sum of taxable amounts BEFORE tax in the ORDER table.
    * total_tax     = total of CGST + SGST + IGST shown on the ORDER table
                      (0 if tax is only noted as a "% extra" with no figure).

LINE ITEMS (capture the core breakdown — keep it lean):
- Return one entry per distinct scope/goods row in the ORDER / WORK ORDER table
  (NEVER rows from a payment schedule), in "line_items".
- For each row capture ONLY these core fields: description, quantity, unit, rate, amount.
- description: a SHORT core name of the item/scope (e.g. "MS Channel 75x40",
  "Fabrication & erection of steel structure"). Do NOT copy long specifications,
  HSN codes, dimensions tables, or multi-line notes — just enough to identify the
  row. Trim to a concise phrase to save space.
- quantity / rate / amount: plain numbers (strip commas & symbols). 0 if absent.
- unit: short unit string (e.g. "MT", "Kg", "Nos", "Sqft", "Lot"), "" if absent.
- If the PO has no itemised table (e.g. a lump-sum scope), return a single row
  summarising the scope with its amount, or an empty list if truly none.

RULES:
1. Numbers: strip commas and currency symbols, return plain numbers
   (23,25,190.00 -> 2325190.00). Use 0 if genuinely absent.
2. po_date: format as DD-MMM-YYYY (e.g. 16-Mar-2026). Empty string if absent.
3. line_item_count: the number of rows in line_items.
4. payment_terms: a short single-line summary of the payment terms / schedule if
   present (e.g. "60% with PO, 35% for erection, 5% after completion"). If the PO
   indicates part of the value is settled outside the bank / in cash, you may note
   that here (e.g. "bank ~23L per schedule, balance in cash") — but this does NOT
   change total_value, which stays the full ORDER-table total. Else "".
5. Text fields absent -> "".  Numeric fields absent -> 0.
6. currency: the ISO-ish code, default "INR".

Return ONLY valid JSON in EXACTLY this structure (no markdown, no commentary):

{
  "po_number": "",
  "po_date": "",
  "client_name": "",
  "currency": "INR",
  "taxable_value": 0,
  "total_tax": 0,
  "total_value": 0,
  "amount_in_words": "",
  "line_item_count": 0,
  "payment_terms": "",
  "line_items": [
    {"description": "", "quantity": 0, "unit": "", "rate": 0, "amount": 0}
  ]
}
"""


def _normalize_po_data(data):
    """Coerce extracted values into the gist shape with safe types."""
    def num(v):
        try:
            if isinstance(v, str):
                v = v.replace(',', '').replace('₹', '').strip()
                if v == '':
                    return 0.0
            return float(v)
        except (ValueError, TypeError):
            return 0.0

    def text(v):
        return (str(v).strip() if v is not None else '')

    # Core line-item breakdown — keep only the 5 fields we surface, drop noise.
    items = []
    raw_items = data.get('line_items')
    if isinstance(raw_items, list):
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            desc = text(it.get('description'))
            row = {
                'description': desc,
                'quantity': num(it.get('quantity')),
                'unit': text(it.get('unit')),
                'rate': num(it.get('rate')),
                'amount': num(it.get('amount')),
            }
            # Skip empty placeholder rows (no description and no amount).
            if desc or row['amount']:
                items.append(row)

    return {
        'po_number': text(data.get('po_number')),
        'po_date': text(data.get('po_date')),
        'client_name': text(data.get('client_name')),
        'currency': text(data.get('currency')) or 'INR',
        'taxable_value': num(data.get('taxable_value')),
        'total_tax': num(data.get('total_tax')),
        'total_value': num(data.get('total_value')),
        'amount_in_words': text(data.get('amount_in_words')),
        # Count reflects the rows we actually captured.
        'line_item_count': len(items) or int(num(data.get('line_item_count'))),
        'payment_terms': text(data.get('payment_terms')),
        'line_items': items,
    }


def _build_contents(file_path, ext):
    """Build the Gemini `contents` payload for the whole document."""
    if ext == '.pdf':
        with open(file_path, 'rb') as f:
            pdf_bytes = f.read()
        return [
            types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf'),
            PO_EXTRACTION_PROMPT,
        ]
    # image
    img = Image.open(file_path)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')
    return [img, PO_EXTRACTION_PROMPT]


def extract_po(file_path, filename=None):
    """
    Extract the gist of a project PO from a PDF or image file.

    Returns a dict:
      { 'success': True,  'data': <normalized gist>, 'model': '<display name>' }
      { 'success': False, 'error': '<message>' }
    """
    filename = filename or os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ({'.pdf'} | IMAGE_EXTENSIONS):
        return {
            'success': False,
            'error': 'Auto-extraction supports PDF/image POs only — enter the '
                     'value manually for this file type.',
        }

    if not os.path.exists(file_path):
        return {'success': False, 'error': f'File not found: {file_path}'}

    if not get_gemini_api_keys():
        return {'success': False,
                'error': 'GEMINI_API_KEY not found in environment variables'}

    try:
        contents = _build_contents(file_path, ext)
    except Exception as e:
        return {'success': False, 'error': f'Could not read file: {e}'}

    # Delegate to bill_processor's hardened runner: verified model chain,
    # multi-key round-robin with per-key-404 failover, timeout and backoff.
    # It returns already-parsed JSON (run in JSON mode), which we normalize into
    # the PO gist shape.
    data, model_name, last_error = run_model_chain(
        contents, label=f" for PO {filename}")

    if data is not None:
        try:
            gist = _normalize_po_data(data)
        except Exception as e:
            return {'success': False, 'error': f'Could not normalize PO data: {e}'}
        print(f"[+] {model_name} extracted PO: total_value={gist['total_value']}, "
              f"client={gist['client_name']!r}")
        return {'success': True, 'data': gist, 'model': model_name}

    print("[!] All Gemini models failed for PO extraction")
    return {'success': False, 'error': last_error or 'All models failed'}
