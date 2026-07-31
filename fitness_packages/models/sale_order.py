from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    fitness_is_package = fields.Boolean(
        "Contains Fitness Package",
        compute='_compute_fitness_is_package',
        store=True,
        help="Set automatically when any line contains a fitness class-pack product.",
    )

    @api.depends('order_line.product_id.fitness_is_package')
    def _compute_fitness_is_package(self):
        for order in self:
            order.fitness_is_package = any(
                line.product_id.fitness_is_package
                for line in order.order_line
                if line.product_id
            )

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            today = fields.Date.today()
            for line in order.order_line:
                if not line.product_id.fitness_is_package:
                    continue
                validity_days = line.product_id.fitness_validity_days or 15
                class_count = int(
                    line.product_id.fitness_class_count * line.product_uom_qty
                )
                line.write({
                    'fitness_original_class_count': class_count,
                    'fitness_remaining_classes': class_count,
                    'fitness_validity_end_date': fields.Date.add(today, days=validity_days),
                })
        return result
