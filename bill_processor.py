# ============================================================================
# BILL PROCESSOR MODULE - Gemini Vision AI Integration
# ============================================================================
# Extracts structured data from invoice images/PDFs using Google Gemini API
# with intelligent fallback chain for reliability.
# ============================================================================

import os
import json
import re
from io import BytesIO
from datetime import datetime

from google import genai
from google.genai import types
from PIL import Image
from PyPDF2 import PdfReader

from extraction_validator import validate_extraction

# Model configuration - Gemini models via direct API (in priority order).
# All Flash-tier: fast, cheap, and strong at invoice OCR + table extraction.
# gemini-3-pro is intentionally excluded — it's a reasoning model (slow + costly)
# with no accuracy edge on this OCR/extraction task, and falling through to it on
# every free-tier throttle was the main source of latency.
GEMINI_MODELS = [
    "gemini-3-flash",        # primary: best vision quality at flash speed, cheaper than 3.5
    "gemini-2.5-flash",      # fallback: proven on GST tables
    "gemini-2.5-flash-lite", # last resort: cheap/fast, lower accuracy
]
# Note: gemini-3.5-flash is the newest/most capable Flash but costs more than
# gemini-3-flash with no meaningful accuracy edge on this OCR/extraction task,
# so it is intentionally NOT in the chain. (Display name kept below in case it
# is reintroduced.)

