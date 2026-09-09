# -*- coding: utf-8 -*-
"""Opening-promo prices on the five base plans.

data/products.xml is noupdate="1" - deliberately, because that is what stopped
a module update from silently reverting live prices - so the seed alone does
not touch an existing database. This applies the same five numbers here.

Reversibility: the original price of every plan it changes is written to the
log before the change, so the studio can be put back on the old prices without
having to reconstruct them from memory:

    75 / 140 / 80 / 150 / 210   ->   65 / 120 / 70 / 130 / 190

Idempotent. A plan whose price is neither the original nor the promo price has
been set by hand since, and is left alone and reported rather than overwritten.
"""
import logging

_logger = logging.getLogger(__name__)

LABEL = ' (Promo de apertura)'

# xmlid, original price, promo price
PLANS = [
    ('fitness_subscriptions.product_barre_clase_fija_1',  75.0,  65.0),
    ('fitness_subscriptions.product_barre_clase_fija_2', 140.0, 120.0),
    ('fitness_subscriptions.product_reformer_mensual_1',  80.0,  70.0),
    ('fitness_subscriptions.product_reformer_mensual_2', 150.0, 130.0),
    ('fitness_subscriptions.product_reformer_mensual_3', 210.0, 190.0),
]


def migrate(cr, version):
    if not version:
        return          # fresh install: the seed already carries these prices

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.info("[PROMO] Opening-promo repricing - original prices, for reversal:")
    changed = skipped = 0

    for xmlid, original, promo in PLANS:
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            _logger.warning("[PROMO] %s not found; skipped", xmlid)
            continue

        current = product.list_price or 0.0
        _logger.info("[PROMO]   %-34s was %7.2f  ->  %7.2f  (original %7.2f)",
                     xmlid.split('.')[-1], current, promo, original)

        if abs(current - promo) < 0.005:
            skipped += 1                      # already repriced
        elif abs(current - original) >= 0.005:
            # Someone has set this by hand since. Overwriting it would throw
            # away a deliberate decision, so report it and leave it.
            _logger.warning(
                "[PROMO]   %s is at %.2f, which is neither the original %.2f "
                "nor the promo %.2f - left as it is.",
                xmlid, current, original, promo)
            skipped += 1
            continue
        else:
            product.list_price = promo
            changed += 1

        # The name is stored English-only on these plans, so one value shows on
        # every language's page - which is why the label goes on directly
        # rather than through a translation.
        name = product.with_context(lang='en_US').name or ''
        if LABEL.strip() not in name:
            product.with_context(lang='en_US').name = name + LABEL

    _logger.info("[PROMO] Repricing done: %d changed, %d already correct or "
                 "manually set.", changed, skipped)
