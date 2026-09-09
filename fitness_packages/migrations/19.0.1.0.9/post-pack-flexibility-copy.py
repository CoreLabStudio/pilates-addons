# -*- coding: utf-8 -*-
"""Append the pack-flexibility clause to the five class packs.

Students kept asking whether a pack tied them to one class in the timetable.
It never did, so the answer is now written on the product instead of being
something they have to ask.

data/products.xml is noupdate="1", so the seed does not reach an existing
database - this does, in all three languages.

Two things are done the way 19.0.1.0.8 established, because both were learned
the hard way:

  * the stored jsonb is read with SQL, not through the ORM. A translatable
    field falls back to the source language when a translation is missing, so
    an ORM read makes an untranslated record look like it already has the
    clause the moment en_US is written.
  * en_US is written first. Changing the source term on a translate=True field
    can re-sync the other languages, so the translations are written after it,
    never before.

Idempotent. The clause names the pack's own discipline; the approved wording
says Barre because it was written for the Barre packs, and putting "any Barre
class" on a Reformer pack would be wrong on its face.
"""
import logging

_logger = logging.getLogger(__name__)

CLAUSE = {
    'en_US': u' Valid for any %s class on the timetable — you choose which, and when.',
    'es_ES': u' Válidas para cualquier clase de %s del horario: tú eliges cuál y cuándo.',
    'ca_ES': u" Vàlides per a qualsevol classe de %s de l'horari: tu tries quina i quan.",
}
LANG_ORDER = ('en_US', 'es_ES', 'ca_ES')

PACKS = [
    ('fitness_packages.product_barre_5pack',     'Barre'),
    ('fitness_packages.product_barre_10pack',    'Barre'),
    ('fitness_packages.product_reformer_5pack',  'Reformer'),
    ('fitness_packages.product_reformer_10pack', 'Reformer'),
    ('fitness_packages.product_reformer_15pack', 'Reformer'),
]


def migrate(cr, version):
    if not version:
        return          # fresh install: the seed and catalogue already carry it

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    added = skipped = 0
    for xmlid, disc in PACKS:
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            _logger.warning("[PACKCOPY] %s not found; skipped", xmlid)
            continue

        cr.execute("SELECT description_sale FROM product_template WHERE id = %s",
                   (product.id,))
        row = cr.fetchone()
        stored = (row[0] if row and isinstance(row[0], dict) else {}) or {}

        for lang in LANG_ORDER:
            clause = CLAUSE[lang] % disc
            current = (stored.get(lang) or '').strip()
            if not current:
                _logger.info("[PACKCOPY] %s [%s] has no description; skipped",
                             xmlid, lang)
                continue
            if clause.strip() in current:
                skipped += 1
                continue
            product.with_context(lang=lang).description_sale = current + clause
            added += 1
            _logger.info("[PACKCOPY] %s [%s] clause appended", xmlid, lang)

    _logger.info("[PACKCOPY] Flexibility clause: %d string(s) added, %d already "
                 "present.", added, skipped)
