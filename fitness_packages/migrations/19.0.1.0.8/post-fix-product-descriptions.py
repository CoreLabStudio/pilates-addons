# -*- coding: utf-8 -*-
"""Correct the shop descriptions: encoding, translations, stale day counts, tone.

Four problems, one pass:

  1. ENCODING. "Reformer Intro Bono (3 Clases)" carried a mojibake em dash in
     English - UTF-8 bytes decoded as Latin-1 by some earlier import. It was
     live and sellable.

  2. MISSING TRANSLATIONS. "Barre Privada Single Class" and "Reformer Privado
     Single" existed in English only, on active products, so Spanish and
     Catalan students read English.

  3. STALE DAY COUNTS. Several descriptions restated the validity period in
     prose - "valid for 60 days". That number already appears as a field, and
     duplicating it means the sentence goes stale the moment the field
     changes, which is exactly what happens when the price-sheet corrections
     land. The prose now describes the pack; the field states the number.

  4. UNEVEN TONE. Some entries just restated the product name and the validity
     ("5 Reformer group classes, valid for 90 days."). Rewritten to match the
     ones that were already good.

WHY BY NAME
-----------
Record ids differ between databases - established when prod_13 was written,
where an id-based script would have hit the wrong records. These products carry
xmlids, but the xmlids no longer match the names in several cases (the studio
renamed things), so the name is the reliable key here.

IDEMPOTENT
----------
A language already holding the new text is skipped. Anything replaced is logged
in full, so a value overwritten by mistake can be read back out of the log.

NOT IN THE SEED
---------------
description_sale appears nowhere in products.xml and is set by no Python; these
strings only ever existed as data. That means a FRESH install still gets no
descriptions at all - this migration repairs existing databases only. Closing
that gap means adding description_sale for all 24 sellable products to the seed
XML, which is a separate piece of work.
"""
import logging

_logger = logging.getLogger(__name__)

