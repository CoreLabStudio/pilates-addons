# -*- coding: utf-8 -*-
"""Name the Barre intro pack in Spanish and Catalan.

It missed the sweep that named every other product. That migration was
written listing what existed at the time, and this product was created in
the commit after it - so it shipped as the one item in the shop still
showing English to Spanish and Catalan students.

Named to match the Reformer intro pack, which is the same offer for the
other room.

Only names a product nobody has named themselves.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

XMLID = 'fitness_packages.product_barre_intro3'
EN = u'Barre Intro Pack (3 classes)'
ES = u'Barre Intro Bono (3 Clases)'
CA = u'Barre Intro Bo (3 Classes)'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    product = env.ref(XMLID, raise_if_not_found=False)
    if not product:
        _logger.info("fitness_subscriptions: %s not present, skipped", XMLID)
        return

    product = product.sudo().with_context(active_test=False)
    installed = [code for code, _name in env['res.lang'].get_installed()]
    english = (product.with_context(lang='en_US').name or '').strip()

    for lang in ('es_ES', 'ca_ES'):
        if lang not in installed:
            continue
        current = (product.with_context(lang=lang).name or '').strip()
        if current and current != english:
            _logger.info(
                "fitness_subscriptions: %s already named %r in %s - left alone",
                XMLID, current, lang)
            return

    if english != EN:
        _logger.info(
            "fitness_subscriptions: %s is named %r, not the name this expected "
            "- left alone", XMLID, english)
        return

    for lang, text in (('en_US', EN), ('es_ES', ES), ('ca_ES', CA)):
        if lang == 'en_US' or lang in installed:
            product.with_context(lang=lang).write({'name': text})

    _logger.info(
        "fitness_subscriptions: Barre intro pack named in three languages")
