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
    const detailPoExisting = document.getElementById('detail-po-existing');
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

    const detailPayments = document.getElementById('detail-payments');

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

    // The three registry buckets, in display order. A row's bucket comes from
    // project_type, falling back to the legacy is_project boolean.
    const TYPE_SECTIONS = [
        { key: 'project', title: 'Projects', sub: 'Valid client / site projects', variant: 'projects' },
        { key: 'design', title: 'Designs', sub: 'Design-only work', variant: 'designs' },
        { key: 'other', title: 'Others', sub: 'Internal heads (office, factory, KVB, sridhar…)', variant: 'others' },
    ];
    const projectTypeOf = (p) => p.project_type || (p.is_project === false ? 'other' : 'project');

    let projects = [];
    let activeProjectId = null;

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
        card.className = 'project-card';
        card.dataset.id = p.id;
        const created = p.created_at ? new Date(p.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }) : '';
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
        TYPE_SECTIONS.forEach(sec => {
            const items = projects.filter(p => projectTypeOf(p) === sec.key);
            if (items.length) {
                listEl.appendChild(renderSection(sec.title, sec.sub, items, sec.variant));
            }
        });
    }

    function escapeHtml(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Indian-format a number with a ₹ prefix (e.g. 2325190 -> ₹23,25,190).
    function formatINR(value) {
        const n = Number(value) || 0;
        return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
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
        renderPayments(p);
        // Start in read-only view; editing is opt-in via the header Edit button.
        setEditMode(false);
        // Cash client payments ledger — form is collapsed until "+ Add".
        setCashFormOpen(false);
        cashForm.reset();
        cashError.classList.add('hidden');
        cashError.textContent = '';
        loadCashPayments(p.id);
        // Reflect current type in the toggle
        const wantVal = projectTypeOf(p);
        detailTypeRadios().forEach(r => { r.checked = (r.value === wantVal); });
        detailTypeStatus.textContent = '';
        detailTypeStatus.classList.remove('error');
        detailUploadError.classList.add('hidden');
        detailUploadError.textContent = '';
        detailUploadForm.reset();

        if (p.has_po) {
            detailPoExisting.classList.remove('hidden');
            detailUploadBlock.classList.add('hidden');
            detailPoFilename.textContent = p.po_filename;
            detailPoLink.href = `/api/projects/${p.id}/po`;
            poAdmin.classList.remove('hidden');
            exitPoEditForm();
            loadPoGist(p.id);
        } else {
            detailPoExisting.classList.add('hidden');
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
        setEditMode(editPanel.classList.contains('hidden'));
    });

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
        cashToggleLabel.textContent = on ? 'Close' : 'Add';
        if (on) setTimeout(() => cashAmount.focus(), 50);
    }
    cashToggleBtn.addEventListener('click', () => {
        setCashFormOpen(cashForm.classList.contains('hidden'));
    });

    // ── PO value vs client payments received ──────────
    function renderPayments(p) {
        const po = Number(p.po_total_value) || 0;
        const rec = Number(p.received_total) || 0;
        const bank = Number(p.received_bank) || 0;
        const cash = Number(p.received_cash) || 0;
        if (po <= 0 && rec <= 0) {
            detailPayments.classList.add('hidden');
            detailPayments.innerHTML = '';
            return;
        }
        const bal = po - rec;
        const pct = po > 0 ? Math.min(100, Math.round((rec / po) * 100)) : null;
        const balLabel = bal < -0.5 ? 'Excess' : 'Balance';
        const balCls = bal > 0.5 ? 'due' : 'settled';
        // Only show the bank/cash split once cash is actually in play — otherwise
        // "Received" alone is clearer.
        const splitNote = cash > 0
            ? `<span class="proj-pay-split" title="Bank transfers: ${escapeHtml(formatINR(bank))} · Cash: ${escapeHtml(formatINR(cash))}">${formatINRCompact(bank)} bank + ${formatINRCompact(cash)} cash</span>`
            : '';
        detailPayments.innerHTML = `
            <div class="proj-pay-head">
                <span class="proj-field-label">Payments vs PO</span>
                ${pct != null ? `<span class="proj-pay-pct">${pct}% received</span>` : ''}
            </div>
            <div class="proj-pay-grid">
                <div class="proj-pay-cell">
                    <span class="proj-pay-k">PO value</span>
                    <span class="proj-pay-v">${po > 0 ? formatINR(po) : '—'}</span>
                </div>
                <div class="proj-pay-cell">
                    <span class="proj-pay-k">Received</span>
                    <span class="proj-pay-v received">${formatINR(rec)}</span>
                    ${splitNote}
                </div>
                <div class="proj-pay-cell">
                    <span class="proj-pay-k">${balLabel}</span>
                    <span class="proj-pay-v ${balCls}">${po > 0 ? formatINR(Math.abs(bal)) : '—'}</span>
                </div>
            </div>
            ${pct != null ? `<div class="proj-pay-bar"><div class="proj-pay-bar-fill" style="width:${pct}%"></div></div>` : ''}`;
        detailPayments.classList.remove('hidden');
    }

    // ── Cash client payments ───────────────────────────
    function applyPaymentSummary(summary) {
        // Push fresh totals into the cached project so the card + payments view
        // reflect the change without a full reload.
        const cached = projects.find(x => x.id === activeProjectId);
        if (cached) {
            cached.received_bank = summary.received_bank;
            cached.received_cash = summary.received_cash;
            cached.received_total = summary.received_total;
            renderPayments(cached);
            renderList(); // keep the registry card's "Received" in sync
        }
        renderCashList(summary.payments || []);
    }

    function renderCashList(payments) {
        const total = payments.reduce((s, c) => s + (Number(c.amount) || 0), 0);
        cashTotalEl.textContent = payments.length ? formatINR(total) : '';
        if (!payments.length) {
            cashListEl.innerHTML = `<p class="proj-cash-empty">No cash payments recorded yet.</p>`;
            return;
        }
        cashListEl.innerHTML = payments.map(c => {
            const when = c.payment_date
                ? new Date(c.payment_date).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })
                : (c.created_at ? new Date(c.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' }) : '');
            return `
                <div class="proj-cash-item" data-id="${c.id}">
                    <div class="proj-cash-item-main">
                        <span class="proj-cash-item-amt">${formatINR(c.amount)}</span>
                        ${c.note ? `<span class="proj-cash-item-note">${escapeHtml(c.note)}</span>` : ''}
                    </div>
                    <div class="proj-cash-item-side">
                        ${when ? `<span class="proj-cash-item-date">${when}</span>` : ''}
                        <button type="button" class="proj-cash-del" data-id="${c.id}" title="Remove this payment" aria-label="Remove this payment">×</button>
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
        const rows = [
            ['Total project value', formatINR(po.total_value), 'headline'],
            ['PO number', po.po_number ? escapeHtml(po.po_number) : '—'],
            ['PO date', po.po_date ? escapeHtml(po.po_date) : '—'],
            ['Client', po.client_name ? escapeHtml(po.client_name) : '—'],
            ['Taxable value', formatINR(po.taxable_value)],
            ['Total tax', formatINR(po.total_tax)],
            ['Scope items', po.line_item_count != null ? po.line_item_count : '—'],
        ];
        if (po.payment_terms) rows.push(['Payment terms', escapeHtml(po.payment_terms)]);
        if (po.amount_in_words) rows.push(['In words', escapeHtml(po.amount_in_words)]);

        const manualTag = po.extraction_status === 'manual'
            ? `<span class="proj-gist-tag">manually edited</span>` : '';

        gistEl.innerHTML = `
            <div class="proj-gist-header">
                <span class="proj-field-label">Extracted PO gist</span>${manualTag}
            </div>
            <div class="proj-gist-rows">
                ${rows.map(([k, v, cls]) => `
                    <div class="proj-gist-row ${cls === 'headline' ? 'headline' : ''}">
                        <span class="proj-gist-k">${k}</span>
                        <span class="proj-gist-v">${v}</span>
                    </div>`).join('')}
            </div>
            ${renderPoLineItems(po.line_items)}`;
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
