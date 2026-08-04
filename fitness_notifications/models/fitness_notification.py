from odoo import models, fields, api

import logging
_logger = logging.getLogger(__name__)


class FitnessNotification(models.Model):
    _name = 'fitness.notification'
    _description = 'In-App Notification'
    _order = 'create_date desc'
    _rec_name = 'title'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    title = fields.Char(required=True)
    body = fields.Text()
    notification_type = fields.Selection([
        ('booking_confirmed', 'Booking Confirmed'),
        ('booking_cancelled', 'Booking Cancelled'),
        ('credit_low', 'Credits Running Low'),
        ('credit_expiring', 'Credits Expiring'),
        ('credit_used', 'Credit Used'),
        ('credit_zero', 'No Credits Left'),
        ('teacher_swap', 'Teacher Changed'),
        ('invoice_issued', 'Invoice Issued'),
        ('purchase_completed', 'Purchase Completed'),
        ('message_reply', 'New Message Reply'),
        ('billing_reminder', 'Subscription Renewal Reminder'),
    ], required=True, default='booking_confirmed')
    read = fields.Boolean(default=False, index=True)
    action_url = fields.Char("Action URL")

    @api.model
    def _create_for_user(self, user_id, notif_type, title, body=None, action_url=None):
        """Create a single in-app notification; silently skips if user_id is falsy."""
        if not user_id:
            return
        try:
            self.sudo().create({
                'user_id': user_id,
                'notification_type': notif_type,
                'title': title,
                'body': body,
                'action_url': action_url,
            })
        except Exception:
            _logger.exception(
                "[NOTIFICATIONS] Failed to create in-app notification (type=%s, user=%s)",
                notif_type, user_id,
            )
