"""Projects registry: /projects page, /api/projects/*, cash-payments, PO upload
and extraction, and admin normalize/uppercase endpoints."""

import os
import re
import json
import math
import traceback

import pandas as pd

from flask import (
    Blueprint, render_template, request, jsonify, send_file,
)
from werkzeug.utils import secure_filename

from config import Config, now_ist, VALID_BANK_CODES
from extensions import db_manager
from helpers.formatting import format_indian_number
from helpers.bankdata import get_bank_df
from helpers.project_finance import (
    compute_project_finance, is_other_expense_category, resolve_contract,
    PO_LEDGER_GST_RATE,
)
from helpers.bill_reconcile import (
    build_bill_vendor_index, is_unbilled_material_purchase,
)
import po_processor
import salary_api
from auth import login_required

bp = Blueprint('projects', __name__)


PROJECTS_UPLOAD_ROOT = os.path.join(Config.UPLOAD_FOLDER, 'projects')
os.makedirs(PROJECTS_UPLOAD_ROOT, exist_ok=True)

PROJECT_PO_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'xlsx', 'xls', 'docx', 'doc'}


def _project_po_allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in PROJECT_PO_EXTENSIONS


def _ledger_totals(rows):
    """Roll one ledger's rows up into the {taxable, tax, total} the ladder wants."""
    return {
        'count': len(rows),
        'taxable': round(sum(r['basic_amount'] for r in rows), 2),
        'tax': round(sum(r['tax_amount'] for r in rows), 2),
        'total': round(sum(r['total_amount'] for r in rows), 2),
    }


def _po_summary_for_response(project_id):
    """Compact PO gist for inclusion in JSON responses (or None).

    Carries the extracted baseline and both contract ledgers side by side, so
    the PO section can show the whole ladder: the document as read, the changes
    agreed to it, the work as finally measured, and the contract the rest of the
    app works from. A project with ledger rows but no gist row still answers, so
    a hand-entered contract can be varied and measured too.

    `revised` is the PO plus its variations; `final` is what is actually in
    force, which is the actuals once any exist (see resolve_contract). When
    there are none the two are equal, and every pre-actuals caller reading
    `revised` still gets the right number.
    """
    po = db_manager.get_project_po(project_id)
    variations = db_manager.list_po_ledger(project_id, 'variation')
    actuals = db_manager.list_po_ledger(project_id, 'actual')
    if not po and not variations and not actuals:
        return None
    po = po or {'project_id': project_id, 'line_items': [],
                'taxable_value': 0, 'total_tax': 0, 'total_value': 0}
    po['variations'] = variations
    po['variation_totals'] = _ledger_totals(variations)
    po['actuals'] = actuals
    po['actual_totals'] = _ledger_totals(actuals)
    contract = resolve_contract(
        {'taxable': po.get('taxable_value'), 'tax': po.get('total_tax'),
         'total': po.get('total_value')},
        po['variation_totals'], po['actual_totals'],
        has_actuals=bool(actuals),
    )
    # Keyed as the PO columns are (taxable_value/total_tax/total_value) because
    # that is what the panel and the registry cache read elsewhere.
    def _as_po_keys(c):
        return {'taxable_value': c['taxable'], 'total_tax': c['tax'],
                'total_value': c['total']}
    po['revised'] = _as_po_keys(contract['revised'])
    po['final'] = _as_po_keys(contract['final'])
    po['gst_rate'] = PO_LEDGER_GST_RATE
    po['total_value_formatted'] = format_indian_number(po['final']['total_value'])
    return po


def _run_po_extraction(project_id, abs_path, filename, *, force=False):
    """Extract a PO's gist and upsert into project_pos.

    Never raises: a failed/unavailable extraction is recorded as status
    'failed' so the uploaded file is still kept and the user can reprocess
    or enter the value by hand. Returns the stored PO gist dict (or None).
    """
    db_manager.ensure_project_pos_table()
    try:
        result = po_processor.extract_po(abs_path, filename)
    except Exception as e:
        result = {'success': False, 'error': f'extraction crashed: {e}'}

    if result.get('success'):
        data = result.get('data', {})
        db_manager.upsert_project_po(
            project_id, data,
            model=result.get('model'),
            status='success',
            error=None,
            raw_json=json.dumps(data, ensure_ascii=False),
            source_filename=filename,
            force=force,
        )
    else:
        db_manager.upsert_project_po(
            project_id, {},
            model=None,
            status='failed',
            error=result.get('error', 'extraction failed'),
            raw_json=None,
            source_filename=filename,
            force=force,
        )
    return _po_summary_for_response(project_id)


