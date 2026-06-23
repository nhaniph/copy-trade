let equityChart = null;
let currentRun = null;
let equityMode = 'confirmed';

const RUN_LABELS = {
  'v1-estimated': 'v1 — Estimated (1R defaults)',
  'v2-confirmed': 'v2 — Confirmed (explicit exits only)',
  'v3-reviewed': 'v3 — Reviewed (manual corrections)',
  'v3-stateful': 'v3 — Stateful (open trade context)',
};

const RUN_DISCLAIMERS = {
  'v1-estimated': '⚠️ v1: R values default to 1R where not explicitly stated. Stats are floor estimates.',
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

  select.onchange = () => loadAll(select.value);
  currentRun = runs[runs.length - 1];
  select.value = currentRun;
  loadAll(currentRun);
}

async function createSnapshot() {
  const btn = document.getElementById('snapshot-btn');
  btn.textContent = 'Creating…';
  btn.disabled = true;
  try {
    const res = await fetch(`/api/backtest/snapshot?source_run=${encodeURIComponent(currentRun)}&target_run=v3-reviewed`, { method: 'POST' });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Failed');
    alert(`✅ v3-reviewed created with ${d.copied} trades. Switching now.`);
    await loadRuns();
    document.getElementById('run-select').value = 'v3-reviewed';
    loadAll('v3-reviewed');
  } catch (e) {
    alert('Error: ' + e.message);
    btn.textContent = '📸 Snapshot → v3';
    btn.disabled = false;
  }
}

async function loadAll(run) {
  currentRun = run;

  // Show snapshot button only for v2, and only if v3 doesn't exist yet
  const snapshotBtn = document.getElementById('snapshot-btn');
  const runsRes = await fetch('/api/backtest/runs');
  const runs = await runsRes.json();
  snapshotBtn.style.display = (run === 'v2-confirmed' && !runs.includes('v3-reviewed')) ? '' : 'none';

  const disclaimer = document.getElementById('disclaimer-banner');
  const msg = RUN_DISCLAIMERS[run];
  if (msg) {
    disclaimer.textContent = msg;
    disclaimer.style.display = '';
  } else {
    disclaimer.style.display = 'none';
  }

  await Promise.all([
    loadDateRange(run),
    loadStats(run),
    loadEquity(run, equityMode),
    loadTrades(run, 1),
    loadReviewProgress(run),
  ]);
}

async function loadDateRange(run) {
  const res = await fetch(`/api/backtest/date-range?run=${encodeURIComponent(run)}`);
  const d = await res.json();
  const el = document.getElementById('date-range-badge');
  el.textContent = d.from && d.to ? `${d.from} → ${d.to}` : '';
}

async function loadReviewProgress(run) {
  const res = await fetch(`/api/review/queue?run=${encodeURIComponent(run)}&page=1&limit=1`);
  const d = await res.json();
  const total = d.total_closed || 0;
  const reviewed = d.total_reviewed || 0;
  if (!total) return;

  const pct = Math.round(reviewed / total * 100);
  const wrap = document.getElementById('review-progress');
  wrap.style.display = '';
  document.getElementById('review-progress-bar').style.width = pct + '%';
  document.getElementById('review-progress-label').textContent =
    `${reviewed} of ${total} trades manually reviewed (${pct}%) — stats update in real time as you review`;
}

async function loadStats(run) {
  const res = await fetch(`/api/stats?source=backfill&run=${encodeURIComponent(run)}`);
  const s = await res.json();

  const conf = s.confirmed;
  const est = s.estimated;

  // Coverage note
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

async function loadEquity(run, mode) {
  const confirmed_only = mode === 'confirmed';
  const res = await fetch(`/api/equity?source=backfill&run=${encodeURIComponent(run)}&confirmed_only=${confirmed_only}`);
  const points = await res.json();

  const ctx = document.getElementById('equity-chart').getContext('2d');
  if (equityChart) equityChart.destroy();

  if (!points.length) {
    equityChart = null;
    return;
  }

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
  loadEquity(currentRun, mode);
}

async function loadTrades(run, page = 1) {
  const res = await fetch(`/api/trades?source=backfill&run=${encodeURIComponent(run)}&page=${page}&limit=50`);
  const data = await res.json();
  const tbody = document.getElementById('trades-tbody');
  tbody.innerHTML = '';

  if (!data.trades.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">No closed trades</td></tr>';
    return;
  }

  for (const t of data.trades) {
    const date = (t.opened_at || '').slice(0, 10);
    const dir = t.direction;
    const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '—';
    const result = t.status === 'closed_win' ? 'WIN' : 'LOSS';
    const resultBadge = `<span class="badge badge-${t.status === 'closed_win' ? 'win' : 'loss'}">${result}</span>`;
    const r = t.final_r != null
      ? `<span class="${t.final_r >= 0 ? 'r-positive' : 'r-negative'}">${t.final_r >= 0 ? '+' : ''}${t.final_r}R</span>`
      : `<span style="color:var(--text-muted)">—</span>`;
    tbody.innerHTML += `<tr>
      <td>${date}</td>
      <td class="symbol">${t.pair || '—'}</td>
      <td>${dirBadge}</td>
      <td>${resultBadge}</td>
      <td>${r}</td>
      <td class="notes">${t.notes || '—'}</td>
    </tr>`;
  }

  renderPagination(run, page, data.total, 50);
}

function renderPagination(run, page, total, limit) {
  const totalPages = Math.ceil(total / limit);
  const container = document.getElementById('pagination');
  container.innerHTML = '';
  if (totalPages <= 1) return;
  const prev = document.createElement('button');
  prev.className = 'page-btn'; prev.textContent = '← Prev';
  prev.disabled = page <= 1; prev.onclick = () => loadTrades(run, page - 1);
  container.appendChild(prev);
  for (let i = Math.max(1, page - 2); i <= Math.min(totalPages, page + 2); i++) {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (i === page ? ' active' : '');
    btn.textContent = i; btn.onclick = () => loadTrades(run, i);
    container.appendChild(btn);
  }
  const next = document.createElement('button');
  next.className = 'page-btn'; next.textContent = 'Next →';
  next.disabled = page >= totalPages; next.onclick = () => loadTrades(run, page + 1);
  container.appendChild(next);
}

loadRuns();
