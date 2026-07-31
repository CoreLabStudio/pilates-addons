from odoo import models, fields


class SaleOrder(models.Model):
    """Records what the student chose in the portal checkout's Payment step.

    Purely a record of the student's declared intent — no payment is taken
    online. The studio reconciles the Bizum / bank transfer manually, exactly
    as it did before this step existed.
    """
    _inherit = 'sale.order'

    fitness_payment_method = fields.Selection([
        ('bizum', 'Bizum'),
        ('transfer', 'Bank Transfer'),
    ], string="Portal Payment Method", copy=False,
        help="Payment method the student selected during portal checkout.")

    fitness_terms_accepted_on = fields.Datetime(
        "Terms Accepted On", copy=False, readonly=True,
        help="When the student ticked 'I agree to the Terms and Conditions' "
             "during portal checkout.",
    )