# Extraction prompt
EXTRACTION_PROMPT = """
You are an expert invoice data extractor. Analyze this GST invoice and extract ALL information.

CRITICAL TASK - LINE ITEMS EXTRACTION:
The invoice has a table with columns like "Description of Goods", "HSN/SAC", "Quantity", "Rate", "Amount" etc.
You MUST extract EVERY row from this table. Each product/item is one line_item.

Example items you might see:
- Steel products: "CHANNEL 75X40", "MS PIPE 25X25", "MS ANGLE 50X50"
- Paint products: "Apcomin QD Grey Primer 20L", "NC Thinner", "Enamel Paint"
- Construction materials with specifications

═══════════════════════════════════════════════════════════════════════
RULE 1 — INVOICE DATE (capture it correctly, EVERY time):
═══════════════════════════════════════════════════════════════════════
- "invoice_date" is the date the INVOICE itself was raised. It is printed near
  the invoice number, usually labelled "Invoice Date", "Date", "Dated",
  "Bill Date", "Inv Date", or "Invoice Dt".
- DO NOT confuse it with any other date on the bill. These are DIFFERENT dates
  and must NOT be used as invoice_date:
    * E-Way Bill date  -> eway_bill_date
    * Acknowledgement (Ack) date -> ack_date
    * Due date / payment due date -> ignore
    * LR date / transport / dispatch date -> transport.lr_date
    * Delivery note date, PO/order date, challan date -> ignore for invoice_date
- The invoice ALWAYS has an invoice date. Look carefully (top-right, header box,
  or beside the invoice number). NEVER leave invoice_date blank if any invoice/bill
  date is visible anywhere on the document.
- Output format: DD-MMM-YYYY (e.g. 30-Dec-2025). Convert any input format
  (30/12/2025, 2025-12-30, 30.12.25) to this. Day-first when ambiguous (Indian invoices).

═══════════════════════════════════════════════════════════════════════
RULE 2 — TAXES vs OTHER CHARGES (freight / shipping / packing must NOT pollute GST):
═══════════════════════════════════════════════════════════════════════
- total_cgst, total_sgst, total_igst must contain ONLY genuine GST tax amounts
  (the CGST / SGST / IGST tax lines). Nothing else.
- Freight, Shipping, Transport, Packing, Forwarding, Loading/Unloading, Handling,
  Insurance, Courier, P&F, and similar service/logistics charges are NOT taxes.
  Some invoices sloppily print these charges INSIDE or BESIDE the CGST/SGST/IGST
  block (in the tax area, between the tax rows, or in a tax column). IGNORE their
  placement — they are charges, never tax.
    * Put EVERY such charge as its own entry in "other_charges"
      (description = the charge name as printed, amount = its value, hsn_code if shown).
    * These amounts must be EXCLUDED from total_cgst / total_sgst / total_igst.
- So: read the tax block carefully. If a "CGST" or "IGST" figure is actually the
  tax ON freight, keep that tax in the tax totals, but the freight BASE goes to
  other_charges. Real GST tax -> tax totals. Charge values -> other_charges.
- Sanity check before you answer: total_amount should ≈ taxable_amount
  + total_cgst + total_sgst + total_igst + (sum of other_charges) + round_off.
  If your CGST/IGST looks inflated, you probably swept a freight/shipping charge
  into it by mistake — move it to other_charges and recompute.

═══════════════════════════════════════════════════════════════════════
RULE 3 — MULTI-PAGE PDFs: CONTINUATION PAGES vs. DUPLICATE COPIES
═══════════════════════════════════════════════════════════════════════
A multi-page PDF is ONE of two things. Decide which BEFORE extracting:

(A) CONTINUATION PAGES — one long invoice split across pages because the goods
    table did not fit on a single page. The pages carry DIFFERENT goods rows and
    the totals appear only at the very end.

(B) DUPLICATE / TRIPLICATE COPIES — the SAME invoice printed several times in one
    PDF. Indian GST invoices are commonly issued in copies, each page marked with
    labels like "ORIGINAL FOR RECIPIENT / BUYER", "DUPLICATE FOR TRANSPORTER",
    "TRIPLICATE FOR SUPPLIER", or simply "Original Copy", "Duplicate Copy",
    "Triplicate Copy", "Extra Copy". These copies are IDENTICAL — same invoice
    number, same date, same line items, same totals — just reprinted.

HOW TO TELL THEM APART:
- Same invoice number + same date + same total_amount repeating on a later page,
  or an explicit "Duplicate/Triplicate/Original for ..." copy label  -> these are
  COPIES (case B), NOT continuation.
- A later page that continues the goods table with NEW rows and no copy label,
  with totals only at the end  -> continuation (case A).

WHAT TO DO:
- Case A (continuation): read and COMBINE all pages into ONE invoice. Merge the
  goods rows from EVERY page into one continuous line_items list, in order
  (continuation pages often repeat the column header / invoice header — do NOT
  duplicate header rows, but DO capture every distinct goods row). Take the FINAL
  CONSOLIDATED totals (taxable_amount, total_cgst/sgst/igst, round_off,
  total_amount, amount_in_words) from the LAST page — never a page-1 subtotal.
- Case B (copies): process ONLY the ORIGINAL copy (prefer the page marked
  "Original"; if none is marked, use the first occurrence). EXTRACT IT ONCE.
  IGNORE the duplicate and triplicate pages entirely. Do NOT merge their line
  items and do NOT add up their totals — the duplicates are the SAME bill, so
  aggregating them would double/triple the amounts. The result must reflect a
  single invoice's values, exactly as if only the original page were uploaded.
- In BOTH cases: header fields (invoice number, date, vendor, buyer) come from
  where they appear (usually page 1). Return a SINGLE invoice object, not one per page.

GENERAL INSTRUCTIONS:
1. Extract ALL line items - do NOT skip any row from the goods table (across all pages)
2. For numeric values: remove commas, convert to numbers (47,542.20 -> 47542.20)
3. Dates: use DD-MMM-YYYY format (30-Dec-2025)
4. Empty/missing fields: use "" for text, 0 for numbers
5. Capture the EXACT product description as written on the invoice

Return ONLY valid JSON in this exact structure (no markdown, no explanation):

{
  "invoice_header": {
    "invoice_number": "",
    "invoice_date": "",
    "irn": "",
    "ack_number": "",
    "ack_date": "",
    "eway_bill_number": "",
    "eway_bill_date": "",
    "delivery_note": "",
    "payment_terms": "",
    "reference_number": "",
    "buyer_order_number": "",
    "dispatch_doc_number": "",
    "destination": ""
  },
  "vendor": {
    "name": "",
    "address": "",
    "gstin": "",
    "pan": "",
    "state": "",
    "state_code": "",
    "phone": "",
    "email": "",
    "bank_name": "",
    "bank_account": "",
    "bank_ifsc": "",
    "bank_branch": ""
  },
  "buyer": {
    "name": "",
    "address": "",
    "gstin": "",
    "state": "",
    "state_code": "",
    "phone": ""
  },
  "ship_to": {
    "name": "",
    "address": "",
    "gstin": "",
    "state": "",
    "state_code": ""
  },
  "line_items": [
    {
      "sl_no": 1,
      "description": "",
      "hsn_sac_code": "",
      "quantity": 0,
      "uom": "",
      "rate_per_unit": 0,
      "rate_incl_tax": 0,
      "discount_percent": 0,
      "discount_amount": 0,
      "taxable_value": 0,
      "cgst_rate": 0,
      "cgst_amount": 0,
      "sgst_rate": 0,
      "sgst_amount": 0,
      "igst_rate": 0,
      "igst_amount": 0,
      "gst_percent": 0,
      "amount": 0
    }
  ],
  "other_charges": [
    {
      "description": "",
      "hsn_code": "",
      "amount": 0
    }
  ],
  "taxes": {
    "subtotal": 0,
    "taxable_amount": 0,
    "total_cgst": 0,
    "total_sgst": 0,
    "total_igst": 0,
    "total_tax": 0,
    "round_off": 0,
    "total_amount": 0,
    "amount_in_words": ""
  },
  "transport": {
    "vehicle_number": "",
    "transport_mode": "",
    "transporter_name": "",
    "transporter_id": "",
    "lr_number": "",
    "lr_date": ""
  }
}
"""


