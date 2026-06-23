let equityChart = null;

async function loadActiveSetups() {
  const res = await fetch('/api/trade-threads?source=live&status=idea&limit=5');
  const data = await res.json();
  const openRes = await fetch('/api/trade-threads?source=live&status=open&limit=5');
  const openData = await openRes.json();

  const threads = [...(openData.threads || []), ...(data.threads || [])];
  const container = document.getElementById('active-threads');
  const countEl = document.getElementById('active-count');
  countEl.textContent = threads.length;

  if (!threads.length) {
    container.innerHTML = '<div style="padding:20px;color:var(--text-muted);text-align:center;">No active setups</div>';
    return;
  }

  container.innerHTML = '';
  for (const { trade, signals } of threads) {
    const pair = trade.pair || '?';
    const dir = trade.direction || '';
    const status = trade.status || 'idea';
    const statusLabel = status === 'open' ? 'OPEN' : 'IDEA';
    const statusClass = status === 'open' ? 'badge-open' : 'badge-idea';
    const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '';

    const lastMsg = signals.length ? signals[signals.length - 1] : null;
    const preview = lastMsg ? lastMsg.raw_message.slice(0, 100) + (lastMsg.raw_message.length > 100 ? '…' : '') : '';
    const date = (trade.opened_at || '').slice(0, 10);

    const card = document.createElement('div');
    card.className = 'compact-thread-card';
    card.innerHTML = `
      <div class="compact-thread-header">
        <span class="symbol">${pair}</span>
        ${dirBadge}
        <span class="badge ${statusClass}">${statusLabel}</span>
        <span style="margin-left:auto;font-size:11px;color:var(--text-muted)">${date}</span>
      </div>
      <div style="font-size:12px;color:var(--text-muted);padding:8px 0 4px">${preview}</div>
      <div style="font-size:11px;color:var(--text-muted)">${signals.length} message${signals.length !== 1 ? 's' : ''}</div>
    `;
    container.appendChild(card);
  }
}

async function loadStats() {
  const res = await fetch('/api/stats?source=live');
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
  const res = await fetch('/api/equity?source=live');
  const points = await res.json();
  if (!points.length) return;

  const ctx = document.getElementById('equity-chart').getContext('2d');
  if (equityChart) equityChart.destroy();

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

async function loadTrades(page = 1) {
  const res = await fetch(`/api/trades?source=live&page=${page}&limit=50`);
  const data = await res.json();
  const tbody = document.getElementById('trades-tbody');
  tbody.innerHTML = '';

  if (!data.trades.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No closed trades yet</td></tr>';
    return;
  }

  for (const t of data.trades) {
    const date = (t.opened_at || '').slice(0, 10);
    const dir = t.direction;
    const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '—';
    const result = t.status === 'closed_win' ? 'WIN' : 'LOSS';
    const resultBadge = `<span class="badge badge-${t.status === 'closed_win' ? 'win' : 'loss'}">${result}</span>`;
    const r = t.final_r != null ? t.final_r : (t.status === 'closed_win' ? 1 : -1);
    const rDisplay = `<span class="${r >= 0 ? 'r-positive' : 'r-negative'}">${r >= 0 ? '+' : ''}${r}R</span>`;
    tbody.innerHTML += `<tr>
      <td>${date}</td>
      <td class="symbol">${t.pair || '—'}</td>
      <td>${dirBadge}</td>
      <td>${resultBadge}</td>
      <td>${rDisplay}</td>
      <td class="notes">${t.notes || '—'}</td>
    </tr>`;
  }

  renderPagination(page, data.total, 50);
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

loadActiveSetups();
loadStats();
loadEquity();
loadTrades(1);
