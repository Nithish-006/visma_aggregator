(() => {
    'use strict';

    const listEl = document.getElementById('projects-list');
    const newBtn = document.getElementById('new-project-btn');
    const newModal = document.getElementById('new-project-modal');
    const newForm = document.getElementById('new-project-form');
    const idInput = document.getElementById('new-project-id');
    const stemInput = document.getElementById('new-project-stem');
    const poInput = document.getElementById('new-project-po');
    const submitBtn = document.getElementById('new-project-submit');
    const collisionEl = document.getElementById('new-project-collision');
    const errorEl = document.getElementById('new-project-error');

    const detailModal = document.getElementById('project-detail-modal');
    const detailTitle = document.getElementById('detail-title');
    const detailPoFilename = document.getElementById('detail-po-filename');
    const detailPoLink = document.getElementById('detail-po-link');
    const detailUploadBlock = document.getElementById('detail-po-upload');
    const detailUploadLabel = document.getElementById('detail-upload-label');
    const detailUploadForm = document.getElementById('detail-upload-form');
    const detailPoInput = document.getElementById('detail-po-input');
    const detailUploadError = document.getElementById('detail-upload-error');

    // PO gist / edit / reprocess
    const gistEl = document.getElementById('detail-po-gist');
    const poActions = document.getElementById('detail-po-actions');
    const reprocessBtn = document.getElementById('detail-po-reprocess');
    const editBtn = document.getElementById('detail-po-edit-btn');
    const editForm = document.getElementById('detail-po-edit-form');
    const editCancel = document.getElementById('detail-po-edit-cancel');
    const editError = document.getElementById('detail-po-edit-error');

    const toast = document.getElementById('proj-toast');

    const detailOverview = document.getElementById('detail-overview');
    const detailPoBlock = document.getElementById('detail-po-block');

    // Insight tabs (PO / payments / expenses / bills / labour)
    const tabsBar = document.getElementById('detail-tabs');
    const tabButtons = () => Array.from(tabsBar.querySelectorAll('.proj-tab'));
    const tabPanels = () => Array.from(detailModal.querySelectorAll('[data-tab-panel]'));
    const payModesEl = document.getElementById('detail-pay-modes');
    const expensesEl = document.getElementById('detail-expenses');
    const purchaseBillsEl = document.getElementById('detail-purchase-bills');
    const salesBillsEl = document.getElementById('detail-sales-bills');
    const labourEl = document.getElementById('detail-labour');

    // Edit panel (type / reprocess / PO values, behind the header Edit button)
    const editToggleBtn = document.getElementById('detail-edit-toggle');
    const editToggleLabel = document.getElementById('detail-edit-toggle-label');
    const editPanel = document.getElementById('detail-edit-panel');
    const poAdmin = document.getElementById('detail-po-admin');

    // Cash client payments
    const cashTotalEl = document.getElementById('detail-cash-total');
    const cashForm = document.getElementById('detail-cash-form');
    const cashToggleBtn = document.getElementById('detail-cash-toggle');
    const cashToggleLabel = document.getElementById('detail-cash-toggle-label');
    const cashAmount = document.getElementById('detail-cash-amount');
    const cashDate = document.getElementById('detail-cash-date');
    const cashNote = document.getElementById('detail-cash-note');
    const cashAddBtn = document.getElementById('detail-cash-add');
    const cashError = document.getElementById('detail-cash-error');
    const cashListEl = document.getElementById('detail-cash-list');

    const detailTypeStatus = document.getElementById('detail-type-status');
    const detailTypeRadios = () => Array.from(detailModal.querySelectorAll('input[name="detail_project_type"]'));

    const detailStatusStatus = document.getElementById('detail-status-status');
    const detailInactiveToggle = document.getElementById('detail-is-inactive');

    // The three registry buckets, in display order. A row's bucket comes from
    // project_type, falling back to the legacy is_project boolean.
    const TYPE_SECTIONS = [
        { key: 'project', title: 'Projects', sub: 'Valid client / site projects', variant: 'projects' },
        { key: 'design', title: 'Designs', sub: 'Design-only work', variant: 'designs' },
        { key: 'other', title: 'Others', sub: 'Internal heads (office, factory, KVB, sridhar…)', variant: 'others' },
    ];
    const projectTypeOf = (p) => p.project_type || (p.is_project === false ? 'other' : 'project');
    const isClosed = (p) => p.is_inactive === true || p.is_inactive === 1;

    let projects = [];
    let activeProjectId = null;
    let insights = null;        // /insights payload for the open project
    let cashPayments = [];      // live cash ledger for the open project

    // ── Toast ──────────────────────────────────────────
    let toastTimer = null;
    function showToast(msg, kind = 'success') {
        toast.textContent = msg;
        toast.classList.remove('hidden', 'error');
        if (kind === 'error') toast.classList.add('error');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.add('hidden'), 2800);
    }

    // ── Render ─────────────────────────────────────────
    // One labelled stat in a card's finance strip. When `fullValue` is given,
    // the tooltip is enriched with the full-precision amount (the cell itself
    // shows the compact form), so callers don't repeat `: ${formatINR(x)}`.
    function financeCell(label, value, cls, title, fullValue) {
        const tip = fullValue != null
            ? (title ? `${title}: ${formatINR(fullValue)}` : formatINR(fullValue))
            : title;
        return `<div class="proj-fin-cell"${tip ? ` title="${escapeHtml(tip)}"` : ''}>
            <span class="proj-fin-k">${label}</span>
            <span class="proj-fin-v ${cls}">${value}</span>
        </div>`;
    }

    function buildCard(p) {
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'project-card' + (isClosed(p) ? ' is-closed' : '');
        card.dataset.id = p.id;
        const created = p.created_at ? new Date(p.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }) : '';
        const closedBadge = isClosed(p) ? `<span class="project-po-badge closed">Closed</span>` : '';
        const badge = p.has_po
            ? `<span class="project-po-badge has-po">PO uploaded</span>`
            : `<span class="project-po-badge no-po">No PO yet</span>`;
        const poValue = Number(p.po_total_value) || 0;
        const received = Number(p.received_total) || 0;
        const hasPoValue = p.po_total_value != null && poValue > 0;

        // A clean, aligned finance strip — one labelled stat per column —
        // instead of cramped abbreviated pills that wrapped onto each other.
        const cells = [];
        if (hasPoValue) {
            cells.push(financeCell('PO Value', formatINRCompact(poValue), '',
                'Total purchase-order value', poValue));
        } else if (p.po_extraction_status === 'failed') {
            cells.push(financeCell('PO Value', 'Pending', 'pending', 'Auto-read failed — open to enter manually'));
        }
        const hasReceived = received > 0;
        if (hasReceived || hasPoValue) {
            cells.push(financeCell('Received', hasReceived ? formatINRCompact(received) : '—',
                hasReceived ? 'received' : 'muted',
                'Client payments received', hasReceived ? received : null));
        }
        if (hasPoValue) {
            const bal = poValue - received;
            const settled = bal <= 0.5;
            cells.push(financeCell('Balance', settled ? 'Settled' : formatINRCompact(bal),
                settled ? 'settled' : 'due',
                settled ? 'Fully received' : 'Balance due (PO value − received)', settled ? null : bal));
        }
        const financeBlock = cells.length ? `<div class="project-finance">${cells.join('')}</div>` : '';

        card.innerHTML = `
            <div class="project-card-main">
                <span class="project-card-id">${p.id}</span>
                <span class="project-card-stem">${escapeHtml(p.stem_name)}</span>
            </div>
            <div class="project-card-foot">
                <div class="project-card-meta">
                    ${closedBadge}
                    ${badge}
                    ${created ? `<span class="project-created">Added ${created}</span>` : ''}
                </div>
                ${financeBlock}
            </div>
        `;
        card.addEventListener('click', () => openDetail(p.id));
        return card;
    }

    function renderSection(title, subtitle, items, variant) {
        const section = document.createElement('section');
        section.className = 'proj-section' + (variant ? ` proj-section--${variant}` : '');
        const head = document.createElement('div');
        head.className = 'proj-section-head';
        head.innerHTML = `
            <h2 class="proj-section-title">${title} <span class="proj-section-count">${items.length}</span></h2>
            ${subtitle ? `<span class="proj-section-sub">${subtitle}</span>` : ''}
        `;
        section.appendChild(head);
        const grid = document.createElement('div');
        grid.className = 'proj-section-grid';
        items.forEach(p => grid.appendChild(buildCard(p)));
        section.appendChild(grid);
        return section;
    }

    function renderList() {
        if (!projects.length) {
            listEl.innerHTML = `<div class="proj-empty">No projects yet. Click <strong>+ New Project</strong> to create the first one.</div>`;
            return;
        }

        listEl.innerHTML = '';
        // Active entries first, grouped by type bucket…
        TYPE_SECTIONS.forEach(sec => {
            const items = projects.filter(p => !isClosed(p) && projectTypeOf(p) === sec.key);
            if (items.length) {
                listEl.appendChild(renderSection(sec.title, sec.sub, items, sec.variant));
            }
        });
        // …then a single "Closed" section at the very bottom for every inactive
        // entry, regardless of its type bucket.
        const closed = projects.filter(isClosed);
        if (closed.length) {
            listEl.appendChild(renderSection(
                'Closed', 'Inactive / completed — kept for reference', closed, 'closed'));
        }
    }

    // Defined once in project_glance.js — the glance and this page format the
    // same figures, so they share one set rather than two that can drift.
    const escapeHtml = ProjectGlance.escapeHtml;
    const formatINR = ProjectGlance.formatINR;
    const formatSignedINR = ProjectGlance.formatSignedINR;
    const formatINRCompact = ProjectGlance.formatINRCompact;
    const formatDeltaINR = ProjectGlance.formatDeltaINR;

    // Render a bank name as a colored badge: Axis in red, KVB in green.
    function bankBadge(bank) {
        const code = String(bank || '').trim().toLowerCase();
        const label = code ? escapeHtml(code.toUpperCase()) : '';
        if (!label) return '';
        const cls = code === 'axis' ? 'bank-axis' : code === 'kvb' ? 'bank-kvb' : '';
        return `<span class="proj-bank-badge ${cls}">${label}</span>`;
    }


    // ── Load ───────────────────────────────────────────
    async function loadProjects() {
        try {
            const res = await fetch('/api/projects', { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            projects = data.projects || [];
            renderList();
        } catch (e) {
            console.error('Failed to load projects', e);
            listEl.innerHTML = `<div class="proj-empty">Failed to load projects. Refresh to retry.</div>`;
        }
    }

    // ── Modals ─────────────────────────────────────────
    function openModal(modal) {
        modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    }
    function closeModal(modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }

    document.querySelectorAll('[data-close]').forEach(el => {
        el.addEventListener('click', () => {
            const id = el.getAttribute('data-close');
            const m = document.getElementById(id);
            if (m) closeModal(m);
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.proj-modal:not(.hidden)').forEach(m => closeModal(m));
        }
    });

    // ── New project flow ───────────────────────────────
    newBtn.addEventListener('click', () => {
        newForm.reset();
        collisionEl.classList.add('hidden');
        collisionEl.textContent = '';
        errorEl.classList.add('hidden');
        errorEl.textContent = '';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save';
        openModal(newModal);
        setTimeout(() => idInput.focus(), 60);
    });

    // Live collision check against cached project list
    function checkCollision() {
        collisionEl.classList.add('hidden');
        collisionEl.textContent = '';
        const idVal = idInput.value.trim();
        const stemVal = stemInput.value.trim().toLowerCase();
        if (!idVal) return;
        const idNum = parseInt(idVal, 10);
        if (Number.isNaN(idNum)) return;

        const idClash = projects.find(p => p.id === idNum);
        if (idClash) {
            collisionEl.textContent = `ID ${idNum} is already used by "${idClash.display}". Pick a different id.`;
            collisionEl.classList.remove('hidden');
            return;
        }
        if (stemVal) {
            const stemClash = projects.find(p => p.stem_name.toLowerCase() === stemVal);
            if (stemClash) {
                collisionEl.textContent = `A project named "${stemClash.stem_name}" already exists with id ${stemClash.id}.`;
                collisionEl.classList.remove('hidden');
            }
        }
    }
    idInput.addEventListener('input', checkCollision);
    stemInput.addEventListener('input', checkCollision);

    newForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.classList.add('hidden');
        errorEl.textContent = '';

        const idVal = idInput.value.trim();
        const stemVal = stemInput.value.trim();
        if (!idVal || !stemVal) {
            errorEl.textContent = 'Both ID and project name are required.';
            errorEl.classList.remove('hidden');
            return;
        }
        const idNum = parseInt(idVal, 10);
        if (Number.isNaN(idNum) || idNum <= 0) {
            errorEl.textContent = 'ID must be a positive integer.';
            errorEl.classList.remove('hidden');
            return;
        }

        const typeEl = newForm.querySelector('input[name="project_type"]:checked');
        if (!typeEl) {
            errorEl.textContent = 'Please choose a type — Project, Design or Other.';
            errorEl.classList.remove('hidden');
            return;
        }

        const fd = new FormData();
        fd.append('id', String(idNum));
        fd.append('stem_name', stemVal);
        fd.append('project_type', typeEl.value);
        if (poInput.files && poInput.files[0]) fd.append('po_file', poInput.files[0]);

        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving…';
        try {
            const res = await fetch('/api/projects', {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                const msg = data.message || data.error || `Failed (HTTP ${res.status})`;
                errorEl.textContent = msg;
                errorEl.classList.remove('hidden');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Save';
                return;
            }
            closeModal(newModal);
            showToast(`Project ${idNum} - ${stemVal} created.`);
            await loadProjects();
        } catch (err) {
            errorEl.textContent = `Network error: ${err.message}`;
            errorEl.classList.remove('hidden');
            submitBtn.disabled = false;
            submitBtn.textContent = 'Save';
        }
    });

    // ── Project detail / PO upload flow ────────────────
    function openDetail(projectId) {
        const p = projects.find(x => x.id === projectId);
        if (!p) return;
        activeProjectId = projectId;
        detailTitle.textContent = `${p.id} − ${p.stem_name}`;
        // Forward link to the full breakdown on the Project Summary page. The
        // canonical "<id> - NAME" tag is what that page matches on (by id).
        const breakdownLink = document.getElementById('detail-breakdown-link');
        if (breakdownLink) {
            breakdownLink.href = '/project-summary?project=' +
                encodeURIComponent(`${p.id} - ${p.stem_name}`);
        }
        // Fresh insight state: PO tab first, counts cleared, panels in loading state.
        insights = null;
        cashPayments = [];
        switchTab('overview');
        switchSubTab('bills', 'purchase');
        switchSubTab('ledger', 'payments');
        ['bills', 'ledger'].forEach(k => setTabCount(k, null));
        ['purchase', 'sales', 'payments', 'expenses', 'labour'].forEach(k => setSubTabCount(k, null));
        payModesEl.innerHTML = '';
        const loading = `<p class="proj-tab-loading">Loading…</p>`;
        expensesEl.innerHTML = loading;
        purchaseBillsEl.innerHTML = loading;
        salesBillsEl.innerHTML = loading;
        labourEl.innerHTML = loading;
        renderOverview(p);
        // Start in read-only view; editing is opt-in via the header Edit button.
        // (Overhead is the exception — it's edited in place in the Expenses
        // list, so it isn't gated behind Edit mode.)
        setEditMode(false);
        // Cash client payments ledger — form is collapsed until "+ Add".
        setCashFormOpen(false);
        cashForm.reset();
        cashError.classList.add('hidden');
        cashError.textContent = '';
        loadCashPayments(p.id);
        loadInsights(p.id);
        // Reflect current type in the toggle
        const wantVal = projectTypeOf(p);
        detailTypeRadios().forEach(r => { r.checked = (r.value === wantVal); });
        detailTypeStatus.textContent = '';
        detailTypeStatus.classList.remove('error');
        // Reflect closed/active status
        detailInactiveToggle.checked = isClosed(p);
        detailStatusStatus.textContent = '';
        detailStatusStatus.classList.remove('error');
        detailUploadError.classList.add('hidden');
        detailUploadError.textContent = '';
        detailUploadForm.reset();

        if (p.has_po) {
            detailPoBlock.classList.remove('hidden');
            detailPoBlock.open = false; // reference detail — folded until asked for
            detailUploadBlock.classList.add('hidden');
            detailPoFilename.textContent = p.po_filename;
            detailPoLink.href = `/api/projects/${p.id}/po`;
            poAdmin.classList.remove('hidden');
            exitPoEditForm();
            loadPoGist(p.id);
        } else {
            detailPoBlock.classList.add('hidden');
            detailUploadBlock.classList.remove('hidden');
            poAdmin.classList.add('hidden');
            detailUploadLabel.textContent = `Upload PO document for "${p.stem_name}"`;
        }
        openModal(detailModal);
    }

    // ── Edit mode (header Edit button reveals the edit panel) ──
    function setEditMode(on) {
        editPanel.classList.toggle('hidden', !on);
        editToggleBtn.classList.toggle('active', on);
        editToggleLabel.textContent = on ? 'Done' : 'Edit';
        if (!on) exitPoEditForm(); // collapse any open PO-values form on exit
    }
    editToggleBtn.addEventListener('click', () => {
        const turningOn = editPanel.classList.contains('hidden');
        if (turningOn) switchTab('overview'); // the edit panel lives on the Overview tab
        setEditMode(turningOn);
    });


    // ── Insight tabs ───────────────────────────────────
    function switchTab(key) {
        tabButtons().forEach(b => b.classList.toggle('active', b.dataset.tab === key));
        tabPanels().forEach(pn => pn.classList.toggle('hidden', pn.dataset.tabPanel !== key));
    }
    // Nothing recorded yet? Surface the cash entry form so the input is visible
    // without hunting for the "+ Add cash" button. Driven from the click
    // handlers rather than switchSubTab: openDetail calls switchSubTab to reset
    // the panels and then resets the form itself, so an auto-open in there
    // would be immediately undone.
    function maybeOpenCashForm() {
        if (cashForm.classList.contains('hidden')
            && !cashPayments.length
            && (!insights || !insights.payments.bank.length)) {
            setCashFormOpen(true);
        }
    }

    tabsBar.addEventListener('click', (e) => {
        const btn = e.target.closest('.proj-tab');
        if (!btn) return;
        switchTab(btn.dataset.tab);
        // The Ledger tab opens on its payments sub-panel, so it needs the same
        // nudge the payments sub-tab gets.
        if (btn.dataset.tab === 'ledger'
            && !subTabScope('ledger').querySelector('[data-subtab-panel="payments"]').classList.contains('hidden')) {
            maybeOpenCashForm();
        }
    });

    // Sub-tabs within Bills and Ledger. Scoped to their own panel so the two
    // groups can both have a "payments"/"purchase" key without colliding.
    function subTabScope(tabKey) {
        return detailModal.querySelector(`[data-tab-panel="${tabKey}"]`);
    }
    function switchSubTab(tabKey, subKey) {
        const scope = subTabScope(tabKey);
        if (!scope) return;
        scope.querySelectorAll('.proj-subtab').forEach(b =>
            b.classList.toggle('active', b.dataset.subtab === subKey));
        scope.querySelectorAll('[data-subtab-panel]').forEach(pn =>
            pn.classList.toggle('hidden', pn.dataset.subtabPanel !== subKey));
    }
    detailModal.addEventListener('click', (e) => {
        const btn = e.target.closest('.proj-subtab');
        if (!btn) return;
        const panel = btn.closest('[data-tab-panel]');
        if (!panel) return;
        switchSubTab(panel.dataset.tabPanel, btn.dataset.subtab);
        if (panel.dataset.tabPanel === 'ledger' && btn.dataset.subtab === 'payments') {
            maybeOpenCashForm();
        }
    });

    function setTabCount(key, value) {
        const el = tabsBar.querySelector(`[data-tab-count="${key}"]`);
        if (!el) return;
        if (!value) {
            el.classList.add('hidden');
            el.textContent = '';
        } else {
            el.textContent = value;
            el.classList.remove('hidden');
        }
    }

    function setSubTabCount(key, value) {
        detailModal.querySelectorAll(`[data-subtab-count="${key}"]`).forEach(el => {
            el.textContent = value ? ` ${value}` : '';
        });
    }

    function fmtDate(s) {
        if (!s) return '—';
        const d = new Date(s);
        return Number.isNaN(d.getTime())
            ? String(s)
            : d.toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
    }

    // Revert the inline PO-values form back to the read-only gist.
    function exitPoEditForm() {
        editForm.classList.add('hidden');
        editError.classList.add('hidden');
        poActions.classList.remove('hidden');
        gistEl.classList.remove('hidden');
    }

    // ── Cash form reveal (+ Add) ───────────────────────
    function setCashFormOpen(on) {
        cashForm.classList.toggle('hidden', !on);
        cashToggleBtn.classList.toggle('active', on);
        cashToggleLabel.textContent = on ? 'Close' : 'Add cash';
        if (on) setTimeout(() => {
            // The modal body scrolls — on short screens the freshly revealed
            // form can sit below the fold, so bring it into view first.
            cashForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            cashAmount.focus({ preventScroll: true });
        }, 60);
    }
    cashToggleBtn.addEventListener('click', () => {
        setCashFormOpen(cashForm.classList.contains('hidden'));
    });

    // ── Project at a glance ────────────────────────────
    // Rendered by the shared module so this pop-up and the project summary page
    // can't drift apart (project_glance.js). Called twice per open — once from
    // the cached registry row for an instant paint, then again once /insights
    // lands with the full picture.
    function renderOverview(p) {
        const html = ProjectGlance.render({
            project: p,
            insights: insights,
            // The overhead field is only editable where its handlers are wired,
            // which is here — see saveOverhead below.
            editableOverhead: true,
        });
        if (html === null) {
            detailOverview.classList.add('hidden');
            detailOverview.innerHTML = '';
            return;
        }
        detailOverview.innerHTML = html;
        detailOverview.classList.remove('hidden');
    }

    // ── Cash client payments ───────────────────────────
    function applyPaymentSummary(summary) {
        // Push fresh totals into the cached project so the card + payments view
        // reflect the change without a full reload.
        // Insights first: renderOverview reads its received/receivable figures
        // from insights.summary when it's loaded, so it has to see the new
        // totals before the repaint below.
        if (insights && insights.summary) {
            insights.summary.received_cash = summary.received_cash;
            insights.summary.received_total = summary.received_total;
            insights.summary.receivable = insights.summary.value.total - summary.received_total;
            insights.payments.cash_total = summary.received_cash;
            insights.payments.total = summary.received_total;
        }
        const cached = projects.find(x => x.id === activeProjectId);
        if (cached) {
            cached.received_bank = summary.received_bank;
            cached.received_cash = summary.received_cash;
            cached.received_total = summary.received_total;
            renderOverview(cached);
            renderList(); // keep the registry card's "Received" in sync
        }
        renderCashList(summary.payments || []);
    }

    function renderCashList(payments) {
        cashPayments = payments || [];
        renderPaymentHistory();
        renderPayModes();
        if (insights) {
            const payCount = insights.payments.bank.length + cashPayments.length;
            setSubTabCount('payments', payCount);
            setTabCount('ledger', payCount + insights.expenses.count);
        }
    }

    // Bank (KVB) total / cash total / total received chips at the top of the
    // Client Payments tab. Cash figures come from the live ledger so an
    // add/delete updates them instantly.
    function renderPayModes() {
        if (!insights) { payModesEl.innerHTML = ''; return; }
        const bank = insights.payments.bank;
        const bankTotal = Number(insights.payments.bank_total) || 0;
        const cashTotal = cashPayments.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        payModesEl.innerHTML = `
            <div class="proj-chip">
                <span class="proj-chip-k">Bank (KVB)</span>
                <span class="proj-chip-v">${formatINR(bankTotal)}</span>
                <span class="proj-chip-sub">${bank.length} credit${bank.length === 1 ? '' : 's'}</span>
            </div>
            <div class="proj-chip">
                <span class="proj-chip-k">Cash</span>
                <span class="proj-chip-v">${formatINR(cashTotal)}</span>
                <span class="proj-chip-sub">${cashPayments.length} entr${cashPayments.length === 1 ? 'y' : 'ies'}</span>
            </div>
            <div class="proj-chip accent">
                <span class="proj-chip-k">Total received</span>
                <span class="proj-chip-v">${formatINR(bankTotal + cashTotal)}</span>
            </div>`;
    }

    // One chronological history mixing KVB statement credits (read-only, with
    // their statement context) and manual cash entries (deletable).
    function renderPaymentHistory() {
        const bank = (insights && insights.payments && insights.payments.bank) || [];
        const cashTotal = cashPayments.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        cashTotalEl.textContent = cashPayments.length ? `${formatINR(cashTotal)} in cash` : '';

        const entries = [];
        bank.forEach(b => entries.push({
            mode: 'bank',
            date: b.date || '',
            amount: Number(b.amount) || 0,
            context: (b.vendor && b.vendor !== 'Unknown') ? b.vendor : (b.description || ''),
            title: b.description || '',
        }));
        cashPayments.forEach(c => entries.push({
            mode: 'cash',
            id: c.id,
            date: c.payment_date || (c.created_at ? String(c.created_at).slice(0, 10) : ''),
            amount: Number(c.amount) || 0,
            context: c.note || '',
            title: c.note || '',
        }));

        if (!entries.length) {
            cashListEl.innerHTML = insights
                ? `<p class="proj-cash-empty">No client payments recorded for this project yet.</p>`
                : `<p class="proj-cash-empty">Loading payments…</p>`;
            return;
        }

        entries.sort((a, b) => String(b.date).localeCompare(String(a.date)));
        cashListEl.innerHTML = entries.map(en => {
            const when = en.date ? fmtDate(en.date) : '';
            const badge = en.mode === 'bank'
                ? `<span class="proj-mode-badge bank" title="From the KVB bank statement">Bank</span>`
                : `<span class="proj-mode-badge cash" title="Cash handed over — recorded manually">Cash</span>`;
            const del = en.mode === 'cash'
                ? `<button type="button" class="proj-cash-del" data-id="${en.id}" title="Remove this payment" aria-label="Remove this payment">×</button>`
                : '';
            return `
                <div class="proj-cash-item">
                    <div class="proj-cash-item-main">
                        <span class="proj-cash-item-amt">${formatINR(en.amount)} ${badge}</span>
                        ${en.context ? `<span class="proj-cash-item-note" title="${escapeHtml(en.title)}">${escapeHtml(en.context)}</span>` : ''}
                    </div>
                    <div class="proj-cash-item-side">
                        ${when ? `<span class="proj-cash-item-date">${when}</span>` : ''}
                        ${del}
                    </div>
                </div>`;
        }).join('');
    }

    function loadCashPayments(projectId) {
        cashError.classList.add('hidden');
        cashError.textContent = '';
        cashListEl.innerHTML = `<p class="proj-cash-empty">Loading…</p>`;
        cashTotalEl.textContent = '';
        fetch(`/api/projects/${projectId}/cash-payments`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (projectId !== activeProjectId) return; // modal changed
                renderCashList(data.payments || []);
            })
            .catch(() => {
                if (projectId !== activeProjectId) return;
                cashListEl.innerHTML = `<p class="proj-cash-empty">Couldn't load cash payments.</p>`;
            });
    }

    cashForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        cashError.classList.add('hidden');
        cashError.textContent = '';

        const amount = parseFloat(cashAmount.value);
        if (Number.isNaN(amount) || amount <= 0) {
            cashError.textContent = 'Enter an amount greater than zero.';
            cashError.classList.remove('hidden');
            return;
        }
        const payload = {
            amount,
            payment_date: cashDate.value || null,
            note: cashNote.value.trim() || null,
        };
        cashAddBtn.disabled = true;
        cashAddBtn.textContent = 'Adding…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/cash-payments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                cashError.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                cashError.classList.remove('hidden');
                return;
            }
            cashForm.reset();
            setCashFormOpen(false);
            applyPaymentSummary(data);
            showToast(`Cash payment of ${formatINR(amount)} added.`);
        } catch (err) {
            cashError.textContent = `Network error: ${err.message}`;
            cashError.classList.remove('hidden');
        } finally {
            cashAddBtn.disabled = false;
            cashAddBtn.textContent = 'Add';
        }
    });

    cashListEl.addEventListener('click', async (e) => {
        const btn = e.target.closest('.proj-cash-del');
        if (!btn || !activeProjectId) return;
        const id = btn.dataset.id;
        if (!id) return;
        if (!confirm('Remove this cash payment?')) return;
        btn.disabled = true;
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/cash-payments/${id}`, {
                method: 'DELETE',
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                showToast(data.message || data.error || 'Could not remove payment.', 'error');
                btn.disabled = false;
                return;
            }
            applyPaymentSummary(data);
            showToast('Cash payment removed.');
        } catch (err) {
            showToast(`Network error: ${err.message}`, 'error');
            btn.disabled = false;
        }
    });

    // ── Project insights (overview / bills / ledger tabs) ──
    async function loadInsights(projectId) {
        try {
            const res = await fetch(`/api/projects/${projectId}/insights`, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (projectId !== activeProjectId) return; // modal changed
            insights = data;
            // If the cash ledger fetch hasn't landed yet, seed it from insights
            // so the merged history doesn't briefly miss the cash rows.
            if (!cashPayments.length && data.payments.cash.length) {
                cashPayments = data.payments.cash;
            }
            // Repaint the glance now that the real numbers (profit, GST, costs)
            // are in — the first paint only had the cached PO/received figures.
            const p = projects.find(x => x.id === projectId);
            if (p) renderOverview(p);
            renderPayModes();
            renderPaymentHistory();
            renderExpensesTab();
            renderBillsTab('purchase');
            renderBillsTab('sales');
            renderLabourTab();
            const payCount = data.payments.bank.length + cashPayments.length;
            const labourCount = data.labour && data.labour.monthly ? data.labour.monthly.length : 0;
            setTabCount('bills', data.purchase_bills.count + data.sales_bills.count);
            setTabCount('ledger', payCount + data.expenses.count);
            setSubTabCount('purchase', data.purchase_bills.count);
            setSubTabCount('sales', data.sales_bills.count);
            setSubTabCount('payments', payCount);
            setSubTabCount('expenses', data.expenses.count);
            setSubTabCount('labour', labourCount);
        } catch (e) {
            console.error('Failed to load project insights', e);
            if (projectId !== activeProjectId) return;
            const fail = `<p class="proj-tab-empty">Couldn't load this section. Close and reopen the project to retry.</p>`;
            expensesEl.innerHTML = fail;
            purchaseBillsEl.innerHTML = fail;
            salesBillsEl.innerHTML = fail;
            labourEl.innerHTML = fail;
            payModesEl.innerHTML = '';
            renderPaymentHistory();
            // The glance can't be trusted without insights — say so rather than
            // leaving the half-painted PO-only numbers looking authoritative.
            const costsFail = detailOverview.querySelector('.proj-ov-costs');
            if (costsFail) {
                costsFail.innerHTML = fail;
            }
        }
    }

    function renderExpensesTab() {
        const ex = insights.expenses;
        if (!ex || !ex.count) {
            expensesEl.innerHTML = `<p class="proj-tab-empty">No expenses tagged to this project in the bank statements yet.</p>`;
            return;
        }
        const chips = `
            <div class="proj-pay-modes">
                <div class="proj-chip accent">
                    <span class="proj-chip-k">Total spent</span>
                    <span class="proj-chip-v">${formatINR(ex.total)}</span>
                    <span class="proj-chip-sub">${ex.count} transaction${ex.count === 1 ? '' : 's'}</span>
                </div>
                ${ex.by_category.slice(0, 3).map(c => `
                <div class="proj-chip">
                    <span class="proj-chip-k">${escapeHtml(c.category)}</span>
                    <span class="proj-chip-v">${formatINRCompact(c.amount)}</span>
                    <span class="proj-chip-sub">${c.count}×</span>
                </div>`).join('')}
            </div>`;
        const rows = ex.transactions.map(t => `
            <tr>
                <td class="proj-li-unit">${fmtDate(t.date)}</td>
                <td class="proj-li-desc" title="${escapeHtml(t.description)}">${escapeHtml((t.vendor && t.vendor !== 'Unknown') ? t.vendor : t.description)}</td>
                <td><span class="proj-cat-chip">${escapeHtml(t.category)}</span></td>
                <td class="proj-li-unit">${bankBadge(t.bank)}</td>
                <td class="proj-li-num">${formatINR(t.amount)}</td>
            </tr>`).join('');
        const truncNote = ex.count > ex.transactions.length
            ? `<p class="proj-tab-note">Showing the latest ${ex.transactions.length} of ${ex.count} transactions.</p>` : '';
        expensesEl.innerHTML = `${chips}
            <div class="proj-li-scroll proj-li-scroll--tall">
                <table class="proj-li-table">
                    <thead><tr><th>Date</th><th>Paid to</th><th>Category</th><th>Bank</th><th class="proj-li-num">Amount</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>${truncNote}`;
    }

    function renderBillsTab(kind) {
        const isPurchase = kind === 'purchase';
        const el = isPurchase ? purchaseBillsEl : salesBillsEl;
        const data = isPurchase ? insights.purchase_bills : insights.sales_bills;
        if (!data || !data.count) {
            el.innerHTML = `<p class="proj-tab-empty">No ${isPurchase ? 'purchase' : 'sales'} bills found for this project.</p>`;
            return;
        }
        const chips = `
            <div class="proj-pay-modes">
                <div class="proj-chip accent">
                    <span class="proj-chip-k">Total billed</span>
                    <span class="proj-chip-v">${formatINR(data.total_amount)}</span>
                    <span class="proj-chip-sub">${data.count} bill${data.count === 1 ? '' : 's'}</span>
                </div>
                <div class="proj-chip">
                    <span class="proj-chip-k">GST included</span>
                    <span class="proj-chip-v">${formatINR(data.total_gst)}</span>
                </div>
            </div>`;
        const rows = data.bills.map(b => `
            <tr>
                <td class="proj-li-unit">${b.invoice_date ? escapeHtml(b.invoice_date) : '—'}</td>
                <td class="proj-li-unit">${b.invoice_number ? escapeHtml(b.invoice_number) : '—'}</td>
                <td class="proj-li-desc">${escapeHtml((isPurchase ? b.vendor_name : b.buyer_name) || '—')}</td>
                <td class="proj-li-num">${b.line_item_count != null ? b.line_item_count : '—'}</td>
                <td class="proj-li-num">${formatINR(b.total_amount)}</td>
            </tr>`).join('');
        el.innerHTML = `${chips}
            <div class="proj-li-scroll proj-li-scroll--tall">
                <table class="proj-li-table">
                    <thead><tr><th>Date</th><th>Invoice #</th><th>${isPurchase ? 'Vendor' : 'Buyer'}</th><th class="proj-li-num">Items</th><th class="proj-li-num">Amount</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>`;
    }

    function renderLabourTab() {
        const lab = insights.labour;
        if (!lab || lab.available === false) {
            labourEl.innerHTML = `<p class="proj-tab-empty">Couldn't reach the attendance app database right now — labour charges are unavailable. Try again later.</p>`;
            return;
        }
        if (!lab.monthly || !lab.monthly.length) {
            labourEl.innerHTML = `<p class="proj-tab-empty">No attendance recorded against this project yet.</p>`;
            return;
        }
        const chips = `
            <div class="proj-pay-modes">
                <div class="proj-chip accent">
                    <span class="proj-chip-k">Labour charges</span>
                    <span class="proj-chip-v">${formatINR(lab.total_cost)}</span>
                    <span class="proj-chip-sub">from the attendance app</span>
                </div>
                <div class="proj-chip">
                    <span class="proj-chip-k">Man-days</span>
                    <span class="proj-chip-v">${Number(lab.total_days).toLocaleString('en-IN')}</span>
                </div>
                <div class="proj-chip">
                    <span class="proj-chip-k">OT hours</span>
                    <span class="proj-chip-v">${Number(lab.total_ot_hours).toLocaleString('en-IN')}</span>
                </div>
            </div>`;
        const rows = lab.monthly.map(m => `
            <tr>
                <td>${escapeHtml(m.label)}</td>
                <td class="proj-li-num">${Number(m.days).toLocaleString('en-IN')}</td>
                <td class="proj-li-num">${Number(m.ot_hours).toLocaleString('en-IN', { maximumFractionDigits: 1 })}</td>
                <td class="proj-li-num">${formatINR(m.cost)}</td>
            </tr>`).join('');
        const namesNote = lab.project_names && lab.project_names.length
            ? `<p class="proj-tab-note">Matched attendance project${lab.project_names.length === 1 ? '' : 's'}: ${lab.project_names.map(escapeHtml).join(', ')}</p>`
            : '';
        labourEl.innerHTML = `${chips}
            <div class="proj-li-scroll proj-li-scroll--tall">
                <table class="proj-li-table">
                    <thead><tr><th>Month</th><th class="proj-li-num">Man-days</th><th class="proj-li-num">OT hours</th><th class="proj-li-num">Cost</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>${namesNote}`;
    }

    // ── Mobile: collapse the modal's line-item tables into stacked cards ──
    // Reads each table's own <thead> and stamps every <td> with data-label so
    // the CSS (max-width:640px) can render LABEL : value rows. A MutationObserver
    // catches tables injected by any tab (expenses / bills / labour / PO items).
    function decorateProjLiTables(root) {
        (root || document).querySelectorAll('.proj-li-table:not([data-mobi])').forEach(table => {
            const heads = Array.from(table.querySelectorAll('thead th'))
                .map(th => th.textContent.trim());
            table.querySelectorAll('tbody tr').forEach(tr => {
                const tds = tr.querySelectorAll('td');
                if (tds.length <= 1) return;
                tds.forEach((td, i) => {
                    if (heads[i]) td.setAttribute('data-label', heads[i]);
                    td.classList.toggle('proj-li-title', i === 0);
                });
            });
            table.setAttribute('data-mobi', '1');
        });
    }
    (function watchProjTables() {
        const modal = document.getElementById('project-detail-modal');
        if (modal && 'MutationObserver' in window) {
            new MutationObserver(() => decorateProjLiTables(modal))
                .observe(modal, { childList: true, subtree: true });
        }
    })();

    let currentPo = null;

    // ── Render the extracted PO gist ───────────────────
    function loadPoGist(projectId) {
        currentPo = null;
        gistEl.innerHTML = `<div class="proj-gist-loading">Loading PO details…</div>`;
        fetch(`/api/projects/${projectId}/po-data`, { credentials: 'same-origin' })
            .then(r => r.json())
            .then(data => {
                if (projectId !== activeProjectId) return; // modal changed
                currentPo = data.po || null;
                renderPoGist(currentPo);
            })
            .catch(() => {
                gistEl.innerHTML = `<div class="proj-gist-empty">Couldn't load PO details.</div>`;
            });
    }

    function renderPoGist(po) {
        if (!po) {
            gistEl.innerHTML = `<div class="proj-gist-empty">Not processed yet. Click <strong>Reprocess</strong> to extract the PO values.</div>`;
            return;
        }
        if (po.extraction_status === 'failed') {
            gistEl.innerHTML = `<div class="proj-gist-failed">
                Couldn't auto-read this PO${po.extraction_error ? ` (${escapeHtml(po.extraction_error)})` : ''}.
                Click <strong>Edit</strong> (top right) to enter the total manually or reprocess the file.
            </div>`;
            return;
        }
        const manualTag = po.extraction_status === 'manual'
            ? `<span class="proj-gist-tag">manually edited</span>` : '';

        gistEl.innerHTML = `
            <div class="proj-gist-header">
                <span class="proj-field-label">Extracted PO gist</span>${manualTag}
            </div>
            <div class="proj-gist-rows" data-gist-rows>${poGistRowsHtml(po)}</div>
            ${renderPoLineItems(po.line_items)}
            ${renderPoVariations(po)}`;
    }

    // Split out from renderPoGist because a variation edit has to refresh these
    // figures without re-rendering the variations table underneath — that table
    // holds the input the user is currently tabbing out of.
    function poGistRowsHtml(po) {
        const rev = po.revised || {
            taxable_value: po.taxable_value, total_tax: po.total_tax, total_value: po.total_value,
        };
        const vt = po.variation_totals || { count: 0, total: 0 };
        // Two decompositions of one headline, each internally consistent:
        // contract = as-per-PO + variations (right under it), and
        // as-per-PO = taxable + tax (down with the document facts).
        // Only worth the extra rows once the contract has actually moved; an
        // unvaried PO shouldn't pay for a feature it isn't using.
        const rows = [[vt.count ? 'Contract value' : 'Total project value',
                       formatINR(rev.total_value), 'headline']];
        if (vt.count) {
            rows.push(['As per PO', formatINR(po.total_value)]);
            rows.push(['Variations', `${formatDeltaINR(vt.total)} <span class="proj-gist-sub">${vt.count} change${vt.count > 1 ? 's' : ''}</span>`]);
        }
        rows.push(
            ['PO number', po.po_number ? escapeHtml(po.po_number) : '—'],
            ['PO date', po.po_date ? escapeHtml(po.po_date) : '—'],
            ['Client', po.client_name ? escapeHtml(po.client_name) : '—'],
            // Baseline, not revised: these sit above the scope line items, which
            // sum to the baseline taxable, and the whole panel is checked
            // against the PDF behind "View PO document". Showing the revised
            // split here made the gist state a taxable value that matched
            // neither the document nor the items directly beneath it.
            ['Taxable value', formatINR(po.taxable_value)],
            ['Total tax', formatINR(po.total_tax)],
            ['Scope items', po.line_item_count != null ? po.line_item_count : '—'],
        );
        if (po.payment_terms) rows.push(['Payment terms', escapeHtml(po.payment_terms)]);
        if (po.amount_in_words) rows.push(['In words', escapeHtml(po.amount_in_words)]);
        return rows.map(([k, v, cls]) => `
            <div class="proj-gist-row ${cls === 'headline' ? 'headline' : ''}">
                <span class="proj-gist-k">${k}</span>
                <span class="proj-gist-v">${v}</span>
            </div>`).join('');
    }

    // ── Core line-item breakdown (description / qty / unit / rate / amount) ──
    function renderPoLineItems(items) {
        if (!Array.isArray(items) || items.length === 0) return '';
        const num = (v) => (v ? formatINR(v) : '—');
        const qty = (v) => {
            if (!v) return '—';
            // trim trailing zeros: 12.00 -> 12, 12.50 -> 12.5
            return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 });
        };
        const body = items.map(it => `
            <tr>
                <td class="proj-li-desc">${it.description ? escapeHtml(it.description) : '—'}</td>
                <td class="proj-li-num">${qty(it.quantity)}</td>
                <td class="proj-li-unit">${it.unit ? escapeHtml(it.unit) : '—'}</td>
                <td class="proj-li-num">${num(it.rate)}</td>
                <td class="proj-li-num">${num(it.amount)}</td>
            </tr>`).join('');
        return `
            <div class="proj-gist-items">
                <div class="proj-field-label">Line items (${items.length})</div>
                <div class="proj-li-scroll">
                    <table class="proj-li-table">
                        <thead>
                            <tr>
                                <th>Description</th><th class="proj-li-num">Qty</th>
                                <th>Unit</th><th class="proj-li-num">Rate</th>
                                <th class="proj-li-num">Amount</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            </div>`;
    }

    // ── PO variations: the contract's agreed changes ───────────────────────
    // Scope moves after signing — extra tonnage agreed, or work that came in
    // under the quote. The extracted PO above is left exactly as the document
    // reads; each change is a row here, and the contract is the two added up.
    // That's what keeps "View PO document" honest: the gist never claims the
    // PDF says something it doesn't.
    //
    // Amounts are computed server-side (helpers/project_finance) and only
    // previewed here, so the figure that lands in the ladder is never a number
    // this file invented.
    const VAR_GST_RATE = 18; // last-resort default; the server sends po.gst_rate
    const varFields = ['description', 'quantity', 'unit', 'rate'];
    let insightsRefreshTimer = null;


    function trimQty(v) {
        if (v === '' || v == null) return '';
        return String(Number(v)); // 20.000 -> 20, -2.500 -> -2.5
    }

    function variationRowHtml(v, draft) {
        const snap = JSON.stringify({
            description: v.description || '', quantity: trimQty(v.quantity || 0),
            unit: v.unit || '', rate: trimQty(v.rate || 0),
        });
        // Unlike the overhead field, qty/rate stay as raw numbers at rest rather
        // than swapping formatted<->raw on focus. Overhead is a lone input
        // inside a read-only tabulation, where a bare 250000 looked broken; this
        // is a grid of inputs, where a value that rewrites itself on every blur
        // is just noise mid-entry.
        const cell = (field, extra, placeholder) => `
            <input class="proj-var-input ${extra}" type="text" data-var-field="${field}"
                   value="${escapeHtml(String(v[field] == null ? '' : v[field]))}"
                   placeholder="${placeholder}" autocomplete="off">`;
        return `
            <tr data-var-id="${draft ? 'new' : v.id}" class="${draft ? 'is-draft' : ''}" data-var-snapshot='${escapeHtml(snap)}'>
                <td>${cell('description', '', 'e.g. Additional structural steel')}</td>
                <td class="proj-li-num"><input class="proj-var-input proj-var-num" type="text"
                        inputmode="decimal" data-var-field="quantity"
                        value="${trimQty(v.quantity || '')}" placeholder="0" autocomplete="off"></td>
                <td>${cell('unit', 'proj-var-unit', 'MT')}</td>
                <td class="proj-li-num"><input class="proj-var-input proj-var-num" type="text"
                        inputmode="decimal" data-var-field="rate"
                        value="${trimQty(v.rate || '')}" placeholder="0" autocomplete="off"></td>
                <td class="proj-li-num" data-var-out="basic">${formatDeltaINR(v.basic_amount || 0)}</td>
                <td class="proj-li-num" data-var-out="tax">${formatDeltaINR(v.tax_amount || 0)}</td>
                <td class="proj-li-num proj-var-total" data-var-out="total">${formatDeltaINR(v.total_amount || 0)}</td>
                <td class="proj-var-actions">${draft
                    ? `<button type="button" class="proj-var-btn is-save" data-var-save title="Add this change">✓</button>
                       <button type="button" class="proj-var-btn" data-var-discard title="Discard">×</button>`
                    : `<button type="button" class="proj-var-btn" data-var-delete title="Remove this change">×</button>`}
                </td>
            </tr>`;
    }

    const VAR_EMPTY_ROW = `<tr class="proj-var-empty-row" data-var-empty>
            <td colspan="8">No changes to the contract yet.</td></tr>`;

    function variationFootHtml(vt) {
        if (!vt || !vt.count) return '';
        // data-label is stamped by hand here: decorateProjLiTables only walks
        // tbody, so on a phone — where this becomes a card like the rows above —
        // these cells would otherwise lose their headings along with the thead.
        return `<tfoot><tr>
                <td colspan="4" class="proj-var-foot-title">Net change</td>
                <td class="proj-li-num" data-label="Basic">${formatDeltaINR(vt.taxable)}</td>
                <td class="proj-li-num" data-label="GST">${formatDeltaINR(vt.tax)}</td>
                <td class="proj-li-num proj-var-total" data-label="Total">${formatDeltaINR(vt.total)}</td>
                <td class="proj-var-foot-pad"></td>
            </tr></tfoot>`;
    }

    function renderPoVariations(po) {
        const list = (po && po.variations) || [];
        const vt = (po && po.variation_totals) || { count: 0, taxable: 0, tax: 0, total: 0 };
        const rate = (po && po.gst_rate != null) ? po.gst_rate : VAR_GST_RATE;
        return `
            <div class="proj-gist-items proj-var-block" data-var-block>
                <div class="proj-var-head">
                    <span class="proj-field-label">Variations${vt.count ? ` (${vt.count})` : ''}</span>
                    <button type="button" class="proj-secondary-btn proj-var-add" data-var-add>+ Add variation</button>
                </div>
                <p class="proj-note proj-var-note">Agreed changes to the contract. Enter a reduction as a
                    negative weight — <strong>-2</strong> subtracts exactly what <strong>2</strong> would add.
                    GST is applied at ${rate}%.</p>
                <div class="proj-li-scroll">
                    <table class="proj-li-table proj-var-table">
                        <thead>
                            <tr>
                                <th>Change</th><th class="proj-li-num">Weight</th><th>Unit</th>
                                <th class="proj-li-num">Rate</th><th class="proj-li-num">Basic</th>
                                <th class="proj-li-num">GST</th><th class="proj-li-num">Total</th><th></th>
                            </tr>
                        </thead>
                        <tbody data-var-body>${list.length ? list.map(v => variationRowHtml(v, false)).join('') : VAR_EMPTY_ROW}</tbody>
                        ${variationFootHtml(vt)}
                    </table>
                </div>
            </div>`;
    }

    // ── Variation edit plumbing ────────────────────────
    function varRowValues(tr) {
        const out = {};
        varFields.forEach(f => {
            const el = tr.querySelector(`[data-var-field="${f}"]`);
            out[f] = el ? el.value.trim() : '';
        });
        return out;
    }

    // Mirrors compute_variation_amounts server-side so the figures move as you
    // type. Purely a preview — the row repaints from the server's answer on save.
    function previewVariation(tr) {
        const v = varRowValues(tr);
        const qty = parseMoney(v.quantity);
        const rate = parseMoney(v.rate);
        const ok = Number.isFinite(qty) && Number.isFinite(rate);
        const basic = ok ? Math.round(qty * rate * 100) / 100 : 0;
        // The server's rate, not the local constant, so PO_VARIATION_GST_RATE
        // stays the single place it's set — otherwise changing it there would
        // leave the preview quoting the old rate right up until save.
        const gst = (currentPo && currentPo.gst_rate != null) ? currentPo.gst_rate : VAR_GST_RATE;
        const tax = Math.round(basic * gst) / 100;
        const set = (key, val) => {
            const cell = tr.querySelector(`[data-var-out="${key}"]`);
            if (cell) cell.textContent = formatDeltaINR(val);
        };
        set('basic', basic);
        set('tax', tax);
        set('total', Math.round((basic + tax) * 100) / 100);
    }

    // Repaint everything a variation change moves *except* the variations table
    // itself, whose inputs the user may still be inside.
    function applyPoChange(po) {
        currentPo = po || null;
        const rowsEl = gistEl.querySelector('[data-gist-rows]');
        if (rowsEl && po) rowsEl.innerHTML = poGistRowsHtml(po);
        const vt = (po && po.variation_totals) || { count: 0 };
        const foot = gistEl.querySelector('.proj-var-table tfoot');
        const footHtml = variationFootHtml(vt);
        // Replacing with '' removes the node outright, so re-adding it later
        // needs the table, not the (now detached) tfoot, as the anchor.
        if (foot) foot.outerHTML = footHtml;
        else if (footHtml) {
            const table = gistEl.querySelector('.proj-var-table');
            if (table) table.insertAdjacentHTML('beforeend', footHtml);
        }
        const head = gistEl.querySelector('.proj-var-head .proj-field-label');
        if (head) head.textContent = `Variations${vt.count ? ` (${vt.count})` : ''}`;
        // The glance ladder reads the *cached* registry row, not insights, so
        // the cache has to move too or the panel repaints to a stale contract.
        const cached = projects.find(x => x.id === activeProjectId);
        if (cached) {
            // po === null means nothing is left to show — no gist row and no
            // variations. Skipping the cache then left the card advertising a
            // contract that no longer exists, and renderList() below would
            // repaint it straight back.
            const rev = po && po.revised;
            cached.po_total_value = rev ? rev.total_value : null;
            cached.po_taxable_value = rev ? rev.taxable_value : null;
            cached.po_total_tax = rev ? rev.total_tax : null;
            // Every field the ladder reads, not just the revised totals: it
            // derives its Contract and Variations blocks from the baseline and
            // rollup splits, so refreshing only the totals left it announcing
            // "2 changes agreed" above a Revised PO value still showing the
            // unvaried figure.
            cached.po_base_taxable_value = po ? po.taxable_value : null;
            cached.po_base_total_tax = po ? po.total_tax : null;
            cached.po_base_total_value = po ? po.total_value : null;
            cached.po_var_taxable = vt.taxable || 0;
            cached.po_var_tax = vt.tax || 0;
            cached.po_var_total = vt.total || 0;
            cached.po_var_count = vt.count;
        }
        // Contract value feeds the ladder and what the client still owes, so the
        // glance is now stale. Debounced because insights is the heaviest query
        // in the app — bills, bank rows and the external salary API — and
        // tabbing across a row would otherwise fire it once per field, flicker
        // the panel through stale numbers, and risk the API returning 0 labour.
        clearTimeout(insightsRefreshTimer);
        const pid = activeProjectId;
        insightsRefreshTimer = setTimeout(() => {
            if (pid === activeProjectId) loadInsights(pid);
        }, 400);
        renderList();
    }

    function varRowError(tr, msg) {
        tr.classList.add('error');
        showToast(msg, 'error');
    }

    async function saveVariationRow(tr) {
        // A save already in flight for this row: remember that the row moved on
        // and re-run once it lands. Returning here without this dropped the
        // edit silently AND let the in-flight save stamp a snapshot taken
        // before it, so the row looked saved and wasn't.
        if (tr.classList.contains('is-saving')) {
            tr.dataset.varPending = '1';
            return;
        }
        const v = varRowValues(tr);
        const isDraft = tr.dataset.varId === 'new';
        if (!v.description) {
            // Says so for saved rows too, not just drafts: blanking the
            // description while editing the weight used to bail out here with
            // no request and no message, silently discarding every later edit
            // to that row for as long as it stayed blank.
            varRowError(tr, 'A change needs a description.');
            return;
        }
        const qty = parseMoney(v.quantity);
        const rate = parseMoney(v.rate);
        if (!Number.isFinite(qty) || !Number.isFinite(rate)) {
            varRowError(tr, 'Weight and rate must be numbers.');
            return;
        }
        if (rate < 0) {
            varRowError(tr, 'Rate must be zero or more — use a negative weight to reduce scope.');
            return;
        }
        // Unchanged? Leave it be — no request, no repaint. Same guard as the
        // overhead field, since focusout fires on every field the user tabs out
        // of, changed or not.
        const snap = tr.dataset.varSnapshot;
        const now = JSON.stringify({
            description: v.description, quantity: trimQty(qty), unit: v.unit, rate: trimQty(rate),
        });
        if (!isDraft && snap === now) return;

        tr.classList.remove('error');
        tr.classList.add('is-saving');
        delete tr.dataset.varPending;
        const body = JSON.stringify({ ...v, quantity: qty, rate });
        // Pinned for the round trip: blurring a cell can close the modal, and
        // the response must not be applied to whichever project is open by the
        // time it lands. Same reason loadPoGist guards its own response.
        const pid = activeProjectId;
        const base = `/api/projects/${pid}/po-variations`;
        try {
            const res = await fetch(isDraft ? base : `${base}/${tr.dataset.varId}`, {
                method: isDraft ? 'POST' : 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body,
            });
            const data = await res.json().catch(() => ({}));
            tr.classList.remove('is-saving');
            if (pid !== activeProjectId) return; // modal changed under us
            if (!res.ok) {
                varRowError(tr, data.message || data.error || `Failed (HTTP ${res.status})`);
                return;
            }
            if (isDraft) {
                // A new row shifts the table anyway, so a full repaint costs
                // nothing here and leaves the grid ready for the next entry.
                renderPoGist(data.po);
                showToast('Variation added.');
            } else {
                tr.dataset.varSnapshot = now;
                const v2 = data.variation || {};
                ['basic', 'tax', 'total'].forEach(k => {
                    const cell = tr.querySelector(`[data-var-out="${k}"]`);
                    if (cell) cell.textContent = formatDeltaINR(v2[`${k}_amount`] || 0);
                });
                showToast('Variation updated.');
            }
            applyPoChange(data.po);
            // Edited again while that was in flight — the row on screen is
            // ahead of what the server just stored, so send the difference.
            if (tr.dataset.varPending && tr.isConnected) {
                delete tr.dataset.varPending;
                saveVariationRow(tr);
            }
        } catch (err) {
            tr.classList.remove('is-saving');
            varRowError(tr, `Network error: ${err.message}`);
        }
    }

    async function deleteVariation(tr) {
        const label = (tr.querySelector('[data-var-field="description"]') || {}).value || 'this change';
        if (!confirm(`Remove "${label}" from the contract?`)) return;
        tr.classList.add('is-saving');
        const pid = activeProjectId; // see saveVariationRow
        try {
            const res = await fetch(
                `/api/projects/${pid}/po-variations/${tr.dataset.varId}`,
                { method: 'DELETE', credentials: 'same-origin' });
            const data = await res.json().catch(() => ({}));
            if (pid !== activeProjectId) return; // modal changed under us
            if (!res.ok) {
                tr.classList.remove('is-saving');
                varRowError(tr, data.message || data.error || `Failed (HTTP ${res.status})`);
                return;
            }
            renderPoGist(data.po);
            applyPoChange(data.po);
            showToast('Variation removed.');
        } catch (err) {
            tr.classList.remove('is-saving');
            varRowError(tr, `Network error: ${err.message}`);
        }
    }

    // Delegated: the gist is re-rendered wholesale whenever the contract moves.
    gistEl.addEventListener('click', (e) => {
        const addBtn = e.target.closest('[data-var-add]');
        if (addBtn) {
            const body = gistEl.querySelector('[data-var-body]');
            if (!body || body.querySelector('.is-draft')) return; // one draft at a time
            const empty = body.querySelector('[data-var-empty]');
            if (empty) empty.remove();
            body.insertAdjacentHTML('beforeend', variationRowHtml({}, true));
            // decorateProjLiTables skips tables it has already stamped, so a row
            // added after that first pass would reach a phone with no
            // data-label on any cell — four unlabelled boxes you can't tell
            // apart. Clear the stamp so the new row gets decorated too.
            const table = body.closest('.proj-li-table');
            if (table) {
                table.removeAttribute('data-mobi');
                decorateProjLiTables(gistEl);
            }
            const first = body.querySelector('.is-draft [data-var-field="description"]');
            if (first) first.focus();
            return;
        }
        const saveBtn = e.target.closest('[data-var-save]');
        if (saveBtn) { saveVariationRow(saveBtn.closest('tr')); return; }
        const discardBtn = e.target.closest('[data-var-discard]');
        if (discardBtn) {
            const body = gistEl.querySelector('[data-var-body]');
            discardBtn.closest('tr').remove();
            if (body && !body.children.length) body.innerHTML = VAR_EMPTY_ROW;
            return;
        }
        const delBtn = e.target.closest('[data-var-delete]');
        if (delBtn) deleteVariation(delBtn.closest('tr'));
    });

    gistEl.addEventListener('input', (e) => {
        const field = e.target.closest('[data-var-field]');
        if (field) previewVariation(field.closest('tr'));
    });

    // focusout is the single commit path for saved rows, matching the overhead
    // field. A draft row is explicitly *not* committed on blur: clicking away
    // from a half-typed change would post a variation the user never agreed to.
    gistEl.addEventListener('focusout', (e) => {
        const field = e.target.closest('[data-var-field]');
        if (!field) return;
        const tr = field.closest('tr');
        // saveVariationRow owns the in-flight case now — it queues rather than
        // drops, so blurring mid-save no longer loses the edit.
        if (tr && tr.dataset.varId !== 'new') saveVariationRow(tr);
    });

    gistEl.addEventListener('keydown', (e) => {
        const field = e.target.closest('[data-var-field]');
        if (!field) return;
        const tr = field.closest('tr');
        if (e.key === 'Enter') {
            e.preventDefault();
            if (tr.dataset.varId === 'new') saveVariationRow(tr);
            else field.blur();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            // Escape on the document closes every open modal. Here it means
            // "undo this cell" — without stopping it, discarding a typo would
            // also shut the whole project pop-up and lose the user's place.
            e.stopPropagation();
            if (tr.dataset.varId === 'new') {
                const body = gistEl.querySelector('[data-var-body]');
                tr.remove();
                if (body && !body.children.length) body.innerHTML = VAR_EMPTY_ROW;
                return;
            }
            // Restore from the snapshot, then let focusout no-op.
            const snap = JSON.parse(tr.dataset.varSnapshot || '{}');
            varFields.forEach(f => {
                const el = tr.querySelector(`[data-var-field="${f}"]`);
                if (el) el.value = snap[f] == null ? '' : snap[f];
            });
            previewVariation(tr);
            field.blur();
        }
    });

    // ── Type toggle (project / design / other) ─────────
    const TYPE_LABELS = { project: 'a project', design: 'a design', other: 'an internal “other”' };
    detailTypeRadios().forEach(radio => {
        radio.addEventListener('change', async () => {
            if (!activeProjectId || !radio.checked) return;
            const projectType = radio.value;
            detailTypeStatus.classList.remove('error');
            detailTypeStatus.textContent = 'Saving…';
            try {
                const res = await fetch(`/api/projects/${activeProjectId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ project_type: projectType }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    detailTypeStatus.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                    detailTypeStatus.classList.add('error');
                    return;
                }
                // Sync cached list so the sections regroup on close/reopen
                const cached = projects.find(x => x.id === activeProjectId);
                if (cached) {
                    cached.project_type = projectType;
                    cached.is_project = (projectType === 'project');
                }
                detailTypeStatus.textContent = 'Saved';
                showToast(`Marked as ${TYPE_LABELS[projectType] || 'updated'}.`);
                loadProjects();
            } catch (err) {
                detailTypeStatus.textContent = `Network error: ${err.message}`;
                detailTypeStatus.classList.add('error');
            }
        });
    });

    // ── Closed / active toggle ─────────────────────────
    detailInactiveToggle.addEventListener('change', async () => {
        if (!activeProjectId) return;
        const makeInactive = detailInactiveToggle.checked;
        detailStatusStatus.classList.remove('error');
        detailStatusStatus.textContent = 'Saving…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ is_inactive: makeInactive }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                detailStatusStatus.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                detailStatusStatus.classList.add('error');
                detailInactiveToggle.checked = !makeInactive; // revert
                return;
            }
            const cached = projects.find(x => x.id === activeProjectId);
            if (cached) cached.is_inactive = makeInactive;
            detailStatusStatus.textContent = 'Saved';
            showToast(makeInactive ? 'Project marked closed.' : 'Project reopened.');
            loadProjects();
        } catch (err) {
            detailStatusStatus.textContent = `Network error: ${err.message}`;
            detailStatusStatus.classList.add('error');
            detailInactiveToggle.checked = !makeInactive; // revert
        }
    });

    // ── Overhead (edited in place in the Expenses list) ─
    // A cost bills and bank statements can't see, so it's typed in by hand and
    // feeds the project's cost total and profit. Delegated, because the panel
    // is re-rendered wholesale whenever the numbers change.
    // "₹2,50,000.00" / "250000" / "2,50,000" -> 250000.
    // Cleared field -> 0 (a deliberate "no overhead"); anything with content but
    // no number in it -> NaN, so junk is rejected rather than silently zeroing.
    function parseMoney(text) {
        const s = String(text ?? '').trim();
        if (!s) return 0;
        const cleaned = s.replace(/[^0-9.-]/g, '');
        if (!cleaned) return NaN;
        return Number(cleaned);
    }

    async function saveOverhead(input) {
        if (!activeProjectId) return;
        const value = parseMoney(input.value);
        const original = Number(input.dataset.raw) || 0;
        if (!Number.isFinite(value) || value < 0) {
            input.classList.add('error');
            showToast('Overhead must be a number, zero or more.', 'error');
            input.value = original ? formatINR(original) : '';
            return;
        }
        input.classList.remove('error');
        // Unchanged? Reformat and leave it alone — no request, and no repaint
        // churning the panel for nothing.
        if (Math.abs(original - value) < 0.005) {
            input.value = value ? formatINR(value) : '';
            return;
        }
        input.value = formatINR(value); // show the committed value while saving
        input.disabled = true;
        const cached = projects.find(x => x.id === activeProjectId);
        try {
            const res = await fetch(`/api/projects/${activeProjectId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ overhead: value }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                input.classList.add('error');
                input.disabled = false;
                showToast(data.message || data.error || `Failed (HTTP ${res.status})`, 'error');
                return;
            }
            if (cached) cached.overhead = value;
            // Overhead is a cost input, so the glance is now stale: refetch so
            // the list, total cost and profit all move together. This re-renders
            // the panel, replacing the (disabled) input with a fresh one.
            loadInsights(activeProjectId);
            showToast('Overhead updated.');
        } catch (err) {
            input.disabled = false;
            input.classList.add('error');
            showToast(`Network error: ${err.message}`, 'error');
        }
    }

    // Editing shows the plain number; at rest it shows the formatted figure so
    // the column stays symmetrical.
    detailOverview.addEventListener('focusin', (e) => {
        const input = e.target.closest('[data-overhead-input]');
        if (!input) return;
        const raw = Number(input.dataset.raw) || 0;
        input.value = raw ? String(raw) : '';
        input.select();
    });
    // focusout is the single commit path — it covers blur, Tab and Enter (which
    // blurs below). Wiring 'change' as well would PATCH twice.
    detailOverview.addEventListener('focusout', (e) => {
        const input = e.target.closest('[data-overhead-input]');
        if (input && !input.disabled) saveOverhead(input);
    });
    detailOverview.addEventListener('keydown', (e) => {
        const input = e.target.closest('[data-overhead-input]');
        if (!input) return;
        if (e.key === 'Enter') {
            e.preventDefault();
            input.blur();
        } else if (e.key === 'Escape') {
            // Escape on the document closes every open modal. Inside a field it
            // means "undo this cell", so the event stops here — otherwise
            // discarding a typo also shut the whole project pop-up and threw the
            // user out of the panel they were working in. preventDefault alone
            // wouldn't do it: bubbling is what reaches the document listener.
            e.preventDefault();
            e.stopPropagation();
            const raw = Number(input.dataset.raw) || 0;
            input.value = raw ? String(raw) : ''; // discard, then let focusout no-op
            input.blur();
        }
    });

    // ── Reprocess ──────────────────────────────────────
    reprocessBtn.addEventListener('click', async () => {
        if (!activeProjectId) return;
        reprocessBtn.disabled = true;
        const orig = reprocessBtn.textContent;
        reprocessBtn.textContent = 'Reprocessing…';
        gistEl.innerHTML = `<div class="proj-gist-loading">Re-reading the PO with AI…</div>`;
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/process-po`, {
                method: 'POST', credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            currentPo = data.po || null;
            renderPoGist(currentPo);
            showToast(data.success ? 'PO reprocessed.' : (data.message || 'Extraction failed — enter the value manually.'),
                data.success ? 'success' : 'error');
            loadProjects(); // refresh card chips
        } catch (err) {
            showToast(`Network error: ${err.message}`, 'error');
            renderPoGist(currentPo);
        } finally {
            reprocessBtn.disabled = false;
            reprocessBtn.textContent = orig;
        }
    });

    // ── Edit values ────────────────────────────────────
    editBtn.addEventListener('click', () => {
        const po = currentPo || {};
        editForm.total_value.value = po.total_value ?? '';
        editForm.po_number.value = po.po_number ?? '';
        editForm.po_date.value = po.po_date ?? '';
        editForm.client_name.value = po.client_name ?? '';
        editForm.taxable_value.value = po.taxable_value ?? '';
        editForm.total_tax.value = po.total_tax ?? '';
        editError.classList.add('hidden');
        editForm.classList.remove('hidden');
        poActions.classList.add('hidden');
        gistEl.classList.add('hidden');
    });

    editCancel.addEventListener('click', exitPoEditForm);

    editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        editError.classList.add('hidden');
        const payload = {
            total_value: editForm.total_value.value,
            po_number: editForm.po_number.value,
            po_date: editForm.po_date.value,
            client_name: editForm.client_name.value,
            taxable_value: editForm.taxable_value.value,
            total_tax: editForm.total_tax.value,
        };
        const btn = editForm.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.textContent = 'Saving…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/po-data`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                editError.textContent = data.message || data.error || `Failed (HTTP ${res.status})`;
                editError.classList.remove('hidden');
                return;
            }
            currentPo = data.po || null;
            renderPoGist(currentPo);
            exitPoEditForm();
            showToast('PO values updated.');
            loadProjects();
        } catch (err) {
            editError.textContent = `Network error: ${err.message}`;
            editError.classList.remove('hidden');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Save changes';
        }
    });

    detailUploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!activeProjectId) return;
        detailUploadError.classList.add('hidden');
        detailUploadError.textContent = '';

        if (!detailPoInput.files || !detailPoInput.files[0]) {
            detailUploadError.textContent = 'Please choose a file.';
            detailUploadError.classList.remove('hidden');
            return;
        }
        const fd = new FormData();
        fd.append('po_file', detailPoInput.files[0]);

        const btn = detailUploadForm.querySelector('button[type="submit"]');
        btn.disabled = true;
        btn.textContent = 'Uploading…';
        try {
            const res = await fetch(`/api/projects/${activeProjectId}/upload-po`, {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                detailUploadError.textContent = data.message || data.error || `Upload failed (HTTP ${res.status})`;
                detailUploadError.classList.remove('hidden');
                btn.disabled = false;
                btn.textContent = 'Upload PO';
                return;
            }
            closeModal(detailModal);
            showToast('PO uploaded successfully.');
            await loadProjects();
        } catch (err) {
            detailUploadError.textContent = `Network error: ${err.message}`;
            detailUploadError.classList.remove('hidden');
            btn.disabled = false;
            btn.textContent = 'Upload PO';
        }
    });

    // ── Boot ───────────────────────────────────────────
    loadProjects();
})();
