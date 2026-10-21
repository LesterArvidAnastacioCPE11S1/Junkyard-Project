
(function () {
  'use strict';

  const KEY = 'scrapdesk_session';
  const MATERIALS = ['Plastic', 'Paper', 'Cardboard', 'Aluminum', 'Other_Metals', 'Glass', 'Electronic_Waste'];
  const INTENTS = {
    Price_Inquiry: 'Price inquiry',
    Pickup_Request: 'Pickup request',
    Bulk_Negotiation: 'Bulk negotiation',
    Other: 'Other / unrelated',
  };
  const ITAG = { Price_Inquiry: 'price', Pickup_Request: 'pickup', Bulk_Negotiation: 'bulk', Other: 'other' };

  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pretty = s => String(s).replace(/_/g, ' ');
  const shorten = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
  const effIntent = m => m.corrected_intent || m.intent;
  const effMaterials = m => m.corrected_materials || (m.materials ? m.materials.labels : []);

  let session = null;
  try {
    session = JSON.parse(localStorage.getItem(KEY));
  } catch (e) {
    session = null;
  }

  let inbox = [], filter = 'all', current = null, selMats = new Set();

  // ---------- helpers ----------
  function when(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toDateString() === new Date().toDateString()
      ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
      : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  let toastTimer;
  function toast(msg) {
    const t = $('toast');
    if (!t) {
      console.log(msg);
      return;
    }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
  }

  function errText(data) {
    if (!data || !data.detail) return '';
    return Array.isArray(data.detail)
      ? data.detail.map(d => d.msg).join(' ')
      : String(data.detail);
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
    try {
      data = await res.json();
    } catch (e) {
      // Some responses have no JSON body.
    }

    if (res.status === 401 && session) {
      logoutLocal();
      throw new Error('Session expired. Please log in again.');
    }

    if (!res.ok) {
      throw new Error(errText(data) || 'Request failed (' + res.status + ')');
    }

    return data;
  }

  // ---------- navigation ----------
  function show(id) {
    document.querySelectorAll('.screen').forEach(s => {
      s.classList.toggle('active', s.id === id);
    });

    const tab = (id === 'detail' || id === 'compose') ? 'inquiries' : id;

    document.querySelectorAll('nav button').forEach(b => {
      b.classList.toggle('active', b.dataset.nav === tab);
    });

    $('nav').style.display =
      (id === 'login' || id === 'signup') ? 'none' : '';

    $('screens').scrollTo({ top: 0 });

    if (id === 'inquiries') loadInbox();
    if (id === 'more') loadMore();
  }

  document.querySelectorAll('nav button').forEach(b => {
    b.addEventListener('click', () => {
      if (document.getElementById(b.dataset.nav)) {
        show(b.dataset.nav);
      } else {
        toast('This screen has not been implemented yet.');
      }
    });
  });

  $('backBtn').addEventListener('click', () => show('inquiries'));
  $('composeBack').addEventListener('click', () => show('inquiries'));
  $('addBtn').addEventListener('click', () => show('compose'));

  // ---------- login / logout ----------
  function logoutLocal() {
    session = null;
    localStorage.removeItem(KEY);
    show('login');
  }

  function enterApp() {
    document.querySelectorAll('[data-shop]').forEach(el => {
      el.textContent = session.shop.name;
    });

    const initials = session.user.full_name
      .split(/\s+/)
      .map(w => w[0])
      .slice(0, 2)
      .join('')
      .toUpperCase();

    document.querySelectorAll('[data-avatar]').forEach(el => {
      el.textContent = initials;
    });

    const driver = session.user.role === 'driver';

    document.querySelectorAll('nav button').forEach(b => {
      b.style.display =
        driver && ['inquiries', 'planning'].includes(b.dataset.nav)
          ? 'none'
          : '';
    });

    show(driver ? 'collections' : 'inquiries');
  }

  $('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    $('loginErr').textContent = '';

    try {
      const r = await api('/auth/login', {
        method: 'POST',
        body: {
          email: $('lEmail').value.trim(),
          password: $('lPass').value,
          device_name: 'Web app',
        },
      });

      session = { token: r.token, user: r.user, shop: r.shop };
      localStorage.setItem(KEY, JSON.stringify(session));

      $('lPass').value = '';
      enterApp();
    } catch (err) {
      $('loginErr').textContent = err.message;
    }
  });

  // ---------- registration ----------
  $('showSignup').addEventListener('click', () => {
    $('signupErr').textContent = '';
    show('signup');
  });

  $('showLogin').addEventListener('click', () => {
    $('loginErr').textContent = '';
    show('login');
  });

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

  // ---------- inbox list ----------
  function itagHtml(intent) {
    return `<span class="itag ${ITAG[intent] || 'other'}">${esc(INTENTS[intent] || intent)}</span>`;
  }

  function headTag(m) {
    return (m.needs_review && m.status === 'new')
      ? '<span class="tag review">Needs review</span>'
      : itagHtml(effIntent(m));
  }

  function materialsText(m) {
    if (effIntent(m) === 'Other') return '';
    const labels = effMaterials(m);
    return labels.length ? labels.map(pretty).join(', ') : '';
  }

  function card(m) {
    const meta = [
      INTENTS[effIntent(m)] || effIntent(m),
      materialsText(m),
      m.channel,
      when(m.received_at),
    ].filter(Boolean).join(' · ');

    return `<button class="card inq" data-id="${m.id}">
      <div class="inq-head">
        <span class="inq-name">
          ${m.status === 'new' ? '<span class="unread"></span>' : ''}
          ${esc(m.sender)}
        </span>
        ${headTag(m)}
      </div>
      <div class="inq-msg">${esc(shorten(m.subject || m.text, 90))}</div>
      <div class="inq-meta">${esc(meta)}</div>
    </button>`;
  }

  function renderList() {
    const q = $('searchInput').value.trim().toLowerCase();

    const rows = inbox.filter(m => {
      const intent = effIntent(m);

      if (filter === 'all') {
        if (intent === 'Other') return false;
      } else if (filter === 'review') {
        if (!(m.needs_review && m.status === 'new')) return false;
      } else if (intent !== filter) {
        return false;
      }

      return !q ||
        [m.text, m.subject, m.sender]
          .join(' ')
          .toLowerCase()
          .includes(q);
    });

    $('inqList').innerHTML = rows.length
      ? rows.map(card).join('')
      : '<div class="empty">No messages here yet.</div>';
  }

  function renderStats(stats) {
    const by = stats.by_intent || {};
    const open = stats.total - (by.Other || 0);

    $('mOpen').textContent = open;
    $('mPickup').textContent = by.Pickup_Request || 0;
    $('mReview').textContent = stats.pending_review;
    $('mBulk').textContent = by.Bulk_Negotiation || 0;

    const counts = {
      all: open,
      review: stats.pending_review,
      Price_Inquiry: by.Price_Inquiry || 0,
      Pickup_Request: by.Pickup_Request || 0,
      Bulk_Negotiation: by.Bulk_Negotiation || 0,
      Other: by.Other || 0,
    };

    document.querySelectorAll('[data-count]').forEach(el => {
      el.textContent = counts[el.dataset.count] ?? 0;
    });

    $('navBadge').textContent = stats.pending_review;
    $('navBadge').style.display = stats.pending_review ? '' : 'none';
  }

  async function loadInbox() {
    if (!session || session.user.role === 'driver') return;

    try {
      const [stats, list] = await Promise.all([
        api('/inbox/stats'),
        api('/inbox?limit=200'),
      ]);

      inbox = list.messages;
      renderStats(stats);
      renderList();
    } catch (e) {
      if (session) toast(e.message);
    }
  }

  $('inqList').addEventListener('click', e => {
    const c = e.target.closest('.inq');
    if (c) openDetail(c.dataset.id);
  });

  $('pills').addEventListener('click', e => {
    const p = e.target.closest('.pill');
    if (!p) return;

    document.querySelectorAll('.pill').forEach(x => {
      x.classList.remove('active');
    });

    p.classList.add('active');
    filter = p.dataset.filter;
    renderList();
  });

  $('searchInput').addEventListener('input', renderList);

  setInterval(() => {
    if (
      session &&
      !document.hidden &&
      $('inquiries').classList.contains('active')
    ) {
      loadInbox();
    }
  }, 10000);

  // ---------- detail + human review ----------
  async function openDetail(id) {
    show('detail');
    $('detailTitle').textContent = 'Inquiry';
    $('detailTag').innerHTML = '';
    $('detailBody').innerHTML = '<div class="empty">Loading…</div>';

    try {
      current = await api('/inbox/' + id);
      renderDetail();
    } catch (e) {
      $('detailBody').innerHTML =
        `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function renderDetail() {
    const m = current;
    const intent = effIntent(m);
    const conf = Math.round((m.intent_confidence || 0) * 100);
    const reviewed = m.status !== 'new';
    const matches = (m.materials && m.materials.matches) || [];

    selMats = new Set(effMaterials(m).filter(l => l !== 'Unknown'));

    $('detailTitle').textContent = m.sender;
    $('detailTag').innerHTML = headTag(m);

    let banner = '';

    if (reviewed) {
      banner = m.status === 'corrected'
        ? '<div class="banner"><b>Corrected by staff</b>Your correction replaced the model’s prediction.</div>'
        : '<div class="banner"><b>Confirmed by staff</b>You confirmed the model’s prediction.</div>';
    } else if (m.needs_review) {
      banner = '<div class="banner"><b>Please double-check</b>The model isn’t sure about this message. Confirm it or correct the labels below.</div>';
    }

    let matHtml;

    if (!m.materials) {
      matHtml = '<div class="pad muted">Not checked: this isn’t a customer inquiry.</div>';
    } else if (!matches.length) {
      matHtml = '<div class="pad muted">No recyclable material recognised.</div>';
    } else {
      matHtml = matches.map(x =>
        `<div class="row">
          <div class="l">
            <b>${esc(pretty(x.label))}</b>
            <span>“${esc(x.evidence)}”</span>
          </div>
          <div class="r">${Math.round(x.confidence * 100)}%</div>
        </div>`
      ).join('');
    }

    const intentOpts = Object.keys(INTENTS)
      .map(k => `<option value="${k}" ${k === intent ? 'selected' : ''}>${esc(INTENTS[k])}</option>`)
      .join('');

    const chips = MATERIALS
      .map(k =>
        `<button type="button" class="chip ${selMats.has(k) ? 'on' : ''}" data-mat="${k}">${esc(pretty(k))}</button>`
      )
      .join('');

    $('detailBody').innerHTML = `
      ${banner}

      <div class="section-title">What the customer wants</div>
      <div class="card pad">
        ${itagHtml(intent)}
        ${m.corrected_intent
          ? `<div class="muted" style="margin-top:6px">Model predicted: ${esc(INTENTS[m.intent] || m.intent)}</div>`
          : ''}
        <div class="muted" style="margin-top:10px">Model confidence · ${conf}%</div>
        <div class="conf ${conf < 50 ? 'low' : ''}">
          <i style="width:${conf}%"></i>
        </div>
      </div>

      <div class="section-title">Materials detected</div>
      <div class="card">${matHtml}</div>

      <div class="section-title">Message</div>
      <div class="card">
        <div class="bubble">
          ${m.subject ? `<b>${esc(m.subject)}</b><br>` : ''}
          ${esc(m.text)}
          <small>${esc(m.sender)} · ${esc(m.channel)} · ${esc(when(m.received_at))}</small>
        </div>
      </div>

      <div class="section-title">Your review</div>
      <div class="card">
        <div class="pad">
          <label class="field" style="margin:0">
            <span>Intent</span>
            <select id="revIntent">${intentOpts}</select>
          </label>
        </div>
        <div class="muted" style="padding:0 14px">Materials (leave empty if unknown)</div>
        <div class="chips">${chips}</div>
      </div>

      <div class="btns">
        <button class="btn ghost" data-act="confirm">Confirm as is</button>
        <button class="btn primary" data-act="save">Save review</button>
      </div>

      <p class="muted" style="margin-top:12px;text-align:center">
        Quantities, prices and pickup details aren’t extracted yet.
      </p>`;
  }

  async function submitReview(confirmOnly, btn) {
    btn.disabled = true;

    try {
      const body = {};

      if (!confirmOnly) {
        const intent = $('revIntent').value;
        body.intent = intent;

        if (intent !== 'Other') {
          body.materials = selMats.size ? [...selMats] : ['Unknown'];
        }
      }

      current = await api(`/inbox/${current.id}/review`, {
        method: 'PATCH',
        body,
      });

      renderDetail();
      toast(current.status === 'corrected' ? 'Correction saved' : 'Confirmed');
      loadInbox();
    } catch (err) {
      toast(err.message);
      btn.disabled = false;
    }
  }

  $('detailBody').addEventListener('click', e => {
    const chip = e.target.closest('.chip');

    if (chip) {
      const k = chip.dataset.mat;
      if (selMats.has(k)) selMats.delete(k);
      else selMats.add(k);
      chip.classList.toggle('on');
      return;
    }

    const btn = e.target.closest('[data-act]');
    if (btn) submitReview(btn.dataset.act === 'confirm', btn);
  });

  // ---------- add a message manually ----------
  $('composeForm').addEventListener('submit', async e => {
    e.preventDefault();

    const text = $('cText').value.trim();
    if (!text) return;

    const btn = e.target.querySelector('button[type=submit]');
    btn.disabled = true;

    try {
      const r = await api('/inbox/ingest', {
        method: 'POST',
        body: {
          channel: 'manual',
          sender: $('cSender').value.trim() || 'Walk-in',
          text,
        },
      });

      $('cText').value = '';
      toast(r.created ? 'Message classified' : 'Already stored');
      openDetail(r.message.id);
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // ---------- More tab / Settings ----------
  async function loadMore() {
    if (!session) return;

    const u = session.user;
    const el = $('moreBody');

    let html = `
      <div class="section-title">Account</div>
      <div class="card pad">
        <b>${esc(u.full_name)}</b>
        <div class="muted">${esc(u.email)} · ${esc(u.role)} · ${esc(session.shop.name)}</div>
      </div>`;

    if (u.role === 'owner') {
      try {
        const ch = await api('/channels');
        const e = ch.email || { connected: false };
        const s = ch.sms || { enabled: false, webhook_path: '/webhooks/sms' };
        const m = ch.messenger || { connected: false };

        html += `
          <div class="section-title">Connected message channels</div>

          <div class="card pad">
            <h3>Email inbox</h3>
            <p class="muted">Status: <b>${e.connected ? 'Configured' : 'Not connected'}</b></p>
            ${e.last_error ? `<p class="err">${esc(e.last_error)}</p>` : ''}
            ${e.last_checked_at ? `<p class="muted">Last checked: ${esc(e.last_checked_at)}</p>` : ''}

            <form id="emailSettingsForm">
              <label class="field">
                <span>IMAP server</span>
                <input id="emailHost" value="${esc(e.imap_host || 'imap.gmail.com')}" maxlength="200" required>
              </label>
              <label class="field">
                <span>Email address</span>
                <input id="emailUser" type="email" value="${esc(e.imap_user || '')}" maxlength="200" required>
              </label>
              <label class="field">
                <span>Mailbox password / app password</span>
                <input id="emailPassword" type="password" maxlength="200" autocomplete="new-password" placeholder="Enter mailbox password" required>
              </label>
              <label class="field">
                <span>Folder</span>
                <input id="emailFolder" value="${esc(e.folder || 'INBOX')}" maxlength="100" required>
              </label>
              <button class="btn primary" type="submit">Test and save email</button>
            </form>

            <p class="muted">
              Gmail usually requires an App Password with 2-Step Verification enabled.
              Never use your normal Gmail password if Google requires an App Password.
            </p>

            <div class="btns">
              ${e.connected
                ? '<button class="btn ghost" data-act="poll">Check email now</button><button class="btn ghost" data-act="disconnect-email">Disconnect email</button>'
                : ''}
            </div>
          </div>

          <div class="card pad" style="margin-top:14px">
            <h3>SMS inbox</h3>
            <p class="muted">Status: <b>${s.enabled ? 'Enabled' : 'Not configured'}</b></p>

            <label class="field">
              <span>Webhook path</span>
              <input readonly value="${esc(s.webhook_path || '')}">
            </label>

            <p class="muted">
              Webhook URL:
              <code>${esc(location.origin + (s.webhook_path || ''))}</code>
            </p>

            ${s.enabled
              ? `<p class="muted">Key hint: ${esc(s.key_hint || '')}</p>
                 <button class="btn ghost" data-act="disconnect-sms">Disable SMS</button>`
              : ''}

            <div class="btns">
              <button class="btn primary" data-act="smskey">
                ${s.enabled ? 'Replace SMS key' : 'Generate SMS key'}
              </button>
            </div>

            <p class="muted">
              The full key is shown only once. Copy it securely to your SMS forwarding
              app or gateway. The forwarder must POST JSON containing a sender and
              message text to the webhook URL, using the X-API-Key header.
            </p>
          </div>

          <div class="card pad" style="margin-top:14px">
            <h3>Facebook Messenger</h3>
            <p class="muted">
              Status:
              <b>${m.connected ? 'Page registered (webhook setup still required)' : 'Not configured'}</b>
            </p>

            <form id="messengerSettingsForm">
              <label class="field">
                <span>Facebook Page ID</span>
                <input id="messengerPageId" value="${esc(m.page_id || '')}" minlength="3" maxlength="100" required>
              </label>
              <button class="btn primary" type="submit">Save Facebook Page ID</button>
            </form>

            <label class="field">
              <span>Meta webhook callback URL</span>
              <input readonly value="${esc(location.origin + '/webhooks/messenger')}">
            </label>

            <p class="muted">
              For real messages, configure a Meta developer app, HTTPS public callback,
              verify token, app secret, and Page messaging subscriptions. Saving a
              Page ID alone does not connect Messenger.
            </p>

            ${m.connected
              ? '<button class="btn ghost" data-act="disconnect-messenger">Disconnect Page</button>'
              : ''}
          </div>`;
      } catch (err) {
        html += `
          <div class="card pad">
            <p class="err">Unable to load channel settings: ${esc(err.message)}</p>
          </div>`;
      }

      try {
        const st = await api('/staff');

        html += '<div class="section-title">Staff</div><div class="card">' +
          (st.staff.length
            ? st.staff.map(p => `
                <div class="row">
                  <div class="l">
                    <b>${esc(p.full_name)}</b>
                    <span>${esc(p.email)}</span>
                  </div>
                  <div class="r">${esc(p.role)}${p.is_active ? '' : ' (off)'}</div>
                </div>`
              ).join('')
            : '<div class="pad muted">No staff yet.</div>') +
          '</div>';
      } catch (err) {
        // Staff list is optional.
      }
    }

    html += `
      <div class="btns" style="margin-top:16px">
        <button class="btn ghost" data-act="logout">Log out</button>
      </div>`;

    el.innerHTML = html;
  }

  // Settings forms are rendered dynamically, so listen on their parent.
  $('moreBody').addEventListener('submit', async e => {
    const form = e.target;

    if (!['emailSettingsForm', 'messengerSettingsForm'].includes(form.id)) return;

    e.preventDefault();

    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;

    try {
      if (form.id === 'emailSettingsForm') {
        await api('/channels/email', {
          method: 'PUT',
          body: {
            imap_host: $('emailHost').value.trim(),
            imap_user: $('emailUser').value.trim(),
            imap_password: $('emailPassword').value,
            folder: $('emailFolder').value.trim() || 'INBOX',
          },
        });

        toast('Email tested and saved.');
      } else {
        await api('/channels/messenger', {
          method: 'PUT',
          body: {
            page_id: $('messengerPageId').value.trim(),
          },
        });

        toast('Facebook Page ID saved. Complete Meta webhook setup to receive messages.');
      }

      await loadMore();
    } catch (err) {
      toast(err.message);
    } finally {
      button.disabled = false;
    }
  });

  $('moreBody').addEventListener('click', async e => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;

    const act = btn.dataset.act;

    try {
      if (act === 'logout') {
        try {
          await api('/auth/logout', { method: 'POST' });
        } catch (x) {
          // Clear local session even if the server logout fails.
        }
        logoutLocal();

      } else if (act === 'poll') {
        const r = await api('/channels/email/poll-now', { method: 'POST' });

        toast(
          r.error
            ? 'Email check failed: ' + r.error
            : `Mailbox checked. New messages: ${r.new ?? 0}`
        );

        await loadInbox();
        await loadMore();

      } else if (act === 'smskey') {
        if (!confirm('Generate or replace the SMS key? Any old forwarding setup will stop working.')) {
          return;
        }

        const r = await api('/channels/sms/key', { method: 'POST' });

        prompt(
          'Copy and save this key now. It is shown only once.\n' +
          'Webhook: ' + location.origin + r.webhook_path +
          '\nSend the key in the X-API-Key header.',
          r.sms_key
        );

        toast('SMS key generated. Connect an SMS forwarding service to receive messages.');
        await loadMore();

      } else if (
        ['disconnect-email', 'disconnect-sms', 'disconnect-messenger'].includes(act)
      ) {
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

  // ---------- Start-route toggle ----------
  const start = $('startRoute');
  const state = document.querySelector('.hero .state span:last-child');

  if (start && state) {
    start.addEventListener('click', () => {
      const started = start.dataset.started === '1';
      start.dataset.started = started ? '0' : '1';
      start.textContent = started ? 'Start route' : 'Route in progress';
      state.textContent = started ? '● Not started' : '● In progress';
    });
  }

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
