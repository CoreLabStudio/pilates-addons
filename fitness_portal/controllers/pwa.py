import logging
import os

from odoo import http
from odoo.http import request
from odoo.modules import get_module_path

_logger = logging.getLogger(__name__)

APP_NAME = 'CoreLab'
BRAND_BG = '#FAF9F6'
BRAND_THEME = '#18110C'

LOGO_CANDIDATES = [
    ('fitness_core/static/src/img/corelab-logo.png', 'image/png'),
]
ICON_CANDIDATES = [
    ('fitness_core/static/src/img/corelab-icon.png', 'image/png'),
    ('fitness_core/static/src/img/corelab-icon.svg', 'image/svg+xml'),
    ('fitness_core/static/src/img/corelab-logo.png', 'image/png'),
]
# The install icon, fetched once when someone adds the app to a home screen -
# never on an ordinary page load. Kept separate so the icon every page asks for
# stays small: corelab-logo.png is a 4500x4500 print master, and serving it as
# a favicon cost 130 KB on every single request.
ICON_512_CANDIDATES = [
    ('fitness_core/static/src/img/corelab-icon-512.png', 'image/png'),
] + ICON_CANDIDATES


def _read_first(candidates):
    for path, mimetype in candidates:
        parts = path.split('/')
        module_name = parts[0]
        module_root = get_module_path(module_name, display_warning=False)
        if not module_root:
            continue
        full_path = os.path.join(module_root, *parts[1:])
        if os.path.isfile(full_path):
            try:
                with open(full_path, 'rb') as fh:
                    return fh.read(), mimetype
            except OSError:
                continue
    return None, None


class FitnessPortalBrand(http.Controller):
    """Serves the CoreLab brand mark and a PWA manifest scoped to /my."""

    @http.route('/corelab/logo', type='http', auth='public', methods=['GET'], sitemap=False)
    def brand_logo(self, **kw):
        return self._serve(LOGO_CANDIDATES)

    @http.route('/corelab/icon', type='http', auth='public', methods=['GET'], sitemap=False)
    def brand_icon(self, **kw):
        return self._serve(ICON_CANDIDATES)

    @http.route('/corelab/icon-512', type='http', auth='public', methods=['GET'],
                sitemap=False)
    def brand_icon_512(self, **kw):
        return self._serve(ICON_512_CANDIDATES)

    @staticmethod
    def _icon_entries():
        """Advertise the icon with the mimetype actually being served, so the
        entry stays valid whether the bundled SVG or a studio-supplied PNG
        is in place."""
        _, mimetype = _read_first(ICON_CANDIDATES)
        if mimetype == 'image/png':
            # Each entry points at a file that really is that size. Both used to
            # name the same URL, so whichever file was behind it was advertised
            # as 192 and 512 at once - true of neither.
            return [
                {'src': '/corelab/icon', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
                {'src': '/corelab/icon-512', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            ]
        return [
            {'src': '/corelab/icon', 'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any'},
        ]

    @staticmethod
    def _serve(candidates):
        data, mimetype = _read_first(candidates)
        if data is None:
            _logger.warning('CoreLab brand asset missing: %s', candidates[0][0])
            return request.not_found()
        return request.make_response(data, headers=[
            ('Content-Type', mimetype),
            ('Cache-Control', 'public, max-age=86400'),
        ])

    # Chrome and Edge refuse to fire beforeinstallprompt unless a service
    # worker with a fetch handler is registered, so without this the install
    # button would simply never become available on Android or desktop.
    #
    # The handler is deliberately a pass-through with no caching. This is a
    # live booking portal: a cache would happily serve a student a stale class
    # list or a stale credit balance, which is a far worse bug than not being
    # installable. Served from /my/ so its scope covers the portal and nothing
    # else on the database.
    SERVICE_WORKER = """// CoreLab portal service worker.
// Exists so the browser considers the portal installable. It deliberately
// does not cache: stale class availability or credit counts would be worse
// than no offline support.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {});

// ── Push ──────────────────────────────────────────────────────────────────
// The push service wakes this worker whether or not the app is open, which is
// the whole point: with no tab and the phone locked, this still runs. The text
// arrives already written in the recipient's language - the server builds it
// from their own account setting - so nothing here translates anything.
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  const title = data.title || 'CoreLab';
  const options = {
    body: data.body || '',
    icon: '/corelab/icon-512',
    badge: '/corelab/icon',
    // One notification per kind: a second cancellation replaces the first
    // rather than stacking two identical rows on the lock screen.
    tag: data.tag || 'corelab',
    renotify: true,
    data: { url: data.url || '/my/home' },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

// Tapping it should land on the thing it is about, and should re-use a window
// that is already open rather than opening a second copy of the app.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/my/home';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) {
          if ('navigate' in client) { client.navigate(target); }
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});

// Chrome can retire a subscription on its own (key rotation, storage
// pressure). Re-subscribing here keeps a device from going quietly silent.
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil((async () => {
    try {
      const res = await fetch('/my/push/key', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: {} }),
      });
      const key = ((await res.json()).result || {}).key;
      if (!key) return;
      const sub = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: Uint8Array.from(
          atob(key.replace(/-/g, '+').replace(/_/g, '/')), (ch) => ch.charCodeAt(0)),
      });
      await fetch('/my/push/subscribe', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call',
                               params: { subscription: sub.toJSON() } }),
      });
    } catch (e) { /* a silent device is bad; a crashed worker is worse */ }
  })());
});
"""

    @http.route('/my/sw.js', type='http', auth='public', methods=['GET'], sitemap=False)
    def portal_service_worker(self):
        return request.make_response(self.SERVICE_WORKER, [
            ('Content-Type', 'text/javascript; charset=utf-8'),
            # the worker itself must not be cached hard, or a future change to
            # it can take a week to reach an installed phone
            ('Cache-Control', 'no-cache'),
            ('Service-Worker-Allowed', '/my/'),
        ])

    @http.route('/my/manifest.webmanifest', type='http', auth='public',
                methods=['GET'], readonly=True)
    def portal_manifest(self):
        app_name = (
            request.env['ir.config_parameter'].sudo().get_param('web.web_app_name')
            or APP_NAME
        )
        manifest = {
            'name': app_name,
            'short_name': APP_NAME,
            'scope': '/my',
            'start_url': '/my/home',
            'display': 'standalone',
            'background_color': BRAND_BG,
            'theme_color': BRAND_THEME,
            'prefer_related_applications': False,
            'icons': self._icon_entries(),
        }
        return request.make_json_response(manifest, {
            'Content-Type': 'application/manifest+json',
        })
