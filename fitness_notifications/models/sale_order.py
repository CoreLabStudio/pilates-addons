from odoo import models


class SaleOrderNotifications(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            if not order.fitness_is_package:
                continue
            partner = order.partner_id
            user = partner.user_ids[:1]
            if not user:
                continue
            for line in order.order_line:
                if not line.product_id.fitness_is_package:
                    continue
                count = int(line.fitness_remaining_classes or 0)
                pkg_name = line.product_id.name or 'your package'
                title = order.env._('%s confirmed', pkg_name)
                body = order.env._(
                    'You have %d class credit(s) ready to book.', count
                ) if count else None
                self.env['fitness.notification'].sudo()._create_for_user(
                    user.id,
                    'purchase_completed',
                    title,
                    body=body,
                    action_url='/my/packages',
                )
        return result
