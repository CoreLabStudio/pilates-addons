# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class AccountMoveFitnessPeriod(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        """A membership paid for a new period opens that period, however it was paid.

        Posting a membership invoice moves next_invoice_date past the paid
        period (Odoo's sale_subscription account.move._post). The studio's
        side of the new period - its start, the weekly counter, her weekly
        classes - was only done by _update_next_invoice_date, which the desk
        calls and Odoo's own online payment of a membership invoice (her
        subscription page, a payment link) does not. Eva Cuartero paid her
        second month that way on 14 Oct: her period still began on 17 Sep,
        the monthly limit counted her September classes against October,
        and her fourth October class was never placed.

        Placement here never raises: this runs inside a payment
        confirmation, and a full class must not undo a payment. What could
        not be placed is logged, and the nightly job places it later.
        """
        # sudo: Stripe's confirmation posts as the public user, who cannot
        # read orders; the period belongs to the order whoever paid.
        invoices = self.sudo().filtered(lambda m: m.move_type == 'out_invoice')
        subs = invoices.invoice_line_ids.subscription_id.filtered(
            'fitness_subscription_product_id')
        before = {sub.id: sub.next_invoice_date for sub in subs}
        res = super()._post(soft)
        for sub in subs:
            old = before.get(sub.id)
            if (old and sub.next_invoice_date and sub.next_invoice_date > old
                    and sub.subscription_state in ('3_progress', '4_paused')
                    and sub.fitness_period_start_date != old):
                sub._fitness_open_period(old)
                booked, errors = sub._fitness_place_slots()
                if errors:
                    _logger.warning("[SUBSCRIPTION] %s: period opened on payment, "
                                    "%d placed, not placed: %s", sub.name, booked, errors)
        return res
