let currentPage = 1;
let equityChart = null;

async function loadStats() {
  const res = await fetch('/api/stats');
  const s = await res.json();

  document.getElementById('stat-total-r').textContent = (s.total_r >= 0 ? '+' : '') + s.total_r + 'R';
  document.getElementById('stat-total-r').className = 'stat-value ' + (s.total_r >= 0 ? 'green' : 'red');
  document.getElementById('stat-win-rate').textContent = s.win_rate + '%';
  document.getElementById('stat-expectancy').textContent = (s.expectancy >= 0 ? '+' : '') + s.expectancy + 'R';
  document.getElementById('stat-expectancy').className = 'stat-value ' + (s.expectancy >= 0 ? 'green' : 'red');
  document.getElementById('stat-sharpe').textContent = s.sharpe;
  document.getElementById('stat-profit-factor').textContent = s.profit_factor + 'x';
  document.getElementById('stat-avg-win').textContent = '+' + s.avg_win + 'R';
  document.getElementById('stat-avg-loss').textContent = '-' + s.avg_loss + 'R';
  document.getElementById('stat-total-trades').textContent = s.total_trades;
}

async function loadEquity() {
  const res = await fetch('/api/equity');
  const points = await res.json();

  if (!points.length) return;

  const labels = points.map(p => p.date);
  const data = points.map(p => p.r);

  const ctx = document.getElementById('equity-chart').getContext('2d');

  if (equityChart) equityChart.destroy();

  const isPositive = data[data.length - 1] >= 0;
  const lineColor = isPositive ? '#00c896' : '#ff4d4d';

  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data,
        borderColor: lineColor,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: lineColor,
        fill: true,
        backgroundColor: (ctx) => {
          const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, 300);
          gradient.addColorStop(0, isPositive ? 'rgba(0,200,150,0.15)' : 'rgba(255,77,77,0.15)');
          gradient.addColorStop(1, 'rgba(0,0,0,0)');
          return gradient;
        },
        tension: 0.3,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1d27',
          borderColor: '#2a2d3e',
          borderWidth: 1,
          titleColor: '#9ca3af',
          bodyColor: '#e2e8f0',
          callbacks: {
            label: ctx => (ctx.raw >= 0 ? '+' : '') + ctx.raw + 'R'
          }
        }
      },
      scales: {
        x: {
          grid: { color: '#1e2130' },
          ticks: { color: '#6b7280', maxTicksLimit: 10, font: { size: 11 } },
        },
        y: {
          grid: { color: '#1e2130' },
          ticks: {
            color: '#6b7280',
            font: { size: 11 },
            callback: v => (v >= 0 ? '+' : '') + v + 'R'
          }
        }
      }
    }
  });
}

