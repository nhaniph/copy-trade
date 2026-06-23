let currentPage = 1;

const STATUS_LABELS = {
  idea: 'Idea', open: 'Open', closed_win: 'Win',
  closed_loss: 'Loss', cancelled: 'Cancelled', commentary: 'Commentary'
};
const STATUS_BADGE = {
  idea: 'badge-idea', open: 'badge-open', closed_win: 'badge-win',
  closed_loss: 'badge-loss', cancelled: 'badge-cancelled', commentary: 'badge-cancelled'
};

async function loadIdeas(page = 1) {
  currentPage = page;
  const pair = document.getElementById('filter-pair').value.trim();
  const status = document.getElementById('filter-status').value;

  const params = new URLSearchParams({ page, limit: 25 });
  if (pair) params.append('pair', pair);
  if (status) params.append('status', status);

  const res = await fetch(`/api/trade-threads?${params}`);
  const data = await res.json();

  document.getElementById('total-count').textContent = `${data.total} threads`;

  const grid = document.getElementById('ideas-grid');
  grid.innerHTML = '';

  if (!data.threads.length) {
    grid.innerHTML = '<div class="empty" style="grid-column:1/-1">No ideas found</div>';
    renderPagination(1, 0, 25);
    return;
  }

  for (const thread of data.threads) {
    const trade = thread.trade;
    const signals = thread.signals;

    const pair = trade.pair || 'Unknown';
    const dir = trade.direction;
    const status = trade.status || 'idea';
    const openDate = trade.opened_at ? trade.opened_at.slice(0, 10) : '—';
    const closeDate = trade.closed_at ? trade.closed_at.slice(0, 10) : null;
    const finalR = trade.final_r;

    const statusBadge = `<span class="badge ${STATUS_BADGE[status] || 'badge-idea'}">${STATUS_LABELS[status] || status}</span>`;
    const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '';
    const rDisplay = finalR != null
      ? `<span class="${finalR >= 0 ? 'r-positive' : 'r-negative'}" style="font-size:13px;font-weight:700">${finalR >= 0 ? '+' : ''}${finalR}R</span>`
      : '';
    const dateDisplay = closeDate ? `${openDate} → ${closeDate}` : openDate;
    const threadId = `idea-thread-${trade.id}`;

    const signalsHtml = signals.map(sig => {
      const d = sig.created_at ? sig.created_at.slice(0, 16).replace('T', ' ') : '—';
      const sigStatus = sig.status || 'idea';
      const sigBadge = `<span class="badge ${STATUS_BADGE[sigStatus] || 'badge-idea'}" style="font-size:10px">${STATUS_LABELS[sigStatus] || sigStatus}</span>`;
      return `<div class="compact-signal-entry">
        <div class="compact-signal-date" style="display:flex;align-items:center;gap:8px">${d} ${sigBadge}</div>
        <div class="compact-signal-message">${sig.raw_message || sig.notes || '—'}</div>
      </div>`;
    }).join('');

    grid.innerHTML += `
      <div class="compact-thread-card" style="width:100%">
        <div class="compact-thread-header" onclick="toggleIdea('${threadId}')">
          <div class="compact-thread-left">
            <span class="compact-thread-pair">${pair}</span>
            ${statusBadge}
            ${dirBadge}
            ${rDisplay}
          </div>
          <div class="compact-thread-right">
            <span>${dateDisplay}</span>
            <span>${signals.length} msg${signals.length !== 1 ? 's' : ''}</span>
            <span id="itoggle-${threadId}">▼</span>
          </div>
        </div>
        <div class="compact-thread-body" id="${threadId}">
          ${signalsHtml || '<div style="padding:10px;font-size:12px;color:var(--text-muted)">No messages</div>'}
        </div>
      </div>`;
  }

  renderPagination(page, data.total, 25);
}

function toggleIdea(id) {
  const body = document.getElementById(id);
  const toggle = document.getElementById(`itoggle-${id}`);
  const isOpen = body.style.display === 'block';
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
  prev.onclick = () => loadIdeas(page - 1);
  container.appendChild(prev);

  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  for (let i = start; i <= end; i++) {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (i === page ? ' active' : '');
    btn.textContent = i;
    btn.onclick = () => loadIdeas(i);
    container.appendChild(btn);
  }

  const next = document.createElement('button');
  next.className = 'page-btn';
  next.textContent = 'Next →';
  next.disabled = page >= totalPages;
  next.onclick = () => loadIdeas(page + 1);
  container.appendChild(next);
}

document.getElementById('filter-pair').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadIdeas(1);
});

// Update ideas-grid to be a single column list instead of card grid
document.getElementById('ideas-grid').style.display = 'flex';
document.getElementById('ideas-grid').style.flexDirection = 'column';
document.getElementById('ideas-grid').style.gap = '10px';

loadIdeas(1);
