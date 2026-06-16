"""Sales bills: /sales-processor + /api/sales/* endpoints."""

import os

from flask import (
    Blueprint, render_template, request, jsonify, send_file,
)
from werkzeug.utils import secure_filename

from config import Config, now_ist
from extensions import db_manager
from bill_processor import process_bill_file, generate_excel, format_extracted_data_for_display
from helpers.projects import validate_project_value
from helpers.invoices import (
    extract_project_from_filename, _reprocess_invoice, _set_invoice_validation,
)
from auth import login_required

bp = Blueprint('sales', __name__)


@bp.route('/api/sales/reprocess/<int:invoice_id>', methods=['POST'])
@login_required
def reprocess_sales_bill(invoice_id):
    """Re-extract a sales bill from its PDF; preview or apply (clean-only)."""
    body = request.json or {}
    apply_changes = bool(body.get('apply', False))
    supplied_flat = body.get('extraction') if apply_changes else None
    payload, status = _reprocess_invoice(invoice_id, 'sales', apply_changes, supplied_flat)
    return jsonify(payload), status


@bp.route('/api/sales/<int:invoice_id>/validation', methods=['POST'])
@login_required
def set_sales_validation(invoice_id):
    """Manually mark a sales bill OK (approve) or re-check it."""
    return _set_invoice_validation(invoice_id, 'sales')


@bp.route('/sales-processor')
@login_required
def sales_processor_page():
    """Render sales processor page"""
    # Ensure sales tables exist
    db_manager.ensure_sales_tables()
    # Ensure the reconciliation/validation columns exist (additive migration).
    db_manager.ensure_validation_columns()
    return render_template('sales_processor.html')


