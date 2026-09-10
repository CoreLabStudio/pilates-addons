# -*- coding: utf-8 -*-
"""Put the number next to the room it belongs to.

"Barre + Reformer 1 + 2 per week" gives a student no way to tell which
number is which room. The studio's own price sheet words it properly -
"1 Barre + 2 Reformer / semana" - and reads itself, so the shop should say
the same thing.

The monthly packs get "al mes" as well, so they no longer look like the
weekly plans at a glance. And the three of them stop being bare numbers in
Spanish and Catalan, which is what they were until now.

Only renames a product still carrying the name this expects to replace.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# xmlid -> (en_US, es_ES, ca_ES, the English name this expects to replace)
NAMES = {
    'fitness_packages.product_combo_2_2': (
        u'2 Barre + 2 Reformer per month',
        u'2 Barre + 2 Reformer al mes',
        u'2 Barre + 2 Reformer al mes',
        u'Barre + Reformer 2 + 2'),
    'fitness_packages.product_combo_4_4': (
        u'4 Barre + 4 Reformer per month',
        u'4 Barre + 4 Reformer al mes',
        u'4 Barre + 4 Reformer al mes',
        u'Barre + Reformer 4 + 4'),
    'fitness_packages.product_combo_6_6': (
        u'6 Barre + 6 Reformer per month',
        u'6 Barre + 6 Reformer al mes',
        u'6 Barre + 6 Reformer al mes',
        u'Barre + Reformer 6 + 6'),
    'fitness_subscriptions.product_combo_week_1_1': (
        u'1 Barre + 1 Reformer per week',
        u'1 Barre + 1 Reformer por semana',
        u'1 Barre + 1 Reformer per setmana',
        u'Barre + Reformer 1 + 1 per week'),
    'fitness_subscriptions.product_combo_week_2_1': (
        u'2 Barre + 1 Reformer per week',
        u'2 Barre + 1 Reformer por semana',
        u'2 Barre + 1 Reformer per setmana',
        u'Barre + Reformer 2 + 1 per week'),
    'fitness_subscriptions.product_combo_week_1_2': (
        u'1 Barre + 2 Reformer per week',
        u'1 Barre + 2 Reformer por semana',
        u'1 Barre + 2 Reformer per setmana',
        u'Barre + Reformer 1 + 2 per week'),
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
        "fitness_subscriptions: combined packs - %d renamed so the number "
        "sits beside its room, %d left alone, %d not found",
        renamed, skipped, missing)
