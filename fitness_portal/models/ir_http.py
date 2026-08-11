from odoo import models
from odoo.http import request

_PORTAL_LANGS = frozenset({'en_US', 'es_ES', 'ca_ES'})


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _get_mv_lang(cls):
        mv_lang = request.cookies.get('mv_lang')
        if not mv_lang or mv_lang not in _PORTAL_LANGS:
            # No explicit user preference — let Odoo's default lang handling apply.
            # Returning None here prevents forcing es_ES on every request (which breaks
            # core Odoo test runs where no cookies are set).
            return None
        return request.env['res.lang']._get_data(code=mv_lang)

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        # _frontend_pre_dispatch handles frontend routes already.
        # For non-frontend auth='none' routes like /web/login, apply mv_lang here.
        if not getattr(request, 'is_frontend', False):
            try:
                lang_data = cls._get_mv_lang()
                if lang_data:
                    request.update_context(lang=lang_data.code)
            except Exception:
                pass

    @classmethod
    def _frontend_pre_dispatch(cls):
        super()._frontend_pre_dispatch()
        lang_data = cls._get_mv_lang()
        if lang_data:
            request.lang = lang_data
            request.update_context(lang=lang_data.code)
            # Sync frontend_lang cookie so _match picks the right lang next request.
            request.future_response.set_cookie('frontend_lang', lang_data.code)
