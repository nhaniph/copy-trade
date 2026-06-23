let equityChart = null;
let equityMode = 'confirmed';

const CONF_COLOR = {
  high: 'var(--green)',
  medium: '#f59e0b',
  low: 'var(--red)',
};

async function loadAll() {
  await Promise.all([
    loadDateRange(),
    loadStats(),
    loadEquity(equityMode),
    loadTrades(1),
  ]);
}

async function loadDateRange() {
  const res = await fetch('/api/results/date-range');
  const d = await res.json();
  const el = document.getElementById('date-range-badge');
  el.textContent = d.from && d.to ? `${d.from} → ${d.to}` : '';
}

async function loadStats() {
  const res = await fetch('/api/stats?source=analysis');
  const s = await res.json();
  const conf = s.confirmed;
  const est = s.estimated;

  const pct = s.total_count > 0 ? Math.round(s.confirmed_count / s.total_count * 100) : 0;
  document.getElementById('confirmed-coverage').textContent =
    `${s.confirmed_count} of ${s.total_count} trades have explicit R (${pct}%)`;

  function fillSection(prefix, d) {
    document.getElementById(`${prefix}-total-r`).textContent = (d.total_r >= 0 ? '+' : '') + d.total_r + 'R';
    document.getElementById(`${prefix}-total-r`).className = 'stat-value ' + (d.total_r >= 0 ? 'green' : 'red');
    document.getElementById(`${prefix}-win-rate`).textContent = d.win_rate + '%';
    document.getElementById(`${prefix}-expectancy`).textContent = (d.expectancy >= 0 ? '+' : '') + d.expectancy + 'R';
    document.getElementById(`${prefix}-expectancy`).className = 'stat-value ' + (d.expectancy >= 0 ? 'green' : 'red');
    document.getElementById(`${prefix}-sharpe`).textContent = d.sharpe;
    document.getElementById(`${prefix}-profit-factor`).textContent = d.profit_factor + 'x';
    document.getElementById(`${prefix}-avg-win`).textContent = '+' + d.avg_win + 'R';
    document.getElementById(`${prefix}-avg-loss`).textContent = '-' + d.avg_loss + 'R';
    document.getElementById(`${prefix}-total-trades`).textContent = d.total_trades;
  }

  fillSection('conf', conf);
  fillSection('est', est);
}

async function loadEquity(mode) {
  const confirmed_only = mode === 'confirmed';
  const res = await fetch(`/api/equity?source=analysis&confirmed_only=${confirmed_only}`);
  const points = await res.json();

  const ctx = document.getElementById('equity-chart').getContext('2d');
  if (equityChart) equityChart.destroy();
  if (!points.length) { equityChart = null; return; }

  const isPositive = points[points.length - 1].r >= 0;
  const lineColor = isPositive ? '#00c896' : '#ff4d4d';

  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: points.map(p => p.date),
      datasets: [{
        data: points.map(p => p.r),
        borderColor: lineColor,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
        backgroundColor: (ctx) => {
          const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 300);
          g.addColorStop(0, isPositive ? 'rgba(0,200,150,0.15)' : 'rgba(255,77,77,0.15)');
          g.addColorStop(1, 'rgba(0,0,0,0)');
          return g;
        },
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1d27', borderColor: '#2a2d3e', borderWidth: 1,
          titleColor: '#9ca3af', bodyColor: '#e2e8f0',
          callbacks: { label: ctx => (ctx.raw >= 0 ? '+' : '') + ctx.raw + 'R' }
        }
      },
      scales: {
        x: { grid: { color: '#1e2130' }, ticks: { color: '#6b7280', maxTicksLimit: 10, font: { size: 11 } } },
        y: { grid: { color: '#1e2130' }, ticks: { color: '#6b7280', font: { size: 11 }, callback: v => (v >= 0 ? '+' : '') + v + 'R' } }
      }
    }
  });
}

function switchEquity(mode) {
  equityMode = mode;
  document.getElementById('btn-confirmed').classList.toggle('active', mode === 'confirmed');
  document.getElementById('btn-estimated').classList.toggle('active', mode === 'estimated');
  loadEquity(mode);
}

async function loadTrades(page = 1) {
  const res = await fetch(`/api/results/trades?page=${page}&limit=20`);
  const data = await res.json();
  const container = document.getElementById('trades-container');
  container.innerHTML = '';

  if (!data.threads.length) {
    container.innerHTML = '<div class="card" style="padding:32px;text-align:center;color:var(--text-muted)">No closed trades yet</div>';
    return;
  }

  for (const { trade, signals } of data.threads) {
    container.appendChild(buildCard(trade, signals));
  }

  renderPagination(page, data.total, 20);
}

function buildCard(trade, signals) {
  const card = document.createElement('div');
  card.className = 'review-card';

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

  // Sort signals by created_at
  const sorted = [...signals].sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
  const threadHtml = sorted.map(s => {
    const d = (s.created_at || '').slice(0, 16).replace('T', ' ');
    const role = s.notes || '';
    const isExit = ['closed_win', 'closed_loss'].includes(s.status);
    const roleLabel = role === 'entry' ? ' <span style="color:var(--green);font-size:10px;font-weight:600">ENTRY</span>'
      : role === 'exit' ? ' <span style="color:var(--red);font-size:10px;font-weight:600">EXIT</span>'
      : '';
    return `<div class="review-message ${isExit ? 'review-message-close' : ''}">
      <span class="review-message-date">${d}</span>
      <span class="review-message-text">${s.raw_message || '—'}${roleLabel}</span>
    </div>`;
  }).join('');

  const threadId = `thread-${trade.id}`;

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
        <span style="font-size:11px;color:${confColor}">● ${conf}</span>
        <button class="review-toggle" onclick="toggleThread('${threadId}', this)">Show messages ▼</button>
      </div>
    </div>

    ${trade.close_trigger ? `
    <div class="review-trigger">
      <span style="color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Exit trigger</span>
      <span class="review-trigger-text">"${trade.close_trigger}"</span>
    </div>` : `
    <div class="review-trigger" style="border-color:var(--red);background:rgba(255,77,77,0.05)">
      <span style="color:var(--red);font-size:11px">⚠ No exit trigger recorded</span>
    </div>`}

    <div class="review-thread" id="${threadId}" style="display:none;">
      ${threadHtml || '<div style="padding:12px;color:var(--text-muted);font-size:12px">No messages linked</div>'}
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

function renderPagination(page, total, limit) {
  const totalPages = Math.ceil(total / limit);
  const container = document.getElementById('pagination');
  container.innerHTML = '';
  if (totalPages <= 1) return;
  const prev = document.createElement('button');
  prev.className = 'page-btn'; prev.textContent = '← Prev';
  prev.disabled = page <= 1; prev.onclick = () => loadTrades(page - 1);
  container.appendChild(prev);
  for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (i === page ? ' active' : '');
    btn.textContent = i; btn.onclick = () => loadTrades(i);
    container.appendChild(btn);
  }
  const next = document.createElement('button');
  next.className = 'page-btn'; next.textContent = 'Next →';
  next.disabled = page >= totalPages; next.onclick = () => loadTrades(page + 1);
  container.appendChild(next);
}

loadAll();
