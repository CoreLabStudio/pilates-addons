import datetime

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

import logging
_logger = logging.getLogger(__name__)

# Active per sale_subscription's own state machine (odoo/addons/sale_subscription/models/sale_order.py).
# '4_paused' is deliberately excluded: a paused subscription must not be bookable.
ACTIVE_SUBSCRIPTION_STATE = '3_progress'

# ISO weekday number that starts each cap window (1=Monday … 7=Sunday).
# THIS IS THE SINGLE PLACE to change the week boundary — never inline this value.
# Changing to 7 (Sunday) would make Sun–Sat weeks; adding Saturday classes later
# requires no logic change as long as this constant is honoured throughout.
WEEK_START_ISODAY = 1  # Monday

# Promo window: plans with fitness_promo_first_cycle_bonus > 0 may only be
# confirmed during this inclusive date range. Locked decision D — no manual toggle.
PROMO_WINDOW_START = datetime.date(2026, 9, 1)
PROMO_WINDOW_END   = datetime.date(2026, 11, 30)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ─── Per-subscription counters and overrides ──────────────────────────────
    # Stored on sale.order because fitness.booking.subscription_id points here.

    # ── REPORTING ONLY — DO NOT use in validation or _select_payment_source ──
    # Running count of classes attended in the current billing cycle (all bookings:
    # allowance-paid and floating-credit). Incremented on every booking creation,
    # NEVER decremented (not even on cancellation), reset to 0 at cycle renewal.
    # Previously used as an enforcement counter; enforcement now uses the weekly
    # ISO-week count via fitness_weekly_used_count() and weekly_class_allowance.
    fitness_subscription_used_classes = fields.Integer(
        "Classes This Period (reporting)",
        default=0,
        help="REPORTING ONLY. Running total of classes attended in the current "
             "billing cycle (allowance + floating). Never decremented. "
             "Not used to enforce any cap.",
    )
    fitness_period_start_date = fields.Date(
        "Current Period Start",
        help="Start of the current billing period, aligned to the subscription's "
             "own next_invoice_date / start_date (no parallel calendar).",
    )

    # ── FLOATING CREDITS — per-subscription, accumulating pool ───────────────
    # Each credit permits one booking exempt from the weekly cap. Fed by:
    #   (a) promo first-cycle bonus (product.fitness_promo_first_cycle_bonus)
    #   (b) in-time (>2h) cancellation of an allowance-paid booking
    # Carry forward across renewals; decremented when a floating-credit booking is made.
    fitness_floating_credits = fields.Integer(
        "Floating Credits",
        default=0,
        help="Cap-exempt booking credits accumulated across all billing cycles. "
             "Seeded from promo bonus on first confirmation; earned via >2h "
             "cancellation of allowance bookings. Carry forward at renewal — "
             "only decremented when actually consumed by a booking.",
    )

    # ── PER-MEMBER OVERRIDE — 0 means 'use plan default' ─────────────────────
    fitness_weekly_allowance_override = fields.Integer(
        "Weekly Allowance Override",
        default=0,
        help="When >0, overrides the plan's Weekly Class Allowance for this member "
             "only. 0 means use the plan default.",
    )

    # ─── Convenience fields, derived from the fitness subscription product line ─

    fitness_subscription_product_id = fields.Many2one(
        'product.product',
        compute='_compute_fitness_subscription_product_id',
        store=True,
        help="The fitness subscription plan product on this order, if any.",
    )
    fitness_class_type = fields.Selection(
        related='fitness_subscription_product_id.fitness_class_type', store=False, string="Class Type",
    )
    fitness_session_type = fields.Selection(
        related='fitness_subscription_product_id.fitness_session_type', store=False, string="Session Type",
    )
    # Reporting-only legacy: mirrors the product's monthly_class_allowance (legacy values 4/8/12).
    fitness_monthly_class_allowance = fields.Integer(
        related='fitness_subscription_product_id.monthly_class_allowance', store=False, string="Monthly Allowance (legacy)",
    )
    # Enforcement: weekly cap N — used by validate_subscription_for_booking() and selector.
    fitness_weekly_class_allowance = fields.Integer(
        related='fitness_subscription_product_id.weekly_class_allowance', store=False, string="Weekly Allowance",
    )
    fitness_is_unlimited = fields.Boolean(
        related='fitness_subscription_product_id.is_unlimited', store=False, string="Unlimited",
    )
    fitness_is_clase_fija = fields.Boolean(
        related='fitness_subscription_product_id.fitness_is_clase_fija',
        store=False, string="Is Clase Fija",
    )

    # ── CLASE FIJA: fixed weekly class slots (one per reserved class time) ──────
    # Each active slot holds an anchor event. Auto-placement creates bookings for
    # every occurrence of each slot's class within the billing period.
    # Active slot count must not exceed effective_weekly_allowance (enforced by
    # FitnessClaseFija._check_slot_count_vs_allowance — the B1 guard).
    fitness_clase_fija_ids = fields.One2many(
        'fitness.clase.fija', 'subscription_id',
        "Fixed Class Slots",
    )

    # ── DISPLAY: live weekly-state readouts shown on the subscription form ─────
    # Non-stored; recomputed on every read. fitness_subscription_used_classes is
    # used as a proxy dependency so the web client refreshes after each booking.
    fitness_effective_weekly_allowance_display = fields.Integer(
        "Effective Weekly Cap",
        compute='_compute_fitness_weekly_display',
        compute_sudo=True,
        store=False,
    )
    fitness_weekly_used_this_week = fields.Integer(
        "Used This Week",
        compute='_compute_fitness_weekly_display',
        compute_sudo=True,
        store=False,
    )

    @api.depends('order_line.product_id.fitness_is_subscription_plan')
    def _compute_fitness_subscription_product_id(self):
        for order in self:
            line = order.order_line.filtered(lambda l: l.product_id.fitness_is_subscription_plan)[:1]
            order.fitness_subscription_product_id = line.product_id

    @api.depends(
        'fitness_weekly_allowance_override',
        'fitness_subscription_product_id.weekly_class_allowance',
        'fitness_subscription_used_classes',
    )
    def _compute_fitness_weekly_display(self):
        today = datetime.date.today()
        for order in self:
            order.fitness_effective_weekly_allowance_display = (
                order.fitness_effective_weekly_allowance()
            )
            order.fitness_weekly_used_this_week = (
                order.fitness_weekly_used_count(today)
                if order.fitness_subscription_product_id else 0
            )

    # ─── ISO-week utilities ────────────────────────────────────────────────────

    @classmethod
    def _get_iso_week_bounds(cls, ref_date):
        """Return (week_start, week_end) for the ISO week containing ref_date.

        week_start: the Monday (WEEK_START_ISODAY) that opens the week.
        week_end:   the Monday that opens the NEXT week (exclusive upper bound).
        Both are datetime.date objects.

        Year-boundary weeks are handled correctly by date.fromisocalendar():
        e.g. 2021-01-01 belongs to ISO week 53 of 2020, so week_start is
        2020-12-28, not 2021-01-04.
        """
        if isinstance(ref_date, datetime.datetime):
            ref_date = ref_date.date()
        iso_year, iso_week, _ = ref_date.isocalendar()
        week_start = datetime.date.fromisocalendar(iso_year, iso_week, WEEK_START_ISODAY)
        week_end = week_start + datetime.timedelta(days=7)
        return week_start, week_end

    def fitness_effective_weekly_allowance(self):
        """Return the weekly class cap that applies to this subscription.

        Returns the per-member override (fitness_weekly_allowance_override)
        when it is >0; otherwise returns the plan's weekly_class_allowance.
        Callers MUST check fitness_is_unlimited BEFORE using this value —
        for unlimited plans this returns 0, which must not be treated as
        a zero cap.
        """
        self.ensure_one()
        if self.fitness_weekly_allowance_override > 0:
            return self.fitness_weekly_allowance_override
        product = self.fitness_subscription_product_id
        return product.weekly_class_allowance if product else 0

    def fitness_weekly_used_count(self, ref_date):
        """Return the number of weekly-allowance slots consumed by this
        subscription in the ISO week that contains ref_date.

        Counts ALL allowance-paid bookings (fitness_used_floating_credit=False)
        in the week, INCLUDING cancelled ones — a cancelled allowance booking
        permanently consumes its weekly slot (anti-gaming rule; the member
        receives a floating credit instead of a refund, see Stage 5).

        ref_date: datetime.date or datetime.datetime; time part is ignored.
        """
        self.ensure_one()
        if isinstance(ref_date, datetime.datetime):
            ref_date = ref_date.date()
        week_start, week_end = self._get_iso_week_bounds(ref_date)
        # Convert date bounds to datetime (midnight) for the Datetime field.
        week_start_dt = datetime.datetime.combine(week_start, datetime.time.min)
        week_end_dt = datetime.datetime.combine(week_end, datetime.time.min)
        return self.env['fitness.booking'].search_count([
            ('subscription_id', '=', self.id),
            ('fitness_used_floating_credit', '=', False),
            ('class_start', '>=', fields.Datetime.to_string(week_start_dt)),
            ('class_start', '<', fields.Datetime.to_string(week_end_dt)),
        ])

    # ─── Promo date gate: block confirmation outside the promo window ────────────

    def action_confirm(self):
        """Prevent promo plans from being sold outside the 2026-09-01/11-30 window.

        Promo eligibility is date-window only (locked decision G — no 'new customer'
        check). Pass context key _fitness_promo_gate_date (datetime.date) to
        override the effective date in tests.
        """
        gate_date = self.env.context.get('_fitness_promo_gate_date') or datetime.date.today()
        for order in self:
            promo_lines = order.order_line.filtered(
                lambda l: l.product_id.fitness_promo_first_cycle_bonus > 0
            )
            if promo_lines and not (PROMO_WINDOW_START <= gate_date <= PROMO_WINDOW_END):
                names = ', '.join(promo_lines.mapped('product_id.name'))
                raise ValidationError(
                    f"Promo plan '{names}' is only available "
                    f"{PROMO_WINDOW_START.strftime('%d %b %Y')} – "
                    f"{PROMO_WINDOW_END.strftime('%d %b %Y')}. "
                    f"Today ({gate_date}) is outside this window."
                )
        return super().action_confirm()

    # ─── Activation: initialize first period + seed promo bonus + auto-place ────

    def _confirm_subscription(self):
        super()._confirm_subscription()
        gate_date = datetime.date.today()
        for sub in self:
            product = sub.fitness_subscription_product_id
            if not product:
                continue
            sub.fitness_subscription_used_classes = 0
            sub.fitness_period_start_date = sub.start_date

            product_bonus = product.fitness_promo_first_cycle_bonus or 0

            # Clase Fija plans: +1 floating credit if confirmed within promo window.
            # The product itself keeps fitness_promo_first_cycle_bonus=0 so the
            # action_confirm() gate does not block year-round sales.
            cf_promo = (
                product.fitness_is_clase_fija
                and PROMO_WINDOW_START <= gate_date <= PROMO_WINDOW_END
            )

            if cf_promo:
                sub.fitness_floating_credits = 1
                _logger.info(
                    "[SUBSCRIPTION] %s confirmed (CF opening promo): plan=%s "
                    "period_start=%s → 1 floating credit seeded",
                    sub.name, product.name, sub.start_date,
                )
            elif product_bonus:
                sub.fitness_floating_credits = product_bonus
                _logger.info(
                    "[SUBSCRIPTION] %s confirmed (promo): plan=%s period_start=%s "
                    "→ %d floating credit(s) seeded",
                    sub.name, product.name, sub.start_date, product_bonus,
                )
            else:
                sub.fitness_floating_credits = 0
                _logger.info(
                    "[SUBSCRIPTION] %s confirmed: plan=%s period_start=%s",
                    sub.name, product.name, sub.start_date,
                )

            sub._auto_place_clase_fija()

    # ─── Renewal: reset usage counter; floating credits carry forward ────────────

    def _update_next_invoice_date(self):
        # Snapshot BEFORE super() advances next_invoice_date. The old value is the
        # start of the newly-opened billing period; the advanced value is its end.
        old_invoice_dates = {sub.id: sub.next_invoice_date for sub in self}
        super()._update_next_invoice_date()
        for sub in self:
            if not sub.fitness_subscription_product_id:
                continue
            sub.fitness_subscription_used_classes = 0
            # fitness_floating_credits is NOT reset — credits carry forward
            # across billing periods until consumed by an actual booking.
            # fitness_period_start_date = start of the NEW period (old next_invoice_date)
            sub.fitness_period_start_date = old_invoice_dates.get(sub.id)
            _logger.info(
                "[SUBSCRIPTION] %s renewed: reporting_counter=0 "
                "floating_credits=%d (carried forward) "
                "period_start=%s period_end=%s",
                sub.name, sub.fitness_floating_credits,
                sub.fitness_period_start_date, sub.next_invoice_date,
            )
            sub._auto_place_clase_fija()

    # ─── Clase Fija auto-placement (multi-slot) ──────────────────────────────

    def _auto_place_clase_fija(self):
        """Create fitness.booking records for every occurrence of EACH active
        fitness.clase.fija slot within the current billing period.

        FIX 1 rule: any failure (no schedule found for a slot, class full,
        unexpected error) is collected and raised as a visible ValidationError —
        never swallowed silently.

        Idempotent: already-booked occurrences are silently skipped, so calling
        this on re-confirm or manual retry is safe.
        """
        self.ensure_one()
        active_slots = self.fitness_clase_fija_ids.filtered('active')
        if not active_slots:
            return 0  # no slots configured — no-op

        period_start = self.fitness_period_start_date or self.start_date
        period_end = self.next_invoice_date
        if not period_start or not period_end:
            raise ValidationError(
                f"[CLASE FIJA] {self.name}: period dates not set "
                f"(period_start={period_start}, next_invoice_date={period_end}). "
                "Ensure start_date and next_invoice_date are set before confirming."
            )
        if period_end <= period_start:
            # Odoo 19 sets next_invoice_date = start_date on initial confirmation
            # (first invoice due immediately; it advances by billing_period after
            # the first invoice is posted). Derive the real period end from the plan
            # so placement covers the full first billing cycle.
            billing = self.plan_id and self.plan_id.billing_period
            if not billing:
                raise ValidationError(
                    f"[CLASE FIJA] {self.name}: period_start ({period_start}) is not "
                    f"before period_end ({period_end}) and no billing period could be "
                    "derived from the plan. Check subscription date/plan setup."
                )
            period_end = period_start + billing
            _logger.info(
                "[CLASE FIJA] %s: next_invoice_date == start_date (pre-first-invoice); "
                "derived period_end from plan billing_period as %s",
                self.name, period_end,
            )

        period_start_dt = datetime.datetime.combine(period_start, datetime.time.min)
        period_end_dt = datetime.datetime.combine(period_end, datetime.time.min)
        partner = self.partner_id
        all_errors = []
        total_booked = 0

        for slot in active_slots:
            anchor = slot.calendar_event_id
            # Find every occurrence of this slot's class in the billing period.
            domain = [
                ('is_fitness_class', '=', True),
                ('start', '>=', fields.Datetime.to_string(period_start_dt)),
                ('start', '<', fields.Datetime.to_string(period_end_dt)),
            ]
            if anchor.recurrence_id:
                domain.append(('recurrence_id', '=', anchor.recurrence_id.id))
            else:
                domain.append(('id', '=', anchor.id))

            occurrences = self.env['calendar.event'].search(domain, order='start asc')

            if not occurrences:
                all_errors.append(
                    f"  • Slot '{slot.name}': no occurrences found "
                    f"in {period_start}–{period_end} — add to schedule then re-confirm"
                )
                continue

            for event in occurrences:
                # Idempotent: skip occurrences already assigned this period.
                # Includes no_show/cancelled so reruns don't create duplicate slots
                # for weeks the student already missed or intentionally cancelled.
                already = self.env['fitness.booking'].search_count([
                    ('student_id', '=', partner.id),
                    ('calendar_event_id', '=', event.id),
                    ('state', 'in', ('booked', 'attended', 'no_show', 'cancelled')),
                ])
                if already:
                    continue

                # FIX 1: capacity failures collected, never swallowed
                if event.capacity and event.booked_seats >= event.capacity:
                    all_errors.append(
                        f"  • {fields.Datetime.to_string(event.start)} "
                        f"'{event.name}' — full ({event.booked_seats}/{event.capacity})"
                    )
                    continue

                try:
                    self.env['fitness.booking'].with_context(
                        _fitness_clase_fija_placement=True
                    ).create({
                        'student_id': partner.id,
                        'calendar_event_id': event.id,
                        'subscription_id': self.id,
                    })
                    total_booked += 1
                except Exception as exc:
                    # FIX 1: unexpected errors also surfaced
                    all_errors.append(
                        f"  • {fields.Datetime.to_string(event.start)} "
                        f"'{event.name}' — {exc}"
                    )

        if all_errors:
            raise ValidationError(
                f"[CLASE FIJA] {self.name}: auto-placement failed for "
                f"{len(all_errors)} slot/event(s) "
                f"({total_booked} booked successfully):\n"
                + "\n".join(all_errors) + "\n\n"
                "Resolve issues above, then re-confirm or manually book remaining slots."
            )

        if total_booked > 0:
            _logger.info(
                "[CLASE FIJA] %s: auto-placed %d booking(s) across %d slot(s) "
                "for %s–%s",
                self.name, total_booked, len(active_slots), period_start, period_end,
            )
        return total_booked

    # ─── UI-7: manual "Place Classes" trigger for Clase Fija subscriptions ──────

    def action_place_clase_fija(self):
        """Manual trigger for Clase Fija auto-placement.

        Identical logic to the automatic call on confirmation/renewal — idempotent,
        existing bookings skipped, failures raised as ValidationError.

        Server-side group check mirrors the button's groups= attribute so the
        method is protected even when called directly via RPC or shell.
        """
        self.ensure_one()
        if not self.env.user.has_group('fitness_core.group_fitness_manager'):
            raise UserError(
                "Only Fitness Studio Managers can place Clase Fija classes."
            )
        if not self.fitness_is_clase_fija:
            raise UserError(
                f"{self.name} is not a Clase Fija subscription."
            )
        booked = self._auto_place_clase_fija()
        if booked:
            title       = 'Classes Placed'
            message     = f'{booked} booking(s) created for {self.name}.'
            notif_type  = 'success'
        else:
            title       = 'Already Up to Date'
            message     = (
                f'All Clase Fija slots for {self.name} are already booked'
                f' — nothing new to place.'
            )
            notif_type  = 'info'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   title,
                'message': message,
                'type':    notif_type,
                'sticky':  False,
            },
        }

    # ─── Validation: called by fitness_booking before creating a booking ───────

    def validate_subscription_for_booking(self, calendar_event):
        """Mirrors sale.order.line.validate_package_for_booking() (fitness_packages)
        but for a subscription (sale.order). Raises ValidationError on failure."""
        self.ensure_one()
        product = self.fitness_subscription_product_id
        if not product:
            raise ValidationError(
                f"{self.name} is not a fitness subscription (no subscription plan product found)."
            )
        if self.subscription_state != ACTIVE_SUBSCRIPTION_STATE:
            raise ValidationError(
                f"Subscription {self.name} is not active (status: {self.subscription_state or 'none'}). "
                "It cannot be used to pay for a booking."
            )

        event_studio = calendar_event.class_type_id.classroom_type or calendar_event.classroom_id.classroom_type
        event_session = calendar_event.session_type

        if product.fitness_class_type != 'any' and product.fitness_class_type != event_studio:
            raise ValidationError(
                f"This subscription ({product.fitness_class_type or 'unset'} discipline) cannot be used "
                f"for a {event_studio or 'unset'} class."
            )
        if product.fitness_session_type != event_session:
            raise ValidationError(
                f"This subscription is for '{product.fitness_session_type}' sessions only; "
                f"the selected class is a '{event_session}' session."
            )

        if not product.is_unlimited:
            weekly_used = self.fitness_weekly_used_count(calendar_event.start)
            eff = self.fitness_effective_weekly_allowance()
            if weekly_used >= eff and self.fitness_floating_credits <= 0:
                raise ValidationError(
                    f"Weekly limit reached on {self.name}: "
                    f"{weekly_used}/{eff} allowance classes already booked this week "
                    f"and no floating credits remaining."
                )
