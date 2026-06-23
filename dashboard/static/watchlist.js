const CONF_COLOR = {
  high: 'var(--green)',
  medium: '#f59e0b',
  low: 'var(--red)',
};

const VIDEO_TYPE_LABELS = {
  weekly_prep: { label: '📹 Weekly Prep', color: 'var(--accent)' },
  trade_review: { label: '📋 Trade Review', color: '#7c3aed' },
};

function getVideoDate() {
  const val = document.getElementById('video-date').value;
  return val || new Date().toISOString().slice(0, 10);
}

function initDatePicker() {
  document.getElementById('video-date').value = new Date().toISOString().slice(0, 10);
}

let activeWeek = null;

async function loadWeeks() {
  const res = await fetch('/api/watchlist/weeks');
  const weeks = await res.json();

  const bar = document.getElementById('week-filter');
  bar.innerHTML = '';

  if (!weeks.length) return;

  // Default to most recent week
  if (!activeWeek) activeWeek = weeks[0].label;

  for (const w of weeks) {
    const sunday = new Date(w.date + 'T00:00:00');
    const saturday = new Date(sunday);
    saturday.setDate(saturday.getDate() + 6);

    const fmt = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const displayYear = saturday.getFullYear();
    const rangeStr = `${fmt(sunday)} – ${fmt(saturday)}, ${displayYear}`;

    const chip = document.createElement('button');
    chip.className = 'toggle-btn';
    chip.textContent = rangeStr;
    chip.dataset.week = w.label;
    chip.style.cssText = w.label === activeWeek
      ? 'background:var(--accent);color:#fff;border-color:var(--accent);font-size:13px'
      : 'font-size:13px';

    chip.onclick = () => {
      activeWeek = w.label;
      loadWeeks();
      loadWatchlist();
    };

    bar.appendChild(chip);
  }
}

async function loadWatchlist() {
  const url = activeWeek ? `/api/watchlist/ideas?week=${encodeURIComponent(activeWeek)}` : '/api/watchlist/ideas';
  const res = await fetch(url);
  const data = await res.json();

  const weekLabel = document.getElementById('week-label');
  weekLabel.textContent = '';

  const container = document.getElementById('ideas-container');
  container.innerHTML = '';

  if (!data.ideas.length) {
    container.innerHTML = `
      <div class="card" style="padding:48px;text-align:center;color:var(--text-muted);">
        <div style="font-size:32px;margin-bottom:12px">👁</div>
        <div style="font-size:18px;font-weight:600;color:var(--text)">No active ideas</div>
        <div style="margin-top:8px;font-size:14px">Upload Tom's weekly prep or trade review video to extract ideas.</div>
      </div>`;
    return;
  }

  // Group by video_type
  const groups = {};
  for (const item of data.ideas) {
    const vt = item.idea.video_type || 'weekly_prep';
    if (!groups[vt]) groups[vt] = [];
    groups[vt].push(item);
  }

  // Render Weekly Prep first, then Trade Review
  for (const vt of ['weekly_prep', 'trade_review']) {
    if (!groups[vt] || !groups[vt].length) continue;
    const meta = VIDEO_TYPE_LABELS[vt] || { label: vt, color: 'var(--text-muted)' };

    const section = document.createElement('div');
    section.style.cssText = 'margin-bottom:36px';

    const uploadedAt = groups[vt][0]?.idea?.opened_at;
    const dateStr = uploadedAt
      ? new Date(uploadedAt).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
      : '';

    const header = document.createElement('div');
    header.style.cssText = `display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid ${meta.color}`;
    header.innerHTML = `
      <span style="font-size:18px;font-weight:700;color:${meta.color}">${meta.label}</span>
      ${dateStr ? `<span style="font-size:13px;color:var(--text-muted);font-weight:500">— ${dateStr}</span>` : ''}
      <span style="font-size:13px;color:var(--text-muted);font-weight:500;margin-left:auto">${groups[vt].length} idea${groups[vt].length !== 1 ? 's' : ''}</span>
    `;
    section.appendChild(header);

    for (const { idea, updates } of groups[vt]) {
      section.appendChild(buildCard(idea, updates));
    }

    container.appendChild(section);
  }
}

function buildLevelBlock(icon, label, value, color) {
  if (!value) return '';
  return `
    <div style="flex:1;min-width:160px;background:var(--card-bg, var(--bg));border:1px solid var(--border);border-radius:8px;padding:10px 14px;">
      <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.6px;color:var(--text-muted);font-weight:600;margin-bottom:4px">${icon} ${label}</div>
      <div style="font-size:15px;font-weight:700;color:${color};line-height:1.3">${value}</div>
    </div>`;
}

