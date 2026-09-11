from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

from odoo.addons.fitness_bookings.exceptions import LateCancellationError

import logging
_logger = logging.getLogger(__name__)

#: How close to the start of a class a student may still cancel and keep
#: their credit, in hours. The studio can override it without a deploy by
#: setting the ``fitness.cancellation_window_hours`` system parameter.
#:
#: This was three separate hardcoded 2s, one of which decided whether the
#: credit came back. Changing the rule meant finding all three and every
#: sentence that quoted the number, and the sentences were what the portal
#: matched on to recognise the error. One value now, read in one place.
CANCELLATION_WINDOW_HOURS = 6.0

# How far ahead a student may book. The portal timetable reads this so it can
# say "booking opens on ..." in place instead of letting the student tap
# through and bounce off the ValidationError below.
BOOKING_WINDOW_DAYS = 7

# The studio does not take bookings for classes before it opens.
#
# The timetable is generated well ahead of opening, so classes exist on dates
# the studio is not running yet - the 10th and the 16th each carried a full
# day of them, and nothing stopped a student booking one. The rule had been
# agreed but was never actually written down anywhere in the code.
#
# The 16th is the opening event rather than a normal class day, so the studio
# wanted the 17th to be the first bookable day.
#
# The date lives in a system parameter and there is deliberately no default in
# code. A hard-coded 2026-09-17 here refused every booking made before that
# date in every database that ran this module - which broke the test suite the
# moment it landed, because tests create a class a few days out and book it.
# A rule that silently blocks bookings should be switched on by somebody, in
# the environment that wants it, not inherited by every new database.
#
# Set fitness.opening_date to a date to switch it on; clear it to retire the
# rule once opening has passed.
OPENING_DATE_PARAM = 'fitness.opening_date'


def fitness_opening_date(env):
    """First date the studio accepts bookings for, or None when unset."""
    raw = (env['ir.config_parameter'].sudo()
           .get_param(OPENING_DATE_PARAM) or '').strip()
    if not raw:
        return None
    try:
        return fields.Date.to_date(raw)
    except (ValueError, TypeError):
        _logger.warning(
            "[BOOKING] %s is %r, which is not a date; opening rule skipped.",
            OPENING_DATE_PARAM, raw)
        return None


