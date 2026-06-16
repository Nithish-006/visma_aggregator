"""Bill processor: /bill-processor + /api/bills/* endpoints."""

import os

from flask import (
    Blueprint, render_template, request, jsonify, send_file,
)
from werkzeug.utils import secure_filename

from config import Config, now_ist
from extensions import db_manager
from bill_processor import process_bill_file, generate_excel, format_extracted_data_for_display
from helpers.projects import validate_project_value
from helpers.invoices import _reprocess_invoice, _set_invoice_validation
from auth import login_required

bp = Blueprint('bills', __name__)


@bp.route('/bill-processor')
@login_required
def bill_processor_page():
    """Render bill processor page"""
    # Ensure the reconciliation/validation columns exist (additive migration).
    db_manager.ensure_validation_columns()
    return render_template('bill_processor.html')


@bp.route('/api/bills/process', methods=['POST'])
@login_required
def process_bill():
    """Process an uploaded bill image/PDF and extract data using Gemini Vision"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        # Check file extension
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf', '.webp'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

        # Save file temporarily
        filename = secure_filename(file.filename)
        timestamp = now_ist().strftime('%Y%m%d_%H%M%S')
        temp_filename = f"bill_{timestamp}_{filename}"
        temp_path = os.path.join(Config.UPLOAD_FOLDER, temp_filename)

        file.save(temp_path)


        # Process the bill

        results = process_bill_file(temp_path, filename)

        # Save to database (with duplicate check)
        db_results = []
        for bill in results:
            if bill.get('success'):
                # Extract invoice number from the bill data
                invoice_number = bill.get('data', {}).get('invoice_header', {}).get('invoice_number', '')

                # Check for duplicate invoice before saving
                existing_bill = db_manager.check_duplicate_invoice(invoice_number)
                if existing_bill:

                    db_results.append({
                        'saved': False,
                        'invoice_id': None,
                        'db_error': 'Duplicate invoice',
                        'is_duplicate': True,
                        'existing_bill': existing_bill
                    })
                    continue

                # No duplicate found, proceed with insert
                success, invoice_id, error = db_manager.insert_bill(bill)
                db_results.append({
                    'saved': success,
                    'invoice_id': invoice_id,
                    'db_error': error,
                    'is_duplicate': False
                })
            else:
                db_results.append({'saved': False, 'invoice_id': None, 'db_error': 'Extraction failed', 'is_duplicate': False})

        # Format for display
        display_data = format_extracted_data_for_display(results)

        # Add DB status to display data
        for i, display_item in enumerate(display_data):
            if i < len(db_results):
                display_item['db_saved'] = db_results[i]['saved']
                display_item['invoice_id'] = db_results[i]['invoice_id']
                display_item['is_duplicate'] = db_results[i].get('is_duplicate', False)
                if db_results[i].get('existing_bill'):
                    display_item['existing_bill'] = db_results[i]['existing_bill']

        return jsonify({
            'success': True,
            'results': results,
            'display_data': display_data,
            'db_results': db_results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/bills/download', methods=['POST'])
@login_required
def download_bills_excel():
    """Generate and download Excel file from extracted bill data"""
    try:
        data = request.json
        results = data.get('results', [])

        if not results:
            return jsonify({'error': 'No data to download'}), 400

        # Generate Excel file
        excel_buffer = generate_excel(results)

        # Create filename with timestamp
        filename = f"bills_extracted_{now_ist().strftime('%Y%m%d_%H%M%S')}.xlsx"

        return send_file(
            excel_buffer,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/bills/stored')
@login_required
def get_stored_bills():
    """Get all stored bills from database with optional filters"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        project = request.args.get('project', None)
        projects_csv = request.args.get('projects', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)
        added_from = request.args.get('added_from', None)
        added_to = request.args.get('added_to', None)

        # Multi-project support: comma-separated list takes precedence
        projects_list = None
        if projects_csv:
            projects_list = [p.strip() for p in projects_csv.split(',') if p.strip()]
        elif project:
            projects_list = [project]

        bills = db_manager.get_all_bills(limit=limit, offset=offset, projects=projects_list,
                                         date_from=date_from, date_to=date_to,
                                         added_from=added_from, added_to=added_to)
        total = db_manager.get_bill_count(projects=projects_list, date_from=date_from, date_to=date_to,
                                          added_from=added_from, added_to=added_to)


        return jsonify({
            'success': True,
            'bills': bills,
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/stored/<int:invoice_id>')
@login_required
def get_stored_bill_detail(invoice_id):
    """Get detailed bill information including line items"""
    try:
        bill = db_manager.get_bill_detail(invoice_id)

        if not bill:
            return jsonify({'success': False, 'error': 'Bill not found'}), 404

        return jsonify({
            'success': True,
            'bill': bill
        })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/stored/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_stored_bill(invoice_id):
    """Delete a stored bill"""
    try:
        success = db_manager.delete_bill(invoice_id)

        if success:
            return jsonify({'success': True, 'message': 'Bill deleted'})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete bill'}), 500
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/stored/<int:invoice_id>/project', methods=['PUT'])
@login_required
def update_bill_project(invoice_id):
    """Update the project field for a bill"""
    try:
        data = request.json
        ok, project, perr = validate_project_value((data or {}).get('project'))
        if not ok:
            return jsonify({'success': False, 'error': perr}), 400

        success = db_manager.update_bill_project(invoice_id, project)

        if success:
            return jsonify({'success': True, 'message': 'Project updated', 'project': project})
        else:
            return jsonify({'success': False, 'error': 'Failed to update project'}), 500
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/projects')
@login_required
def get_bill_projects():
    """Get all unique project names from bills"""
    try:
        projects = db_manager.get_unique_projects()
        return jsonify({
            'success': True,
            'projects': projects
        })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/summary')
@login_required
def get_bills_summary():
    """Get summary statistics for stored bills"""
    try:
        project = request.args.get('project', None)
        projects_csv = request.args.get('projects', None)
        date_from = request.args.get('date_from', None)
        date_to = request.args.get('date_to', None)
        added_from = request.args.get('added_from', None)
        added_to = request.args.get('added_to', None)

        projects_list = None
        if projects_csv:
            projects_list = [p.strip() for p in projects_csv.split(',') if p.strip()]
        elif project:
            projects_list = [project]

        query = """
        SELECT
            COUNT(*) as cnt,
            COALESCE(SUM(total_amount), 0) as sum_value,
            COALESCE(SUM(COALESCE(total_cgst, 0) + COALESCE(total_sgst, 0) + COALESCE(total_igst, 0)), 0) as sum_gst,
            COALESCE(SUM(COALESCE(total_cgst, 0)), 0) as sum_cgst,
            COALESCE(SUM(COALESCE(total_sgst, 0)), 0) as sum_sgst,
            COALESCE(SUM(COALESCE(total_igst, 0)), 0) as sum_igst,
            COUNT(DISTINCT vendor_name) as vendor_cnt
        FROM bill_invoices
        WHERE 1=1
        """
        params = []

        if projects_list:
            placeholders = ','.join(['%s'] * len(projects_list))
            query += f" AND project IN ({placeholders})"
            params.extend(projects_list)

        if date_from:
            query += " AND invoice_date >= %s"
            params.append(date_from)

        if date_to:
            query += " AND invoice_date <= %s"
            params.append(date_to)

        if added_from:
            query += " AND DATE(created_at) >= %s"
            params.append(added_from)

        if added_to:
            query += " AND DATE(created_at) <= %s"
            params.append(added_to)

        result = db_manager.fetch_all(query, tuple(params) if params else None)


        if result and len(result) > 0 and result[0] is not None:
            row = result[0]
            # Convert each value - use float() directly, don't rely on 'or' since Decimal(0) is falsy
            total_invoices = int(row[0]) if row[0] is not None else 0
            total_value = float(row[1]) if row[1] is not None else 0.0
            total_gst = float(row[2]) if row[2] is not None else 0.0
            total_cgst = float(row[3]) if row[3] is not None else 0.0
            total_sgst = float(row[4]) if row[4] is not None else 0.0
            total_igst = float(row[5]) if row[5] is not None else 0.0
            unique_vendors = int(row[6]) if row[6] is not None else 0
            return jsonify({
                'success': True,
                'summary': {
                    'total_invoices': total_invoices,
                    'total_value': total_value,
                    'total_gst': total_gst,
                    'total_cgst': total_cgst,
                    'total_sgst': total_sgst,
                    'total_igst': total_igst,
                    'unique_vendors': unique_vendors
                }
            })
        else:
            return jsonify({
                'success': True,
                'summary': {
                    'total_invoices': 0,
                    'total_value': 0,
                    'total_gst': 0,
                    'total_cgst': 0,
                    'total_sgst': 0,
                    'total_igst': 0,
                    'unique_vendors': 0
                }
            })
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/stats')
@login_required
def get_bills_stats():
    """Get bill processor stats for hub page"""
    try:
        invoice_count = db_manager.get_bill_count()
        return jsonify({
            'success': True,
            'invoice_count': invoice_count
        })
    except Exception as e:

        return jsonify({
            'success': False,
            'invoice_count': 0,
            'error': str(e)
        }), 500


@bp.route('/api/bills/file/<filename>')
@login_required
def serve_bill_file(filename):
    """Serve uploaded bill file (PDF or image) for preview"""
    import glob as glob_module

    try:
        # Security: Prevent path traversal attacks
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        # Build the file path
        file_path = os.path.join(Config.UPLOAD_FOLDER, filename)

        # Check if file exists directly
        if not os.path.exists(file_path):
            # Files are saved with bill_{timestamp}_ prefix, so search for matching file
            pattern = os.path.join(Config.UPLOAD_FOLDER, f"bill_*_{filename}")
            matches = glob_module.glob(pattern)

            if matches:
                # Use the most recent match (last in sorted order)
                file_path = sorted(matches)[-1]
            else:
                return jsonify({'success': False, 'error': 'File not found'}), 404

        # Determine MIME type based on extension
        ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
        mime_types = {
            'pdf': 'application/pdf',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'webp': 'image/webp',
            'gif': 'image/gif',
            'bmp': 'image/bmp'
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')

        return send_file(file_path, mimetype=mime_type)
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/upload-files', methods=['POST'])
@login_required
def bulk_upload_bill_files():
    """
    Bulk upload bill files (PDFs/images) without processing.
    Used to restore original documents for bills already in the database.
    Files are saved with their original names to match database records.
    """
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'error': 'No files provided'}), 400

        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({'success': False, 'error': 'No files selected'}), 400

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf', '.webp', '.gif', '.bmp'}
        results = []
        uploaded_count = 0
        skipped_count = 0

        for file in files:
            if not file.filename:
                continue

            # Check file extension
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                results.append({
                    'filename': file.filename,
                    'status': 'skipped',
                    'reason': f'Unsupported file type: {ext}'
                })
                skipped_count += 1
                continue

            # Secure the filename and save
            filename = secure_filename(file.filename)
            file_path = os.path.join(Config.UPLOAD_FOLDER, filename)

            # Check if file already exists
            if os.path.exists(file_path):
                results.append({
                    'filename': filename,
                    'status': 'skipped',
                    'reason': 'File already exists'
                })
                skipped_count += 1
                continue

            # Save the file
            file.save(file_path)
            results.append({
                'filename': filename,
                'status': 'uploaded'
            })
            uploaded_count += 1


        return jsonify({
            'success': True,
            'message': f'Uploaded {uploaded_count} files, skipped {skipped_count}',
            'uploaded': uploaded_count,
            'skipped': skipped_count,
            'details': results
        })

    except Exception as e:

        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/stored/<int:invoice_id>', methods=['PUT'])
@login_required
def update_stored_bill(invoice_id):
    """Update a stored bill with all fields and line items"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        if 'project' in data:
            ok, normalized, perr = validate_project_value(data.get('project'))
            if not ok:
                return jsonify({'success': False, 'error': perr}), 400
            data['project'] = normalized

        success, error = db_manager.update_bill(invoice_id, data)

        if success:
            return jsonify({'success': True, 'message': 'Invoice updated successfully'})
        else:
            return jsonify({'success': False, 'error': error or 'Failed to update invoice'}), 500
    except Exception as e:

        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/revalidate', methods=['POST'])
@login_required
def revalidate_bills():
    """Run the Tier-1 reconciliation over every stored bill (purchase + sales)
    and persist the verdicts. Populates the review queue."""
    try:
        summary = db_manager.revalidate_existing_bills()
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/bills/reprocess/<int:invoice_id>', methods=['POST'])
@login_required
def reprocess_bill(invoice_id):
    """Re-extract a purchase bill from its PDF; preview or apply (clean-only)."""
    body = request.json or {}
    apply_changes = bool(body.get('apply', False))
    supplied_flat = body.get('extraction') if apply_changes else None
    payload, status = _reprocess_invoice(invoice_id, 'purchase', apply_changes, supplied_flat)
    return jsonify(payload), status


@bp.route('/api/bills/<int:invoice_id>/validation', methods=['POST'])
@login_required
def set_bill_validation(invoice_id):
    """Manually mark a purchase bill OK (approve) or re-check it."""
    return _set_invoice_validation(invoice_id, 'purchase')
