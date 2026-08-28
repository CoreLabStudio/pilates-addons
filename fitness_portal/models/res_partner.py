from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    consent_terms_date = fields.Datetime(string='Terms Accepted On', readonly=True)
    consent_marketing = fields.Boolean(string='Marketing Email Consent', default=False)
    consent_marketing_date = fields.Datetime(string='Marketing Consent On', readonly=True)

    # ── Credits ──────────────────────────────────────────────────────────────
    #
    # There is no credit ledger table. A balance is derived, every time it is
    # asked for, from two places:
    #
    #   * sale.order.line.fitness_remaining_classes - a counter on the package
    #     line, decremented on booking and incremented back when a booking is
    #     cancelled more than 2h out
    #   * sale.order.fitness_floating_credits       - promo credits attached to
    #     a running subscription
    #
    # The portal used to do that arithmetic inside the controller, so the admin
    # backend had no way to show the same number without re-deriving it, and it
    # would drift the moment either rule changed. The computation lives here now
    # and the controller calls into it, so both sides read one source.

    fitness_credit_available = fields.Integer(
        "Credits Available",
        compute='_compute_fitness_credits',
        help="Credits the student can book with right now: unexpired package "
             "credits plus subscription floating credits. This is the same "
             "number the student sees on their own portal home page.",
    )
    fitness_credit_purchased = fields.Integer(
        "Credits Purchased", compute='_compute_fitness_credits',
        help="Total credits bought on packages that are still valid.",
    )
    fitness_credit_used = fields.Integer(
        "Credits Used", compute='_compute_fitness_credits',
        help="Purchased minus remaining, on packages that are still valid.",
    )

    def _fitness_active_package_lines(self, single_class=None):
        """Credit-bearing package lines that have not passed their validity date.

        single_class=None  -> every credit-bearing line (what the balance sums)
        single_class=False -> multi-class packs, the shop's Packages tab
        single_class=True  -> trial/single/private, the shop's Classes tab

        The split mirrors the domain in packages_list() exactly
        (fitness_class_count > 1 vs <= 1), so the home page prompts and the shop
        tabs can never disagree about which category a product belongs to.

        Expiry is filtered in Python rather than in the domain because a null
        validity date means "never expires" and has to pass.
        """
        self.ensure_one()
        domain = [
            ('order_partner_id', '=', self.id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ]
        if single_class is True:
            domain += [('product_id.fitness_class_count', '<=', 1)]
        elif single_class is False:
            domain += [('product_id.fitness_class_count', '>', 1)]

        today = fields.Date.context_today(self)
        lines = self.env['sale.order.line'].sudo().search(domain)
        return lines.filtered(
            lambda l: not l.fitness_validity_end_date or l.fitness_validity_end_date >= today
        )

    def _fitness_active_subscription(self):
        """The student's running membership, or an empty recordset."""
        self.ensure_one()
        return self.env['sale.order'].sudo().search([
            ('partner_id', '=', self.id),
            ('is_subscription', '=', True),
            ('subscription_state', '=', '3_progress'),
            ('fitness_subscription_product_id', '!=', False),
        ], order='id desc', limit=1)

    def _fitness_credit_total(self):
        """Credits bookable right now: unexpired pack credits + floating credits."""
        self.ensure_one()
        total = sum(self._fitness_active_package_lines().mapped('fitness_remaining_classes'))
        subs = self.env['sale.order'].sudo().search([
            ('partner_id', '=', self.id),
            ('subscription_state', '=', '3_progress'),
        ])
        return total + sum(subs.mapped('fitness_floating_credits'))

    @api.depends('name')
    def _compute_fitness_credits(self):
        # Derived from live sale data, so no depends can express the real
        # trigger. The field is not stored, so every read recomputes.
        for partner in self:
            lines = partner._fitness_active_package_lines()
            partner.fitness_credit_available = partner._fitness_credit_total()
            partner.fitness_credit_purchased = sum(lines.mapped('fitness_original_class_count'))
            partner.fitness_credit_used = sum(lines.mapped('fitness_classes_used'))

    def _fitness_credit_pools(self):
        """Every active credit pool, most time-sensitive first.

        1. the subscription's weekly slots, which reset and so expire soonest
        2. credit packs, soonest-expiring first

        Drives the portal home Credits card.
        """
        self.ensure_one()
        pools = []

        active_sub = self._fitness_active_subscription()
        if active_sub:
            weekly_cap = active_sub.fitness_weekly_class_allowance or 0
            used_this_week = active_sub.fitness_weekly_used_this_week or 0
            remaining_week = max(0, weekly_cap - used_this_week)
            ct = active_sub.fitness_class_type or 'reformer'
            type_label = {'barre': 'barre', 'reformer': 'reformer'}.get(ct, 'class')
            pools.append({
                'remaining': remaining_week,
                'total': weekly_cap,
                'display': ('%s / %s' % (remaining_week, weekly_cap)) if weekly_cap else str(remaining_week),
                'label': _('%s slots this week') % type_label,
                'credits_available_text': _('%d %s slot(s) left this week') % (remaining_week, type_label),
            })

        lines = self._fitness_active_package_lines().sorted(
            key=lambda l: (l.fitness_validity_end_date is False, l.fitness_validity_end_date)
        )
        for line in lines:
            ct = getattr(line.product_id, 'fitness_class_type', 'any') or 'any'
            label = {
                'barre': _('barre credits'),
                'reformer': _('reformer credits'),
            }.get(ct, _('class credits'))
            remaining = line.fitness_remaining_classes
            total = line.fitness_original_class_count
            pools.append({
                'remaining': remaining,
                'total': total,
                'display': ('%s / %s' % (remaining, int(total))) if total else str(remaining),
                'label': label,
                'credits_available_text': _('%d %s available') % (remaining, label),
            })

        return pools

    # ── What the student does not own yet ────────────────────────────────────
    #
    # Each category is independent: someone on a membership with no credits left
    # still gets prompted to buy a pack. This answers "does this person own
    # anything in this category", which is a different question from "have they
    # booked a class" - that one belongs to the Next up block.

    def _fitness_missing_purchases(self):
        """Which of the three shop categories this student has nothing active in."""
        self.ensure_one()
        return {
            'membership': not self._fitness_active_subscription(),
            'package': not self._fitness_active_package_lines(single_class=False),
            'class': not self._fitness_active_package_lines(single_class=True),
        }