class FitnessBooking(models.Model):
    _name = 'fitness.booking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Class Booking'
    _order = 'booking_date desc'

    # ─── Identity ─────────────────────────────────────────────────────────────

    name = fields.Char(compute='_compute_name', store=True)

    def _mail_get_partner_fields(self, introspect_fields=False):
        """Tell the mail layer that the customer on a booking is `student_id`.

        Odoo's default only looks for `partner_id` / `partner_ids`. This model
        names its customer `student_id`, so `_mail_get_partners()` found nobody,
        `_message_get_default_recipients()` returned empty, and every template
        rendered with `use_default_to=True` (the Odoo default) produced a
        mail.mail with no partner_ids and no email_to. In other words all five
        fitness notification emails were queued and could never be delivered,
        regardless of SMTP.

        Overriding this single hook is enough: it sits upstream of
        `_message_get_default_recipients`, so the base implementation keeps
        doing its own normalisation, ban-list and public-partner filtering, and
        the chatter/followers subsystem resolves the student consistently too.
        """
        fnames = super()._mail_get_partner_fields(introspect_fields=introspect_fields)
        if 'student_id' not in fnames:
            fnames = list(fnames) + ['student_id']
        return fnames

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
        store=True, string="Instructor",
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

    def _skip_booking_window(self, vals, student, event):
        """May this one booking ignore the seven-day window?

        False here, and overridden by the module that has a reason. The
        manager override above is a different thing: it is a field the caller
        sends and is re-checked against the group. This one is never supplied
        by the caller at all - it is worked out from the booking itself, so
        nothing a student can post will earn the exemption.
        """
        return False

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

        # ── 1b. Not before the studio opens ──────────────────────────────────
        # Checked before the 7-day window so a class on the opening day gets
        # the reason that is actually true, rather than being told to come
        # back later when coming back later would not help.
        #
        # No manager override: this is not a restriction on the student, it is
        # the studio not running classes yet, and it applies to the back office
        # for the same reason. Moving the date moves it for everyone.
        opening = fitness_opening_date(self.env)
        if opening and class_start.date() < opening:
            raise ValidationError(
                f"The studio opens on {opening.strftime('%d %b %Y')}. "
                f"Classes before then are on the timetable but are not open "
                f"for booking - this one is on "
                f"{class_start.strftime('%d %b %Y')}."
            )

        # ── 2. Cannot book more than 7 days in advance ───────────────────────
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
        if (not _tw_override
                and not self._skip_booking_window(vals, student, event)
                and time_until.total_seconds() > BOOKING_WINDOW_DAYS * 86400):
            raise ValidationError(
                f"Booking opens 7 days before the class. "
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

    def _notify_moved(self, origin_event):
        """Hook: the studio moved this booking to another class.

        A no-op here. fitness_notifications overrides it to tell the student -
        being moved is something that happens *to* them, so silence would mean
        turning up to a class they are no longer booked into.
        """
        return

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

    def action_open_reassign_wizard(self):
        """Open the cancel-or-move wizard for this one booking.

        Called from the student's booking under Students and from the class
        roster under Classes. Both arrive here so the two entry points cannot
        drift into behaving differently.
        """
        self.ensure_one()
        wizard = self.env['fitness.booking.reassign.wizard'].create({
            'booking_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Cancel or move this student'),
            'res_model': 'fitness.booking.reassign.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ─── CANCEL ───────────────────────────────────────────────────────────────

    @staticmethod
    def _format_window(hours):
        """6.0 -> '6', 1.5 -> '1.5'. Students should not read a float."""
        return str(int(hours)) if float(hours).is_integer() else str(hours)

    @api.model
    def _cancellation_window_hours(self):
        """The studio's cancellation window, in hours.

        Reads the ``fitness.cancellation_window_hours`` system parameter and
        falls back to CANCELLATION_WINDOW_HOURS. Anything unparseable falls
        back too rather than raising: a typo in a settings field must not stop
        every cancellation in the studio.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'fitness.cancellation_window_hours')
        if raw in (None, False, ''):
            return CANCELLATION_WINDOW_HOURS
        try:
            return float(raw)
        except (TypeError, ValueError):
            _logger.warning(
                "fitness.cancellation_window_hours is %r, which is not a number; "
                "falling back to %s h", raw, CANCELLATION_WINDOW_HOURS)
            return CANCELLATION_WINDOW_HOURS

    def action_cancel(self):
        """
        Cancellation rules, where W is the studio's cancellation window:
          >W h before start → credit_returned = True, student can trigger
          ≤W h before start → credit_returned = False, admin only
          admin ≤W h + not _admin_cancel_direct context → opens wizard with explicit
            restore_credit checkbox; wizard re-calls with _admin_cancel_direct=True

        W comes from _cancellation_window_hours(), never from a literal here.
        """
        window = self._cancellation_window_hours()
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
            if hours_until <= window:
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

            if hours_until <= window and not (
                self.env.user.has_group('base.group_system')
                or self.env.user.has_group('fitness_core.group_fitness_manager')
            ):
                # A type, not a sentence: the portal catches this class rather
                # than searching the wording for a number.
                raise LateCancellationError(
                    self.env._(
                        "This class starts in less than %(hours)s hours. Late "
                        "cancellations within %(hours)s hours can only be done "
                        "by a studio admin/manager.",
                        hours=self._format_window(window),
                    ),
                    window_hours=window,
                )

            # credit_returned: True when outside the window, or admin explicitly chose refund
            if hours_until > window or self.env.context.get('admin_force_refund'):
                booking.credit_returned = True
                _logger.info(
                    "[CANCEL] credit returned (%.1f h until class, force_refund=%s)",
                    hours_until, bool(self.env.context.get('admin_force_refund')),
                )
            else:
                booking.credit_returned = False
                _logger.info("[CANCEL] within %s h window - NO credit", window)

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
