from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_is_zero, float_round
from odoo.tools.misc import format_date


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    fitness_is_package = fields.Boolean(
        "Is Fitness Package",
        default=False,
        help="Enable for class-pack products. Activates credit tracking on sale order lines.",
    )
    fitness_class_count = fields.Integer(
        "Classes in Pack",
        default=1,
        help="Number of class credits granted when this product is sold.",
    )
    fitness_validity_days = fields.Integer(
        "Validity (days)",
        default=15,
        help="Credits expire this many days after the sale order is confirmed.",
    )
    fitness_class_type = fields.Selection([
        ('barre',    'Barre'),
        ('reformer', 'Reformer Pilates'),
        ('any',      'Any'),
    ], string="Class Type", default='any',
        help="Restricts which studio type the credits can be used for.",
    )
    fitness_session_type = fields.Selection([
        ('group',   'Group'),
        ('private', 'Private (1-on-1)'),
        ('duo',     'Duo (2 people)'),
    ], string="Session Type", default='group',
        help="Restricts which session type the credits can be used for.",
    )

    # ── Promotional pricing ──────────────────────────────────────────────
    #
    # The studio ran its free trial by typing 0 into the sales price and typing
    # the real number back afterwards. Two things went wrong with that: the
    # checkout could not complete a genuine zero, and nothing put the price
    # back when the offer ended. This models the offer instead of overwriting
    # the price - the sales price is never touched, and the offer expires on
    # its own date with nothing to reset by hand.
    fitness_promo_mode = fields.Selection([
        ('none', 'Full price'),
        ('free', 'Free'),
        ('percent', 'Percentage off'),
    ], string="Promotion", default='none', required=True,
        help="How this product is priced while the promotion window is open. "
             "Outside that window it always sells at the full sales price.")
    fitness_promo_percent = fields.Float(
        "Discount (%)", default=0.0,
        help="Percentage taken off the sales price, e.g. 10 for 10% off.")
    fitness_promo_start = fields.Date(
        "Promotion Starts",
        help="First day the promotion applies. Leave empty to start immediately.")
    fitness_promo_end = fields.Date(
        "Promotion Ends",
        help="Last day the promotion applies, inclusive. Leave empty for no end "
             "date. After this day the product returns to its full price.")

    fitness_promo_is_live = fields.Boolean(
        "Promotion Running", compute='_compute_fitness_price',
        help="Whether the promotion applies today.")
    fitness_price_now = fields.Float(
        "Price Today", compute='_compute_fitness_price', digits='Product Price',
        help="What a student is charged today, after any running promotion.")
    fitness_promo_saving = fields.Float(
        "Saving", compute='_compute_fitness_price', digits='Product Price')
    fitness_promo_summary = fields.Char(
        "Promotion Summary", compute='_compute_fitness_price')

    # ── the single source of truth ───────────────────────────────────────
    def _fitness_promo_window_open(self, on=None):
        """Is the promotion window open on this date?

        Both ends are optional and inclusive: no start means it is already
        running, no end means it never expires. The date is taken in the
        reader's own timezone, so an offer ending "today" is still on for a
        student in Madrid at 23:00 rather than having stopped at UTC midnight.
        """
        self.ensure_one()
        if self.fitness_promo_mode == 'none':
            return False
        on = on or fields.Date.context_today(self)
        if self.fitness_promo_start and on < self.fitness_promo_start:
            return False
        if self.fitness_promo_end and on > self.fitness_promo_end:
            return False
        return True

    def fitness_effective_price(self, on=None):
        """The price a student actually pays, today.

        Everything that shows a price or charges one goes through here: the
        packages list, the product page, the checkout, and the order line that
        Stripe is eventually handed. A second calculation anywhere else is how
        a student ends up shown one number and charged another.
        """
        self.ensure_one()
        full = self.list_price or 0.0
        if not self._fitness_promo_window_open(on):
            return full
        if self.fitness_promo_mode == 'free':
            return 0.0
        if self.fitness_promo_mode == 'percent':
            pct = min(max(self.fitness_promo_percent or 0.0, 0.0), 100.0)
            rounding = self.currency_id.rounding or 0.01
            return float_round(full * (1.0 - pct / 100.0), precision_rounding=rounding)
        return full

    def fitness_price_is_free(self, on=None):
        """Does this resolve to nothing to pay?

        A 100% discount is free in every way that matters to a student, so it
        takes the same one-tap path as the Free mode rather than sending them
        to a payment page for 0.00.
        """
        self.ensure_one()
        rounding = self.currency_id.rounding or 0.01
        return float_is_zero(self.fitness_effective_price(on),
                             precision_rounding=rounding)

    @api.depends('list_price', 'fitness_promo_mode', 'fitness_promo_percent',
                 'fitness_promo_start', 'fitness_promo_end', 'currency_id')
    def _compute_fitness_price(self):
        for product in self:
            live = product._fitness_promo_window_open()
            price = product.fitness_effective_price()
            product.fitness_promo_is_live = live
            product.fitness_price_now = price
            product.fitness_promo_saving = (product.list_price or 0.0) - price
            # Whole phrases, not a fragment glued onto another string.
            # This used to build the badge as _("%s%% off") + _(" until %s"),
            # and a translatable string that begins with a space and has to
            # follow two different openings is one no translator can place -
            # word order is not the same in every language, and it left
            # "off until" in English on a Spanish page.
            #
            # The date goes through format_date so a Spanish reader gets
            # 24/09/2026 rather than the ISO form.
            if not live:
                product.fitness_promo_summary = _("Full price")
            elif product.fitness_promo_mode == 'free':
                if product.fitness_promo_end:
                    product.fitness_promo_summary = _("Free until %(date)s") % {
                        'date': format_date(product.env, product.fitness_promo_end)}
                else:
                    product.fitness_promo_summary = _("Free")
            else:
                pct = '%g' % (product.fitness_promo_percent or 0.0)
                if product.fitness_promo_end:
                    product.fitness_promo_summary = _("%(pct)s%% off until %(date)s") % {
                        'pct': pct,
                        'date': format_date(product.env, product.fitness_promo_end)}
                else:
                    product.fitness_promo_summary = _("%(pct)s%% off") % {'pct': pct}

    # ── keep the admin from saving something incoherent ──────────────────
    @api.constrains('fitness_promo_mode', 'fitness_promo_percent',
                    'fitness_promo_start', 'fitness_promo_end')
    def _check_fitness_promo(self):
        for product in self:
            if product.fitness_promo_mode == 'percent':
                pct = product.fitness_promo_percent or 0.0
                if float_compare(pct, 0.0, precision_digits=2) <= 0 or \
                        float_compare(pct, 100.0, precision_digits=2) > 0:
                    raise ValidationError(_(
                        "The discount on %s must be greater than 0 and at most "
                        "100 percent.") % product.display_name)
            if (product.fitness_promo_start and product.fitness_promo_end
                    and product.fitness_promo_end < product.fitness_promo_start):
                raise ValidationError(_(
                    "The promotion on %s ends before it starts.")
                    % product.display_name)

    @api.onchange('fitness_promo_mode')
    def _onchange_fitness_promo_mode(self):
        """Start today by default, so a mode just switched on is running.

        Saving a mode with both dates empty is a promotion with no end, which
        is a reasonable thing to want but a poor thing to get by accident.
        """
        for product in self:
            if product.fitness_promo_mode != 'none' and not product.fitness_promo_start:
                product.fitness_promo_start = fields.Date.context_today(product)
            if product.fitness_promo_mode == 'none':
                product.fitness_promo_percent = 0.0