@bp.route('/projects')
@login_required
def projects_page():
    return render_template('projects.html')


def _attach_client_payments(projects):
    """Enrich each canonical project with its client-payment totals.

    Money comes in two ways:
      * `received_bank` — KVB credits captured from the bank statement. Credit
        rows are tagged with the canonical project in the same "<id> - NAME"
        form shown in the registry (e.g. "647 - POLSONS"); the id is the unique
        key, so matching is an exact id match. Untagged credits are unassigned.
      * `received_cash` — cash handed over outside the bank, recorded manually
        in the project_cash_payments ledger and keyed directly by project id.

    `received_total` is the sum of the two, which is what the cards and the
    payments-vs-PO view use.
    """
    try:
        rows = db_manager.get_kvb_credit_by_project()
    except Exception as e:
        print(f"[!] Could not load client payments: {e}")
        rows = []

    bank_by_id = {}
    for proj_str, amount in rows:
        m = re.match(r'^\s*(\d+)\s*-', proj_str or '')
        if not m:
            continue  # untagged credit — not tied to a canonical project id
        pid = int(m.group(1))
        bank_by_id[pid] = bank_by_id.get(pid, 0.0) + float(amount or 0)

    try:
        cash_by_id = db_manager.get_cash_total_by_project()
    except Exception as e:
        print(f"[!] Could not load cash payments: {e}")
        cash_by_id = {}

    for p in projects:
        pid = p.get('id')
        bank = bank_by_id.get(pid, 0.0)
        cash = cash_by_id.get(pid, 0.0)
        p['received_bank'] = bank
        p['received_cash'] = cash
        p['received_total'] = bank + cash
    return projects


def _po_and_payments_for_project(project_param):
    """Resolve a canonical "<id> - NAME" selection to its PO value and total
    client payments (bank + cash). Returns (po_value, client_payments) as
    floats; (0, 0) when no single project id can be parsed (e.g. the 'All'
    selection or an untagged value)."""
    m = re.match(r'^\s*(\d+)\s*-', project_param or '')
    if not m:
        return 0.0, 0.0
    pid = int(m.group(1))
    try:
        project = db_manager.get_project(pid)
        if not project:
            return 0.0, 0.0
        po_value = float(project.get('po_total_value') or 0)
        enriched = _attach_client_payments([project])[0]
        return po_value, float(enriched.get('received_total') or 0)
    except Exception as e:
        print(f"[!] Could not load PO/payments for project {pid}: {e}")
        return 0.0, 0.0


@bp.route('/api/projects', methods=['GET'])
@login_required
def api_list_projects():
    db_manager.ensure_projects_table()
    projects = _attach_client_payments(db_manager.list_projects())
    return jsonify({'projects': projects})


