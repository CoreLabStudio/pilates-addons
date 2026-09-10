# -*- coding: utf-8 -*-
"""Bring the shop in line with the studio's final price sheet.

Two things the sheet settles, both of which change records that already
exist - so they belong here rather than in a data file, which would leave
them untouched on any database that already has them.

  The full-price weekly tiers are deliberately untouched. They exist ready
  for the day the opening promo ends, when they take over from the promo
  versions - that is a swap for another day, not part of this.

  * The products the sheet does not offer are archived, not deleted. People
    have bought some of them, and their credits and history have to keep
    resolving to a product that still exists.

  * Validity periods match the sheet. This only reaches future purchases:
    fitness_validity_end_date is written once when an order is confirmed, so
    a student holding credits keeps the window they were sold.

Each change is checked before it is made, so re-running this is quiet.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Not on the sheet. Archived so existing credits and orders still resolve.
ARCHIVE = (
    'fitness_packages.product_barre_single',
    'fitness_packages.product_reformer_single',
    'fitness_packages.product_duo_5pack',
    'fitness_packages.product_duo_10pack',
    'fitness_packages.product_private_10pack',
)

# xmlid -> validity in days, from the sheet's own wording
VALIDITY = {
    'fitness_packages.product_barre_5pack': 42,       # 6 semanas
    'fitness_packages.product_barre_10pack': 90,      # 3 meses
    'fitness_packages.product_reformer_5pack': 42,    # 6 semanas
    'fitness_packages.product_reformer_15pack': 120,  # 4 meses
    'fitness_packages.product_private_5pack': 90,     # 3 meses
    'fitness_packages.product_reformer_intro3': 14,   # 14 dias
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    archived = already_off = 0
    for xmlid in ARCHIVE:
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            continue
        product = product.sudo()
        if not product.active:
            already_off += 1
            continue
        product.write({'active': False})
        archived += 1

    changed = unchanged = 0
    for xmlid, days in VALIDITY.items():
        product = env.ref(xmlid, raise_if_not_found=False)
        if not product:
            continue
        product = product.sudo()
        if product.fitness_validity_days == days:
            unchanged += 1
            continue
        product.write({'fitness_validity_days': days})
        changed += 1

    _logger.info(
        "fitness_subscriptions: price sheet - archived %d (%d already off), "
        "validity changed on %d (%d already correct). Existing credits keep "
        "the window they were sold.",
        archived, already_off, changed, unchanged)
