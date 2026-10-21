(function () {
  'use strict';
  // Served by FastAPI at :8000 -> same origin. Opened from Live Server -> call the API directly.
  const API_BASE = location.port === '8000' ? '' : 'http://127.0.0.1:8000';
  const INTENTS = {
    Price_Inquiry: 'Price inquiry',
    Pickup_Request: 'Pickup request',
    Bulk_Negotiation: 'Bulk deal',
    Other: 'Other',
  };
  const MATERIALS = ['Plastic', 'Paper', 'Cardboard', 'Aluminum',
                     'Other_Metals', 'Glass', 'Electronic_Waste', 'Unknown'];
  const $ = id => document.getElementById(id);
  const pretty = s => String(s).replace(/_/g, ' ');
  // Customer messages are untrusted text: always escape before putting them in HTML.
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------------------------------------------------------------- session
  let token = localStorage.getItem('kk_token');
  let user = JSON.parse(localStorage.getItem('kk_user') || 'null');
  let shop = JSON.parse(localStorage.getItem('kk_shop') || 'null');

  function saveSession(data) {
    token = data.token; user = data.user; shop = data.shop;
    localStorage.setItem('kk_token', token);
    localStorage.setItem('kk_user', JSON.stringify(user));
    localStorage.setItem('kk_shop', JSON.stringify(shop));
  }

  function clearSession() {
    token = user = shop = null;
    ['kk_token', 'kk_user', 'kk_shop'].forEach(k => localStorage.removeItem(k));
    messages = [];
    $('loginView').hidden = false;
  }

  async function api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (token) headers.Authorization = 'Bearer ' + token;
    let res;
    try {
      res = await fetch(API_BASE + path, { ...options, headers });
    } catch {
      throw new Error('Cannot reach the server. Is the API running?');
    }
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (res.status === 401 && token) clearSession();
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`);
    }
    return data;
  }

  // ---------------------------------------------------------------- navigation
  const screens = document.querySelectorAll('.screen');
  const navBtns = document.querySelectorAll('nav button');
  const container = document.querySelector('.screens');

  function show(id) {
    screens.forEach(s => s.classList.toggle('active', s.id === id));
    const tab = id === 'detail' ? 'inquiries' : id;
    navBtns.forEach(b => b.classList.toggle('active', b.dataset.nav === tab));
    container.scrollTo({ top: 0 });
  }

  navBtns.forEach(b => b.addEventListener('click', () => {
    show(b.dataset.nav);
    if (b.dataset.nav === 'inquiries') loadInbox();
  }));
  $('backBtn').addEventListener('click', () => show('inquiries'));

  // ---------------------------------------------------------------- login / logout
  function applyUser() {
    if (!user) return;
    $('shopLine').textContent = `${shop.name} · ${user.role}`;
    $('avatarBtn').textContent = user.full_name.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
  }

  async function doLogin() {
    $('loginError').textContent = '';$('loginBtn').disabled = true;
    try {
      const data = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: $('loginEmail').value,
          password: $('loginPassword').value,
          device_name: 'Kalakally web app',
        }),
      });

      saveSession(data);
      $('loginPassword').value = '';$('loginView').hidden = true;
      applyUser();
      show('inquiries');
      loadInbox();
    } catch (e) {
      $('loginError').textContent = e.message;
    } finally {
      $('loginBtn').disabled = false;
    }
  }

  $('loginBtn').addEventListener('click', doLogin);
  $('loginPassword').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });$('avatarBtn').addEventListener('click', async () => {
    if (!confirm('Log out of Kalakally?')) return;
    try { await api('/auth/logout', { method: 'POST' }); } catch { /* clear anyway */ }
    clearSession();
  });

  // ---------------------------------------------------------------- inbox list
  let messages = [];
  let filter = 'all';
  const effectiveIntent = m => m.corrected_intent || m.intent;
  const isPending = m => m.needs_review && m.status === 'new';
  const materialsOf = m => m.corrected_materials || (m.materials && m.materials.labels) || [];
  const fmtTime = iso => iso
    ? new Date(iso).toLocaleString('en-PH', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : '';

  function tagHtml(m) {
    if (isPending(m)) return '<span class="tag review">Needs review</span>';
    if (m.status !== 'new') return '<span class="tag sched">Reviewed</span>';
    const intent = effectiveIntent(m);
    if (intent === 'Price_Inquiry') return '<span class="tag price">Price inquiry</span>';
    if (intent === 'Pickup_Request') return '<span class="tag sched">Pickup</span>';
    if (intent === 'Bulk_Negotiation') return '<span class="tag price">Bulk deal</span>';
    return '<span class="tag muted">Other</span>';
  }

  function renderMetrics() {
    const pending = messages.filter(isPending).length;
    const pickups = messages.filter(m => effectiveIntent(m) === 'Pickup_Request').length;
    $('mTotal').textContent = messages.length;
    $('mNew').textContent = messages.filter(m => m.status === 'new').length;
    $('mReview').textContent = pending;
    $('mPickup').textContent = pickups;
    $('cAll').textContent = messages.length;
    $('cReview').textContent = pending;
    $('cPickup').textContent = pickups;
    const badge = document.querySelector('.badge');
    badge.textContent = pending;
    badge.hidden = pending === 0;
  }

  function renderList() {
    const q = $('searchInput').value.trim().toLowerCase();
    const rows = messages.filter(m => {
      if (filter === 'review' && !isPending(m)) return false;
      if (filter === 'pickup' && effectiveIntent(m) !== 'Pickup_Request') return false;
      if (!q) return true;

      return `${m.sender} ${m.subject || ''} ${m.text}`.toLowerCase().includes(q);
    });
    if (!rows.length) {
      $('inqList').innerHTML = '<div class="empty">No inquiries to show.</div>';
      return;
    }
    $('inqList').innerHTML = rows.map(m => {
      const text = m.text.length > 90 ? m.text.slice(0, 90) + '…' : m.text;
      const mats = materialsOf(m).map(pretty).join(', ');
      const meta = [m.channel, mats, fmtTime(m.received_at)].filter(Boolean).join(' · ');
      return `<button class="card inq" data-id="${m.id}">
        <div class="inq-head">
          <span class="inq-name">${m.status === 'new' ? '<span class="unread"></span>' : ''}${esc(m.sender)}</span>
          ${tagHtml(m)}
        </div>
        <div class="inq-msg">${esc(text)}</div>
        <div class="inq-meta">${esc(meta)}</div>
      </button>`;
    }).join('');
  }

  async function loadInbox() {
    if (!token) return;
    $('listStatus').textContent = 'Loading…';
    try {
      const data = await api('/inbox?limit=200');
      messages = data.messages;
      $('listStatus').textContent = '';
    } catch (e) {
      messages = [];
      $('listStatus').textContent = e.message;
    }
    renderMetrics();
    renderList();
  }

  document.querySelectorAll('.pill').forEach(p => p.addEventListener('click', () => {
    document.querySelectorAll('.pill').forEach(x => x.classList.remove('active'));
    p.classList.add('active');
    filter = p.dataset.filter;
    renderList();
  }));

  $('searchInput').addEventListener('input', renderList);$('inqList').addEventListener('click', e => {
    const card = e.target.closest('.inq');
    if (card) openDetail(Number(card.dataset.id));
  });

  // ---------------------------------------------------------------- detail + review
  let current = null;
  let selectedMaterials = new Set();

  async function openDetail(id) {
    try {
      current = await api(`/inbox/${id}`);
    } catch (e) {
      $('listStatus').textContent = e.message;
      return;
    }
    selectedMaterials = new Set(materialsOf(current));
    renderDetail(current);
    show('detail');
  }

  function renderDetail(m) {
    $('detailTitle').textContent = m.sender;
    $('detailTag').innerHTML = tagHtml(m);
    const banner = isPending(m)
      ? '<b>Check before you reply</b>The classifier was not sure about this message. Confirm or fix the labels below.'
      : `<b>Already reviewed</b>The labels were ${esc(m.status)}${m.reviewed_at ? ' on ' + esc(fmtTime(m.reviewed_at)) : ''}.`;
    const intentOptions = Object.entries(INTENTS).map(([value, text]) =>
      `<option value="${value}"${value === effectiveIntent(m) ? ' selected' : ''}>${text}</option>`).join('');
    const chips = MATERIALS.map(name =>
      `<button type="button" class="chip${selectedMaterials.has(name) ? ' on' : ''}" data-material="${name}">${pretty(name)}</button>`
    ).join('');
    const evidence = (m.materials ? m.materials.matches : []).map(x =>
      `<div class="evidence"><b>${esc(pretty(x.label))}</b> · ${Math.round(x.confidence * 100)}% · “${esc(x.evidence)}”</div>`
    ).join('');
    $('detailBody').innerHTML = `
      <div class="banner">${banner}</div>
      <div class="section-title">Message</div>
      <div class="card">
        <div class="kv"><i>Channel</i><b>${esc(m.channel)}</b></div>
        <div class="kv"><i>From</i><b>${esc(m.sender)}</b></div>
        ${m.subject ? `<div class="kv"><i>Subject</i><b>${esc(m.subject)}</b></div>` : ''}
        <div class="kv"><i>Received</i><b>${esc(fmtTime(m.received_at))}</b></div>
        <div class="bubble">${esc(m.text).replace(/\n/g, '<br>')}</div>
      </div>

      <div class="section-title">Intent</div>
      <div class="card" style="padding:12px 14px">
        <select id="intentSelect">${intentOptions}</select>
        <div class="hint">Model guess: ${esc(INTENTS[m.intent])} (${Math.round(m.intent_confidence * 100)}% sure)</div>
      </div>
      <div class="section-title">Materials</div>
      <div class="card" style="padding:12px 14px">
        <div class="chips" id="chips">${chips}</div>
        ${evidence}
      </div>
      <div class="btns"><button class="btn primary" id="saveReview">Save review</button></div>
      <p class="form-error" id="reviewError"></p>`;
  }

  $('detailBody').addEventListener('click', async e => {
    const chip = e.target.closest('.chip');
    if (chip) {
      const name = chip.dataset.material;
      selectedMaterials.has(name) ? selectedMaterials.delete(name) : selectedMaterials.add(name);
      chip.classList.toggle('on');
      return;
    }
    if (e.target.id === 'saveReview' && current) {
      e.target.disabled = true;
      $('reviewError').textContent = '';
      try {
        await api(`/inbox/${current.id}/review`, {
          method: 'PATCH',
          body: JSON.stringify({
            intent: $('intentSelect').value,
            materials: [...selectedMaterials],
          }),
        });
        show('inquiries');
        loadInbox();
      } catch (err) {
        $('reviewError').textContent = err.message;
        e.target.disabled = false;
      }
    }
  });

  // ---------------------------------------------------------------- Collections demo button (static)
  const start = $('startRoute');
  const state = document.querySelector('.hero .state span:last-child');
  start.addEventListener('click', () => {
    const started = start.dataset.started === '1';
    start.dataset.started = started ? '0' : '1';
    start.textContent = started ? 'Start route' : 'Route in progress';
    state.textContent = started ? '● Not started' : '● In progress';
  });

  // ---------------------------------------------------------------- start
  setInterval(() => {
    if (token && $('inquiries').classList.contains('active')) loadInbox();
  }, 30000);

  if (token && user) {
    $('loginView').hidden = true;
    applyUser();
    loadInbox();
  } else {
    $('loginView').hidden = false;
  }
})();