@bp.route('/api/projects', methods=['POST'])
@login_required
def api_create_project():
    """Create a new canonical project. Multipart form with optional PO file.

    Form fields:
        id          (required, integer)
        stem_name   (required, non-empty)
        po_file     (optional)
    """
    db_manager.ensure_projects_table()

    raw_id = (request.form.get('id') or '').strip()
    stem = (request.form.get('stem_name') or '').strip().upper()

    if not raw_id or not stem:
        return jsonify({'error': 'id and stem_name are required'}), 400

    # Type must be chosen explicitly — we never default a new entry to "project".
    # Accept the new project_type field, with a fallback to the legacy is_project.
    raw_type = (request.form.get('project_type') or request.form.get('is_project') or '').strip().lower()
    type_aliases = {
        '1': 'project', 'true': 'project', 'yes': 'project', 'project': 'project',
        'design': 'design', 'designs': 'design',
        '0': 'other', 'false': 'other', 'no': 'other', 'other': 'other',
    }
    project_type = type_aliases.get(raw_type)
    if project_type is None:
        return jsonify({'error': 'type_required',
                        'message': 'Choose a type: Project, Design or Other (internal).'}), 400
    try:
        project_id = int(raw_id)
    except ValueError:
        return jsonify({'error': 'id must be an integer'}), 400
    if project_id <= 0:
        return jsonify({'error': 'id must be positive'}), 400

    existing = db_manager.get_project(project_id)
    if existing:
        return jsonify({
            'error': 'duplicate_id',
            'message': f"Project id {project_id} already exists as '{existing['display']}'",
            'existing': existing,
        }), 409
    stem_clash = db_manager.find_project_by_stem(stem)
    if stem_clash:
        return jsonify({
            'error': 'duplicate_stem',
            'message': f"A project named '{stem_clash['stem_name']}' already exists with id {stem_clash['id']}",
            'existing': stem_clash,
        }), 409

    po_filename = None
    po_rel_path = None
    po_save_path = None
    file = request.files.get('po_file')
    if file and file.filename:
        if not _project_po_allowed(file.filename):
            return jsonify({'error': 'Unsupported PO file type'}), 400
        safe = secure_filename(file.filename)
        ts = now_ist().strftime('%Y%m%d_%H%M%S')
        po_filename = f"{ts}_{safe}"
        proj_dir = os.path.join(PROJECTS_UPLOAD_ROOT, str(project_id))
        os.makedirs(proj_dir, exist_ok=True)
        po_save_path = os.path.join(proj_dir, po_filename)
        po_rel_path = os.path.relpath(po_save_path, Config.UPLOAD_FOLDER).replace('\\', '/')
        file.save(po_save_path)

    ok, err = db_manager.create_project(project_id, stem, po_filename, po_rel_path, project_type)
    if not ok:
        if po_save_path and os.path.exists(po_save_path):
            try:
                os.remove(po_save_path)
            except OSError:
                pass
        if err == 'duplicate_id':
            return jsonify({'error': 'duplicate_id', 'message': 'Project id already exists'}), 409
        if err == 'duplicate_stem':
            return jsonify({'error': 'duplicate_stem', 'message': 'Project name already exists'}), 409
        return jsonify({'error': 'create_failed', 'message': err}), 500

    po_summary = None
    if po_save_path:
        po_summary = _run_po_extraction(project_id, po_save_path, po_filename, force=True)

    return jsonify({
        'success': True,
        'project': db_manager.get_project(project_id),
        'po': po_summary,
    }), 201


@bp.route('/api/projects/<int:project_id>', methods=['PATCH'])
@login_required
def api_update_project(project_id):
    """Update an existing registry entry. Supports changing the type between
    'project', 'design' and 'other', and toggling the closed (inactive) flag.

    JSON body: { "project_type": "project"|"design"|"other" }
            or: { "is_inactive": true|false }
            or: { "overhead": <number> }
    (legacy: { "is_project": true|false } is still accepted)
    """
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404

    data = request.get_json(silent=True) or {}

    # Overhead: a manually entered cost, independent of type/closed state.
    if 'overhead' in data:
        raw = data['overhead']
        try:
            overhead = float(raw if raw not in ('', None) else 0)
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid_overhead',
                            'message': 'Overhead must be a number.'}), 400
        if overhead < 0 or not math.isfinite(overhead):
            return jsonify({'error': 'invalid_overhead',
                            'message': 'Overhead must be zero or more.'}), 400
        ok, err = db_manager.set_project_overhead(project_id, overhead)
        if not ok:
            if err == 'not_found':
                return jsonify({'error': 'not_found'}), 404
            return jsonify({'error': 'update_failed', 'message': err}), 500
        return jsonify({'success': True, 'project': db_manager.get_project(project_id)})

    # Closed/active toggle is independent of the type buckets.
    if 'is_inactive' in data:
        ok, err = db_manager.set_project_inactive(project_id, bool(data['is_inactive']))
        if not ok:
            if err == 'not_found':
                return jsonify({'error': 'not_found'}), 404
            return jsonify({'error': 'update_failed', 'message': err}), 500
        return jsonify({'success': True, 'project': db_manager.get_project(project_id)})

    if 'project_type' in data:
        project_type = str(data['project_type']).strip().lower()
    elif 'is_project' in data:
        project_type = 'project' if bool(data['is_project']) else 'other'
    else:
        return jsonify({'error': 'nothing_to_update',
                        'message': 'No supported fields provided'}), 400

    if project_type not in db_manager.VALID_PROJECT_TYPES:
        return jsonify({'error': 'invalid_type',
                        'message': 'Type must be project, design or other.'}), 400

    ok, err = db_manager.set_project_type(project_id, project_type)
    if not ok:
        if err == 'not_found':
            return jsonify({'error': 'not_found'}), 404
        return jsonify({'error': 'update_failed', 'message': err}), 500

    return jsonify({'success': True, 'project': db_manager.get_project(project_id)})


