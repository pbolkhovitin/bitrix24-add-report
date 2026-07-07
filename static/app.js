/* SLA Dashboard — frontend logic */

// ---- State ----
let currentData = {
    summary: null,
    tasks: [],
    timeline: [],
    statusDist: null,
    filters: null,
};
let charts = {};
let sortState = { key: null, asc: true };

// ---- Init ----
document.addEventListener('DOMContentLoaded', async () => {
    await loadFilters();
    setDefaultDates();
    await refreshAll();
});

function setDefaultDates() {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 30);
    document.getElementById('filterFrom').value = toISODate(from);
    document.getElementById('filterTo').value = toISODate(to);
}

function toISODate(d) {
    return d.getFullYear() + '-' +
        String(d.getMonth() + 1).padStart(2, '0') + '-' +
        String(d.getDate()).padStart(2, '0');
}

// ---- API helpers ----
function getFilters() {
    return {
        from_date: document.getElementById('filterFrom').value || undefined,
        to_date: document.getElementById('filterTo').value || undefined,
        responsible_id: document.getElementById('filterResponsible').value || undefined,
        priority: document.getElementById('filterPriority').value || undefined,
        group_id: document.getElementById('filterGroup').value || undefined,
        signal: document.getElementById('filterSignal').value || 'status',
    };
}

function qs(params) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== '' && v !== null) {
            p.set(k, v);
        }
    }
    return p.toString();
}

async function apiFetch(url) {
    const resp = await fetch(url);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
    }
    return resp.json();
}

async function apiPost(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
    }
    return resp.json();
}

// ---- Data Loading ----
async function refreshAll() {
    const filters = getFilters();

    try {
        const [summary, tasks, timeline, statusDist, config] = await Promise.all([
            apiFetch('/api/summary?' + qs(filters)),
            apiFetch('/api/tasks?' + qs(filters)),
            apiFetch('/api/timeline?' + qs({ ...filters, bucket: 'day' })),
            apiFetch('/api/status_distribution?' + qs(filters)),
            apiFetch('/api/config'),
        ]);

        currentData.summary = summary;
        currentData.tasks = tasks;
        currentData.timeline = timeline;
        currentData.statusDist = statusDist;
        currentData.config = config;

        renderAll();
        renderTable(tasks);
    } catch (err) {
        showToast('Ошибка загрузки: ' + err.message);
    }
}

async function loadFilters() {
    try {
        const data = await apiFetch('/api/filters');
        currentData.filters = data;

        const selResp = document.getElementById('filterResponsible');
        selResp.innerHTML = '<option value="">Все</option>';
        for (const r of (data.responsibles || [])) {
            selResp.innerHTML += `<option value="${r.id}">${r.name}</option>`;
        }

        const selPrio = document.getElementById('filterPriority');
        selPrio.innerHTML = '<option value="">Все</option>';
        for (const p of (data.priorities || [])) {
            selPrio.innerHTML += `<option value="${p.id}">${p.label}</option>`;
        }

        const selGrp = document.getElementById('filterGroup');
        selGrp.innerHTML = '<option value="">Все</option>';
        for (const g of (data.groups || [])) {
            selGrp.innerHTML += `<option value="${g.id}">${g.title}</option>`;
        }
    } catch (err) {
        console.error('Failed to load filters:', err);
    }
}

function applyFilters() {
    refreshAll();
}

// ---- Render ----
function renderAll() {
    const s = currentData.summary;
    if (!s) return;

    const kpis = s.kpis || {};
    const fmtPct = v => v !== null && v !== undefined ? v + '%' : '—';
    const fmtMin = v => v !== null && v !== undefined ? Math.round(v) + ' мин' : '—';

    document.getElementById('kpiTotal').textContent = kpis.total || 0;

    const frEl = document.getElementById('kpiFRPct');
    frEl.textContent = fmtPct(kpis.sla_first_response_pct);
    frEl.className = 'kpi-value ' + (kpis.sla_first_response_pct >= 80 ? 'kpi-good' : kpis.sla_first_response_pct !== null ? 'kpi-bad' : '');

    const resEl = document.getElementById('kpiResPct');
    resEl.textContent = fmtPct(kpis.sla_resolution_pct);
    resEl.className = 'kpi-value ' + (kpis.sla_resolution_pct >= 80 ? 'kpi-good' : kpis.sla_resolution_pct !== null ? 'kpi-bad' : '');

    const dlEl = document.getElementById('kpiDeadlinePct');
    dlEl.textContent = fmtPct(kpis.deadline_met_pct);
    dlEl.className = 'kpi-value ' + (kpis.deadline_met_pct >= 80 ? 'kpi-good' : kpis.deadline_met_pct !== null ? 'kpi-bad' : '');

    document.getElementById('kpiAvgFR').textContent = fmtMin(kpis.avg_first_response_min);
    document.getElementById('kpiAvgRes').textContent = fmtMin(kpis.avg_resolution_min);
    document.getElementById('kpiBreached').textContent = kpis.breached_count || 0;

    renderTimeline();
    renderAssigneeChart();
    renderStatusChart();
    renderSlaDoughnut();
    renderPriorityChart();
}

