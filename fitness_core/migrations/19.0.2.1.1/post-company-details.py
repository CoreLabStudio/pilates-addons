# -*- coding: utf-8 -*-
"""Fill in the studio's legal identity, supplied by the client.

The company record had a name and an email and nothing else - no address, no
NIF - which is why the Terms and the signup consent had nothing to show. The
portal renders those fields live, so writing them here fixes the Terms, the
signup consent, the checkout pages and the invoices together.

A migration rather than a data file on purpose. A data file with
noupdate="0" would reapply on every single upgrade and quietly revert any
correction the studio later makes in Settings > Companies, and with
noupdate="1" it would never reach an existing database at all. This runs
once, on the upgrade to this version.

Only empty fields are filled, so the studio's own edits always win over this.
"""
import logging

_logger = logging.getLogger(__name__)

# Supplied by the studio. The VAT is stored country-prefixed because that is
# what Odoo, VIES and EU invoicing expect; the portal strips the ES prefix
# when displaying it, since a Spanish legal notice shows the bare NIF.
DETAILS = {
    'street': 'Carrer de la Noguera 39',
    'zip': '08230',
    'city': 'Matadepera',
    'vat': 'ESB88940010',
    'email': 'info@corelabstudio.es',
}
COUNTRY_CODE = 'ES'
STATE_NAME = 'Barcelona'


def migrate(cr, version):
    if not version:
        return

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    company = env.ref('base.main_company', raise_if_not_found=False)
    if not company:
        _logger.warning('main company not found; legal details not written')
        return

    vals = {f: v for f, v in DETAILS.items() if not company[f]}

    # country and province are decided independently: this database already
    # had the country set, which on the first pass skipped the province with it
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
        return

    company.write(vals)
    _logger.info('company legal details written: %s', ', '.join(sorted(vals)))
