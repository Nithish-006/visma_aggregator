"""Excel export for the Project Summary page.

Moved verbatim out of app.py (it was a ~1290-line route body). The
project_summary blueprint exposes /api/project-summary/export as a thin route
that calls export_project_summary() here. openpyxl is imported lazily inside
the function, as in the original.
"""

import io
import re
import traceback
from datetime import datetime

import pandas as pd

from flask import request, jsonify, send_file

from config import VALID_BANK_CODES, get_bank_config, now_ist
from extensions import db_manager
import salary_api
from helpers.bankdata import get_bank_df
from helpers.dataframe import (
    filter_by_date_range, filter_by_category, filter_by_vendor, robust_filter_by_project,
)
from helpers.projects import (
    get_project_stems, build_smart_project_groups, match_bills_to_project_groups,
    match_labour_to_project_groups, normalize_project_stem, parse_project_selection,
    project_value_matches_selection,
)


def export_project_summary():
    """Export professional project summary report as multi-tab Excel"""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    project = request.args.get('project', None)
    category = request.args.get('category', None)
    vendor = request.args.get('vendor', None)

    # Gather combined data
    combined_rows = []
    for bank_code in VALID_BANK_CODES:
        df = get_bank_df(bank_code).copy()
        if df.empty:
            continue
        df = filter_by_date_range(df, start_date, end_date)
        df = robust_filter_by_project(df, project)
        df = filter_by_category(df, category)
        df = filter_by_vendor(df, vendor)
        if df.empty:
            continue
        df['bank'] = bank_code
        combined_rows.append(df)

    if not combined_rows:
        combined = pd.DataFrame()
    else:
        combined = pd.concat(combined_rows, ignore_index=True)

    # Style constants
    header_font = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
    title_font = Font(name='Calibri', bold=True, size=14, color='1A1A2E')
    subtitle_font = Font(name='Calibri', bold=True, size=11, color='4A4A68')
    currency_fmt = '#,##0.00'
    pct_fmt = '0.0%'
    thin_border = Border(
        bottom=Side(style='thin', color='E5E7EB')
    )
    income_font = Font(name='Calibri', color='059669', bold=True)
    expense_font = Font(name='Calibri', color='DC2626', bold=True)
    axis_fill = PatternFill(start_color='FDF2F8', end_color='FDF2F8', fill_type='solid')
    kvb_fill = PatternFill(start_color='EFF6FF', end_color='EFF6FF', fill_type='solid')

    def style_header_row(ws, row_num, col_count):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center')

    def auto_width(ws):
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                try:
                    val = str(cell.value) if cell.value else ''
                    max_len = max(max_len, len(val))
                except:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 3, 40)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # ──────────────────────────────────────────────────────────
        # TAB 1: Executive Summary
        # ──────────────────────────────────────────────────────────
        kvb_export_df = combined[combined['bank'] == 'kvb'] if not combined.empty else pd.DataFrame()
        axis_export_df = combined[combined['bank'] == 'axis'] if not combined.empty else pd.DataFrame()
        total_income = float(kvb_export_df['CR Amount'].sum()) if not kvb_export_df.empty else 0
        total_bank_transfer = float(axis_export_df['CR Amount'].sum()) if not axis_export_df.empty else 0
        total_credit_all = float(combined['CR Amount'].sum()) if not combined.empty else 0
        total_expense = float(combined['DR Amount'].sum()) if not combined.empty else 0
        txn_count = len(combined) if not combined.empty else 0

        date_label = ''
        if start_date and end_date:
            date_label = f"{start_date} to {end_date}"
        elif start_date:
            date_label = f"From {start_date}"
        elif end_date:
            date_label = f"Up to {end_date}"
        else:
            date_label = 'All Time'

        summary_data = [
            ['VISMA Financial - Project Summary Report'],
            [''],
            ['Report Period', date_label],
            ['Generated On', now_ist().strftime('%d-%b-%Y %H:%M')],
            [''],
            ['KEY PERFORMANCE INDICATORS'],
            [''],
            ['Metric', 'Value'],
            ['Total Income (KVB)', total_income],
            ['Total Bank Transfer (Axis)', total_bank_transfer],
            ['Total Expense', total_expense],
            ['Total Transactions', txn_count],
            ['Expense Ratio', total_expense / total_income if total_income > 0 else 0],
            ['Average Transaction Size', (total_income + total_bank_transfer + total_expense) / txn_count if txn_count > 0 else 0],
        ]

        # Per-bank KPIs
        summary_data.append([''])
        summary_data.append(['BANK-WISE SUMMARY'])
        summary_data.append([''])
        summary_data.append(['Bank', 'Income / Bank Transfer', 'Expense', 'Net', 'Transactions', '% of Total Expense'])

        for bc in VALID_BANK_CODES:
            if combined.empty:
                continue
            bdf = combined[combined['bank'] == bc]
            if bdf.empty:
                continue
            b_inc = float(bdf['CR Amount'].sum())
            b_exp = float(bdf['DR Amount'].sum())
            b_net = b_inc - b_exp
            b_cnt = len(bdf)
            b_pct = b_exp / total_expense if total_expense > 0 else 0
            bank_name = get_bank_config(bc)['name']
            summary_data.append([bank_name, b_inc, b_exp, b_net, b_cnt, b_pct])

        # Active filters
        summary_data.append([''])
        summary_data.append(['APPLIED FILTERS'])
        summary_data.append([''])
        if project:
            summary_data.append(['Project Filter', project])
        if category:
            summary_data.append(['Category Filter', category])
        if vendor:
            summary_data.append(['Vendor Filter', vendor])
        if not project and not category and not vendor:
            summary_data.append(['Filters', 'None (all data)'])

        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name='Executive Summary', index=False, header=False)

        ws = writer.sheets['Executive Summary']
        ws.cell(row=1, column=1).font = title_font
        ws.cell(row=6, column=1).font = subtitle_font
        ws.cell(row=8, column=1).font = header_font
        ws.cell(row=8, column=1).fill = header_fill
        ws.cell(row=8, column=2).font = header_font
        ws.cell(row=8, column=2).fill = header_fill

        # Format currency cells
        for r in range(9, 15):
            cell = ws.cell(row=r, column=2)
            if r == 12:  # Transaction count
                pass
            elif r == 13:  # Expense ratio
                cell.number_format = pct_fmt
            else:
                cell.number_format = currency_fmt
            if r == 9:   # Total Income (KVB)
                cell.font = income_font
            elif r == 10:  # Total Bank Transfer (Axis)
                cell.font = Font(color='2563EB', bold=True)
            elif r == 11:  # Total Expense
                cell.font = expense_font

        # Style bank summary header
        bank_header_row = None
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=1):
            for cell in row:
                if cell.value == 'Bank':
                    bank_header_row = cell.row
                    break
        if bank_header_row:
            style_header_row(ws, bank_header_row, 6)
            for r in range(bank_header_row + 1, ws.max_row + 1):
                c = ws.cell(row=r, column=1)
                if c.value and ('Axis' in str(c.value) or 'KVB' in str(c.value) or 'Karur' in str(c.value)):
                    for col in range(2, 5):
                        ws.cell(row=r, column=col).number_format = currency_fmt
                    ws.cell(row=r, column=6).number_format = pct_fmt

        # Style filters header
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=1):
            for cell in row:
                if cell.value == 'BANK-WISE SUMMARY' or cell.value == 'APPLIED FILTERS':
                    cell.font = subtitle_font

        auto_width(ws)
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 20

        # ──────────────────────────────────────────────────────────
        # TAB 2: Expense Breakdown (by Category)
        # ──────────────────────────────────────────────────────────
        if not combined.empty:
            expense_df = combined[combined['DR Amount'] > 0]
            if not expense_df.empty:
                cat_data = expense_df.groupby('Category').agg(
                    Total_Expense=('DR Amount', 'sum')
                ).sort_values('Total_Expense', ascending=False).reset_index()

                total_exp = cat_data['Total_Expense'].sum()

                cat_data.columns = ['Category', 'Total Expense']

                cat_data.to_excel(writer, sheet_name='Expense Breakdown', index=False, startrow=2)
                ws2 = writer.sheets['Expense Breakdown']
                ws2.cell(row=1, column=1, value='Expense Breakdown by Category').font = title_font
                style_header_row(ws2, 3, 2)

                for r in range(4, 4 + len(cat_data)):
                    ws2.cell(row=r, column=2).number_format = currency_fmt

                # Add total row
                total_row = 4 + len(cat_data)
                ws2.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
                ws2.cell(row=total_row, column=2, value=total_exp).font = Font(bold=True)
                ws2.cell(row=total_row, column=2).number_format = currency_fmt

                auto_width(ws2)
            else:
                pd.DataFrame({'Note': ['No expense data for the selected filters']}).to_excel(
                    writer, sheet_name='Expense Breakdown', index=False)

        # ──────────────────────────────────────────────────────────
        # TAB 3: Cashflow Analysis (by Project)
        # ──────────────────────────────────────────────────────────
        if not combined.empty:
            project_col = 'Project' if 'Project' in combined.columns else 'project'
            if project_col in combined.columns:
                proj_income = combined.groupby(project_col)['CR Amount'].sum()
                proj_expense = combined.groupby(project_col)['DR Amount'].sum()
                all_projects_list = sorted(set(proj_income.index) | set(proj_expense.index))

                proj_rows = []
                for p in all_projects_list:
                    p_inc = float(proj_income.get(p, 0))
                    p_exp = float(proj_expense.get(p, 0))
                    proj_rows.append({
                        'Project': str(p) if p and str(p) != 'nan' else 'Unassigned',
                        'Income': p_inc, 'Expense': p_exp
                    })

                df_proj = pd.DataFrame(proj_rows).sort_values('Expense', ascending=False)
                df_proj.to_excel(writer, sheet_name='Cashflow Analysis', index=False, startrow=2)

                ws3 = writer.sheets['Cashflow Analysis']
                ws3.cell(row=1, column=1, value='Project Cashflow Analysis').font = title_font
                style_header_row(ws3, 3, 3)

                for r in range(4, 4 + len(df_proj)):
                    for c in [2, 3]:
                        ws3.cell(row=r, column=c).number_format = currency_fmt

                # Add total row
                total_row = 4 + len(df_proj)
                ws3.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
                ws3.cell(row=total_row, column=2, value=total_credit_all).font = Font(bold=True)
                ws3.cell(row=total_row, column=2).number_format = currency_fmt
                ws3.cell(row=total_row, column=3, value=total_expense).font = Font(bold=True)
                ws3.cell(row=total_row, column=3).number_format = currency_fmt

                auto_width(ws3)

        # ──────────────────────────────────────────────────────────
        # TAB 4: Vendor Breakdown
        # ──────────────────────────────────────────────────────────
        if not combined.empty:
            expense_df = combined[combined['DR Amount'] > 0]
            vendor_col = 'Client/Vendor' if 'Client/Vendor' in combined.columns else 'client_vendor'
            if vendor_col in combined.columns and not expense_df.empty:
                vendor_data = expense_df.groupby(vendor_col).agg(
                    Total_Expense=('DR Amount', 'sum')
                ).sort_values('Total_Expense', ascending=False).reset_index()

                total_v_exp = vendor_data['Total_Expense'].sum()

                vendor_data.columns = ['Vendor', 'Total Expense']

                vendor_data.to_excel(writer, sheet_name='Vendor Breakdown', index=False, startrow=2)

                ws4 = writer.sheets['Vendor Breakdown']
                ws4.cell(row=1, column=1, value='Vendor Expense Breakdown').font = title_font
                style_header_row(ws4, 3, 2)

                for r in range(4, 4 + len(vendor_data)):
                    ws4.cell(row=r, column=2).number_format = currency_fmt

                # Total row
                total_row = 4 + len(vendor_data)
                ws4.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
                ws4.cell(row=total_row, column=2, value=total_v_exp).font = Font(bold=True)
                ws4.cell(row=total_row, column=2).number_format = currency_fmt

                auto_width(ws4)
            else:
                pd.DataFrame({'Note': ['No vendor expense data for the selected filters']}).to_excel(
                    writer, sheet_name='Vendor Breakdown', index=False)

        # ──────────────────────────────────────────────────────────
        # TAB 5 & 6: Bank-wise Transactions (one tab per bank)
        # ──────────────────────────────────────────────────────────
        for bc in VALID_BANK_CODES:
            bank_config = get_bank_config(bc)
            sheet_name = f"{bank_config['name']} Txns"
            if len(sheet_name) > 31:
                sheet_name = sheet_name[:31]

            if combined.empty:
                pd.DataFrame({'Note': ['No data']}).to_excel(writer, sheet_name=sheet_name, index=False)
                continue

            bdf = combined[combined['bank'] == bc].sort_values('date', ascending=False).copy()
            if bdf.empty:
                pd.DataFrame({'Note': [f'No transactions for {bank_config["name"]}']}).to_excel(
                    writer, sheet_name=sheet_name, index=False)
                continue

            bdf['Date'] = bdf['date'].dt.strftime('%d-%m-%Y')
            export_cols = {
                'Date': 'Date',
                'Client/Vendor': 'Vendor',
                'Category': 'Category',
                'Project': 'Project',
                'DR Amount': 'Debit (₹)',
                'CR Amount': 'Credit (₹)'
            }

            df_export = pd.DataFrame()
            for src, dst in export_cols.items():
                if src in bdf.columns:
                    df_export[dst] = bdf[src]
                elif src.lower() in bdf.columns:
                    df_export[dst] = bdf[src.lower()]
                else:
                    df_export[dst] = None

            df_export.to_excel(writer, sheet_name=sheet_name, index=False, startrow=2)

            ws_b = writer.sheets[sheet_name]
            ws_b.cell(row=1, column=1, value=f'{bank_config["name"]} - Transaction Details').font = title_font
            style_header_row(ws_b, 3, len(df_export.columns))

            for r in range(4, 4 + len(df_export)):
                ws_b.cell(row=r, column=5).number_format = currency_fmt
                ws_b.cell(row=r, column=6).number_format = currency_fmt
                dr_val = ws_b.cell(row=r, column=5).value
                cr_val = ws_b.cell(row=r, column=6).value
                if dr_val and float(dr_val) > 0:
                    ws_b.cell(row=r, column=5).font = expense_font
                if cr_val and float(cr_val) > 0:
                    ws_b.cell(row=r, column=6).font = income_font

            # Bank subtotals
            total_row = 4 + len(df_export)
            ws_b.cell(row=total_row, column=1, value='TOTAL').font = Font(bold=True)
            ws_b.cell(row=total_row, column=5, value=float(bdf['DR Amount'].sum())).font = Font(bold=True)
            ws_b.cell(row=total_row, column=5).number_format = currency_fmt
            ws_b.cell(row=total_row, column=6, value=float(bdf['CR Amount'].sum())).font = Font(bold=True)
            ws_b.cell(row=total_row, column=6).number_format = currency_fmt

            auto_width(ws_b)

        # ──────────────────────────────────────────────────────────
        # TAB 7 & 8: Purchase Bills / Sales Bills (project-grouped)
        # ──────────────────────────────────────────────────────────
        # Shared auditor-format styles (reused by Project Breakdown tab too)
        green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        block_bg = PatternFill(start_color='FFFDE7', end_color='FFFDE7', fill_type='solid')  # mild yellow
        project_name_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        project_name_font = Font(name='Calibri', bold=True, size=14, color='FFFFFF')
        separator_fill = PatternFill(start_color='2F2F2F', end_color='2F2F2F', fill_type='solid')

        # Shared helper: writes a project-grouped bills sheet
        def write_bills_sheet(ws, bills_by_stem_local, stem_groups_local,
                              sheet_title, party_label, party_key, gstin_key,
                              total_font):
            """Write a project-grouped bills sheet with expanded line items.

            party_label: 'VENDOR' or 'BUYER'
            party_key: 'vendor_name' or 'buyer_name'
            gstin_key: 'vendor_gstin' or 'buyer_gstin'
            total_font: font colour for totals (red_amount or green_amount-like)
            """
            BILL_COLS = 15  # SL.NO, Party, GSTIN, Invoice#, Date, Description, HSN/SAC, QTY, UOM, RATE, TAXABLE, CGST, SGST, IGST, TOTAL
            bill_header_labels = [
                'SL.NO', party_label, 'GSTIN', 'INVOICE #', 'DATE',
                'DESCRIPTION', 'HSN/SAC', 'QTY', 'UOM', 'RATE',
                'TAXABLE AMT', 'CGST', 'SGST', 'IGST', 'TOTAL'
            ]

            ws.cell(row=1, column=1, value=sheet_title).font = title_font
            cr = 3  # current row
            grand_taxable = 0
            grand_cgst = 0
            grand_sgst = 0
            grand_igst = 0
            grand_total = 0
            bill_serial = 0

            for stem in sorted(stem_groups_local.keys()):
                group_bills = bills_by_stem_local.get(stem, [])
                if not group_bills:
                    continue

                project_names = stem_groups_local[stem]
                group_label = stem.upper()
                proj_list = ', '.join(sorted(str(p) for p in project_names if str(p) != 'nan'))

                block_start = cr

                # ── PROJECT HEADER (blue fill, white text) ──
                for c in range(1, BILL_COLS + 1):
                    ws.cell(row=cr, column=c).fill = project_name_fill
                ws.cell(row=cr, column=1,
                        value=f'PROJECT :  {group_label}').font = project_name_font
                cr += 1

                # Variant names
                ws.cell(row=cr, column=1,
                        value=f'({proj_list})').font = Font(
                    name='Calibri', italic=True, color='6B7280', size=9)
                cr += 2

                # ── COLUMN HEADERS ──
                for ci, lbl in enumerate(bill_header_labels, 1):
                    cell = ws.cell(row=cr, column=ci, value=lbl)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                cr += 1

                proj_taxable = 0
                proj_cgst = 0
                proj_sgst = 0
                proj_igst = 0
                proj_total = 0

                for bill in group_bills:
                    bill_serial += 1
                    line_items = bill.get('line_items', [])
                    b_taxable = float(bill.get('subtotal', 0) or 0)
                    b_cgst = float(bill.get('total_cgst', 0) or 0)
                    b_sgst = float(bill.get('total_sgst', 0) or 0)
                    b_igst = float(bill.get('total_igst', 0) or 0)
                    b_total = float(bill.get('total_amount', 0) or 0)

                    if line_items:
                        # First line item shares the row with bill header info
                        for li_idx, item in enumerate(line_items):
                            if li_idx == 0:
                                ws.cell(row=cr, column=1, value=bill_serial)
                                ws.cell(row=cr, column=2, value=bill.get(party_key, ''))
                                ws.cell(row=cr, column=3, value=bill.get(gstin_key, ''))
                                ws.cell(row=cr, column=4, value=bill.get('invoice_number', ''))
                                ws.cell(row=cr, column=5, value=bill.get('invoice_date', ''))
                            # Line item detail columns
                            ws.cell(row=cr, column=6, value=item.get('description', ''))
                            ws.cell(row=cr, column=7, value=item.get('hsn_sac_code', ''))
                            qty = item.get('quantity', 0)
                            if qty:
                                ws.cell(row=cr, column=8, value=qty)
                                ws.cell(row=cr, column=8).number_format = '#,##0.00'
                            ws.cell(row=cr, column=9, value=item.get('uom', ''))
                            rate = item.get('rate_per_unit', 0)
                            if rate:
                                ws.cell(row=cr, column=10, value=rate)
                                ws.cell(row=cr, column=10).number_format = currency_fmt
                            taxable = item.get('taxable_value', 0)
                            if taxable:
                                ws.cell(row=cr, column=11, value=taxable)
                                ws.cell(row=cr, column=11).number_format = currency_fmt
                            item_cgst = item.get('cgst_amount', 0)
                            if item_cgst:
                                ws.cell(row=cr, column=12, value=item_cgst)
                                ws.cell(row=cr, column=12).number_format = currency_fmt
                            item_sgst = item.get('sgst_amount', 0)
                            if item_sgst:
                                ws.cell(row=cr, column=13, value=item_sgst)
                                ws.cell(row=cr, column=13).number_format = currency_fmt
                            item_igst = item.get('igst_amount', 0)
                            if item_igst:
                                ws.cell(row=cr, column=14, value=item_igst)
                                ws.cell(row=cr, column=14).number_format = currency_fmt
                            cr += 1
                    else:
                        # Bill with no line items - single row with bill totals
                        ws.cell(row=cr, column=1, value=bill_serial)
                        ws.cell(row=cr, column=2, value=bill.get(party_key, ''))
                        ws.cell(row=cr, column=3, value=bill.get(gstin_key, ''))
                        ws.cell(row=cr, column=4, value=bill.get('invoice_number', ''))
                        ws.cell(row=cr, column=5, value=bill.get('invoice_date', ''))
                        ws.cell(row=cr, column=11, value=b_taxable)
                        ws.cell(row=cr, column=11).number_format = currency_fmt
                        ws.cell(row=cr, column=12, value=b_cgst)
                        ws.cell(row=cr, column=12).number_format = currency_fmt
                        ws.cell(row=cr, column=13, value=b_sgst)
                        ws.cell(row=cr, column=13).number_format = currency_fmt
                        ws.cell(row=cr, column=14, value=b_igst)
                        ws.cell(row=cr, column=14).number_format = currency_fmt
                        ws.cell(row=cr, column=15, value=b_total)
                        ws.cell(row=cr, column=15).number_format = currency_fmt
                        cr += 1

                    # ── Bill Total row ──
                    ws.cell(row=cr, column=6, value='Bill Total').font = Font(bold=True)
                    ws.cell(row=cr, column=11, value=b_taxable).font = Font(bold=True)
                    ws.cell(row=cr, column=11).number_format = currency_fmt
                    ws.cell(row=cr, column=12, value=b_cgst).font = Font(bold=True)
                    ws.cell(row=cr, column=12).number_format = currency_fmt
                    ws.cell(row=cr, column=13, value=b_sgst).font = Font(bold=True)
                    ws.cell(row=cr, column=13).number_format = currency_fmt
                    ws.cell(row=cr, column=14, value=b_igst).font = Font(bold=True)
                    ws.cell(row=cr, column=14).number_format = currency_fmt
                    ws.cell(row=cr, column=15, value=b_total).font = Font(bold=True)
                    ws.cell(row=cr, column=15).number_format = currency_fmt
                    # Thin bottom border on bill total row
                    for c in range(1, BILL_COLS + 1):
                        ws.cell(row=cr, column=c).border = thin_border
                    cr += 1

                    proj_taxable += b_taxable
                    proj_cgst += b_cgst
                    proj_sgst += b_sgst
                    proj_igst += b_igst
                    proj_total += b_total

                # ── PROJECT TOTAL (green fill) ──
                for c in range(1, BILL_COLS + 1):
                    ws.cell(row=cr, column=c).fill = green_fill
                ws.cell(row=cr, column=1, value=f'PROJECT TOTAL — {group_label}').font = Font(bold=True)
                ws.cell(row=cr, column=11, value=proj_taxable).font = total_font
                ws.cell(row=cr, column=11).number_format = currency_fmt
                ws.cell(row=cr, column=12, value=proj_cgst).font = total_font
                ws.cell(row=cr, column=12).number_format = currency_fmt
                ws.cell(row=cr, column=13, value=proj_sgst).font = total_font
                ws.cell(row=cr, column=13).number_format = currency_fmt
                ws.cell(row=cr, column=14, value=proj_igst).font = total_font
                ws.cell(row=cr, column=14).number_format = currency_fmt
                ws.cell(row=cr, column=15, value=proj_total).font = total_font
                ws.cell(row=cr, column=15).number_format = currency_fmt
                cr += 1

                # Yellow background on all content rows in this block
                for r in range(block_start, cr):
                    for c in range(1, BILL_COLS + 1):
                        cell = ws.cell(row=r, column=c)
                        if cell.fill == PatternFill(fill_type=None) or cell.fill == PatternFill():
                            cell.fill = block_bg

                # ── Dark separator ──
                for c in range(1, BILL_COLS + 1):
                    ws.cell(row=cr, column=c).fill = separator_fill
                cr += 2

                grand_taxable += proj_taxable
                grand_cgst += proj_cgst
                grand_sgst += proj_sgst
                grand_igst += proj_igst
                grand_total += proj_total

            # ── GRAND TOTAL ──
            if grand_total > 0:
                ws.cell(row=cr, column=1, value='GRAND TOTAL').font = Font(bold=True, size=12)
                ws.cell(row=cr, column=11, value=grand_taxable).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=11).number_format = currency_fmt
                ws.cell(row=cr, column=12, value=grand_cgst).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=12).number_format = currency_fmt
                ws.cell(row=cr, column=13, value=grand_sgst).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=13).number_format = currency_fmt
                ws.cell(row=cr, column=14, value=grand_igst).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=14).number_format = currency_fmt
                ws.cell(row=cr, column=15, value=grand_total).font = Font(bold=True, size=12)
                ws.cell(row=cr, column=15).number_format = currency_fmt

            # Column widths
            col_widths = {
                'A': 8, 'B': 28, 'C': 18, 'D': 18, 'E': 14,
                'F': 35, 'G': 12, 'H': 10, 'I': 8, 'J': 12,
                'K': 15, 'L': 12, 'M': 12, 'N': 12, 'O': 15
            }
            for col_letter, width in col_widths.items():
                ws.column_dimensions[col_letter].width = width

        # ── Fetch purchase bills and build project groups ──
        try:
            purchase_bills = db_manager.get_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date
            )
        except Exception as e:
            print(f"[!] Error fetching purchase bills for export: {e}")
            purchase_bills = []

        try:
            sales_bills = db_manager.get_sales_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date
            )
        except Exception as e:
            print(f"[!] Error fetching sales bills for export: {e}")
            sales_bills = []

        # Collect project names from bank txns, purchase bills, and sales bills
        pb_bank_projects = []
        pb_project_col = 'Project' if 'Project' in combined.columns else 'project' if not combined.empty else 'Project'
        if not combined.empty and pb_project_col in combined.columns:
            pb_bank_projects = [str(p) for p in combined[pb_project_col].dropna().unique()
                                if str(p).strip() and str(p).lower() != 'nan']
        pb_bill_projects = [str(b.get('project', '')) for b in purchase_bills
                            if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']
        sb_bill_projects = [str(b.get('project', '')) for b in sales_bills
                            if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']

        bills_stem_groups = build_smart_project_groups(
            pb_bank_projects, pb_bill_projects + sb_bill_projects
        )

        # Apply project filter if active
        if project:
            proj_stems = get_project_stems(project)
            bills_stem_groups = {
                s: names for s, names in bills_stem_groups.items()
                if s in proj_stems or any(normalize_project_stem(t) in proj_stems
                                          for n in names for t in str(n).split())
            }

        purchase_by_stem = match_bills_to_project_groups(purchase_bills, bills_stem_groups)
        sales_by_stem = match_bills_to_project_groups(sales_bills, bills_stem_groups)

        # TAB 7: Purchase Bills
        wb_tabs = writer.book
        if purchase_by_stem:
            ws_purchase = wb_tabs.create_sheet('Purchase Bills')
            write_bills_sheet(
                ws_purchase, purchase_by_stem, bills_stem_groups,
                sheet_title='Purchase Bills — Project Grouped',
                party_label='VENDOR', party_key='vendor_name',
                gstin_key='vendor_gstin',
                total_font=Font(name='Calibri', bold=True, color='DC2626')
            )
        else:
            pd.DataFrame({'Note': ['No purchase bills for the selected filters']}).to_excel(
                writer, sheet_name='Purchase Bills', index=False)

        # TAB 8: Sales Bills
        if sales_by_stem:
            ws_sales = wb_tabs.create_sheet('Sales Bills')
            write_bills_sheet(
                ws_sales, sales_by_stem, bills_stem_groups,
                sheet_title='Sales Bills — Project Grouped',
                party_label='BUYER', party_key='buyer_name',
                gstin_key='buyer_gstin',
                total_font=Font(name='Calibri', bold=True, color='059669')
            )
        else:
            pd.DataFrame({'Note': ['No sales bills for the selected filters']}).to_excel(
                writer, sheet_name='Sales Bills', index=False)

        # ──────────────────────────────────────────────────────────
        # TAB 9: Project Breakdown (Auditor Format)
        # ──────────────────────────────────────────────────────────
        wb = writer.book
        project_col = 'Project' if 'Project' in combined.columns else 'project' if not combined.empty else 'Project'
        v_col = 'Client/Vendor' if (not combined.empty and 'Client/Vendor' in combined.columns) else 'client_vendor'

        # Auditor-format styling (green_fill, block_bg, project_name_fill/font,
        # separator_fill already defined above for bills tabs)
        section_bold = Font(name='Calibri', bold=True, size=11)
        green_amount = Font(name='Calibri', bold=True, color='006100')
        red_amount = Font(name='Calibri', bold=True, color='DC2626')
        blue_amount = Font(name='Calibri', bold=True, color='2563EB')
        pb_currency = '#,##0.00'
        WEIGHT_UOMS = {'KGS', 'KG', 'MT', 'TONS', 'TON', 'MTS'}
        # Exclude these from Other Expense; LABOUR categories go to LABOUR PAYMENT
        EXCLUDE_CATS = {'MATERIAL PURCHASE', 'AMOUNT RECEIVED', 'SALARY AC', 'BANK CHARGES', 'DUTIES & TAX'}
        LABOUR_CATS = {'LABOUR PAYMENT', 'LABOR PAYMENT', 'LABOUR', 'LABOR'}
        NUM_COLS = 3  # A, B, C

        def pb_section_header(ws, row, text):
            """Green-filled section header spanning all columns."""
            ws.cell(row=row, column=1, value=text).font = section_bold
            for c in range(1, NUM_COLS + 1):
                ws.cell(row=row, column=c).fill = green_fill
            return row + 1

        def pb_separator(ws, row):
            """Dark separator row between project blocks."""
            for c in range(1, NUM_COLS + 1):
                ws.cell(row=row, column=c).fill = separator_fill
            return row + 1

        def pb_block_bg(ws, row):
            """Apply mild yellow background to a content row."""
            for c in range(1, NUM_COLS + 1):
                cell = ws.cell(row=row, column=c)
                if cell.fill == PatternFill(fill_type=None) or cell.fill == PatternFill():
                    cell.fill = block_bg

        try:
            export_bills = db_manager.get_bills_with_line_items_for_export(
                start_date=start_date, end_date=end_date
            )
        except Exception as e:
            print(f"[!] Error fetching bills with line items: {e}")
            export_bills = []

        # Filter export_bills by the project selection (same as combined API)
        if project:
            pb_proj_sel = parse_project_selection(project)
            if pb_proj_sel[0] or pb_proj_sel[1]:
                export_bills = [b for b in export_bills
                                if project_value_matches_selection(b.get('project'), pb_proj_sel)]

        # Collect project names from bank txns and bills
        bank_projects = []
        if not combined.empty and project_col in combined.columns:
            bank_projects = [str(p) for p in combined[project_col].dropna().unique()
                             if str(p).strip() and str(p).lower() != 'nan']
        bill_projects = [str(b.get('project', '')) for b in export_bills
                         if str(b.get('project', '')).strip() and str(b.get('project', '')).lower() != 'nan']

        stem_groups = build_smart_project_groups(bank_projects, bill_projects)

        bills_by_stem = match_bills_to_project_groups(export_bills, stem_groups)

        # Fetch labour costs from the external salary API, filtered by project
        try:
            labour_costs_raw = salary_api.get_labour_costs_by_project(
                start_date=start_date, end_date=end_date
            )
            if project:
                pb_proj_sel = parse_project_selection(project)
                if pb_proj_sel[0] or pb_proj_sel[1]:
                    labour_costs_raw = {k: v for k, v in labour_costs_raw.items()
                                        if project_value_matches_selection(k, pb_proj_sel)}
            labour_by_stem = match_labour_to_project_groups(labour_costs_raw, stem_groups)
        except Exception as e:
            print(f"[!] Error matching labour costs: {e}")
            labour_by_stem = {}

        if stem_groups:
            ws_pb = wb.create_sheet('Project Breakdown')
            current_row = 1

            for stem_idx, stem in enumerate(sorted(stem_groups.keys())):
                project_names = stem_groups[stem]
                group_label = stem.upper()
                group_bills = bills_by_stem.get(stem, [])
                proj_list = ', '.join(sorted(str(p) for p in project_names if str(p) != 'nan'))

                # Filter bank transactions for this project group
                if not combined.empty and project_col in combined.columns:
                    group_mask = combined[project_col].isin(project_names)
                    group_df = combined[group_mask]
                else:
                    group_df = pd.DataFrame()

                if group_df.empty and not group_bills:
                    continue

                # Track the first row of this block so we can paint background
                block_start_row = current_row

                # ════════════════════════════════════════════════════════
                # PROJECT NAME — big, bold, blue fill, white text
                # ════════════════════════════════════════════════════════
                for c in range(1, NUM_COLS + 1):
                    ws_pb.cell(row=current_row, column=c).fill = project_name_fill
                ws_pb.cell(row=current_row, column=1,
                           value=f'PROJECT :  {group_label}').font = project_name_font
                current_row += 1

                # Sub-label showing all project name variants
                ws_pb.cell(row=current_row, column=1,
                           value=f'({proj_list})').font = Font(
                    name='Calibri', italic=True, color='6B7280', size=9)
                current_row += 2  # blank row gap

                # ── OVERALL SUMMARY ──
                current_row = pb_section_header(ws_pb, current_row, 'OVERALL SUMMARY')

                # TOTAL PROJECT VALUE row (amount filled at the end)
                ws_pb.cell(row=current_row, column=1, value='TOTAL PROJECT VALUE').font = Font(bold=True)
                total_value_row = current_row
                current_row += 2  # blank row

                # ── MAIN MATERIAL PURCHASE ──
                current_row = pb_section_header(ws_pb, current_row, 'MAIN MATERIAL PURCHASE')

                # Column headers
                ws_pb.cell(row=current_row, column=2, value='WEIGHT').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3, value='AMOUNT').font = Font(bold=True)
                current_row += 1

                # Aggregate bills by vendor — use total_amount (subtotal + taxes)
                material_total = 0
                if group_bills:
                    vendor_agg = {}  # vendor_name -> {weight, amount}
                    for bill in group_bills:
                        vname = bill.get('vendor_name', 'Unknown Vendor')
                        if vname not in vendor_agg:
                            vendor_agg[vname] = {'weight': 0, 'amount': 0}
                        for item in bill.get('line_items', []):
                            uom = str(item.get('uom', '')).upper().strip()
                            if uom in WEIGHT_UOMS:
                                vendor_agg[vname]['weight'] += item.get('quantity', 0)
                        # Use bill total_amount (includes taxes) for consistent totals
                        vendor_agg[vname]['amount'] += bill.get('total_amount', 0)

                    for vname, data in sorted(vendor_agg.items(), key=lambda x: x[1]['amount'], reverse=True):
                        ws_pb.cell(row=current_row, column=1, value=vname)
                        if data['weight'] > 0:
                            ws_pb.cell(row=current_row, column=2, value=data['weight'])
                            ws_pb.cell(row=current_row, column=2).number_format = '#,##0.00'
                        ws_pb.cell(row=current_row, column=3, value=data['amount'])
                        ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                        material_total += data['amount']
                        current_row += 1

                # Material total — just the green amount (no duplicate header)
                ws_pb.cell(row=current_row, column=3, value=material_total).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── OTHER EXPENSE ──
                current_row = pb_section_header(ws_pb, current_row, 'OTHER EXPENSE')

                other_total = 0
                if not group_df.empty:
                    expense_df = group_df[group_df['DR Amount'] > 0].copy()
                    if 'Category' in expense_df.columns:
                        # Exclude labour + standard exclusions from other expense
                        upper_cats = expense_df['Category'].str.upper().str.strip()
                        labour_mask = upper_cats.isin(LABOUR_CATS)
                        exclude_mask = expense_df['Category'].isin(EXCLUDE_CATS) | labour_mask
                        expense_df = expense_df[~exclude_mask]

                    if not expense_df.empty and v_col in expense_df.columns:
                        for (vend, cat), grp in expense_df.groupby([v_col, 'Category']):
                            amt = float(grp['DR Amount'].sum())
                            vend_str = str(vend).strip()
                            cat_str = str(cat).strip()
                            if not vend_str or vend_str.lower() in ('unknown', 'nan', '', 'unassigned'):
                                label = cat_str
                            else:
                                label = f"{cat_str} - {vend_str}"
                            ws_pb.cell(row=current_row, column=1, value=label)
                            ws_pb.cell(row=current_row, column=3, value=amt)
                            ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                            other_total += amt
                            current_row += 1
                    elif not expense_df.empty:
                        for cat, grp in expense_df.groupby('Category'):
                            amt = float(grp['DR Amount'].sum())
                            ws_pb.cell(row=current_row, column=1, value=str(cat))
                            ws_pb.cell(row=current_row, column=3, value=amt)
                            ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                            other_total += amt
                            current_row += 1

                # Other expense total (green amount only)
                ws_pb.cell(row=current_row, column=3, value=other_total).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── LABOUR PAYMENT (blue amount, from salary/attendance DB) ──
                salary_labour = labour_by_stem.get(stem, 0)
                ws_pb.cell(row=current_row, column=1, value='LABOUR PAYMENT').font = Font(bold=True)
                if salary_labour > 0:
                    ws_pb.cell(row=current_row, column=3, value=salary_labour).font = blue_amount
                    ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── BALANCE GST PAYMENT ──
                ws_pb.cell(row=current_row, column=1, value='BALANCE GST PAYMENT').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── OVER HEADS ──
                ws_pb.cell(row=current_row, column=1, value='OVER HEADS').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── TOTAL EXP ──
                total_project = material_total + other_total + salary_labour
                ws_pb.cell(row=current_row, column=1, value='TOTAL EXP').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3, value=total_project).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 2  # blank row

                # ── BALANCE ──
                ws_pb.cell(row=current_row, column=1, value='BALANCE').font = Font(bold=True)
                ws_pb.cell(row=current_row, column=3).font = green_amount
                ws_pb.cell(row=current_row, column=3).number_format = pb_currency
                current_row += 1

                # TOTAL PROJECT VALUE left empty (user-fillable)

                block_end_row = current_row

                # Paint mild yellow background on all content rows in this block
                for r in range(block_start_row, block_end_row + 1):
                    pb_block_bg(ws_pb, r)

                # ── Dark separator + gap before next project ──
                current_row += 1
                current_row = pb_separator(ws_pb, current_row)
                current_row += 2

            # Column widths
            ws_pb.column_dimensions['A'].width = 40
            ws_pb.column_dimensions['B'].width = 15
            ws_pb.column_dimensions['C'].width = 20

        # ──────────────────────────────────────────────────────────
        # TAB 10: Labour Salary Summary (per-worker monthly, from the API)
        # ──────────────────────────────────────────────────────────
        import calendar as cal

        labour_sheet_names = []
        try:
            # Use the actual date filters so all months in the range get a sheet
            labour_start = start_date
            labour_end = end_date
            if not labour_start and not labour_end:
                from datetime import date as _d
                today = _d.today()
                labour_start = f"{today.year}-{today.month:02d}-01"
                labour_end = f"{today.year}-{today.month:02d}-{cal.monthrange(today.year, today.month)[1]:02d}"

            monthly_data = salary_api.get_monthly_labour_summary(
                start_date=labour_start, end_date=labour_end, project=project
            )

            # Styling for labour sheets
            labour_title_font = Font(name='Calibri', bold=True, size=13, color='1A1A2E')
            labour_header_font = Font(name='Calibri', bold=True, size=10, color='FFFFFF')
            labour_header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
            labour_currency = '#,##0.00'

            # The salary API exposes per-worker MONTHLY totals (not day-by-day
            # attendance), so each month is rendered as a per-worker salary
            # summary table rather than the old day-grid calendar.
            for month_data in monthly_data:
                sheet_name = f"Labour {month_data['sheet_name']}"
                if len(sheet_name) > 31:
                    sheet_name = sheet_name[:31]
                labour_sheet_names.append(sheet_name)

                ws_l = wb.create_sheet(sheet_name)

                # ===== ROW 1: Title =====
                ws_l.cell(row=1, column=1,
                          value=f"LABOUR SALARY SUMMARY — {month_data['month_name'].upper()}").font = labour_title_font
                ws_l.merge_cells(start_row=1, start_column=1, end_row=1, end_column=9)

                # ===== ROW 2: Headers =====
                headers = ['S.No', 'NAME', 'DESIGNATION', 'PRESENT DAYS', 'OT HOURS',
                           'BASE/DAY', 'BASE PAY', 'OT PAY', 'TOTAL SALARY']
                for ci, h in enumerate(headers, 1):
                    c = ws_l.cell(row=2, column=ci, value=h)
                    c.font = labour_header_font
                    c.fill = labour_header_fill
                    c.alignment = Alignment(horizontal='center')

                # ===== DATA ROWS (one per worker) =====
                data_row = 3
                sno = 1
                for w in month_data['workers']:
                    ws_l.cell(row=data_row, column=1, value=sno)
                    ws_l.cell(row=data_row, column=2, value=w['name'])
                    ws_l.cell(row=data_row, column=3, value=w['designation'])
                    ws_l.cell(row=data_row, column=4, value=w['present_days'])
                    ws_l.cell(row=data_row, column=5, value=w['ot_hours'])
                    ws_l.cell(row=data_row, column=6,
                              value=w['base_salary_per_day']).number_format = labour_currency
                    ws_l.cell(row=data_row, column=7,
                              value=w['base_pay']).number_format = labour_currency
                    ws_l.cell(row=data_row, column=8,
                              value=w['ot_pay']).number_format = labour_currency
                    ws_l.cell(row=data_row, column=9,
                              value=w['total_salary']).number_format = labour_currency
                    sno += 1
                    data_row += 1

                # ===== MONTHLY SUMMARY footer =====
                data_row += 1
                ws_l.cell(row=data_row, column=1, value='MONTHLY SUMMARY').font = Font(bold=True, size=11)
                ws_l.cell(row=data_row, column=1).fill = PatternFill(
                    start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
                data_row += 1

                summary_pairs = [
                    ('Total Workers', month_data['headcount'], None),
                    ('Total Present Days', month_data['total_present_days'], None),
                    ('Total OT Hours', month_data['total_ot_hours'], None),
                    ('Total Base Pay', month_data['total_base_pay'], labour_currency),
                    ('Total OT Pay', month_data['total_ot_pay'], labour_currency),
                    ('Total Salary', month_data['total_salary'], labour_currency),
                ]
                for label, value, fmt in summary_pairs:
                    ws_l.cell(row=data_row, column=2, value=label).font = Font(bold=True)
                    cell = ws_l.cell(row=data_row, column=4, value=value)
                    if fmt:
                        cell.number_format = fmt
                    if label == 'Total Salary':
                        cell.font = Font(bold=True, color='006100')
                    data_row += 1

                # OT pay applies to daily-rate workers only; monthly-salaried
                # workers show OT hours for tracking but never accrue OT pay.
                data_row += 1
                ws_l.cell(row=data_row, column=1, value=(
                    'Note: OT pay applies to daily-rate workers only; monthly-salaried '
                    'workers show OT hours for tracking but no OT pay.'
                )).font = Font(italic=True, size=9, color='6B7280')

                # Column widths
                ws_l.column_dimensions['A'].width = 6
                ws_l.column_dimensions['B'].width = 24
                ws_l.column_dimensions['C'].width = 16
                for col_letter in ('D', 'E', 'F', 'G', 'H', 'I'):
                    ws_l.column_dimensions[col_letter].width = 14

        except Exception as e:
            print(f"[!] Labour tab export error: {e}")
            import traceback
            traceback.print_exc()

        # ── Sheet ordering ──
        if len(wb.sheetnames) > 1:
            desired_order = [
                'Executive Summary', 'Expense Breakdown', 'Cashflow Analysis',
                'Vendor Breakdown'
            ]
            for bc in VALID_BANK_CODES:
                bank_config = get_bank_config(bc)
                sn = f"{bank_config['name']} Txns"
                if len(sn) > 31:
                    sn = sn[:31]
                desired_order.append(sn)
            desired_order.extend(['Project Breakdown', 'Purchase Bills', 'Sales Bills'])
            desired_order.extend(labour_sheet_names)  # Labour always last

            desired_order = [s for s in desired_order if s in wb.sheetnames]
            desired_order += [s for s in wb.sheetnames if s not in desired_order]

            wb._sheets = [wb[s] for s in desired_order]

    output.seek(0)
    filename = f"Project_Summary_{now_ist().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ════════════════════════════════════════════════════════════════════════════
# PER-PROJECT EXPORT
#
# One project = one workbook, structured exactly like the registry detail
# pop-up: PO Value → Client Payments → Expenses → Purchase Bills → Sales Bills
# → Labour Payments → Consolidated Summary, followed by the analytical extras
# (Expense by Category, Vendor Breakdown, per-bank transactions).
# ════════════════════════════════════════════════════════════════════════════

# Category buckets — mirror blueprints.projects.api_project_insights so the
# Consolidated Summary's spend composition matches the pop-up's headline.
_LABOUR_CATS = {'LABOUR PAYMENT', 'LABOR PAYMENT', 'LABOUR', 'LABOR'}
_OTHER_EXCLUDE_CATS = {'MATERIAL PURCHASE', 'AMOUNT RECEIVED', 'SALARY AC',
                       'BANK CHARGES', 'DUTIES & TAX'}


def _make_styles():
    """Build the shared openpyxl style set (lazy import, as elsewhere)."""
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    return {
        'header_font': Font(name='Calibri', bold=True, color='FFFFFF', size=11),
        'header_fill': PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid'),
        'title_font': Font(name='Calibri', bold=True, size=14, color='1A1A2E'),
        'subtitle_font': Font(name='Calibri', bold=True, size=11, color='4A4A68'),
        'currency_fmt': '#,##0.00',
        'pct_fmt': '0.0%',
        'thin_border': Border(bottom=Side(style='thin', color='E5E7EB')),
        'income_font': Font(name='Calibri', color='059669', bold=True),
        'expense_font': Font(name='Calibri', color='DC2626', bold=True),
        'section_bold': Font(name='Calibri', bold=True, size=11),
        'green_amount': Font(name='Calibri', bold=True, color='006100'),
        'red_amount': Font(name='Calibri', bold=True, color='DC2626'),
        'blue_amount': Font(name='Calibri', bold=True, color='2563EB'),
        'green_fill': PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid'),
        'block_bg': PatternFill(start_color='FFFDE7', end_color='FFFDE7', fill_type='solid'),
        'project_name_fill': PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid'),
        'project_name_font': Font(name='Calibri', bold=True, size=14, color='FFFFFF'),
        'separator_fill': PatternFill(start_color='2F2F2F', end_color='2F2F2F', fill_type='solid'),
        # Bank-coloured fonts, mirroring the pop-up's Axis-red / KVB-green badges.
        'bank_axis_font': Font(name='Calibri', bold=True, color='C0392B'),
        'bank_kvb_font': Font(name='Calibri', bold=True, color='1E8449'),
    }


def _write_project_bills_sheet(ws, bills, project_label, sheet_title,
                               party_label, party_key, gstin_key, total_font, st):
    """Project-grouped bills sheet for a SINGLE project (one project block).

    A trimmed sibling of export_project_summary's write_bills_sheet: same
    auditor layout (project header → per-bill line items → bill totals →
    project total), but for just this project's bills.
    """
    from openpyxl.styles import Font, Alignment

    title_font = st['title_font']
    header_font = st['header_font']
    header_fill = st['header_fill']
    currency_fmt = st['currency_fmt']
    thin_border = st['thin_border']
    green_fill = st['green_fill']
    project_name_fill = st['project_name_fill']
    project_name_font = st['project_name_font']

    BILL_COLS = 15
    bill_header_labels = [
        'SL.NO', party_label, 'GSTIN', 'INVOICE #', 'DATE',
        'DESCRIPTION', 'HSN/SAC', 'QTY', 'UOM', 'RATE',
        'TAXABLE AMT', 'CGST', 'SGST', 'IGST', 'TOTAL'
    ]

    ws.cell(row=1, column=1, value=sheet_title).font = title_font
    cr = 3

    # ── PROJECT HEADER (blue fill, white text) ──
    for c in range(1, BILL_COLS + 1):
        ws.cell(row=cr, column=c).fill = project_name_fill
    ws.cell(row=cr, column=1, value=f'PROJECT :  {project_label.upper()}').font = project_name_font
    cr += 2

    # ── COLUMN HEADERS ──
    for ci, lbl in enumerate(bill_header_labels, 1):
        cell = ws.cell(row=cr, column=ci, value=lbl)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')
    cr += 1

    grand_taxable = grand_cgst = grand_sgst = grand_igst = grand_total = 0
    bill_serial = 0

    for bill in bills:
        bill_serial += 1
        line_items = bill.get('line_items', [])
        b_taxable = float(bill.get('subtotal', 0) or 0)
        b_cgst = float(bill.get('total_cgst', 0) or 0)
        b_sgst = float(bill.get('total_sgst', 0) or 0)
        b_igst = float(bill.get('total_igst', 0) or 0)
        b_total = float(bill.get('total_amount', 0) or 0)

        if line_items:
            for li_idx, item in enumerate(line_items):
                if li_idx == 0:
                    ws.cell(row=cr, column=1, value=bill_serial)
                    ws.cell(row=cr, column=2, value=bill.get(party_key, ''))
                    ws.cell(row=cr, column=3, value=bill.get(gstin_key, ''))
                    ws.cell(row=cr, column=4, value=bill.get('invoice_number', ''))
                    ws.cell(row=cr, column=5, value=bill.get('invoice_date', ''))
                ws.cell(row=cr, column=6, value=item.get('description', ''))
                ws.cell(row=cr, column=7, value=item.get('hsn_sac_code', ''))
                qty = item.get('quantity', 0)
                if qty:
                    ws.cell(row=cr, column=8, value=qty).number_format = '#,##0.00'
                ws.cell(row=cr, column=9, value=item.get('uom', ''))
                rate = item.get('rate_per_unit', 0)
                if rate:
                    ws.cell(row=cr, column=10, value=rate).number_format = currency_fmt
                taxable = item.get('taxable_value', 0)
                if taxable:
                    ws.cell(row=cr, column=11, value=taxable).number_format = currency_fmt
                if item.get('cgst_amount', 0):
                    ws.cell(row=cr, column=12, value=item['cgst_amount']).number_format = currency_fmt
                if item.get('sgst_amount', 0):
                    ws.cell(row=cr, column=13, value=item['sgst_amount']).number_format = currency_fmt
                if item.get('igst_amount', 0):
                    ws.cell(row=cr, column=14, value=item['igst_amount']).number_format = currency_fmt
                cr += 1
        else:
            ws.cell(row=cr, column=1, value=bill_serial)
            ws.cell(row=cr, column=2, value=bill.get(party_key, ''))
            ws.cell(row=cr, column=3, value=bill.get(gstin_key, ''))
            ws.cell(row=cr, column=4, value=bill.get('invoice_number', ''))
            ws.cell(row=cr, column=5, value=bill.get('invoice_date', ''))
            cr += 1

        # ── Bill Total row ──
        ws.cell(row=cr, column=6, value='Bill Total').font = Font(bold=True)
        for col, val in ((11, b_taxable), (12, b_cgst), (13, b_sgst), (14, b_igst), (15, b_total)):
            cell = ws.cell(row=cr, column=col, value=val)
            cell.font = Font(bold=True)
            cell.number_format = currency_fmt
        for c in range(1, BILL_COLS + 1):
            ws.cell(row=cr, column=c).border = thin_border
        cr += 1

        grand_taxable += b_taxable
        grand_cgst += b_cgst
        grand_sgst += b_sgst
        grand_igst += b_igst
        grand_total += b_total

    # ── PROJECT / GRAND TOTAL (green fill) ──
    for c in range(1, BILL_COLS + 1):
        ws.cell(row=cr, column=c).fill = green_fill
    ws.cell(row=cr, column=1, value=f'PROJECT TOTAL — {project_label.upper()}').font = Font(bold=True)
    for col, val in ((11, grand_taxable), (12, grand_cgst), (13, grand_sgst),
                     (14, grand_igst), (15, grand_total)):
        cell = ws.cell(row=cr, column=col, value=val)
        cell.font = total_font
        cell.number_format = currency_fmt

    col_widths = {'A': 8, 'B': 28, 'C': 18, 'D': 18, 'E': 14, 'F': 35, 'G': 12,
                  'H': 10, 'I': 8, 'J': 12, 'K': 15, 'L': 12, 'M': 12, 'N': 12, 'O': 15}
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width


def export_single_project_summary(project_id):
    """Per-project Excel export, structured like the registry detail pop-up.

    Sheets, in pop-up order:
      1. PO Value
      2. Client Payments (KVB bank credits + cash ledger)
      3. Expenses
      4. Purchase Bills
      5. Sales Bills
      6. Labour Payments
      7. Consolidated Summary
    Then the analytical extras, scoped to this project:
      Expense by Category, Vendor Breakdown, Axis Txns, KVB Txns.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    from openpyxl.utils import get_column_letter

    db_manager.ensure_projects_table()
    project = db_manager.get_project(project_id)
    if not project:
        return jsonify({'error': 'not_found'}), 404

    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)

    if start_date and end_date:
        date_label = f"Period: {start_date} to {end_date}"
    elif start_date:
        date_label = f"Period: from {start_date}"
    elif end_date:
        date_label = f"Period: up to {end_date}"
    else:
        date_label = ''

    display = project.get('display') or f"{project_id} - {project.get('stem_name', '')}"
    stem_name = project.get('stem_name', '') or display
    po_value = float(project.get('po_total_value') or 0)

    st = _make_styles()
    currency_fmt = st['currency_fmt']
    pct_fmt = st['pct_fmt']

    # ── Gather this project's bank transactions across banks ──
    def project_mask(df):
        col = 'Project' if 'Project' in df.columns else 'project'
        if col not in df.columns:
            return pd.Series(False, index=df.index)
        s = df[col].astype(str).str.strip()
        return s.str.match(rf'^{project_id}\s*-')

    combined_rows = []
    for bc in VALID_BANK_CODES:
        df = get_bank_df(bc).copy()
        if df.empty:
            continue
        df = filter_by_date_range(df, start_date, end_date)
        df = df[project_mask(df)]
        if df.empty:
            continue
        df['bank'] = bc
        combined_rows.append(df)
    combined = pd.concat(combined_rows, ignore_index=True) if combined_rows else pd.DataFrame()

    # ── Client payments: KVB credits + cash ledger ──
    kvb_df = combined[combined['bank'] == 'kvb'] if not combined.empty else pd.DataFrame()
    if not kvb_df.empty and 'CR Amount' in kvb_df.columns:
        bank_credits = kvb_df[kvb_df['CR Amount'] > 0].sort_values('date', ascending=False)
    else:
        bank_credits = pd.DataFrame()
    received_bank = float(bank_credits['CR Amount'].sum()) if not bank_credits.empty else 0.0
    cash_payments = db_manager.list_cash_payments(project_id)
    received_cash = sum(float(c.get('amount') or 0) for c in cash_payments)
    received_total = received_bank + received_cash

    # ── Expenses: debit transactions, all banks ──
    expense_df = combined[combined['DR Amount'] > 0] if not combined.empty else pd.DataFrame()
    v_col = 'Client/Vendor' if (not combined.empty and 'Client/Vendor' in combined.columns) else 'client_vendor'

    # ── Bills with line items, filtered to this project ──
    def _belongs(bill):
        proj = str(bill.get('project', '') or '').strip()
        return bool(re.match(rf'^{project_id}\s*-', proj))

    try:
        purchase_bills = [b for b in db_manager.get_bills_with_line_items_for_export(
            start_date=start_date, end_date=end_date) if _belongs(b)]
    except Exception as e:
        print(f"[!] Error fetching purchase bills for project export: {e}")
        purchase_bills = []
    try:
        sales_bills = [b for b in db_manager.get_sales_bills_with_line_items_for_export(
            start_date=start_date, end_date=end_date) if _belongs(b)]
    except Exception as e:
        print(f"[!] Error fetching sales bills for project export: {e}")
        sales_bills = []

    material_total = sum(float(b.get('total_amount') or 0) for b in purchase_bills)

    # ── Labour from the salary API ──
    try:
        labour_summary = salary_api.get_labour_summary_for_project(
            project_id, project_display=display, start_date=start_date, end_date=end_date)
    except Exception as e:
        print(f"[!] Labour summary error (project {project_id}): {e}")
        labour_summary = {'available': False, 'monthly': [], 'total_cost': 0.0}
    labour_total = float(labour_summary.get('total_cost') or 0)
    try:
        labour_monthly_detail = salary_api.get_monthly_labour_summary(
            start_date=start_date, end_date=end_date, project=display)
    except Exception as e:
        print(f"[!] Labour monthly detail error (project {project_id}): {e}")
        labour_monthly_detail = []

    # ── Other (non-material, non-labour, non-internal) expense ──
    other_expense_total = 0.0
    if not expense_df.empty and 'Category' in expense_df.columns:
        up = expense_df['Category'].astype(str).str.upper().str.strip()
        keep = ~(up.isin(_OTHER_EXCLUDE_CATS) | up.isin(_LABOUR_CATS))
        other_expense_total = float(expense_df[keep]['DR Amount'].sum())

    spend_total = material_total + other_expense_total + labour_total
    balance = po_value - received_total

    wb = Workbook()
    wb.remove(wb.active)

    def style_header_row(ws, row_num, col_count):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.font = st['header_font']
            cell.fill = st['header_fill']
            cell.alignment = Alignment(horizontal='center', vertical='center')

    def auto_width(ws, cap=40):
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                try:
                    val = str(cell.value) if cell.value is not None else ''
                    max_len = max(max_len, len(val))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 3, cap)

    def kv_row(ws, row, label, value, *, fmt=None, font=None, bold_label=True):
        lcell = ws.cell(row=row, column=1, value=label)
        if bold_label:
            lcell.font = Font(bold=True)
        vcell = ws.cell(row=row, column=2, value=value)
        if fmt:
            vcell.number_format = fmt
        if font:
            vcell.font = font

    def bank_font(bc):
        return st['bank_axis_font'] if bc == 'axis' else st['bank_kvb_font'] if bc == 'kvb' else None

    # ─────────────────────────────────────────────── SHEET 1: PO Value ──
    ws = wb.create_sheet('PO Value')
    ws.cell(row=1, column=1, value=f'PO Value — {display}').font = st['title_font']
    pct = (received_total / po_value) if po_value > 0 else 0
    bal_label = 'Excess Received' if balance < -0.5 else 'Balance Due'
    r = 3
    kv_row(ws, r, 'PO Number', project.get('po_number') or '—'); r += 1
    kv_row(ws, r, 'PO Document', project.get('po_filename') or '—'); r += 1
    kv_row(ws, r, 'PO Value', po_value, fmt=currency_fmt, font=st['blue_amount']); r += 2
    kv_row(ws, r, 'Received — Bank (KVB)', received_bank, fmt=currency_fmt, font=st['income_font']); r += 1
    kv_row(ws, r, 'Received — Cash', received_cash, fmt=currency_fmt, font=st['income_font']); r += 1
    kv_row(ws, r, 'Total Received', received_total, fmt=currency_fmt, font=st['income_font']); r += 2
    kv_row(ws, r, bal_label, abs(balance), fmt=currency_fmt,
           font=(st['red_amount'] if balance > 0.5 else st['green_amount'])); r += 1
    kv_row(ws, r, '% Received', pct, fmt=pct_fmt); r += 1
    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 22

    # ──────────────────────────────────────── SHEET 2: Client Payments ──
    ws = wb.create_sheet('Client Payments')
    ws.cell(row=1, column=1, value=f'Client Payments — {display}').font = st['title_font']
    # Chips row
    kv_row(ws, 3, 'Bank (KVB)', received_bank, fmt=currency_fmt, font=st['income_font'])
    ws.cell(row=3, column=3, value=f'{len(bank_credits)} credit(s)').font = Font(italic=True, color='6B7280')
    kv_row(ws, 4, 'Cash', received_cash, fmt=currency_fmt, font=st['income_font'])
    ws.cell(row=4, column=3, value=f'{len(cash_payments)} entr{"y" if len(cash_payments) == 1 else "ies"}').font = Font(italic=True, color='6B7280')
    kv_row(ws, 5, 'Total Received', received_total, fmt=currency_fmt, font=st['income_font'])
    # Combined history table
    headers = ['Date', 'Source', 'Particulars', 'Vendor', 'Amount']
    hr = 7
    for ci, h in enumerate(headers, 1):
        ws.cell(row=hr, column=ci, value=h)
    style_header_row(ws, hr, len(headers))
    pay_entries = []
    for _, row in bank_credits.iterrows():
        desc = ''
        for c in ('Description', 'Transaction Description', 'transaction_description'):
            if c in row and pd.notna(row.get(c)) and str(row.get(c)).strip():
                desc = str(row.get(c)).strip()
                break
        pay_entries.append({
            'date': row['date'].strftime('%d-%m-%Y') if pd.notna(row.get('date')) else '',
            'sort': row['date'] if pd.notna(row.get('date')) else None,
            'source': 'KVB', 'particulars': desc,
            'vendor': str(row.get('Client/Vendor', '') or ''),
            'amount': float(row.get('CR Amount', 0)),
        })
    for c in cash_payments:
        pay_entries.append({
            'date': (c.get('payment_date') or c.get('created_at') or '')[:10],
            'sort': c.get('payment_date') or c.get('created_at') or '',
            'source': 'Cash', 'particulars': c.get('note') or '',
            'vendor': '', 'amount': float(c.get('amount') or 0),
        })
    pay_entries.sort(key=lambda x: str(x['sort'] or ''), reverse=True)
    rr = hr + 1
    for e in pay_entries:
        ws.cell(row=rr, column=1, value=e['date'])
        ws.cell(row=rr, column=2, value=e['source']).font = (
            st['bank_kvb_font'] if e['source'] == 'KVB' else Font(bold=True, color='6B7280'))
        ws.cell(row=rr, column=3, value=e['particulars'])
        ws.cell(row=rr, column=4, value=e['vendor'])
        ac = ws.cell(row=rr, column=5, value=e['amount'])
        ac.number_format = currency_fmt
        ac.font = st['income_font']
        rr += 1
    ws.cell(row=rr, column=1, value='TOTAL').font = Font(bold=True)
    tc = ws.cell(row=rr, column=5, value=received_total)
    tc.font = Font(bold=True)
    tc.number_format = currency_fmt
    for col, w in (('A', 13), ('B', 10), ('C', 40), ('D', 24), ('E', 16)):
        ws.column_dimensions[col].width = w

    # ──────────────────────────────────────────────── SHEET 3: Expenses ──
    # Consolidated analytical sheet: total, a category breakdown with a bar
    # chart (like the dashboard), vendor + bank breakdowns, and a filterable
    # transactions table (Excel column auto-filter).
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.series import DataPoint
    CAT_COLORS = ['3B82F6', 'EF4444', '10B981', 'F59E0B', '8B5CF6',
                  'EC4899', '06B6D4', 'F97316', '6366F1', '14B8A6',
                  'E11D48', '84CC16', 'A855F7', '0EA5E9', 'D946EF']

    ws = wb.create_sheet('Expenses')
    ws.cell(row=1, column=1, value=f'Expenses — {display}').font = st['title_font']
    if date_label:
        ws.cell(row=2, column=1, value=date_label).font = Font(italic=True, color='6B7280')
    expense_total = float(expense_df['DR Amount'].sum()) if not expense_df.empty else 0.0
    kv_row(ws, 3, 'Total Spent', expense_total, fmt=currency_fmt, font=st['expense_font'])
    ws.cell(row=3, column=3, value=f'{len(expense_df)} transaction(s)').font = Font(italic=True, color='6B7280')

    has_cats = (not expense_df.empty) and ('Category' in expense_df.columns)

    # ── BY CATEGORY (+ horizontal bar chart) ──
    r = 5
    ws.cell(row=r, column=1, value='BY CATEGORY').font = st['subtitle_font']
    r += 1
    cat_header_row = r
    for ci, h in enumerate(['Category', 'Amount', 'Count', '% of Spend'], 1):
        ws.cell(row=r, column=ci, value=h)
    style_header_row(ws, r, 4)
    r += 1
    cat_count = 0
    if has_cats:
        cat_grp = expense_df.groupby('Category')['DR Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
        for cat, row in cat_grp.iterrows():
            amt = float(row['sum'])
            ws.cell(row=r, column=1, value=str(cat))
            ws.cell(row=r, column=2, value=amt).number_format = currency_fmt
            ws.cell(row=r, column=3, value=int(row['count']))
            ws.cell(row=r, column=4, value=(amt / expense_total if expense_total else 0)).number_format = pct_fmt
            r += 1
            cat_count += 1
    cat_last_row = r - 1
    ws.cell(row=r, column=1, value='TOTAL').font = Font(bold=True)
    tc = ws.cell(row=r, column=2, value=expense_total)
    tc.font = Font(bold=True)
    tc.number_format = currency_fmt
    r += 1

    if cat_count > 0:
        chart = BarChart()
        chart.type = 'bar'           # horizontal bars, like the dashboard
        chart.title = 'Expense by Category'
        chart.legend = None
        data = Reference(ws, min_col=2, min_row=cat_header_row, max_row=cat_last_row)
        cats = Reference(ws, min_col=1, min_row=cat_header_row + 1, max_row=cat_last_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        series = chart.series[0]
        for i in range(cat_count):
            dp = DataPoint(idx=i)
            dp.graphicalProperties.solidFill = CAT_COLORS[i % len(CAT_COLORS)]
            series.data_points.append(dp)
        chart.height = max(6, min(22, cat_count * 0.9 + 2))
        chart.width = 16
        ws.add_chart(chart, f'G{cat_header_row}')

    # ── BY VENDOR ──
    r += 1
    ws.cell(row=r, column=1, value='BY VENDOR').font = st['subtitle_font']
    r += 1
    for ci, h in enumerate(['Vendor', 'Amount', 'Count'], 1):
        ws.cell(row=r, column=ci, value=h)
    style_header_row(ws, r, 3)
    r += 1
    if not expense_df.empty and v_col in expense_df.columns:
        ven_grp = expense_df.groupby(v_col)['DR Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
        for vn, row in ven_grp.iterrows():
            ws.cell(row=r, column=1, value=str(vn) if str(vn) != 'nan' else 'Unknown')
            ws.cell(row=r, column=2, value=float(row['sum'])).number_format = currency_fmt
            ws.cell(row=r, column=3, value=int(row['count']))
            r += 1

    # ── BY BANK ──
    r += 1
    ws.cell(row=r, column=1, value='BY BANK').font = st['subtitle_font']
    r += 1
    for ci, h in enumerate(['Bank', 'Amount', 'Count'], 1):
        ws.cell(row=r, column=ci, value=h)
    style_header_row(ws, r, 3)
    r += 1
    if not expense_df.empty and 'bank' in expense_df.columns:
        bank_grp = expense_df.groupby('bank')['DR Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
        for bcode, row in bank_grp.iterrows():
            bcell = ws.cell(row=r, column=1, value=str(bcode).upper())
            bf = bank_font(str(bcode))
            if bf:
                bcell.font = bf
            ws.cell(row=r, column=2, value=float(row['sum'])).number_format = currency_fmt
            ws.cell(row=r, column=3, value=int(row['count']))
            r += 1

    # ── TRANSACTIONS (filterable) ──
    r += 1
    ws.cell(row=r, column=1, value='TRANSACTIONS').font = st['subtitle_font']
    r += 1
    txn_header_row = r
    headers = ['Date', 'Paid To', 'Category', 'Bank', 'Amount']
    for ci, h in enumerate(headers, 1):
        ws.cell(row=r, column=ci, value=h)
    style_header_row(ws, r, len(headers))
    r += 1
    if not expense_df.empty:
        for _, row in expense_df.sort_values('date', ascending=False).iterrows():
            vend = str(row.get(v_col, '') or '')
            desc = ''
            for c in ('Description', 'Transaction Description', 'transaction_description'):
                if c in row and pd.notna(row.get(c)) and str(row.get(c)).strip():
                    desc = str(row.get(c)).strip()
                    break
            paid_to = vend if vend and vend.lower() not in ('unknown', 'nan', '') else desc
            bcode = str(row.get('bank', '') or '')
            ws.cell(row=r, column=1, value=row['date'].strftime('%d-%m-%Y') if pd.notna(row.get('date')) else '')
            ws.cell(row=r, column=2, value=paid_to)
            ws.cell(row=r, column=3, value=str(row.get('Category', '') or ''))
            bcell = ws.cell(row=r, column=4, value=bcode.upper())
            bf = bank_font(bcode)
            if bf:
                bcell.font = bf
            ac = ws.cell(row=r, column=5, value=float(row.get('DR Amount', 0)))
            ac.number_format = currency_fmt
            ac.font = st['expense_font']
            r += 1
    txn_last_row = r - 1
    # Excel column auto-filter over the transactions table.
    ws.auto_filter.ref = f'A{txn_header_row}:E{max(txn_last_row, txn_header_row)}'

    for col, w in (('A', 14), ('B', 34), ('C', 22), ('D', 10), ('E', 16)):
        ws.column_dimensions[col].width = w

    # ──────────────────────────────────────────── SHEET 4: Purchase Bills ──
    if purchase_bills:
        _write_project_bills_sheet(
            wb.create_sheet('Purchase Bills'), purchase_bills, stem_name,
            sheet_title=f'Purchase Bills — {display}',
            party_label='VENDOR', party_key='vendor_name', gstin_key='vendor_gstin',
            total_font=st['red_amount'], st=st)
    else:
        ws = wb.create_sheet('Purchase Bills')
        ws.cell(row=1, column=1, value='No purchase bills tagged to this project.')

    # ─────────────────────────────────────────────── SHEET 5: Sales Bills ──
    if sales_bills:
        _write_project_bills_sheet(
            wb.create_sheet('Sales Bills'), sales_bills, stem_name,
            sheet_title=f'Sales Bills — {display}',
            party_label='BUYER', party_key='buyer_name', gstin_key='buyer_gstin',
            total_font=st['green_amount'], st=st)
    else:
        ws = wb.create_sheet('Sales Bills')
        ws.cell(row=1, column=1, value='No sales bills tagged to this project.')

    # ───────────────────────────────────────────── SHEET 6: Labour Payments ──
    ws = wb.create_sheet('Labour Payments')
    ws.cell(row=1, column=1, value=f'Labour Payments — {display}').font = st['title_font']
    if not labour_summary.get('available', False):
        ws.cell(row=3, column=1, value=(
            'Could not reach the attendance app database — labour charges are '
            'unavailable.')).font = Font(italic=True, color='6B7280')
    else:
        # Monthly summary (mirrors the pop-up Labour tab)
        r = 3
        ws.cell(row=r, column=1, value='MONTHLY SUMMARY').font = st['subtitle_font']
        r += 1
        for ci, h in enumerate(['Month', 'Present Days', 'Workers', 'OT Hours', 'Cost'], 1):
            ws.cell(row=r, column=ci, value=h)
        style_header_row(ws, r, 5)
        r += 1
        for m in labour_summary.get('monthly', []):
            ws.cell(row=r, column=1, value=m.get('label', ''))
            ws.cell(row=r, column=2, value=m.get('days', 0))
            ws.cell(row=r, column=3, value=m.get('workers', 0))
            ws.cell(row=r, column=4, value=m.get('ot_hours', 0))
            ws.cell(row=r, column=5, value=float(m.get('cost', 0))).number_format = currency_fmt
            r += 1
        ws.cell(row=r, column=1, value='TOTAL').font = Font(bold=True)
        tc = ws.cell(row=r, column=5, value=labour_total)
        tc.font = st['green_amount']
        tc.number_format = currency_fmt
        r += 2
        # Per-worker detail per month
        labour_currency = currency_fmt
        for month_data in labour_monthly_detail:
            ws.cell(row=r, column=1,
                    value=f"{month_data['month_name'].upper()} — WORKER DETAIL").font = st['subtitle_font']
            r += 1
            wheaders = ['S.No', 'NAME', 'DESIGNATION', 'PRESENT DAYS', 'OT HOURS',
                        'BASE/DAY', 'BASE PAY', 'OT PAY', 'TOTAL SALARY']
            for ci, h in enumerate(wheaders, 1):
                ws.cell(row=r, column=ci, value=h)
            style_header_row(ws, r, len(wheaders))
            r += 1
            sno = 1
            for w in month_data['workers']:
                ws.cell(row=r, column=1, value=sno)
                ws.cell(row=r, column=2, value=w['name'])
                ws.cell(row=r, column=3, value=w['designation'])
                ws.cell(row=r, column=4, value=w['present_days'])
                ws.cell(row=r, column=5, value=w['ot_hours'])
                ws.cell(row=r, column=6, value=w['base_salary_per_day']).number_format = labour_currency
                ws.cell(row=r, column=7, value=w['base_pay']).number_format = labour_currency
                ws.cell(row=r, column=8, value=w['ot_pay']).number_format = labour_currency
                ws.cell(row=r, column=9, value=w['total_salary']).number_format = labour_currency
                sno += 1
                r += 1
            ws.cell(row=r, column=3, value='Month total').font = Font(bold=True)
            tc = ws.cell(row=r, column=9, value=float(month_data.get('total_salary', 0)))
            tc.font = st['green_amount']
            tc.number_format = labour_currency
            r += 2
    for col, w in (('A', 16), ('B', 24), ('C', 16), ('D', 13), ('E', 12),
                   ('F', 12), ('G', 13), ('H', 12), ('I', 14)):
        ws.column_dimensions[col].width = w

    # ──────────────────────────────────────── SHEET 7: Consolidated Summary ──
    ws = wb.create_sheet('Consolidated Summary')
    NUM = 3
    cr = 1
    for c in range(1, NUM + 1):
        ws.cell(row=cr, column=c).fill = st['project_name_fill']
    ws.cell(row=cr, column=1, value=f'PROJECT :  {display.upper()}').font = st['project_name_font']
    cr += 2

    def section(ws, row, text):
        ws.cell(row=row, column=1, value=text).font = st['section_bold']
        for c in range(1, NUM + 1):
            ws.cell(row=row, column=c).fill = st['green_fill']
        return row + 1

    cr = section(ws, cr, 'CLIENT PAYMENTS')
    kv_row(ws, cr, 'PO Value', po_value, fmt=currency_fmt, font=st['blue_amount']); cr += 1
    kv_row(ws, cr, 'Received — Bank (KVB)', received_bank, fmt=currency_fmt, font=st['income_font']); cr += 1
    kv_row(ws, cr, 'Received — Cash', received_cash, fmt=currency_fmt, font=st['income_font']); cr += 1
    kv_row(ws, cr, 'Total Received', received_total, fmt=currency_fmt, font=st['income_font']); cr += 1
    kv_row(ws, cr, ('Excess Received' if balance < -0.5 else 'Balance Due'), abs(balance),
           fmt=currency_fmt, font=(st['red_amount'] if balance > 0.5 else st['green_amount'])); cr += 2

    cr = section(ws, cr, 'SPEND COMPOSITION')
    kv_row(ws, cr, 'Material Purchase (bills)', material_total, fmt=currency_fmt); cr += 1
    kv_row(ws, cr, 'Other Expense', other_expense_total, fmt=currency_fmt); cr += 1
    kv_row(ws, cr, 'Labour Payment', labour_total, fmt=currency_fmt, font=st['blue_amount']); cr += 1
    kv_row(ws, cr, 'Total Spend', spend_total, fmt=currency_fmt, font=st['expense_font']); cr += 2

    cr = section(ws, cr, 'NET POSITION')
    kv_row(ws, cr, 'Received − Spend', received_total - spend_total, fmt=currency_fmt,
           font=(st['green_amount'] if received_total - spend_total >= 0 else st['red_amount'])); cr += 1
    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 22

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    safe_stem = re.sub(r'[^A-Za-z0-9_-]+', '_', stem_name).strip('_') or f'project_{project_id}'
    filename = f"Project_{project_id}_{safe_stem}_{now_ist().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )
