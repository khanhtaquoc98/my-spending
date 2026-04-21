/**
 * MySpending Dashboard - Frontend Logic
 * Uses Lucide Icons (SVG) for all icons
 */

// ─── Constants ─────────────────────────────────────────────────────────────────

const TYPE_CONFIG = {
    bank_transfer: { icon: 'landmark',      label: 'Chuyển khoản', color: '#06b6d4' },
    momo:          { icon: 'smartphone',     label: 'MoMo',         color: '#8b5cf6' },
    shopee:        { icon: 'shopping-bag',   label: 'Shopee',       color: '#f59e0b' },
    tiktok:        { icon: 'music',          label: 'TikTok',       color: '#ec4899' },
    bill:          { icon: 'receipt-text',    label: 'Bill/Hóa đơn', color: '#10b981' },
    unknown:       { icon: 'help-circle',    label: 'Không xác định', color: '#6b7280' },
};

function lucideIcon(name, size = 18, color = 'currentColor') {
    return `<i data-lucide="${name}" style="width:${size}px;height:${size}px;color:${color}"></i>`;
}

function reinitIcons() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

let currentTab = 'overview';
let recordsOffset = 0;
const RECORDS_LIMIT = 20;
let typeChart = null;
let amountChart = null;
let trendChart = null;

// ─── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initUpload();
    initModal();
    loadOverview();
});

// ─── Navigation ────────────────────────────────────────────────────────────────

function initNavigation() {
    document.querySelectorAll('.nav-item[data-tab]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const tab = item.dataset.tab;
            switchTab(tab);
            // Close sidebar on mobile
            document.getElementById('sidebar').classList.remove('open');
            document.getElementById('sidebarOverlay')?.classList.remove('active');
        });
    });

    document.getElementById('refreshBtn').addEventListener('click', () => {
        if (currentTab === 'overview') loadOverview();
        else if (currentTab === 'records') loadRecords(true);
    });

    document.getElementById('filterType').addEventListener('change', () => {
        loadRecords(true);
    });
}

