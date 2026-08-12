/* CoreLab Portal — interactions, view transitions, animations
   No jQuery, no Odoo OWL — vanilla JS only.
   All DOM mutations are cosmetic; zero business logic here. */
(function () {
  'use strict';

  /* ── helpers ─────────────────────────────────────────────── */
  const $ = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => [...(ctx || document).querySelectorAll(sel)];

  /* ── 3. Bottom nav — highlight active tab ──────────────────
     Four student tabs: Home / Studio / Packages / Profile.
     /my/classes/<id> (class detail) and /my/schedule belong to Studio. */
  const STUDIO_PATHS = ['/my/studio', '/my/classes', '/my/schedule'];
  const PACKAGE_PATHS = ['/my/packages', '/my/credits', '/my/terms', '/my/checkout'];
  const PROFILE_PATHS = ['/my/messages', '/my/notifications', '/my/orders',
                         '/my/security', '/my/language', '/my/addresses'];

  function startsWithAny(path, prefixes) {
    return prefixes.some((p) => path === p || path.startsWith(p + '/') || path.startsWith(p + '?'));
  }

  function activateBottomNav() {
    // Strip Odoo language prefix (/en/, /es/, /ca_ES/, etc.) before comparing
    let path = window.location.pathname;
    const langMatch = path.match(/^\/((?:[a-z]{2})(?:_[A-Za-z]{2,4})?)(\/.*)/);
    if (langMatch) path = langMatch[2];

    $$('.mv-nav-tab').forEach((tab) => {
      const href = (tab.getAttribute('href') || '').split('?')[0];
      if (!href) return;
      let active;
      if (href === '/my/home') {
        active = path === '/my/home';
      } else if (href === '/my/studio') {
        active = startsWithAny(path, STUDIO_PATHS);
      } else if (href === '/my/packages') {
        active = startsWithAny(path, PACKAGE_PATHS);
      } else if (href === '/my/teacher/classes') {
        active = path === '/my/teacher/classes' || path.startsWith('/my/teacher/classes/');
      } else if (href === '/my') {
        // Profile tab — explicit positive match only
        active = path === '/my' || startsWithAny(path, PROFILE_PATHS);
      } else {
        active = false;
      }
      if (active) {
        tab.classList.add('mv-active');
        tab.setAttribute('aria-current', 'page');
      }
    });
  }

  /* ── 4. Card tap → navigate (excluding buttons/forms) ───────
     .mv-class-card wraps an image + body; tapping anywhere
     except the Book form navigates to data-href.             */
  function setupCardTaps() {
    $$('.mv-class-card[data-href]').forEach((card) => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('form, button, a')) return;
        window.location.href = card.dataset.href;
      });
    });
    // Prevent form clicks bubbling up to card click handler
    $$('.mv-class-card form').forEach((form) => {
      form.addEventListener('click', (e) => e.stopPropagation());
    });
  }

  /* ── 5. Booking success checkmark animation ─────────────── */
  function animateBookingSuccess() {
    const flash = $('.mv-flash-ok');
    if (!flash) return;
    const check = document.createElement('span');
    check.style.cssText =
      'display:inline-block;margin-right:6px;' +
      'animation:mv-check-pop 340ms cubic-bezier(0.175,0.885,0.32,1.275) 200ms both';
    check.textContent = '✓';
    flash.prepend(check);

    if (!$('#mv-kf')) {
      const s = document.createElement('style');
      s.id = 'mv-kf';
      s.textContent =
        '@keyframes mv-check-pop{' +
        'from{opacity:0;transform:scale(0.4) rotate(-20deg)}' +
        'to{opacity:1;transform:scale(1) rotate(0)}}';
      document.head.appendChild(s);
    }
  }

  /* ── 6. Cancel confirm for upcoming bookings ─────────────── */
  function setupCancelConfirm() {
    $$('.mv-cancel-form').forEach((form) => {
      form.addEventListener('submit', (e) => {
        if (!confirm('Cancel this booking?')) e.preventDefault();
      });
    });
  }

  /* ── 7. Teacher reassign dropdown — no extra JS needed,
           but wire up confirm for reassign forms             */
  function setupReassignConfirm() {
    $$('.mv-reassign-form').forEach((form) => {
      form.addEventListener('submit', (e) => {
        const sel = form.querySelector('select');
        if (!sel || !sel.value) { e.preventDefault(); return; }
        if (!confirm('Reassign this class?')) e.preventDefault();
      });
    });
  }

  /* ── 8. Notification bell ───────────────────────────────────
     Bell fetches /my/notifications/count on load for the badge,
     then /my/notifications on click (marks all as read server-side). */
  function _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function setupNotificationBell() {
    const btn    = document.getElementById('mv-bell-btn');
    if (!btn) return;
    const badge  = document.getElementById('mv-bell-badge');
    const panel  = document.getElementById('mv-notif-panel');
    const empty  = document.getElementById('mv-notif-empty');
    const list   = document.getElementById('mv-notif-list');

    // Load unread count
    fetch('/my/notifications/count', {credentials: 'same-origin'})
      .then(r => r.json())
      .then(data => {
        const n = data.count || 0;
        if (n > 0 && badge) {
          badge.style.display = 'block';
        }
      }).catch(() => {});

    // Bell click — on a phone go straight to the archive page, because a
    // 300px dropdown is unusable there and the dropdown marks everything
    // read with no way to review it afterwards.
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (window.matchMedia('(max-width: 600px)').matches) {
        window.location.href = '/my/notifications';
        return;
      }
      const open = panel.style.display !== 'none';
      if (open) { panel.style.display = 'none'; return; }
      panel.style.display = 'block';
      if (badge) badge.style.display = 'none';
      if (empty) { empty.textContent = 'Loading…'; empty.style.display = ''; }
      if (list)  list.style.display = 'none';

      fetch('/my/notifications/data', {credentials: 'same-origin'})
        .then(r => r.json())
        .then(data => {
          const notifs = data.notifications || [];
          if (!notifs.length) {
            if (empty) empty.textContent = 'No new notifications';
            return;
          }
          if (empty) empty.style.display = 'none';
          if (list) {
            list.innerHTML = notifs.map(function(n) {
              var cls = 'mv-notif-item mv-notif-item--unread';
              var dId = ' data-id="' + n.id + '"';
              var inner = '<span class="mv-notif-title">' + _escHtml(n.title) + '</span>' +
                (n.body ? '<span class="mv-notif-body">' + _escHtml(n.body) + '</span>' : '') +
                '<span class="mv-notif-time">' + _escHtml(n.time_ago) + '</span>';
              if (n.action_url) {
                return '<li class="' + cls + ' mv-notif-item--linked"' + dId + '>' +
                  '<a href="' + _escHtml(n.action_url) + '" class="mv-notif-link">' + inner + '</a></li>';
              }
              return '<li class="' + cls + '"' + dId + '>' + inner + '</li>';
            }).join('');
            list.style.display = 'block';

            // Mark-read on click: fire async, remove from list immediately
            list.addEventListener('click', function(e) {
              var li = e.target.closest('li[data-id]');
              if (!li) return;
              var nid = li.getAttribute('data-id');
              fetch('/my/notifications/mark_read', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'notif_id=' + encodeURIComponent(nid),
                keepalive: true,
              }).catch(function() {});
              li.remove();
              if (!list.querySelector('li')) {
                list.style.display = 'none';
                if (empty) { empty.textContent = 'No new notifications'; empty.style.display = ''; }
              }
            });
          }
        }).catch(() => { if (empty) empty.textContent = 'Could not load notifications'; });
    });

    // Close panel when clicking outside
    document.addEventListener('click', () => {
      if (panel) panel.style.display = 'none';
    });
  }

  /* ── 8a. Session-history tracker (PWA back-nav) ─────────────
     In PWA / standalone mode document.referrer is always empty, so
     8b would fall back to the static server href on every page. We
     track /my/* navigation in sessionStorage so that 8b can use the
     real previous page even without a referrer.                    */
  function trackNavHistory() {
    // Settings/utility pages are excluded from the nav stack so they never
    // appear as back-navigation targets from content pages.
    const UTILITY = ['/my/language', '/my/security', '/my/set_lang', '/my/addresses'];
    const key = 'cl_nav_stack';
    try {
      const cur = window.location.pathname + window.location.search;
      if (!/^\/my(\/|$)/.test(cur)) return;
      if (UTILITY.some(function(u) { return cur === u || cur.startsWith(u + '?'); })) return;
      const stack = JSON.parse(sessionStorage.getItem(key) || '[]');
      if (stack[stack.length - 1] === cur) return; // no duplicate on reload
      stack.push(cur);
      if (stack.length > 30) stack.shift();
      sessionStorage.setItem(key, JSON.stringify(stack));
    } catch (_) {}
  }

  /* ── 8b. Referrer-aware back links ────────────────────────────
     A sub-page such as Credit History is reachable from Home, Studio,
     Packages and Profile, so a fixed href always sent someone to the
     wrong place. When the previous page was inside /my we point the
     back link at it. Utility/settings pages are excluded as back targets.
     Falls back to sessionStorage nav stack (PWA mode), then to the
     server-rendered href when nothing better is available.             */
  function setupBackLinks() {
    const links = $$('[data-cl-back]');
    if (!links.length) return;

    // Checkout step pages have server-provided back URLs — skip JS override
    if (/\/my\/(packages\/\d+\/checkout|checkout\/\d+\/sign)/.test(window.location.pathname)) return;

    const UTILITY = ['/my/language', '/my/security', '/my/set_lang', '/my/addresses'];
    function isUtility(p) {
      return UTILITY.some(function(u) { return p === u || p.startsWith(u + '?') || p.startsWith(u + '/'); });
    }

    const cur = window.location.pathname + window.location.search;
    let target = null;

    // 1. Try document.referrer (normal browser navigation)
    const ref = document.referrer;
    if (ref) {
      try {
        const url = new URL(ref, window.location.href);
        if (
          url.origin === window.location.origin &&
          /^\/my(\/|$)/.test(url.pathname) &&
          url.pathname !== window.location.pathname &&
          !isUtility(url.pathname)
        ) {
          target = url.pathname + url.search;
        }
      } catch (_) {}
    }

    // 2. PWA fallback: walk sessionStorage nav stack backwards, skipping utility pages
    if (!target) {
      try {
        const key = 'cl_nav_stack';
        const stack = JSON.parse(sessionStorage.getItem(key) || '[]');
        for (let i = stack.length - 1; i >= 0; i--) {
          const entry = stack[i];
          if (entry !== cur && /^\/my(\/|$)/.test(entry) && !isUtility(entry)) {
            target = entry;
            break;
          }
        }
      } catch (_) {}
    }

    if (!target) return; // nothing better than the static server href

    links.forEach(function(link) {
      link.setAttribute('href', target);
    });
  }

  /* ── 9. Packages tab — collapsing search + discipline chips ──
     The list is rendered server-side and grouped by discipline; this
     only shows/hides cards and their now-empty section headers.      */
  function applyPackageFilter() {
    const root = $('#mv-pkg-list');
    if (!root) return;
    const chip = $('.mv-pkg-pill-btn.mv-active', root.parentNode) ||
                 $('.mv-pkg-pill-btn.mv-active');
    const filter = chip ? (chip.dataset.filter || 'all') : 'all';
    const input = $('#mv-pkg-search');
    const term = input ? input.value.trim().toLowerCase() : '';

    let shown = 0;
    $$('.mv-pkg-card', root).forEach((card) => {
      const ct = card.dataset.ct || 'any';
      const name = (card.dataset.name || '').toLowerCase();
      const okChip = filter === 'all' || ct === filter || ct === 'any';
      const okTerm = !term || name.indexOf(term) !== -1;
      const visible = okChip && okTerm;
      card.style.display = visible ? '' : 'none';
      if (visible) shown++;
    });

    // Hide a discipline heading when every card under it is filtered out
    $$('.mv-pkg-group', root).forEach((group) => {
      const any = $$('.mv-pkg-card', group).some((c) => c.style.display !== 'none');
      group.style.display = any ? '' : 'none';
    });

    const empty = $('#mv-pkg-empty');
    if (empty) empty.style.display = shown ? 'none' : '';
  }

  function applyStudioFilter() {
    // Legacy entry point — delegates to the combined filter.
    applyCombinedFilter();
  }

  function applyCombinedFilter() {
    const typeWrap = $('#mv-type-filters');
    const dateSel  = $('#mv-date-select');
    if (!typeWrap && !dateSel) return;

    const typeChip  = typeWrap ? $('.mv-type-pill.mv-active', typeWrap) : null;
    const activeType = typeChip ? (typeChip.dataset.filter || '') : '';
    const activeDate = dateSel ? (dateSel.value || 'all') : 'all';

    $$('.mv-class-card, .mv-upcoming-card').forEach((card) => {
      const ct      = card.dataset.ct   || '';
      const dateStr = card.dataset.date || '';
      const typeOk  = !activeType || ct === activeType;
      const dateOk  = activeDate === 'all' || dateStr === activeDate;
      card.style.display = typeOk && dateOk ? '' : 'none';
    });

    $$('.mv-day-group').forEach((group) => {
      const any = $$('.mv-class-card, .mv-upcoming-card', group).some(
        (c) => c.style.display !== 'none'
      );
      group.style.display = any ? '' : 'none';
    });
  }

  function setupPackageControls() {
    const toggle = $('#mv-search-toggle');
    const wrap = $('#mv-search-wrap');
    if (toggle && wrap) {
      toggle.addEventListener('click', () => {
        const open = wrap.classList.toggle('mv-open');
        toggle.classList.toggle('mv-active', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        const input = $('#mv-pkg-search');
        if (open && input) {
          input.focus();
        } else if (input) {
          // Collapse back to icon-only and drop the filter
          input.value = '';
          applyPackageFilter();
        }
      });
    }

    const input = $('#mv-pkg-search');
    if (input) input.addEventListener('input', applyPackageFilter);

    $$('.mv-pkg-pill-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const isType = !!btn.closest('#mv-type-filters');
        const isTf   = !!btn.closest('#mv-timeframe-filters');

        if (isType) {
          const wasActive = btn.classList.contains('mv-active');
          $$('.mv-type-pill').forEach((b) => b.classList.remove('mv-active'));
          if (!wasActive) btn.classList.add('mv-active');
          applyCombinedFilter();

        } else if (!isTf) {
          // Package-page pills (not type, not timeframe)
          $$('.mv-pkg-pill-btn').forEach((b) => {
            if (!b.closest('#mv-type-filters')) b.classList.remove('mv-active');
          });
          btn.classList.add('mv-active');
          applyPackageFilter();
        }
      });
    });

    if ($('#mv-pkg-list')) applyPackageFilter();

    // Date dropdown for studio page — built from data-date attributes on class/booking cards
    (function buildDateDropdown() {
      const wrap = $('#mv-date-filter-wrap');
      const sel  = $('#mv-date-select');
      if (!wrap || !sel) return;
      const cards = $$('.mv-class-card, .mv-upcoming-card');
      if (!cards.length) return;
      const seen = {}, dates = [];
      cards.forEach((c) => {
        const d = c.dataset.date;
        if (d && !seen[d]) { seen[d] = true; dates.push(d); }
      });
      if (!dates.length) return;
      const lang = (document.documentElement.lang || 'es_ES').replace('_', '-');
      function fmtDate(dStr) {
        const p = dStr.split('-');
        const dt = new Date(+p[0], +p[1] - 1, +p[2]);
        return dt.toLocaleDateString(lang, { day: 'numeric', month: 'long' });
      }
      const allLabel = lang.startsWith('ca') ? 'Totes les dates'
                     : lang.startsWith('es') ? 'Todas las fechas'
                     : 'All dates';
      const allOpt = document.createElement('option');
      allOpt.value = 'all';
      allOpt.textContent = allLabel;
      sel.appendChild(allOpt);
      dates.forEach((d) => {
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = fmtDate(d);
        sel.appendChild(opt);
      });
      sel.addEventListener('change', applyCombinedFilter);
      wrap.style.display = '';
    }());

    if ($('#mv-type-filters') || $('#mv-date-select')) applyCombinedFilter();
  }

  /* ── 10. Payment step — Next stays disabled until a method is
           chosen AND the terms box is ticked. Server re-checks both. */
  function setupCheckoutGate() {
    const form = $('#mv-payment-form');
    if (!form) return;
    const next = $('#mv-payment-next', form);
    const terms = $('#mv-terms-check', form);
    if (!next || !terms) return;

    const sync = () => {
      const method = form.querySelector('input[name="payment_method"]:checked');
      next.disabled = !(method && terms.checked);
    };
    form.addEventListener('change', sync);
    sync();
  }

  /* ── 11. Signature pad ───────────────────────────────────────
     Draws to a canvas and copies the result into a hidden input as a
     base64 PNG. The POST handler stores it on the existing
     sale.order signature fields and calls the standard confirmation. */
  function setupSignaturePad() {
    const canvas = $('#mv-sign-pad');
    if (!canvas) return;
    const form = $('#mv-sign-form');
    const hidden = $('#mv-sign-data');
    const submit = $('#mv-sign-submit');
    const nameInput = $('#mv-sign-name');
    const placeholder = $('#mv-sign-placeholder');
    const clearBtn = $('#mv-sign-clear');
    const ctx = canvas.getContext('2d');

    let drawing = false;
    let dirty = false;

    function resize() {
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.round(rect.width * ratio);
      canvas.height = Math.round(rect.height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = '#50423D';
    }
    resize();
    window.addEventListener('resize', resize);

    function pos(e) {
      const rect = canvas.getBoundingClientRect();
      const src = e.touches ? e.touches[0] : e;
      return { x: src.clientX - rect.left, y: src.clientY - rect.top };
    }
    function start(e) {
      e.preventDefault();
      drawing = true;
      const p = pos(e);
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
    }
    function move(e) {
      if (!drawing) return;
      e.preventDefault();
      const p = pos(e);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      if (!dirty) {
        dirty = true;
        if (placeholder) placeholder.style.display = 'none';
      }
      sync();
    }
    function end() { drawing = false; }

    function sync() {
      if (submit) submit.disabled = !(dirty && (!nameInput || nameInput.value.trim()));
    }

    canvas.addEventListener('mousedown', start);
    canvas.addEventListener('mousemove', move);
    document.addEventListener('mouseup', end);
    canvas.addEventListener('touchstart', start, { passive: false });
    canvas.addEventListener('touchmove', move, { passive: false });
    canvas.addEventListener('touchend', end);
    if (nameInput) nameInput.addEventListener('input', sync);

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        dirty = false;
        if (placeholder) placeholder.style.display = '';
        sync();
      });
    }

    if (form && hidden) {
      form.addEventListener('submit', (e) => {
        if (!dirty) { e.preventDefault(); return; }
        hidden.value = canvas.toDataURL('image/png').split(',')[1] || '';
      });
    }
    sync();
  }

  /* ── Init ────────────────────────────────────────────────── */
  function init() {
    trackNavHistory();      // must run before setupBackLinks reads the stack
    activateBottomNav();
    setupCardTaps();
    animateBookingSuccess();
    setupCancelConfirm();
    setupReassignConfirm();
    setupNotificationBell();
    setupBackLinks();
    setupPackageControls();
    setupCheckoutGate();
    setupSignaturePad();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