def _cash_payment_summary(project_id):
    """Return the cash ledger plus the refreshed payment totals for a project,
    so the client can update the registry card without a full reload."""
    payments = db_manager.list_cash_payments(project_id)
    enriched = _attach_client_payments([db_manager.get_project(project_id)])[0]
    return {
        'payments': payments,
        'received_bank': enriched.get('received_bank', 0.0),
        'received_cash': enriched.get('received_cash', 0.0),
        'received_total': enriched.get('received_total', 0.0),
    }


@bp.route('/api/projects/<int:project_id>/cash-payments', methods=['GET'])
@login_required
def api_list_cash_payments(project_id):
    """List the cash client payments recorded against a project."""
    db_manager.ensure_projects_table()
    if not db_manager.get_project(project_id):
        return jsonify({'error': 'not_found'}), 404
    return jsonify(_cash_payment_summary(project_id))


@bp.route('/api/projects/<int:project_id>/cash-payments', methods=['POST'])
@login_required
def api_add_cash_payment(project_id):
    """Record a cash payment received from the client for this project.

    JSON body: { "amount": number (required, > 0),
                 "payment_date": "DD-MMM-YYYY" (optional),
                 "note": str (optional) }
    """
    db_manager.ensure_projects_table()
    if not db_manager.get_project(project_id):
        return jsonify({'error': 'not_found'}), 404

    data = request.get_json(silent=True) or {}
    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_amount',
                        'message': 'Amount must be a number.'}), 400
    if not (amount > 0):
        return jsonify({'error': 'invalid_amount',
                        'message': 'Amount must be greater than zero.'}), 400

    note = (data.get('note') or '').strip() or None
    payment_date = (data.get('payment_date') or '').strip() or None

    ok, err, new_id = db_manager.add_cash_payment(project_id, amount, payment_date, note)
    if not ok:
        if err == 'project_not_found':
            return jsonify({'error': 'not_found'}), 404
        return jsonify({'error': 'create_failed', 'message': err}), 500

    summary = _cash_payment_summary(project_id)
    summary['success'] = True
    summary['id'] = new_id
    return jsonify(summary), 201


@bp.route('/api/projects/<int:project_id>/cash-payments/<int:payment_id>', methods=['DELETE'])
@login_required
def api_delete_cash_payment(project_id, payment_id):
    """Remove a single recorded cash payment."""
    ok, err = db_manager.delete_cash_payment(project_id, payment_id)
    if not ok:
        if err == 'not_found':
            return jsonify({'error': 'not_found'}), 404
        return jsonify({'error': 'delete_failed', 'message': err}), 500

    summary = _cash_payment_summary(project_id)
    summary['success'] = True
    return jsonify(summary)