function renderTimeline() {
    const data = currentData.timeline || [];
    const labels = data.map(d => d.bucket);
    const total = data.map(d => d.total);
    const breached = data.map(d => d.breached);

    const ctx = document.getElementById('timelineChart').getContext('2d');
    destroyChart('timeline');

    charts.timeline = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Всего',
                    data: total,
                    backgroundColor: 'rgba(26,115,232,0.7)',
                    borderRadius: 4,
                },
                {
                    label: 'Просрочено',
                    data: breached,
                    backgroundColor: 'rgba(217,48,37,0.7)',
                    borderRadius: 4,
                },
            ],
        },
        options: {
            responsive: true,
            plugins: { legend: { position: 'top' } },
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true, ticks: { stepSize: 1 } },
            },
        },
    });
}

function renderAssigneeChart() {
    const data = (currentData.summary?.by_assignee || []).slice(0, 10);
    const labels = data.map(d => d.name || `#${d.id}`);
    const totals = data.map(d => d.total);
    const avgRes = data.map(d => d.avg_resolution_min || 0);

    const ctx = document.getElementById('assigneeChart').getContext('2d');
    destroyChart('assignee');

    charts.assignee = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Задач',
                    data: totals,
                    backgroundColor: 'rgba(26,115,232,0.7)',
                    borderRadius: 4,
                    yAxisID: 'y',
                },
                {
                    label: 'Ср. решение (мин)',
                    data: avgRes,
                    backgroundColor: 'rgba(249,171,0,0.7)',
                    borderRadius: 4,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            plugins: { legend: { position: 'top' } },
            scales: {
                y: { beginAtZero: true, position: 'left', ticks: { stepSize: 1 } },
                y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false } },
            },
        },
    });
}

function renderStatusChart() {
    const data = currentData.statusDist;
    if (!data) return;

    const labels = Object.keys(data.counts);
    const values = Object.values(data.counts);
    const colors = ['#1a73e8', '#0f9d58', '#f9ab00', '#d93025', '#9aa0a6', '#5f6368', '#e8eaed'];

    const ctx = document.getElementById('statusChart').getContext('2d');
    destroyChart('status');

    charts.status = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: colors.slice(0, labels.length),
            }],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'bottom' },
            },
        },
    });
}

function renderSlaDoughnut() {
    const s = currentData.summary?.kpis;
    if (!s) return;
    const met = s.sla_fully_met || 0;
    const total = s.total || 0;
    const breached = s.breached_count || 0;
    const unknown = total - met - breached;

    const ctx = document.getElementById('slaDoughnut').getContext('2d');
    destroyChart('sla');

    charts.sla = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['В SLA', 'Просрочено', 'Н/Д'],
            datasets: [{
                data: [met, breached, Math.max(0, unknown)],
                backgroundColor: ['#0f9d58', '#d93025', '#9aa0a6'],
            }],
        },
        options: {
            responsive: true,
            plugins: {
                legend: { position: 'bottom' },
            },
        },
    });
}

function renderPriorityChart() {
    const data = currentData.summary?.by_priority || [];
    const labels = data.map(d => d.label);
    const slaPct = data.map(d => d.sla_first_response_pct !== null ? d.sla_first_response_pct : 0);
    const totals = data.map(d => d.total);

    const ctx = document.getElementById('priorityChart').getContext('2d');
    destroyChart('priority');

    charts.priority = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                {
                    label: 'Задач',
                    data: totals,
                    backgroundColor: 'rgba(26,115,232,0.7)',
                    borderRadius: 4,
                    yAxisID: 'y',
                },
                {
                    label: '% SLA (ответ)',
                    data: slaPct,
                    backgroundColor: 'rgba(15,157,88,0.7)',
                    borderRadius: 4,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            plugins: { legend: { position: 'top' } },
            scales: {
                y: { beginAtZero: true, position: 'left', ticks: { stepSize: 1 } },
                y1: { beginAtZero: true, max: 100, position: 'right', grid: { drawOnChartArea: false } },
            },
        },
    });
}