def get_gemini_client():
    """Get configured Gemini client"""
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables")
    return genai.Client(api_key=api_key)


def clean_json_response(response_text):
    """Clean up response - remove markdown code blocks if present"""
    text = response_text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    return text


# Generation config shared by every extraction call.
# - response_mime_type='application/json' constrains the model to emit a single
#   valid JSON object (no markdown fences, no prose), which is the single biggest
#   guard against the "Expecting value: line 1 column 1 (char 0)" parse failure.
# - max_output_tokens is set high because gemini-3-flash / 2.5-flash are THINKING
#   models: with the default (~8k) budget, internal reasoning can consume the
#   whole allowance and leave an EMPTY text part -> response.text == "" -> the
#   char-0 error. A generous budget leaves room for both thinking and the JSON.
# - temperature 0 makes extraction deterministic and less prone to stray tokens.
GENERATION_CONFIG = types.GenerateContentConfig(
    response_mime_type='application/json',
    temperature=0.0,
    max_output_tokens=65535,
)


def extract_response_text(response):
    """
    Pull the text out of a Gemini response, tolerating empty/blocked candidates.

    `response.text` raises (or returns '') when the candidate has no text part —
    e.g. a safety block, or a thinking model that spent its whole token budget on
    reasoning. Returns (text, reason): text is None/'' when nothing usable came
    back, and reason explains why (finish_reason / block) for the logs.
    """
    try:
        text = response.text
    except Exception:
        text = None
    if text and text.strip():
        return text, None

    reason = 'empty response'
    try:
        # prompt_feedback carries safety/block info even when there are no candidates
        feedback = getattr(response, 'prompt_feedback', None)
        block_reason = getattr(feedback, 'block_reason', None) if feedback else None
        if block_reason:
            reason = f'blocked: {block_reason}'

        candidates = getattr(response, 'candidates', None) or []
        if candidates:
            cand = candidates[0]
            fr = getattr(cand, 'finish_reason', None)
            if fr is not None and not block_reason:
                reason = f'finish_reason={fr}'
            # Last resort: stitch the text parts back together by hand.
            content = getattr(cand, 'content', None)
            parts = getattr(content, 'parts', None) or []
            joined = ''.join(getattr(p, 'text', '') or '' for p in parts)
            if joined.strip():
                return joined, None
    except Exception:
        pass
    return None, reason


def repair_json(text):
    """
    Best-effort recovery of a JSON object from imperfect model output.

    Handles the two realistic failure modes left after JSON mode: a stray token
    before/after the object, and a response truncated mid-object. Returns a dict
    on success, or None if nothing parseable can be salvaged.
    """
    start = text.find('{')
    if start == -1:
        return None

    # 1) Trim to the outermost {...} and try as-is.
    end = text.rfind('}')
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 2) Truncated output: close any still-open braces/brackets and retry.
    snippet = text[start:]
    depth_obj = depth_arr = 0
    in_str = escaped = False
    closing = []
    for ch in snippet:
        if in_str:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth_obj += 1
            closing.append('}')
        elif ch == '[':
            depth_arr += 1
            closing.append(']')
        elif ch == '}' and depth_obj:
            depth_obj -= 1
            if closing:
                closing.pop()
        elif ch == ']' and depth_arr:
            depth_arr -= 1
            if closing:
                closing.pop()
    patched = snippet.rstrip().rstrip(',') + ''.join(reversed(closing))
    try:
        return json.loads(patched)
    except json.JSONDecodeError:
        return None