function switchTab(tab) {
    currentTab = tab;

    document.querySelectorAll('.nav-item[data-tab]').forEach(i => i.classList.remove('active'));
    document.querySelector(`[data-tab="${tab}"]`)?.classList.add('active');

    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tab-${tab}`).classList.add('active');

    const titles = { overview: 'Tổng quan', records: 'Lịch sử', upload: 'Upload' };
    document.getElementById('pageTitle').textContent = titles[tab] || tab;

    if (tab === 'overview') loadOverview();
    else if (tab === 'records') loadRecords(true);
}

// ─── Overview ──────────────────────────────────────────────────────────────────

async function loadOverview() {
    try {
        const res = await fetch('/api/statistics');
        const data = await res.json();
        if (data.status !== 'success') return;

        const stats = data.statistics;
        updateStatsCards(stats);
        renderTypeChart(stats);
        renderAmountChart(stats);
        renderTrendChart(stats);
        renderTypeBreakdown(stats);
    } catch (err) {
        console.error('Failed to load statistics:', err);
    }
}

function updateStatsCards(stats) {
    document.getElementById('statTotal').textContent = formatNumber(stats.total_records);
    document.getElementById('statToday').textContent = formatNumber(stats.today_count);
    document.getElementById('statWeek').textContent = formatNumber(stats.week_count);

    const totalAmount = (stats.amount_by_type || []).reduce((s, item) => s + (item.total || 0), 0);
    document.getElementById('statAmount').textContent = formatCurrency(totalAmount);
}

function renderTypeChart(stats) {
    const ctx = document.getElementById('typeChart').getContext('2d');
    const byType = stats.by_type || [];

    if (typeChart) typeChart.destroy();

    if (byType.length === 0) {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        return;
    }

    typeChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: byType.map(t => (TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown).label),
            datasets: [{
                data: byType.map(t => t.count),
                backgroundColor: byType.map(t => (TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown).color + '33'),
                borderColor: byType.map(t => (TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown).color),
                borderWidth: 2,
                hoverOffset: 8,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { color: '#6b7280', font: { family: 'Inter', size: 12 }, padding: 12 }
                }
            },
            cutout: '65%',
        }
    });
}

function renderAmountChart(stats) {
    const ctx = document.getElementById('amountChart').getContext('2d');
    const amountByType = stats.amount_by_type || [];

    if (amountChart) amountChart.destroy();

    if (amountByType.length === 0) {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        return;
    }

    amountChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: amountByType.map(t => (TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown).label),
            datasets: [{
                label: 'Tổng tiền (VND)',
                data: amountByType.map(t => t.total),
                backgroundColor: amountByType.map(t => (TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown).color + '44'),
                borderColor: amountByType.map(t => (TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown).color),
                borderWidth: 2,
                borderRadius: 8,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => formatCurrency(ctx.parsed.y)
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#6b7280', font: { family: 'Inter', size: 11 } },
                    grid: { display: false },
                },
                y: {
                    ticks: {
                        color: '#6b7280',
                        font: { family: 'Inter', size: 11 },
                        callback: (v) => formatCompact(v),
                    },
                    grid: { color: 'rgba(0,0,0,0.04)' },
                }
            }
        }
    });
}

function renderTrendChart(stats) {
    const ctx = document.getElementById('trendChart').getContext('2d');
    const trend = stats.daily_trend || [];

    if (trendChart) trendChart.destroy();

    if (trend.length === 0) {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        return;
    }

    // Group by type
    const types = [...new Set(trend.map(t => t.image_type))];
    const dates = [...new Set(trend.map(t => t.date))].sort();

    const datasets = types.map(type => {
        const cfg = TYPE_CONFIG[type] || TYPE_CONFIG.unknown;
        const dataMap = {};
        trend.filter(t => t.image_type === type).forEach(t => dataMap[t.date] = t.count);
        return {
            label: cfg.label,
            data: dates.map(d => dataMap[d] || 0),
            borderColor: cfg.color,
            backgroundColor: cfg.color + '15',
            fill: true,
            tension: 0.4,
            borderWidth: 2,
            pointRadius: 2,
            pointHoverRadius: 5,
        };
    });

    trendChart = new Chart(ctx, {
        type: 'line',
        data: { labels: dates.map(d => d.slice(5)), datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: '#6b7280', font: { family: 'Inter', size: 11 }, usePointStyle: true }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#9ca3af', font: { family: 'Inter', size: 10 }, maxRotation: 0 },
                    grid: { display: false },
                },
                y: {
                    ticks: { color: '#9ca3af', font: { family: 'Inter', size: 11 }, stepSize: 1 },
                    grid: { color: 'rgba(0,0,0,0.04)' },
                    beginAtZero: true,
                }
            },
            interaction: { mode: 'index', intersect: false },
        }
    });
}

function renderTypeBreakdown(stats) {
    const container = document.getElementById('typeBreakdown');
    const byType = stats.by_type || [];

    if (byType.length === 0) {
        container.innerHTML = `<div class="empty-state">${lucideIcon('inbox', 48, '#9ca3af')}<p>Chưa có dữ liệu</p></div>`;
        reinitIcons();
        return;
    }

    container.innerHTML = byType.map(t => {
        const cfg = TYPE_CONFIG[t.image_type] || TYPE_CONFIG.unknown;
        return `
            <div class="type-card">
                <span class="type-card-icon">${lucideIcon(cfg.icon, 32, cfg.color)}</span>
                <div class="type-card-name">${cfg.label}</div>
                <div class="type-card-count" style="color:${cfg.color}">${t.count}</div>
                ${t.total_amount > 0 ? `<div class="type-card-amount">${formatCurrency(t.total_amount)}</div>` : ''}
            </div>
        `;
    }).join('');

    reinitIcons();
}

// ─── Records ───────────────────────────────────────────────────────────────────

async function loadRecords(reset = false) {
    if (reset) recordsOffset = 0;

    const type = document.getElementById('filterType').value;
    const params = new URLSearchParams({ limit: RECORDS_LIMIT, offset: recordsOffset });
    if (type && type !== 'all') params.set('type', type);

    try {
        const res = await fetch(`/api/records?${params}`);
        const data = await res.json();

        if (data.status !== 'success') return;

        const list = document.getElementById('recordsList');
        if (reset) list.innerHTML = '';

        if (data.records.length === 0 && reset) {
            list.innerHTML = `<div class="empty-state">${lucideIcon('inbox', 48, '#9ca3af')}<p>Không có records nào</p></div>`;
            reinitIcons();
        }

        data.records.forEach(record => {
            list.appendChild(createRecordCard(record));
        });

        reinitIcons();

        document.getElementById('recordsCount').textContent = `${list.children.length} kết quả`;

        const loadMoreBtn = document.getElementById('loadMoreBtn');
        loadMoreBtn.style.display = data.records.length >= RECORDS_LIMIT ? 'block' : 'none';
        loadMoreBtn.onclick = () => {
            recordsOffset += RECORDS_LIMIT;
            loadRecords(false);
        };
    } catch (err) {
        console.error('Failed to load records:', err);
    }
}

function createRecordCard(record) {
    const cfg = TYPE_CONFIG[record.image_type] || TYPE_CONFIG.unknown;
    const div = document.createElement('div');
    div.className = 'record-card';
    div.onclick = () => openRecordModal(record.id);

    const confClass = record.confidence > 50 ? 'conf-high' : record.confidence > 25 ? 'conf-medium' : 'conf-low';
    const textPreview = (record.raw_text || '').substring(0, 80);
    const date = record.created_at ? new Date(record.created_at).toLocaleString('vi-VN') : '';

    div.innerHTML = `
        <div class="record-type-badge badge-${record.image_type}">${lucideIcon(cfg.icon, 20, cfg.color)}</div>
        <div class="record-info">
            <div class="record-info-top">
                <span class="record-type-label" style="color:${cfg.color}">${cfg.label}</span>
                <span class="record-confidence ${confClass}">${Math.round(record.confidence)}%</span>
            </div>
            <div class="record-text-preview">${escapeHtml(textPreview)}${textPreview.length >= 80 ? '...' : ''}</div>
        </div>
        <div class="record-meta">
            ${record.amount ? `<span class="record-amount">${formatCurrency(record.amount)}</span>` : ''}
            <span class="record-date">${date}</span>
        </div>
    `;

    return div;
}

// ─── Modal ─────────────────────────────────────────────────────────────────────

function initModal() {
    document.getElementById('modalClose').addEventListener('click', closeModal);
    document.getElementById('modalOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('active');
}

async function openRecordModal(recordId) {
    try {
        const res = await fetch(`/api/records/${recordId}`);
        const data = await res.json();
        if (data.status !== 'success') return;

        const record = data.record;
        const cfg = TYPE_CONFIG[record.image_type] || TYPE_CONFIG.unknown;

        document.getElementById('modalTitle').innerHTML = `${lucideIcon(cfg.icon, 18, cfg.color)} ${cfg.label} - #${record.id}`;

        const body = document.getElementById('modalBody');
        const date = record.created_at ? new Date(record.created_at).toLocaleString('vi-VN') : 'N/A';

        let detailsHtml = '';
        const fields = [
            ['Loại', cfg.label],
            ['Độ tin cậy', `${Math.round(record.confidence)}%`],
            ['Số tiền', record.amount ? formatCurrency(record.amount) : 'N/A'],
            ['Người gửi', record.sender || 'N/A'],
            ['Người nhận', record.receiver || 'N/A'],
            ['Mã giao dịch', record.transaction_id || 'N/A'],
            ['Mã đơn hàng', record.order_id || 'N/A'],
            ['Platform', record.platform || 'N/A'],
            ['Thời gian', date],
            ['Ghi chú', record.note || '—'],
        ];

        fields.forEach(([key, val]) => {
            detailsHtml += `<div class="modal-detail-row"><span class="modal-detail-key">${key}</span><span class="modal-detail-value">${escapeHtml(val)}</span></div>`;
        });

        body.innerHTML = `
            ${detailsHtml}
            ${record.raw_text ? `<h4 style="margin-top:1rem;font-size:0.85rem;color:var(--text-secondary);">OCR Text:</h4><div class="modal-raw-text">${escapeHtml(record.raw_text)}</div>` : ''}
            <div class="modal-actions">
                <button class="btn btn-danger" onclick="deleteRecordAction(${record.id})">${lucideIcon('trash-2', 14)} Xóa</button>
            </div>
        `;

        document.getElementById('modalOverlay').classList.add('active');
        reinitIcons();
    } catch (err) {
        console.error('Failed to load record:', err);
    }
}

