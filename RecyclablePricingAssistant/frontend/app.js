(function () {
  'use strict';

  const KEY = 'scrapdesk_session';
  const MATERIALS = ['Plastic', 'Paper', 'Cardboard', 'Aluminum', 'Other_Metals', 'Glass', 'Electronic_Waste'];
  const INTENTS = {
    Price_Inquiry: 'Price inquiry',
    Pickup_Request: 'Pickup request',
    Bulk_Negotiation: 'Bulk sale negotiation',
    Other: 'Other / unrelated',
  };
  const ITAG = { Price_Inquiry: 'price', Pickup_Request: 'pickup', Bulk_Negotiation: 'bulk', Other: 'other' };
  const PAGE_SIZE = 20;
  const VEHICLES = {
    tricycle: 'Tricycle / motorcycle', multicab: 'Multicab / van', pickup: 'Pickup',
    small_truck: 'Small / light truck', large_truck: 'Large truck',
  };
  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pretty = s => String(s).replace(/_/g, ' ');
  const shorten = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
  const effIntent = m => m.corrected_intent || m.intent;
  const effMaterials = m => m.corrected_materials || (m.materials ? m.materials.labels : []);
  const icon = name => `<svg class="ic"><use href="#i-${name}"/></svg>`;
  const initials = name => String(name || '?').trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase() || '?';
  const shortName = name => {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : (parts[0] || '');
  };
  const firstName = name => String(name || '').trim().split(/\s+/)[0] || 'Customer';
  const peso = n => '₱' + Number(n || 0).toLocaleString('en-PH', { maximumFractionDigits: 2 });
  const kgText = n => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' kg';

  // ---------- dates and times (the shop works in Philippine time) ----------
  const todayStr = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Manila' });
  function addDays(iso, n) {
    const d = new Date(iso + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function fmtDay(iso) {
    const d = new Date(iso + 'T00:00:00Z');
    return d.toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
    });
  }
  function time12(hhmm) {
    if (!hhmm) return '';
    const [h, m] = hhmm.split(':').map(Number);
    return `${(h % 12) || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
  }
  function windowText(s, e) {
    if (!s) return '';
    return e ? `${time12(s)}–${time12(e)}` : time12(s);
  }
  function when(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toDateString() === new Date().toDateString()
      ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
      : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  let session = null;
  try { session = JSON.parse(localStorage.getItem(KEY)); } catch (e) { session = null; }

  const isDriver = () => !!session && session.user.role === 'driver';
  const isOwner = () => !!session && session.user.role === 'owner';

  let inbox = [], filter = 'all', showAll = false, current = null, currentPickup = null, selMats = new Set();
  let selecting = false, lastRows = [];     // "Select" mode on the inbox (for deleting messages)
  const picked = new Set();
  let pickupMap = {}, trucks = [];
  let planDate = todayStr();
  let colDate = todayStr(), colTruckId = null, colData = null;
  let rv = null;                 // state of the price-review screen
  let backTo = 'inquiries';      // where the back arrow on the review screen goes

  // ---------- helpers ----------
  let toastTimer;
  function toast(msg) {
    const t = $('toast');
    if (!t) { console.log(msg); return; }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), msg.length > 70 ? 6000 : 3000);
  }

  function driverNote(result) {
    const n = result && result.driver_notice;
    if (!n) return '';
    return n.sent ? ` Driver emailed (${n.driver}).` : ` \u26a0 ${n.message}`;
  }

  function errText(data) {
    if (!data || !data.detail) return '';
    return Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(' ') : String(data.detail);
  }

  async function api(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (session) headers.Authorization = 'Bearer ' + session.token;
    let res;
    try {
      res = await fetch(path, {
        ...opts,
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      });
    } catch (e) {
      throw new Error('Cannot reach the server.');
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* some responses have no JSON body */ }
    if (res.status === 401 && session) {
      logoutLocal();
      throw new Error('Session expired. Please log in again.');
    }
    if (!res.ok) throw new Error(errText(data) || 'Request failed (' + res.status + ')');
    return data;
  }

  // ---------- navigation ----------
  const TAB_OF = { detail: 'inquiries', review: 'inquiries' };

  function show(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === id));
    const tab = TAB_OF[id] || id;
    document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.nav === tab));
    $('nav').style.display = (id === 'login' || id === 'signup') ? 'none' : '';
    $('screens').scrollTo({ top: 0 });

    if (id === 'inquiries') loadInbox();
    if (id === 'planning') loadPlan();
    if (id === 'collections') loadCollections();
    if (id === 'more') { moreView = null; loadMore(); }
  }

  document.querySelectorAll('nav button').forEach(b => {
    b.addEventListener('click', () => show(b.dataset.nav));
  });

  $('backBtn').addEventListener('click', () => show('inquiries'));
  $('reviewBack').addEventListener('click', () => show(backTo));

  // ---------- login / logout / sign up ----------
  function logoutLocal() {
    session = null;
    localStorage.removeItem(KEY);
    show('login');
  }

  function enterApp() {
    document.querySelectorAll('[data-shop]').forEach(el => { el.textContent = session.shop.name; });
    document.querySelectorAll('[data-avatar]').forEach(el => { el.textContent = initials(session.user.full_name); });
    document.querySelectorAll('[data-today]').forEach(el => {
      el.textContent = new Date().toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'Asia/Manila',
      });
    });
    const driver = isDriver();
    document.querySelectorAll('nav button').forEach(b => {
      b.style.display = driver && ['inquiries', 'planning'].includes(b.dataset.nav) ? 'none' : '';
    });
    planDate = todayStr();
    colDate = todayStr();
    colTruckId = null;
    show(driver ? 'collections' : 'inquiries');
  }

  $('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    $('loginErr').textContent = '';
    try {
      const r = await api('/auth/login', {
        method: 'POST',
        body: { email: $('lEmail').value.trim(), password: $('lPass').value, device_name: 'Web app' },
      });
      session = { token: r.token, user: r.user, shop: r.shop };
      localStorage.setItem(KEY, JSON.stringify(session));
      $('lPass').value = '';
      enterApp();
    } catch (err) {
      $('loginErr').textContent = err.message;
    }
  });

  $('showSignup').addEventListener('click', () => { $('signupErr').textContent = ''; show('signup'); });
  $('showLogin').addEventListener('click', () => { $('loginErr').textContent = ''; show('login'); });

  $('signupForm').addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.currentTarget;
    const button = form.querySelector('button[type="submit"]');
    const error = $('signupErr');
    error.textContent = '';
    button.disabled = true;
    try {
      const r = await api('/auth/register-shop', {
        method: 'POST',
        body: {
          shop_name: $('sShop').value.trim(),
          full_name: $('sName').value.trim(),
          email: $('sEmail').value.trim(),
          password: $('sPass').value,
          device_name: 'Web app',
        },
      });
      session = { token: r.token, user: r.user, shop: r.shop };
      localStorage.setItem(KEY, JSON.stringify(session));
      form.reset();
      enterApp();
      toast('Account created successfully.');
    } catch (err) {
      error.textContent = err.message;
    } finally {
      button.disabled = false;
    }
  });

  // =====================================================================
  //  INQUIRIES
  // =====================================================================
  function itagHtml(intent) {
    return `<span class="itag ${ITAG[intent] || 'other'}">${esc(INTENTS[intent] || intent)}</span>`;
  }

  async function loadPickupMap() {
    const [conf, pend, done] = await Promise.all([
      api('/pickups?status=confirmed&limit=200'),
      api('/pickups?status=pending_approval&limit=200'),
      api('/pickups?status=collected&limit=200'),
    ]);
    const map = {};
    [...done.pickups, ...pend.pickups, ...conf.pickups].forEach(p => { if (p.message_id) map[p.message_id] = p; });
    return { map, confirmed: conf.pickups.length };
  }

  function truckLine(p) {
    const t = trucks.find(x => x.id === p.truck_id);
    if (!t) return '';
    return [shortName(t.driver_name), t.code].filter(Boolean).join(' · ');
  }

  function tagFor(m) {
    const p = pickupMap[m.id];
    if (p && p.status === 'collected') return '<span class="tag sched">Collected</span>';
    if (p && p.status === 'confirmed') return '<span class="tag sched">Scheduled</span>';
    if (p && p.status === 'pending_approval' && p.auto_filled) return '<span class="tag pending">Draft ready</span>';
    if (m.replied_at) return '<span class="tag sched">Replied</span>';
    if (m.needs_review && m.status === 'new') return '<span class="tag review">Needs review</span>';
    return `<span class="tag plain">${esc(INTENTS[effIntent(m)] || effIntent(m))}</span>`;
  }

  function metaFor(m) {
    const p = pickupMap[m.id];
    if (p && p.status !== 'pending_approval') {
      return [p.expected_kg ? kgText(p.expected_kg) : '', truckLine(p)].filter(Boolean).join(' · ');
    }
    const parts = [];
    if (p && p.expected_kg) parts.push(kgText(p.expected_kg));
    else if (effIntent(m) !== 'Other') {
      const labels = effMaterials(m).filter(l => l !== 'Unknown').map(pretty);
      if (labels.length) parts.push(labels.slice(0, 2).join(', '));
    }
    if (p && p.area) parts.push(p.area);
    else parts.push(m.channel);
    return parts.join(' · ');
  }

  function card(m, selected) {
    const title = m.subject || INTENTS[effIntent(m)] || '';
    return `<button class="card inq ${selected ? 'sel' : ''}${picked.has(m.id) ? ' picked' : ''}" data-id="${m.id}">
      <div class="inq-head">
        ${selecting ? `<span class="pick">${picked.has(m.id) ? '✓' : ''}</span>` : ''}
        <span class="ava">${esc(initials(m.sender))}</span>
        <span class="inq-name">${esc(m.sender || 'Customer')}</span>
        <span class="inq-time">${esc(when(m.received_at))}${m.status === 'new' ? '<span class="unread"></span>' : ''}</span>
      </div>
      <div class="inq-title">${esc(shorten(title, 60))}</div>
      <div class="inq-msg">${esc(m.text)}</div>
      <div class="inq-foot">${tagFor(m)}<span class="inq-meta">${esc(metaFor(m))}</span></div>
    </button>`;
  }

  function filteredRows() {
    const q = $('searchInput').value.trim().toLowerCase();
    return inbox.filter(m => {
      const intent = effIntent(m);
      if (filter === 'review') {
        if (!(m.needs_review && m.status === 'new')) return false;
      } else if (filter !== 'all' && intent !== filter) {
        return false;
      }
      return !q || [m.text, m.subject, m.sender].join(' ').toLowerCase().includes(q);
    });
  }

  function renderList() {
    const rows = filteredRows();
    const visible = showAll ? rows : rows.slice(0, PAGE_SIZE);
    const first = rows.find(m => m.status === 'new' && m.needs_review);
    $('inqList').innerHTML = visible.length
      ? visible.map(m => card(m, first && m.id === first.id)).join('')
      : '<div class="empty">No messages here yet.</div>';
    const more = rows.length > PAGE_SIZE && !showAll;
    $('viewAll').style.display = more ? '' : 'none';
    $('viewAll').innerHTML = `View all ${rows.length} inquiries →`;
    lastRows = visible;
    [...picked].forEach(id => { if (!inbox.some(m => m.id === id)) picked.delete(id); });
    renderSelBar();
  }

  function renderSelBar() {
    $('selBar').style.display = selecting ? '' : 'none';
    $('selectBtn').innerHTML = selecting ? 'Done' : icon('trash');
    $('selectBtn').classList.toggle('on', selecting);
    $('selectBtn').setAttribute('aria-label', selecting ? 'Finish selecting' : 'Select messages to delete');
    if (!selecting) return;
    $('selCount').textContent = picked.size ? `${picked.size} selected` : 'Tap messages to select';
    $('selDelete').disabled = !picked.size;
    $('selAll').textContent = lastRows.length && lastRows.every(m => picked.has(m.id))
      ? 'Clear' : `Select all ${lastRows.length}`;
  }

  function renderStats(stats, confirmedCount) {
    const by = stats.by_intent || {};
    const unread = inbox.filter(m => m.status === 'new').length;
    $('mOpen').textContent = stats.total;
    $('mUnread').textContent = unread;
    $('mReview').textContent = stats.pending_review;
    $('mSched').textContent = confirmedCount;

    const counts = {
      all: stats.total,
      review: stats.pending_review,
      Price_Inquiry: by.Price_Inquiry || 0,
      Pickup_Request: by.Pickup_Request || 0,
      Bulk_Negotiation: by.Bulk_Negotiation || 0,
      Other: by.Other || 0,
    };
    document.querySelectorAll('[data-count]').forEach(el => { el.textContent = counts[el.dataset.count] ?? 0; });
    $('navBadge').textContent = stats.pending_review;
    $('navBadge').style.display = stats.pending_review ? '' : 'none';
  }

  async function loadInbox() {
    if (!session || isDriver()) return;
    try {
      const [stats, list, pm, tr] = await Promise.all([
        api('/inbox/stats'),
        api('/inbox?limit=200'),
        loadPickupMap(),
        api('/planning/trucks'),
      ]);
      inbox = list.messages;
      pickupMap = pm.map;
      trucks = tr.trucks;
      renderStats(stats, pm.confirmed);
      renderList();
    } catch (e) {
      if (session) toast(e.message);
    }
  }

  $('inqList').addEventListener('click', e => {
    const c = e.target.closest('.inq');
    if (!c) return;
    if (!selecting) return openDetail(c.dataset.id);
    const id = parseInt(c.dataset.id, 10);
    if (picked.has(id)) picked.delete(id); else picked.add(id);
    renderList();
  });

  // select and delete messages
  async function deleteMessages(ids, fromDetail) {
    const many = ids.length > 1;
    const ok = confirm((many ? `Delete these ${ids.length} inquiries?` : 'Delete this inquiry?') +
      '\n\nThe replies you sent for them are deleted too, and any draft pickup waiting for approval is cancelled. ' +
      'This can’t be undone.');
    if (!ok) return;
    try {
      const r = await api('/inbox/delete', { method: 'POST', body: { ids } });
      picked.clear();
      selecting = fromDetail ? selecting : false;
      const note = r.blocked.length
        ? ` ${r.blocked.length} kept: ${r.blocked[0].reason}` : '';
      toast(r.deleted ? `Deleted ${r.deleted} inquir${r.deleted === 1 ? 'y' : 'ies'}.${note}` : (note.trim() || 'Nothing was deleted.'));
      if (fromDetail && r.deleted) show('inquiries'); else loadInbox();
    } catch (err) {
      toast(err.message);
    }
  }

  $('selectBtn').addEventListener('click', () => { selecting = !selecting; picked.clear(); renderList(); });
  $('selAll').addEventListener('click', () => {
    const all = lastRows.length && lastRows.every(m => picked.has(m.id));
    lastRows.forEach(m => { if (all) picked.delete(m.id); else picked.add(m.id); });
    renderList();
  });
  $('selDelete').addEventListener('click', () => deleteMessages([...picked], false));

  $('viewAll').addEventListener('click', () => { showAll = true; renderList(); });

  $('pills').addEventListener('click', e => {
    const p = e.target.closest('.pill');
    if (!p) return;
    document.querySelectorAll('.pill').forEach(x => x.classList.remove('active'));
    p.classList.add('active');
    filter = p.dataset.filter;
    showAll = false;
    renderList();
  });

  $('searchInput').addEventListener('input', () => { showAll = false; renderList(); });

  setInterval(() => {
    if (session && !document.hidden && $('inquiries').classList.contains('active')) loadInbox();
  }, 10000);

  // =====================================================================
  //  INQUIRY DETAIL
  // =====================================================================
  async function openDetail(id) {
    show('detail');
    $('detailBody').innerHTML = '<div class="empty">Loading…</div>';
    try {
      const [msg, pm] = await Promise.all([api('/inbox/' + id), loadPickupMap()]);
      current = msg;
      pickupMap = pm.map;
      currentPickup = pm.map[msg.id] || null;
      renderDetail();
    } catch (e) {
      $('detailBody').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  // the shop's price list, quoted in replies
  let currentQuote = { items: [], basis: 'none' };      // price-list items matching the open inquiry

  function quoteLine(i) {
    const parts = [];
    if (i.buy_price != null) parts.push('we buy at ' + priceText(i.buy_price, i.unit));
    if (i.sell_price != null) parts.push('we sell at ' + priceText(i.sell_price, i.unit));
    return `- ${i.name}: ${parts.join(', ')}${i.note ? ' (' + i.note + ')' : ''}`;
  }

  function quoteDraft(name, items) {
    const head = `Hi ${name}, thank you for your message. Here are our current prices:`;
    const foot = `Prices can change, and the final amount depends on the weighed material. Let us know if you'd like us to pick it up.`;
    const lines = [];
    for (const i of items) {
      const next = [...lines, quoteLine(i)];
      if ([head, ...next, foot].join('\n').length > 1400) break;
      lines.push(quoteLine(i));
    }
    return [head, ...lines, foot].join('\n');
  }

  function priceListHtml() {
    const items = currentQuote.items;
    if (!items.length) {
      return `<div class="sect-h">Your price list</div>
        <div class="card pad muted">Nothing on your price list matches this message yet. Add or change items under More › Price list.</div>`;
    }
    return `<div class="sect-h">Your price list <small>${currentQuote.basis === 'category' ? 'by material type' : 'matched from the message'}</small></div>
      <div class="card pad">${items.map(i => `
        <div class="price-line">
          <div><b>${esc(i.name)}</b><span>${esc(i.note || (i.survey ? 'Survey avg ' + peso(i.survey.average) : ' '))}</span></div>
          <div class="r">${i.buy_price != null ? esc(priceText(i.buy_price, i.unit)) : '—'}${i.sell_price != null ? `<br><span>sell ${esc(priceText(i.sell_price, i.unit))}</span>` : ''}</div>
        </div>`).join('')}
        <button class="btn ghost" data-act="addprices" style="width:100%;margin-top:10px">${icon('copy')}Add these prices to the reply</button>
      </div>`;
  }

  function replyDraft(m, p) {
    const name = firstName(m.sender);
    if (p && p.status === 'confirmed') {
      const t = trucks.find(x => x.id === p.truck_id);
      return `Hi ${name}, your pickup is confirmed for ${fmtDay(p.pickup_date)}, ${windowText(p.window_start, p.window_end)}. ` +
        `${t && t.driver_name ? 'Our driver ' + firstName(t.driver_name) + ' will come with truck ' + t.code + '.' : 'Our driver will come to your location.'}`;
    }
    if (p && p.status === 'pending_approval') {
      return `Hi ${name}, thank you. We'll review the requested rates first. We'll confirm pickup once the price is approved.`;
    }
    if (effIntent(m) === 'Other') return `Hi ${name}, thank you for your message. How can we help you today?`;
    if (effIntent(m) === 'Price_Inquiry' && currentQuote.items.length) return quoteDraft(name, currentQuote.items);

  }

  function materialsCard(p) {
    const approved = p.status !== 'pending_approval';
    const lines = p.items.map(i => {
      const rate = approved && i.approved_rate != null ? i.approved_rate : i.requested_rate;
      return `<div class="mline">
        <div><b>${esc(i.material)}</b><span>${kgText(i.expected_kg)}</span></div>
        <div class="r"><b>${rate != null ? peso(rate) + '/kg' : '—'}</b>
          <span>${rate != null ? peso(i.expected_kg * rate) : 'No rate yet'}</span></div>
      </div>`;
    }).join('');
    const total = approved ? p.approved_total : p.requested_total;
    return `<div class="card mcard">
      <div class="mhead"><h3>Materials &amp; prices</h3><span class="kg">${kgText(p.expected_kg)}</span></div>
      <div class="mcols"><span>Material / weight</span><span>${approved ? 'Approved rate' : 'Requested rate'}</span></div>
      ${lines || '<div class="muted">No materials were detected. Open the price review to add them.</div>'}
      <div class="mtotal">
        <div><b>${approved ? 'Approved total' : 'Requested total'}</b><span>${approved ? 'Confirmed rates' : 'Estimate only · not approved'}</span></div>
        <div class="big">${peso(total)}</div>
      </div>
    </div>`;
  }

  function pickupCard(p) {
    const when_ = p.pickup_date
      ? `${fmtDay(p.pickup_date)}${p.window_start ? ' · ' + windowText(p.window_start, p.window_end) : ''}`
      : 'No date requested yet';
    const t = trucks.find(x => x.id === p.truck_id);
    const state = p.status === 'pending_approval'
      ? 'Pending price approval · Unassigned'
      : p.status === 'collected' ? 'Collected' : `Confirmed${t ? ' · ' + t.code : ''}`;
    const place = [p.address, p.area].filter(Boolean);
    return `<div class="card mcard">
      <div class="mhead"><h3>Requested pickup</h3></div>
      <div class="irow">${icon('cal')}<div><b>${esc(when_)}</b><span>${esc(state)}</span></div></div>
      ${place.length ? `<div class="irow">${icon('pin')}<div><b>${esc(place[0])}</b>${place[1] ? `<span>${esc(place[1])}</span>` : ''}</div></div>` : ''}
      ${p.access_note ? `<div class="irow">${icon('truck')}<div><b>Access</b><span>${esc(p.access_note)}</span></div></div>` : ''}
      ${t && p.status === 'pending_approval' ? `<div class="irow">${icon('truck')}<div><b>Suggested: ${esc(shortName(t.driver_name) || t.code)} · ${esc(t.code)}</b><span>Not final until you approve</span></div></div>` : ''}
    </div>`;
  }

  // The "check these" list and the reason for the suggested driver on an auto-filled draft.
  function draftNotesHtml(p) {
    if (!p || !p.auto_filled) return '';
    const notes = (p.auto_notes || []).map(n => `<li>${esc(n)}</li>`).join('');
    return `${p.assign_note ? `<div class="assign-note">${icon('truck')}<span>${esc(p.assign_note)}</span></div>` : ''}
      ${notes ? `<div class="checklist"><b>Check before approving</b><ul>${notes}</ul></div>` : ''}`;
  }

  function threadHtml(m) {
    return (m.replies || []).map(r => `<div class="card convo mine ${r.status === 'failed' ? 'failed' : ''}">
      <div class="who">${esc(r.sent_by_name || 'You')}<span>${esc(when(r.sent_at))} · ${r.status === 'sent' ? 'sent via ' + esc(r.channel) : 'not sent'}</span></div>
      <p>${esc(r.body)}</p>${r.error ? `<div class="err">${esc(r.error)}</div>` : ''}</div>`).join('');
  }

  async function surveyHtml(m) {
    const labels = effMaterials(m).filter(l => l !== 'Unknown');
    if (!labels.length) return '';
    try {
      const q = labels.map(l => 'labels=' + encodeURIComponent(l)).join('&');
      const r = await api('/prices/by-classifier?' + q);
      const list = (r.materials || []).filter(x => x.unit === 'kg').slice(0, 6);
      if (!list.length) return '';
      return `<div class="sect-h">Survey prices <small>per kg · surveyed junkshops</small></div>
        <div class="card pad">${list.map(x => `
          <div class="price-line">
            <div><b>${esc(x.name)}</b><span>${x.shops} shop${x.shops === 1 ? '' : 's'} surveyed</span></div>
            <div class="r">${peso(x.min)}–${peso(x.max)}<br><span>median ${peso(x.median)}</span></div>
          </div>`).join('')}</div>`;
    } catch (e) { return ''; }
  }

  async function renderDetail() {
    const m = current;
    const p = currentPickup;
    const intent = effIntent(m);
    const reviewed = m.status !== 'new';
    selMats = new Set(effMaterials(m).filter(label => label !== 'Unknown'));
    currentQuote = { items: [], basis: 'none' };
    if (!p && intent !== 'Other') {
      try {
        const labels = effMaterials(m).filter(l => l !== 'Unknown').map(l => '&labels=' + encodeURIComponent(l)).join('');
        currentQuote = await api('/inventory/match?text=' + encodeURIComponent((m.text || '').slice(0, 1500)) + labels);
      } catch (e) { /* no price list yet: the plain draft is used */ }
    }
    const draft = replyDraft(m, p);
    const rep = m.reply || { can_reply: false, reason: '' };

    // Once a reply has been sent, start with an empty box instead of offering the same text again.
    const lastSent = [...(m.replies || [])].reverse().find(r => r.status === 'sent');
    const startText = lastSent && lastSent.body.trim() === draft.trim() ? '' : draft;
    const canPickup = intent === 'Pickup_Request' || intent === 'Bulk_Negotiation';

    let banner = '';
    if (p && p.status === 'pending_approval') {
      banner = p.auto_filled
        ? `<div class="banner"><b>${icon('clip')}Draft pickup made from this message</b>
            Details were read from the message and a driver was suggested. Review, change anything, then approve.</div>`
        : `<div class="banner"><b>${icon('clock')}Price review before pickup</b>
            Requested rates only. Not approved, not scheduled, and no driver assigned yet.</div>`;
      banner += draftNotesHtml(p);
    } else if (p && p.status === 'confirmed') {
      banner = `<div class="banner ok"><b>${icon('truck')}Pickup confirmed</b>
        ${esc(fmtDay(p.pickup_date))} · ${esc(windowText(p.window_start, p.window_end))}${truckLine(p) ? ' · ' + esc(truckLine(p)) : ''}</div>`;
    } else if (p && p.status === 'collected') {
      banner = `<div class="banner ok"><b>${icon('clip')}Collected</b>${esc(kgText(p.actual_kg))} weighed on site.</div>`;
    }
    if (reviewed) {
      banner += m.status === 'corrected'
        ? `<div class="banner"><b>Staff update saved</b>The category or materials were adjusted by staff.</div>`
        : `<div class="banner ok"><b>Reviewed</b>A staff member confirmed this message.</div>`;
    }

    let middle = '';
    if (p) {
      middle = materialsCard(p) + pickupCard(p);
    } else if (intent !== 'Other') {
      const labels = effMaterials(m);
      const chipsHtml = labels.length
        ? labels.map(l => `<span class="itag other">${esc(pretty(l))}</span>`).join(' ')
        : '<span class="muted">No recyclable material recognised.</span>';
      middle = `<div class="sect-h">Materials</div><div class="card pad">${chipsHtml}</div>` + priceListHtml() + await surveyHtml(m);
    }

    let action = '';
    if (p && p.status === 'pending_approval') {
      action = `<div class="reviewbox"><h3>Review request</h3>
        <p>Check the details, rates, driver and time, then approve.</p>
        <button class="btn primary" data-act="review">${icon('clip')}Review &amp; approve</button></div>`;
    } else if (p && p.status === 'confirmed') {
      action = `<div class="reviewbox"><h3>Scheduled</h3>
        <p>This pickup is on the planning board.</p>
        <button class="btn primary" data-act="toplan">${icon('cal')}Open in planning</button></div>`;
    } else if (!p && canPickup) {
      action = `<div class="reviewbox"><h3>Turn into a pickup</h3>
        <p>Weights, rates and time are read from the message so you can review them.</p>
        <button class="btn primary" data-act="mkpickup">${icon('clip')}Create pickup request</button></div>`;
    }

    const intentOpts = Object.keys(INTENTS)
      .map(key => `<option value="${key}" ${key === intent ? 'selected' : ''}>${esc(INTENTS[key])}</option>`).join('');
    const chips = MATERIALS
      .map(key => `<button type="button" class="chip ${selMats.has(key) ? 'on' : ''}" data-mat="${key}">${esc(pretty(key))}</button>`).join('');

    $('detailBody').innerHTML = `
      <div class="dtitle">
        <h1 class="h1">${esc(firstName(m.sender))}’s inquiry</h1>
        ${tagFor(m)}
      </div>
      <div class="dsub">${esc(m.sender || 'Customer')}${p && p.organization ? ' · ' + esc(p.organization) : ''}</div>
      <div class="dsubject">${esc(m.subject || INTENTS[intent] || '')}</div>
      ${banner}
      ${middle}

      <div class="sect-h">Conversation <small>${esc(when(m.received_at))} · ${esc(m.channel)}</small></div>
      <div class="card convo">
        <div class="who">${esc(m.sender || 'Customer')}<span>${esc(when(m.received_at))}</span></div>
        <p>${esc(m.text)}</p>
      </div>
      ${threadHtml(m)}

      ${action}

      <div class="sect-h">Reply to ${esc(firstName(m.sender))} <small>${rep.can_reply ? 'Sends by ' + esc(rep.via) + (rep.to_hint ? ' to ' + esc(rep.to_hint) : '') : 'Not sent from the app'}</small></div>
      <div class="card replybox">
        <textarea id="replyText" maxlength="1500" placeholder="Write a reply…">${esc(startText)}</textarea>
        <div class="foot"><span>${rep.can_reply ? 'The customer receives this exactly as written.' : esc(rep.reason || 'Copy and send it yourself.')}</span></div>
      </div>
      <div class="btns" style="margin:0 0 14px">
        ${rep.can_reply ? `<button class="btn primary" data-act="sendreply">${icon('send')}Send reply</button>` : ''}
        <button class="btn ${rep.can_reply ? 'ghost' : 'primary'}" data-act="copyreply">${icon('copy')}Copy</button>
      </div>

      <details class="card optional-review">
        <summary>${reviewed ? 'View or update staff review (optional)' : 'Staff review (optional)'}</summary>
        <label class="field" style="margin:0 0 10px">
          <span>Category</span>
          <select id="revIntent">${intentOpts}</select>
        </label>
        <div class="muted">Materials (leave empty if unknown)</div>
        <div class="chips">${chips}</div>
        <div class="btns">
          <button class="btn ghost" data-act="confirm">Confirm category</button>
          <button class="btn primary" data-act="save">Save changes</button>
        </div>
      </details>

      <button class="btn danger" data-act="delmsg" style="width:100%;margin-top:14px">${icon('trash')}Delete this inquiry</button>
    `;
  }

  async function submitReview(confirmOnly, btn) {
    btn.disabled = true;
    try {
      const body = {};
      if (!confirmOnly) {
        const intent = $('revIntent').value;
        body.intent = intent;
        if (intent !== 'Other') body.materials = selMats.size ? [...selMats] : ['Unknown'];
      }
      await api(`/inbox/${current.id}/review`, { method: 'PATCH', body });
      const pm = await loadPickupMap();                  // re-labelling can create a draft pickup
      pickupMap = pm.map;
      current = await api('/inbox/' + current.id);
      currentPickup = pm.map[current.id] || null;
      await renderDetail();
      toast(current.status === 'corrected' ? 'Correction saved' : 'Confirmed');
      loadInbox();
    } catch (err) {
      toast(err.message);
      btn.disabled = false;
    }
  }

  $('detailBody').addEventListener('click', async e => {
    const chip = e.target.closest('.chip');
    if (chip) {
      const k = chip.dataset.mat;
      if (selMats.has(k)) selMats.delete(k); else selMats.add(k);
      chip.classList.toggle('on');
      return;
    }
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;

    if (act === 'confirm' || act === 'save') return submitReview(act === 'confirm', btn);
    if (act === 'delmsg') return deleteMessages([current.id], true);

    if (act === 'sendreply') {
      const text = $('replyText').value.trim();
      if (!text) return toast('Write a reply first.');
      btn.disabled = true;
      try {
        await api(`/inbox/${current.id}/reply`, { method: 'POST', body: { text } });
        toast('Reply sent.');
        current = await api('/inbox/' + current.id);
        await renderDetail();
        loadInbox();
      } catch (err) {
        toast(err.message);
        btn.disabled = false;
        try { current = await api('/inbox/' + current.id); } catch (x) { /* keep what is on screen */ }
      }
      return;
    }
    if (act === 'copyreply') {
      const text = $('replyText').value;
      try { await navigator.clipboard.writeText(text); toast('Reply copied.'); }
      catch (err) { $('replyText').select(); toast('Press Ctrl+C to copy the selected text.'); }
      return;
    }

    if (act === 'addprices') {
      const box = $('replyText');
      const add = currentQuote.items.slice(0, 8).map(quoteLine).join('\n');
      const next = (box.value.trim() ? box.value.trim() + '\n' : '') + add;
      if (next.length > 1500) return toast('That would make the reply too long. Add fewer items by hand.');
      box.value = next;
      box.focus();
      return toast('Prices added to the reply.');
    }  
      
    if (act === 'review' && currentPickup) return openReview(currentPickup.id, 'detail');
    if (act === 'toplan') {
      planDate = (currentPickup && currentPickup.pickup_date) || todayStr();
      return show('planning');
    }
    if (act === 'mkpickup') {
      btn.disabled = true;
      try {
        const r = await api(`/pickups/from-message/${current.id}`, { method: 'POST' });
        currentPickup = r.pickup;
        if (r.pickup.items.length === 0) toast('No weights found in the message. Add them in the review.');
        openReview(r.pickup.id, 'detail');
      } catch (err) {
        toast(err.message);
        btn.disabled = false;
      }
    }
  });

  // =====================================================================
  //  PRICE REVIEW  (requested prices -> approve with a truck and time)
  // =====================================================================
  const verdictClass = v => v === 'within_market' ? 'good' : (v === 'no_reference' ? 'warn' : 'bad');

  async function openReview(pickupId, from) {
    backTo = from || 'planning';
    show('review');
    $('reviewBody').innerHTML = '<div class="empty">Loading…</div>';
    try {
      const [pickup, review, tr] = await Promise.all([
        api('/pickups/' + pickupId),
        api(`/pickups/${pickupId}/price-review`),
        api('/planning/trucks'),
      ]);
      trucks = tr.trucks;
      rv = { pickup, review, checks: {}, truckId: null, timers: {} };
      const date = pickup.pickup_date || planDate;
      if (pickup.status === 'pending_approval' && trucks.length) {
        const found = await Promise.all(trucks.map(t => runCheck(pickup.id, t.id, date, pickup.window_start, pickup.window_end)));
        const okOnes = found.filter(c => c && c.ok).sort((a, b) => a.projected_kg - b.projected_kg);
        rv.truckId = trucks.some(t => t.id === pickup.truck_id)
          ? pickup.truck_id                                  // the driver suggested automatically
          : (okOnes[0] || found[0] || { truck_id: trucks[0].id }).truck_id;
      }
      renderReview();
    } catch (err) {
      $('reviewBody').innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  }

  async function runCheck(pid, truckId, date, start, end) {
    try {
      const qs = new URLSearchParams({ truck_id: truckId });
      if (date) qs.set('date', date);
      if (start) qs.set('start', start);
      if (end) qs.set('end', end);
      const c = await api(`/pickups/${pid}/check?${qs}`);
      rv.checks[truckId] = c;
      return c;
    } catch (e) { return null; }
  }

  function renderReview() {
    const p = rv.pickup;
    const pending = p.status === 'pending_approval';
    const lineById = {};
    rv.review.lines.forEach(l => { lineById[l.item_id] = l; });

    const lines = p.items.map((i, n) => {
      const l = lineById[i.id] || {};
      const asked = i.approved_rate != null ? i.approved_rate : i.requested_rate;
      const suggested = asked == null && pending ? (l.suggested_rate ?? null) : null;   // survey median
      const rate = asked != null ? asked : suggested;
      const vr = l.review;
      return `<div class="card pad" style="margin-bottom:10px" data-line="${n}">
        <b style="font-size:16px">${esc(i.material)}</b>
        <div class="two" style="margin-top:8px">
          <label class="field" style="margin:0"><span>Weight (kg)</span>
            <input class="rv-kg" type="number" min="0" step="any" value="${i.expected_kg}" ${pending ? '' : 'disabled'}></label>
          <label class="field" style="margin:0"><span>Rate (₱/kg)</span>
            <input class="rv-rate" type="number" min="0" step="any" value="${rate ?? ''}"
              data-key="${esc(i.catalog_key || '')}" data-mat="${esc(i.material)}" data-req="${i.requested_rate ?? ''}" ${pending ? '' : 'disabled'}></label>
        </div>
        ${peso(suggested)}/kg is ${l.suggested_rate !== undefined && l.suggested_source === 'price_list' ? 'the rate on your price list' : 'the survey median'} - change it if you pay differently.
        <div class="verdict ${vr ? verdictClass(vr.verdict) : ''}" data-verdict>${vr ? esc(vr.message) : ''}</div>
        <div class="muted" style="margin-top:4px">Line total: <b data-line-total>${rate ? peso(i.expected_kg * rate) : '—'}</b></div>
      </div>`;
    }).join('');

    const truckOpts = trucks.map(t => {
      const label = `${t.code} · ${t.label}${t.driver_name ? ' · ' + t.driver_name : ' · no driver'} (${kgText(t.capacity_kg)})`;
      return `<option value="${t.id}" ${t.id === rv.truckId ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('');

    const schedule = pending ? `
      <div class="sect-h">Schedule</div>
      ${trucks.length ? '' : `<div class="banner bad"><b>${icon('alert')}No trucks yet</b>An owner must add a truck in More → Trucks before a pickup can be approved.</div>`}
      <div class="card pad">
        <label class="field"><span>Pickup date</span><input id="rvDate" type="date" value="${esc(p.pickup_date || planDate)}"></label>
        <div class="two">
          <label class="field"><span>From</span><input id="rvStart" type="time" value="${esc(p.window_start || '')}"></label>
          <label class="field"><span>To</span><input id="rvEnd" type="time" value="${esc(p.window_end || '')}"></label>
        </div>
        <label class="field" style="margin:0"><span>Truck &amp; driver</span>
          <select id="rvTruck">${truckOpts}</select></label>
        <button class="btn ghost" type="button" data-act="suggest" style="width:100%;margin-top:10px">${icon('truck')}Suggest driver for this load</button>
        <div id="rvAssign" style="margin-top:10px"></div>
        <div id="rvCheck" style="margin-top:10px"></div>
      </div>` : '';

    const d = (k, label, ph = '') => `<label class="field"><span>${label}</span>
      <input id="rvd_${k}" value="${esc(p[k] || '')}" maxlength="300" placeholder="${ph}" ${pending ? '' : 'disabled'}></label>`;

    $('reviewBody').innerHTML = `
      <div class="eyebrow">Price review</div>
      <h1 class="h1">${esc(p.customer_name)}</h1>
      <p class="lede">${pending
        ? 'Compare the requested rates with what surveyed junkshops pay, then confirm the truck and time.'
        : `This pickup is ${esc(pretty(p.status))}.`}</p>

 ${pending ? draftNotesHtml(p) : ''}
      ${lines || '<div class="empty">No materials on this request yet.</div>'}
      <div class="card mcard"><div class="mtotal" style="border:none;margin:0;padding:0">
        <div><b>Total</b><span id="rvNote">${pending ? 'Estimate until approved' : 'Approved'}</span></div>
        <div class="big" id="rvTotal">${peso(0)}</div></div></div>

      ${schedule}

      <details class="card optional-review">
        <summary>Customer &amp; pickup details</summary>
        ${d('organization', 'Organization')}
        ${d('phone', 'Phone')}
        ${d('address', 'Address')}
        ${d('area', 'Area', 'e.g. Bagumbayan, QC')}
        ${d('access_note', 'Access note', 'e.g. Loading is at gate 2')}
        ${d('stop_note', 'Note for the driver')}
      </details>

      <div class="err" id="rvErr"></div>
      ${pending ? `<div class="btns">
        <button class="btn danger" data-act="cancel">Cancel request</button>
        <button class="btn primary" data-act="approve" id="rvApprove">Approve &amp; schedule</button>
      </div>` : `<div class="btns"><button class="btn danger" data-act="cancel">Cancel pickup</button></div>`}
    `;
    recalcReview();
    if (pending) showCheck();
  }

  function recalcReview() {
    let total = 0;
    document.querySelectorAll('#reviewBody [data-line]').forEach(row => {
      const kg = parseFloat(row.querySelector('.rv-kg').value) || 0;
      const rate = parseFloat(row.querySelector('.rv-rate').value) || 0;
      row.querySelector('[data-line-total]').textContent = rate ? peso(kg * rate) : '—';
      total += kg * rate;
    });
    if ($('rvTotal')) $('rvTotal').textContent = peso(total);
  }

  function showCheck() {
    const box = $('rvCheck');
    if (!box) return;
    const c = rv.checks[rv.truckId];
    if (!c) { box.innerHTML = ''; return; }
    box.innerHTML = c.ok
      ? `<div class="banner ok" style="margin:0"><b>${icon('truck')}Fits this truck</b>
         Load would be ${kgText(c.projected_kg)} of ${kgText(c.capacity_kg)}.</div>`
      : `<div class="banner bad" style="margin:0"><b>${icon('alert')}Check before approving</b>${esc(c.message || '')}</div>`;
    $('rvApprove').textContent = c.ok ? 'Approve & schedule' : 'Approve anyway';
  }

  async function refreshCheck() {
    const kgChanged = [...document.querySelectorAll('#reviewBody .rv-kg')]
      .some((el, n) => parseFloat(el.value) !== rv.pickup.items[n].expected_kg);
    rv.truckId = parseInt($('rvTruck').value, 10);
    const c = await runCheck(rv.pickup.id, rv.truckId, $('rvDate').value || null, $('rvStart').value || null, $('rvEnd').value || null);
    if (c && kgChanged) c.message = (c.message || '') + ' (Based on the saved weight; it is re-checked when you approve.)';
    showCheck();
  }

  $('reviewBody').addEventListener('input', e => {
    if (e.target.matches('.rv-kg, .rv-rate')) recalcReview();
    if (e.target.matches('.rv-rate')) {
      const el = e.target;
      const row = el.closest('[data-line]');
      clearTimeout(rv.timers[row.dataset.line]);
      rv.timers[row.dataset.line] = setTimeout(async () => {
        const rate = parseFloat(el.value);
        const out = row.querySelector('[data-verdict]');
        if (!rate || rate <= 0) { out.textContent = ''; return; }
        const word = el.dataset.key || el.dataset.mat;
        try {
          const r = await api(`/prices/compare?material=${encodeURIComponent(word)}&rate=${rate}`);
          out.className = 'verdict ' + verdictClass(r.verdict);
          out.textContent = r.message || '';
        } catch (err) { out.textContent = ''; }
      }, 400);
    }
  });

  $('reviewBody').addEventListener('change', e => {
    if (e.target.matches('#rvTruck, #rvDate, #rvStart, #rvEnd')) refreshCheck();
  });

  async function suggestDriver(btn) {
    const box = $('rvAssign');
    const total = [...document.querySelectorAll('#reviewBody [data-line]')]
      .reduce((sum, row) => sum + (parseFloat(row.querySelector('.rv-kg').value) || 0), 0);
    btn.disabled = true;
    box.innerHTML = '';
    try {
      const r = await api(`/pickups/${rv.pickup.id}/suggest-driver`, {
        method: 'POST',
        body: {
          total_kg: total, pickup_date: $('rvDate').value || null,
          window_start: $('rvStart').value || null, window_end: $('rvEnd').value || null,
        },
      });
      if (r.truck_id) {
        $('rvTruck').value = r.truck_id;
        if (r.date_assumed || !$('rvDate').value) $('rvDate').value = r.pickup_date;
        if (!$('rvStart').value) $('rvStart').value = r.window_start;
        box.innerHTML = `<div class="assign-note">${icon('truck')}<span>${esc(r.note)}</span></div>`;
        await refreshCheck();
      } else {
        box.innerHTML = `<div class="banner bad" style="margin:0"><b>${icon('alert')}No driver fits</b>${esc(r.note)}</div>`;
      }
    } catch (err) {
      box.innerHTML = `<div class="err">${esc(err.message)}</div>`;
    } finally {
      btn.disabled = false;
    }
  }

  async function approveCurrent(btn) {
    const err = $('rvErr');
    err.textContent = '';
    const p = rv.pickup;
    const date = $('rvDate').value, start = $('rvStart').value, end = $('rvEnd').value;
    if (!trucks.length) { err.textContent = 'Add a truck first (More → Trucks).'; return; }
    if (!date || !start) { err.textContent = 'Choose a pickup date and a start time.'; return; }
    if (end && end <= start) { err.textContent = 'The end time must be after the start time.'; return; }

    const rows = [...document.querySelectorAll('#reviewBody [data-line]')];
    const kgs = rows.map(r => parseFloat(r.querySelector('.rv-kg').value) || 0);
    const rates = rows.map(r => parseFloat(r.querySelector('.rv-rate').value) || null);
    if (!rows.length) { err.textContent = 'This request has no materials. Cancel it and add a new one by hand.'; return; }
    for (let n = 0; n < rows.length; n++) {
      if (kgs[n] > 0 && !rates[n]) { err.textContent = `Set a rate for ${p.items[n].material}.`; return; }
    }

    btn.disabled = true;
    try {
      const fields = {};
      ['organization', 'phone', 'address', 'area', 'access_note', 'stop_note'].forEach(k => {
        const v = $('rvd_' + k).value.trim();
        if (v !== (p[k] || '')) fields[k] = v || null;
      });
      const weightsChanged = kgs.some((kg, n) => kg !== p.items[n].expected_kg);
      let pickup = p;
      if (weightsChanged || Object.keys(fields).length) {
        const body = { ...fields };
        if (weightsChanged) {
          body.items = p.items.map((i, n) => ({
            material: i.material, expected_kg: kgs[n], requested_rate: i.requested_rate,
            catalog_key: i.catalog_key || undefined,
          }));
        }
        pickup = await api('/pickups/' + p.id, { method: 'PATCH', body });
      }
      const body = {
        truck_id: parseInt($('rvTruck').value, 10),
        pickup_date: date, window_start: start, window_end: end || null,
        rates: pickup.items.map((i, n) => ({ item_id: i.id, approved_rate: rates[n] })).filter(r => r.approved_rate),
        force: false,
      };
      let approved;
      try {
        approved = await api(`/pickups/${p.id}/approve`, { method: 'POST', body });
      } catch (ex) {
        if (/force=true/.test(ex.message) &&
            confirm(ex.message.replace(' Send force=true to confirm anyway.', '') + '\n\nApprove anyway?')) {
          body.force = true;
          approved = await api(`/pickups/${p.id}/approve`, { method: 'POST', body });
        } else {
          throw ex;
        }
      }
      planDate = date;
      if (p.message_id) {
        toast('Pickup approved.' + driverNote(approved) + ' Send the customer a confirmation below.');
        openDetail(p.message_id);
      } else {
        toast('Pickup approved and scheduled.' + driverNote(approved));
        show('planning');
      }
    } catch (ex) {
      err.textContent = ex.message;
      btn.disabled = false;
    }
  }

  $('reviewBody').addEventListener('click', async e => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    if (btn.dataset.act === 'approve') return approveCurrent(btn);
    if (btn.dataset.act === 'suggest') return suggestDriver(btn);
    if (btn.dataset.act === 'cancel') {
      if (!confirm('Cancel this pickup?')) return;
      try {
        const cancelled = await api(`/pickups/${rv.pickup.id}/cancel`, { method: 'POST', body: {} });
        toast('Pickup cancelled.' + driverNote(cancelled));
        show(backTo === 'detail' ? 'inquiries' : backTo);
      } catch (ex) { toast(ex.message); }
    }
  });

  // =====================================================================
  //  PICKUP PLANNING
  // =====================================================================
  async function loadPlan() {
    if (!session || isDriver()) return;
    try {
      const d = await api('/planning/day?date=' + planDate);
      renderPlan(d);
    } catch (e) {
      $('planBody').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function renderPlan(d) {
    const s = d.summary;
    d.trucks.sort((x, y) => x.id - y.id);
    const colorOf = id => 'tcol' + (Math.max(0, d.trucks.findIndex(t => t.id === id)) % 4);
    const split = hhmm => {
      const t = time12(hhmm).split(' ');
      return t.length === 2 ? `${t[0]}<small>${t[1]}</small>` : '—';
    };

    const schedule = d.schedule.length
      ? d.schedule.map(r => `<div class="srow ${r.status === 'collected' ? 'done' : ''}">
          <div class="t">${split(r.window_start)}</div>
          <div class="bar-v ${colorOf(r.truck_id)}"></div>
          <div class="n"><b>${esc(r.customer_name)}</b>
            <span>${esc([r.driver_short, r.truck_code].filter(Boolean).join(' · ') || 'No truck')}${r.status === 'collected' ? ' · Collected' : ''}</span></div>
          <div class="kg">${kgText(r.expected_kg)}</div></div>`).join('')
      : '<div class="empty">Nothing is scheduled for this day.</div>';

    const truckCards = d.trucks.length
      ? `<div class="trucks">${d.trucks.map(t => `<div class="card truck ${t.working ? '' : 'off'}">
          <b>${esc(t.driver_short || 'No driver')}</b>
          <div class="code">${esc(t.code)} · ${esc(t.vehicle_label || t.label)}</div>
          <div class="shift ${t.working ? '' : 'off'}">${icon('clock')}${esc(t.shift_label || '')}</div>
          <div class="bar ${t.load_kg > t.capacity_kg ? 'over' : ''}"><i style="width:${Math.min(100, t.load_percent)}%"></i></div>
          <div class="cap">${kgText(t.load_kg)} / ${kgText(t.capacity_kg)}</div>
          <div class="avail">${kgText(t.available_kg)} available</div></div>`).join('')}</div>`
      : `<div class="banner"><b>${icon('truck')}No trucks yet</b>${isOwner()
          ? 'Add your trucks and drivers in More → Trucks.' : 'Ask the owner to add trucks in More → Trucks.'}</div>`;

    const queue = (d.review_queue || []).map(p => {
      const meta = [p.expected_kg ? kgText(p.expected_kg) : '', p.area].filter(Boolean).join(' · ');
      const when_ = p.pickup_date
        ? `${fmtDay(p.pickup_date)}${p.window_label ? ' · ' + p.window_label : ''}` : 'No date yet';
      const who = p.truck_id
        ? `Suggested: ${esc([p.driver_short, p.truck_code].filter(Boolean).join(' · '))}`
        : 'No driver suggested yet';
      return `<div class="card pending">
        <div class="ph"><div class="who" style="flex:1">${esc(p.customer_name)}</div>
          <span class="tag pending">${p.auto_filled ? 'Auto-filled' : 'Pending'}</span></div>
        <div class="meta">${esc(meta || p.materials)}</div>
        <div class="req">${esc(when_)}</div>
        <div class="req" style="color:${p.truck_id ? 'var(--green)' : 'var(--amber)'}">${who}</div>
        ${p.check_count ? `<div class="note">${p.check_count} thing${p.check_count === 1 ? '' : 's'} to check</div>` : ''}
        <button class="btn primary" data-act="rev" data-pid="${p.id}" style="margin-top:6px">${icon('clip')}Review &amp; approve</button>
        ${p.message_id ? `<button class="linkbtn" data-act="inq" data-mid="${p.message_id}" style="margin-top:8px">Open the customer's message</button>` : ''}
      </div>`;
    }).join('');

    const warns = d.warnings.map(w => `<div class="warn"><b>${icon('alert')}${esc(w.title)}</b>${esc(w.detail)}</div>`).join('');

    $('planBody').innerHTML = `
      <div class="card datebar">
        <button class="arrow" data-act="prev" aria-label="Previous day">${icon('chev-l')}</button>
        <button class="mid" data-act="today">${icon('cal')}${esc(fmtDay(d.date))}${d.is_today ? '<span class="today">Today</span>' : ''}</button>
        <button class="arrow" data-act="next" aria-label="Next day">${icon('chev-r')}</button>
      </div>

      <div class="hero hero-three">
        <div><b>${s.pickups}</b><span>Pickups</span></div>
        <div><b>${Number(s.to_collect_kg).toLocaleString('en-US', { maximumFractionDigits: 0 })} kg</b><span>To collect</span></div>
        <div><b>${s.drivers_assigned} / ${s.drivers_total}</b><span>Drivers assigned</span></div>
      </div>

      <div class="sect-h">Ready for review <small style="color:var(--amber)">${(d.review_queue || []).length} waiting</small></div>
      ${queue || '<div class="empty">Nothing waiting. New pickup requests from your messages appear here, already filled in.</div>'}

      <div class="sect-h">${d.is_today ? 'Today’s' : 'Day’s'} schedule <small style="color:var(--green)">${s.confirmed} confirmed</small></div>
      <div class="card sched">${schedule}</div>

      <div class="sect-h">Drivers &amp; capacity</div>
      ${truckCards}
      ${warns}
    `;
  }

  $('planBody').addEventListener('click', e => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    const a = b.dataset.act;
    if (a === 'prev') { planDate = addDays(planDate, -1); loadPlan(); }
    if (a === 'next') { planDate = addDays(planDate, 1); loadPlan(); }
    if (a === 'today') { planDate = todayStr(); loadPlan(); }
    if (a === 'rev') openReview(b.dataset.pid, 'planning');
    if (a === 'inq') openDetail(b.dataset.mid);
  });

  // =====================================================================
  //  COLLECTIONS  (the driver's day)
  // =====================================================================
  async function loadCollections() {
    if (!session) return;
    const body = $('colBody');
    try {
      let qs = 'date=' + colDate;
      if (!isDriver()) {
        const tr = await api('/planning/trucks');
        trucks = tr.trucks;
        trucks.sort((x, y) => x.id - y.id);
        if (!trucks.length) {
          body.innerHTML = `<h1 class="h1" style="margin-bottom:10px">Collections</h1>
            <div class="banner"><b>${icon('truck')}No trucks yet</b>${isOwner()
              ? 'Add a truck and a driver in More → Trucks.' : 'Ask the owner to add trucks in More → Trucks.'}</div>`;
          return;
        }
        if (!trucks.find(t => t.id === colTruckId)) colTruckId = trucks[0].id;
        qs += '&truck_id=' + colTruckId;
      }
      colData = await api('/collections/day?' + qs);
      renderCollections(colData);
    } catch (e) {
      body.innerHTML = `<h1 class="h1" style="margin-bottom:10px">Collections</h1>
        <div class="banner"><b>${icon('alert')}Nothing to show</b>${esc(e.message)}</div>`;
    }
  }

  function mapsUrl(stops) {
    const place = s => [s.address, s.area].filter(Boolean).join(', ') || s.customer_name;
    const list = stops.filter(s => s.state !== 'collected');
    if (!list.length) return null;
    const dest = place(list[list.length - 1]);
    const way = list.slice(0, -1).map(place).join('|');
    return 'https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=' +
      encodeURIComponent(dest) + (way ? '&waypoints=' + encodeURIComponent(way) : '');
  }

  function renderCollections(d) {
    const driverName = d.driver && d.driver.short_name;
    const title = isDriver()
      ? `${firstName(session.user.full_name)}’s collections`
      : `${d.driver && d.driver.name ? firstName(d.driver.name) + '’s' : d.truck.code} collections`;
    const status = { not_started: ['Not started', ''], in_progress: ['In progress', ''], completed: ['Completed', ''] }[d.route_status];
    const started = d.route_status !== 'not_started';

    const picker = !isDriver() && trucks.length > 1
      ? `<label class="field truckpick"><span>Truck</span><select id="colTruck">${trucks.map(t =>
          `<option value="${t.id}" ${t.id === colTruckId ? 'selected' : ''}>${esc(t.code)} · ${esc(t.label)}${t.driver_name ? ' · ' + esc(t.driver_name) : ''}</option>`).join('')}</select></label>`
      : '';

    const stops = d.stops.map(s => {
      const note = s.note || s.access_note || '';
      const where = [s.time_label, s.area || s.address].filter(Boolean).join(' · ');
      const nav = encodeURIComponent([s.address, s.area].filter(Boolean).join(', ') || s.customer_name);
      const tag = s.state === 'collected' ? '<span class="tag sched">Collected</span>'
        : s.state === 'up_next' ? '<span class="tag next">Up next</span>' : '<span class="tag plain">Pending</span>';
      const main = s.state === 'collected'
        ? `<button class="btn ghost" disabled>${icon('clip')}Collected · ${kgText(s.actual_kg)}</button>`
        : s.state === 'up_next'
          ? `<button class="btn primary" data-act="record" data-id="${s.id}">${icon('scale')}Record collection</button>`
          : `<button class="btn ghost" data-act="record" data-id="${s.id}">${icon('clip')}Open stop</button>`;
      return `<div class="card stop ${s.state === 'up_next' ? 'next' : ''} ${s.state === 'collected' ? 'done' : ''}">
        <div class="stop-top">
          <div class="num">${String(s.sequence).padStart(2, '0')}</div>
          <div class="n"><b>${esc(s.customer_name)}</b><span>${esc(where)}</span></div>
          ${tag}
        </div>
        <div class="expect">
          <div><small>Expected material</small><b>${esc(s.expected_material)}</b></div>
          <div class="kgbig">${kgText(s.expected_kg)}</div>
        </div>
        ${note ? `<div class="stopnote">${esc(note)}</div>` : ''}
        <div class="stop-actions">
          ${main}
          <a class="btn icon-btn ${s.phone ? '' : 'off'}" ${s.phone ? `href="tel:${esc(s.phone)}"` : ''} aria-label="Call">${icon('phone')}</a>
          <a class="btn icon-btn" href="https://www.google.com/maps/dir/?api=1&destination=${nav}" target="_blank" rel="noopener" aria-label="Navigate">${icon('nav')}</a>
        </div>
      </div>`;
    }).join('');

    const win = d.day_window
      ? `${time12(d.day_window.start)} – ${time12(d.day_window.end)}` : '';

    $('colBody').innerHTML = `
      <div class="eyebrow">${esc(fmtDay(d.date))}</div>
      <div class="titlerow"><h1 class="h1">${esc(title)}</h1></div>
      <p class="lede">Daily manifest${driverName ? ' · ' + esc(driverName) : ''} · Truck ${esc(d.truck.code)}</p>
      ${picker}

      <div class="hero rhero">
        <div class="state"><div>${icon('route')}Confirmed route</div><span class="st">${esc(status[0])}</span></div>
        <div class="stats">
          <div><b>${d.stops_total}</b><span>Stops</span></div>
          <div><b>${Number(d.expected_kg).toLocaleString('en-US', { maximumFractionDigits: 0 })} kg</b><span>Expected load</span></div>
          <div><b>${d.collected_count} / ${d.stops_total}</b><span>Collected</span></div>
        </div>
        <div class="capl"><span>${esc(d.truck.code)} · ${kgText(d.truck.capacity_kg)} capacity</span><b>${d.planned_percent}% planned</b></div>
        <div class="bar"><i style="width:${Math.min(100, d.planned_percent)}%"></i></div>
        <div class="remain">${kgText(d.remaining_capacity_kg)} remaining · ${d.collected_count ? kgText(d.collected_kg) + ' weighed' : 'Expected weights only'}</div>
      </div>

      <div class="actionbar">
        <button class="btn primary" data-act="start" ${started || !d.stops_total ? 'disabled' : ''}>${icon('play')}${started ? (d.route_status === 'completed' ? 'Route completed' : 'Route in progress') : 'Start route'}</button>
        <button class="btn ghost" data-act="map">${icon('map')}Map</button>
      </div>

      <div class="sect-h">${d.date === todayStr() ? 'Today’s' : 'Day’s'} stops <small>${esc(win)}</small></div>
      ${stops || '<div class="empty">No confirmed stops for this truck on this day.</div>'}
      <div class="hint">${icon('clip')}<span>At each stop: weigh, enter the actual kg, then mark as collected.</span></div>
    `;
  }

  $('colBody').addEventListener('change', e => {
    if (e.target.id === 'colTruck') { colTruckId = parseInt(e.target.value, 10); loadCollections(); }
  });

  $('colBody').addEventListener('click', async e => {
    const b = e.target.closest('[data-act]');
    if (!b || !colData) return;
    const a = b.dataset.act;
    if (a === 'start') {
      b.disabled = true;
      try {
        await api('/collections/route/start', {
          method: 'POST',
          body: { date: colDate, truck_id: isDriver() ? null : colTruckId },
        });
        toast('Route started.');
        loadCollections();
      } catch (err) { toast(err.message); b.disabled = false; }
    }
    if (a === 'map') {
      const url = mapsUrl(colData.stops);
      if (url) window.open(url, '_blank', 'noopener'); else toast('No remaining stops to show.');
    }
    if (a === 'record') openRecord(parseInt(b.dataset.id, 10));
  });

  // ---------- record a collection (bottom sheet) ----------
  function openSheet(html) {
    $('sheet').innerHTML = html;
    $('sheet').classList.add('show');
    $('sheetBg').classList.add('show');
  }
  function closeSheet() {
    $('sheet').classList.remove('show');
    $('sheetBg').classList.remove('show');
  }
  $('sheetBg').addEventListener('click', closeSheet);

  function openRecord(id) {
    const s = colData.stops.find(x => x.id === id);
    if (!s) return;
    const done = s.state === 'collected';
    const inputs = s.items.map(i => `<label class="field"><span>${esc(i.material)} · expected ${kgText(i.expected_kg)}</span>
      <input class="rec-kg" data-item="${i.id}" type="number" min="0" step="any" inputmode="decimal"
        value="${i.actual_kg ?? ''}" placeholder="Weighed kg" ${done ? 'disabled' : ''}></label>`).join('');
    openSheet(`
      <h3>${esc(s.customer_name)}</h3>
      <p class="muted" style="margin-bottom:12px">${esc([s.time_label, s.address || s.area].filter(Boolean).join(' · '))}</p>
      ${s.note || s.access_note ? `<div class="hint" style="margin:0 0 12px">${icon('alert')}<span>${esc(s.note || s.access_note)}</span></div>` : ''}
      ${inputs || '<div class="muted">This stop has no materials listed.</div>'}
      <div class="err" id="recErr"></div>
      <div class="btns">
        <button class="btn ghost" data-sheet="close">Close</button>
        ${done ? '' : `<button class="btn primary" data-sheet="save" data-id="${s.id}">${icon('scale')}Mark as collected</button>`}
      </div>`);
  }

  $('sheet').addEventListener('click', async e => {
    const b = e.target.closest('[data-sheet]');
    if (!b) return;
    if (b.dataset.sheet === 'close') return closeSheet();
    const items = [...document.querySelectorAll('.rec-kg')].map(el => ({
      item_id: parseInt(el.dataset.item, 10), actual_kg: parseFloat(el.value) || 0,
    }));
    if (!items.some(i => i.actual_kg > 0)) { $('recErr').textContent = 'Enter the weighed kg.'; return; }
    b.disabled = true;
    try {
      const r = await api(`/collections/stops/${b.dataset.id}/record`, { method: 'POST', body: { items } });
      closeSheet();
      const sign = r.variance_kg > 0 ? '+' : '';
      toast(`Collected. ${sign}${r.variance_kg} kg vs expected · amount due ${peso(r.amount_due)}${r.route_complete ? ' · Route complete!' : ''}`);
      loadCollections();
    } catch (err) {
      $('recErr').textContent = err.message;
      b.disabled = false;
    }
  });

  // =====================================================================
  //  MORE / SETTINGS
  // =====================================================================
  function helpHtml(title, steps, note = '') {
    return `
      <details class="channel-help">
        <summary aria-label="Help: ${esc(title)}" title="Click for step-by-step help">?</summary>
        <div class="channel-help-content">
          <strong>${esc(title)}</strong>
          <ol>${steps.map(step => `<li>${step}</li>`).join('')}</ol>
          ${note ? `<p>${note}</p>` : ''}
        </div>
      </details>`;
  }

  // the More tab: a menu of sections, each opening its own page
  let moreView = null;                       // null = the menu; otherwise the key of the open section
  const THEME_KEY = 'scrapdesk_theme';
  const MORE_TITLES = {
    trucks: 'Trucks', availability: 'Driver availability', prices: 'Price list', staff: 'Staff',
    email: 'Email inbox', sms: 'SMS · phone forwarding', twilio: 'SMS · Twilio', messenger: 'Facebook Messenger',
  };
  const OWNER_ONLY = ['trucks', 'staff', 'email', 'sms', 'twilio', 'messenger'];

  function isDarkTheme() {
    const saved = document.documentElement.getAttribute('data-theme');
    if (saved) return saved === 'dark';
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function setTheme(mode) {
    document.documentElement.setAttribute('data-theme', mode);
    try { localStorage.setItem(THEME_KEY, mode); } catch (err) { /* private mode: still applies for this visit */ }
  }

  function moreRow(o) {
    const attr = o.key ? `data-more="${o.key}"` : `data-act="${o.act}"`;
    const isSwitch = o.switchOn !== undefined;
    const right = isSwitch
      ? `<span class="swlabel">${o.switchOn ? 'On' : 'Off'}</span><span class="switch ${o.switchOn ? 'on' : ''}"></span>`
      : `${o.badge ? `<span class="mstatus ${o.badge.on ? 'on' : ''}">${esc(o.badge.text)}</span>` : ''}${icon('chev-r')}`;
    return `<button class="mrow ${o.danger ? 'danger' : ''}" ${attr}${isSwitch ? ` role="switch" aria-checked="${o.switchOn}"` : ''}>
      <span class="mico">${icon(o.ico)}</span>
      <span class="mtext"><b>${esc(o.title)}</b>${o.sub ? `<small>${esc(o.sub)}</small>` : ''}</span>${right}</button>`;
  }
  const moreGroup = (title, rows) => rows.length
    ? `<div class="section-title">${esc(title)}</div><div class="mlist">${rows.map(moreRow).join('')}</div>` : '';
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

  // Price list: the prices the shop quotes, with the survey average beside each
  let priceOpenId = null;                          // the item left open after a save
  const unitSuffix = u => (u === 'unit' ? ' each' : '/kg');
  const priceText = (n, u) => peso(n) + unitSuffix(u);

  function priceSub(i) {
    const parts = [];
    if (i.survey) {
      parts.push(`Survey avg ${peso(i.survey.average)} · ${plural(i.survey.shops, 'shop')}`);
      if (i.buy_price) {
        const pct = Math.round((i.buy_price - i.survey.average) / i.survey.average * 100);
        parts.push(pct === 0 ? 'at average' : `${pct > 0 ? '+' : ''}${pct}%`);
      }
    } else parts.push('No survey match');
    if (i.last_change && i.last_change.old != null) parts.push(`was ${peso(i.last_change.old)}`);
    return parts.join(' · ');
  }

  function surveyOptions(materials, selected, withAuto) {
    return (withAuto ? '<option value="auto">Auto-detect from the name</option>' : '') +
      '<option value="">No survey match</option>' +
      materials.map(m => `<option value="${esc(m.key)}" ${m.key === selected ? 'selected' : ''}>${esc(m.name)}${m.unit === 'unit' ? ' (each)' : ''} · avg ${esc(peso(m.average))}</option>`).join('');
  }

  function priceItemHtml(i, materials) {
    const searchText = [i.name, i.category, i.aliases].join(' ').toLowerCase();
    return `<details class="pitem ${i.is_active ? '' : 'off'}" data-search="${esc(searchText)}" data-id="${i.id}" ${priceOpenId === i.id ? 'open' : ''}>
      <summary>
        <div class="l"><b>${esc(i.name)}${i.is_active ? '' : ' · hidden'}</b><span>${esc(priceSub(i))}</span></div>
        <div class="r">${i.buy_price != null ? esc(priceText(i.buy_price, i.unit)) : '—'}
          <small>${i.sell_price != null ? 'sell ' + esc(priceText(i.sell_price, i.unit)) : 'buy price'}</small></div>
      </summary>
      <form class="pbody" data-form="priceedit" data-id="${i.id}">
        <label class="field"><span>Name</span><input class="p-name" maxlength="100" value="${esc(i.name)}" required></label>
        <div class="two">
          <label class="field"><span>We buy at (₱)</span><input class="p-buy" type="number" min="0.01" step="any" value="${i.buy_price ?? ''}"></label>
          <label class="field"><span>We sell at (₱, optional)</span><input class="p-sell" type="number" min="0.01" step="any" value="${i.sell_price ?? ''}"></label>
        </div>
        <div class="two">
          <label class="field"><span>Priced per</span><select class="p-unit"><option value="kg" ${i.unit === 'kg' ? 'selected' : ''}>kilogram</option><option value="unit" ${i.unit === 'unit' ? 'selected' : ''}>piece</option></select></label>
          <label class="field"><span>Category</span><input class="p-cat" maxlength="60" value="${esc(i.category || '')}"></label>
        </div>
        <label class="field"><span>Other names customers use</span><input class="p-alias" maxlength="300" placeholder="karton, carton" value="${esc(i.aliases || '')}"></label>
        <label class="field"><span>Compare with survey</span><select class="p-key">${surveyOptions(materials, i.catalog_key, true)}</select></label>
        <label class="field"><span>Note (optional)</span><input class="p-note" maxlength="200" placeholder="e.g. clean and dry only" value="${esc(i.note || '')}"></label>
        <button class="btn primary" type="submit" style="width:100%">Save changes</button>
        <div class="btns" style="margin-top:8px">
          <button type="button" class="btn ghost" data-act="price-history" data-id="${i.id}">Price history</button>
          <button type="button" class="btn ghost" data-act="price-toggle" data-id="${i.id}" data-active="${i.is_active ? 1 : 0}">${i.is_active ? 'Hide' : 'Show'}</button>
          <button type="button" class="btn danger" data-act="price-del" data-id="${i.id}">Delete</button>
        </div>
        <div class="phist" id="phist-${i.id}"></div>
      </form>
    </details>`;
  }

  function pricesHtml(items, materials) {
    const active = items.filter(i => i.is_active).length;
    const importBtn = label => `<button class="btn ${items.length ? 'ghost' : 'primary'}" data-act="price-import" style="width:100%">${label}</button>`;
    const groups = {};
    items.forEach(i => { (groups[i.category || 'Other'] = groups[i.category || 'Other'] || []).push(i); });
    const list = Object.keys(groups).sort().map(cat => `
      <div class="pgroup"><div class="section-title">${esc(cat)}</div>
        <div class="card">${groups[cat].map(i => priceItemHtml(i, materials)).join('')}</div></div>`).join('');

    const intro = items.length
      ? `<div class="card pad"><b>${plural(active, 'item')} on your price list</b>
          <p class="muted" style="margin:4px 0 10px">These are the prices you quote to customers. Tap an item to change its price. The survey average is shown for comparison.</p>
          <label class="card search" style="margin:0 0 8px"><svg class="ic"><use href="#i-search"/></svg><input type="search" id="priceSearch" placeholder="Search items"></label>
          <button class="linkbtn" data-act="price-import">Add missing survey items</button></div>`
      : `<div class="card pad"><b>Your price list is empty</b>
          <p class="muted" style="margin:4px 0 12px">Start with the ${materials.length} materials from the junkshop price survey, priced at the survey average. Then change any price to what you actually pay. Or add items one by one below.</p>
          ${importBtn(`Start from survey prices (${materials.length} items)`)}</div>`;

    return `${intro}
      <details class="card pad" style="margin-top:12px" ${items.length ? '' : 'open'}>
        <summary style="cursor:pointer;font-weight:700">Add an item</summary>
        <form id="priceForm" style="margin-top:12px">
          <label class="field"><span>Name</span><input id="pName" maxlength="100" placeholder="Cardboard" required></label>
          <div class="two">
            <label class="field"><span>We buy at (₱)</span><input id="pBuy" type="number" min="0.01" step="any"></label>
            <label class="field"><span>We sell at (₱, optional)</span><input id="pSell" type="number" min="0.01" step="any"></label>
          </div>
          <div class="two">
            <label class="field"><span>Priced per</span><select id="pUnit"><option value="kg">kilogram</option><option value="unit">piece</option></select></label>
            <label class="field"><span>Category</span><input id="pCat" maxlength="60" placeholder="Paper"></label>
          </div>
          <label class="field"><span>Other names customers use</span><input id="pAlias" maxlength="300" placeholder="karton, carton"></label>
          <label class="field"><span>Compare with survey</span><select id="pKey">${surveyOptions(materials, null, true)}</select></label>
          <label class="field"><span>Note (optional)</span><input id="pNote" maxlength="200"></label>
          <button class="btn primary" type="submit" style="width:100%">Add to price list</button>
        </form>
      </details>
      <div id="priceList">${list}</div>`;
  }

  function filterPriceList(q) {
    q = q.trim().toLowerCase();
    document.querySelectorAll('#priceList .pitem').forEach(el => { el.style.display = !q || el.dataset.search.includes(q) ? '' : 'none'; });
    document.querySelectorAll('#priceList .pgroup').forEach(g => {
      g.style.display = [...g.querySelectorAll('.pitem')].some(el => el.style.display !== 'none') ? '' : 'none';
    });
  }

  const numOrNull = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

  function trucksHtml(truckList, drivers) {
    const driverOpts = sel => '<option value="">No driver</option>' + drivers.map(d =>
      `<option value="${d.id}" ${d.id === sel ? 'selected' : ''}>${esc(d.full_name)}</option>`).join('');
    return `
      <div class="card">
        ${truckList.length ? truckList.map(t => `
          <div class="row" style="align-items:flex-start;flex-wrap:wrap">
            <div class="l"><b>${esc(t.code)} · ${esc(t.label)}</b><span>${esc(t.vehicle_label || '')} · ${kgText(t.capacity_kg)} capacity${t.is_active ? '' : ' · inactive'}</span></div>
            <div class="r" style="display:flex;gap:6px;align-items:center">
              <select class="truck-driver" data-id="${t.id}" style="max-width:130px;padding:6px;border:1px solid var(--border);border-radius:8px;background:var(--card);color:var(--text)">${driverOpts(t.driver_id)}</select>
              <button class="linkbtn" data-act="truck-toggle" data-id="${t.id}" data-active="${t.is_active ? 1 : 0}">${t.is_active ? 'Remove' : 'Restore'}</button>
            </div>
          </div>`).join('') : '<div class="pad muted">No trucks yet.</div>'}
      </div>
      <form id="truckForm" class="card pad" style="margin-top:12px">
        <b>Add a truck</b>
        <div class="two" style="margin-top:10px">
          <label class="field"><span>Code</span><input id="tCode" maxlength="20" placeholder="SD-01" required></label>
          <label class="field"><span>Capacity (kg)</span><input id="tCap" type="number" min="1" step="any" required></label>
        </div>
        <label class="field"><span>Label</span><input id="tLabel" maxlength="60" placeholder="Small truck" required></label>
        <label class="field"><span>Vehicle type (decides which pickups it can take)</span>
          <select id="tVehicle"><option value="">Work it out from the label</option>${Object.entries(VEHICLES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></label>
        <label class="field"><span>Driver</span><select id="tDriver">${driverOpts(null)}</select></label>
        <button class="btn primary" type="submit" style="width:100%">Add truck</button>
      </form>`;
  }

  function availabilityHtml(drivers) {
    const cards = drivers.map(d => `
      <div class="card pad" style="margin-bottom:10px">
        <b>${esc(d.driver_name)}</b>
        <span class="muted"> ${d.truck_code ? '· ' + esc(d.truck_code) : '· no truck yet'}${d.off_today ? ' · off today' : ''}</span>
        <form data-form="avail" data-driver="${d.driver_id}" style="margin-top:10px">
          <div class="two">
            <label class="field"><span>Shift starts</span><input class="av-start" type="time" value="${esc(d.shift_start)}" required></label>
            <label class="field"><span>Shift ends</span><input class="av-end" type="time" value="${esc(d.shift_end)}" required></label>
          </div>
          <div class="days">${DAY_NAMES.map((n, i) => `<label class="day"><input class="av-day" type="checkbox" value="${i + 1}" ${d.work_days.includes(i + 1) ? 'checked' : ''}><span>${n}</span></label>`).join('')}</div>
          <button class="btn ghost" type="submit" style="width:100%">Save shift</button>
        </form>
        <div class="timeoff">
          <b>Time off</b>
          ${d.time_off.length ? d.time_off.map(o => `<div class="to-row"><span>${esc(fmtDay(o.off_date))} · ${o.start_time ? esc(windowText(o.start_time, o.end_time)) : 'whole day'}${o.note ? ' · ' + esc(o.note) : ''}</span>
            <button class="linkbtn" data-act="timeoff-del" data-id="${o.id}">Remove</button></div>`).join('') : '<div class="muted">None scheduled.</div>'}
          <form data-form="timeoff" data-driver="${d.driver_id}" style="margin-top:10px">
            <label class="field"><span>Day off</span><input class="to-date" type="date" required></label>
            <div class="two">
              <label class="field"><span>From (optional)</span><input class="to-start" type="time"></label>
              <label class="field"><span>To (optional)</span><input class="to-end" type="time"></label>
            </div>
            <label class="field"><span>Note (optional)</span><input class="to-note" maxlength="200" placeholder="e.g. Sick leave"></label>
            <button class="btn ghost" type="submit" style="width:100%">Add time off</button>
          </form>
        </div>
      </div>`).join('');
    return `
      <p class="muted" style="margin-bottom:8px">Pickups are only assigned to a driver during their shift, on their working days, and never on time off. Leave the times empty on a day off to block the whole day.</p>
      ${cards || '<div class="card pad muted">Add a driver under Staff first.</div>'}`;
  }

  function staffHtml(staff) {
    return `
      <div class="card">
        ${staff.length ? staff.map(person => `
          <div class="row">
            <div class="l"><b>${esc(person.full_name)}</b><span>${esc(person.email)}</span></div>
            <div class="r">${esc(person.role)}${person.is_active ? '' : ' (off)'}</div>
          </div>`).join('') : '<div class="pad muted">No staff yet.</div>'}
      </div>
      <form id="staffForm" class="card pad" style="margin-top:12px">
        <b>Add a driver or dispatcher</b>
        <label class="field" style="margin-top:10px"><span>Full name</span><input id="stName" minlength="2" maxlength="100" required></label>
        <label class="field"><span>Email address</span><input id="stEmail" type="email" required></label>
        <label class="field"><span>Temporary password (8+ characters)</span><input id="stPass" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label>
        <label class="field"><span>Role</span><select id="stRole"><option value="driver">Driver</option><option value="dispatcher">Dispatcher</option></select></label>
        <button class="btn primary" type="submit" style="width:100%">Add staff member</button>
      </form>`;
  }

  function emailHtml(e) {
    return `
      <div class="card pad">
        <div class="channel-heading">
          <h3>Email inbox</h3>
          ${helpHtml('How to connect your email', [
            'Use the email account where your shop receives customer inquiries.',
            'Enter your email address in the Email address box below.',
            'If you use Gmail, open your <a href="https://myaccount.google.com/security" target="_blank" rel="noopener noreferrer">Google Account security settings</a>.',
            'If Google requires an App Password, turn on 2-Step Verification first, then follow the <a href="https://support.google.com/accounts/answer/185833" target="_blank" rel="noopener noreferrer">official instructions for creating an App Password</a>.',
            'Copy the App Password and enter it in the Mailbox / app password box below. Do not share it with anyone.',
            'For Gmail, leave the IMAP server as imap.gmail.com and the folder as INBOX unless your administrator tells you otherwise.',
            'Click Test and save email. Wait for the result.',
            'If the status shows Configured, click Check email now to check for new customer messages.',
          ], 'Using Outlook, Yahoo, or another email provider? The required settings may be different. If you cannot connect your account, contact your email administrator. Your email password is private; never send it to anyone in a message.')}
        </div>
        <p class="muted">Status: <b>${e.connected ? 'Configured' : 'Not connected'}</b></p>
        ${e.last_error ? `<p class="err">${esc(e.last_error)}</p>` : ''}
        ${e.last_checked_at ? `<p class="muted">Last checked: ${esc(e.last_checked_at)}</p>` : ''}
        <form id="emailSettingsForm" style="margin-top:10px">
          <label class="field"><span>IMAP server</span>
            <input id="emailHost" value="${esc(e.imap_host || 'imap.gmail.com')}" maxlength="200" required></label>
          <label class="field"><span>Email address</span>
            <input id="emailUser" type="email" value="${esc(e.imap_user || '')}" maxlength="200" required></label>
          <label class="field"><span>Mailbox / app password</span>
            <input id="emailPassword" type="password" maxlength="200" autocomplete="new-password" placeholder="Enter mailbox app password" required></label>
          <label class="field"><span>Folder</span>
            <input id="emailFolder" value="${esc(e.folder || 'INBOX')}" maxlength="100" required></label>
          <label class="field"><span>Outgoing (SMTP) server for replies — optional</span>
            <input id="emailSmtp" value="${esc(e.smtp_host || '')}" maxlength="200" placeholder="Leave empty: smtp.gmail.com is used for Gmail"></label>
          <button class="btn primary" type="submit" style="width:100%">Test and save email</button>
        </form>
        <div class="btns">
          ${e.connected ? `
            <button class="btn ghost" data-act="poll">Check email now</button>
            <button class="btn ghost" data-act="disconnect-email">Disconnect email</button>` : ''}
        </div>
      </div>
`;
  }

  function smsHtml(s) {
    return `
      <div class="card pad">
        <div class="channel-heading">
          <h3>SMS inbox — phone forwarding</h3>
          ${helpHtml('How to receive SMS messages', [
            'First, check whether your shop already has SMS forwarding set up. If you are unsure, ask your system administrator.',
            'This option requires a compatible SMS-forwarding app on the Android phone that receives your customers’ text messages.',
            'If the forwarding app has not been configured, ask your system administrator to set it up. You do not need to enter technical settings yourself.',
            'Only generate an SMS key when the person setting up the forwarding app is ready to use it.',
            'Click Generate SMS key. Copy the key and give it securely to your authorized administrator. The full key is shown only once.',
            'Ask the administrator to finish the setup and send a test text message to the phone.',
            'Open the ScrapDesk inbox and check whether the test message appears.',
          ], 'Generating a key alone does not connect your phone. If no compatible forwarding app has been configured, ask your system administrator for help. Treat the SMS key like a password.')}
        </div>
        <p class="muted">Status: <b>${s.enabled ? 'Enabled' : 'Not configured'}</b></p>
        <label class="field" style="margin-top:8px"><span>Webhook URL</span>
          <input readonly value="${esc(location.origin + (s.webhook_path || ''))}"></label>
        ${s.enabled ? `<p class="muted">Key hint: ${esc(s.key_hint || '')}</p>
          <button class="btn ghost" data-act="disconnect-sms" style="width:100%">Disable phone forwarding</button>` : ''}
        <div class="btns">
          <button class="btn primary" data-act="smskey">${s.enabled ? 'Replace SMS key' : 'Set up SMS forwarding'}</button>
        </div>
      </div>
`;
  }

  function twilioHtml(tw) {
    return `
      <div class="card pad">
        <div class="channel-heading">
          <h3>SMS inbox — Twilio</h3>
          ${helpHtml('How to connect SMS using Twilio', [
            'Ask your system administrator whether your shop already has a Twilio account and an SMS-capable phone number.',
            'If not, an authorized person must create and configure the Twilio account and obtain a suitable phone number. Messaging charges may apply.',
            'Ask your administrator to enter the Twilio Account SID, Auth Token, and phone number in the fields below.',
            'The administrator must finish connecting Twilio to ScrapDesk before customer messages can arrive.',
            'Once the administrator confirms setup is complete, send a test text message to the connected Twilio phone number.',
            'Open ScrapDesk and check whether the test message appears in the inbox.',
          ], 'You do not need to create technical settings yourself. If the account has not been configured, ask your system administrator. Never share your Twilio password or Auth Token with unauthorized people.')}
        </div>
        <p class="muted">Status: <b>${tw.connected ? 'Connected' : 'Not connected'}</b></p>
        <form id="twilioSmsSettingsForm" style="margin-top:10px">
          <label class="field"><span>Twilio Account SID</span>
            <input id="twilioAccountSid" value="${esc(tw.account_sid || '')}" minlength="34" maxlength="34" autocomplete="off" required></label>
          <label class="field"><span>Twilio Auth Token</span>
            <input id="twilioAuthToken" type="password" maxlength="200" autocomplete="new-password"
              placeholder="Enter Auth Token${tw.connected ? ' to update' : ''}" required></label>
          <label class="field"><span>Twilio phone number (international format)</span>
            <input id="twilioPhoneNumber" value="${esc(tw.phone_number || '')}" placeholder="+14155550123" minlength="9" maxlength="16" required></label>
          <button class="btn primary" type="submit">Save Twilio settings</button>
        </form>
        <label class="field" style="margin-top:12px"><span>Incoming-message webhook URL</span>
          <input readonly value="${esc(location.origin + '/webhooks/twilio/sms')}"></label>
        ${tw.connected ? '<button class="btn ghost" data-act="disconnect-twilio" style="width:100%">Disconnect Twilio</button>' : ''}
      </div>
`;
  }

  function messengerHtml(m) {
    return `
      <div class="card pad">
        <div class="channel-heading">
          <h3>Facebook Messenger</h3>
          ${helpHtml('How to connect Facebook Messenger', [
            'Make sure you have access to the Facebook Page your shop uses to communicate with customers.',
            'Ask your system administrator to connect that Page to ScrapDesk. The setup requires additional Facebook configuration.',
            'When the administrator is ready, provide the Page ID if they ask for it. You can enter it in the Facebook Page ID box below if you already have it.',
            'Click Save Facebook Page ID.',
            'Remember: saving the Page ID does not complete the entire connection. Your administrator must finish the Facebook setup before messages can be received.',
            'After your administrator confirms that everything is connected, send a test message to your shop’s Facebook Page.',
            'Open the ScrapDesk inbox and check whether the test message appears.',
          ], 'If you need help finding your Page ID or connecting Facebook, ask your system administrator. Do not share your Facebook password with anyone.')}
        </div>
        <p class="muted">Status: <b>${m.connected ? 'Page registered (webhook setup still required)' : 'Not configured'}</b></p>
        <form id="messengerSettingsForm" style="margin-top:10px">
          <label class="field"><span>Facebook Page ID</span>
            <input id="messengerPageId" value="${esc(m.page_id || '')}" minlength="3" maxlength="100" required></label>
          <label class="field"><span>Page access token — needed to reply from ScrapDesk${m.can_reply ? ' (saved)' : ''}</span>
            <input id="messengerToken" type="password" maxlength="1000" autocomplete="new-password"
              placeholder="${m.can_reply ? 'Leave empty to keep the saved token' : 'Paste the token from your Meta app'}"></label>
          <button class="btn primary" type="submit" style="width:100%">Save Facebook Page</button>
        </form>
        <label class="field" style="margin-top:12px"><span>Meta webhook callback URL</span>
          <input readonly value="${esc(location.origin + '/webhooks/messenger')}"></label>
        ${m.connected ? '<button class="btn ghost" data-act="disconnect-messenger" style="width:100%">Disconnect Page</button>' : ''}
      </div>
`;
  }

  async function renderMoreMenu() {
    const u = session.user;
    const owner = isOwner(), driver = isDriver();
    let truckList = [], staff = [], drivers = [], ch = {}, priceItems = [];
    const jobs = [];
    if (!driver) jobs.push(api('/planning/availability').then(r => { drivers = r.drivers; }));
    if (!driver) jobs.push(api('/inventory/items').then(r => { priceItems = r.items; }));
    if (owner) {
      jobs.push(api('/planning/trucks?include_inactive=true').then(r => { truckList = r.trucks; }));
      jobs.push(api('/staff').then(r => { staff = r.staff; }));
      jobs.push(api('/channels').then(r => { ch = r; }));
    }
    await Promise.allSettled(jobs);                     // a failed call just leaves that row's subtitle plain

    const e = ch.email || {}, s = ch.sms || {}, tw = ch.sms_twilio || {}, m = ch.messenger || {};
    const activeTrucks = truckList.filter(t => t.is_active).length;
    const nDrivers = staff.filter(x => x.role === 'driver' && x.is_active).length;
    const nDispatchers = staff.filter(x => x.role === 'dispatcher' && x.is_active).length;
    const offToday = drivers.filter(d => d.off_today).length;

    const management = [];
    if (owner) management.push({ key: 'trucks', ico: 'truck', title: 'Trucks & vehicles',
      sub: truckList.length ? plural(activeTrucks, 'active truck') : 'Add your first truck' });
    if (!driver) management.push({ key: 'availability', ico: 'cal', title: 'Driver availability',
      sub: drivers.length ? plural(drivers.length, 'driver') + (offToday ? ` · ${offToday} off today` : '') : 'Shifts and days off' });
    if (!driver) management.push({ key: 'prices', ico: 'scale', title: 'Price list',
      sub: priceItems.length ? `${plural(priceItems.filter(i => i.is_active).length, 'item')} · prices you quote` : 'Add items and set your prices' });
    if (owner) management.push({ key: 'staff', ico: 'users', title: 'Staff',
      sub: staff.length ? `${plural(nDrivers, 'driver')} · ${plural(nDispatchers, 'dispatcher')}` : 'Add drivers and dispatchers' });

    const connections = owner ? [
      { key: 'email', ico: 'mail', title: 'Email inbox', sub: e.imap_user || 'Receive customer emails',
        badge: { text: e.connected ? 'Connected' : 'Not set up', on: !!e.connected } },
      { key: 'sms', ico: 'phone', title: 'SMS forwarding', sub: 'Texts forwarded from a phone',
        badge: { text: s.enabled ? 'On' : 'Off', on: !!s.enabled } },
      { key: 'twilio', ico: 'chat', title: 'Twilio SMS', sub: tw.phone_number || 'Send and receive texts',
        badge: { text: tw.connected ? 'Connected' : 'Not set up', on: !!tw.connected } },
      { key: 'messenger', ico: 'messenger', title: 'Messenger', sub: 'Chats from your Facebook Page',
        badge: { text: m.connected ? 'Connected' : 'Not set up', on: !!m.connected } },
    ] : [];

    $('moreBody').innerHTML = `
      <div class="mprofile">
        <div class="mava">${esc(initials(u.full_name))}</div>
        <div class="mwho"><b>${esc(u.full_name)}</b><span>${esc(u.email)}</span>
          <em>${esc(u.role)} · ${esc(session.shop.name)}</em></div>
      </div>
      ${moreGroup('Management', management)}
      ${moreGroup('Connections', connections)}
      ${moreGroup('Preferences', [{ act: 'theme', ico: 'moon', title: 'Dark mode', sub: 'Easier on the eyes at night', switchOn: isDarkTheme() }])}
      ${moreGroup('Account', [{ act: 'logout', ico: 'logout', title: 'Log out', danger: true }])}`;
  }

  async function renderMoreSection(key) {
    const head = `<div class="subhead"><button class="back" data-more="menu" aria-label="Back">${icon('back')}</button>
      <h1 class="h1">${esc(MORE_TITLES[key])}</h1></div>`;
    if ((OWNER_ONLY.includes(key) && !isOwner()) || ((key === 'availability' || key === 'prices') && isDriver())) {
      moreView = null;
      return renderMoreMenu();
    }
    $('moreBody').innerHTML = head + '<div class="empty">Loading…</div>';
    let body = '';
    try {
      if (key === 'trucks') {
        const [tr, st] = await Promise.all([api('/planning/trucks?include_inactive=true'), api('/staff')]);
        body = trucksHtml(tr.trucks, st.staff.filter(x => x.role === 'driver' && x.is_active));
      } else if (key === 'availability') {
        body = availabilityHtml((await api('/planning/availability')).drivers);
      } else if (key === 'prices') {
        const [inv, sv] = await Promise.all([api('/inventory/items'), api('/prices/materials')]);
        body = pricesHtml(inv.items, sv.materials);
      } else if (key === 'staff') {
        body = staffHtml((await api('/staff')).staff);
      } else {
        const ch = await api('/channels');
        body = {
          email: () => emailHtml(ch.email || { connected: false }),
          sms: () => smsHtml(ch.sms || { enabled: false, webhook_path: '/webhooks/sms' }),
          twilio: () => twilioHtml(ch.sms_twilio || { connected: false, phone_number: '', account_sid: '' }),
          messenger: () => messengerHtml(ch.messenger || { connected: false }),
        }[key]();
      }
    } catch (err) {
      body = `<div class="card pad"><p class="err">Unable to load this page: ${esc(err.message)}</p></div>`;
    }
    $('moreBody').innerHTML = head + body;
  }

  async function loadMore() {
    if (!session) return;
    const title = document.querySelector('#more > .h1');       // the big "More" title belongs to the menu only
    if (title) title.style.display = moreView ? 'none' : '';
    if (moreView) await renderMoreSection(moreView); else await renderMoreMenu();
  }

  // Settings forms are rendered dynamically, so listen on their parent.
  $('moreBody').addEventListener('submit', async e => {
    const form = e.target;
    const supported = ['emailSettingsForm', 'messengerSettingsForm', 'twilioSmsSettingsForm', 'truckForm', 'staffForm', 'priceForm'];
    const dynamic = form.dataset.form;                    // 'avail' and 'timeoff' forms, one per driver
    if (!supported.includes(form.id) && !dynamic) return;
    e.preventDefault();
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;

    try {
      if (dynamic === 'priceedit') {
        const q = sel => form.querySelector(sel);
        const id = parseInt(form.dataset.id, 10);
        await api('/inventory/items/' + id, {
          method: 'PATCH',
          body: {
            name: q('.p-name').value.trim(), category: q('.p-cat').value.trim() || null, unit: q('.p-unit').value,
            buy_price: numOrNull(q('.p-buy').value), sell_price: numOrNull(q('.p-sell').value),
            catalog_key: q('.p-key').value, aliases: q('.p-alias').value.trim() || null, note: q('.p-note').value.trim() || null,
          },
        });
        priceOpenId = id;
        toast('Price list updated.');
      } else if (form.id === 'priceForm') {
        await api('/inventory/items', {
          method: 'POST',
          body: {
            name: $('pName').value.trim(), category: $('pCat').value.trim() || null, unit: $('pUnit').value,
            buy_price: numOrNull($('pBuy').value), sell_price: numOrNull($('pSell').value),
            catalog_key: $('pKey').value, aliases: $('pAlias').value.trim() || null, note: $('pNote').value.trim() || null,
          },
        });
        toast('Item added to your price list.');
      } else if (dynamic === 'avail') {
      } else if (dynamic === 'timeoff') {
        await api(`/planning/availability/${form.dataset.driver}/time-off`, {
          method: 'POST',
          body: {
            off_date: form.querySelector('.to-date').value,
            start_time: form.querySelector('.to-start').value || null,
            end_time: form.querySelector('.to-end').value || null,
            note: form.querySelector('.to-note').value.trim() || null,
          },
        });
        toast('Time off added.');
      } else if (form.id === 'emailSettingsForm') {
        await api('/channels/email', {
          method: 'PUT',
          body: {
            imap_host: $('emailHost').value.trim(),
            imap_user: $('emailUser').value.trim(),
            imap_password: $('emailPassword').value,
            folder: $('emailFolder').value.trim() || 'INBOX',
            smtp_host: $('emailSmtp').value.trim() || null,
          },
        });
        toast('Email tested and saved.');
      } else if (form.id === 'messengerSettingsForm') {
        await api('/channels/messenger', {
          method: 'PUT',
          body: { page_id: $('messengerPageId').value.trim(), page_access_token: $('messengerToken').value.trim() || null },
        });
        toast('Facebook Page saved. Complete Meta webhook setup to receive messages.');
      } else if (form.id === 'twilioSmsSettingsForm') {
        await api('/channels/sms/twilio', {
          method: 'PUT',
          body: {
            account_sid: $('twilioAccountSid').value.trim(),
            auth_token: $('twilioAuthToken').value.trim(),
            phone_number: $('twilioPhoneNumber').value.trim(),
          },
        });
        toast('Twilio settings saved. Finish the incoming-message webhook setup in Twilio.');
      } else if (form.id === 'truckForm') {
        await api('/planning/trucks', {
          method: 'POST',
          body: {
            code: $('tCode').value.trim(),
            label: $('tLabel').value.trim(),
            capacity_kg: parseFloat($('tCap').value),
            vehicle_type: $('tVehicle').value || null,
            driver_id: $('tDriver').value ? parseInt($('tDriver').value, 10) : null,
          },
        });
        toast('Truck added.');
      } else if (form.id === 'staffForm') {
        await api('/staff', {
          method: 'POST',
          body: {
            full_name: $('stName').value.trim(),
            email: $('stEmail').value.trim(),
            password: $('stPass').value,
            role: $('stRole').value,
          },
        });
        toast('Staff member added.');
      }
      await loadMore();
    } catch (err) {
      toast(err.message);
    } finally {
      if (button) button.disabled = false;
    }
  });

  $('moreBody').addEventListener('change', async e => {
    if (!e.target.classList.contains('truck-driver')) return;
    try {
      await api('/planning/trucks/' + e.target.dataset.id, {
        method: 'PATCH',
        body: { driver_id: e.target.value ? parseInt(e.target.value, 10) : null },
      });
      toast('Driver updated.');
    } catch (err) {
      toast(err.message);
      loadMore();
    }
  });

  $('moreBody').addEventListener('input', e => { if (e.target.id === 'priceSearch') filterPriceList(e.target.value); });

  // One click handler for the whole More tab.
  $('moreBody').addEventListener('click', async e => {
    const go = e.target.closest('[data-more]');              
    if (go) {
      moreView = go.dataset.more === 'menu' ? null : go.dataset.more;
      $('screens').scrollTo({ top: 0 });
      return loadMore();
    }
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;

    try {
      if (act === 'theme') {
        setTheme(isDarkTheme() ? 'light' : 'dark');
        const on = isDarkTheme();
        btn.setAttribute('aria-checked', on);
        btn.querySelector('.switch').classList.toggle('on', on);
        btn.querySelector('.swlabel').textContent = on ? 'On' : 'Off';

      } else if (act === 'logout') {
        try { await api('/auth/logout', { method: 'POST' }); } catch (x) { /* clear local session anyway */ }
        logoutLocal();

      } else if (act === 'poll') {
        const r = await api('/channels/email/poll-now', { method: 'POST' });
        toast(r.error ? 'Email check failed: ' + r.error : `Mailbox checked. New messages: ${r.new ?? 0}`);
        await loadMore();

      } else if (act === 'timeoff-del') {
        await api('/planning/time-off/' + btn.dataset.id, { method: 'DELETE' });
        toast('Time off removed.');
        await loadMore();

      } else if (act === 'smskey') {
        if (!confirm('Generate or replace the SMS key? Any old forwarding setup will stop working.')) return;
        const r = await api('/channels/sms/key', { method: 'POST' });
        prompt('Copy and save this key now. It is shown only once.\nWebhook: ' + location.origin + r.webhook_path +
          '\nSend the key in the X-API-Key header.', r.sms_key);
        toast('SMS key generated. Configure your SMS-forwarding app to receive messages.');
        await loadMore();

      } else if (act === 'disconnect-twilio') {
        if (!confirm('Disconnect the Twilio SMS gateway?')) return;
        await api('/channels/sms/twilio', { method: 'DELETE' });
        toast('Twilio disconnected.');
        await loadMore();

      } else if (act === 'price-import') {
        const r = await api('/inventory/import-survey', { method: 'POST' });
        toast(r.added ? `Added ${plural(r.added, 'item')} from the survey. Adjust any price to what you pay.`
                      : 'Nothing new to add. Every surveyed item is already on your list.');
        await loadMore();

      } else if (act === 'price-toggle') {
        const on = btn.dataset.active === '1';
        await api('/inventory/items/' + btn.dataset.id, { method: 'PATCH', body: { is_active: !on } });
        priceOpenId = parseInt(btn.dataset.id, 10);
        toast(on ? 'Hidden. It will not be quoted in replies.' : 'Showing again.');
        await loadMore();

      } else if (act === 'price-del') {
        if (!confirm('Delete this item from your price list? Its price history is deleted too.')) return;
        await api('/inventory/items/' + btn.dataset.id, { method: 'DELETE' });
        toast('Item deleted.');
        await loadMore();

      } else if (act === 'price-history') {
        const box = $('phist-' + btn.dataset.id);
        const r = await api(`/inventory/items/${btn.dataset.id}/history`);
        box.innerHTML = r.history.length
          ? r.history.map(h => `<div>${esc(fmtDay(h.changed_at.slice(0, 10)))} · ${h.field === 'buy_price' ? 'Buy' : 'Sell'}: ${h.old_value != null ? esc(peso(h.old_value)) : 'none'} → ${h.new_value != null ? esc(peso(h.new_value)) : 'none'}${h.changed_by ? ' · ' + esc(h.changed_by) : ''}</div>`).join('')
          : 'No price changes yet.';

      } else if (act === 'truck-toggle') {
        const active = btn.dataset.active === '1';
        if (active && !confirm('Remove this truck from planning?')) return;
        await api('/planning/trucks/' + btn.dataset.id, { method: 'PATCH', body: { is_active: !active } });
        toast(active ? 'Truck removed.' : 'Truck restored.');
        await loadMore();

      } else if (['disconnect-email', 'disconnect-sms', 'disconnect-messenger'].includes(act)) {
        const config = {
          'disconnect-email': ['/channels/email', 'Disconnect the email mailbox?'],
          'disconnect-sms': ['/channels/sms', 'Disable SMS and invalidate its key?'],
          'disconnect-messenger': ['/channels/messenger', 'Disconnect this Facebook Page?'],
        }[act];
        if (!confirm(config[1])) return;
        await api(config[0], { method: 'DELETE' });
        toast('Channel disconnected.');
        await loadMore();
      }
    } catch (err) {
      toast(err.message);
    }
  });

  // ---------- boot ----------
  (async function boot() {
    if (!session) return show('login');
    try {
      await api('/auth/me');
      enterApp();
    } catch (e) {
      show('login');
    }
  })();
})();