@bp.route('/api/projects/<int:project_id>/insights', methods=['GET'])
@login_required
def api_project_insights(project_id):
    """One-shot project picture for the registry detail modal tabs.

    Assembles, for a single canonical project:
      * client payments — KVB bank credits tagged with the project (with
        dates and statement context) plus the manual cash ledger;
      * expenses — debit transactions tagged with the project across banks;
      * purchase / sales bills — invoices whose free-text project matches;
      * labour — monthly charges pulled from the linked attendance app DB.

    All sections match strictly by the canonical "<id> -" prefix (the
    module's tagging contract — data is ingested in "<id> - <Stem>" form).
    """
    db_manager.ensure_projects_table()
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404

    def project_mask(df):
        """Rows whose Project tag is this project's canonical "<id> -" form."""
        col = 'Project' if 'Project' in df.columns else 'project'
        if col not in df.columns:
            return pd.Series(False, index=df.index)
        s = df[col].astype(str).str.strip()
        return s.str.match(rf'^{project_id}\s*-')

    def row_description(r):
        for col in ('Description', 'Transaction Description', 'transaction_description'):
            val = r.get(col)
            if val is not None and pd.notna(val) and str(val).strip():
                return str(val).strip()
        return ''

    # ── Client payments: KVB credits tagged with this project + cash ledger ──
    bank_payments = []
    bank_total = 0.0
    kvb_df = get_bank_df('kvb')
    if not kvb_df.empty and 'CR Amount' in kvb_df.columns:
        credit_rows = kvb_df[project_mask(kvb_df) & (kvb_df['CR Amount'] > 0)]
        credit_rows = credit_rows.sort_values('date', ascending=False)
        for _, r in credit_rows.iterrows():
            amount = float(r.get('CR Amount', 0))
            bank_total += amount
            bank_payments.append({
                'date': r['date'].strftime('%Y-%m-%d') if pd.notna(r['date']) else '',
                'description': row_description(r),
                'vendor': str(r.get('Client/Vendor', '') or ''),
                'amount': amount,
            })

    cash_payments = db_manager.list_cash_payments(project_id)
    cash_total = sum(float(c.get('amount') or 0) for c in cash_payments)
    received_total = bank_total + cash_total

    # ── Expenses: debit transactions tagged with this project, all banks ──
    expense_rows = []
    expense_total = 0.0
    other_expense_total = 0.0
    cat_totals = {}
    # Same buckets as cat_totals but only the categories that feed the cost
    # total, so the cost breakdown below is guaranteed to sum to spend_total.
    other_cat_totals = {}
    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code)
        if df.empty or 'DR Amount' not in df.columns:
            continue
        sub = df[project_mask(df) & (df['DR Amount'] > 0)]
        for _, r in sub.iterrows():
            amount = float(r.get('DR Amount', 0))
            category = str(r.get('Category', 'Uncategorized') or 'Uncategorized')
            expense_total += amount
            bucket = cat_totals.setdefault(category, {'amount': 0.0, 'count': 0})
            bucket['amount'] += amount
            bucket['count'] += 1
            if is_other_expense_category(category):
                other_expense_total += amount
                # Keyed on the normalised category: the membership test above is
                # case-insensitive, so keying raw would split "Site Expenses"
                # and "SITE EXPENSES" into two cost lines for the same head.
                key = category.upper().strip()
                other_cat_totals[key] = other_cat_totals.get(key, 0.0) + amount
            expense_rows.append({
                'date': r['date'].strftime('%Y-%m-%d') if pd.notna(r['date']) else '',
                'bank': bank_code,
                'description': row_description(r),
                'vendor': str(r.get('Client/Vendor', '') or ''),
                'category': category,
                'amount': amount,
            })
    expense_count = len(expense_rows)
    expense_rows.sort(key=lambda x: x['date'], reverse=True)
    expense_rows = expense_rows[:500]
    by_category = [
        {'category': c, 'amount': v['amount'], 'count': v['count']}
        for c, v in sorted(cat_totals.items(), key=lambda kv: kv[1]['amount'], reverse=True)
    ]

    # ── Purchase / sales bills ──
    purchase_bills, purchase_summary = db_manager.get_bills_for_canonical_project(
        project_id, kind='purchase')
    sales_bills, sales_summary = db_manager.get_bills_for_canonical_project(
        project_id, kind='sales')

    # ── Flag KVB material-purchase debits with no matching purchase bill ──
    # Reuses the bills just fetched, so no extra query. The tag is synthesised
    # from project_id since every expense row here already belongs to it. Count
    # is over the (capped) rows shown, which for real projects is all of them.
    bill_index = build_bill_vendor_index(purchase_bills)
    no_bill_tag = f"{project_id} -"
    no_bill_count = 0
    for er in expense_rows:
        flag = er['amount'] > 0 and is_unbilled_material_purchase(
            er['category'], no_bill_tag, er['vendor'], bill_index, er['bank'])
        er['no_bill_warning'] = flag
        if flag:
            no_bill_count += 1

    # ── Labour from the external salary API (attendance-priced server-side) ──
    labour = salary_api.get_labour_summary_for_project(
        project_id, project_display=project.get('display'))

    # Resolved: _decorate_project_row has already folded both ledgers into the
    # po_* figures, so the contract this measures against is the one actually in
    # force — the actuals if the work has been measured, otherwise the PO plus
    # any agreed variations — not the figure the PDF was signed at. None there
    # means no contract exists at all; a 0.00 means one exists and came to
    # nothing (varied away, or measured at zero).
    po_value = float(project.get('po_total_value') or 0)
    has_po = project.get('po_total_value') is not None
    labour_total = float(labour.get('total_cost') or 0)

    # The whole money model lives in helpers/project_finance so this endpoint
    # and the Excel export can't drift apart. See that module for the formulas.
    fin = compute_project_finance(
        sales={'taxable': sales_summary['total_taxable'],
               'gst': sales_summary['total_gst'],
               'total': sales_summary['total_amount']},
        purchase={'taxable': purchase_summary['total_taxable'],
                  'gst': purchase_summary['total_gst'],
                  'total': purchase_summary['total_amount']},
        po={'taxable': project.get('po_taxable_value'),
            'gst': project.get('po_total_tax'),
            'total': po_value},
        received_total=received_total,
        other_expense_total=other_expense_total,
        labour_total=labour_total,
        overhead=project.get('overhead'),
        other_cat_totals=other_cat_totals,
        has_po=has_po,
    )

    return jsonify({
        'project': project,
        'summary': {
            'po_value': po_value,
            'received_bank': bank_total,
            'received_cash': cash_total,
            'received_total': received_total,
            # Kept for backward compatibility with existing readers. Aliases
            # `receivable` outright rather than recomputing `po_value -
            # received`: the two agree whenever a PO exists, but a project with
            # no PO (or one varied down to zero) measures against the billed
            # total, and recomputing here would ship two contradictory balances
            # in one response.
            'balance': fin['receivable'],
            # When the attendance app is unreachable, labour comes back as 0 and
            # the cost total quietly loses it — which overstates profit. The UI
            # needs to know the figure is incomplete rather than just low.
            'labour_available': labour.get('available') is not False,
            **fin,
        },
        'payments': {
            'bank': bank_payments,
            'cash': cash_payments,
            'bank_total': bank_total,
            'cash_total': cash_total,
            'total': received_total,
        },
        'expenses': {
            'transactions': expense_rows,
            'total': expense_total,
            'count': expense_count,
            'by_category': by_category,
            'no_bill_count': no_bill_count,
        },
        'purchase_bills': {'bills': purchase_bills, **purchase_summary},
        'sales_bills': {'bills': sales_bills, **sales_summary},
        'labour': labour,
    })


