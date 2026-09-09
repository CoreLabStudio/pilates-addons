# -*- coding: utf-8 -*-
"""Name the billing plan on existing subscription products.

Until now the portal picked the plan with search([], limit=1) - not a choice
but an accident of ordering. It always returned Monthly, which meant Yearly
could not be bought from the portal at all and every membership was signed up
monthly whatever it had been sold as. The product now says which plan it bills
on, and this writes down what these products have in fact been doing.

Monthly for all of them: that is what they were already getting, so this
records the status quo rather than changing anybody's billing. The new
Quarterly plan exists to be chosen deliberately, and is deliberately assigned
to nothing here - which membership is sold as a quarter is the studio's
pricing decision, not a migration's.

data/products.xml is noupdate="1", so the seed does not reach an existing
database; this does. Idempotent - a product that already names a plan is left
alone, including one an admin has set to something other than Monthly.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return          # fresh install: the seed already names the plan

    from odoo import api, SUPERUSER_ID
    env = api.Environment(cr, SUPERUSER_ID, {})

    monthly = env.ref('sale_subscription.subscription_plan_month',
                      raise_if_not_found=False)
    if not monthly:
        _logger.warning(
            "[PLANS] Monthly plan not found; billing plans left unset. The "
            "portal still falls back to Monthly at order time.")
        return

    products = env['product.template'].with_context(active_test=False).search([
        ('fitness_is_subscription_plan', '=', True),
        ('fitness_subscription_plan_id', '=', False),
    ])
    for product in products:
        _logger.info("[PLANS] %s -> %s", product.display_name, monthly.name)
    products.write({'fitness_subscription_plan_id': monthly.id})

    quarter = env.ref('fitness_subscriptions.subscription_plan_quarter',
                      raise_if_not_found=False)
    _logger.info(
        "[PLANS] %d product(s) now name Monthly explicitly. Quarterly plan "
        "%s and assigned to nothing yet, by design.",
        len(products),
        'created' if quarter else 'MISSING')
