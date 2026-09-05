from odoo import models
from odoo.http import request


class IrQweb(models.AbstractModel):
    """Give the rendered page an <html lang> that matches the portal language.

    web.layout renders ``<html t-att="html_data or {}">`` and nothing in this
    database ever sets html_data - the module that normally does is `website`,
    which is not installed here. So every portal and auth page went out with no
    lang attribute at all.

    That is not only a validity problem. The browser picks the language for its
    OWN interface text from <html lang>, so with the attribute missing it fell
    back to the browser's UI language: a Spanish signup form answered an empty
    required field with "Please fill out this field." in English. The same
    source drives the native date picker, which is why the calendar code
    carries a comment about <html lang> being empty and passes the language
    down through a data attribute instead.

    Set here rather than in each template because there is one <html> element
    for the whole site and every page should agree about what language it is
    in. Scoped to requests that went through the portal language logic, so the
    back office keeps whatever behaviour it had.
    """
    _inherit = 'ir.qweb'

    def _prepare_environment(self, values):
        # Deliberately NOT html_data. web.frontend_layout and four sibling
        # templates each do t-set="html_data" with a fresh dict, which replaces
        # whatever was passed in rather than adding to it - so a value set here
        # under that name is thrown away before <html> is reached. This value
        # has a name no stock template touches, and the layout override reads
        # it into a t-att-lang of its own.
        code = None
        try:
            code = getattr(request, 'mv_portal_lang', None)
        except RuntimeError:
            # rendering outside a request (cron, mail) - no portal language
            pass
        # Always set the key: the template reads it unconditionally, and an
        # undefined name would raise on every back-office render instead.
        # BCP 47 uses a hyphen; Odoo's locale codes use an underscore.
        values.setdefault('mv_html_lang', code.replace('_', '-') if code else None)

        return super()._prepare_environment(values)
