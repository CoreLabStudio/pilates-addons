from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fitness_is_subscription_plan = fields.Boolean(
        "Is Fitness Subscription Plan",
        default=False,
        help="Enable for recurring fitness plans. Activates weekly-allowance "
             "tracking on the subscription (sale.order).",
    )
    fitness_subscription_plan_id = fields.Many2one(
        'sale.subscription.plan',
        string="Billing Plan",
        help="How often this plan bills. The portal reads it when it creates "
             "the order, so it decides what the student is actually signed up "
             "to. Leave it empty and the order falls back to Monthly.",
    )
    fitness_is_matricula = fields.Boolean(
        "Is Registration Fee",
        default=False,
        help="The one-off registration fee. It is added to a membership "
             "checkout automatically for a student's first membership, and "
             "never sold on its own, so it is kept out of the shop listing.",
    )
    fitness_is_clase_fija = fields.Boolean(
        "Is Clase Fija Plan",
        default=False,
        help="When enabled, confirming or renewing a subscription automatically "
             "creates bookings for every occurrence of the member's fixed class "
             "slot within the billing period (auto-placement).",
    )
    fitness_is_reformer_mensual = fields.Boolean(
        "Is Reformer Mensual Plan",
        default=False,
        help="When enabled, confirming a subscription within the studio-wide promo "
             "window (Sept–Nov) grants +1 floating credit automatically — identical "
             "mechanism to Barre Clase Fija opening promo.",
    )

    # ── ENFORCEMENT fields — read by validate_subscription_for_booking() and
    #    _select_payment_source(). These are the authoritative cap values. ────────

    weekly_class_allowance = fields.Integer(
        "Weekly Class Allowance",
        default=0,
        help="Maximum allowance-paid bookings a member may make in one ISO week "
             "(Mon 00:00 – Sun 23:59). Admin-editable; changes take effect "
             "immediately for all new bookings. Ignored for unlimited plans.",
    )
    fitness_secondary_weekly_allowance = fields.Integer(
        "Second Weekly Class Allowance",
        default=0,
        help="On a combined plan, the weekly cap for the second discipline "
             "(fitness_secondary_class_type). Enforced as its own cap: the "
             "two are never pooled, so allowance left on one discipline "
             "cannot be spent on the other.",
    )
    fitness_promo_first_cycle_bonus = fields.Integer(
        "Promo First-Cycle Bonus (Floating Credits)",
        default=0,
        help="Floating credits granted once when this subscription is first confirmed "
             "(first cycle only). Set to 1 for '+1 Promo' plans; 0 for all others. "
             "Not applied on renewal.",
    )
    is_unlimited = fields.Boolean(
        "Unlimited",
        default=False,
        help="When enabled, the weekly class allowance is not enforced — "
             "any number of classes may be booked against this plan, subject to "
             "normal capacity/overlap rules.",
    )

    # ── REPORTING ONLY — DO NOT read in validation or _select_payment_source ─────
    # This field previously stored the monthly cap (4 / 8 / 12). Enforcement has
    # moved to weekly_class_allowance above. This field is now a running total of
    # classes attended in the current billing cycle across all subscriptions on this
    # plan; it is incremented on every booking (allowance-paid and floating-credit)
    # and reset to 0 at cycle renewal. Its values on the product record are legacy
    # (4 / 8 / 12) and have no operational effect.
    monthly_class_allowance = fields.Integer(
        "Monthly Class Allowance (legacy / reporting only)",
        default=0,
        help="REPORTING ONLY. Previously the monthly cap; now a running total of "
             "classes attended this billing cycle. Not used to enforce any booking "
             "limit. See Weekly Class Allowance for the active cap.",
    )

    # Discipline restriction reuses the same two-field model as fitness_packages
    # (fitness_class_type + fitness_session_type, defined on product.template
    # by the fitness_packages module) — no new discipline field is introduced.

    # ── Purchase shape: months, matrícula, and the lines that follow ────────
    #
    # These were controller methods on fitness_portal, reachable only from a
    # web request. The desk wizard could not call them, so it sold a pack by
    # calling fitness_sale_line_vals() directly - which meant it applied no
    # months multiplier and never charged the matrícula. Harmless while the
    # desk sold only packs; wrong the moment it sells a membership, because a
    # Trimestral sold there would charge one month of a three-month
    # commitment. That is the shape of the 585.00-billed-as-195.00 fault
    # already recorded in the checkout code.
    #
    # Moved here so checkout and the desk build a purchase from the same
    # rules. _order_lines_for's own docstring already said one place builds
    # them; this is that place.

    MATRICULA_WAIVED_FROM_MONTHS = 3

    @staticmethod
    def fitness_plan_months(plan):
        """How many months one billing period covers.

        Weeks and days are rounded down deliberately: they are not commitment
        periods the studio sells, and a plan that does not reach a month must
        not accidentally clear the three-month waiver.
        """
        if not plan:
            return 1
        # sudo to read: sale.subscription.plan is a Sales model, and a fitness
        # manager is not a Sales user. Reading how long a period lasts is not
        # a permission the studio needs to hold - it is a property of what she
        # is already authorised to sell. Left unsudoed this raised AccessError
        # the moment a manager picked a membership at the desk.
        plan = plan.sudo()
        value = plan.billing_period_value or 1
        unit = plan.billing_period_unit
        if unit == 'year':
            return value * 12
        if unit == 'month':
            return value
        if unit == 'week':
            return (value * 7) // 30
        if unit == 'day':
            return value // 30
        return 1

    def fitness_matricula_due(self, partner, plan=None):
        """The registration fee product when it should be charged, else empty.

        Two conditions, both the studio's: it is a student's first membership,
        and the commitment is shorter than three months. Committing to three
        months or more waives it.
        """
        empty = self.env['product.template'].browse()
        self.ensure_one()
        if not self.fitness_is_subscription_plan:
            return empty
        matricula = self.env.ref('fitness_subscriptions.product_matricula',
                                 raise_if_not_found=False)
        if not matricula or not matricula.sudo().active:
            return empty
        if self.fitness_plan_months(plan) >= self.MATRICULA_WAIVED_FROM_MONTHS:
            return empty
        if self.fitness_has_paid_membership_before(partner):
            return empty
        return matricula.sudo()

    @staticmethod
    def fitness_has_paid_membership_before(partner):
        """Has this student ever held a membership?

        Read from what actually happened rather than a flag somebody has to
        remember to set: any confirmed order carrying a subscription plan
        counts, whether it was made in the portal, the back office or an
        import. Drafts do not - the checkout reuses them, so an abandoned
        attempt must not make a first membership look like a second and skip
        the fee. The order being built right now is still draft when this is
        asked, which is what stops it excluding itself.
        """
        if not partner:
            return False
        return bool(partner.env['sale.order.line'].sudo().search([
            ('order_id.partner_id', '=', partner.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('product_id.product_tmpl_id.fitness_is_subscription_plan', '=', True),
        ], limit=1))

    def fitness_order_line_vals(self, partner, plan=None, period_price=None,
                                total_price=None):
        """The lines this purchase should carry, priced.

        `period_price` is the price of ONE billing period - the student price,
        which the trial rule can change - and the months multiplier is applied
        to it here, because a quarterly membership is three months charged at
        once.

        `total_price` replaces that calculation outright and is what the desk
        passes: a manager types the cash actually taken for the whole sale,
        not a price per month.
        """
        self.ensure_one()
        variant = self.product_variant_ids[:1]
        if not variant:
            return []
        if total_price is None:
            base = (period_price if period_price is not None
                    else self.fitness_effective_price())
            total_price = base * self.fitness_plan_months(plan)
        lines = self.fitness_sale_line_vals(total_price)
        matricula = self.fitness_matricula_due(partner, plan)
        if matricula:
            mat_variant = matricula.product_variant_ids[:1]
            if mat_variant:
                mat_base, _total = matricula.fitness_taxed_price(
                    matricula.fitness_effective_price(), partner,
                    price_includes_tax=True)
                lines.append({
                    'product_id': mat_variant.id,
                    'product_uom_qty': 1,
                    'price_unit': mat_base,
                })
        return lines
