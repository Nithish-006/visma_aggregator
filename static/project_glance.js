/* ============================================================================
   Project at a glance -- the shared money panels.

   The registry detail pop-up and the project summary page answer the same
   questions about a project, so they render from here rather than each building
   their own. They also read the same endpoint (/api/projects/<id>/insights),
   which is what stops the two screens disagreeing -- the drift that
   helpers/project_finance.py exists to prevent on the server, applied to the
   client.

   render() takes data and returns HTML (or null when there is genuinely nothing
   to say); the caller owns the element it goes into.

   Styling lives in project_glance.css. Load both before the page's own files.
   ============================================================================ */
window.ProjectGlance = (function () {
    'use strict';

    function escapeHtml(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Indian-format a number with a ₹ prefix (e.g. 2325190 -> ₹23,25,190.00).
    // Always two decimals: mixing ₹2,00,000 with ₹5,505.90 in one column makes
    // the figures hard to scan, and a lone ".5" reads as a rounding bug.
    function formatINR(value) {
        const n = Number(value) || 0;
        return '₹' + n.toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    // Signed: the minus goes before the ₹ ("-₹5,000.00"), not after it, which
    // is what toLocaleString would do. Used where a figure can legitimately go
    // negative and the sign is the whole point.
    function formatSignedINR(value) {
        const n = Number(value) || 0;
        return (n < 0 ? '-' : '') + formatINR(Math.abs(n));
    }

    // Compact Indian-format for the card finance strip so values stay on a
    // single line (e.g. 22165179 -> ₹2.22 Cr, 6640450 -> ₹66.40 L).
    function formatINRCompact(value) {
        const n = Number(value) || 0;
        const sign = n < 0 ? '-' : '';
        const abs = Math.abs(n);
        if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)} Cr`;
        if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)} L`;
        return sign + '₹' + abs.toLocaleString('en-IN', { maximumFractionDigits: 0 });
    }

    // Variations are deltas, so the sign is the point: formatSignedINR marks
    // negatives but leaves additions bare, which in a column that runs both ways
    // reads as an absolute figure rather than an increase.
    function formatDeltaINR(value) {
        const n = Number(value) || 0;
        return (n > 0 ? '+' : '') + formatSignedINR(n);
    }

    // ── Project at a glance ────────────────────────────
    // Mirrors the summary sheet the client actually works from: a value ladder
    // (basic -> GST -> total -> received -> balance), the GST position of
    // purchases against sales, and the cost breakdown. Called twice per open —
    // once from the cached registry row for an instant paint, then again once
    // /insights lands with the full picture.
    // opts: { project, insights, editableOverhead }
    //   project  - the decorated registry row (carries po_base_* / po_var_*), so
    //              the panel can paint before insights lands.
    //   insights - the /api/projects/<id>/insights payload, or null while it is
    //              in flight. Its `summary` is the server's money model.
    // Returns an HTML string, or null when there is nothing worth showing.
    function render(opts) {
        const p = (opts && opts.project) || {};
        const s = (opts && opts.insights && opts.insights.summary) || null;
        const rec = Number((s ? s.received_total : p.received_total)) || 0;
        const bank = Number((s ? s.received_bank : p.received_bank)) || 0;
        const cash = Number((s ? s.received_cash : p.received_cash)) || 0;
        const po = Number(p.po_total_value) || 0;

        // What the client owes is measured against the contract — the PO plus
        // any agreed variations, GST included — not against what we've invoiced
        // so far. The server settles that (helpers/project_finance); before
        // insights land, the cached row's PO value is already
        // variation-inclusive, and a project with no PO falls back to the
        // billed total because that is the only promise on record.
        const billed = s ? (Number(s.value && s.value.total) || 0) : 0;
        const contract = s ? (Number(s.contract && s.contract.total) || 0)
                           : (po > 0 ? po : billed);
        const receivable = s ? (Number(s.receivable) || 0) : contract - rec;

        // Only bail when there is genuinely nothing to say. This guard predates
        // the cost breakdown, and a project can have real costs (bills, labour,
        // overhead) with no PO, no sales bills and nothing received yet —
        // hiding on value alone would blank out its spend and loss entirely.
        const hasCosts = !!(s && Number(s.spend_total) > 0);
        if (contract <= 0 && rec <= 0 && !hasCosts) return null;
        // Percentages track the same denominator as the figure above them,
        // otherwise the hero states a balance the bar underneath contradicts.
        const pct = contract > 0 ? Math.min(100, Math.round((rec / contract) * 100)) : null;
        const dueLabel = receivable < -0.5 ? 'Client overpaid by' : 'Client yet to pay';
        const dueCls = receivable > 0.5 ? 'due' : 'settled';

        // ── Hero: the three questions people open this for ──
        // "Client yet to pay" is what the client still owes against the contract;
        // "Total Expenses" is everything the project has cost; "Net Balance" is
        // cash actually in hand against that spend — what the client has *paid*
        // minus what has gone out, not billed value minus cost. Billing is a
        // promise; this line is the money position, so a project can be in the
        // black on profit and still short here until the client pays.
        const spend = s ? (Number(s.spend_total) || 0) : 0;
        const netBalance = rec - spend;
        const expensesCell = s ? `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Total Expenses</span>
                <span class="proj-hero-v">${formatINR(spend)}</span>
                <span class="proj-hero-sub">&nbsp;</span>
            </div>` : `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Total Expenses</span>
                <span class="proj-hero-v is-loading">…</span>
                <span class="proj-hero-sub">&nbsp;</span>
            </div>`;
        const netCell = s ? `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Net Balance</span>
                <span class="proj-hero-v ${netBalance >= 0 ? 'profit' : 'loss'}">${formatSignedINR(netBalance)}</span>
                <span class="proj-hero-sub">${formatINRCompact(rec)} paid − ${formatINRCompact(spend)} spent</span>
            </div>` : `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Net Balance</span>
                <span class="proj-hero-v is-loading">…</span>
                <span class="proj-hero-sub">&nbsp;</span>
            </div>`;
        const hero = `
            <div class="proj-hero proj-hero-3">
                <div class="proj-hero-cell">
                    <span class="proj-hero-k">${dueLabel}</span>
                    <span class="proj-hero-v ${dueCls}">${formatINR(Math.abs(receivable))}</span>
                    <span class="proj-hero-sub">${pct != null ? `${pct}% of ${formatINRCompact(contract)} received` : '&nbsp;'}</span>
                </div>
                ${expensesCell}
                ${netCell}
            </div>
            ${pct != null ? `<div class="proj-pay-bar"><div class="proj-pay-bar-fill" style="width:${pct}%"></div></div>` : ''}`;

        // ── Value ladder ──
        // The contract, derived in full: the PO as signed, the changes agreed
        // since, and the revised figure the client is measured against. Every
        // row here is the PO's own — the sales bills are a different question
        // (what we've invoiced) and answer it on the Bills tab and in the
        // hero's Balance, not in the middle of this subtraction.
        const splitNote = cash > 0
            ? `<span class="proj-ladder-split">${formatINRCompact(bank)} bank + ${formatINRCompact(cash)} cash</span>`
            : '';
        // The baseline split and both ledger rollups all ride on the project
        // row (_decorate_project_row), so the whole ladder paints from the
        // cached registry entry and doesn't wait on insights.
        const baseBasic = Number(p.po_base_taxable_value) || 0;
        const baseGst = Number(p.po_base_total_tax) || 0;
        const baseTotal = Number(p.po_base_total_value) || 0;
        const varBasic = Number(p.po_var_taxable) || 0;
        const varGst = Number(p.po_var_tax) || 0;
        const varTotal = Number(p.po_var_total) || 0;
        const varCount = Number(p.po_var_count) || 0;
        const actBasic = Number(p.po_act_taxable) || 0;
        const actGst = Number(p.po_act_tax) || 0;
        const actTotal = Number(p.po_act_total) || 0;
        const actCount = Number(p.po_act_count) || 0;
        // With no PO there is no contract, so the receivable falls back to what
        // we billed (see helpers/project_finance). Labelling that "Contract"
        // would state an agreement that doesn't exist, so the row names its
        // real source instead.
        const fromPo = s ? (s.contract && s.contract.source === 'po') : po > 0;

        const lRow = (label, value, cls = '', fmt = formatINR, suffix = '') => `
                    <div class="proj-ladder-row ${cls}"><dt>${label}</dt><dd>${fmt(value)}${suffix}</dd></div>`;
        const lHead = (label, hint = '') => `
                    <div class="proj-ladder-head"><span>${label}</span>${hint ? `<span class="proj-ladder-hint">${hint}</span>` : ''}</div>`;

        let ladderRows = '';
        if (fromPo) {
            // Once actuals exist they replace the PO and any variations
            // outright (see resolve_contract), so the rungs above them are
            // struck through — kept as the history of how the figure moved, but
            // plainly no longer the number in force.
            const supAbove = actCount ? ' is-superseded' : '';
            ladderRows += lHead('Contract', 'as per PO');
            ladderRows += lRow('Basic value', baseBasic, 'is-sub' + supAbove);
            ladderRows += lRow('GST', baseGst, 'is-sub' + supAbove);
            ladderRows += lRow('Total', baseTotal, 'is-sub is-total' + supAbove);
            // Only once something has actually been agreed: with no changes the
            // block would be three zeros and "Revised PO value" would just
            // restate the Total directly above it.
            if (varCount) {
                ladderRows += lHead('Variations', `${varCount} change${varCount > 1 ? 's' : ''} agreed`);
                ladderRows += lRow('Basic value', varBasic, 'is-sub' + supAbove, formatDeltaINR);
                ladderRows += lRow('GST', varGst, 'is-sub' + supAbove, formatDeltaINR);
                ladderRows += lRow('Total', varTotal, 'is-sub is-total' + supAbove, formatDeltaINR);
                ladderRows += lRow('Revised PO value', baseTotal + varTotal, 'is-revised' + supAbove);
            }
            // Actuals: the work as finally measured, replacing everything above.
            if (actCount) {
                ladderRows += lHead('Actuals', `${actCount} ${actCount > 1 ? 'entries' : 'entry'} measured`);
                ladderRows += lRow('Basic value', actBasic, 'is-sub');
                ladderRows += lRow('GST', actGst, 'is-sub');
                ladderRows += lRow('Total', actTotal, 'is-sub is-total');
                ladderRows += lRow('Final PO value', actTotal, 'is-revised');
            }
        } else if (contract > 0) {
            ladderRows += lHead('Billed', 'no PO yet — from sales bills');
            ladderRows += lRow('Total', contract, 'is-sub is-total');
        }
        ladderRows += lRow('Payments received', rec, '', formatINR, splitNote);
        ladderRows += `
                    <div class="proj-ladder-row is-balance"><dt>${receivable < -0.5 ? 'Client overpaid by' : 'Current balance'}</dt><dd class="${dueCls}">${formatINR(Math.abs(receivable))}</dd></div>`;

        const ladder = `
            <div class="proj-ov-panel">
                <div class="proj-ov-head"><h4 class="proj-ov-title">Project value</h4></div>
                <div class="proj-ov-body">
                <dl class="proj-ladder">${ladderRows}
                </dl>
                </div>
            </div>`;

        // ── GST position ──
        // Laid out like the value ladder beside it — same heads, same indented
        // basic/GST/total under each — rather than a 2x3 grid of its own. Two
        // panels side by side that tabulate the same three figures should read
        // the same way, and the grid left this one standing half the height of
        // its neighbour.
        let gstPanel = '';
        if (s) {
            const g = s.gst;
            const hasBills = g.purchase_total > 0 || g.sales_total > 0;
            // Negative = input GST exceeds output: a credit, not something owed.
            const isCredit = g.extra < -0.5;
            gstPanel = `
            <div class="proj-ov-panel">
                <div class="proj-ov-head"><h4 class="proj-ov-title">GST position</h4></div>
                <div class="proj-ov-body">
                ${hasBills ? `
                <dl class="proj-ladder">
                    ${lHead('Purchase', 'bills in')}
                    ${lRow('Basic value', g.purchase_basic, 'is-sub')}
                    ${lRow('GST', g.purchase_gst, 'is-sub')}
                    ${lRow('Total', g.purchase_total, 'is-sub is-total')}
                    ${lHead('Sales', 'bills out')}
                    ${lRow('Basic value', g.sales_basic, 'is-sub')}
                    ${lRow('GST', g.sales_gst, 'is-sub')}
                    ${lRow('Total', g.sales_total, 'is-sub is-total')}
                </dl>
                <div class="proj-gst-extra ${isCredit ? 'is-credit' : ''}">
                    <span class="proj-gst-extra-k">${isCredit ? 'GST credit' : 'GST extra'}</span>
                    <span class="proj-gst-extra-v">${formatINR(Math.abs(g.extra))}</span>
                </div>
                ${isCredit ? `<p class="proj-ov-note">Input GST exceeds output GST — carried forward as credit, not counted as a cost.</p>` : ''}
                ` : `<p class="proj-tab-empty">No bills tagged to this project yet.</p>`}
                </div>
            </div>`;
        }

        return hero + `<div class="proj-ov-grid">${ladder}${gstPanel}</div>` + renderCostPanel(s, opts);
    }

    // ── Expenses, highest first ───────────────────────
    // Lines and totals come from the server so they always sum to spend_total.
    // Overhead is the one hand-entered line and is edited in place here.
    function renderCostPanel(s, opts) {
        if (!s) return '';
        const lines = s.cost_lines || [];
        // "Expenses" doubles as the head of the left column, so the band reads
        // as a table header rather than a title stacked on one.
        const head = `
            <div class="proj-ov-head">
                <h4 class="proj-ov-title">Expenses</h4>
                <span class="proj-cost-head-amt">Amount</span>
            </div>`;
        if (!lines.length) {
            return `<div class="proj-ov-panel proj-ov-costs">${head}
                <p class="proj-tab-empty proj-cost-empty">No costs recorded for this project yet.</p>
            </div>`;
        }
        const total = Number(s.spend_total) || 0;
        const rows = lines.map(l => {
            // A number input can't render "₹2,00,000.00", and a bare 200000 in a
            // column of formatted figures looks broken. So it's a text field
            // showing the formatted value at rest, swapped to the raw number on
            // focus (see the focusin/focusout handlers).
            const cell = (l.editable && opts && opts.editableOverhead)
                ? `<input class="proj-cost-input" type="text" inputmode="decimal"
                          value="${l.amount ? formatINR(l.amount) : ''}" placeholder="${formatINR(0)}"
                          data-overhead-input data-raw="${l.amount || 0}"
                          aria-label="Overhead amount in rupees"
                          title="Costs no bill or bank row covers. Counts toward the total and profit.">`
                : formatINR(l.amount);
            return `
            <li class="proj-cost-row${(l.editable && opts && opts.editableOverhead) ? ' is-editable' : ''}" data-source="${escapeHtml(l.source)}">
                <span class="proj-cost-k">${escapeHtml(l.label)}</span>
                <span class="proj-cost-v">${cell}</span>
            </li>`;
        }).join('');
        // Labour comes from the attendance app. If that's unreachable it counts
        // as 0, so the total is short — say so rather than presenting an
        // incomplete figure as final.
        const labourWarning = s.labour_available === false
            ? `<p class="proj-cost-warn">Labour is missing — the attendance app
               couldn't be reached, so the total below excludes it.</p>`
            : '';
        // Material-purchase payments here that no purchase bill accounts for —
        // a likely project mis-tag on the bank side. A gentle nudge to verify.
        const noBillCount = (opts && opts.insights && opts.insights.expenses
            && opts.insights.expenses.no_bill_count) || 0;
        const noBillWarning = noBillCount > 0
            ? `<p class="proj-cost-warn">${noBillCount} material-purchase payment${noBillCount > 1 ? 's have' : ' has'}
               no matching purchase bill — worth verifying the project tag on the KVB statement.</p>`
            : '';
        // No profit/balance line here: the hero owns the money position (Net
        // Balance = paid − spent), and a second "Balance" against billed value
        // beside it only invited the reader to mix the two up.
        return `
            <div class="proj-ov-panel proj-ov-costs">${head}
                ${labourWarning}
                ${noBillWarning}
                <ul class="proj-cost-list">${rows}</ul>
                <div class="proj-cost-foot">
                    <div class="proj-cost-foot-row is-total">
                        <span>Total expenses</span><span>${formatINR(total)}</span>
                    </div>
                </div>
            </div>`;
    }

    return {
        render: render,
        escapeHtml: escapeHtml,
        formatINR: formatINR,
        formatSignedINR: formatSignedINR,
        formatINRCompact: formatINRCompact,
        formatDeltaINR: formatDeltaINR,
    };
})();