// ---- Table ----
function renderTable(tasks) {
    const tbody = document.getElementById('tasksBody');
    document.getElementById('tableCount').textContent = `${tasks.length} задач`;

    let html = '';
    for (const t of tasks) {
        const slaClass = t.sla_first_response_met === false || t.sla_resolution_met === false
            ? 'sla-badge-breached'
            : (t.sla_first_response_met === true && t.sla_resolution_met !== false)
                ? 'sla-badge-met'
                : 'sla-badge-na';

        const slaText = t.sla_first_response_met === false || t.sla_resolution_met === false
            ? 'Просрочено'
            : (t.sla_first_response_met === true && t.sla_resolution_met !== false)
                ? 'Выполнен'
                : 'Н/Д';

        const created = t.created_at ? formatDate(t.created_at) : '—';
        const deadline = t.deadline ? formatDate(t.deadline) : '—';

        html += `<tr>
            <td>${t.task_id || ''}</td>
            <td>${escapeHtml(t.title || '')}</td>
            <td>${escapeHtml(t.responsible_name || '—')}</td>
            <td>${escapeHtml(t.priority_label || '')}</td>
            <td>${created}</td>
            <td>${t.first_response_str || '—'}</td>
            <td>${t.resolution_str || '—'}</td>
            <td>${deadline}</td>
            <td><span class="sla-badge ${slaClass}">${slaText}</span></td>
        </tr>`;
    }
    tbody.innerHTML = html || '<tr><td colspan="9" style="text-align:center;padding:20px;color:var(--gray-500)">Нет данных</td></tr>';
    document.getElementById('tableInfo').textContent = `Показано ${tasks.length} записей`;
}

function formatDate(d) {
    if (!d) return '—';
    try {
        const dt = new Date(d);
        return dt.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' }) +
            ' ' + dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    } catch {
        return String(d).slice(0, 10);
    }
}

function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

// ---- Sorting ----
function sortTable(key) {
    if (sortState.key === key) {
        sortState.asc = !sortState.asc;
    } else {
        sortState.key = key;
        sortState.asc = true;
    }

    const tasks = [...(currentData.tasks || [])];
    tasks.sort((a, b) => {
        let va = a[key];
        let vb = b[key];
        if (va === null || va === undefined) va = '';
        if (vb === null || vb === undefined) vb = '';
        if (typeof va === 'string') va = va.toLowerCase();
        if (typeof vb === 'string') vb = vb.toLowerCase();
        if (va < vb) return sortState.asc ? -1 : 1;
        if (va > vb) return sortState.asc ? 1 : -1;
        return 0;
    });
    renderTable(tasks);
}

