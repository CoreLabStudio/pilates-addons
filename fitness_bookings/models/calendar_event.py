from odoo import models, fields
from odoo.exceptions import UserError

# Spanish-first, like the rest of the studio's screens.
DEFAULT_LANG = 'es_ES'

import logging
_logger = logging.getLogger(__name__)


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    booking_ids = fields.One2many(
        'fitness.booking', 'calendar_event_id',
        string="Bookings",
    )

    def action_cancel_classes_bulk(self):
        """Call off every class ticked, in one pass.

        Loops action_cancel_class rather than reimplementing it, so a class
        cancelled here ends up exactly where one cancelled from its own form
        does: bookings cancelled, credits returned, students told.

        A class already cancelled is skipped rather than failing the batch -
        somebody may have got to it first, and the rest of the selection
        still needs doing.
        """
        if not (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        ):
            raise UserError(self.env._("Only studio managers can cancel a class."))

        done = skipped = students = 0
        for event in self:
            if event.class_state == 'cancelled':
                skipped += 1
                continue
            students += event.booked_seats or 0
            event.action_cancel_class()
            done += 1

        msg = self.env._(
            "%(done)s class(es) cancelled, %(students)s student booking(s) "
            "cancelled and their credits returned.",
            done=done, students=students)
        if skipped:
            msg += " " + self.env._(
                "%(skipped)s were already cancelled and were left alone.",
                skipped=skipped)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._("Classes cancelled"),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_restore_classes(self):
        """Put a cancelled class back on the timetable.

        Only the class. The bookings that were cancelled with it are NOT
        restored, and the credits that went back to students stay with them -
        undoing that would take a class off somebody who has already been
        told theirs was cancelled, and may well have booked something else.
        Said out loud in the message rather than left to be discovered.
        """
        if not (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        ):
            raise UserError(self.env._("Only studio managers can restore a class."))

        cancelled = self.filtered(lambda e: e.class_state == 'cancelled')
        cancelled.write({'class_state': 'scheduled'})
        # booked_seats is deliberately left where it is. It is maintained by
        # fitness.booking, the bookings stay cancelled, and the seats are
        # genuinely free - putting the class back does not put anybody in it.
        _logger.info(
            "[RESTORE] %s class(es) put back on the timetable by %s",
            len(cancelled), self.env.user.login)

        msg = self.env._(
            "%(done)s class(es) back on the timetable. Students who were "
            "cancelled have not been re-booked - their credits are back and "
            "they need to book again.", done=len(cancelled))
        if len(self) - len(cancelled):
            msg += " " + self.env._(
                "%(skipped)s were not cancelled and were left alone.",
                skipped=len(self) - len(cancelled))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._("Classes restored"),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_cancel_class(self):
        """Studio-initiated class cancellation: cancel ALL active bookings,
        always restore credits (no 2-hour restriction applies to studio),
        then send in-app notifications to students and teacher."""
        self.ensure_one()
        if not (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        ):
            raise UserError(self.env._("Only studio managers can cancel an entire class."))

        if self.class_state == 'cancelled':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Already Cancelled',
                    'message': 'This class has already been cancelled.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        self.write({'class_state': 'cancelled'})

        active_bookings = self.booking_ids.filtered(lambda b: b.state == 'booked')
        if not active_bookings:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Class Cancelled',
                    'message': 'Class marked as cancelled. No active bookings to process.',
                    'type': 'success',
                    'sticky': False,
                },
            }

        n = len(active_bookings)
        # Bypass wizard and 2-hour check; always refund (studio-initiated).
        # _class_cancelled=True tells fitness_notifications to skip the per-booking
        # in-app bell — the class-level notification below handles student alerts.
        active_bookings.with_context(
            _admin_cancel_direct=True,
            admin_force_refund=True,
            _class_cancelled=True,
        ).action_cancel()

        # In-app bell notifications.
        #
        # Written in each recipient's own language, not in the language of
        # whoever pressed cancel. These were f-strings: an admin working in
        # Spanish told every student "Class cancelled" in English, and the
        # same text is what the push notification now carries.
        Notif = self.env['fitness.notification']
        class_name = self.name or self.env._('the class')

        # The local is called _ on purpose: Odoo's extractor finds translatable
        # strings by looking for calls literally named _(), so a helper under
        # any other name means these never enter the catalogue at all.
        def _for(user):
            return self.env(context=dict(
                self.env.context, lang=user.lang or DEFAULT_LANG))._

        notified = 0
        for booking in active_bookings:
            user = booking.student_id.user_ids[:1]
            if user:
                _ = _for(user)
                Notif._create_for_user(
                    user.id,
                    'booking_cancelled',
                    _('Class cancelled: %(name)s', name=class_name),
                    _('The studio has cancelled this class. Your credit has '
                      'been returned.'),
                )
                notified += 1

        teacher = self.user_id
        if teacher:
            _ = _for(teacher)
            Notif._create_for_user(
                teacher.id,
                'booking_cancelled',
                _('Class cancelled: %(name)s', name=class_name),
                _('This class was cancelled by the studio. %(n)s booking(s) '
                  'removed and credits returned.', n=n),
            )

        _logger.info(
            "[CANCEL CLASS] '%s': %d booking(s) cancelled, "
            "%d student(s) notified, teacher=%s",
            class_name, n, notified,
            teacher.name if teacher else 'none',
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Class Cancelled',
                'message': f'{n} booking(s) cancelled. Credits returned.',
                'type': 'success',
                'sticky': False,
            },
        }
