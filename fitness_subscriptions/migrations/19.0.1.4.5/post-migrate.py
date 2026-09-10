# -*- coding: utf-8 -*-
"""Name the full-price weekly tiers properly, before anyone sees them.

These five sit archived, waiting for the day the opening promo ends. Their
names still read "+1 Promo" - which is exactly backwards, because they are
the tiers that apply once the promo is over - and they exist in English
only, unlike every other product in the shop.

None of that shows today. It would show the moment somebody activates them,
which is a day for flipping a switch, not for discovering that five
products need renaming and translating first.

Named for what they are: the plain tier, sitting under the "(Opening
promo)" version it eventually replaces. Both rooms use "Clase Fija", so
the pair reads the same whichever discipline a student is looking at.

Only touches a product nobody has renamed. If somebody has already given
one of these a name of their own, theirs stands.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# xmlid -> (en_US, es_ES, ca_ES), and the name we expect to be replacing
NAMES = {
    'fitness_subscriptions.product_barre_clase_fija_1_promo': (
        u'Barre Fixed Class 1',
        u'Barre Clase Fija 1',
        u'Barre Classe Fixa 1',
        u'Barre Clase Fija 1 +1 Promo'),
    'fitness_subscriptions.product_barre_clase_fija_2_promo': (
        u'Barre Fixed Class 2',
        u'Barre Clase Fija 2',
        u'Barre Classe Fixa 2',
        u'Barre Clase Fija 2 +1 Promo'),
    'fitness_subscriptions.product_reformer_mensual_1_promo': (
        u'Reformer Fixed Class 1',
        u'Reformer Clase Fija 1',
        u'Reformer Classe Fixa 1',
        u'Reformer Mensual 1 +1 Promo'),
    'fitness_subscriptions.product_reformer_mensual_2_promo': (
        u'Reformer Fixed Class 2',
        u'Reformer Clase Fija 2',
        u'Reformer Classe Fixa 2',
        u'Reformer Mensual 2 +1 Promo'),
    'fitness_subscriptions.product_reformer_mensual_3_promo': (
        u'Reformer Fixed Class 3',
        u'Reformer Clase Fija 3',
        u'Reformer Classe Fixa 3',
        u'Reformer Mensual 3 +1 Promo'),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = [code for code, _name in env['res.lang'].get_installed()]
    renamed = skipped = missing = 0

    for xmlid, (en, es, ca, expected_old) in NAMES.items():
        # archived records are invisible to a plain ref lookup
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            missing += 1
            continue
        product = product.sudo().with_context(active_test=False)

        current = (product.with_context(lang='en_US').name or '').strip()
        if current not in (expected_old, en):
            # somebody has named this themselves - leave it be
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
        "fitness_subscriptions: full-price tiers - %d renamed and translated, "
        "%d left alone, %d not found",
        renamed, skipped, missing)