// ---- Sync ----
async function syncData() {
    const btn = document.getElementById('syncBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="loading"></span> Синхронизация...';
    try {
        await apiPost('/api/sync', {});
        showToast('Синхронизация запущена');
        // Poll for updates
        let attempts = 0;
        const poll = setInterval(async () => {
            attempts++;
            try {
                await refreshAll();
                const syncState = await apiFetch('/api/summary?' + qs(getFilters()));
                if (attempts >= 3) {
                    clearInterval(poll);
                    showToast('Синхронизация завершена');
                }
                clearInterval(poll);
                showToast('Синхронизация завершена');
            } catch {
                if (attempts >= 6) {
                    clearInterval(poll);
                    showToast('Ошибка синхронизации');
                }
            }
        }, 2000);
    } catch (err) {
        showToast('Ошибка: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔄 Обновить данные';
    }
}

// ---- Settings Modal ----
async function openSettings() {
    try {
        const config = currentData.config || await apiFetch('/api/config');
        document.getElementById('whStart').value = config.working_hours?.start || '09:00';
        document.getElementById('whEnd').value = config.working_hours?.end || '18:00';
        document.getElementById('whWorkdays').value = (config.working_hours?.workdays || [1, 2, 3, 4, 5]).join(',');

        const holidays = config.working_hours?.holidays || [];
        document.getElementById('whHolidays').value = holidays.join('\n');

        // Threshold inputs
        const thr = config.sla_thresholds || {};
        let thrHtml = '';
        const keys = Object.keys(thr).sort((a, b) => {
            if (a === 'default') return -1;
            if (b === 'default') return 1;
            return parseInt(a) - parseInt(b);
        });
        for (const k of keys) {
            const v = thr[k];
            const label = config.priority_labels && config.priority_labels[k]
                ? config.priority_labels[k]
                : (k === 'default' ? 'По умолчанию' : `Приоритет ${k}`);
            thrHtml += `<div class="form-row" style="margin-bottom:8px">
                <div><label style="font-weight:400">${label} — первый ответ (мин)</label><input type="number" class="thr-fr" data-key="${k}" value="${v.first_response_minutes || ''}"></div>
                <div><label style="font-weight:400">${label} — решение (мин)</label><input type="number" class="thr-res" data-key="${k}" value="${v.resolution_minutes || ''}"></div>
            </div>`;
        }
        document.getElementById('thresholdInputs').innerHTML = thrHtml;

        document.getElementById('settingsModal').classList.add('active');
    } catch (err) {
        showToast('Ошибка загрузки настроек: ' + err.message);
    }
}

function closeSettings() {
    document.getElementById('settingsModal').classList.remove('active');
}

async function saveSettings() {
    const thresholds = {};
    document.querySelectorAll('.thr-fr').forEach(el => {
        const k = el.dataset.key;
        if (!thresholds[k]) thresholds[k] = {};
        thresholds[k].first_response_minutes = parseInt(el.value) || 0;
    });
    document.querySelectorAll('.thr-res').forEach(el => {
        const k = el.dataset.key;
        if (!thresholds[k]) thresholds[k] = {};
        thresholds[k].resolution_minutes = parseInt(el.value) || 0;
    });

    const workdays = document.getElementById('whWorkdays').value
        .split(',')
        .map(s => parseInt(s.trim()))
        .filter(n => !isNaN(n));

    const holidays = document.getElementById('whHolidays').value
        .split('\n')
        .map(s => s.trim())
        .filter(s => s.length > 0);

    const data = {
        thresholds,
        working_hours: {
            start: document.getElementById('whStart').value,
            end: document.getElementById('whEnd').value,
            workdays: workdays,
            holidays: holidays,
        },
    };

    try {
        await apiPost('/api/config', data);
        showToast('Настройки сохранены');
        closeSettings();
        await refreshAll();
    } catch (err) {
        showToast('Ошибка сохранения: ' + err.message);
    }
}

// ---- Toast ----
function showToast(msg) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 3000);
}

// ---- Chart cleanup ----
function destroyChart(key) {
    if (charts[key]) {
        charts[key].destroy();
        delete charts[key];
    }
}


// ===================== Tab Navigation =====================

function switchTab(tabId, event) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    if (event) event.target.classList.add('active');
    document.getElementById('tab-' + tabId).classList.add('active');

    if (tabId === 'deviations') loadDeviations();
    else if (tabId === 'daily') loadDailyControl();
    else if (tabId === 'weekly') loadWeeklyReview();
    else if (tabId === 'routing') loadRouting();
}


// ===================== Deviations =====================

async function loadDeviations() {
    try {
        const data = await apiFetch('/api/deviations');
        const container = document.getElementById('deviationSummary');
        const body = document.getElementById('deviationBody');

        const summary = data.summary || {};
        const bySev = summary.by_severity || {};

        container.innerHTML = `
            <div class="kpi-card"><div class="kpi-value kpi-bad">${summary.total || 0}</div><div class="kpi-label">Всего отклонений</div></div>
            <div class="kpi-card"><div class="kpi-value" style="color:var(--danger)">${bySev.high || 0}</div><div class="kpi-label">Высоких</div></div>
            <div class="kpi-card"><div class="kpi-value" style="color:var(--warning)">${bySev.medium || 0}</div><div class="kpi-label">Средних</div></div>
            <div class="kpi-card"><div class="kpi-value kpi-neutral">${bySev.low || 0}</div><div class="kpi-label">Низких</div></div>
        `;

        const devs = data.deviations || [];
        if (devs.length === 0) {
            body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--gray-500)">Отклонений не найдено</td></tr>';
            return;
        }

        let html = '';
        for (const d of devs) {
            const badgeClass = d.severity === 'high' ? 'deviation-badge-high'
                : d.severity === 'medium' ? 'deviation-badge-medium'
                : 'deviation-badge-low';
            const sevLabel = d.severity === 'high' ? 'Высокая'
                : d.severity === 'medium' ? 'Средняя' : 'Низкая';
            html += `<tr>
                <td>${d.task_id}</td>
                <td>${escapeHtml(d.title || '')}</td>
                <td>${escapeHtml(d.type_label || '')}</td>
                <td><span class="deviation-badge ${badgeClass}">${sevLabel}</span></td>
                <td>${escapeHtml(d.detail || '')}</td>
                <td>${escapeHtml(d.responsible_name || '—')}</td>
            </tr>`;
        }
        body.innerHTML = html;
    } catch (err) {
        showToast('Ошибка загрузки отклонений: ' + err.message);
    }
}