@bp.route('/api/sales/process', methods=['POST'])
@login_required
def process_sales_bill():
    """Process an uploaded sales bill image/PDF and extract data using Gemini Vision"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.pdf', '.webp'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

        # Save file with sales_ prefix
        filename = secure_filename(file.filename)
        timestamp = now_ist().strftime('%Y%m%d_%H%M%S')
        temp_filename = f"sales_{timestamp}_{filename}"
        temp_path = os.path.join(Config.UPLOAD_FOLDER, temp_filename)

        file.save(temp_path)

        # Auto-extract project name from original filename
        project_name = extract_project_from_filename(file.filename)

        # Process the bill (uses same AI extraction as purchase bills)
        results = process_bill_file(temp_path, filename)

        # Save to database (with duplicate check)
        db_results = []
        for bill in results:
            if bill.get('success'):
                invoice_number = bill.get('data', {}).get('invoice_header', {}).get('invoice_number', '')

                # Check for duplicate invoice before saving
                existing_bill = db_manager.check_duplicate_sales_invoice(invoice_number)
                if existing_bill:
                    db_results.append({
                        'saved': False,
                        'invoice_id': None,
                        'db_error': 'Duplicate invoice',
                        'is_duplicate': True,
                        'existing_bill': existing_bill
                    })
                    continue

                # Insert into sales tables
                success, invoice_id, error = db_manager.insert_sales_bill(bill)
                db_results.append({
                    'saved': success,
                    'invoice_id': invoice_id,
                    'db_error': error,
                    'is_duplicate': False
                })

                # Auto-assign project name from filename only if it maps to a canonical project
                if success and invoice_id and project_name:
                    ok, normalized, _ = validate_project_value(project_name)
                    if ok and normalized:
                        db_manager.update_sales_bill_project(invoice_id, normalized)
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


@bp.route('/api/sales/download', methods=['POST'])
@login_required
def download_sales_excel():
    """Generate and download Excel file from extracted sales data"""
    try:
        data = request.json
        results = data.get('results', [])

        if not results:
            return jsonify({'error': 'No data to download'}), 400

        excel_buffer = generate_excel(results)
        filename = f"sales_extracted_{now_ist().strftime('%Y%m%d_%H%M%S')}.xlsx"

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


@bp.route('/api/sales/stored')
@login_required
def get_stored_sales_bills():
    """Get all stored sales bills from database with optional filters"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
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

        bills = db_manager.get_all_sales_bills(limit=limit, offset=offset, projects=projects_list,
                                                date_from=date_from, date_to=date_to,
                                                added_from=added_from, added_to=added_to)
        total = db_manager.get_sales_bill_count(projects=projects_list, date_from=date_from, date_to=date_to,
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


@bp.route('/api/sales/stored/<int:invoice_id>')
@login_required
def get_stored_sales_bill_detail(invoice_id):
    """Get detailed sales bill information including line items"""
    try:
        bill = db_manager.get_sales_bill_detail(invoice_id)

        if not bill:
            return jsonify({'success': False, 'error': 'Sales bill not found'}), 404

        return jsonify({
            'success': True,
            'bill': bill
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/sales/stored/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_stored_sales_bill(invoice_id):
    """Delete a stored sales bill"""
    try:
        success = db_manager.delete_sales_bill(invoice_id)

        if success:
            return jsonify({'success': True, 'message': 'Sales bill deleted'})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete sales bill'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/sales/stored/<int:invoice_id>/project', methods=['PUT'])
@login_required
def update_sales_bill_project(invoice_id):
    """Update the project field for a sales bill"""
    try:
        data = request.json
        ok, project, perr = validate_project_value((data or {}).get('project'))
        if not ok:
            return jsonify({'success': False, 'error': perr}), 400

        success = db_manager.update_sales_bill_project(invoice_id, project)

        if success:
            return jsonify({'success': True, 'message': 'Project updated', 'project': project})
        else:
            return jsonify({'success': False, 'error': 'Failed to update project'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/sales/projects')
@login_required
def get_sales_projects():
    """Get all unique project names from sales bills"""
    try:
        projects = db_manager.get_unique_sales_projects()
        return jsonify({
            'success': True,
            'projects': projects
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/sales/summary')
@login_required
def get_sales_summary():
    """Get summary statistics for stored sales bills"""
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
        FROM sales_invoices
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


@bp.route('/api/sales/stats')
@login_required
def get_sales_stats():
    """Get sales bill stats for hub page"""
    try:
        invoice_count = db_manager.get_sales_bill_count()
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


@bp.route('/api/sales/file/<filename>')
@login_required
def serve_sales_file(filename):
    """Serve uploaded sales bill file (PDF or image) for preview"""
    import glob as glob_module

    try:
        if '..' in filename or '/' in filename or '\\' in filename:
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        file_path = os.path.join(Config.UPLOAD_FOLDER, filename)

        if not os.path.exists(file_path):
            # Search for files with sales_ prefix
            pattern = os.path.join(Config.UPLOAD_FOLDER, f"sales_*_{filename}")
            matches = glob_module.glob(pattern)

            if matches:
                file_path = sorted(matches)[-1]
            else:
                return jsonify({'success': False, 'error': 'File not found'}), 404

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


@bp.route('/api/sales/upload-files', methods=['POST'])
@login_required
def bulk_upload_sales_files():
    """Bulk upload sales bill files without processing."""
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

            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                results.append({
                    'filename': file.filename,
                    'status': 'skipped',
                    'reason': f'Unsupported file type: {ext}'
                })
                skipped_count += 1
                continue

            filename = secure_filename(file.filename)
            file_path = os.path.join(Config.UPLOAD_FOLDER, filename)

            if os.path.exists(file_path):
                results.append({
                    'filename': filename,
                    'status': 'skipped',
                    'reason': 'File already exists'
                })
                skipped_count += 1
                continue

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


@bp.route('/api/sales/stored/<int:invoice_id>', methods=['PUT'])
@login_required
def update_stored_sales_bill(invoice_id):
    """Update a stored sales bill with all fields and line items"""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        if 'project' in data:
            ok, normalized, perr = validate_project_value(data.get('project'))
            if not ok:
                return jsonify({'success': False, 'error': perr}), 400
            data['project'] = normalized

        success, error = db_manager.update_sales_bill(invoice_id, data)

        if success:
            return jsonify({'success': True, 'message': 'Sales invoice updated successfully'})
        else:
            return jsonify({'success': False, 'error': error or 'Failed to update sales invoice'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