def generate_and_parse(client, model, model_name, contents, empty_retries=1):
    """
    Run one Gemini extraction call and parse the JSON result.

    Returns (data, error): data is the parsed dict on success (error None), or
    (None, error_message) when the response could not be parsed. API/transport
    exceptions (rate limit, 404, network) are NOT caught here — they propagate to
    the caller's existing fallback handling. An empty response is retried once on
    the SAME model (it is usually a transient blip) before giving up.
    """
    attempt = 0
    while True:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=GENERATION_CONFIG,
        )
        text, empty_reason = extract_response_text(response)

        if text:
            cleaned = clean_json_response(text)
            try:
                return json.loads(cleaned), None
            except json.JSONDecodeError as e:
                repaired = repair_json(cleaned)
                if repaired is not None:
                    print(f"[~] {model_name} returned imperfect JSON — repaired successfully")
                    return repaired, None
                return None, f'Failed to parse response: {e}'

        if attempt < empty_retries:
            attempt += 1
            print(f"[!] {model_name} returned no text ({empty_reason}); "
                  f"retrying {attempt}/{empty_retries}...")
            continue
        return None, f'Empty response from model ({empty_reason})'


def get_pdf_page_count(pdf_path):
    """Get the number of pages in a PDF"""
    try:
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except Exception as e:
        print(f"[!] Error reading PDF: {e}")
        return 0