function buildCard(idea, updates) {
  const card = document.createElement('div');
  card.className = 'review-card';
  card.style.marginBottom = '16px';

  const conf = idea.confidence || 'medium';
  const confColor = CONF_COLOR[conf] || 'var(--text-muted)';
  const dir = idea.direction || '';
  const dirBadge = dir ? `<span class="badge badge-${dir.toLowerCase()}">${dir}</span>` : '';
  const tf = idea.timeframe ? `<span style="font-size:12px;color:var(--text-muted);font-weight:500">${idea.timeframe}</span>` : '';

  const updatesHtml = updates.length ? updates.map(u => {
    const d = (u.created_at || '').slice(0, 16).replace('T', ' ');
    return `<div class="review-message">
      <span class="review-message-date">${d}</span>
      <span class="review-message-text">${u.raw_message || u.notes || '—'}</span>
    </div>`;
  }).join('') : '<div style="padding:12px;color:var(--text-muted);font-size:13px">No updates yet</div>';

  const threadId = `thread-${idea.id}`;
  const updateCount = updates.length;

  const levelsHtml = (idea.target || idea.invalidation) ? `
    <div style="display:flex;gap:10px;flex-wrap:wrap;padding:0 14px 14px;">
      ${buildLevelBlock('🎯', 'Target', idea.target, 'var(--green)')}
      ${buildLevelBlock('🛑', 'Invalidation', idea.invalidation, 'var(--red)')}
    </div>` : '';

  const chartHtml = idea.chart_url ? `
    <div style="padding:0 14px 14px;">
      <img src="${idea.chart_url}" alt="Chart"
        style="width:100%;max-height:320px;object-fit:contain;border-radius:6px;border:1px solid var(--border);cursor:pointer"
        onclick="this.style.maxHeight = this.style.maxHeight === 'none' ? '320px' : 'none'" />
    </div>` : '';

  const chartBtnId = `chart-btn-${idea.id}`;

  card.innerHTML = `
    <div class="review-card-header">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span class="symbol" style="font-size:20px;font-weight:700">${idea.pair || '?'}</span>
        ${dirBadge}
        ${tf}
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:12px;color:${confColor};font-weight:600">● ${conf}</span>
        <button class="review-toggle" onclick="toggleThread('${threadId}', this)">
          Updates ${updateCount > 0 ? `(${updateCount})` : ''} ▼
        </button>
      </div>
    </div>

    <div class="review-trigger" style="border-color:var(--text-muted);margin:0 14px 12px">
      <span style="color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:0.5px;font-weight:600">Entry Condition</span>
      <span class="review-trigger-text" style="color:var(--text);font-size:15px;line-height:1.5">"${idea.entry_condition || '—'}"</span>
    </div>

    ${levelsHtml}

    <div style="padding:0 14px 14px;font-size:13px;color:var(--text-muted);font-style:italic;line-height:1.5">
      ${idea.summary || ''}
    </div>

    <div id="chart-${idea.id}">${chartHtml}</div>

    <div class="review-thread" id="${threadId}" style="display:none;">
      ${updatesHtml}
    </div>
  `;

  return card;
}

function toggleThread(id, btn) {
  const el = document.getElementById(id);
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  const count = btn.textContent.match(/\((\d+)\)/);
  const label = count ? `Updates (${count[1]})` : 'Updates';
  btn.textContent = open ? `${label} ▼` : `${label} ▲`;
}

function showStatus(msg, isError = false) {
  const el = document.getElementById('upload-status');
  el.textContent = msg;
  el.style.display = '';
  el.style.borderColor = isError ? 'var(--red)' : 'var(--green)';
}

function hideStatus() {
  document.getElementById('upload-status').style.display = 'none';
}

async function uploadVideo(input, videoType) {
  const file = input.files[0];
  if (!file) return;

  const typeLabel = videoType === 'trade_review' ? 'Trade Review' : 'Weekly Prep';
  showStatus(`Uploading "${file.name}" (${typeLabel}) to Gemini for analysis… this may take a few minutes.`);

  const formData = new FormData();
  formData.append('file', file);
  formData.append('video_type', videoType);
  formData.append('video_date', getVideoDate());

  try {
    const res = await fetch('/api/watchlist/upload-video', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    showStatus(`✅ Extracted ${data.ideas_saved} trade ideas from ${typeLabel} video.`);
    setTimeout(hideStatus, 5000);
    loadWeeks();
    loadWatchlist();
  } catch (e) {
    showStatus(`❌ Error: ${e.message}`, true);
  }
  input.value = '';
}

async function uploadImage(input) {
  const file = input.files[0];
  if (!file) return;

  const caption = prompt('Any caption Tom wrote with this image? (leave blank if none)') || '';
  showStatus(`Analyzing chart image…`);

  const formData = new FormData();
  formData.append('file', file);
  formData.append('caption', caption);

  try {
    const res = await fetch('/api/watchlist/upload-image', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    showStatus(`✅ Extracted ${data.ideas_saved} trade ideas from image.`);
    setTimeout(hideStatus, 5000);
    loadWeeks();
    loadWatchlist();
  } catch (e) {
    showStatus(`❌ Error: ${e.message}`, true);
  }
  input.value = '';
}

initDatePicker();
loadWeeks();
loadWatchlist();
