import datetime

from odoo import models, fields, api
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

# Sentinel for sources with no fixed expiry (unlimited subscriptions).
# Sorting these LAST means a dated source — whose classes would be lost if unused —
# is always consumed before one that replenishes or has no cap.
_DATE_MAX = datetime.date.max


class FitnessBookingSubscription(models.Model):
    """Extends fitness.booking to integrate subscription weekly-allowance management."""
    _inherit = 'fitness.booking'

    # ── FLOATING-CREDIT FLAG ────────────────────────────────────────────────────
    # True when this booking was paid from the subscription's floating-credit pool
    # rather than from the weekly allowance. Used in two places:
    #   (1) fitness_weekly_used_count() excludes these from the ISO-week tally so
    #       floating-credit bookings do not consume a weekly slot.
    #   (2) action_cancel(): cancelling a floating-credit booking never restores
    #       the credit (anti-gaming rule).
    fitness_used_floating_credit = fields.Boolean(
        "Paid with Floating Credit",
        default=False,
        help="True when this booking was charged against the subscription's floating "
             "credit pool rather than the weekly allowance. Floating-credit bookings "
             "are exempt from the weekly cap and do not generate a new credit on "
             "cancellation.",
    )

    # ─── Validation: called inside super().create() ────────────────────────────

    def _validate_new_booking(self, vals):
        if self.env.context.get('_fitness_clase_fija_placement'):
            # Capacity pre-checked; time-window and cap validation bypassed for
            # batch auto-placement. Failures are surfaced by _auto_place_clase_fija().
            return
        super()._validate_new_booking(vals)
        sub_id = vals.get('subscription_id')
        if not sub_id:
            return
        order = self.env['sale.order'].browse(sub_id)
        event = self.env['calendar.event'].browse(vals['calendar_event_id'])
        order.validate_subscription_for_booking(event)
        _logger.info(
            "[SUBSCRIPTION] ✓ %s valid — weekly_used=%d eff=%d floating_credits=%d",
            order.name,
            order.fitness_weekly_used_count(event.start),
            order.fitness_effective_weekly_allowance(),
            order.fitness_floating_credits,
        )

    # ─── Booking creation: floating-credit flag + reporting counter ───────────

    @api.model_create_multi
    def create(self, vals_list):
        # ── UI-5: auto-select payment source when the form leaves it unset ───
        # Called before floating-credit pre-computation so the rest of the
        # pipeline (weekly-cap flag, _validate_new_booking, discipline-match)
        # all see a fully-populated source — no guard is bypassed.
        # Only runs when NEITHER source field is set by the caller.  An explicit
        # choice by the admin (or by _auto_place_clase_fija / tests) is always
        # respected (neither branch of the `or` is entered).
        for vals in vals_list:
            if vals.get('subscription_id') or vals.get('package_order_line_id'):
                continue  # caller already chose a source — don't override
            student_id = vals.get('student_id')
            event_id   = vals.get('calendar_event_id')
            if not student_id or not event_id:
                continue  # incomplete vals; existing validation will block later
            event = self.env['calendar.event'].browse(event_id)
            # _select_payment_source raises UserError if no valid source exists,
            # which propagates as a user-facing error and blocks the INSERT.
            source = self._select_payment_source(student_id, event)
            vals.update(source)

        # ── Pre-compute floating-credit flag BEFORE super().create() ─────────
        # fitness_weekly_used_count() must be called now, while the DB still
        # shows the pre-booking count. The flag is injected into vals so the
        # record is created with the correct value in the same INSERT.
        for vals in vals_list:
            sub_id = vals.get('subscription_id')
            if not sub_id:
                continue
            sub = self.env['sale.order'].browse(sub_id)
            if sub.fitness_is_unlimited:
                vals['fitness_used_floating_credit'] = False
                continue
            ev = self.env['calendar.event'].browse(vals['calendar_event_id'])
            weekly_used = sub.fitness_weekly_used_count(ev.start)
            eff = sub.fitness_effective_weekly_allowance()
            # True = weekly cap already met → charge floating credit instead.
            vals['fitness_used_floating_credit'] = (weekly_used >= eff)

        bookings = super().create(vals_list)

        for booking in bookings:
            sub = booking.subscription_id
            if not sub:
                continue
            sub_sudo = sub.sudo()
            if booking.fitness_used_floating_credit:
                # Floating-credit booking: deduct one credit from the cycle pool.
                sub_sudo.fitness_floating_credits = max(0, sub.fitness_floating_credits - 1)
                _logger.info(
                    "[SUBSCRIPTION] Floating credit used on %s → %d credits remaining",
                    sub.name, sub_sudo.fitness_floating_credits,
                )
            else:
                _logger.info(
                    "[SUBSCRIPTION] Allowance slot consumed on %s",
                    sub.name,
                )
            # REPORTING ONLY: period total counts every booking (allowance + floating).
            # Never read for enforcement — enforcement uses fitness_weekly_used_count().
            sub_sudo.fitness_subscription_used_classes += 1
            _logger.info(
                "[SUBSCRIPTION] Period total on %s → %d (reporting only)",
                sub.name, sub_sudo.fitness_subscription_used_classes,
            )

        return bookings

    # ─── Cancellation: grant floating credit for allowance bookings only ────────

    def action_cancel(self):
        # Snapshot both maps BEFORE super() sets credit_returned and changes state.
        # .read() returns plain dicts, bypassing the Odoo 19 ORM field_cache lookup
        # that raises TypeError: unhashable type: 'list' on Many2one access.
        booking_data = self.sudo().read(['subscription_id', 'fitness_used_floating_credit'])
        sub_map = {}
        float_map = {}
        for d in booking_data:
            bid = d['id']
            float_map[bid] = d['fitness_used_floating_credit']
            if d['subscription_id']:
                # .read() returns Many2one as [id, display_name] or False
                sub_id = d['subscription_id'][0] if isinstance(d['subscription_id'], (list, tuple)) else d['subscription_id']
                sub_map[bid] = self.env['sale.order'].browse(sub_id)

        result = super().action_cancel()

        # If super() returned a wizard action (admin late-cancel), propagate it.
        # Credit restoration will run when the wizard confirms and re-calls action_cancel.
        if isinstance(result, dict):
            return result

        for booking in self:
            sub = sub_map.get(booking.id)
            if not sub or sub.fitness_is_unlimited:
                continue
            was_floating = float_map.get(booking.id, False)
            if booking.credit_returned and not was_floating:
                # Allowance booking cancelled >2h before class → earn 1 floating credit.
                # Weekly slot stays consumed (fitness_weekly_used_count counts
                # all non-floating bookings regardless of state — monotonic rule).
                sub.sudo().fitness_floating_credits += 1
                _logger.info(
                    "[SUBSCRIPTION] Allowance cancellation on %s → +1 floating credit (%d total)",
                    sub.name, sub.sudo().fitness_floating_credits,
                )
            elif was_floating:
                # Floating-credit booking cancelled → no credit restored (anti-gaming).
                _logger.info(
                    "[SUBSCRIPTION] Floating-credit cancellation on %s → no credit restored",
                    sub.name,
                )
            # fitness_subscription_used_classes is NEVER decremented — it is a
            # monotonic period reporting counter; enforcement uses weekly counts.
        return True

    # ─── Payment-source auto-selection ────────────────────────────────────────
    #
    # Selects the source whose allowance EXPIRES SOONEST so that members never
    # silently lose paid classes. A subscription is exhausted when its weekly slot
    # count (fitness_weekly_used_count) meets the effective cap AND floating credits
    # are depleted. Soonest-expiry-first ordering is preserved (next_invoice_date
    # for subscriptions, fitness_validity_end_date for packages). Both fields remain
    # independently settable and independently validated.

    @api.model
    def _select_payment_source(self, student_id, calendar_event):
        """Select which payment source to charge for a new booking.

        ORDERING RULE (2026-07 client decision):
          Consume the source whose current allowance EXPIRES SOONEST so that
          members never silently lose classes they already paid for.

        Expiry fields compared:
          - Package (sale.order.line): fitness_validity_end_date (Date).
          - Subscription (sale.order):  next_invoice_date (Date) = end of the
            current billing period; allowance resets on renewal.

        Edge cases:
          - Unlimited subscriptions (fitness_is_unlimited=True) have no cap that
            can be lost, so they sort LAST using _DATE_MAX as their expiry.
          - Packages without a validity date are also given _DATE_MAX (treated as
            never-expiring; existing fitness_is_expired already ignores them).
          - Same expiry date (tie): subscription is preferred over package, because
            the monthly allowance resets at period end and would otherwise be
            wasted, while a package validity-end rolls the remaining credits to
            zero permanently. This tiebreak is deterministic and documented; change
            it by adjusting the sort key's secondary tuple element.

        Sources that fail discipline-match or have no remaining credits are
        excluded; discipline-match logic is unchanged from prior implementation.
        """
        event_studio = calendar_event.class_type_id.classroom_type or calendar_event.classroom_id.classroom_type
        event_session = calendar_event.session_type

        # ── 1. Collect all valid sources ──────────────────────────────────────

        candidates = []   # list of (expiry_date, tiebreak_int, source_dict)
        # tiebreak_int: 0 = subscription, 1 = package  →  lower wins on equal expiry

        # Subscriptions that matched discipline/session but were excluded only
        # because the weekly allowance is exhausted and floating credits = 0.
        # Populated so we can raise a specific "weekly limit reached" error
        # instead of the generic "no source covers this class" message.
        capped_subs = []  # list of dicts with cap details for the error message

        subscriptions = self.env['sale.order'].search([
            ('partner_id', '=', student_id),
            ('subscription_state', '=', '3_progress'),
            ('fitness_subscription_product_id', '!=', False),
        ])
        for sub in subscriptions:
            product = sub.fitness_subscription_product_id
            if product.fitness_class_type not in ('any', event_studio):
                continue
            if product.fitness_session_type != event_session:
                continue
            if not product.is_unlimited:
                weekly_used = sub.fitness_weekly_used_count(calendar_event.start)
                eff = sub.fitness_effective_weekly_allowance()
                if weekly_used >= eff and sub.fitness_floating_credits <= 0:
                    capped_subs.append({
                        'product_name': product.name,
                        'sub_ref': sub.name,
                        'weekly_used': weekly_used,
                        'weekly_allowance': eff,
                    })
                    continue  # weekly cap exhausted and no floating credits
            # Unlimited subs expire "never"; metered subs expire at period end.
            expiry = _DATE_MAX if product.is_unlimited else (sub.next_invoice_date or _DATE_MAX)
            candidates.append((expiry, 0, {'subscription_id': sub.id}))

        lines = self.env['sale.order.line'].search([
            ('order_partner_id', '=', student_id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ])
        for line in lines:
            if line.fitness_is_expired:
                continue
            product = line.product_id
            if product.fitness_class_type not in ('any', event_studio):
                continue
            if product.fitness_session_type != event_session:
                continue
            expiry = line.fitness_validity_end_date or _DATE_MAX
            candidates.append((expiry, 1, {'package_order_line_id': line.id}))

        if not candidates:
            if capped_subs:
                n = capped_subs[0]['weekly_allowance']
                word = 'class' if n == 1 else 'classes'
                _logger.info(
                    "[PAYMENT-SOURCE] Cap exhausted for student=%d event=%s: %s",
                    student_id, calendar_event.name,
                    "; ".join(f"{c['sub_ref']} {c['weekly_used']}/{c['weekly_allowance']}" for c in capped_subs),
                )
                raise UserError(
                    f"You've reached your weekly limit of {n} {word}. "
                    f"Your allowance resets at the start of your next billing period."
                )
            raise UserError(
                "No active subscription or package covers this class type. "
                "Contact the studio if you think this is an error."
            )

        # ── 2. Sort by (expiry ASC, tiebreak ASC) and return first ────────────
        candidates.sort(key=lambda c: (c[0], c[1]))
        chosen = candidates[0]
        _logger.info(
            "[PAYMENT-SOURCE] Selected %s (expiry %s) from %d candidate(s) for %s/%s",
            list(chosen[2].keys())[0], chosen[0], len(candidates),
            event_studio, event_session,
        )
        return chosen[2]