async function deleteRecordAction(recordId) {
    if (!confirm('Bạn chắc chắn muốn xóa record này?')) return;
    try {
        await fetch(`/api/records/${recordId}`, { method: 'DELETE' });
        closeModal();
        loadRecords(true);
        if (currentTab === 'overview') loadOverview();
    } catch (err) {
        console.error('Failed to delete record:', err);
    }
}

// ─── Upload ────────────────────────────────────────────────────────────────────

function initUpload() {
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');

    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        handleFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener('change', () => {
        handleFiles(fileInput.files);
        fileInput.value = '';
    });
}

async function handleFiles(files) {
    const results = document.getElementById('uploadResults');
    const note = document.getElementById('uploadNote').value;

    for (const file of files) {
        if (!file.type.startsWith('image/')) continue;

        const card = document.createElement('div');
        card.className = 'upload-result-card';
        card.innerHTML = `
            <div class="upload-result-header">
                <span class="upload-result-type">${lucideIcon('loader', 20, '#6366f1')}</span>
                <span class="upload-result-label">Đang xử lý ${escapeHtml(file.name)}...</span>
                <span class="upload-result-conf"><span class="loading-spinner"></span></span>
            </div>
        `;
        results.prepend(card);
        reinitIcons();

        const formData = new FormData();
        formData.append('image', file);
        if (note) formData.append('note', note);

        try {
            const res = await fetch('/api/webhook', { method: 'POST', body: formData });
            const data = await res.json();

            if (data.status === 'success') {
                const cfg = TYPE_CONFIG[data.classification.type] || TYPE_CONFIG.unknown;
                const ext = data.extracted_data || {};

                let dataGridHtml = '';
                const items = [
                    ['Loại', cfg.label],
                    ['Độ tin cậy', `${Math.round(data.classification.confidence)}%`],
                    ['Số tiền', ext.amount ? formatCurrency(ext.amount) : 'N/A'],
                    ['Platform', ext.platform || 'N/A'],
                ];
                if (ext.transaction_id) items.push(['Mã GD', ext.transaction_id]);
                if (ext.order_id) items.push(['Mã đơn', ext.order_id]);
                if (ext.sender) items.push(['Người gửi', ext.sender]);
                if (ext.receiver) items.push(['Người nhận', ext.receiver]);

                dataGridHtml = items.map(([k, v]) => `
                    <div class="result-data-item">
                        <div class="result-data-key">${k}</div>
                        <div class="result-data-value">${escapeHtml(v)}</div>
                    </div>
                `).join('');

                card.innerHTML = `
                    <div class="upload-result-header">
                        <span class="upload-result-type">${lucideIcon(cfg.icon, 24, cfg.color)}</span>
                        <span class="upload-result-label" style="color:${cfg.color}">${cfg.label}</span>
                        <span class="upload-result-conf">OCR: ${data.ocr.confidence}%</span>
                    </div>
                    <div class="result-data-grid">${dataGridHtml}</div>
                    <div class="upload-actions" style="display:flex;gap:0.5rem;margin-top:1rem;">
                        <button class="btn btn-primary" style="flex:1" onclick="confirmUpload(this, ${JSON.stringify(data.record_data).replace(/"/g, '&quot;')})">${lucideIcon('check', 14)} Lưu lại</button>
                        <button class="btn btn-secondary" style="flex:1" onclick="this.closest('.upload-result-card').remove()">${lucideIcon('rotate-ccw', 14)} Bỏ qua</button>
                    </div>
                `;
                reinitIcons();
            } else {
                card.innerHTML = `
                    <div class="upload-result-header">
                        <span class="upload-result-type">${lucideIcon('alert-circle', 20, '#ef4444')}</span>
                        <span class="upload-result-label" style="color:#ef4444">Lỗi: ${escapeHtml(data.error || 'Unknown error')}</span>
                    </div>
                `;
                reinitIcons();
            }
        } catch (err) {
            card.innerHTML = `
                <div class="upload-result-header">
                    <span class="upload-result-type">${lucideIcon('alert-circle', 20, '#ef4444')}</span>
                    <span class="upload-result-label" style="color:#ef4444">Lỗi: ${escapeHtml(err.message)}</span>
                </div>
            `;
            reinitIcons();
        }
    }
}

async function confirmUpload(btn, recordData) {
    btn.disabled = true;
    btn.innerHTML = `${lucideIcon('loader', 14)} Đang lưu...`;
    reinitIcons();

    try {
        const res = await fetch('/api/webhook/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(recordData),
        });
        const data = await res.json();

        if (data.status === 'success') {
            const card = btn.closest('.upload-result-card');
            const actions = card.querySelector('.upload-actions');
            if (actions) {
                actions.innerHTML = `<div style="text-align:center;color:#10b981;padding:0.5rem;font-weight:500;">${lucideIcon('check-circle', 16, '#10b981')} Đã lưu - Record #${data.record?.id || ''}</div>`;
                reinitIcons();
            }
        }
    } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Lỗi - Thử lại';
    }
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function formatNumber(n) {
    return (n || 0).toLocaleString('vi-VN');
}

function formatCurrency(n) {
    if (!n) return '0đ';
    return Math.round(n).toLocaleString('vi-VN') + 'đ';
}

function formatCompact(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
