# -*- coding: utf-8 -*-
"""Spanish and Catalan sale descriptions for the six combined products.

The combos were created with English copy only, so Spanish and Catalan
students read the English on the shop cards while every other product spoke
their language. These are field translations rather than catalogue terms -
description_sale is data, not a msgid - which is why they arrive as a
migration instead of a .po entry.

Written only where the stored translation is still the English text. Anyone
who has since edited a description in the back office keeps their wording;
this fills gaps, it does not overwrite decisions.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

TRANSLATIONS = {
    'fitness_subscriptions.product_combo_week_1_1': {
        'es_ES': u'Una clase de Barre y una de Reformer cada semana. Las dos '
                 u'disciplinas, todas las semanas, en un plan mensual.',
        'ca_ES': u'Una classe de Barre i una de Reformer cada setmana. Les dues '
                 u'disciplines, totes les setmanes, en un pla mensual.',
    },
    'fitness_subscriptions.product_combo_week_1_2': {
        'es_ES': u'Una clase de Barre y dos de Reformer cada semana. Para cuando '
                 u'el Reformer lleva la voz cantante y el Barre te mantiene en '
                 u'movimiento.',
        'ca_ES': u'Una classe de Barre i dues de Reformer cada setmana. Per quan '
                 u'el Reformer porta la veu cantant i el Barre et manté en '
                 u'moviment.',
    },
    'fitness_subscriptions.product_combo_week_2_1': {
        'es_ES': u'Dos clases de Barre y una de Reformer cada semana. Para cuando '
                 u'el Barre lleva la voz cantante y el Reformer te pone a prueba.',
        'ca_ES': u'Dues classes de Barre i una de Reformer cada setmana. Per quan '
                 u'el Barre porta la veu cantant i el Reformer et posa a prova.',
    },
    'fitness_packages.product_combo_2_2': {
        'es_ES': u'Dos clases de Barre y dos de Reformer cada mes. Cada disciplina '
                 u'guarda sus propios créditos, así que siempre tienes las dos '
                 u'esperándote.',
        'ca_ES': u'Dues classes de Barre i dues de Reformer cada mes. Cada '
                 u'disciplina guarda els seus propis crèdits, així que sempre '
                 u'tens les dues esperant-te.',
    },
    'fitness_packages.product_combo_4_4': {
        'es_ES': u'Cuatro clases de Barre y cuatro de Reformer cada mes. Las '
                 u'suficientes de cada una para ganar fuerza y técnica de verdad, '
                 u'en paralelo.',
        'ca_ES': u'Quatre classes de Barre i quatre de Reformer cada mes. Les '
                 u'suficients de cadascuna per guanyar força i tècnica de veritat, '
                 u'en paral·lel.',
    },
    'fitness_packages.product_combo_6_6': {
        'es_ES': u'Seis clases de Barre y seis de Reformer cada mes. Entrenar las '
                 u'dos disciplinas como rutina, a nuestro mejor precio combinado.',
        'ca_ES': u'Sis classes de Barre i sis de Reformer cada mes. Entrenar les '
                 u'dues disciplines com a rutina, al nostre millor preu combinat.',
    },
}


def migrate(cr, version):
    if not version:
        # fresh install: the data files have just written the English, and a
        # fresh database has no back-office edits to protect either way
        pass

    env = api.Environment(cr, SUPERUSER_ID, {})
    written = skipped = missing = 0

    for xmlid, langs in TRANSLATIONS.items():
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            missing += 1
            _logger.info("fitness_subscriptions: %s not present, skipped", xmlid)
            continue
        product = product.sudo()
        english = (product.with_context(lang='en_US').description_sale or '').strip()
        for lang, text in langs.items():
            if lang not in [c for c, _n in env['res.lang'].get_installed()]:
                continue
            current = (product.with_context(lang=lang).description_sale or '').strip()
            # only fill the gap: an existing translation is somebody's decision
            if current and current != english:
                skipped += 1
                continue
            product.with_context(lang=lang).write({'description_sale': text})
            written += 1

    _logger.info(
        "fitness_subscriptions: combo descriptions - %d translation(s) written, "
        "%d left as already translated, %d product(s) not found",
        written, skipped, missing)