def get_model_display_name(model):
    """Get a friendly display name for the model"""
    names = {
        "gemini-3.5-flash": "Gemini 3.5 Flash",
        "gemini-3-flash": "Gemini 3 Flash",
        "gemini-3-pro": "Gemini 3 Pro",
        "gemini-2.5-flash": "Gemini 2.5 Flash",
        "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    }
    return names.get(model, model)


# ============================================================================
# EXTRACTION FUNCTIONS
# ============================================================================

def extract_from_image(image_path):
    """
    Extract invoice data from an image using Gemini models with fallback.
    Tries each model in priority order until one succeeds.
    """
    print(f"\n[*] Processing image: {os.path.basename(image_path)}")

    try:
        client = get_gemini_client()
    except ValueError as e:
        return {'success': False, 'error': str(e)}

    # Load and prepare image
    img = Image.open(image_path)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGB')

    last_error = None

    for model in GEMINI_MODELS:
        model_name = get_model_display_name(model)
        try:
            print(f"[*] Trying {model_name}...")

            data, parse_error = generate_and_parse(
                client, model, model_name, [img, EXTRACTION_PROMPT]
            )

            if data is not None:
                line_items = data.get('line_items', [])
                print(f"[+] {model_name} extracted {len(line_items)} line items successfully")
                return {'success': True, 'data': data, 'model': model_name}

            # Empty / unparseable response — fall through to the next model.
            print(f"[!] {model_name}: {parse_error}")
            last_error = parse_error
            continue

        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'rate' in error_str.lower():
                print(f"[!] {model_name} rate limited, trying next...")
            elif '404' in error_str or 'not found' in error_str.lower():
                print(f"[!] {model_name} not available, trying next...")
            else:
                print(f"[!] {model_name} error: {e}")
            last_error = error_str
            continue

    print("[!] All Gemini models failed")
    return {'success': False, 'error': last_error or 'All models failed'}


def rasterize_pdf_pages(pdf_path, dpi=200):
    """
    Render every page of a PDF to a PNG image, in page order, using PyMuPDF.

    Passing an ordered image sequence (instead of raw PDF bytes) makes page
    boundaries explicit to the model, which fixes the multi-page bug where it
    read a page-1 subtotal as the final total. PyMuPDF is pip-only (no poppler
    / system libraries), so this works on Railway.

    Returns a list of PNG byte strings, one per page, or None if rasterization
    is unavailable (PyMuPDF not installed / file unreadable) so the caller can
    fall back to sending the raw PDF.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[!] PyMuPDF not available — falling back to raw PDF bytes")
        return None

    try:
        images = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=dpi)
                images.append(pix.tobytes("png"))
        return images if images else None
    except Exception as e:
        print(f"[!] PDF rasterization failed ({e}) — falling back to raw PDF bytes")
        return None


def extract_from_pdf(pdf_path, page_count=None):
    """
    Extract invoice data from an ENTIRE PDF in a single Gemini call.

    A multi-page PDF is treated as ONE invoice: the model reads every page,
    merges all line items, and returns the final consolidated totals (which
    typically appear on the last page). This avoids the old per-page approach
    that mistook continuation pages for separate invoices and read only page-1
    subtotals. Tries each model in priority order until one succeeds.

    Pages are rasterized to an ordered image sequence (PyMuPDF) so the model
    sees explicit page boundaries; if rasterization is unavailable we fall back
    to sending the raw PDF bytes.
    """
    pages_note = f" ({page_count} pages)" if page_count else ""
    print(f"\n[*] Processing PDF as a single consolidated invoice{pages_note}")

    try:
        client = get_gemini_client()
    except ValueError as e:
        return {'success': False, 'error': str(e)}

    # Prefer an ordered page-image sequence; fall back to raw PDF bytes.
    page_images = rasterize_pdf_pages(pdf_path)

    if page_images:
        n = len(page_images)
        print(f"[*] Rasterized PDF into {n} page image(s) at 200 DPI")
        # Build ordered image parts, each tagged with its page position so the
        # model knows where the document ends and which page holds the totals.
        content_parts = []
        for i, png_bytes in enumerate(page_images, 1):
            content_parts.append(f"--- PAGE {i} of {n} ---")
            content_parts.append(
                types.Part.from_bytes(data=png_bytes, mime_type='image/png')
            )
        content_parts.append(
            EXTRACTION_PROMPT + (
                f"\n\nThe {n} image(s) above are the pages of ONE invoice, in order "
                f"(PAGE 1 of {n} ... PAGE {n} of {n}). Apply RULE 3: first decide "
                "whether these pages are CONTINUATION pages (different goods rows, "
                "one long invoice) or DUPLICATE/TRIPLICATE COPIES (same invoice "
                "number/date/totals reprinted, or pages labelled Original/Duplicate/"
                "Triplicate). If continuation, merge all line items in page order and "
                f"take the FINAL totals from the LAST page (PAGE {n}). If they are "
                "copies, extract ONLY the original copy ONCE and IGNORE the duplicate/"
                "triplicate pages — never aggregate their line items or totals. "
                "Return ONE invoice object."
            )
        )
    else:
        # Fallback: hand Gemini the raw PDF (previous behaviour).
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        content_parts = [
            types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf'),
            EXTRACTION_PROMPT + (
                "\n\nThis PDF spans "
                f"{page_count or 'multiple'} page(s). Apply RULE 3: decide whether the "
                "pages are CONTINUATION pages of one long invoice or DUPLICATE/"
                "TRIPLICATE COPIES of the same invoice. If continuation, read every "
                "page, merge all line items, and return the FINAL consolidated totals "
                "(usually on the last page). If they are copies (same invoice number/"
                "date/totals reprinted, or pages labelled Original/Duplicate/"
                "Triplicate), extract ONLY the original copy ONCE and IGNORE the rest "
                "— never aggregate duplicate line items or totals. Return ONE invoice object."
            )
        ]

    last_error = None

    for model in GEMINI_MODELS:
        model_name = get_model_display_name(model)
        try:
            print(f"[*] Trying {model_name} for PDF...")

            data, parse_error = generate_and_parse(
                client, model, model_name, content_parts
            )

            if data is not None:
                line_items = data.get('line_items', [])
                print(f"[+] {model_name} extracted {len(line_items)} consolidated line items from PDF")
                return {'success': True, 'data': data, 'model': model_name}

            # Empty / unparseable response — fall through to the next model.
            print(f"[!] {model_name} PDF: {parse_error}")
            last_error = parse_error
            continue

        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'rate' in error_str.lower():
                print(f"[!] {model_name} rate limited, trying next...")
            elif '404' in error_str or 'not found' in error_str.lower():
                print(f"[!] {model_name} not available, trying next...")
            else:
                print(f"[!] {model_name} PDF error: {e}")
            last_error = error_str
            continue

    print("[!] All Gemini models failed for PDF")
    return {'success': False, 'error': last_error or 'All models failed'}


def process_bill_file(file_path, filename):
    """
    Process a bill file (image or PDF) and extract structured data.
    Returns a list of extracted bill data (one per page for PDFs).
    """
    results = []

    try:
        ext = os.path.splitext(filename)[1].lower()

        if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']:
            # Process image
            result = extract_from_image(file_path)
            result['filename'] = filename
            result['page'] = 1
            results.append(result)

        elif ext == '.pdf':
            # A multi-page PDF is treated as ONE invoice: read every page in a
            # single call and consolidate (merge line items, use final totals).
            # GST invoices commonly run 2-3 pages with totals only on the last
            # page, so per-page extraction produced partial/duplicate records.
            page_count = get_pdf_page_count(file_path)

            if page_count == 0:
                return [{'success': False, 'error': 'Could not read PDF file', 'filename': filename}]

            result = extract_from_pdf(file_path, page_count)
            result['filename'] = filename
            result['page'] = 1
            result['page_count'] = page_count
            results.append(result)
        else:
            return [{'success': False, 'error': f'Unsupported file type: {ext}', 'filename': filename}]

    except Exception as e:
        print(f"[!] Error processing {filename}: {e}")
        import traceback
        traceback.print_exc()
        return [{'success': False, 'error': str(e), 'filename': filename}]

    # Reconcile each extraction's numbers (header identity, line-item sums,
    # per-line GST-rate math). Computed once here so the DB save, the display
    # response and the review-queue UI all share the same verdict.
    for result in results:
        if result.get('success') and result.get('data'):
            try:
                result['validation'] = validate_extraction(result['data'])
            except Exception as e:
                print(f"[!] Validation error for {filename}: {e}")

    return results


def generate_excel(bill_data_list):
    """
    Generate an Excel file from extracted bill data.
    Returns BytesIO object containing the Excel file.
    """
    import pandas as pd
    from openpyxl.styles import Font, Alignment, PatternFill

    # Prepare Summary sheet data
    summary_rows = []
    line_items_rows = []

    for i, bill in enumerate(bill_data_list):
        if not bill.get('success') or not bill.get('data'):
            continue

        data = bill['data']
        header = data.get('invoice_header', {})
        vendor = data.get('vendor', {})
        buyer = data.get('buyer', {})
        taxes = data.get('taxes', {})
        transport = data.get('transport', {})

        # Summary row
        summary_rows.append({
            'S.No': i + 1,
            'File': bill.get('filename', ''),
            'Page': bill.get('page', 1),
            'Invoice Number': header.get('invoice_number', ''),
            'Invoice Date': header.get('invoice_date', ''),
            'Vendor Name': vendor.get('name', ''),
            'Vendor GSTIN': vendor.get('gstin', ''),
            'Vendor Address': vendor.get('address', ''),
            'Buyer Name': buyer.get('name', ''),
            'Buyer GSTIN': buyer.get('gstin', ''),
            'Subtotal': taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0),
            'CGST': taxes.get('total_cgst', 0) or taxes.get('cgst_amount', 0),
            'SGST': taxes.get('total_sgst', 0) or taxes.get('sgst_amount', 0),
            'IGST': taxes.get('total_igst', 0) or taxes.get('igst_amount', 0),
            # Freight/shipping/packing etc. are kept out of GST and collected here.
            'Other Charges': sum(
                (c.get('amount', 0) or 0)
                for c in data.get('other_charges', []) if c.get('description')
            ),
            'Round Off': taxes.get('round_off', 0),
            'Total Amount': taxes.get('total_amount', 0),
            'Project': data.get('project', ''),
            'Vehicle Number': transport.get('vehicle_number', ''),
            'E-Way Bill': header.get('eway_bill_number', ''),
            'IRN': header.get('irn', ''),
        })

        # Line items
        items = data.get('line_items', [])
        project = data.get('project', '')
        for item in items:
            line_items_rows.append({
                'Invoice Number': header.get('invoice_number', ''),
                'Invoice Date': header.get('invoice_date', ''),
                'Vendor Name': vendor.get('name', ''),
                'Project': project,
                'S.No': item.get('sl_no', ''),
                'Description of Goods': item.get('description', ''),
                'HSN/SAC Code': item.get('hsn_sac_code', '') or item.get('hsn_code', ''),
                'Quantity': item.get('quantity', 0),
                'UOM': item.get('uom', ''),
                'Rate per Unit': item.get('rate_per_unit', 0) or item.get('rate', 0),
                'Discount %': item.get('discount_percent', 0),
                'Discount Amt': item.get('discount_amount', 0),
                'Taxable Value': item.get('taxable_value', 0),
                'CGST %': item.get('cgst_rate', 0),
                'CGST Amt': item.get('cgst_amount', 0),
                'SGST %': item.get('sgst_rate', 0),
                'SGST Amt': item.get('sgst_amount', 0),
                'IGST %': item.get('igst_rate', 0),
                'IGST Amt': item.get('igst_amount', 0),
                'Total GST %': item.get('gst_percent', 0),
                'Amount': item.get('amount', 0),
            })

        # Other charges (Loading, Freight, etc.)
        other_charges = data.get('other_charges', [])
        for charge in other_charges:
            if charge.get('description') and charge.get('amount'):
                line_items_rows.append({
                    'Invoice Number': header.get('invoice_number', ''),
                    'Invoice Date': header.get('invoice_date', ''),
                    'Vendor Name': vendor.get('name', ''),
                    'Project': project,
                    'S.No': '-',
                    'Description of Goods': f"[CHARGE] {charge.get('description', '')}",
                    'HSN/SAC Code': charge.get('hsn_code', ''),
                    'Quantity': '',
                    'UOM': '',
                    'Rate per Unit': '',
                    'Discount %': '',
                    'Discount Amt': '',
                    'Taxable Value': '',
                    'CGST %': '',
                    'CGST Amt': '',
                    'SGST %': '',
                    'SGST Amt': '',
                    'IGST %': '',
                    'IGST Amt': '',
                    'Total GST %': '',
                    'Amount': charge.get('amount', 0),
                })

    # Create DataFrames
    df_summary = pd.DataFrame(summary_rows) if summary_rows else pd.DataFrame()
    df_items = pd.DataFrame(line_items_rows) if line_items_rows else pd.DataFrame()

    # Create Excel workbook
    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Write Summary sheet
        if not df_summary.empty:
            df_summary.to_excel(writer, sheet_name='Invoice Summary', index=False)
            ws_summary = writer.sheets['Invoice Summary']

            # Style header
            header_fill = PatternFill(start_color='1a2942', end_color='1a2942', fill_type='solid')
            header_font = Font(bold=True, color='FFFFFF')

            for cell in ws_summary[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')

            # Auto-width columns
            for column in ws_summary.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws_summary.column_dimensions[column_letter].width = adjusted_width

        # Write Line Items sheet
        if not df_items.empty:
            df_items.to_excel(writer, sheet_name='Line Items', index=False)
            ws_items = writer.sheets['Line Items']

            # Style header
            for cell in ws_items[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')

            # Auto-width columns
            for column in ws_items.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws_items.column_dimensions[column_letter].width = adjusted_width

    output.seek(0)
    return output


def format_extracted_data_for_display(bill_data_list):
    """
    Format extracted bill data for frontend display.
    Returns a list of simplified bill objects.
    """
    display_data = []

    for bill in bill_data_list:
        if not bill.get('success'):
            display_data.append({
                'success': False,
                'error': bill.get('error', 'Unknown error'),
                'filename': bill.get('filename', ''),
                'page': bill.get('page', 1)
            })
            continue

        data = bill.get('data', {})
        header = data.get('invoice_header', {})
        vendor = data.get('vendor', {})
        buyer = data.get('buyer', {})
        taxes = data.get('taxes', {})
        items = data.get('line_items', [])
        transport = data.get('transport', {})

        display_data.append({
            'success': True,
            'filename': bill.get('filename', ''),
            'page': bill.get('page', 1),
            'invoice_number': header.get('invoice_number', ''),
            'invoice_date': header.get('invoice_date', ''),
            'vendor_name': vendor.get('name', ''),
            'vendor_gstin': vendor.get('gstin', ''),
            'buyer_name': buyer.get('name', ''),
            'buyer_gstin': buyer.get('gstin', ''),
            'total_amount': taxes.get('total_amount', 0),
            'cgst': taxes.get('total_cgst', 0) or taxes.get('cgst_amount', 0),
            'sgst': taxes.get('total_sgst', 0) or taxes.get('sgst_amount', 0),
            'igst': taxes.get('total_igst', 0) or taxes.get('igst_amount', 0),
            'subtotal': taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0),
            'item_count': len(items),
            'vehicle_number': transport.get('vehicle_number', ''),
            'eway_bill': header.get('eway_bill_number', ''),
            'validation': bill.get('validation'),  # reconciliation verdict (A1)
            'raw_data': data  # Include raw data for detailed view
        })

    return display_data
