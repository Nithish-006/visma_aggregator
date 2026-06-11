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

# Model configuration - Gemini models via direct API (in priority order).
# All Flash-tier: fast, cheap, and strong at invoice OCR + table extraction.
# gemini-3-pro is intentionally excluded — it's a reasoning model (slow + costly)
# with no accuracy edge on this OCR/extraction task, and falling through to it on
# every free-tier throttle was the main source of latency.
GEMINI_MODELS = [
    "gemini-3-flash",        # primary: best vision quality at flash speed
    "gemini-2.5-flash",      # fallback: proven on GST tables
    "gemini-2.5-flash-lite", # last resort: cheap/fast, lower accuracy
]

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
RULE 3 — MULTI-PAGE INVOICES (read the WHOLE document, consolidate to ONE invoice):
═══════════════════════════════════════════════════════════════════════
- This document may span 2, 3 or more pages but is ONE single invoice.
- Read and combine ALL pages — do NOT stop at the first page.
- line_items: merge the rows from EVERY page into one continuous list, in order.
  Continuation pages often repeat the column header and the invoice header — do
  not duplicate header rows, but DO capture every distinct goods row across pages.
- The FINAL CONSOLIDATED totals (taxable_amount, total_cgst/sgst/igst, round_off,
  total_amount, amount_in_words) are usually on the LAST page. Use those final
  figures — never the per-page subtotal of page 1 alone.
- Header fields (invoice number, date, vendor, buyer) come from where they appear
  (usually page 1). Return a SINGLE consolidated invoice object, not one per page.

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

            response = client.models.generate_content(
                model=model,
                contents=[
                    img,
                    EXTRACTION_PROMPT
                ]
            )

            response_text = clean_json_response(response.text)
            data = json.loads(response_text)

            line_items = data.get('line_items', [])
            print(f"[+] {model_name} extracted {len(line_items)} line items successfully")

            return {'success': True, 'data': data, 'model': model_name}

        except json.JSONDecodeError as e:
            print(f"[!] {model_name} JSON parse error: {e}")
            last_error = f'Failed to parse response: {str(e)}'
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


def extract_from_pdf(pdf_path, page_count=None):
    """
    Extract invoice data from an ENTIRE PDF in a single Gemini call.

    A multi-page PDF is treated as ONE invoice: the model reads every page,
    merges all line items, and returns the final consolidated totals (which
    typically appear on the last page). This avoids the old per-page approach
    that mistook continuation pages for separate invoices and read only page-1
    subtotals. Tries each model in priority order until one succeeds.
    """
    pages_note = f" ({page_count} pages)" if page_count else ""
    print(f"\n[*] Processing PDF as a single consolidated invoice{pages_note}")

    try:
        client = get_gemini_client()
    except ValueError as e:
        return {'success': False, 'error': str(e)}

    # Read PDF bytes
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()

    last_error = None

    for model in GEMINI_MODELS:
        model_name = get_model_display_name(model)
        try:
            print(f"[*] Trying {model_name} for PDF...")

            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(
                        data=pdf_bytes,
                        mime_type='application/pdf'
                    ),
                    EXTRACTION_PROMPT + (
                        "\n\nThis PDF is ONE invoice spanning "
                        f"{page_count or 'multiple'} page(s). Read EVERY page, merge all "
                        "line items into a single list, and return the FINAL consolidated "
                        "totals (usually printed on the last page). Return ONE invoice object."
                    )
                ]
            )

            response_text = clean_json_response(response.text)
            data = json.loads(response_text)

            line_items = data.get('line_items', [])
            print(f"[+] {model_name} extracted {len(line_items)} consolidated line items from PDF")

            return {'success': True, 'data': data, 'model': model_name}

        except json.JSONDecodeError as e:
            print(f"[!] {model_name} PDF JSON parse error: {e}")
            last_error = f'Failed to parse response: {str(e)}'
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
            'raw_data': data  # Include raw data for detailed view
        })

    return display_data