@bp.route('/api/projects/<int:project_id>/export')
@login_required
def api_export_project(project_id):
    """Per-project Excel export, structured like this project's detail pop-up."""
    from reports.project_summary_export import export_single_project_summary
    return export_single_project_summary(project_id)


@bp.route('/api/projects/<int:project_id>/upload-po', methods=['POST'])
@login_required
def api_upload_project_po(project_id):
    """Attach a PO file to an existing project that has no PO yet."""
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404
    if project['has_po']:
        return jsonify({'error': 'po_already_attached',
                        'message': 'This project already has a PO; editing is disabled.'}), 409

    file = request.files.get('po_file')
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400
    if not _project_po_allowed(file.filename):
        return jsonify({'error': 'Unsupported PO file type'}), 400

    safe = secure_filename(file.filename)
    ts = now_ist().strftime('%Y%m%d_%H%M%S')
    po_filename = f"{ts}_{safe}"
    proj_dir = os.path.join(PROJECTS_UPLOAD_ROOT, str(project_id))
    os.makedirs(proj_dir, exist_ok=True)
    po_save_path = os.path.join(proj_dir, po_filename)
    po_rel_path = os.path.relpath(po_save_path, Config.UPLOAD_FOLDER).replace('\\', '/')
    file.save(po_save_path)

    ok, err = db_manager.attach_project_po(project_id, po_filename, po_rel_path)
    if not ok:
        if os.path.exists(po_save_path):
            try:
                os.remove(po_save_path)
            except OSError:
                pass
        return jsonify({'error': err or 'attach_failed'}), 409

    po_summary = _run_po_extraction(project_id, po_save_path, po_filename, force=True)

    return jsonify({
        'success': True,
        'project': db_manager.get_project(project_id),
        'po': po_summary,
    })


@bp.route('/api/admin/normalize-projects', methods=['POST'])
@login_required
def api_admin_normalize_projects():
    """One-shot bulk normalization: rewrite any project value matching a canonical
    keyword to the canonical "<id> - <Stem>" form. Idempotent — safe to re-run.

    Body / query: ?apply=1  to commit. Default is dry-run.
    """
    apply_changes = (
        request.args.get('apply') == '1' or
        (request.get_json(silent=True) or {}).get('apply') is True
    )

    mappings = [
        ('663 - Siruvani',       ['siruvani']),
        ('662 - Infinium',       ['infinium']),
        ('659 - Jamuna',         ['jamuna']),
        ('664 - Vetha Kuzhumam', ['vetha', 'kuzhum']),
    ]
    # Expense Tracker (personal_transactions) is intentionally excluded — that
    # module keeps its free-text project field.
    tables = ['axis_transactions', 'kvb_transactions', 'transactions',
              'bill_invoices', 'sales_invoices']

    report = {'apply': apply_changes, 'tables': {}, 'totals': {'preview': 0, 'applied': 0}}

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SHOW TABLES")
            present = {r[0].lower() for r in cursor.fetchall()}

            for tbl in tables:
                if tbl.lower() not in present:
                    continue

                table_block = []
                for canonical, keywords in mappings:
                    like_clauses = " OR ".join(["project LIKE %s"] * len(keywords))
                    like_params = [f"%{kw}%" for kw in keywords]

                    cursor.execute(
                        f"SELECT TRIM(project) AS p, COUNT(*) "
                        f"FROM `{tbl}` "
                        f"WHERE project IS NOT NULL AND ({like_clauses}) AND project <> %s "
                        f"GROUP BY TRIM(project) ORDER BY 2 DESC",
                        tuple(like_params + [canonical])
                    )
                    variants = [{'value': v, 'count': c} for v, c in cursor.fetchall()]
                    if not variants:
                        continue

                    total = sum(v['count'] for v in variants)
                    block = {'canonical': canonical, 'variants': variants, 'preview_rows': total}
                    report['totals']['preview'] += total

                    if apply_changes:
                        cursor.execute(
                            f"UPDATE `{tbl}` SET project = %s "
                            f"WHERE project IS NOT NULL AND ({like_clauses}) AND project <> %s",
                            tuple([canonical] + like_params + [canonical])
                        )
                        block['applied_rows'] = cursor.rowcount
                        report['totals']['applied'] += cursor.rowcount

                    table_block.append(block)

                if table_block:
                    report['tables'][tbl] = table_block

            if apply_changes:
                conn.commit()
            cursor.close()
        return jsonify(report)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/admin/uppercase-canonical-stems', methods=['POST'])
