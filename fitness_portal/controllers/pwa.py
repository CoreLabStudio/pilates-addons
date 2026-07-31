import logging

from odoo import http
from odoo.http import request
from odoo.tools.misc import file_open

_logger = logging.getLogger(__name__)

APP_NAME = 'CoreLab'
BRAND_BG = '#FAF9F6'
BRAND_THEME = '#9ABACD'

# The studio can drop a real PNG next to the bundled SVG at any time and it is
# picked up automatically — no code or template change needed.
LOGO_CANDIDATES = [
    ('fitness_core/static/src/img/corelab-logo.png', 'image/png'),
    ('fitness_core/static/src/img/corelab-logo.svg', 'image/svg+xml'),
]
ICON_CANDIDATES = [
    ('fitness_core/static/src/img/corelab-icon.png', 'image/png'),
    ('fitness_core/static/src/img/corelab-icon.svg', 'image/svg+xml'),
    ('fitness_core/static/src/img/corelab-logo.png', 'image/png'),
    ('fitness_core/static/src/img/corelab-logo.svg', 'image/svg+xml'),
]


def _read_first(candidates):
    for path, mimetype in candidates:
        try:
            with file_open(path, 'rb') as handle:
                return handle.read(), mimetype
        except (FileNotFoundError, OSError, ValueError):
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

    @staticmethod
    def _icon_entries():
        """Advertise the icon with the mimetype actually being served, so the
        entry stays valid whether the bundled SVG or a studio-supplied PNG
        is in place."""
        _, mimetype = _read_first(ICON_CANDIDATES)
        if mimetype == 'image/png':
            return [
                {'src': '/corelab/icon', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
                {'src': '/corelab/icon', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
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
