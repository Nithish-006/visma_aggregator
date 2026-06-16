"""Invoice helpers shared by the bills and sales blueprints.

Re-extraction (preview/apply, clean-only), source-file location, the nested->flat
extraction shape, manual validation override, and project-name-from-filename.
"""

import os

from flask import request, jsonify

from config import Config
from extensions import db_manager
from bill_processor import process_bill_file
from extraction_validator import validate_extraction, validate_db_row


def extract_project_from_filename(filename):
    """Extract project name from filename by removing leading numbers and extension"""
    import re
    name = os.path.splitext(filename)[0]  # Remove extension
    name = re.sub(r'^\d+\s*', '', name)   # Remove leading numbers
    return name.strip()


def _locate_invoice_file(filename, prefix):
    """Find the stored source file on the volume. Files are saved as
    <prefix>_<timestamp>_<originalname>; the DB keeps the original filename.
    Mirrors the serve route. Returns an absolute path or None."""
    import glob as _glob
    if not filename:
        return None
    direct = os.path.join(Config.UPLOAD_FOLDER, filename)
    if os.path.exists(direct):
        return direct
    matches = _glob.glob(os.path.join(Config.UPLOAD_FOLDER, f"{prefix}_*_{filename}"))
    return sorted(matches)[-1] if matches else None


def _extraction_to_flat(data, project):
    """Flatten a nested Gemini extraction dict into the flat shape update_bill /
    update_sales_bill expect, injecting the preserved project tag. other_charges
    is collapsed to the single summed column those updaters store."""
    header = data.get('invoice_header', {}) or {}
    vendor = data.get('vendor', {}) or {}
    buyer = data.get('buyer', {}) or {}
    ship_to = data.get('ship_to', {}) or {}
    taxes = data.get('taxes', {}) or {}
    transport = data.get('transport', {}) or {}
    other_total = sum((c.get('amount', 0) or 0)
                      for c in (data.get('other_charges', []) or [])
                      if c.get('description'))
    return {
        'invoice_number': header.get('invoice_number', ''),
        'invoice_date': header.get('invoice_date', ''),
        'irn': header.get('irn', ''),
        'ack_number': header.get('ack_number', ''),
        'eway_bill_number': header.get('eway_bill_number', ''),
        'vendor_name': vendor.get('name', ''),
        'vendor_gstin': vendor.get('gstin', ''),
        'vendor_address': vendor.get('address', ''),
        'vendor_state': vendor.get('state', ''),
        'vendor_pan': vendor.get('pan', ''),
        'vendor_phone': vendor.get('phone', ''),
        'vendor_bank_name': vendor.get('bank_name', ''),
        'vendor_bank_account': vendor.get('bank_account', ''),
        'vendor_bank_ifsc': vendor.get('bank_ifsc', ''),
        'buyer_name': buyer.get('name', ''),
        'buyer_gstin': buyer.get('gstin', ''),
        'buyer_address': buyer.get('address', ''),
        'buyer_state': buyer.get('state', ''),
        'ship_to_name': ship_to.get('name', ''),
        'ship_to_address': ship_to.get('address', ''),
        'subtotal': taxes.get('subtotal', 0) or taxes.get('taxable_amount', 0) or 0,
        'total_cgst': taxes.get('total_cgst', 0) or 0,
        'total_sgst': taxes.get('total_sgst', 0) or 0,
        'total_igst': taxes.get('total_igst', 0) or 0,
        'other_charges': other_total,
        'round_off': taxes.get('round_off', 0) or 0,
        'total_amount': taxes.get('total_amount', 0) or 0,
        'amount_in_words': taxes.get('amount_in_words', ''),
        'vehicle_number': transport.get('vehicle_number', ''),
        'transporter_name': transport.get('transporter_name', ''),
        'project': project,  # preserved from the existing row — never re-derived
        'line_items': data.get('line_items', []) or [],
    }


