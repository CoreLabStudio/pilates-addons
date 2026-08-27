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
    bell_reminder_sent = fields.Boolean(
        "Bell Reminder Sent",
        default=False,
        readonly=True,
        help="Set once the 6–12h bell-notification cron has fired for this booking. "
             "Prevents duplicate in-app reminders.",
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
                template.sudo().send_mail(booking.id, force_send=False)
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
            self._maybe_notify_credit_used(booking)
            self._maybe_notify_credit_low(booking)
            self._maybe_notify_credit_zero(booking)
        return bookings

    def _maybe_notify_credit_used(self, booking):
        """Notify student when a credit pack credit is used for a booking.
        Skipped for subscription bookings (no pack credits involved).
        """
        if not booking.package_order_line_id:
            return
        partner = booking.student_id
        user = partner.user_ids[:1]
        if not user:
            return
        line = booking.package_order_line_id
        remaining = line.fitness_remaining_classes or 0
        class_name = booking.calendar_event_id.name or 'class'
        lang_env = self.with_context(lang=user.lang or 'en_US')
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_used',
            lang_env.env._('1 credit used for %s', class_name),
            lang_env.env._('%d credit(s) remaining in this pack.', remaining),
            action_url='/my/packages',
        )

    def _maybe_notify_credit_zero(self, booking):
        """Notify student when their total credit balance across all packs hits zero."""
        partner = booking.student_id
        user = partner.user_ids[:1]
        if not user:
            return
        all_lines = self.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ])
        if all_lines:
            return
        recent = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id),
            ('notification_type', '=', 'credit_zero'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=24)),
        ], limit=1)
        if recent:
            return
        lang_env = self.with_context(lang=user.lang or 'en_US')
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_zero',
            lang_env.env._('No credits remaining'),
            lang_env.env._('You have used your last credit. Visit Packages to purchase more.'),
            action_url='/my/packages',
        )

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
        lang_env = self.with_context(lang=user.lang or 'en_US')
        self.env['fitness.notification'].sudo()._create_for_user(
            user.id,
            'credit_low',
            lang_env.env._('Only %d credit(s) left', remaining),
            lang_env.env._('Running low on credits. Browse packages to top up.'),
        )

    # ─── Booking cancelled ───────────────────────────────────────────────────────

    def action_cancel(self):
        super().action_cancel()
        if self._notif_enabled('send_cancellation'):
            self._send_notification('fitness_notifications.mail_template_booking_cancellation')
        # In-app bell: skip for class-wide cancellations (_class_cancelled=True)
        # because action_cancel_class() already sends a class-level alert per student.
        if self.env.context.get('skip_fitness_notification') or self.env.context.get('_class_cancelled'):
            return
        for booking in self:
            user = booking.student_id.user_ids[:1]
            if not user:
                continue
            class_name = booking.calendar_event_id.name or 'class'
            event_start = booking.calendar_event_id.start
            start_str = event_start.strftime('%d %b at %H:%M') if event_start else ''
            body = (
                f'Your booking for {class_name}'
                + (f' on {start_str}' if start_str else '')
                + ' has been cancelled. Check your credit balance for any refunds.'
            )
            try:
                self.env['fitness.notification'].sudo()._create_for_user(
                    user.id,
                    'booking_cancelled',
                    f'Booking cancelled: {class_name}',
                    body,
                    action_url='/my/classes',
                )
            except Exception:
                pass

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
        today = fields.Date.context_today(self)
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
            expire_date_str = line.fitness_validity_end_date.strftime("%d %b %Y")
            lang_env = self.with_context(lang=user.lang or 'en_US')
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'credit_expiring',
                lang_env.env._('%d credit(s) expiring in %d day(s)', remaining, days_left),
                lang_env.env._('Your pack expires on %s. Use your remaining credits before they expire.', expire_date_str),
            )
            notified += 1
        _logger.info("[NOTIFICATIONS] Credit expiry: notified %d student(s).", notified)

    # ─── Subscription billing reminder (cron, 3 days lead) ──────────────────────

    @api.model
    def _cron_send_billing_reminders(self):
        """Notify subscribers 3 days before their next renewal/billing date."""
        LEAD_DAYS = 3
        today = fields.Date.context_today(self)
        target_date = today + timedelta(days=LEAD_DAYS)

        due_subs = self.env['sale.order'].sudo().search([
            ('is_subscription', '=', True),
            ('subscription_state', '=', '3_progress'),
            ('next_invoice_date', '=', target_date),
        ])
        notified = 0
        for sub in due_subs:
            partner = sub.partner_id
            user = partner.user_ids[:1]
            if not user:
                continue
            recent = self.env['fitness.notification'].sudo().search([
                ('user_id', '=', user.id),
                ('notification_type', '=', 'billing_reminder'),
                ('create_date', '>=', fields.Datetime.now() - timedelta(hours=48)),
            ], limit=1)
            if recent:
                continue
            plan_name = sub.fitness_subscription_product_id.name if sub.fitness_subscription_product_id else sub.name
            renew_date_str = target_date.strftime("%d %b %Y")
            lang_env = self.with_context(lang=user.lang or 'en_US')
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'billing_reminder',
                lang_env.env._('Subscription renews in %d days', LEAD_DAYS),
                lang_env.env._('Your %s plan renews on %s. No action needed.', plan_name, renew_date_str),
                action_url='/my/packages',
            )
            notified += 1
        _logger.info("[NOTIFICATIONS] Billing reminders: notified %d subscriber(s).", notified)

    # ─── Class bell reminder (cron, 6–12h window) ────────────────────────────────

    @api.model
    def _cron_send_bell_reminders(self):
        """Send in-app bell notifications for classes starting in 6–12 hours.

        Fires once per booking (bell_reminder_sent flag). The 6h lower bound
        prevents overlap with last-minute logistics; 12h gives enough notice
        to prepare or cancel. Runs every 30 min so no booking falls through the gap.
        """
        now = fields.Datetime.now()
        window_start = now + timedelta(hours=6)
        window_end = now + timedelta(hours=12)

        due = self.search([
            ('state', '=', 'booked'),
            ('bell_reminder_sent', '=', False),
            ('class_start', '>', window_start),
            ('class_start', '<=', window_end),
        ])
        if not due:
            _logger.info("[NOTIFICATIONS] No bell reminders due (6–12h window).")
            return

        notified = 0
        for booking in due:
            partner = booking.student_id
            user = partner.user_ids[:1]
            if not user:
                continue
            event = booking.calendar_event_id
            class_name = event.name or 'class'
            hours_until = max(1, int((booking.class_start - now).total_seconds() / 3600))
            lang_env = self.with_context(lang=user.lang or 'en_US')
            self.env['fitness.notification'].sudo()._create_for_user(
                user.id,
                'class_reminder',
                lang_env.env._('Class in ~%d hours', hours_until),
                lang_env.env._('Reminder: %s is coming up soon. See you there!', class_name),
                action_url='/my/classes',
            )
            notified += 1

        due.write({'bell_reminder_sent': True})
        _logger.info("[NOTIFICATIONS] Bell reminders: notified %d student(s).", notified)
