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
import re
import json

from google import genai
from google.genai import types
from PIL import Image

# Reuse the exact model-fallback chain pattern from bill_processor.py
GEMINI_MODELS = [
    "gemini-3-flash",
    "gemini-3-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_MODEL_DISPLAY_NAMES = {
    "gemini-3-flash": "Gemini 3 Flash",
    "gemini-3-pro": "Gemini 3 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
}

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

GRAND TOTAL (most important):
- The PO may have per-page subtotals. You must return the FINAL CONSOLIDATED
  figures for the whole document, taken from the last/summary page:
    * total_value  = the grand total INCLUDING all taxes (CGST + SGST + IGST).
                     This is the total project value. Use the "Total ₹ ..." figure.
    * taxable_value = the sum of taxable amounts BEFORE tax (subtotal).
    * total_tax     = total of CGST + SGST + IGST (= total_value - taxable_value).

RULES:
1. Numbers: strip commas and currency symbols, return plain numbers
   (23,25,190.00 -> 2325190.00). Use 0 if genuinely absent.
2. po_date: format as DD-MMM-YYYY (e.g. 16-Mar-2026). Empty string if absent.
3. line_item_count: how many distinct goods/scope rows the PO lists (just the count).
4. payment_terms: a short single-line summary of the payment schedule if present
   (e.g. "50% with PO, 45% for erection, 5% after completion"), else "".
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
  "payment_terms": ""
}
"""


def get_gemini_client():
    """Get configured Gemini client (mirrors bill_processor.get_gemini_client)."""
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment variables")
    return genai.Client(api_key=api_key)


def _clean_json_response(response_text):
    """Strip markdown code fences if present."""
    text = (response_text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    return text


def _model_display_name(model):
    return _MODEL_DISPLAY_NAMES.get(model, model)


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

    return {
        'po_number': text(data.get('po_number')),
        'po_date': text(data.get('po_date')),
        'client_name': text(data.get('client_name')),
        'currency': text(data.get('currency')) or 'INR',
        'taxable_value': num(data.get('taxable_value')),
        'total_tax': num(data.get('total_tax')),
        'total_value': num(data.get('total_value')),
        'amount_in_words': text(data.get('amount_in_words')),
        'line_item_count': int(num(data.get('line_item_count'))),
        'payment_terms': text(data.get('payment_terms')),
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

    try:
        client = get_gemini_client()
    except ValueError as e:
        return {'success': False, 'error': str(e)}

    try:
        contents = _build_contents(file_path, ext)
    except Exception as e:
        return {'success': False, 'error': f'Could not read file: {e}'}

    last_error = None
    for model in GEMINI_MODELS:
        name = _model_display_name(model)
        try:
            print(f"[*] PO extraction: trying {name} on {filename}...")
            response = client.models.generate_content(model=model, contents=contents)
            data = json.loads(_clean_json_response(response.text))
            gist = _normalize_po_data(data)
            print(f"[+] {name} extracted PO: total_value={gist['total_value']}, "
                  f"client={gist['client_name']!r}")
            return {'success': True, 'data': gist, 'model': name}
        except json.JSONDecodeError as e:
            print(f"[!] {name} JSON parse error: {e}")
            last_error = f'Failed to parse response: {e}'
            continue
        except Exception as e:
            err = str(e)
            if '429' in err or 'RESOURCE_EXHAUSTED' in err or 'rate' in err.lower():
                print(f"[!] {name} rate limited, trying next...")
            elif '404' in err or 'not found' in err.lower():
                print(f"[!] {name} not available, trying next...")
            else:
                print(f"[!] {name} error: {e}")
            last_error = err
            continue

    print("[!] All Gemini models failed for PO extraction")
    return {'success': False, 'error': last_error or 'All models failed'}
