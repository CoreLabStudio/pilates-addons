# -*- coding: utf-8 -*-
"""Make sure the registration fee product exists on an existing database.

data/products.xml is noupdate="1", which stops a module update reverting live
prices - but it also means a *new* record in that file does reach an existing
database on the update that introduces it, since there is nothing there yet to
protect. This is the belt to that braces: if the seed did not land for any
reason, the checkout would silently stop charging the fee rather than fail
loudly, so the product is verified here and created if missing.

Idempotent, and it never touches the price of a fee that already exists - the
studio may have changed it, and this is not the place to overrule that.
"""
import logging

_logger = logging.getLogger(__name__)

XMLID = 'fitness_subscriptions.product_matricula'
DEFAULT_PRICE = 39.00


def migrate(cr, version):
    if not version:
        return          # fresh install: the seed creates it

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    product = env.ref(XMLID, raise_if_not_found=False)
    if product:
        _logger.info(
            "[MATRICULA] Registration product present: %s at %.2f (active=%s, "
            "sale_ok=%s)", product.display_name, product.list_price,
            product.active, product.sale_ok)
        return

    product = env['product.template'].create({
        'name': 'Registration (Matrícula)',
        'type': 'service',
        'list_price': DEFAULT_PRICE,
        'sale_ok': False,
        'purchase_ok': False,
        'fitness_is_matricula': True,
        'description_sale': 'One-off registration fee, charged with your '
                            'first membership.',
    })
    module, name = XMLID.split('.')
    env['ir.model.data'].create({
        'module': module,
        'name': name,
        'model': 'product.template',
        'res_id': product.id,
        'noupdate': True,
    })
    _logger.info("[MATRICULA] Created registration product %s at %.2f",
                 product.display_name, DEFAULT_PRICE)
