let currentRun = null;
let currentPage = 1;

const RUN_LABELS = {
  'v1-estimated': 'v1 — Estimated',
  'v2-confirmed': 'v2 — Confirmed',
  'v3-reviewed': 'v3 — Reviewed',
  'v3-stateful': 'v3 — Stateful',
};

const CONF_COLOR = {
  high: 'var(--green)',
  medium: '#f59e0b',
  low: 'var(--red)',
};

async function loadRuns() {
  const res = await fetch('/api/backtest/runs');
  const runs = await res.json();
  const select = document.getElementById('run-select');
  select.innerHTML = '';

  if (!runs.length) {
    select.innerHTML = '<option value="">No runs found</option>';
    return;
  }

  for (const run of runs) {
    const opt = document.createElement('option');
    opt.value = run;
    opt.textContent = RUN_LABELS[run] || run;
    select.appendChild(opt);
  }

  select.onchange = () => { currentPage = 1; loadQueue(select.value, 1); };
  currentRun = runs[runs.length - 1];
  select.value = currentRun;
  loadQueue(currentRun, 1);
}

async function loadQueue(run, page = 1) {
  currentRun = run;
  currentPage = page;

  const res = await fetch(`/api/review/queue?run=${encodeURIComponent(run)}&page=${page}&limit=20`);
  const data = await res.json();

  // Progress badge
  const pct = data.total_closed > 0
    ? Math.round(data.total_reviewed / data.total_closed * 100)
    : 0;
  document.getElementById('progress-badge').textContent =
    `${data.total_reviewed} / ${data.total_closed} reviewed (${pct}%)`;

  const container = document.getElementById('queue-container');
  container.innerHTML = '';

  if (!data.threads.length) {
    container.innerHTML = `
      <div class="card" style="text-align:center;padding:48px;color:var(--text-muted);">
        <div style="font-size:32px;margin-bottom:12px">✅</div>
        <div style="font-size:16px;font-weight:600;color:var(--text)">Queue is empty</div>
        <div style="margin-top:8px;font-size:13px">All closed trades have been reviewed.</div>
      </div>`;
    document.getElementById('pagination').innerHTML = '';
    return;
  }

  for (const { trade, signals } of data.threads) {
    container.appendChild(buildCard(trade, signals));
  }

  renderPagination(page, data.total_pending, 20);
}

function buildCard(trade, signals) {
  const card = document.createElement('div');
  card.className = 'review-card';
  card.id = `card-${trade.id}`;

  const conf = trade.confidence || 'high';
  const confColor = CONF_COLOR[conf] || 'var(--text-muted)';
  const isWin = trade.status === 'closed_win';
  const date = (trade.opened_at || '').slice(0, 10);
  const dir = trade.direction || '';
  const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '';
  const resultBadge = `<span class="badge badge-${isWin ? 'win' : 'loss'}">${isWin ? 'WIN' : 'LOSS'}</span>`;
  const rDisplay = trade.final_r != null
    ? `<span class="${trade.final_r >= 0 ? 'r-positive' : 'r-negative'}">${trade.final_r >= 0 ? '+' : ''}${trade.final_r}R</span>`
    : '<span style="color:var(--text-muted)">no R</span>';

  const threadHtml = signals.map(s => {
    const d = (s.created_at || '').slice(0, 16).replace('T', ' ');
    const msgStatus = s.status || '';
    const isClose = ['closed_win', 'closed_loss'].includes(msgStatus);
    return `<div class="review-message ${isClose ? 'review-message-close' : ''}">
      <span class="review-message-date">${d}</span>
      <span class="review-message-text">${s.raw_message || s.notes || '—'}</span>
    </div>`;
  }).join('');

  card.innerHTML = `
    <div class="review-card-header">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span class="symbol" style="font-size:16px">${trade.pair || '?'}</span>
        ${dirBadge}
        ${resultBadge}
        ${rDisplay}
        <span style="font-size:11px;color:var(--text-muted)">${date}</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span class="review-confidence" style="color:${confColor}">● ${conf}</span>
        <button class="review-toggle" onclick="toggleThread('thread-${trade.id}', this)">Show messages ▼</button>
      </div>
    </div>

    ${trade.close_trigger ? `
    <div class="review-trigger">
      <span style="color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Exit trigger</span>
      <span class="review-trigger-text">"${trade.close_trigger}"</span>
    </div>` : `
    <div class="review-trigger" style="border-color:var(--red);background:rgba(255,77,77,0.05)">
      <span style="color:var(--red);font-size:11px">⚠ No close trigger recorded — check messages carefully</span>
    </div>`}

    <div class="review-thread" id="thread-${trade.id}" style="display:none;">
      ${threadHtml || '<div style="padding:12px;color:var(--text-muted);font-size:12px">No messages linked</div>'}
    </div>

    <div class="review-actions">
      <button class="review-btn review-btn-approve" onclick="approve('${trade.id}')">✓ Approve</button>
      <button class="review-btn review-btn-fix" onclick="openFixR('${trade.id}', ${trade.final_r ?? 'null'})">✎ Fix R</button>
      <button class="review-btn review-btn-nullify" onclick="nullifyR('${trade.id}')">∅ Nullify R</button>
      <button class="review-btn review-btn-reopen" onclick="reopen('${trade.id}')">↩ Reopen</button>
      <button class="review-btn review-btn-cancel" onclick="cancelTrade('${trade.id}')">✕ Cancel</button>
    </div>

    <div class="review-fix-form" id="fix-form-${trade.id}" style="display:none;">
      <input type="number" step="0.1" id="fix-input-${trade.id}" class="filter-input"
        placeholder="Enter correct R (e.g. 2.5 or -1)" style="width:200px" />
      <button class="review-btn review-btn-approve" onclick="submitFix('${trade.id}')">Save</button>
      <button class="review-btn" onclick="document.getElementById('fix-form-${trade.id}').style.display='none'">Cancel</button>
    </div>
  `;

  return card;
}