def _reprocess_invoice(invoice_id, kind, apply_changes, supplied_flat=None):
    """Re-extract one stored invoice from its source PDF using the improved
    pipeline, re-validate, and return an old->new diff. Applies the new values
    (preserving the project tag) only when apply_changes is set AND the new
    extraction reconciles ('ok'), per the clean-only policy.

    The single-bill flow is a two-step preview→apply: the preview returns the
    re-extracted values to the browser (the `extraction` key), and the apply
    posts those same values back as `supplied_flat`. This guarantees the values
    applied are exactly the ones the user saw and approved — vision extraction
    is non-deterministic, so re-extracting at apply time could otherwise yield a
    different verdict and silently block a preview the user just saw reconcile.
    The values are re-validated server-side (clean-only still enforced) and the
    project tag is always taken from the stored row, never trusted from the
    client. When no supplied_flat is given (the preview pass, or the one-shot
    bulk reprocess) the bill is extracted fresh from its PDF.
    """
    is_sales = (kind == 'sales')
    prefix = 'sales' if is_sales else 'bill'
    get_detail = db_manager.get_sales_bill_detail if is_sales else db_manager.get_bill_detail
    updater = db_manager.update_sales_bill if is_sales else db_manager.update_bill

    existing = get_detail(invoice_id)
    if not existing:
        return {'success': False, 'error': 'Bill not found'}, 404

    project = existing.get('project')
    filename = existing.get('filename')

    if apply_changes and supplied_flat is not None:
        # Apply the exact values the user previewed and approved. Force the
        # stored project tag (never trust the client copy) and re-validate
        # server-side so the clean-only gate below is authoritative.
        flat = dict(supplied_flat)
        flat['project'] = project
        new_validation = validate_db_row(flat, flat.get('line_items', []))
        model = None
    else:
        pdf_path = _locate_invoice_file(filename, prefix)
        if not pdf_path:
            return {'success': False, 'error': f'Source file not found on disk for "{filename}"'}, 200

        results = process_bill_file(pdf_path, filename)
        res = results[0] if results else None
        if not res or not res.get('success') or not res.get('data'):
            return {'success': False,
                    'error': (res or {}).get('error', 'Re-extraction failed')}, 200

        new_data = res['data']
        new_validation = res.get('validation') or validate_extraction(new_data)
        flat = _extraction_to_flat(new_data, project)
        model = res.get('model')

    def f(x):
        try:
            return round(float(x or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    fields = ['subtotal', 'total_cgst', 'total_sgst', 'total_igst',
              'other_charges', 'round_off', 'total_amount']
    diff = {}
    for k in fields:
        diff[k] = {'old': f(existing.get(k)), 'new': f(flat.get(k)),
                   'changed': f(existing.get(k)) != f(flat.get(k))}
    diff['line_item_count'] = {'old': len(existing.get('line_items', [])),
                               'new': len(flat.get('line_items', [])),
                               'changed': len(existing.get('line_items', [])) != len(flat.get('line_items', []))}
    diff['invoice_number'] = {'old': existing.get('invoice_number', ''),
                              'new': flat.get('invoice_number', ''),
                              'changed': (existing.get('invoice_number') or '') != (flat.get('invoice_number') or '')}

    applied = False
    apply_blocked = None
    if apply_changes:
        if new_validation.get('status') == 'ok':
            ok, err = updater(invoice_id, flat)
            applied = bool(ok)
            if not ok:
                apply_blocked = err or 'update failed'
        else:
            apply_blocked = "Re-extraction still flagged 'review' — not applied (clean-only policy)"

    return {
        'success': True,
        'invoice_id': invoice_id,
        'kind': kind,
        'model': model,
        'project_preserved': project,
        # Echoed so the apply step can post these exact values back.
        'extraction': flat,
        'old_validation': {
            'status': existing.get('validation_status'),
            'diff': f(existing.get('validation_diff')),
            'notes': existing.get('validation_notes'),
        },
        'new_validation': new_validation,
        'diff': diff,
        'applied': applied,
        'apply_blocked': apply_blocked,
    }, 200


def _set_invoice_validation(invoice_id, kind):
    """Manually approve a flagged bill ('approve') or recompute its verdict
    ('recheck'). Approve is a sticky override that survives re-validation."""
    action = (request.json or {}).get('action', 'approve')
    if action == 'approve':
        ok, info = db_manager.approve_bill_validation(invoice_id, kind)
        if not ok:
            return jsonify({'success': False, 'error': info or 'Update failed'}), 200
        return jsonify({'success': True, 'status': 'approved'})
    if action == 'recheck':
        ok, info = db_manager.recheck_bill_validation(invoice_id, kind)
        if not ok:
            return jsonify({'success': False, 'error': info or 'Re-check failed'}), 200
        return jsonify({'success': True, 'status': info})
    return jsonify({'success': False, 'error': f'Unknown action: {action}'}), 400