async function loadTrades(page = 1) {
  currentPage = page;
  const res = await fetch(`/api/trades?page=${page}&limit=50`);
  const data = await res.json();

  const tbody = document.getElementById('trades-tbody');
  tbody.innerHTML = '';

  if (!data.trades.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">No closed trades yet</td></tr>';
    return;
  }

  for (const t of data.trades) {
    const date = (t.opened_at || t.created_at || '').slice(0, 10) || '—';
    const symbol = t.pair || '—';
    const dir = t.direction || '—';
    const dirBadge = dir !== '—'
      ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>`
      : '—';
    const result = t.status === 'closed_win' ? 'WIN' : 'LOSS';
    const resultBadge = `<span class="badge badge-${t.status === 'closed_win' ? 'win' : 'loss'}">${result}</span>`;

    const rDisplay = t.final_r != null
      ? `<span class="${t.final_r >= 0 ? 'r-positive' : 'r-negative'}">${t.final_r >= 0 ? '+' : ''}${t.final_r}R</span>`
      : `<span style="color:var(--text-muted)">—</span>`;

    tbody.innerHTML += `
      <tr>
        <td>${date}</td>
        <td class="symbol">${symbol}</td>
        <td>${dirBadge}</td>
        <td>${t.entry || '—'}</td>
        <td>${t.target || '—'}</td>
        <td>${t.invalidation || '—'}</td>
        <td>${resultBadge}</td>
        <td>${rDisplay}</td>
        <td class="notes">${t.notes || '—'}</td>
      </tr>`;
  }

  renderPagination('pagination', page, data.total, 50, loadTrades);
}

function renderPagination(containerId, page, total, limit, callback) {
  const totalPages = Math.ceil(total / limit);
  const container = document.getElementById(containerId);
  container.innerHTML = '';

  if (totalPages <= 1) return;

  const prev = document.createElement('button');
  prev.className = 'page-btn';
  prev.textContent = '← Prev';
  prev.disabled = page <= 1;
  prev.onclick = () => callback(page - 1);
  container.appendChild(prev);

  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  for (let i = start; i <= end; i++) {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (i === page ? ' active' : '');
    btn.textContent = i;
    btn.onclick = () => callback(i);
    container.appendChild(btn);
  }

  const next = document.createElement('button');
  next.className = 'page-btn';
  next.textContent = 'Next →';
  next.disabled = page >= totalPages;
  next.onclick = () => callback(page + 1);
  container.appendChild(next);
}

const STATUS_BADGE = {
  idea: 'badge-idea', open: 'badge-open',
  closed_win: 'badge-win', closed_loss: 'badge-loss', cancelled: 'badge-cancelled'
};
const STATUS_LABELS = {
  idea: 'Idea', open: 'Open', closed_win: 'Win', closed_loss: 'Loss', cancelled: 'Cancelled'
};

async function loadActiveThreads() {
  const res = await fetch('/api/trade-threads?page=1&limit=3&status=idea');
  const data = await res.json();
  const container = document.getElementById('compact-threads');
  container.innerHTML = '';

  document.getElementById('threads-count').textContent = `${data.total} active`;

  if (!data.threads.length) {
    container.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:20px">No active setups</div>';
    return;
  }

  for (const thread of data.threads) {
    const trade = thread.trade;
    const signals = thread.signals;
    const pair = trade.pair || 'Unknown';
    const dir = trade.direction;
    const status = trade.status || 'idea';
    const openDate = trade.opened_at ? trade.opened_at.slice(0, 10) : '—';
    const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}" style="font-size:10px">${dir}</span>` : '';
    const statusBadge = `<span class="badge ${STATUS_BADGE[status]}" style="font-size:10px">${STATUS_LABELS[status]}</span>`;
    const threadId = `cthread-${trade.id}`;

    let signalsHtml = signals.map(sig => {
      const d = sig.created_at ? sig.created_at.slice(0, 16).replace('T', ' ') : '—';
      return `<div class="compact-signal-entry">
        <div class="compact-signal-date">${d}</div>
        <div class="compact-signal-message">${sig.raw_message || sig.notes || '—'}</div>
      </div>`;
    }).join('');

    container.innerHTML += `
      <div class="compact-thread-card">
        <div class="compact-thread-header" onclick="toggleCompact('${threadId}')">
          <div class="compact-thread-left">
            <span class="compact-thread-pair">${pair}</span>
            ${statusBadge}${dirBadge}
          </div>
          <div class="compact-thread-right">
            <span>${signals.length} msg${signals.length !== 1 ? 's' : ''}</span>
            <span>${openDate}</span>
            <span id="ctoggle-${threadId}">▼</span>
          </div>
        </div>
        <div class="compact-thread-body" id="${threadId}">${signalsHtml || '<div style="padding:10px;font-size:12px;color:var(--text-muted)">No messages</div>'}</div>
      </div>`;
  }
}

function toggleCompact(id) {
  const body = document.getElementById(id);
  const toggle = document.getElementById(`ctoggle-${id}`);
  const isOpen = body.style.display === 'block';
  body.style.display = isOpen ? 'none' : 'block';
  toggle.textContent = isOpen ? '▼' : '▲';
}

// Init
loadActiveThreads();
loadStats();
loadEquity();
loadTrades(1);
