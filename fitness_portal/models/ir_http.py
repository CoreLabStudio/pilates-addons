from odoo import models, tools
from odoo.http import request

_PORTAL_LANGS = frozenset({'en_US', 'es_ES', 'ca_ES'})


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _get_mv_lang(cls):
        mv_lang = request.cookies.get('mv_lang')
        if not mv_lang or mv_lang not in _PORTAL_LANGS:
            if tools.config.get('test_enable'):
                return None
            mv_lang = 'es_ES'
        return request.env['res.lang']._get_data(code=mv_lang)

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        # Portal language (mv_lang) applies only to frontend routes via
        # _frontend_pre_dispatch below. Do NOT override language for backend
        # routes — admins manage their language via their user preferences.

    @classmethod
    def _frontend_pre_dispatch(cls):
        super()._frontend_pre_dispatch()
        lang_data = cls._get_mv_lang()
        if lang_data:
            request.lang = lang_data
            request.update_context(lang=lang_data.code)
            request.future_response.set_cookie('frontend_lang', lang_data.code)
            # Read by ir_qweb to put a matching lang on <html>. Kept as a
            # request attribute rather than re-deriving the cookie there, so
            # exactly the pages that adopted the portal language declare it.
            request.mv_portal_lang = lang_data.code
