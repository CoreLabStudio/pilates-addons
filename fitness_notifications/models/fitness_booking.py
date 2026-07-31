from datetime import timedelta

from odoo import models, fields, api

import logging
_logger = logging.getLogger(__name__)


class FitnessBookingNotifications(models.Model):
    """Extends fitness.booking with email notifications on booking lifecycle events.

    Hooks ONLY the two existing student-facing events (create() = booking confirmed,
    action_cancel() = booking cancelled) — never calendar.event field changes such as
    a teacher swap. A future fitness_teacher_swap module can pass
    context={'skip_fitness_notification': True} on any write it makes to guarantee no
    student email is ever emitted as a side effect of a teacher change; this module
    itself never touches calendar.event at all, so swaps are silent by construction.
    """
    _inherit = 'fitness.booking'

    reminder_sent = fields.Boolean(
        "Reminder Sent",
        default=False,
        readonly=True,
        help="Set once the class-reminder cron has emailed this booking's student. "
             "Prevents duplicate reminders.",
    )

    @api.model
    def _notif_enabled(self, key):
        """key in {'send_confirmation', 'send_cancellation', 'send_reminder'}"""
        value = self.env['ir.config_parameter'].sudo().get_param(f'fitness_notifications.{key}', 'True')
        return str(value).lower() in ('true', '1')

    def _send_notification(self, template_xmlid):
        if self.env.context.get('skip_fitness_notification'):
            return
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning("[NOTIFICATIONS] Template %s not found, skipping send.", template_xmlid)
            return
        for booking in self:
            try:
                template.send_mail(booking.id, force_send=False)
                _logger.info("[NOTIFICATIONS] Queued %s for booking %s (student=%s)",
                             template_xmlid, booking.id, booking.student_id.name)
            except Exception:
                _logger.exception("[NOTIFICATIONS] Failed to queue %s for booking %s",
                                   template_xmlid, booking.id)

    # ─── Booking confirmed (create) ─────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        bookings = super().create(vals_list)
        if self._notif_enabled('send_confirmation'):
            bookings._send_notification('fitness_notifications.mail_template_booking_confirmation')
        for booking in bookings:
            self._maybe_notify_credit_low(booking)
        return bookings

    def _maybe_notify_credit_low(self, booking):
        """Create an in-app notification when a student's remaining credits drop to 1."""
        LOW_THRESHOLD = 1
        partner = booking.student_id
        line = self.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '<=', LOW_THRESHOLD),
            ('fitness_remaining_classes', '>', 0),
        ], limit=1)
        if not line:
            return
        user = partner.user_ids[:1]
        if not user:
            return
        recent = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'credit_low'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=24)),
        ], limit=1)
        if recent:
            return
        remaining = line.fitness_remaining_classes
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_low',
            f'Only {remaining} credit(s) left',
            'Running low on credits. Browse packages to top up.',
        )

    # ─── Booking cancelled ───────────────────────────────────────────────────────

    def action_cancel(self):
        super().action_cancel()
        if self._notif_enabled('send_cancellation'):
            self._send_notification('fitness_notifications.mail_template_booking_cancellation')

    # ─── Class reminder (cron) ──────────────────────────────────────────────────

    @api.model
    def _cron_send_reminders(self):
        if not self._notif_enabled('send_reminder'):
            _logger.info("[NOTIFICATIONS] Reminders disabled via settings, cron skipped.")
            return
        lead_hours = float(self.env['ir.config_parameter'].sudo().get_param(
            'fitness_notifications.reminder_lead_hours', '24'))
        now = fields.Datetime.now()
        window_end = now + timedelta(hours=lead_hours)

        due = self.search([
            ('state', '=', 'booked'),
            ('reminder_sent', '=', False),
            ('class_start', '>', now),
            ('class_start', '<=', window_end),
        ])
        if not due:
            _logger.info("[NOTIFICATIONS] No reminders due (lead=%.1fh).", lead_hours)
            return
        due._send_notification('fitness_notifications.mail_template_class_reminder')
        due.write({'reminder_sent': True})
        _logger.info("[NOTIFICATIONS] Sent %d reminder(s) (lead=%.1fh).", len(due), lead_hours)

    # ─── Credit pack expiry check (cron) ────────────────────────────────────────

    @api.model
    def _cron_check_credit_expiry(self):
        """Notify students whose credit pack expires within 7 days (once per pack per week)."""
        if not self._notif_enabled('send_credit_expiry'):
            return
        today = fields.Date.today()
        expiry_window = today + timedelta(days=7)

        expiring_lines = self.env['sale.order.line'].sudo().search([
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
            ('fitness_validity_end_date', '!=', False),
            ('fitness_validity_end_date', '>=', today),
            ('fitness_validity_end_date', '<=', expiry_window),
        ])
        notified = 0
        for line in expiring_lines:
            partner = line.order_partner_id
            user = partner.user_ids[:1]
            if not user:
                continue
            recent = self.env['fitness.notification'].sudo().search([
                ('user_id', '=', user.id),
                ('notification_type', '=', 'credit_expiring'),
                ('create_date', '>=', fields.Datetime.now() - timedelta(days=7)),
            ], limit=1)
            if recent:
                continue
            days_left = (line.fitness_validity_end_date - today).days
            remaining = line.fitness_remaining_classes
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'credit_expiring',
                f'{remaining} credit(s) expiring in {days_left} day(s)',
                f'Your pack expires on {line.fitness_validity_end_date.strftime("%d %b %Y")}. '
                'Use your remaining credits before they expire.',
            )
            notified += 1
        _logger.info("[NOTIFICATIONS] Credit expiry: notified %d student(s).", notified)
