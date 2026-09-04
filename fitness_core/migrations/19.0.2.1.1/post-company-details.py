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
from odoo import api, SUPERUSER_ID

from odoo.addons.fitness_core.company_defaults import apply_company_details


def migrate(cr, version):
    """Existing databases. A fresh one is handled by post_init_hook instead."""
    if not version:
        return
    apply_company_details(api.Environment(cr, SUPERUSER_ID, {}))
