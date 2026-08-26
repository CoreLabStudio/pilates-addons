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
    ('fitness_core/static/src/img/corelab-logo-blue-square.png', 'image/png'),
]
ICON_CANDIDATES = [
    ('fitness_core/static/src/img/corelab-logo-blue-square.png', 'image/png'),
    ('fitness_core/static/src/img/corelab-icon.svg', 'image/svg+xml'),
    ('fitness_core/static/src/img/corelab-logo-blue-square.png', 'image/png'),
]


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
