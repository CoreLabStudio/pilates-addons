# -*- coding: utf-8 -*-
from odoo import models


class AccountMoveCashPaid(models.Model):
    """Cash taken at the desk counts as paid when her invoice is announced.

    The desk takes the money first and settles the invoice right after
    posting it, so at posting the ledger still says "not paid". A desk sale,
    a cash request the studio has approved, and a Renew (cash) are all money
    already in the till. Renew (cash) inside the window invoices the plan's
    own order, which may have been bought online, so it says so in context.
    """
    _inherit = 'account.move'

    def _fitness_invoice_is_paid(self):
        if super()._fitness_invoice_is_paid() or self.env.context.get('fitness_paid_in_cash'):
            return True
        orders = self.sudo().invoice_line_ids.sale_line_ids.order_id
        return any(o.fitness_payment_method == 'cash'
                   and (not o.fitness_cash_requested_on or o.fitness_cash_approved_on)
                   for o in orders)
