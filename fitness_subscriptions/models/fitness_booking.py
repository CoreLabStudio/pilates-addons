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
            order.fitness_weekly_used_count(
                event.start,
                discipline=(event.class_type_id.classroom_type
                            or event.classroom_id.classroom_type)),
            order.fitness_effective_weekly_allowance(
                discipline=(event.class_type_id.classroom_type
                            or event.classroom_id.classroom_type)),
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
            _disc = (ev.class_type_id.classroom_type
                     or ev.classroom_id.classroom_type)
            weekly_used = sub.fitness_weekly_used_count(ev.start, discipline=_disc)
            eff = sub.fitness_effective_weekly_allowance(discipline=_disc)
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

        # Three ways a floating-credit booking reaches this method, and
        # they do NOT all return the credit:
        #
        #   the student cancels outside the window
        #       credit_returned is already True, nothing else set.
        #       -> returns the credit. She kept her side of the bargain.
        #
        #   the studio calls the whole class off (action_cancel_class)
        #       _class_cancelled and admin_force_refund are both set.
        #       -> returns the credit, whatever the timing. She did not
        #          choose this, and a pack booking already gets its
        #          credit back in exactly this case.
        #
        #   a manager cancels ONE booking - the late-cancel wizard's
        #       "Restore Credit" tick, or "Return the credit" on the
        #       cancel-or-move dialog - which sets admin_force_refund and
        #       so sets credit_returned.
        #       -> returns the credit, because that is what the tick says.
        #
        # All three now reduce to credit_returned, which is the same
        # single question a pack booking and an allowance booking have
        # always been asked. The context no longer has to be read at all.
        #
        # The version before this carried `not manager_forced`, which was
        # perverse in one case: a manager cancelling a booking already
        # OUTSIDE the window, with the tick ON, got no credit, while the
        # same cancellation with the tick OFF returned one. Ticking "give
        # the credit back" took it away.
        #
        # A class MOVED to another time never arrives here at all - the
        # reassign wizard rewrites calendar_event_id and does not cancel.
        studio_called_off = bool(self.env.context.get('_class_cancelled'))

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
            elif was_floating and booking.credit_returned:
                # A make-up credit is a credit. She cancelled outside the
                # window, which is the whole bargain the booking screen
                # and every confirmation email state: cancel in time and
                # you keep what you paid. Refusing here made that promise
                # false for exactly the students who had already been
                # inconvenienced once.
                #
                # This is not a way to manufacture credits. The cancelled
                # booking still holds its weekly slot - the counter is
                # monotonic and untouched by this change - so a cycle of
                # book-and-cancel returns the student to where she
                # started and never past it.
                sub.sudo().fitness_floating_credits += 1
                if studio_called_off:
                    sub.sudo().message_post(body=self.env._(
                        "Make-up credit returned: the studio called off "
                        "%(klass)s, and %(student)s had paid for it with a "
                        "make-up credit.",
                        student=booking.student_id.display_name,
                        klass=booking.calendar_event_id.display_name))
                else:
                    sub.sudo().message_post(body=self.env._(
                        "Make-up credit returned: %(student)s cancelled "
                        "%(klass)s outside the cancellation window, and the "
                        "booking had been paid with a make-up credit.",
                        student=booking.student_id.display_name,
                        klass=booking.calendar_event_id.display_name))
                _logger.info(
                    "[SUBSCRIPTION] Floating-credit cancellation on %s (%s) "
                    "→ +1 floating credit returned (%d total)",
                    sub.name,
                    "studio called the class off" if studio_called_off
                    else "cancelled outside the window",
                    sub.sudo().fitness_floating_credits,
                )
            elif was_floating:
                # Still nothing, in the two cases that have not changed:
                # a late cancellation (credit_returned False - she cannot
                # reach this as a student anyway, the base refuses her),
                # and a class the studio called off, which is left exactly
                # as it was by instruction. The studio case is worth
                # revisiting: a member loses her make-up credit because
                # the studio cancelled, which is nobody's fault but hers
                # to bear. Out of scope here.
                _logger.info(
                    "[SUBSCRIPTION] Floating-credit cancellation on %s → no "
                    "credit restored (credit_returned=%s)",
                    sub.name, booking.credit_returned,
                )
            # fitness_subscription_used_classes is NEVER decremented — it is a
            # monotonic period reporting counter; enforcement uses weekly counts.
        return True

    def _restore_credit_now(self):
        """A membership booking gets one make-up credit back.

        The same thing a cancellation outside the window gives her, and it
        does not matter whether the booking was paid from the weekly
        allowance or from a make-up credit: the weekly counter is
        monotonic and stays untouched, and the compensation is one credit.
        """
        done = super()._restore_credit_now()
        sub = self.subscription_id
        if not sub or sub.fitness_is_unlimited:
            return done
        sub.sudo().fitness_floating_credits += 1
        _logger.info(
            "[SUBSCRIPTION] Credit given back on %s -> %d make-up credit(s)",
            sub.name, sub.sudo().fitness_floating_credits)
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
            # A combined membership covers two disciplines, so either matches.
            # Matching on the primary alone left a "1 Barre + 1 Reformer"
            # member unable to book Reformer at all: the plan was skipped here
            # and they were told nothing covered that class type, even though
            # validate_subscription_for_booking would have allowed it.
            sub_types = {product.fitness_class_type}
            if product.fitness_secondary_class_type:
                sub_types.add(product.fitness_secondary_class_type)
            if 'any' not in sub_types and event_studio not in sub_types:
                continue
            if product.fitness_session_type != event_session:
                continue
            if not product.is_unlimited:
                weekly_used = sub.fitness_weekly_used_count(
                    calendar_event.start, discipline=event_studio)
                eff = sub.fitness_effective_weekly_allowance(
                    discipline=event_studio)
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
            # The line's own discipline, not the product's. A combined package
            # is two lines against one product - one Barre pool, one Reformer
            # pool - and asking the product would match both pools for either
            # class, letting a Reformer booking spend the Barre credits.
            pool_type = line.fitness_class_type or product.fitness_class_type
            if pool_type not in ('any', event_studio):
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