// ===================== Daily Control =====================

async function loadDailyControl() {
    try {
        const data = await apiFetch('/api/daily_control');
        const container = document.getElementById('dailyContent');

        if (!data || !data.summary) {
            container.innerHTML = '<p style="color:var(--gray-500)">Нет данных</p>';
            return;
        }

        let html = `<div class="kpi-grid" style="margin-bottom:16px">
            <div class="kpi-card"><div class="kpi-value kpi-bad">${data.summary.total_issues || 0}</div><div class="kpi-label">Всего замечаний</div></div>
        </div>`;

        const sections = [
            { key: 'new_without_processing', title: '🆕 Новые без обработки', severity: 'medium' },
            { key: 'without_mandatory_fields', title: '📝 Без обязательных полей', severity: 'medium' },
            { key: 'without_owner', title: '👤 Без исполнителя', severity: 'high' },
            { key: 'deadline_moved_without_comment', title: '📅 Сдвиг дедлайна без комментария', severity: 'medium' },
            { key: 'without_result_description', title: '📄 Нет описания результата', severity: 'high' },
            { key: 'without_time_logged', title: '⏱ Нет учёта времени', severity: 'high' },
            { key: 'stuck_tasks', title: '🕸 Зависшие задачи', severity: 'medium' },
        ];

        for (const s of sections) {
            const items = data[s.key] || [];
            const countClass = s.severity === 'high' ? 'kpi-bad' : (s.severity === 'medium' ? 'kpi-neutral' : '');
            html += `<div class="control-section">
                <div class="control-section-header">
                    <span>${s.title}</span>
                    <span class="control-count ${countClass}">${items.length}</span>
                </div>`;
            if (items.length > 0) {
                html += '<div class="control-section-body"><table><thead><tr><th>ID</th><th>Заголовок</th><th>Ответственный</th>';
                if (s.key === 'stuck_tasks') {
                    html += '<th>Дней в залипшем состоянии</th>';
                } else if (s.key === 'new_without_processing') {
                    html += '<th>Дата создания</th>';
                }
                html += '</tr></thead><tbody>';
                for (const item of items) {
                    html += `<tr>
                        <td>${item.task_id || ''}</td>
                        <td>${escapeHtml(item.title || '')}</td>
                        <td>${escapeHtml(item.responsible_name || item.created_date || '—')}</td>`;
                    if (s.key === 'stuck_tasks') {
                        html += `<td>${item.days_stuck || '—'}</td>`;
                    }
                    html += '</tr>';
                }
                html += '</tbody></table></div>';
            }
            html += '</div>';
        }

        container.innerHTML = html;
    } catch (err) {
        showToast('Ошибка загрузки контроля диспетчера: ' + err.message);
    }
}


// ===================== Weekly Review =====================

