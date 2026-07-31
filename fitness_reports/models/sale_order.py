from odoo import models, fields, api


class SaleOrderRevenueType(models.Model):
    _inherit = 'sale.order'

    revenue_type = fields.Selection([
        ('membership', 'Membership'),
        ('pack', 'Pack'),
        ('single', 'Single'),
    ], string='Revenue Type', compute='_compute_revenue_type', store=True)

    @api.depends('is_subscription', 'fitness_is_package')
    def _compute_revenue_type(self):
        for order in self:
            if order.is_subscription:
                order.revenue_type = 'membership'
            elif order.fitness_is_package:
                order.revenue_type = 'pack'
            else:
                order.revenue_type = 'single'
