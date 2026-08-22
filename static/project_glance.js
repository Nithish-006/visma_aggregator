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

    // Whole rupees, for the money panels. Every figure there is a roll-up of
    // many rows — a contract, a spend total, a balance — and at that scale the
    // paise are noise: two digits of it on twenty figures, none of which a
    // decision turns on. Individual ledger and bill lines keep formatINR, where
    // the paise are the invoice's own and belong on screen.
    function formatRupees(value) {
        const n = Math.round(Number(value) || 0);
        return '₹' + Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
    }
    // The minus goes before the ₹ ("-₹5,000"), not after it.
    function formatSignedRupees(value) {
        const n = Math.round(Number(value) || 0);
        return (n < 0 ? '-' : '') + formatRupees(n);
    }
    // Deltas mark both directions — a bare figure in a column that runs both
    // ways reads as an absolute value rather than an increase.
    function formatDeltaRupees(value) {
        const n = Math.round(Number(value) || 0);
        return (n > 0 ? '+' : '') + formatSignedRupees(n);
    }
    // Wrapped so the figure can't break across lines: on a phone the matrix
    // cells become flex rows with the column name on the left.
    const amt = (str) => `<span class="proj-amt">${escapeHtml(str)}</span>`;
    const moneyHtml = (v) => amt(formatRupees(v));
    const deltaHtml = (v) => amt(formatDeltaRupees(v));

    // ── Project at a glance ────────────────────────────
    // Mirrors the summary sheet the client actually works from: the contract
    // and what it is derived from, what has actually been received against it,
    // the GST position of purchases against sales, and the cost breakdown.
    // Every block leads with its result and tabulates the components under it,
    // so the three figures worth knowing are readable in one pass and the
    // arithmetic is there for anyone who wants it. Called twice per open —
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
                <span class="proj-hero-v">${formatRupees(spend)}</span>
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
                <span class="proj-hero-v ${profit >= 0 ? 'profit' : 'loss'}">${formatSignedRupees(profit)}</span>
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
                    <span class="proj-net-v ${note ? 'is-note' : (Number(value) >= 0 ? 'profit' : 'loss')}">${note || formatSignedRupees(value)}</span>
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
                        <span class="proj-hero-v ${dueCls}">${formatRupees(receivable)}</span>
                        <span class="proj-hero-sub">${pct != null ? `${pct}% of ${formatINRCompact(contract)} received${hasThirdParty ? ", net" : ""}` : '&nbsp;'}</span>
                    </div>
                    ${expensesCell}
                    ${netCell}
                </div>
                ${netDrawer}
            </div>
            ${pct != null ? `<div class="proj-pay-bar"><div class="proj-pay-bar-fill" style="width:${pct}%"></div></div>` : ''}`;

        // ── Project value ──
        // Three things and nothing else: what the job is worth, what has come
        // in, and what of that actually stayed with us. The balance is not
        // here — the hero already states it as "Client yet to pay", and a
        // second copy at the foot of this panel only invited the reader to
        // check one against the other.
        //
        // The head carries the two facts wanted before any component: which
        // book governs, and how far it has moved from the PO as signed. The
        // components sit under it, and the books a later one replaced are
        // behind "View details" rather than on screen by default.
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
        const hasActuals = fromPo && actCount > 0;
        const hasVars = fromPo && varCount > 0;

        // One row of the matrix. `delta` signs the figures, for a book that is
        // a set of changes rather than a value in its own right; a null
        // component prints as a dash, for the billed case that has no split.
        const mRow = (label, basic, gst, total, o = {}) => {
            const fmt = o.delta ? deltaHtml : moneyHtml;
            const cell = (v) => (v == null ? '<span class="proj-mx-nil">—</span>' : fmt(v));
            // Whole rupees have to keep adding up. Rounding basic and GST apart
            // can leave the row a rupee short of its own total (0.4 + 0.4 shows
            // as 0 + 0 = 1), which on an accounts screen reads as a bug in the
            // figures rather than in the display. So where the three genuinely
            // reconcile at full precision, the GST shown is what is left of the
            // rounded total after the rounded basic — off the true rounded GST
            // by at most a rupee, and never off the row. Where they don't
            // reconcile, each is rounded on its own and the discrepancy stays
            // visible, because then it is real.
            if (basic != null && gst != null && total != null) {
                const bR = Math.round(basic);
                const tR = Math.round(total);
                if (Math.abs(basic + gst - total) < 0.005) { basic = bR; gst = tR - bR; total = tR; }
            }
            return `
                        <tr class="proj-mx-row ${o.cls || ''}">
                            <th scope="row">
                                <span class="proj-mx-book">${label}</span>
                                ${o.count ? `<span class="proj-mx-count">${o.count}</span>` : ''}
                                ${o.note ? `<span class="proj-mx-note">${o.note}</span>` : ''}
                            </th>
                            <td data-label="Basic">${cell(basic)}</td>
                            <td data-label="GST">${cell(gst)}</td>
                            <td data-label="Total">${cell(total)}</td>
                        </tr>`;
        };
        const mTable = (rows, hiddenRows) => `
                    <table class="proj-mx">
                        <thead>
                            <tr><th scope="col"><span class="proj-sr">Source</span></th>
                                <th scope="col">Basic</th><th scope="col">GST</th><th scope="col">Total</th></tr>
                        </thead>
                        ${hiddenRows ? `<tbody data-glance-panel="books" hidden>${hiddenRows}</tbody>` : ''}
                        <tbody>${rows}</tbody>
                    </table>`;

        // How far the contract has moved from the PO as signed, and which way.
        // On an actuals project this is the whole point of the block: measured
        // work can land well under what was quoted, and that wants saying in
        // the head rather than left for the reader to subtract.
        const moved = fromPo ? (contract - baseTotal) : 0;
        const movedPct = (fromPo && baseTotal > 0.5) ? (moved / baseTotal) * 100 : null;
        const deltaChip = (movedPct != null && Math.abs(moved) > 0.5)
            ? `<span class="proj-chip-delta ${moved > 0 ? 'is-up' : 'is-down'}">${
                   (moved > 0 ? '+' : '') + formatINRCompact(moved)
               } (${moved > 0 ? '+' : ''}${movedPct.toFixed(1)}%)</span>`
            : '';
        const kind = !fromPo ? 'From sales bills'
                   : hasActuals ? 'Actuals'
                   : hasVars ? `PO + ${varCount} variation${varCount > 1 ? 's' : ''}`
                   : 'As per PO';

        let mxRows = '', mxHidden = '';
        if (hasActuals) {
            // Actuals replace the PO and any variations outright (see
            // resolve_contract), so only they are in force and only they are
            // shown. What they replaced is history — one click away, not on
            // screen competing with the figure that governs.
            mxRows = mRow('Actuals', actBasic, actGst, actTotal, { cls: 'is-force', count: actCount });
            mxHidden = mRow('PO', baseBasic, baseGst, baseTotal, { cls: 'is-old', note: 'superseded' })
                + (hasVars ? mRow('Variations', varBasic, varGst, varTotal,
                                  { cls: 'is-old', delta: true, count: varCount, note: 'superseded' }) : '');
        } else if (hasVars) {
            // Both books are in force here — the PO plus the changes agreed
            // against it — so the breakdown stays on screen and earns the
            // total line under it. Everywhere else that line would just
            // restate the single row above it.
            mxRows = mRow('PO', baseBasic, baseGst, baseTotal)
                + mRow('Variations', varBasic, varGst, varTotal, { delta: true, count: varCount })
                + mRow('Total', baseBasic + varBasic, baseGst + varGst, contract, { cls: 'is-force is-total' });
        } else if (fromPo) {
            mxRows = mRow('PO', baseBasic, baseGst, baseTotal, { cls: 'is-force' });
        } else if (contract > 0) {
            // No PO, so no basic/GST split on record — only what we invoiced.
            mxRows = mRow('Billed', null, null, contract, { cls: 'is-force' });
        }

        // Offered only when there is something behind it. On a plain PO, or on
        // variations whose breakdown is already on screen, the button would
        // open onto what the reader is already looking at.
        const detailsBtn = mxHidden ? `
                        <button type="button" class="proj-book-toggle" data-glance-toggle="books"
                                aria-expanded="false" title="Show the PO and variations these actuals replaced">
                            <span>View details</span>
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                        </button>` : '';
        const contractBlock = mxRows ? `
                    <div class="proj-block-head">
                        <span class="proj-block-t">Contract</span>
                        <span class="proj-block-badge">${kind}</span>
                        ${deltaChip}
                        ${detailsBtn}
                    </div>
                    ${mTable(mxRows, mxHidden)}` : '';

        // ── Received ──
        // No heading: the rows name themselves, and "RECEIVED" over a row
        // called "Received" was the same word twice. Money in reads green,
        // money passed straight out reads red, and the net closes the block.
        const rRow = (label, value, cls = '', fmt = moneyHtml) => `
                        <div class="proj-recv-row ${cls}"><dt>${label}</dt><dd>${fmt(value)}</dd></div>`;
        // Deep-links to the Ledger → Third-party payments tab, but only where
        // something is listening for it (the registry modal). The summary page
        // renders the same block with no tabs to jump to.
        const tpLink = (text, title) => ((opts && opts.linkThirdParty)
            ? `<button type="button" class="proj-tp-link" data-glance-goto="third-party"
                    title="${title}">${text}</button>`
            : text);
        let recvRows = rRow('Received', rec, 'is-in');
        if (tpIn > 0.5) {
            recvRows += rRow(tpLink('Received from third parties', 'Show every third-party receipt'),
                             tpIn, 'is-in', deltaHtml);
        }
        if (tpOut > 0.5) {
            recvRows += rRow(tpLink('Paid to third parties', 'Show every third-party payment'),
                             -tpOut, 'is-out', deltaHtml);
        }
        // Only where the ledger actually moved the figure: with no third-party
        // leg the net is the receipt above it, and a row restating its
        // neighbour is exactly the noise this panel is shedding.
        if (hasThirdParty) recvRows += rRow('Net for VISMA', netRec, 'is-net');

        const ladder = `
            <div class="proj-ov-panel">
                <div class="proj-ov-head"><h4 class="proj-ov-title">Project value</h4></div>
                <div class="proj-ov-body">
                    ${contractBlock}
                    <dl class="proj-recv">${recvRows}
                    </dl>
                </div>
            </div>`;

        // ── GST position ──
        // The answer first: what we remit, or what we carry forward. The two
        // books it comes out of tabulate underneath in the same matrix the
        // contract uses — six rows of purchase/sales components standing
        // between the reader and the one number they opened this for was the
        // whole problem.
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
                <div class="proj-gst-lead ${isCredit ? 'is-credit' : ''}">
                    <span class="proj-gst-lead-k">${isCredit ? 'GST credit' : 'GST extra'}</span>
                    <span class="proj-gst-lead-v">${moneyHtml(Math.abs(g.extra))}</span>
                    <span class="proj-cap">output ${formatINRCompact(g.sales_gst)} − input ${formatINRCompact(g.purchase_gst)}</span>
                </div>
                ${mTable(
                    mRow('Purchase', g.purchase_basic, g.purchase_gst, g.purchase_total, { note: 'bills in' })
                    + mRow('Sales', g.sales_basic, g.sales_gst, g.sales_total, { note: 'bills out' }))}
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
                          value="${l.amount ? formatRupees(l.amount) : ''}" placeholder="${formatRupees(0)}"
                          data-overhead-input data-raw="${l.amount || 0}"
                          aria-label="Overhead amount in rupees"
                          title="Costs no bill or bank row covers. Counts toward the total and profit.">`
                : formatRupees(l.amount);
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
                        <span>Total expenses</span><span>${formatRupees(total)}</span>
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

    // "Show what this replaced": the PO and variation rows an actuals entry
    // superseded. Bound on the document for the same reason as the chevron
    // above — the panel is repainted wholesale on every render.
    document.addEventListener('click', function (e) {
        const btn = e.target.closest && e.target.closest('[data-glance-toggle="books"]');
        if (!btn) return;
        const panel = btn.closest('.proj-ov-panel');
        const rows = panel && panel.querySelector('[data-glance-panel="books"]');
        if (!rows) return;
        const open = rows.hasAttribute('hidden');
        if (open) rows.removeAttribute('hidden'); else rows.setAttribute('hidden', '');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        btn.classList.toggle('is-open', open);
        const label = btn.querySelector('span');
        if (label) label.textContent = open ? 'Hide details' : 'View details';
    });

    return {
        render: render,
        escapeHtml: escapeHtml,
        formatINR: formatINR,
        formatSignedINR: formatSignedINR,
        formatINRCompact: formatINRCompact,
        formatDeltaINR: formatDeltaINR,
        formatRupees: formatRupees,
    };
})();