@login_required
def api_admin_uppercase_stems():
    """One-shot: uppercase every project stem in the registry and propagate
    the change to every data table that references that canonical display.

    ?apply=1 to commit. Default is dry-run. Idempotent.
    """
    apply_changes = (
        request.args.get('apply') == '1' or
        (request.get_json(silent=True) or {}).get('apply') is True
    )
    DATA_TABLES = ['axis_transactions', 'kvb_transactions', 'transactions',
                   'bill_invoices', 'sales_invoices']

    report = {'apply': apply_changes, 'projects': [], 'data_tables': {}}

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)

            cursor.execute("SHOW TABLES")
            present = {list(r.values())[0].lower() for r in cursor.fetchall()}

            cursor.execute("SELECT id, stem_name FROM projects ORDER BY id")
            projects = cursor.fetchall()

            cursor_write = conn.cursor()
            for proj in projects:
                old_stem = proj['stem_name']
                new_stem = old_stem.upper()
                if old_stem == new_stem:
                    continue
                pid = proj['id']
                old_display = f"{pid} - {old_stem}"
                new_display = f"{pid} - {new_stem}"
                entry = {'id': pid, 'old': old_display, 'new': new_display}
                report['projects'].append(entry)

                # Preview / apply propagation into data tables
                for tbl in DATA_TABLES:
                    if tbl not in present:
                        continue
                    cursor_write.execute(
                        f"SELECT COUNT(*) FROM `{tbl}` WHERE project = %s",
                        (old_display,)
                    )
                    n = cursor_write.fetchone()[0]
                    if n == 0:
                        continue
                    report['data_tables'].setdefault(tbl, []).append(
                        {'old': old_display, 'new': new_display, 'preview_rows': n}
                    )
                    if apply_changes:
                        cursor_write.execute(
                            f"UPDATE `{tbl}` SET project = %s WHERE project = %s",
                            (new_display, old_display)
                        )

                if apply_changes:
                    cursor_write.execute(
                        "UPDATE projects SET stem_name = %s WHERE id = %s",
                        (new_stem, pid)
                    )

            if apply_changes:
                conn.commit()
            cursor.close()
            cursor_write.close()
        return jsonify(report)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/projects/<int:project_id>/po', methods=['GET'])
@login_required
def api_download_project_po(project_id):
    project = db_manager.get_project(project_id)
    if not project or not project.get('po_path'):
        return jsonify({'error': 'not_found'}), 404
    abs_path = os.path.join(Config.UPLOAD_FOLDER, project['po_path'])
    if not os.path.exists(abs_path):
        return jsonify({'error': 'file_missing_on_disk'}), 410
    return send_file(abs_path, as_attachment=False, download_name=project['po_filename'])


@bp.route('/api/projects/<int:project_id>/po-data', methods=['GET'])
@login_required
def api_get_project_po_data(project_id):
    """Return the extracted PO gist for a project (for the detail view)."""
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404
    po = _po_summary_for_response(project_id)
    return jsonify({'project_id': project_id, 'po': po})


