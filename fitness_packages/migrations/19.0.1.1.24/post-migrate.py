# -*- coding: utf-8 -*-
"""Courtesy credits: 15 days, and names in all three languages.

Two jobs, both of which a data file cannot do, because these records
carry noupdate="1" and an upgrade will not touch them once they exist:

  1. The two group courtesy products were created with a 30-day
     validity. The studio wants 15. This sets 15 ONLY where the value is
     still exactly 30 - if the owner has set anything else, that is her
     decision and it is left alone, which is the whole point of
     noupdate.

     The data file now says 15 as well, for FRESH installs, which never
     run a migration. So on a database built from here on this step
     finds 15 already and says so, rather than reporting our own number
     as somebody's edit.

  2. Their names were written in Spanish with no translations at all, so
     a manager reading the back office in Catalan or English saw
     Spanish. The names are set per language here, again only where
     nothing has been put there already.

CREDITS ALREADY GIVEN ARE NOT TOUCHED, and cannot be: a package line's
expiry is fitness_validity_end_date, written once onto the order line
when the order is confirmed. Changing the product's validity_days
changes what the NEXT credit gets and nothing about one already in
somebody's hands.
"""
import logging

_logger = logging.getLogger(__name__)

OLD_DAYS = 30
NEW_DAYS = 15

NAMES = {
    'fitness_packages.product_courtesy_barre': {
        'en_US': 'Free Barre class',
        'es_ES': 'Clase de cortesía (Barre)',
        'ca_ES': 'Classe de cortesia (Barre)',
    },
    'fitness_packages.product_courtesy_reformer': {
        'en_US': 'Free Reformer class',
        'es_ES': 'Clase de cortesía (Reformer)',
        'ca_ES': 'Classe de cortesia (Reformer)',
    },
    'fitness_packages.product_courtesy_barre_private': {
        'en_US': 'Free private Barre class',
        'es_ES': 'Clase privada de cortesía (Barre)',
        'ca_ES': 'Classe privada de cortesia (Barre)',
    },
    'fitness_packages.product_courtesy_reformer_private': {
        'en_US': 'Free private Reformer class',
        'es_ES': 'Clase privada de cortesía (Reformer)',
        'ca_ES': 'Classe privada de cortesia (Reformer)',
    },
}

# What the two group products were SHIPPED with. Finding one of these is
# not an owner edit - it is the value the data file put there - so it may
# be replaced. Anything else is hers and is left alone.
SHIPPED = (
    'Clase de cortesía (Barre)',
    'Clase de cortesía (Reformer)',
)

VALIDITY = (
    'fitness_packages.product_courtesy_barre',
    'fitness_packages.product_courtesy_reformer',
)


def migrate(cr, version):
    if not version:
        return
    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    # ── 1. validity, only where it is still the old default ──────────
    changed, skipped, missing = [], [], []
    for xmlid in VALIDITY:
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            missing.append(xmlid)
            continue
        current = product.fitness_validity_days
        if current == OLD_DAYS:
            product.fitness_validity_days = NEW_DAYS
            changed.append('%s (%s -> %s days)' % (xmlid, current, NEW_DAYS))
        elif current == NEW_DAYS:
            # A database installed after the data file was changed already
            # has 15. Saying "somebody chose it" about our own value would
            # be a lie in the log of every build from here on.
            skipped.append('%s (already %s days, nothing to do)'
                           % (xmlid, current))
        else:
            skipped.append('%s (left at %s days - neither the old default '
                           'nor ours, so somebody chose it)'
                           % (xmlid, current))

    for line in changed:
        _logger.info("[COURTESY] validity changed: %s", line)
    for line in skipped:
        _logger.info("[COURTESY] validity skipped: %s", line)
    for line in missing:
        _logger.warning("[COURTESY] product not found, nothing done: %s", line)
    _logger.info("[COURTESY] validity: %d changed, %d skipped, %d missing",
                 len(changed), len(skipped), len(missing))

    # ── 2. names, only where that language has nothing ───────────────
    installed = set(env['res.lang'].search([]).mapped('code'))
    named, left = 0, 0
    for xmlid, by_lang in NAMES.items():
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            _logger.warning("[COURTESY] not found, no name set: %s", xmlid)
            continue
        for lang, value in by_lang.items():
            if lang not in installed:
                continue
            existing = product.with_context(lang=lang).name
            # Odoo falls back to the source language when a translation is
            # missing, so "already translated" means it differs from the
            # English and from what we are about to write.
            if (existing and existing not in SHIPPED
                    and existing != by_lang['en_US'] and existing != value):
                left += 1
                _logger.info(
                    "[COURTESY] %s %s left alone, already reads %r",
                    xmlid, lang, existing)
                continue
            product.with_context(lang=lang).name = value
            named += 1
    _logger.info("[COURTESY] names: %d set, %d left as the studio had them",
                 named, left)
