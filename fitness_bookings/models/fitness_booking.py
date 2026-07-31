from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

import logging
_logger = logging.getLogger(__name__)


class FitnessBooking(models.Model):
    _name = 'fitness.booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Class Booking'
    _order = 'booking_date desc'

    # ─── Identity ─────────────────────────────────────────────────────────────

    name = fields.Char(compute='_compute_name', store=True)

    @api.depends('student_id', 'calendar_event_id')
    def _compute_name(self):
        for rec in self:
            student = rec.student_id.name or '?'
            event = rec.calendar_event_id.name or '?'
            rec.name = f"{student} – {event}"

    # ─── Core booking fields ───────────────────────────────────────────────────

    student_id = fields.Many2one(
        'res.partner', "Student",
        required=True, ondelete='restrict', tracking=True,
    )
    calendar_event_id = fields.Many2one(
        'calendar.event', "Class",
        required=True, ondelete='restrict', tracking=True,
    )
    booking_date = fields.Datetime(
        "Booked At",
        default=lambda self: fields.Datetime.now(),
        readonly=True,
    )
    state = fields.Selection([
        ('booked',     'Booked'),
        ('attended',   'Attended'),
        ('no_show',    'No-show'),
        ('cancelled',  'Cancelled'),
    ], default='booked', tracking=True, string="Status")

    # ─── Payment source ────────────────────────────────────────────────────────

    package_order_line_id = fields.Many2one(
        'sale.order.line', "Package Credit Used",
        ondelete='set null',
        help="Which class-pack line deducted a credit for this booking.",
    )
    # Odoo 19: subscriptions are sale.order with is_subscription=True
    subscription_id = fields.Many2one(
        'sale.order', "Subscription Used",
        ondelete='set null',
        domain=[('is_subscription', '=', True)],
        help="Which subscription counted this booking against the monthly cap.",
    )

    # ─── Manager override: booking lead-time window ────────────────────────────
    # Allows a manager to book a class >24h ahead (e.g. for a student who
    # calls in advance).  Grants NO exemption from any other check — capacity,
    # weekly cap, discipline-match, duplicate, overlap, and the ≤2h cancellation
    # rule are all unaffected.
    #
    # field groups= hides it from the UI for non-managers.
    # Server-side: _validate_new_booking() re-checks has_group() before honouring
    # the value, so a non-manager who force-sends the field via API is still blocked.
    manager_override_timewindow = fields.Boolean(
        "Manager Override: Skip 24h Window",
        default=False,
        groups="fitness_core.group_fitness_manager",
        help="Ticking this allows a manager to book a class more than 24 hours in "
             "advance. Does NOT bypass capacity, weekly cap, discipline-match, "
             "duplicate, overlap, or the 2-hour cancellation rule.",
    )

    # ─── Cancellation ─────────────────────────────────────────────────────────

    cancellation_date = fields.Datetime("Cancelled At", readonly=True)
    credit_returned = fields.Boolean(
        "Credit Returned",
        default=False,
        help="True only when cancelled >2 h before class – credit goes back to package/subscription.",
    )

    # ─── Attendance (filled by teacher) ───────────────────────────────────────

    marked_by_id = fields.Many2one(
        'res.users', "Marked By", readonly=True,
    )
    marked_date = fields.Datetime("Marked At", readonly=True)

    # ─── Convenience related fields ────────────────────────────────────────────

    classroom_id = fields.Many2one(
        'fitness.classroom',
        related='calendar_event_id.classroom_id',
        store=True, string="Classroom",
    )
    class_type_id = fields.Many2one(
        'fitness.class.type',
        related='calendar_event_id.class_type_id',
        store=True, string="Class Type",
    )
    # calendar.event.user_id is res.users (the responsible/teacher user)
    teacher_user_id = fields.Many2one(
        'res.users',
        related='calendar_event_id.user_id',
        store=True, string="Teacher",
    )
    class_start = fields.Datetime(
        related='calendar_event_id.start',
        store=True, string="Class Start",
    )

    # ─── CREATE (all validation happens here) ─────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate_new_booking(vals)
        bookings = super().create(vals_list)
        for booking in bookings:
            booking._refresh_booked_seats()
        return bookings

    def _validate_new_booking(self, vals):
        event = self.env['calendar.event'].browse(vals['calendar_event_id'])
        student = self.env['res.partner'].browse(vals['student_id'])

        now = fields.Datetime.now()
        class_start = event.start
        time_until = class_start - now

        _logger.info(
            "[BOOKING] Validating: student=%s event=%s time_until=%.1f h",
            student.name, event.name, time_until.total_seconds() / 3600,
        )

        # ── 1. Class must be in the future ────────────────────────────────────
        if time_until.total_seconds() <= 0:
            raise ValidationError(
                f"Cannot book a class that has already started or passed "
                f"({class_start.strftime('%Y-%m-%d %H:%M')} UTC)."
            )

        # ── 2. Cannot book more than 24 h in advance ──────────────────────────
        # Exception: a manager may tick manager_override_timewindow to bypass
        # this specific check.  The group membership is re-verified here
        # server-side so a non-manager who force-sends the field is still blocked.
        _tw_override = (
            vals.get('manager_override_timewindow')
            and (
                self.env.user.has_group('fitness_core.group_fitness_manager')
                or self.env.user.has_group('base.group_system')
            )
        )
        if not _tw_override and time_until.total_seconds() > 86400:
            raise ValidationError(
                f"Booking opens 24 hours before the class. "
                f"This class starts in {time_until.days}d "
                f"{int(time_until.seconds / 3600)}h – come back later."
            )

        _logger.info("[BOOKING] ✓ Time window OK")

        # ── 3. Concurrency-safe capacity check (row-level lock) ───────────────
        self.env.cr.execute(
            "SELECT id FROM calendar_event WHERE id = %s FOR UPDATE NOWAIT",
            [event.id],
        )
        booked = self.search_count([
            ('calendar_event_id', '=', event.id),
            ('state', 'in', ('booked', 'attended')),
        ])
        capacity = event.capacity
        if capacity and booked >= capacity:
            raise ValidationError(
                f"'{event.name}' is full – {booked}/{capacity} seats taken."
            )

        _logger.info("[BOOKING] ✓ Capacity OK (%d/%d)", booked, capacity)

        # ── 4. Prevent double-booking ─────────────────────────────────────────
        duplicate = self.search([
            ('student_id', '=', vals['student_id']),
            ('calendar_event_id', '=', vals['calendar_event_id']),
            ('state', 'in', ('booked', 'attended', 'no_show')),
        ], limit=1)
        if duplicate:
            raise ValidationError(
                f"{student.name} is already booked for this class."
            )

        _logger.info("[BOOKING] ✓ No duplicate")

        # ── 5. Prevent overlapping bookings (different classes, same time window) ──
        overlapping = self.search([
            ('student_id', '=', vals['student_id']),
            ('state', 'in', ('booked', 'attended')),
            ('calendar_event_id.start', '<', event.stop),
            ('calendar_event_id.stop', '>', event.start),
        ])
        if overlapping:
            raise ValidationError(
                f"{student.name} already has a booking that overlaps this class time "
                f"({overlapping[0].calendar_event_id.name})."
            )

        _logger.info("[BOOKING] ✓ No time overlap")

    def _refresh_booked_seats(self):
        """Re-count active bookings and write back to the calendar event."""
        count = self.search_count([
            ('calendar_event_id', '=', self.calendar_event_id.id),
            ('state', 'in', ('booked', 'attended')),
        ])
        # sudo() is narrow: booked_seats is a server-computed aggregate written
        # only by the booking engine. Portal users calling action_cancel() cannot
        # write calendar.event; granting them broad event-write access would be
        # wrong. This is the only calendar.event write in the cancel path.
        self.calendar_event_id.sudo().booked_seats = count
        _logger.info(
            "[BOOKING] booked_seats updated to %d for event %s",
            count, self.calendar_event_id.name,
        )

    # ─── CANCEL ───────────────────────────────────────────────────────────────

    def action_cancel(self):
        """
        Cancellation rules:
          >2 h before start → credit_returned = True, student can trigger
          ≤2 h before start → credit_returned = False, admin only
          admin ≤2 h + not _admin_cancel_direct context → opens wizard with explicit
            restore_credit checkbox; wizard re-calls with _admin_cancel_direct=True
        """
        # Single-record admin late-cancel: show wizard unless wizard is already calling us.
        is_admin = (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        )
        if (
            len(self) == 1
            and is_admin
            and not self.env.context.get('_admin_cancel_direct')
            and self.state == 'booked'
        ):
            now = fields.Datetime.now()
            hours_until = (self.calendar_event_id.start - now).total_seconds() / 3600
            if hours_until <= 2:
                wizard = self.env['fitness.booking.cancel.wizard'].create({'booking_id': self.id})
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Cancel Booking (Late)',
                    'res_model': 'fitness.booking.cancel.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'target': 'new',
                }

        for booking in self:
            if booking.state == 'cancelled':
                raise UserError("This booking is already cancelled.")
            if booking.state in ('attended', 'no_show'):
                raise UserError("Cannot cancel a class that has already been marked.")

            now = fields.Datetime.now()
            time_until = booking.calendar_event_id.start - now
            hours_until = time_until.total_seconds() / 3600

            _logger.info(
                "[CANCEL] %s | event=%s | %.1f h until class",
                booking.student_id.name, booking.calendar_event_id.name, hours_until,
            )

            if hours_until <= 2 and not (
                self.env.user.has_group('base.group_system')
                or self.env.user.has_group('fitness_core.group_fitness_manager')
            ):
                raise UserError(
                    "This class starts in less than 2 hours. "
                    "Late cancellations within 2 hours can only be done by a studio admin/manager."
                )

            # credit_returned: True when >2 h before start, or admin explicitly chose refund
            if hours_until > 2 or self.env.context.get('admin_force_refund'):
                booking.credit_returned = True
                _logger.info(
                    "[CANCEL] credit returned (%.1f h until class, force_refund=%s)",
                    hours_until, bool(self.env.context.get('admin_force_refund')),
                )
            else:
                booking.credit_returned = False
                _logger.info("[CANCEL] ≤2 h – NO credit")

            booking.write({
                'state': 'cancelled',
                'cancellation_date': fields.Datetime.now(),
            })
            booking._refresh_booked_seats()
        return True

    # ─── ATTENDANCE ───────────────────────────────────────────────────────────

    def action_mark_attended(self):
        """Teacher marks student as attended."""
        is_manager = (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        )
        for booking in self:
            if not is_manager and fields.Datetime.now() < booking.calendar_event_id.start:
                raise UserError(
                    "This class hasn’t started yet — "
                    "attendance can be marked once it begins."
                )
            if booking.state != 'booked':
                raise UserError("Only a 'Booked' entry can be marked as attended.")
            booking.write({
                'state': 'attended',
                'marked_by_id': self.env.uid,
                'marked_date': fields.Datetime.now(),
            })
            booking._refresh_booked_seats()
            _logger.info(
                "[ATTENDANCE] %s → attended (marked by %s)",
                booking.sudo().student_id.name, self.env.user.name,
            )
        return True

    def action_mark_no_show(self):
        """Teacher marks student as no-show. Credit is lost (already consumed on booking)."""
        is_manager = (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        )
        for booking in self:
            if not is_manager and fields.Datetime.now() < booking.calendar_event_id.start:
                raise UserError(
                    "This class hasn’t started yet — "
                    "attendance can be marked once it begins."
                )
            if booking.state != 'booked':
                raise UserError("Only a 'Booked' entry can be marked as no-show.")
            booking.write({
                'state': 'no_show',
                'marked_by_id': self.env.uid,
                'marked_date': fields.Datetime.now(),
            })
            booking._refresh_booked_seats()
            _logger.info(
                "[NO-SHOW] %s → no-show (marked by %s)",
                booking.sudo().student_id.name, self.env.user.name,
            )
        return True