@bp.route('/api/projects/<int:project_id>/process-po', methods=['POST'])
@login_required
def api_process_project_po(project_id):
    """(Re)run AI extraction on a project's already-attached PO file."""
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404
    if not project.get('po_path'):
        return jsonify({'error': 'no_po', 'message': 'No PO file is attached to this project.'}), 400

    abs_path = os.path.join(Config.UPLOAD_FOLDER, project['po_path'])
    if not os.path.exists(abs_path):
        return jsonify({'error': 'file_missing_on_disk'}), 410

    po_summary = _run_po_extraction(
        project_id, abs_path, project.get('po_filename') or os.path.basename(abs_path),
        force=True,
    )
    failed = po_summary and po_summary.get('extraction_status') == 'failed'
    return jsonify({
        'success': not failed,
        'po': po_summary,
        'message': (po_summary or {}).get('extraction_error') if failed else None,
    })


@bp.route('/api/projects/<int:project_id>/po-data', methods=['PUT'])
@login_required
def api_update_project_po_data(project_id):
    """Save user-corrected PO gist fields (flips status to 'manual')."""
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404

    fields = request.get_json(silent=True) or {}
    ok, err = db_manager.update_project_po_fields(project_id, fields)
    if not ok:
        if err == 'no_editable_fields':
            return jsonify({'error': err, 'message': 'No editable fields supplied.'}), 400
        return jsonify({'error': 'update_failed', 'message': err}), 400
    return jsonify({'success': True, 'po': _po_summary_for_response(project_id)})


# ── PO ledgers: variations and actuals ──────────────────────────────────────
# Two ways a signed contract moves, sharing one set of routes because they share
# one row shape (see DatabaseManager.PO_LEDGERS):
#
#   po-variations  changes agreed after signing — extra tonnage, or scope
#                  dropped. Deltas, added to the PO.
#   po-actuals     the work as finally measured. An absolute restatement that
#                  replaces the PO and its variations outright, because a
#                  project that came in under its PO can't honestly be written
#                  as a big negative variation.
#
# Either way the extracted gist stays untouched, so the contract value moves
# without the stored PO drifting from the PDF behind "View PO document".

# The URL slug is the only thing a caller controls, and it is a fixed set here
# — `kind` never reaches the ledger CRUD as free text.
_LEDGER_SLUGS = {'po-variations': 'variation', 'po-actuals': 'actual'}
_LEDGER_SLUG_RULE = '<any("po-variations", "po-actuals"):slug>'
_LEDGER_GONE = {'variation': 'That variation no longer exists.',
                'actual': 'That actuals entry no longer exists.'}


@bp.route(f'/api/projects/<int:project_id>/{_LEDGER_SLUG_RULE}', methods=['POST'])
@login_required
def api_add_po_ledger_row(project_id, slug):
    """Record one variation, or one line of the work as actually measured."""
    kind = _LEDGER_SLUGS[slug]
    if not db_manager.get_project(project_id):
        return jsonify({'error': 'not_found'}), 404
    row, err = db_manager.add_po_ledger_row(
        project_id, kind, request.get_json(silent=True) or {})
    if err:
        return jsonify({'error': 'invalid', 'message': err}), 400
    return jsonify({'success': True, 'row': row,
                    'po': _po_summary_for_response(project_id)})


@bp.route(f'/api/projects/<int:project_id>/{_LEDGER_SLUG_RULE}/<int:row_id>', methods=['PUT'])
@login_required
def api_update_po_ledger_row(project_id, slug, row_id):
    kind = _LEDGER_SLUGS[slug]
    row, err = db_manager.update_po_ledger_row(
        project_id, kind, row_id, request.get_json(silent=True) or {})
    if err == 'not_found':
        return jsonify({'error': 'not_found', 'message': _LEDGER_GONE[kind]}), 404
    if err:
        return jsonify({'error': 'invalid', 'message': err}), 400
    return jsonify({'success': True, 'row': row,
                    'po': _po_summary_for_response(project_id)})


@bp.route(f'/api/projects/<int:project_id>/{_LEDGER_SLUG_RULE}/<int:row_id>', methods=['DELETE'])
@login_required
def api_delete_po_ledger_row(project_id, slug, row_id):
    kind = _LEDGER_SLUGS[slug]
    ok, err = db_manager.delete_po_ledger_row(project_id, kind, row_id)
    if err == 'not_found':
        return jsonify({'error': 'not_found', 'message': _LEDGER_GONE[kind]}), 404
    if not ok:
        return jsonify({'error': 'delete_failed', 'message': err}), 400
    return jsonify({'success': True, 'po': _po_summary_for_response(project_id)})