async function loadWeeklyReview() {
    try {
        const data = await apiFetch('/api/weekly_review');
        const container = document.getElementById('weeklyContent');

        if (!data || !data.summary) {
            container.innerHTML = '<p style="color:var(--gray-500)">Нет данных</p>';
            return;
        }

        const s = data.summary;
        let html = `<div class="kpi-grid" style="margin-bottom:16px">
            <div class="kpi-card"><div class="kpi-value kpi-bad">${s.total_review_items || 0}</div><div class="kpi-label">Всего позиций</div></div>
            <div class="kpi-card"><div class="kpi-value kpi-neutral">${s.oldest_task_days || 0}</div><div class="kpi-label">Старейшая задача (дн)</div></div>
        </div>`;

        const sections = [
            { key: 'old_tasks', title: '🕰 Старые задачи (>7 дней)', fields: ['created_date', 'days_open'] },
            { key: 'overdue_tasks', title: '⚠️ Просроченные задачи', fields: ['deadline'] },
            { key: 'without_time', title: '⏱ Закрытые без учёта времени', fields: [] },
            { key: 'without_result', title: '📄 Закрытые без описания результата', fields: [] },
            { key: 'deadline_changes_without_comment', title: '📅 Сдвиг дедлайна без комментария', fields: ['changed_at'] },
        ];

        for (const sec of sections) {
            const items = data[sec.key] || [];
            html += `<div class="control-section">
                <div class="control-section-header">
                    <span>${sec.title}</span>
                    <span class="control-count ${items.length > 0 ? 'kpi-bad' : ''}">${items.length}</span>
                </div>`;
            if (items.length > 0) {
                html += '<div class="control-section-body"><table><thead><tr><th>ID</th><th>Заголовок</th><th>Ответственный</th>';
                if (sec.fields.includes('days_open')) html += '<th>Дней открыта</th>';
                else if (sec.fields.includes('created_date')) html += '<th>Создана</th>';
                else if (sec.fields.includes('deadline')) html += '<th>Дедлайн</th>';
                else if (sec.fields.includes('changed_at')) html += '<th>Дата изменения</th>';
                html += '</tr></thead><tbody>';
                for (const item of items) {
                    html += `<tr>
                        <td>${item.task_id || ''}</td>
                        <td>${escapeHtml(item.title || '')}</td>
                        <td>${escapeHtml(item.responsible_name || '—')}</td>`;
                    if (sec.fields.includes('days_open')) html += `<td>${item.days_open || '—'}</td>`;
                    else if (sec.fields.includes('created_date')) html += `<td>${item.created_date ? formatDate(item.created_date) : '—'}</td>`;
                    else if (sec.fields.includes('deadline')) html += `<td>${item.deadline ? formatDate(item.deadline) : '—'}</td>`;
                    else if (sec.fields.includes('changed_at')) html += `<td>${item.changed_at ? formatDate(item.changed_at) : '—'}</td>`;
                    html += '</tr>';
                }
                html += '</tbody></table></div>';
            }
            html += '</div>';
        }

        container.innerHTML = html;
    } catch (err) {
        showToast('Ошибка загрузки еженедельного разбора: ' + err.message);
    }
}


// ===================== Routing Analysis =====================

async function loadRouting() {
    try {
        const data = await apiFetch('/api/routing');
        const sumContainer = document.getElementById('routingSummary');
        const body = document.getElementById('routingBody');

        const summary = data.summary || {};
        sumContainer.innerHTML = `
            <div class="kpi-card"><div class="kpi-value kpi-neutral">${summary.total_tasks_analyzed || 0}</div><div class="kpi-label">Проанализировано задач</div></div>
            <div class="kpi-card"><div class="kpi-value">${summary.avg_routing_count || 0}</div><div class="kpi-label">Среднее число передач</div></div>
            <div class="kpi-card"><div class="kpi-value">${summary.avg_time_to_assignment_min || '—'}</div><div class="kpi-label">Среднее время до назначения (мин)</div></div>
            <div class="kpi-card"><div class="kpi-value ${summary.tasks_with_escalation > 0 ? 'kpi-bad' : ''}">${summary.tasks_with_escalation || 0}</div><div class="kpi-label">Эскалаций</div></div>
        `;

        const tasks = data.by_task || [];
        if (tasks.length === 0) {
            body.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:20px;color:var(--gray-500)">Нет данных</td></tr>';
            return;
        }

        let html = '';
        for (const t of tasks) {
            html += `<tr>
                <td>${t.task_id || ''}</td>
                <td>${escapeHtml(t.title || '')}</td>
                <td>${t.routing_count || 0}</td>
                <td>${t.responsible_changes || 0}</td>
                <td>${t.group_changes || 0}</td>
                <td>${t.priority_changes || 0}</td>
                <td>${t.time_to_assignment_min !== null && t.time_to_assignment_min !== undefined ? t.time_to_assignment_min : '—'}</td>
                <td>${t.escalated ? '⚠️ Да' : '—'}</td>
            </tr>`;
        }
        body.innerHTML = html;
    } catch (err) {
        showToast('Ошибка загрузки маршрутизации: ' + err.message);
    }
}
