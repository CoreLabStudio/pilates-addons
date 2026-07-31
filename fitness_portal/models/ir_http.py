from odoo import models
from odoo.http import request

_PORTAL_LANGS = frozenset({'en_US', 'es_ES', 'ca_ES'})


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _frontend_pre_dispatch(cls):
        super()._frontend_pre_dispatch()
        # mv_lang is set by /my/set_lang. Apply AFTER super() so our choice
        # overrides any lang the base machinery derived from session/URL/cookie.
        mv_lang = request.cookies.get('mv_lang')
        if mv_lang and mv_lang in _PORTAL_LANGS:
            lang_data = request.env['res.lang']._get_data(code=mv_lang)
            if lang_data:
                request.lang = lang_data
                request.update_context(lang=mv_lang)
