from odoo import models


class SaleOrderNotifications(models.Model):
    _inherit = 'sale.order'

    def _fitness_reader_lang(self, user):
        """The language to tell this person in.

        Hers, then the company's, then English - each only if it is
        installed, because a code that is set but not installed makes the
        ORM fall back to English silently and the product name with it.
        This used to be `user.lang or 'es_ES'` for the sentence, while the
        product name was read in the language of whoever confirmed the
        sale - so a Spanish reader got "Reformer Private Pack 5 confirmada".

        English always counts as installed. It is the language the source
        is written in, so it always renders - and a database installed
        with --load-language leaves en_US with active NULL, which a search
        for active languages does not return. Without this, an English
        reader there was told in the company's language instead.
        """
        installed = set(self.env['res.lang'].sudo().search([]).mapped('code'))
        installed.add('en_US')
        for code in (user.lang, self.company_id.partner_id.lang, 'en_US'):
            if code and code in installed:
                return code
        return 'en_US'

    def action_confirm(self):
        result = super().action_confirm()
        # The fifth path, and the one that ignored the flag. Booking,
        # cancelling, moving and class changes all stay silent under
        # skip_fitness_notification; confirming an order rang and pushed
        # anyway, so nothing that creates a credit on the student's behalf
        # - a walk-in recorded after the fact, a desk correction - could
        # ever be done quietly.
        if self.env.context.get('skip_fitness_notification'):
            return result
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
            # The reader's language, for the sentence AND the product name.
            lang = order._fitness_reader_lang(user)
            if not lines:
                names = [n for n in dict.fromkeys(
                    l.product_id.with_context(lang=lang).name or ''
                    for l in sub_lines) if n]
                plan_name = ', '.join(names) if names else 'your membership'
                tr = order.env(context=dict(order.env.context, lang=lang))._
                # A fixed-class membership books nothing until her weekly
                # hours are chosen. Paid by card, or approved at the desk
                # while she is not even on the page, nothing ever sent her
                # to choose them; this bell is the one message every path
                # sends, so it takes her there.
                if order.fitness_missing_fixed_slots():
                    body = tr('Choose the day and time of your weekly class '
                              'and we will book it for you every week.')
                    url = '/my/fixed-class'
                else:
                    body = tr('You can book your classes now.')
                    url = '/my/subscription'
                self.env['fitness.notification'].sudo()._create_for_user(
                    user.id,
                    'purchase_completed',
                    tr('%s is active', plan_name),
                    body=body,
                    action_url=url,
                )
                continue
            count = sum(int(l.fitness_remaining_classes or 0) for l in lines)
            # dict.fromkeys keeps the order the lines are in; a combined pack
            # collapses to one name, and a genuinely mixed order names each.
            names = [n for n in dict.fromkeys(
                l.product_id.with_context(lang=lang).name or ''
                for l in lines) if n]
            pkg_name = ', '.join(names) if names else 'your package'
            # order.env is whoever confirmed the sale - often a manager.
            # The person being told is the customer.
            tr = order.env(context=dict(order.env.context, lang=lang))._
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
