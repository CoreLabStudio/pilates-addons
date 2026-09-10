# -*- coding: utf-8 -*-
"""Describe the two Barre packs in Spanish and Catalan.

Both were created after the sweep that translated every product
description, so they shipped reading English on the shop card to Spanish
and Catalan students. Their names were caught; their descriptions were not.

Worded off the Reformer equivalents, which are the same offer for the other
room, so the pair reads the same either side.

Only writes where nobody has written their own - a description edited in
the back office stands.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# xmlid -> {lang: description}
DESCRIPTIONS = {
    'fitness_packages.product_barre_intro3': {
        'es_ES': u'Tres clases de Barre para encontrar tu sitio. Las suficientes '
                 u'para aprender la técnica y notar la diferencia.',
        'ca_ES': u'Tres classes de Barre per trobar el teu lloc. Les suficients '
                 u'per aprendre la tècnica i notar la diferència.',
    },
    'fitness_packages.product_barre_privada_5pack': {
        'es_ES': u'Cinco sesiones privadas de Barre, totalmente personalizadas '
                 u'según tus objetivos. Reserva cuando mejor te venga, en '
                 u'sesiones individuales con tu instructora.',
        'ca_ES': u'Cinc sessions privades de Barre, totalment personalitzades '
                 u'segons els teus objectius. Reserva quan millor et vagi, en '
                 u'sessions individuals amb la teva instructora.',
    },
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = [code for code, _name in env['res.lang'].get_installed()]
    written = skipped = missing = 0

    for xmlid, langs in DESCRIPTIONS.items():
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            missing += 1
            continue
        product = product.sudo().with_context(active_test=False)
        english = (product.with_context(lang='en_US').description_sale or '').strip()

        for lang, text in langs.items():
            if lang not in installed:
                continue
            current = (product.with_context(lang=lang).description_sale or '').strip()
            if current and current != english:
                skipped += 1
                continue
            product.with_context(lang=lang).write({'description_sale': text})
            written += 1

    _logger.info(
        "fitness_subscriptions: Barre pack descriptions - %d written, %d left "
        "as already translated, %d not found", written, skipped, missing)