#: {product name: {lang: text}}
DESCRIPTIONS = {
    'Reformer Intro Bono (3 Clases)': {
        'en_US': "Three Reformer classes to get properly acquainted with the machine. "
                 "Long enough to stop thinking about it and start moving.",
        'es_ES': "Tres clases de Reformer para conocer la máquina de verdad. "
                 "Las suficientes para dejar de pensarla y empezar a moverte.",
        'ca_ES': "Tres classes de Reformer per conèixer la màquina de debò. "
                 "Les suficients per deixar de pensar-hi i començar a moure't.",
    },
    'Barre Privada Single Class': {
        'es_ES': "Sesión privada de Barre, solo tú y tu instructora. "
                 "Técnica personalizada y atención completa.",
        'ca_ES': "Sessió privada de Barre, només tu i la teva instructora. "
                 "Tècnica personalitzada i atenció completa.",
    },
    'Reformer Privado Single': {
        'es_ES': "Sesión privada de Reformer. Toda la atención de tu instructora "
                 "y progresiones adaptadas a ti.",
        'ca_ES': "Sessió privada de Reformer. Tota l'atenció de la teva instructora "
                 "i progressions adaptades a tu.",
    },
    'Barre 5-pack': {
        'en_US': "Five Barre group classes to build the habit. "
                 "Enough to find your rhythm and feel the change.",
        'es_ES': "Cinco clases grupales de Barre para crear el hábito. "
                 "Las justas para encontrar tu ritmo y notar el cambio.",
        'ca_ES': "Cinc classes grupals de Barre per crear l'hàbit. "
                 "Les justes per trobar el teu ritme i notar el canvi.",
    },
    'Barre 10-pack': {
        'en_US': "Ten Barre group classes for when you're ready to commit. "
                 "The point where technique starts to feel like yours.",
        'es_ES': "Diez clases grupales de Barre para cuando quieras comprometerte. "
                 "El punto en el que la técnica empieza a ser tuya.",
        'ca_ES': "Deu classes grupals de Barre per quan vulguis comprometre't. "
                 "El punt en què la tècnica comença a ser teva.",
    },
    'Reformer Pack 5': {
        'en_US': "Five Reformer group classes at your own pace. "
                 "A solid first block to learn the machine and see where it takes you.",
        'es_ES': "Cinco clases grupales de Reformer a tu ritmo. "
                 "Un primer bloque sólido para aprender la máquina y ver hasta dónde te lleva.",
        'ca_ES': "Cinc classes grupals de Reformer al teu ritme. "
                 "Un primer bloc sòlid per aprendre la màquina i veure fins on et porta.",
    },
    'Reformer Pack 10': {
        'en_US': "Ten Reformer group classes, our most popular choice. "
                 "Enough room to build real strength without watching the clock.",
        'es_ES': "Diez clases grupales de Reformer, nuestra opción más elegida. "
                 "Espacio suficiente para ganar fuerza de verdad sin mirar el reloj.",
        'ca_ES': "Deu classes grupals de Reformer, la nostra opció més escollida. "
                 "Espai suficient per guanyar força de debò sense mirar el rellotge.",
    },
    'Reformer Pack 15': {
        'en_US': "Fifteen Reformer group classes for training that becomes routine. "
                 "The best value we offer, and the fastest progress.",
        'es_ES': "Quince clases grupales de Reformer para que entrenar sea rutina. "
                 "La mejor relación calidad-precio y el progreso más rápido.",
        'ca_ES': "Quinze classes grupals de Reformer perquè entrenar sigui rutina. "
                 "La millor relació qualitat-preu i el progrés més ràpid.",
    },
    'Reformer Duo Pack 5': {
        'en_US': "Five Duo Reformer sessions, shared with someone you choose. "
                 "Private attention, split between you.",
        'es_ES': "Cinco sesiones de Reformer Dúo para compartir con otra persona. "
                 "Atención privada, coste repartido.",
        'ca_ES': "Cinc sessions de Reformer Dúo per compartir amb una altra persona. "
                 "Atenció privada, cost repartit.",
    },
    'Reformer Duo Pack 10': {
        'en_US': "Ten Duo Reformer sessions to train alongside someone else. "
                 "All the personal attention, at a shared price.",
        'es_ES': "Diez sesiones de Reformer Dúo para entrenar en compañía. "
                 "Toda la atención personalizada, a un precio compartido.",
        'ca_ES': "Deu sessions de Reformer Dúo per entrenar en companyia. "
                 "Tota l'atenció personalitzada, a un preu compartit.",
    },
}


def migrate(cr, version):
    if not version:
        # Fresh install: these products have no descriptions at all, and this
        # migration is a repair for databases that do. See the note above.
        return

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env['product.template'].sudo().with_context(active_test=False)

    written = skipped = 0
    for name, per_lang in DESCRIPTIONS.items():
        rec = Product.search([('name', '=', name)], limit=1)
        if not rec:
            _logger.warning(
                "fitness_packages: product %r not found - description not updated.", name)
            continue

        # Read what is actually stored per language, not through the ORM: a
        # translatable field falls back to the source language when a
        # translation is missing, which would make an untranslated record look
        # populated as soon as en_US is written.
        cr.execute("SELECT description_sale FROM product_template WHERE id = %s", (rec.id,))
        row = cr.fetchone()
        stored = (row[0] if row and isinstance(row[0], dict) else {}) or {}

        for lang, text in per_lang.items():
            current = (stored.get(lang) or '').strip()
            if current == text.strip():
                skipped += 1
                continue
            if current:
                _logger.info("fitness_packages: %r [%s] replacing %r", name, lang, current)
            rec.with_context(lang=lang).write({'description_sale': text})
            written += 1
            _logger.info("fitness_packages: %r [%s] set (%d chars)", name, lang, len(text))

    _logger.info("fitness_packages: %d description(s) written, %d already correct.",
                 written, skipped)
