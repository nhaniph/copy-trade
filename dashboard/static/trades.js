let currentPage = 1;

const STATUS_LABELS = {
  idea: 'Idea',
  open: 'Open',
  closed_win: 'Win',
  closed_loss: 'Loss',
  cancelled: 'Cancelled',
};

const STATUS_BADGE = {
  idea: 'badge-idea',
  open: 'badge-open',
  closed_win: 'badge-win',
  closed_loss: 'badge-loss',
  cancelled: 'badge-cancelled',
};

async function loadThreads(page = 1) {
  currentPage = page;
  const pair = document.getElementById('filter-pair').value.trim();
  const status = document.getElementById('filter-status').value;

  const params = new URLSearchParams({ page, limit: 10 });
  if (pair) params.append('pair', pair);
  if (status) params.append('status', status);

  const res = await fetch(`/api/trade-threads?${params}`);
  const data = await res.json();

  document.getElementById('total-count').textContent = `${data.total} trades`;

  const container = document.getElementById('threads-container');
  container.innerHTML = '';

  if (!data.threads.length) {
    container.innerHTML = '<div class="empty">No trades found</div>';
    renderPagination(1, 0, 10);
    return;
  }

  for (const thread of data.threads) {
    const trade = thread.trade;
    const signals = thread.signals;

    const openDate = trade.opened_at ? trade.opened_at.slice(0, 10) : '—';
    const closeDate = trade.closed_at ? trade.closed_at.slice(0, 10) : null;
    const pair = trade.pair || 'Unknown';
    const dir = trade.direction;
    const status = trade.status || 'idea';
    const finalR = trade.final_r;

    const statusBadge = `<span class="badge ${STATUS_BADGE[status] || 'badge-idea'}">${STATUS_LABELS[status] || status}</span>`;
    const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '';
    const rDisplay = finalR != null
      ? `<span class="${finalR >= 0 ? 'r-positive' : 'r-negative'}">${finalR >= 0 ? '+' : ''}${finalR}R</span>`
      : '';

    const dateRange = closeDate
      ? `${openDate} → ${closeDate}`
      : `${openDate} → present`;

    // Build signal thread
    let threadHtml = '';
    if (signals.length) {
      threadHtml = `<div class="signal-thread">`;
      for (const sig of signals) {
        const sigDate = sig.created_at ? sig.created_at.slice(0, 16).replace('T', ' ') : '—';
        const sigStatus = sig.status || 'idea';
        const sigBadge = `<span class="badge ${STATUS_BADGE[sigStatus] || 'badge-idea'}" style="font-size:10px">${STATUS_LABELS[sigStatus] || sigStatus}</span>`;
        threadHtml += `
          <div class="signal-entry">
            <div class="signal-entry-meta">
              <span class="signal-entry-date">${sigDate}</span>
              ${sigBadge}
            </div>
            <div class="signal-entry-message">${sig.raw_message || sig.notes || '—'}</div>
          </div>`;
      }
      threadHtml += `</div>`;
    } else {
      threadHtml = `<div class="signal-thread"><div class="empty" style="padding:16px">No messages linked yet</div></div>`;
    }

    const threadId = `thread-${trade.id}`;

    container.innerHTML += `
      <div class="trade-thread-card">
        <div class="trade-thread-header" onclick="toggleThread('${threadId}')">
          <div class="trade-thread-left">
            <span class="trade-thread-pair">${pair}</span>
            <div class="trade-thread-badges">${statusBadge}${dirBadge}</div>
            <span class="trade-thread-dates">${dateRange}</span>
            <span class="trade-thread-count">${signals.length} message${signals.length !== 1 ? 's' : ''}</span>
          </div>
          <div class="trade-thread-right">
            ${rDisplay}
            <span class="thread-toggle" id="toggle-${threadId}">▼</span>
          </div>
        </div>
        <div class="thread-body" id="${threadId}">
          ${threadHtml}
        </div>
      </div>`;
  }

  renderPagination(page, data.total, 10);
}

function toggleThread(id) {
  const body = document.getElementById(id);
  const toggle = document.getElementById(`toggle-${id}`);
  const isOpen = body.style.display !== 'none' && body.style.display !== '';
  body.style.display = isOpen ? 'none' : 'block';
  toggle.textContent = isOpen ? '▼' : '▲';
}

function renderPagination(page, total, limit) {
  const totalPages = Math.ceil(total / limit);
  const container = document.getElementById('pagination');
  container.innerHTML = '';
  if (totalPages <= 1) return;

  const prev = document.createElement('button');
  prev.className = 'page-btn';
  prev.textContent = '← Prev';
  prev.disabled = page <= 1;
  prev.onclick = () => loadThreads(page - 1);
  container.appendChild(prev);

  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  for (let i = start; i <= end; i++) {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (i === page ? ' active' : '');
    btn.textContent = i;
    btn.onclick = () => loadThreads(i);
    container.appendChild(btn);
  }

  const next = document.createElement('button');
  next.className = 'page-btn';
  next.textContent = 'Next →';
  next.disabled = page >= totalPages;
  next.onclick = () => loadThreads(page + 1);
  container.appendChild(next);
}

document.getElementById('filter-pair').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadThreads(1);
});

loadThreads(1);
