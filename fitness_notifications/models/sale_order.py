from odoo import models


class SaleOrderNotifications(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        result = super().action_confirm()
        for order in self:
            partner = order.partner_id
            user = partner.user_ids[:1]
            if not user:
                continue
            # A membership used to fall out here, because the guard was
            # fitness_is_package and a subscription is not one. So the shop
            # promised "we will tell you as soon as it goes through" on the
            # payment return, and for a membership nothing ever came. Packs,
            # trials and memberships now all produce exactly one notification
            # per order - still one, because a combined order is several
            # lines describing a single purchase.
            sub_lines = order.order_line.filtered(
                lambda l: l.product_id.fitness_is_subscription_plan)
            if not order.fitness_is_package and not sub_lines:
                continue
            # One notification per ORDER, not per line. A combined pack is
            # two lines - "2 Barre + 2 Reformer al mes" is one product sold as
            # a Barre pool and a Reformer pool - and both lines carry the same
            # product name, so the student was told the identical thing twice
            # for one purchase. The credits are summed instead, which is also
            # the number she actually has.
            lines = order.order_line.filtered(
                lambda l: l.product_id.fitness_is_package)
            if not lines and not sub_lines:
                continue
            # A membership has no credit counter - the allowance is weekly
            # and lives on the subscription - so the body says what is true
            # for it instead of a count of nothing.
            if not lines:
                names = [n for n in dict.fromkeys(
                    l.product_id.name or '' for l in sub_lines) if n]
                plan_name = ', '.join(names) if names else 'your membership'
                tr = order.env(context=dict(order.env.context,
                                            lang=user.lang or 'es_ES'))._
                self.env['fitness.notification'].sudo()._create_for_user(
                    user.id,
                    'purchase_completed',
                    tr('%s is active', plan_name),
                    body=tr('You can book your classes now.'),
                    action_url='/my/subscription',
                )
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
