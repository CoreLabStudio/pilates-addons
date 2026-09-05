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

    // Go back, rather than forward to the same address.
    //
    // Setting the href alone means every tap of the arrow pushes another
    // entry: three taps into a page and the browser's own back button has to
    // be pressed four times to unwind what looked like one step each. When
    // the referrer really is the page we resolved - same origin, inside /my -
    // history.back() is the same destination, restores the scroll position,
    // and leaves the history stack the length the user thinks it is.
    var refIsTarget = false;
    try {
      var u = new URL(document.referrer || '', window.location.href);
      refIsTarget = document.referrer &&
        u.origin === window.location.origin &&
        (u.pathname + u.search) === target &&
        window.history.length > 1;
    } catch (_) {}
    if (!refIsTarget) return;

    links.forEach(function(link) {
      link.addEventListener('click', function(e) {
        // let a modified click open a real tab from the href above
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        window.history.back();
      });
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

  // Only these two are rooms a student picks between. A class type that is
  // neither belongs to no tab, so it stays visible under whichever tab is
  // showing rather than disappearing somewhere unreachable.
  const ROOMS = ['reformer', 'barre'];

  function applyCombinedFilter() {
    const discWrap = $('#mv-studio-discipline');
    const dateSel  = $('#mv-date-select');
    if (!discWrap && !dateSel) return;

    const active = discWrap ? $('.mv-segment.mv-active', discWrap) : null;
    const activeType = active ? (active.dataset.discipline || '') : '';
    const activeDate = dateSel ? (dateSel.value || 'all') : 'all';

    $$('.mv-class-card, .mv-upcoming-card').forEach((card) => {
      const ct      = card.dataset.ct   || '';
      const dateStr = card.dataset.date || '';
      const typeOk  = !activeType || ct === activeType || ROOMS.indexOf(ct) === -1;
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

  function setupStudioDisciplineToggle() {
    const wrap = $('#mv-studio-discipline');
    if (!wrap) return;
    wrap.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-discipline]');
      if (!btn || btn.classList.contains('mv-active')) return;
      $$('[data-discipline]', wrap).forEach((b) => {
        const on = b === btn;
        b.classList.toggle('mv-active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      applyCombinedFilter();
      // the calendar listens for this, so one toggle drives both views
      document.dispatchEvent(new CustomEvent('mv:discipline-changed'));
    });
    // apply the default tab on load, so the list matches the highlighted pill
    applyCombinedFilter();
  }

  /* ── 13. Calendar view ─────────────────────────────────────────
     One implementation, three pages. The cells are already in the
     page; day, week and month are decisions about which of them to
     show, so switching view costs no round trip and keeps the
     discipline filter and the scroll position intact. */
  function setupCalendar() {
    const cal = $('#mv-cal');
    const btn = $('#mv-cal-toggle');
    const list = $('#mv-list-view');
    if (!cal || !btn || !list) return;

    const grid = $('#mv-cal-grid', cal);
    const timedWrap = $('#mv-cal-timed', cal);
    const period = $('#mv-cal-period', cal);
    const emptyMsg = $('#mv-cal-empty', cal);
    const cells = $$('.mv-cal-cell', cal);
    // No early return when there is nothing to show. An earlier version
    // installed a stub click handler here and returned, which kept the icon
    // visible but never reached the code below that binds the mode buttons,
    // the arrows and the period label - so on an empty week the whole bar was
    // inert and the month name was blank. render() already copes with an
    // empty cell list on its own: it counts nothing, so it hides the grid and
    // shows the empty line while still writing the period label. The controls
    // describe which period you are looking at, and that is worth saying
    // whether or not anything is scheduled in it.

    const isoOf = (c) => c.dataset.iso;
    const all = cells.map(isoOf).sort();
    const parse = (iso) => {
      const p = iso.split('-');
      return new Date(+p[0], +p[1] - 1, +p[2]);
    };
    const fmt = (d) => d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');

    // Start on today when the data covers it, otherwise the first day there
    // is - landing on an empty month because today happens to be outside the
    // range is a worse first impression than starting where the classes are.
    const todayCell = $('.mv-cal-today', cal);
    // Falling back to today matters when there are no cells at all: all[0] is
    // undefined then, and parse() would hand back an Invalid Date whose
    // toLocaleDateString is the blank period label this used to show.
    const now = new Date();
    let cursor = todayCell ? parse(isoOf(todayCell))
      : all.length ? parse(all[0])
      : new Date(now.getFullYear(), now.getMonth(), now.getDate());
    let mode = cal.dataset.mode || 'month';

    // from the server: <html lang> is empty on portal pages, so relying on it
    // formatted every language's dates in the fallback locale
    const lang = cal.dataset.lang || document.documentElement.lang || 'es-ES';
    const monday = (d) => {
      const x = new Date(d);
      x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
      return x;
    };

    function label() {
      if (mode === 'day') {
        return cursor.toLocaleDateString(lang, {
          weekday: 'long', day: 'numeric', month: 'long' });
      }
      if (mode === 'week') {
        const a = monday(cursor);
        const b = new Date(a);
        b.setDate(b.getDate() + 6);
        const opt = { day: 'numeric', month: 'short' };
        return a.toLocaleDateString(lang, opt) + ' – ' + b.toLocaleDateString(lang, opt);
      }
      return cursor.toLocaleDateString(lang, { month: 'long', year: 'numeric' });
    }

    function inView(iso) {
      const d = parse(iso);
      if (mode === 'day') return iso === fmt(cursor);
      if (mode === 'week') {
        const a = monday(cursor);
        const b = new Date(a);
        b.setDate(b.getDate() + 6);
        return d >= a && d <= b;
      }
      return d.getFullYear() === cursor.getFullYear() &&
             d.getMonth() === cursor.getMonth();
    }

    /* Time grid.
       Day, and week on a screen wide enough for seven real columns, draw the
       hours down the side and place each class by when it starts and how long
       it runs. Month keeps its compact bars - thirty days of positioned blocks
       is unreadable at any width, which is why Google Calendar and Odoo both
       stop at week - and week on a phone keeps the stacked list, because seven
       timed columns across 390px is the same 48px column that made names
       unreadable in the first place. */
    const wide = window.matchMedia('(min-width: 600px)');
    const hourStart = parseInt(cal.dataset.hourStart, 10) || 0;
    const timed = () => mode === 'day' || (mode === 'week' && wide.matches);

    function hourPx() {
      const v = parseFloat(getComputedStyle(cal).getPropertyValue('--mv-cal-hour-h'));
      return v > 0 ? v : 44;
    }

    // Two rooms run the same hours, so without this the 07:00 Reformer class
    // and the 07:00 Barre class are drawn on top of each other. Split each
    // run of overlapping classes into side-by-side lanes.
    //
    // Computed over the items actually on screen, not over everything the
    // server sent: when the discipline toggle leaves one room showing, its
    // classes go back to full width instead of holding an empty lane open
    // beside them. That is why this lives here and not in the Python.
    function laneOut(boxes) {
      let cluster = [];
      let clusterEnd = -1;
      const flush = () => {
        if (!cluster.length) return;
        const ends = [];
        cluster.forEach((b) => {
          let i = 0;
          while (i < ends.length && ends[i] > b.start) i++;
          if (i === ends.length) ends.push(0);
          ends[i] = b.start + b.dur;
          b.lane = i;
        });
        cluster.forEach((b) => { b.lanes = ends.length; });
        cluster = [];
      };
      boxes.forEach((b) => {
        if (b.start >= clusterEnd) { flush(); clusterEnd = b.start + b.dur; }
        else clusterEnd = Math.max(clusterEnd, b.start + b.dur);
        cluster.push(b);
      });
      flush();
    }

    function layout(items, on) {
      if (!on) {
        items.forEach((it) => {
          it.style.top = '';
          it.style.height = '';
          it.style.left = '';
          it.style.width = '';
        });
        return;
      }
      const h = hourPx();
      const boxes = items
        .filter((it) => it.style.display !== 'none')
        .map((it) => ({
          el: it,
          start: parseInt(it.dataset.start, 10) || 0,
          dur: parseInt(it.dataset.dur, 10) || 50,
        }))
        .sort((a, b) => (a.start - b.start) || (a.dur - b.dur));
      laneOut(boxes);
      boxes.forEach((b) => {
        const w = 100 / (b.lanes || 1);
        b.el.style.top = ((b.start - hourStart * 60) / 60 * h) + 'px';
        // a 50-minute class is short; never let one collapse below a readable
        // line just because the arithmetic says so
        b.el.style.height = Math.max((b.dur / 60 * h) - 2, 18) + 'px';
        b.el.style.left = (b.lane * w) + '%';
        // 2px short of its lane, so two rooms at the same hour read as two
        // blocks rather than one two-tone one
        b.el.style.width = 'calc(' + w + '% - 2px)';
      });
    }

    function render() {
      cal.dataset.mode = mode;
      const isTimed = timed();
      cal.classList.toggle('mv-cal-timegrid', isTimed);
      let shown = 0;
      let withClasses = 0;
      cells.forEach((c) => {
        const on = inView(isoOf(c));
        c.hidden = !on;
        if (!on) return;
        shown++;
        // the discipline toggle filters the calendar too, not just the list
        const items = $$('.mv-cal-item', c);
        let visible = 0;
        items.forEach((it) => {
          const keep = disciplineAllows(it.dataset.ct || '');
          it.style.display = keep ? '' : 'none';
          if (keep) visible++;
        });
        if (visible) withClasses++;
        // after the filter, so the lanes count only what is on screen
        layout(items, isTimed);
      });
      period.textContent = label();
      if (emptyMsg) emptyMsg.hidden = withClasses > 0;
      if (grid) grid.hidden = shown === 0;
      if (timedWrap) timedWrap.hidden = shown === 0;
    }

    // A desktop week dragged narrow has to fall back to the stacked list, and
    // back again - the breakpoint decides which of the two week views this is.
    wide.addEventListener('change', () => { if (!cal.hidden) render(); });

    function step(dir) {
      if (mode === 'day') cursor.setDate(cursor.getDate() + dir);
      else if (mode === 'week') cursor.setDate(cursor.getDate() + 7 * dir);
      else cursor.setMonth(cursor.getMonth() + dir);
      render();
    }

    btn.addEventListener('click', () => {
      const open = cal.hidden;
      cal.hidden = !open;
      list.hidden = open;
      btn.setAttribute('aria-pressed', open ? 'true' : 'false');
      if (open) render();
    });

    $$('[data-cal-mode]', cal).forEach((b) => {
      b.addEventListener('click', () => {
        mode = b.dataset.calMode;
        $$('[data-cal-mode]', cal).forEach((x) =>
          x.classList.toggle('mv-active', x === b));
        render();
      });
    });

    $$('[data-cal-nav]', cal).forEach((b) => {
      b.addEventListener('click', () => step(parseInt(b.dataset.calNav, 10)));
    });

    // Phone month view: the cells are 48px wide, so names are unreadable and
    // the items are rendered as colour bars instead. Tapping a day opens that
    // day, where the names are full size - the drill-down a month grid on a
    // phone is for. On wider screens the names fit, so this stays out of the
    // way and the class links work directly.
    grid.addEventListener('click', (e) => {
      if (mode !== 'month' || !window.matchMedia('(max-width: 599px)').matches) return;
      const cell = e.target.closest('.mv-cal-cell');
      if (!cell || !cell.querySelector('.mv-cal-item')) return;
      e.preventDefault();
      const p = cell.dataset.iso.split('-');
      cursor = new Date(+p[0], +p[1] - 1, +p[2]);
      mode = 'day';
      $$('[data-cal-mode]', cal).forEach((x) =>
        x.classList.toggle('mv-active', x.dataset.calMode === 'day'));
      render();
    });

    // Re-render when the discipline toggle moves, so the calendar and the
    // list never disagree about what is being shown.
    document.addEventListener('mv:discipline-changed', () => {
      if (!cal.hidden) render();
    });
  }

  /* Which rooms the discipline toggle is currently letting through. Shared by
     the list filter and the calendar so one control drives both. */
  function disciplineAllows(ct) {
    const wrap = $('#mv-studio-discipline') || $('#mv-tt-toggle');
    if (!wrap) return true;
    const active = $('.mv-segment.mv-active, [aria-selected="true"]', wrap);
    const want = active ? (active.dataset.discipline || '') : '';
    if (!want) return true;
    return ct === want || ROOMS.indexOf(ct) === -1;
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
        const isTf = !!btn.closest('#mv-timeframe-filters');

        if (!isTf) {
          // Package-page pills (not type, not timeframe)
          $$('.mv-pkg-pill-btn').forEach((b) => {
            b.classList.remove('mv-active');
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
      // From the server, not from <html lang>: that attribute is empty on
      // portal pages, so the fallback won every time and the whole dropdown
      // came out in Spanish however the site was set - dates and all.
      const lang = (sel.dataset.lang || document.documentElement.lang || 'es-ES')
        .replace('_', '-');
      function fmtDate(dStr) {
        const p = dStr.split('-');
        const dt = new Date(+p[0], +p[1] - 1, +p[2]);
        return dt.toLocaleDateString(lang, { day: 'numeric', month: 'long' });
      }
      // Translated server-side. A three-language table here is one more place
      // to forget when a fourth is added.
      const allLabel = sel.dataset.allLabel || 'All dates';
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

    if ($('#mv-studio-discipline') || $('#mv-date-select')) applyCombinedFilter();
  }

  /* ── 12. Timetable — Reformer/Barre toggle ───────────────────
     Swaps which pane is shown. The first version linked to
     /my/timetable?discipline=..., so every switch was a full page load: the
     browser restored the old scroll offset against a page whose height had
     changed, which is the up-and-down jump that was reported. Toggling a
     hidden attribute cannot move the scroll position at all.
     The URL is kept in step with history.replaceState so a reload or a
     shared link still opens on the discipline being looked at, without
     pushing a history entry per tap. */
  function scrollHost() {
    const b = document.body;
    const de = document.scrollingElement || document.documentElement;
    if (b && b.scrollHeight - b.clientHeight > 1 &&
        /auto|scroll/.test(getComputedStyle(b).overflowY)) {
      return b;
    }
    return de;
  }

  function setupTimetableToggle() {
    const toggle = $('#mv-tt-toggle');
    if (!toggle) return;
    const panes = $$('.mv-tt-pane');
    if (!panes.length) return;

    toggle.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-discipline]');
      if (!btn) return;
      const want = btn.dataset.discipline;

      $$('[data-discipline]', toggle).forEach((b) => {
        const on = b.dataset.discipline === want;
        b.classList.toggle('mv-active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      // Removing the navigation fixes the reported jump, but swapping panes
      // still changes the scroll height, and a view sitting near the bottom of
      // the taller pane gets clamped when the shorter one replaces it. Pin the
      // offset across the swap.
      //
      // The portal shell scrolls <body> (overflow-y:auto), not the document,
      // so window.scrollY is permanently 0 here and pinning that would do
      // nothing at all. Ask which element actually overflows.
      const host = scrollHost();
      const y = host.scrollTop;
      panes.forEach((p) => { p.hidden = p.dataset.discipline !== want; });
      if (host.scrollTop !== y) host.scrollTop = y;
      document.dispatchEvent(new CustomEvent('mv:discipline-changed'));

      try {
        const u = new URL(window.location.href);
        u.searchParams.set('discipline', want);
        window.history.replaceState({}, '', u);
      } catch (err) { /* URL unavailable - the toggle still works */ }
    });
  }

  /* ── 13. Install the app ─────────────────────────────────────
     Three situations, and the browser is the only thing that knows which
     one applies, so nothing here is decided server-side:

       * already installed        -> show nothing at all
       * prompt available         -> the button fires the browser's own
                                     install prompt (Android, Chrome, Edge)
       * no prompt API (iOS)      -> the button opens the instructions,
                                     because Apple exposes no way to trigger
                                     installation from a page

     beforeinstallprompt only fires when a service worker with a fetch
     handler is registered, which is why registerServiceWorker() runs first.

     Dismissal is remembered permanently rather than per session: a prompt
     that returns on every visit reads as nagging, and the Profile row is
     always there for anyone who changes their mind. That is the whole
     reason the row exists. */
  const INSTALL_DISMISSED = 'mv_install_dismissed';

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches ||
           window.matchMedia('(display-mode: fullscreen)').matches ||
           window.matchMedia('(display-mode: minimal-ui)').matches ||
           // iOS Safari predates display-mode and uses its own flag
           window.navigator.standalone === true;
  }

  function isIos() {
    const ua = window.navigator.userAgent || '';
    // iPadOS 13+ reports itself as a Mac, so the touch check is what
    // separates an iPad from a desktop Safari
    return /iPad|iPhone|iPod/.test(ua) ||
           (/Macintosh/.test(ua) && 'ontouchend' in document);
  }

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    // scope /my/ matches where the worker is served from
    navigator.serviceWorker.register('/my/sw.js', { scope: '/my/' })
      .catch(() => { /* installability is a bonus; never break the page */ });
  }

  function setupInstallApp() {
    const triggers = $$('[data-install-trigger]');
    const card = $('#mv-install-card');
    const row = $('#mv-install-row');
    const sheet = $('#mv-ios-sheet');
    if (!triggers.length && !card && !row) return;

    // Installed already: every one of these would be a dead end.
    if (isStandalone()) return;

    const ios = isIos();

    // The Profile row is the persistent way in, so it is always available.
    // Whether the browser has offered a prompt only changes what tapping it
    // does, not whether it can be found.
    if (row) row.hidden = false;

    // The Home card is an interruption rather than a menu entry, so it only
    // appears when it can lead somewhere useful: a real prompt, or the iOS
    // instructions. And never once dismissed.
    const showCard = () => {
      if (!card) return;
      let dismissed = false;
      try { dismissed = localStorage.getItem(INSTALL_DISMISSED) === '1'; } catch (e) { /* private mode */ }
      if (!dismissed) card.hidden = false;
    };
    if (ios || window.mvInstallEvent) showCard();

    // the head script may still catch the event after this point
    document.addEventListener('mv-install-available', showCard);
    document.addEventListener('mv-install-done', () => {
      if (card) card.hidden = true;
      if (row) row.hidden = true;
      if (sheet) sheet.hidden = true;
    });

    const openSheet = () => {
      if (!sheet) return;
      // one sheet, two sets of steps: Safari's Share menu, or the browser's
      // own install control everywhere else
      const wanted = ios ? 'ios' : 'other';
      $$('[data-steps]', sheet).forEach((el) => {
        el.hidden = el.dataset.steps !== wanted;
      });
      sheet.hidden = false;
    };
    const closeSheet = () => { if (sheet) sheet.hidden = true; };

    triggers.forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        const deferred = window.mvInstallEvent;
        if (deferred) {
          deferred.prompt();
          try {
            const choice = await deferred.userChoice;
            if (choice && choice.outcome === 'accepted') {
              if (card) card.hidden = true;
              if (row) row.hidden = true;
            }
          } catch (err) { /* a prompt can only be used once */ }
          window.mvInstallEvent = null;
        } else {
          openSheet();
        }
      });
    });

    const closeBtn = $('#mv-ios-close');
    if (closeBtn) closeBtn.addEventListener('click', closeSheet);
    if (sheet) {
      sheet.addEventListener('click', (e) => { if (e.target === sheet) closeSheet(); });
    }
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && sheet && !sheet.hidden) closeSheet();
    });

    const dismiss = $('#mv-install-dismiss');
    if (dismiss) {
      dismiss.addEventListener('click', () => {
        if (card) card.hidden = true;
        try { localStorage.setItem(INSTALL_DISMISSED, '1'); } catch (err) { /* private mode */ }
      });
    }
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
      const methodInput = form.querySelector('input[name="payment_method"]');
      // Online payment path (Stripe): no method radios present — only terms needed.
      // Manual fallback path: both a selected method and terms are required.
      const method = methodInput
        ? form.querySelector('input[name="payment_method"]:checked')
        : true;
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
    setupTimetableToggle();
    setupStudioDisciplineToggle();
    setupCalendar();
    registerServiceWorker();
    setupInstallApp();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
