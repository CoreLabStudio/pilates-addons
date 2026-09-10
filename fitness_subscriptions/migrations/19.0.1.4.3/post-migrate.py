# -*- coding: utf-8 -*-
"""Put the shop's product names into all three languages.

These were first applied by hand, straight onto the databases, which left
them nowhere in version control: a fresh install had every product named in
one language only, and reinstalling the module would have dropped Spanish
and Catalan on a live site without anything to restore them from.

Only touches products nobody has translated - where Spanish and Catalan are
either absent or still repeating the English. That makes this a no-op
against staging and production, which already hold these exact values, and
it means a name somebody has since edited in the back office is left alone
rather than being reset to what this file happens to say.

The English name is rewritten too. Several products were seeded with a
Spanish name as their source, so setting only the translations would leave
English readers on the Spanish one.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# xmlid -> (en_US, es_ES, ca_ES)
NAMES = {
    'fitness_packages.product_barre_10pack': (
        'Barre 10-pack',
        'Bono de 10 clases de Barre',
        'Bo de 10 classes de Barre'),
    'fitness_packages.product_barre_5pack': (
        'Barre 5-pack',
        'Bono de 5 clases de Barre',
        'Bo de 5 classes de Barre'),
    'fitness_packages.product_barre_privada_5pack': (
        'Barre Private Pack 5',
        'Bono Barre Privada 5',
        'Bo Barre Privada 5'),
    'fitness_packages.product_barre_privada_single': (
        'Barre Private Single Class',
        'Barre Privada Clase Suelta',
        'Barre Privada Classe Solta'),
    'fitness_packages.product_barre_trial': (
        'Barre Trial Class',
        'Clase de prueba de Barre',
        'Classe de prova de Barre'),
    'fitness_packages.product_combo_2_2': (
        'Barre + Reformer 2 + 2',
        'Barre + Reformer 2 + 2',
        'Barre + Reformer 2 + 2'),
    'fitness_packages.product_combo_4_4': (
        'Barre + Reformer 4 + 4',
        'Barre + Reformer 4 + 4',
        'Barre + Reformer 4 + 4'),
    'fitness_packages.product_combo_6_6': (
        'Barre + Reformer 6 + 6',
        'Barre + Reformer 6 + 6',
        'Barre + Reformer 6 + 6'),
    'fitness_packages.product_duo_10pack': (
        'Reformer Duo Pack 10',
        'Bono Reformer Dúo 10',
        'Bo Reformer Dúo 10'),
    'fitness_packages.product_duo_5pack': (
        'Reformer Duo Pack 5',
        'Bono Reformer Dúo 5',
        'Bo Reformer Dúo 5'),
    'fitness_packages.product_duo_single': (
        'Reformer Duo Single',
        'Reformer Dúo Clase Suelta',
        'Reformer Dúo Classe Solta'),
    'fitness_packages.product_private_10pack': (
        'Reformer Private Pack 10',
        'Bono Reformer Privado 10',
        'Bo Reformer Privat 10'),
    'fitness_packages.product_private_5pack': (
        'Reformer Private Pack 5',
        'Bono Reformer Privado 5',
        'Bo Reformer Privat 5'),
    'fitness_packages.product_private_single': (
        'Reformer Private Single',
        'Reformer Privado Clase Suelta',
        'Reformer Privat Classe Solta'),
    'fitness_packages.product_reformer_10pack': (
        'Reformer Pack 10',
        'Bono Reformer 10',
        'Bo Reformer 10'),
    'fitness_packages.product_reformer_15pack': (
        'Reformer Pack 15',
        'Bono Reformer 15',
        'Bo Reformer 15'),
    'fitness_packages.product_reformer_5pack': (
        'Reformer Pack 5',
        'Bono Reformer 5',
        'Bo Reformer 5'),
    'fitness_packages.product_reformer_intro3': (
        'Reformer Intro Pack (3 classes)',
        'Reformer Intro Bono (3 Clases)',
        'Reformer Intro Bo (3 Classes)'),
    'fitness_packages.product_reformer_trial': (
        'Reformer Trial Class',
        'Reformer Clase de prueba',
        'Reformer Classe de prova'),
    'fitness_subscriptions.product_barre_clase_fija_1': (
        'Barre Fixed Class 1 (Opening promo)',
        'Barre Clase Fija 1 (Promo de apertura)',
        "Barre Classe Fixa 1 (Promo d'obertura)"),
    'fitness_subscriptions.product_barre_clase_fija_2': (
        'Barre Fixed Class 2 (Opening promo)',
        'Barre Clase Fija 2 (Promo de apertura)',
        "Barre Classe Fixa 2 (Promo d'obertura)"),
    'fitness_subscriptions.product_barre_ilimitado': (
        'Barre Unlimited',
        'Barre Ilimitado',
        'Barre Il·limitat'),
    'fitness_subscriptions.product_barre_ilimitado_promo': (
        'Barre Unlimited (Promo)',
        'Barre Ilimitado Promo',
        'Barre Il·limitat Promo'),
    'fitness_subscriptions.product_barre_privada_clase_fija': (
        'Barre Private Fixed Class',
        'Barre Privada Clase Fija',
        'Barre Privada Classe Fixa'),
    'fitness_subscriptions.product_combo_week_1_1': (
        'Barre + Reformer 1 + 1 per week',
        'Barre + Reformer 1 + 1 por semana',
        'Barre + Reformer 1 + 1 per setmana'),
    'fitness_subscriptions.product_combo_week_1_2': (
        'Barre + Reformer 1 + 2 per week',
        'Barre + Reformer 1 + 2 por semana',
        'Barre + Reformer 1 + 2 per setmana'),
    'fitness_subscriptions.product_combo_week_2_1': (
        'Barre + Reformer 2 + 1 per week',
        'Barre + Reformer 2 + 1 por semana',
        'Barre + Reformer 2 + 1 per setmana'),
    'fitness_subscriptions.product_reformer_mensual_1': (
        'Reformer Monthly 1 (Opening promo)',
        'Reformer Mensual 1 (Promo de apertura)',
        "Reformer Mensual 1 (Promo d'obertura)"),
    'fitness_subscriptions.product_reformer_mensual_2': (
        'Reformer Monthly 2 (Opening promo)',
        'Reformer Mensual 2 (Promo de apertura)',
        "Reformer Mensual 2 (Promo d'obertura)"),
    'fitness_subscriptions.product_reformer_mensual_3': (
        'Reformer Monthly 3 (Opening promo)',
        'Reformer Mensual 3 (Promo de apertura)',
        "Reformer Mensual 3 (Promo d'obertura)"),
    'fitness_subscriptions.product_reformer_privado_clase_fija': (
        'Reformer Private Fixed Class',
        'Reformer Privado Clase Fija',
        'Reformer Privat Classe Fixa'),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = [code for code, _name in env['res.lang'].get_installed()]
    written = skipped = missing = 0

    for xmlid, (en, es, ca) in NAMES.items():
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            missing += 1
            continue
        product = product.sudo()

        english = (product.with_context(lang='en_US').name or '').strip()
        translated = False
        for lang in ('es_ES', 'ca_ES'):
            if lang not in installed:
                continue
            current = (product.with_context(lang=lang).name or '').strip()
            if current and current != english:
                translated = True
        if translated:
            # somebody's wording is already here - leave the record alone
            skipped += 1
            continue

        product.with_context(lang='en_US').write({'name': en})
        for lang, text in (('es_ES', es), ('ca_ES', ca)):
            if lang in installed:
                product.with_context(lang=lang).write({'name': text})
        written += 1

    _logger.info(
        "fitness_subscriptions: product names - %d product(s) named in three "
        "languages, %d left as already translated, %d not found",
        written, skipped, missing)
