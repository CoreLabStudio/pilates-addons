# -*- coding: utf-8 -*-
"""Call the Reformer weekly promos "Clase Fija", like everything else.

Barre has always called these Clase Fija; Reformer called them Mensual. The
hidden full-price tiers were just brought into line, which left the live
Reformer promos as the only products still using the old word - so a
student comparing rooms saw the same thing described two different ways.

These three are live and purchasable, unlike the hidden tiers. That is safe
here because a product's name is only ever a display name: sale.order.line
carries its own description, copied when the line is created, so an order
placed yesterday keeps the wording it was sold under and nothing already
issued changes. Only the shop and any future order read from here.

Only renames a product still carrying the old name, so somebody's own
wording is never overwritten.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# xmlid -> (en_US, es_ES, ca_ES, the English name this expects to replace)
NAMES = {
    'fitness_subscriptions.product_reformer_mensual_1': (
        u'Reformer Fixed Class 1 (Opening promo)',
        u'Reformer Clase Fija 1 (Promo de apertura)',
        u"Reformer Classe Fixa 1 (Promo d'obertura)",
        u'Reformer Monthly 1 (Opening promo)'),
    'fitness_subscriptions.product_reformer_mensual_2': (
        u'Reformer Fixed Class 2 (Opening promo)',
        u'Reformer Clase Fija 2 (Promo de apertura)',
        u"Reformer Classe Fixa 2 (Promo d'obertura)",
        u'Reformer Monthly 2 (Opening promo)'),
    'fitness_subscriptions.product_reformer_mensual_3': (
        u'Reformer Fixed Class 3 (Opening promo)',
        u'Reformer Clase Fija 3 (Promo de apertura)',
        u"Reformer Classe Fixa 3 (Promo d'obertura)",
        u'Reformer Monthly 3 (Opening promo)'),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = [code for code, _name in env['res.lang'].get_installed()]
    renamed = skipped = missing = 0

    for xmlid, (en, es, ca, expected_old) in NAMES.items():
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            missing += 1
            continue
        product = product.sudo().with_context(active_test=False)

        current = (product.with_context(lang='en_US').name or '').strip()
        if current not in (expected_old, en):
            _logger.info(
                "fitness_subscriptions: %s is named %r, not the name this "
                "expected to replace - left alone", xmlid, current)
            skipped += 1
            continue

        product.with_context(lang='en_US').write({'name': en})
        for lang, text in (('es_ES', es), ('ca_ES', ca)):
            if lang in installed:
                product.with_context(lang=lang).write({'name': text})
        renamed += 1

    _logger.info(
        "fitness_subscriptions: live Reformer promos - %d renamed, %d left "
        "alone, %d not found. Past orders keep their own descriptions.",
        renamed, skipped, missing)
