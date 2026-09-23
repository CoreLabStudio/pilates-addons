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
            # One notification per ORDER, not per line. A combined pack is
            # two lines - "2 Barre + 2 Reformer al mes" is one product sold as
            # a Barre pool and a Reformer pool - and both lines carry the same
            # product name, so the student was told the identical thing twice
            # for one purchase. The credits are summed instead, which is also
            # the number she actually has.
            lines = order.order_line.filtered(
                lambda l: l.product_id.fitness_is_package)
            if not lines:
                continue
            count = sum(int(l.fitness_remaining_classes or 0) for l in lines)
            # dict.fromkeys keeps the order the lines are in; a combined pack
            # collapses to one name, and a genuinely mixed order names each.
            names = [n for n in dict.fromkeys(
                l.product_id.name or '' for l in lines) if n]
            pkg_name = ', '.join(names) if names else 'your package'
            # order.env is whoever confirmed the sale - often a manager.
            # The person being told is the customer.
            tr = order.env(context=dict(order.env.context,
                                        lang=user.lang or 'es_ES'))._
            title = tr('%s confirmed', pkg_name)
            body = tr(
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
