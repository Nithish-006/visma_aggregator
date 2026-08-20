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
    //   linkThirdParty - render the third-party deduction as a link to the
    //              ledger tab. Only where a listener for it exists.
    // Returns an HTML string, or null when there is nothing worth showing.
    function render(opts) {
        const p = (opts && opts.project) || {};
        const s = (opts && opts.insights && opts.insights.summary) || null;
        const rec = Number((s ? s.received_total : p.received_total)) || 0;
        const bank = Number((s ? s.received_bank : p.received_bank)) || 0;
        const cash = Number((s ? s.received_cash : p.received_cash)) || 0;
        // The third-party ledger, both ways: of what the client paid, the part
        // forwarded straight on to someone else (civil, design, transport), and
        // money someone other than the client paid us against this project.
        // Pass-throughs both: they move the cash in hand and what the client
        // still owes, and nothing else. See helpers/project_finance.
        const pick = (key) => Number((s ? s[key] : p[key])) || 0;
        const tpOut = Number((s ? (s.third_party_out_total ?? s.third_party_total)
                                : (p.third_party_out_total ?? p.third_party_total))) || 0;
        const tpIn = pick('third_party_in_total');
        // The net adjustment to the receipts. Positive = more passed on than
        // came in, so it reads as a deduction; negative = the reverse.
        const thirdParty = tpOut - tpIn;
        const hasThirdParty = tpOut > 0.5 || tpIn > 0.5;
        const netRec = rec - thirdParty;
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
        // Net, not gross — see helpers/project_finance: money that came in for a
        // third party and went straight back out never paid down our contract.
        const receivable = s ? (Number(s.receivable) || 0) : contract - netRec;
        // With no PO there is no contract, so both the receivable and the
        // profit fall back to what we billed (see helpers/project_finance).
        // Labelling that "Contract" would state an agreement that doesn't
        // exist, so every line built from it names its real source instead.
        const fromPo = s ? (s.contract && s.contract.source === 'po') : po > 0;

        // Only bail when there is genuinely nothing to say. This guard predates
        // the cost breakdown, and a project can have real costs (bills, labour,
        // overhead) with no PO, no sales bills and nothing received yet —
        // hiding on value alone would blank out its spend and loss entirely.
        const hasCosts = !!(s && Number(s.spend_total) > 0);
        if (contract <= 0 && rec <= 0 && !hasCosts) return null;
        // Percentages track the same denominator as the figure above them,
        // otherwise the hero states a balance the bar underneath contradicts.
        const pct = contract > 0 ? Math.min(100, Math.round((netRec / contract) * 100)) : null;
        const dueLabel = receivable < -0.5 ? 'Client overpaid by' : 'Client yet to pay';
        const dueCls = receivable > 0.5 ? 'due' : 'settled';

        // ── Hero: the three questions people open this for ──
        // "Client yet to pay" is what the client still owes against the
        // contract; "Total Expenses" is everything the project has cost;
        // "Profit" is what the job earns — the contract (the PO as varied, or
        // the actuals once measured) less that cost, which is the subtraction
        // the client actually runs the project by.
        //
        // It used to be cash-in-hand less cost, and that made a profitable
        // project read as a loss for as long as the client was slow to pay.
        // Cash is still a real question, just not the headline one, so the
        // three bottom lines of the Excel export (net position, profit, billed
        // profit) sit behind the chevron beside this figure, named exactly as
        // the export names them. They share a cost total and differ only in
        // what it is struck against — cash received, the contract, or the
        // invoices raised — which is why none of them is "the" balance.
        const spend = s ? (Number(s.spend_total) || 0) : 0;
        // Net, not gross — money passed on to a third party is not in hand to
        // set against the spend.
        const cashPosition = s ? (Number(s.cash_position) || 0) : 0;
        const profit = s ? (Number(s.profit) || 0) : 0;
        const billedProfit = s ? (Number(s.billed_profit) || 0) : 0;
        const hasSalesBills = !!(s && s.has_sales_bills);
        const contractLabel = fromPo ? 'PO contract value' : 'billed value';
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
                <span class="proj-hero-k">
                    Profit
                    <button type="button" class="proj-hero-toggle" data-glance-toggle="net"
                            aria-expanded="false" title="Show all three net positions">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                </span>
                <span class="proj-hero-v ${profit >= 0 ? 'profit' : 'loss'}">${formatSignedINR(profit)}</span>
                <span class="proj-hero-sub">${formatINRCompact(contract)} ${fromPo ? 'contract' : 'billed'} − ${formatINRCompact(spend)} spent</span>
            </div>` : `
            <div class="proj-hero-cell">
                <span class="proj-hero-k">Profit</span>
                <span class="proj-hero-v is-loading">…</span>
                <span class="proj-hero-sub">&nbsp;</span>
            </div>`;

        // The drawer. Rendered collapsed and only when insights have landed —
        // there is nothing to disclose from the cached row alone.
        const nRow = (label, formula, value, note) => `
                <div class="proj-net-row">
                    <div class="proj-net-label">
                        <span class="proj-net-k">${label}</span>
                        <span class="proj-net-f">${formula}</span>
                    </div>
                    <span class="proj-net-v ${note ? 'is-note' : (Number(value) >= 0 ? 'profit' : 'loss')}">${note || formatSignedINR(value)}</span>
                </div>`;
        const netDrawer = s ? `
            <div class="proj-net-drawer" data-glance-panel="net" hidden>
                ${nRow('Net Position',
                       `${formatINRCompact(netRec)} ${hasThirdParty ? "net received" : "received"} − ${formatINRCompact(spend)} cost · cash in hand against cash spent`,
                       cashPosition)}
                ${nRow(fromPo ? 'Profit (contract)' : 'Profit (billed — no PO)',
                       `${formatINRCompact(contract)} ${contractLabel} − ${formatINRCompact(spend)} cost · what the job earns, however much is invoiced`,
                       profit)}
                ${nRow('Billed Profit',
                       hasSalesBills
                           ? `${formatINRCompact(billed)} sales bills − ${formatINRCompact(spend)} cost · earned on the invoices raised so far`
                           : 'nothing invoiced yet, so there is no billed figure to strike',
                       billedProfit,
                       hasSalesBills ? null : 'No sales bills tagged')}
            </div>` : '';
        const hero = `
            <div class="proj-hero-wrap">
                <div class="proj-hero proj-hero-3">
                    <div class="proj-hero-cell">
                        <span class="proj-hero-k">${dueLabel}</span>
                        <span class="proj-hero-v ${dueCls}">${formatINR(Math.abs(receivable))}</span>
                        <span class="proj-hero-sub">${pct != null ? `${pct}% of ${formatINRCompact(contract)} received${hasThirdParty ? ", net" : ""}` : '&nbsp;'}</span>
                    </div>
                    ${expensesCell}
                    ${netCell}
                </div>
                ${netDrawer}
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
        const lRow = (label, value, cls = '', fmt = formatINR, suffix = '') => `
                    <div class="proj-ladder-row ${cls}"><dt>${label}</dt><dd>${fmt(value)}${suffix}</dd></div>`;
        const lHead = (label, hint = '') => `
                    <div class="proj-ladder-head"><span>${label}</span>${hint ? `<span class="proj-ladder-hint">${hint}</span>` : ''}</div>`;

        let ladderRows = '';
        if (fromPo && actCount) {
            // Actuals replace the PO and any variations outright (see
            // resolve_contract), so the ladder states the figure in force and
            // says in its head where that figure came from. The rungs it
            // replaced are history, not arithmetic — they belong in the PO
            // ledger, which keeps all three books side by side. Struck through
            // here they were a column of crossed-out numbers standing between
            // the reader and the one figure that governs.
            ladderRows += lHead('Contract', `actuals — ${actCount} ${actCount > 1 ? 'entries' : 'entry'} measured`);
            ladderRows += lRow('Basic value', actBasic, 'is-sub');
            ladderRows += lRow('GST', actGst, 'is-sub');
            ladderRows += lRow('Final PO value', actTotal, 'is-revised');
        } else if (fromPo) {
            ladderRows += lHead('Contract', 'as per PO');
            ladderRows += lRow('Basic value', baseBasic, 'is-sub');
            ladderRows += lRow('GST', baseGst, 'is-sub');
            ladderRows += lRow('Total', baseTotal, 'is-sub is-total');
            // Only once something has actually been agreed: with no changes the
            // block would be three zeros and "Revised PO value" would just
            // restate the Total directly above it.
            if (varCount) {
                ladderRows += lHead('Variations', `${varCount} change${varCount > 1 ? 's' : ''} agreed`);
                ladderRows += lRow('Basic value', varBasic, 'is-sub', formatDeltaINR);
                ladderRows += lRow('GST', varGst, 'is-sub', formatDeltaINR);
                ladderRows += lRow('Total', varTotal, 'is-sub is-total', formatDeltaINR);
                ladderRows += lRow('Revised PO value', baseTotal + varTotal, 'is-revised');
            }
        } else if (contract > 0) {
            ladderRows += lHead('Billed', 'no PO yet — from sales bills');
            ladderRows += lRow('Total', contract, 'is-sub is-total');
        }
        // The pass-through, spelled out in the sequence the client reads it in:
        // they paid us X, we passed on Y, someone else paid us Z, we have W. It
        // gets its own head and indent — the same blocked shape as the contract
        // rungs — so that on a project carrying both variations and actuals the
        // receipt lines still read as one block instead of trailing off the end
        // of a fifteen-row ladder. With an untouched ledger it stays the single
        // row it was, rather than a head and lines saying nothing happened.
        if (hasThirdParty) {
            // The head names only the legs that actually happened — "less what we
            // passed on" over a project that only ever received from a third
            // party describes the opposite of what the rows below it show.
            const headNote = tpOut > 0.5 && tpIn > 0.5
                ? 'third-party payments both ways'
                : (tpOut > 0.5 ? 'less what we passed on' : 'plus what a third party paid us');
            ladderRows += lHead('Received', headNote);
            ladderRows += lRow('Payments received', rec, 'is-sub', formatINR, splitNote);
            // Deep-links to the Ledger → Third-party payments tab, but only
            // where something is listening for it (the registry modal). The
            // summary page renders the same ladder with no tabs to jump to.
            const tpLink = (text, title) => ((opts && opts.linkThirdParty)
                ? `<button type="button" class="proj-ladder-link" data-glance-goto="third-party"
                        title="${title}">${text}</button>`
                : text);
            if (tpOut > 0.5) {
                ladderRows += lRow(
                    tpLink('Less: paid to third parties', 'Show every third-party payment'),
                    -tpOut, 'is-sub is-deduct', formatDeltaINR);
            }
            if (tpIn > 0.5) {
                ladderRows += lRow(
                    tpLink('Add: received from third parties', 'Show every third-party receipt'),
                    tpIn, 'is-sub', formatDeltaINR);
            }
            ladderRows += lRow('Net for VISMA', netRec, 'is-revised');
        } else {
            ladderRows += lRow('Payments received', rec, '', formatINR, splitNote);
        }
        // Struck against the net: money that arrived earmarked for a contractor
        // and went straight out again never paid down our own work, so the
        // ladder reads as one continuous subtraction — contract, less what
        // actually stayed with us, equals what is still outstanding. Named on
        // the row only where there is a deduction to name.
        const balNote = hasThirdParty
            ? `<span class="proj-ladder-split">contract less the net received</span>` : '';
        ladderRows += `
                    <div class="proj-ladder-row is-balance"><dt>${receivable < -0.5 ? 'Client overpaid by' : 'Current balance'}</dt><dd class="${dueCls}">${formatINR(Math.abs(receivable))}${balNote}</dd></div>`;

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
        // No profit/balance line here: the hero owns the bottom line (profit =
        // contract − cost, with the other two positions behind its chevron), and
        // a second one against billed value beside it only invited the reader to
        // mix the two up.
        return `
            <div class="proj-ov-panel proj-ov-costs">${head}
                ${labourWarning}
                <ul class="proj-cost-list">${rows}</ul>
                <div class="proj-cost-foot">
                    <div class="proj-cost-foot-row is-total">
                        <span>Total expenses</span><span>${formatINR(total)}</span>
                    </div>
                </div>
            </div>`;
    }

    // The hero's profit chevron. Bound once on the document rather than after
    // each render: both callers repaint the panel by replacing innerHTML (the
    // registry twice per open, from the cached row and then from insights), so
    // a listener attached to the button would be thrown away with it.
    document.addEventListener('click', function (e) {
        const btn = e.target.closest && e.target.closest('[data-glance-toggle="net"]');
        if (!btn) return;
        const wrap = btn.closest('.proj-hero-wrap');
        const panel = wrap && wrap.querySelector('[data-glance-panel="net"]');
        if (!panel) return;
        const open = panel.hasAttribute('hidden');
        if (open) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', '');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        btn.classList.toggle('is-open', open);
    });

    return {
        render: render,
        escapeHtml: escapeHtml,
        formatINR: formatINR,
        formatSignedINR: formatSignedINR,
        formatINRCompact: formatINRCompact,
        formatDeltaINR: formatDeltaINR,
    };
})();
