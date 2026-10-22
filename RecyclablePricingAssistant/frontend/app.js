
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
  // Always display the assigned category first.
  // Staff review is optional and is shown separately.
  return itagHtml(effIntent(m));
}

function helpHtml(title, steps, note = '') {
  return `
    <details class="channel-help">
      <summary
        aria-label="Help: ${esc(title)}"
        title="Click for step-by-step help"
      >?</summary>

      <div class="channel-help-content">
        <strong>${esc(title)}</strong>

        <ol>
          ${steps.map(step => `<li>${step}</li>`).join('')}
        </ol>

        ${note ? `<p>${note}</p>` : ''}
      </div>
    </details>`;
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
      // Show every category, including Other.
    } else if (filter === 'review') {
      if (!(m.needs_review && m.status === 'new')) {
        return false;
      }
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

  // Include all categories in the total.
  const open = stats.total;

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
  $('navBadge').style.display =
    stats.pending_review ? '' : 'none';
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
  const reviewed = m.status !== 'new';
  const matches = (m.materials && m.materials.matches) || [];

  selMats = new Set(
    effMaterials(m).filter(label => label !== 'Unknown')
  );

  $('detailTitle').textContent = m.sender || 'Customer';
  $('detailTag').innerHTML = headTag(m);

  let banner = '';

  if (reviewed) {
    banner = m.status === 'corrected'
      ? `<div class="banner">
           <b>Staff update saved</b>
           The category or materials were adjusted by staff.
         </div>`
      : `<div class="banner">
           <b>Reviewed</b>
           A staff member confirmed this message.
         </div>`;
  }

  let matHtml;

  if (!m.materials) {
    matHtml = `
      <div class="pad muted">
        Materials are not shown for unrelated messages.
      </div>`;
  } else if (!matches.length) {
    const labels = effMaterials(m);

    matHtml = labels.length
      ? `<div class="pad">
           ${labels.map(label =>
             `<span class="itag other">${esc(pretty(label))}</span>`
           ).join(' ')}
         </div>`
      : `<div class="pad muted">
           No recyclable material recognised.
         </div>`;
  } else {
    matHtml = matches.map(item => `
      <div class="row">
        <div class="l">
          <b>${esc(pretty(item.label))}</b>
        </div>
      </div>
    `).join('');
  }

  const intentOpts = Object.keys(INTENTS)
    .map(key => `
      <option
        value="${key}"
        ${key === intent ? 'selected' : ''}
      >${esc(INTENTS[key])}</option>
    `)
    .join('');

  const chips = MATERIALS
    .map(key => `
      <button
        type="button"
        class="chip ${selMats.has(key) ? 'on' : ''}"
        data-mat="${key}"
      >${esc(pretty(key))}</button>
    `)
    .join('');

  $('detailBody').innerHTML = `
    ${banner}

    <div class="section-title">Customer category</div>

    <div class="card pad">
      ${itagHtml(intent)}

      ${m.corrected_intent
        ? `<div class="muted" style="margin-top:8px">
             Updated by staff
           </div>`
        : ''}
    </div>

    <div class="section-title">Materials</div>

    <div class="card">
      ${matHtml}
    </div>

    <div class="section-title">Customer message</div>

    <div class="card">
      <div class="bubble">
        ${m.subject
          ? `<b>${esc(m.subject)}</b>\n`
          : ''}
        ${esc(m.text)}

        <small>
          ${esc(m.sender || 'Customer')}
          · ${esc(m.channel)}
          · ${esc(when(m.received_at))}
        </small>
      </div>
    </div>

    <details class="card optional-review">
      <summary>
        ${reviewed
          ? 'View or update staff review (optional)'
          : 'Staff review (optional)'}
      </summary>

      <div class="pad">
        <label class="field" style="margin:0">
          <span>Category</span>
          <select id="revIntent">
            ${intentOpts}
          </select>
        </label>
      </div>

      <div class="muted">
        Materials (leave empty if unknown)
      </div>

      <div class="chips">
        ${chips}
      </div>

      <div class="btns">
        <button class="btn ghost" data-act="confirm">
          Confirm category
        </button>

        <button class="btn primary" data-act="save">
          Save changes
        </button>
      </div>
    </details>

    <p class="muted" style="margin-top:12px;text-align:center">
      Review is optional. Quantities, prices and pickup details
      are not extracted yet.
    </p>
  `;
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

      <div class="muted">
        ${esc(u.email)}
        · ${esc(u.role)}
        · ${esc(session.shop.name)}
      </div>
    </div>
  `;

  if (u.role === 'owner') {
    try {
      const ch = await api('/channels');

      const e = ch.email || { connected: false };

      const s = ch.sms || {
        enabled: false,
        webhook_path: '/webhooks/sms',
      };

      const tw = ch.sms_twilio || {
        connected: false,
        phone_number: '',
        account_sid: '',
      };

      const m = ch.messenger || {
        connected: false,
      };

      html += `
        <div class="section-title">
          Connected message channels
        </div>

        <!-- EMAIL -->
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
              'If the status shows Configured, click Check email now to check for new customer messages.'
            ], 'Using Outlook, Yahoo, or another email provider? The required settings may be different. If you cannot connect your account, contact your email administrator. Your email password is private; never send it to anyone in a message.')}
          </div>

          <p class="muted">
            Status:
            <b>${e.connected ? 'Configured' : 'Not connected'}</b>
          </p>

          ${e.last_error
            ? `<p class="err">${esc(e.last_error)}</p>`
            : ''}

          ${e.last_checked_at
            ? `<p class="muted">
                 Last checked: ${esc(e.last_checked_at)}
               </p>`
            : ''}

          <form id="emailSettingsForm">
            <label class="field">
              <span>IMAP server</span>
              <input
                id="emailHost"
                value="${esc(e.imap_host || 'imap.gmail.com')}"
                maxlength="200"
                required
              >
            </label>

            <label class="field">
              <span>Email address</span>
              <input
                id="emailUser"
                type="email"
                value="${esc(e.imap_user || '')}"
                maxlength="200"
                required
              >
            </label>

            <label class="field">
              <span>Mailbox / app password</span>
              <input
                id="emailPassword"
                type="password"
                maxlength="200"
                autocomplete="new-password"
                placeholder="Enter mailbox app password"
                required
              >
            </label>

            <label class="field">
              <span>Folder</span>
              <input
                id="emailFolder"
                value="${esc(e.folder || 'INBOX')}"
                maxlength="100"
                required
              >
            </label>

            <button class="btn primary" type="submit">
              Test and save email
            </button>
          </form>

          <div class="btns">
            ${e.connected
              ? `
                <button class="btn ghost" data-act="poll">
                  Check email now
                </button>

                <button class="btn ghost" data-act="disconnect-email">
                  Disconnect email
                </button>
              `
              : ''}
          </div>
        </div>

        <!-- SMS PHONE FORWARDING -->
        <div class="card pad" style="margin-top:14px">
          <div class="channel-heading">
            <h3>SMS inbox — phone forwarding</h3>

            ${helpHtml('How to receive SMS messages', [
              'First, check whether your shop already has SMS forwarding set up. If you are unsure, ask your system administrator.',
              'This option requires a compatible SMS-forwarding app on the Android phone that receives your customers’ text messages.',
              'If the forwarding app has not been configured, ask your system administrator to set it up. You do not need to enter technical settings yourself.',
              'Only generate an SMS key when the person setting up the forwarding app is ready to use it.',
              'Click Generate SMS key. Copy the key and give it securely to your authorized administrator. The full key is shown only once.',
              'Ask the administrator to finish the setup and send a test text message to the phone.',
              'Open the ScrapDesk inbox and check whether the test message appears.'
            ], 'Generating a key alone does not connect your phone. If no compatible forwarding app has been configured, ask your system administrator for help. Treat the SMS key like a password.')}
          </div>

          <p class="muted">
            Status:
            <b>${s.enabled ? 'Enabled' : 'Not configured'}</b>
          </p>

          <label class="field">
            <span>Webhook URL</span>
            <input
              readonly
              value="${esc(location.origin + (s.webhook_path || ''))}"
            >
          </label>

          ${s.enabled
            ? `
              <p class="muted">
                Key hint: ${esc(s.key_hint || '')}
              </p>

              <button class="btn ghost" data-act="disconnect-sms">
                Disable phone forwarding
              </button>
            `
            : ''}

          <div class="btns">
            <button class="btn primary" data-act="smskey">
              ${s.enabled ? 'Replace SMS key' : 'Set up SMS forwarding'}
            </button>
          </div>
        </div>

        <!-- TWILIO SMS -->
        <div class="card pad" style="margin-top:14px">
          <div class="channel-heading">
            <h3>SMS inbox — Twilio</h3>

            ${helpHtml('How to connect SMS using Twilio', [
              'Ask your system administrator whether your shop already has a Twilio account and an SMS-capable phone number.',
              'If not, an authorized person must create and configure the Twilio account and obtain a suitable phone number. Messaging charges may apply.',
              'Ask your administrator to enter the Twilio Account SID, Auth Token, and phone number in the fields below.',
              'The administrator must finish connecting Twilio to ScrapDesk before customer messages can arrive.',
              'Once the administrator confirms setup is complete, send a test text message to the connected Twilio phone number.',
              'Open ScrapDesk and check whether the test message appears in the inbox.'
            ], 'You do not need to create technical settings yourself. If the account has not been configured, ask your system administrator. Never share your Twilio password or Auth Token with unauthorized people.')}
          </div>

          <p class="muted">
            Status:
            <b>${tw.connected ? 'Connected' : 'Not connected'}</b>
          </p>

          <form id="twilioSmsSettingsForm">
            <label class="field">
              <span>Twilio Account SID</span>
              <input
                id="twilioAccountSid"
                value="${esc(tw.account_sid || '')}"
                minlength="34"
                maxlength="34"
                autocomplete="off"
                required
              >
            </label>

            <label class="field">
              <span>Twilio Auth Token</span>
              <input
                id="twilioAuthToken"
                type="password"
                maxlength="200"
                autocomplete="new-password"
                placeholder="Enter Auth Token${tw.connected ? ' to update' : ''}"
                required
              >
            </label>

            <label class="field">
              <span>Twilio phone number (international format)</span>
              <input
                id="twilioPhoneNumber"
                value="${esc(tw.phone_number || '')}"
                placeholder="+14155550123"
                minlength="9"
                maxlength="16"
                required
              >
            </label>

            <button class="btn primary" type="submit">
              Save Twilio settings
            </button>
          </form>

          <label class="field" style="margin-top:12px">
            <span>Incoming-message webhook URL</span>
            <input
              readonly
              value="${esc(location.origin + '/webhooks/twilio/sms')}"
            >
          </label>

          ${tw.connected
            ? `
              <button class="btn ghost" data-act="disconnect-twilio">
                Disconnect Twilio
              </button>
            `
            : ''}
        </div>

        <!-- FACEBOOK MESSENGER -->
        <div class="card pad" style="margin-top:14px">
          <div class="channel-heading">
            <h3>Facebook Messenger</h3>

            ${helpHtml('How to connect Facebook Messenger', [
              'Make sure you have access to the Facebook Page your shop uses to communicate with customers.',
              'Ask your system administrator to connect that Page to ScrapDesk. The setup requires additional Facebook configuration.',
              'When the administrator is ready, provide the Page ID if they ask for it. You can enter it in the Facebook Page ID box below if you already have it.',
              'Click Save Facebook Page ID.',
              'Remember: saving the Page ID does not complete the entire connection. Your administrator must finish the Facebook setup before messages can be received.',
              'After your administrator confirms that everything is connected, send a test message to your shop’s Facebook Page.',
              'Open the ScrapDesk inbox and check whether the test message appears.'
            ], 'If you need help finding your Page ID or connecting Facebook, ask your system administrator. Do not share your Facebook password with anyone.')}
          </div>

          <p class="muted">
            Status:
            <b>
              ${m.connected
                ? 'Page registered (webhook setup still required)'
                : 'Not configured'}
            </b>
          </p>

          <form id="messengerSettingsForm">
            <label class="field">
              <span>Facebook Page ID</span>
              <input
                id="messengerPageId"
                value="${esc(m.page_id || '')}"
                minlength="3"
                maxlength="100"
                required
              >
            </label>

            <button class="btn primary" type="submit">
              Save Facebook Page ID
            </button>
          </form>

          <label class="field" style="margin-top:12px">
            <span>Meta webhook callback URL</span>
            <input
              readonly
              value="${esc(location.origin + '/webhooks/messenger')}"
            >
          </label>

          ${m.connected
            ? `
              <button class="btn ghost" data-act="disconnect-messenger">
                Disconnect Page
              </button>
            `
            : ''}
        </div>
      `;
    } catch (err) {
      html += `
        <div class="card pad">
          <p class="err">
            Unable to load channel settings: ${esc(err.message)}
          </p>
        </div>
      `;
    }

    // Existing staff list.
    try {
      const st = await api('/staff');

      html += `
        <div class="section-title">Staff</div>
        <div class="card">
          ${
            st.staff.length
              ? st.staff.map(person => `
                  <div class="row">
                    <div class="l">
                      <b>${esc(person.full_name)}</b>
                      <span>${esc(person.email)}</span>
                    </div>

                    <div class="r">
                      ${esc(person.role)}
                      ${person.is_active ? '' : ' (off)'}
                    </div>
                  </div>
                `).join('')
              : '<div class="pad muted">No staff yet.</div>'
          }
        </div>
      `;
    } catch (err) {
      // The staff list is optional.
    }
  }

  html += `
    <div class="btns" style="margin-top:16px">
      <button class="btn ghost" data-act="logout">
        Log out
      </button>
    </div>
  `;

  el.innerHTML = html;
}

// Settings forms are rendered dynamically, so listen on their parent.
$('moreBody').addEventListener('submit', async e => {
  const form = e.target;

  const supportedForms = [
    'emailSettingsForm',
    'messengerSettingsForm',
    'twilioSmsSettingsForm',
  ];

  if (!supportedForms.includes(form.id)) return;

  e.preventDefault();

  const button = form.querySelector('button[type="submit"]');

  if (button) button.disabled = true;

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

    } else if (form.id === 'messengerSettingsForm') {
      await api('/channels/messenger', {
        method: 'PUT',
        body: {
          page_id: $('messengerPageId').value.trim(),
        },
      });

      toast(
        'Facebook Page ID saved. Complete Meta webhook setup to receive messages.'
      );

    } else if (form.id === 'twilioSmsSettingsForm') {
      await api('/channels/sms/twilio', {
        method: 'PUT',
        body: {
          account_sid: $('twilioAccountSid').value.trim(),
          auth_token: $('twilioAuthToken').value.trim(),
          phone_number: $('twilioPhoneNumber').value.trim(),
        },
      });

      toast(
        'Twilio settings saved. Finish the incoming-message webhook setup in Twilio.'
      );
    }

    await loadMore();

  } catch (err) {
    toast(err.message);

  } finally {
    if (button) button.disabled = false;
  }
});

$('moreBody').addEventListener('click', async e => {
  const btn = e.target.closest('[data-act]');

  if (!btn) return;

  const act = btn.dataset.act;

  try {
    if (act === 'logout') {
      try {
        await api('/auth/logout', {
          method: 'POST',
        });
      } catch (err) {
        // Clear the local session even if server logout fails.
      }

      logoutLocal();

    } else if (act === 'poll') {
      const r = await api('/channels/email/poll-now', {
        method: 'POST',
      });

      toast(
        r.error
          ? 'Email check failed: ' + r.error
          : `Mailbox checked. New messages: ${r.new ?? 0}`
      );

      await loadInbox();
      await loadMore();

    } else if (act === 'smskey') {
      const confirmed = confirm(
        'Generate or replace the SMS key? Any old forwarding setup will stop working.'
      );

      if (!confirmed) return;

      const r = await api('/channels/sms/key', {
        method: 'POST',
      });

      // The key is only returned once. Copy it and save it securely.
      prompt(
        'Copy and save this key now. It is shown only once.\n' +
        'Webhook: ' + location.origin + r.webhook_path +
        '\nSend the key in the X-API-Key header.',
        r.sms_key
      );

      toast(
        'SMS key generated. Configure your SMS-forwarding app to receive messages.'
      );

      await loadMore();

    } else if (act === 'disconnect-twilio') {
      const confirmed = confirm(
        'Disconnect the Twilio SMS gateway?'
      );

      if (!confirmed) return;

      await api('/channels/sms/twilio', {
        method: 'DELETE',
      });

      toast('Twilio disconnected.');

      await loadMore();

    } else if (
      [
        'disconnect-email',
        'disconnect-sms',
        'disconnect-messenger',
      ].includes(act)
    ) {
      const config = {
        'disconnect-email': [
          '/channels/email',
          'Disconnect the email mailbox?',
        ],
        'disconnect-sms': [
          '/channels/sms',
          'Disable SMS and invalidate its key?',
        ],
        'disconnect-messenger': [
          '/channels/messenger',
          'Disconnect this Facebook Page?',
        ],
      }[act];

      if (!confirm(config[1])) return;

      await api(config[0], {
        method: 'DELETE',
      });

      toast('Channel disconnected.');

      await loadMore();
    }

  } catch (err) {
    toast(err.message);
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