function toggleThread(id, btn) {
  const el = document.getElementById(id);
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  btn.textContent = open ? 'Show messages ▼' : 'Hide messages ▲';
}

function openFixR(tradeId, currentR) {
  const form = document.getElementById(`fix-form-${tradeId}`);
  const input = document.getElementById(`fix-input-${tradeId}`);
  form.style.display = form.style.display === 'none' ? 'flex' : 'none';
  if (currentR !== null) input.value = currentR;
  input.focus();
}

async function approve(tradeId) {
  await fetch(`/api/review/approve/${tradeId}`, { method: 'POST' });
  removeCard(tradeId);
}

async function nullifyR(tradeId) {
  await fetch(`/api/review/nullify/${tradeId}`, { method: 'POST' });
  removeCard(tradeId);
}

async function reopen(tradeId) {
  if (!confirm('Mark this trade as still open (phantom close)?')) return;
  await fetch(`/api/review/reopen/${tradeId}`, { method: 'POST' });
  removeCard(tradeId);
}

async function cancelTrade(tradeId) {
  if (!confirm('Mark this trade as cancelled (never entered)?')) return;
  await fetch(`/api/review/cancel/${tradeId}`, { method: 'POST' });
  removeCard(tradeId);
}

async function submitFix(tradeId) {
  const input = document.getElementById(`fix-input-${tradeId}`);
  const val = parseFloat(input.value);
  if (isNaN(val)) { input.style.borderColor = 'var(--red)'; return; }
  await fetch(`/api/review/fix/${tradeId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ final_r: val }),
  });
  removeCard(tradeId);
}

function removeCard(tradeId) {
  const card = document.getElementById(`card-${tradeId}`);
  card.style.transition = 'opacity 0.2s';
  card.style.opacity = '0';
  setTimeout(() => {
    card.remove();
    // Reload if queue is now empty on this page
    const remaining = document.querySelectorAll('.review-card');
    if (!remaining.length) loadQueue(currentRun, currentPage > 1 ? currentPage - 1 : 1);
    else {
      // Just update progress badge
      const badge = document.getElementById('progress-badge');
      const match = badge.textContent.match(/(\d+) \/ (\d+)/);
      if (match) {
        const reviewed = parseInt(match[1]) + 1;
        const total = parseInt(match[2]);
        const pct = Math.round(reviewed / total * 100);
        badge.textContent = `${reviewed} / ${total} reviewed (${pct}%)`;
      }
    }
  }, 200);
}

function renderPagination(page, total, limit) {
  const totalPages = Math.ceil(total / limit);
  const container = document.getElementById('pagination');
  container.innerHTML = '';
  if (totalPages <= 1) return;
  const prev = document.createElement('button');
  prev.className = 'page-btn'; prev.textContent = '← Prev';
  prev.disabled = page <= 1; prev.onclick = () => loadQueue(currentRun, page - 1);
  container.appendChild(prev);
  for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (i === page ? ' active' : '');
    btn.textContent = i; btn.onclick = () => loadQueue(currentRun, i);
    container.appendChild(btn);
  }
  const next = document.createElement('button');
  next.className = 'page-btn'; next.textContent = 'Next →';
  next.disabled = page >= totalPages; next.onclick = () => loadQueue(currentRun, page + 1);
  container.appendChild(next);
}

loadRuns();
