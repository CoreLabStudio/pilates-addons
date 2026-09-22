from odoo import models, fields


class SaleOrder(models.Model):
    """Records what the student chose in the portal checkout's Payment step.

    Purely a record of the student's declared intent — no payment is taken
    online. The studio reconciles the Bizum / bank transfer manually, exactly
    as it did before this step existed.
    """
    _inherit = 'sale.order'

    fitness_payment_method = fields.Selection([
        ('stripe', 'Stripe (Online)'),
        ('bizum', 'Bizum'),
        ('transfer', 'Bank Transfer'),
        # Taken in person at the desk. Unlike Bizum and bank transfer there is
        # nothing left to chase: the money is in the till before the order is
        # written, so a cash order is not waiting on anybody.
        ('cash', 'Cash (at the studio)'),
        # Not a method so much as the absence of one: the order came to zero,
        # so nothing was charged and no provider was involved. Recorded rather
        # than left blank so a free order is tellable from one whose method was
        # never set, which is what the unpaid-confirmation guard keys on.
        ('free', 'Free (no payment)'),
    ], string="Portal Payment Method", copy=False,
        help="Payment method the student selected during portal checkout.")

    fitness_terms_accepted_on = fields.Datetime(
        "Terms Accepted On", copy=False, readonly=True,
        help="When the student ticked 'I agree to the Terms and Conditions' "
             "during portal checkout.",
    )


class SaleOrderLine(models.Model):
    """How a pack was paid for, readable from the pack itself.

    The payment method is recorded on the order, but the studio reads the
    balances list, which is lines - so answering "did she pay cash for this
    one" meant opening the order. Lives here rather than in fitness_packages
    because the field it mirrors is defined in this module.
    """
    _inherit = 'sale.order.line'

    fitness_payment_method = fields.Selection(
        related='order_id.fitness_payment_method', string='Paid By',
        readonly=True)
