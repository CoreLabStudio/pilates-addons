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
