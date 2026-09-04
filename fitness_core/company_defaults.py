# -*- coding: utf-8 -*-
"""The studio's legal identity, supplied by the client.

Kept in one place because it has to be applied from two: a fresh database
installs the module and never runs a migration, while an existing one
upgrades and never runs the install hook. The first version of this only
handled the upgrade path, so a freshly built database - which is exactly what
odoo.sh builds from a branch - ended up serving Terms and checkout pages with
no company details on them at all.

The portal renders these fields live from res.company, so writing them here
fixes the Terms, the signup consent, both payment steps and the invoices
together.
"""
import logging

_logger = logging.getLogger(__name__)

# The VAT is stored country-prefixed because that is what Odoo, VIES and EU
# invoicing expect. The portal strips the ES prefix when displaying it, since
# a Spanish legal notice shows the bare NIF.
COMPANY_DETAILS = {
    'street': 'Carrer de la Noguera 39',
    'zip': '08230',
    'city': 'Matadepera',
    'vat': 'ESB88940010',
    'email': 'info@corelabstudio.es',
}
COUNTRY_CODE = 'ES'
STATE_NAME = 'Barcelona'


def apply_company_details(env):
    """Fill in any of the studio's legal details that are still empty.

    Only empty fields are written, so a correction the studio makes in
    Settings is never reverted by a later deploy.

    :return: the field names actually written
    """
    company = env.ref('base.main_company', raise_if_not_found=False)
    if not company:
        _logger.warning('main company not found; legal details not written')
        return []

    vals = {f: v for f, v in COMPANY_DETAILS.items() if not company[f]}

    country = company.country_id or env['res.country'].search(
        [('code', '=', COUNTRY_CODE)], limit=1)
    if country and not company.country_id:
        vals['country_id'] = country.id
    if country and not company.state_id:
        state = env['res.country.state'].search(
            [('country_id', '=', country.id), ('name', '=', STATE_NAME)], limit=1)
        if state:
            vals['state_id'] = state.id

    if not vals:
        _logger.info('company legal details already set; nothing to do')
        return []

    company.write(vals)
    written = sorted(vals)
    _logger.info('company legal details written: %s', ', '.join(written))
    return written
