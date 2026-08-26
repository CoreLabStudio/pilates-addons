from odoo import models, fields
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)


class CalendarEvent(models.Model):
    _inherit = 'calendar.event'

    booking_ids = fields.One2many(
        'fitness.booking', 'calendar_event_id',
        string="Bookings",
    )

    def action_cancel_class(self):
        """Studio-initiated class cancellation: cancel ALL active bookings,
        always restore credits (no 2-hour restriction applies to studio),
        then send in-app notifications to students and teacher."""
        self.ensure_one()
        if not (
            self.env.user.has_group('base.group_system')
            or self.env.user.has_group('fitness_core.group_fitness_manager')
        ):
            raise UserError("Only studio managers can cancel an entire class.")

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

        # In-app bell notifications
        Notif = self.env['fitness.notification']
        class_name = self.name or 'the class'

        notified = 0
        for booking in active_bookings:
            user = booking.student_id.user_ids[:1]
            if user:
                Notif._create_for_user(
                    user.id,
                    'booking_cancelled',
                    f'Class cancelled: {class_name}',
                    'The studio has cancelled this class. Your credit has been returned.',
                )
                notified += 1

        teacher = self.user_id
        if teacher:
            Notif._create_for_user(
                teacher.id,
                'booking_cancelled',
                f'Class cancelled: {class_name}',
                f'This class was cancelled by the studio. '
                f'{n} booking(s) removed and credits returned.',
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
