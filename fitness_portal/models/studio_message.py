from odoo import models, fields, api

import logging
_logger = logging.getLogger(__name__)


class FitnessStudioConversation(models.Model):
    _name = 'fitness.studio.conversation'
    _description = 'Studio Conversation'
    _order = 'write_date desc'
    _rec_name = 'display_name_computed'

    user_id = fields.Many2one(
        'res.users', 'User', required=True, readonly=True,
        ondelete='cascade', index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', 'Partner', required=True, readonly=True,
        ondelete='cascade',
    )
    role = fields.Char('Role', readonly=True)

    message_ids = fields.One2many(
        'fitness.studio.message', 'conversation_id', 'Messages',
    )
    message_count = fields.Integer(
        compute='_compute_stats', store=True,
    )
    last_activity = fields.Datetime(
        compute='_compute_stats', store=True,
    )
    has_unread = fields.Boolean(
        compute='_compute_stats', store=True,
        help="True when the latest student message has not yet received an admin reply.",
    )
    display_name_computed = fields.Char(
        compute='_compute_display_name_field', store=False,
    )
    reply_body = fields.Text('Your Reply')

    @api.depends('message_ids', 'message_ids.create_date', 'message_ids.is_admin')
    def _compute_stats(self):
        for conv in self:
            msgs = conv.message_ids
            conv.message_count = len(msgs)
            if msgs:
                dates = msgs.mapped('create_date')
                conv.last_activity = max(d for d in dates if d)
            else:
                conv.last_activity = conv.create_date
            student_msgs = msgs.filtered(lambda m: not m.is_admin)
            admin_msgs = msgs.filtered(lambda m: m.is_admin)
            if student_msgs:
                latest_student = student_msgs.sorted('create_date')[-1]
                latest_admin = admin_msgs.sorted('create_date')[-1] if admin_msgs else None
                if latest_admin and latest_admin.create_date >= latest_student.create_date:
                    conv.has_unread = False
                else:
                    conv.has_unread = True
            else:
                conv.has_unread = False

    @api.depends('user_id', 'partner_id')
    def _compute_display_name_field(self):
        for conv in self:
            name = conv.partner_id.name or conv.user_id.name or 'Unknown'
            conv.display_name_computed = f"{name} ({conv.role or 'member'})"

    def name_get(self):
        return [(r.id, r.display_name_computed or f"Conv #{r.id}") for r in self]

    def action_send_reply(self):
        for conv in self:
            body = (conv.reply_body or '').strip()
            if not body:
                return True
            self.env['fitness.studio.message'].create({
                'conversation_id': conv.id,
                'author_id': self.env.user.id,
                'author_name': self.env.user.name,
                'is_admin': True,
                'body': body,
            })
            conv.reply_body = ''
        return True


class FitnessStudioMessage(models.Model):
    _name = 'fitness.studio.message'
    _description = 'Studio Thread Message'
    _order = 'create_date asc'

    conversation_id = fields.Many2one(
        'fitness.studio.conversation', 'Conversation',
        required=True, ondelete='cascade', index=True,
    )
    author_id = fields.Many2one(
        'res.users', 'Author',
        readonly=True, ondelete='set null',
    )
    author_name = fields.Char('Author Name', readonly=True)
    is_admin = fields.Boolean('From Admin', default=False, readonly=True)
    body = fields.Text('Message', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('author_id') and not vals.get('author_name'):
                user = self.env['res.users'].browse(vals['author_id'])
                vals['author_name'] = user.name
        records = super().create(vals_list)
        # Notify the student/teacher when admin posts a reply
        for msg in records:
            if msg.is_admin:
                conv = msg.conversation_id
                if conv.user_id and conv.user_id != self.env.user:
                    try:
                        recipient = conv.user_id
                        lang_env = self.with_context(lang=recipient.lang or 'en_US')
                        sender = msg.author_name or lang_env.env._('the studio')
                        self.env['fitness.notification'].sudo()._create_for_user(
                            recipient.id,
                            'message_reply',
                            lang_env.env._('Reply from %s', sender),
                            msg.body[:200] if msg.body else None,
                            action_url='/my/messages',
                        )
                    except Exception:
                        _logger.exception(
                            "[MESSAGES] Failed to create reply notification for user %s",
                            conv.user_id.id,
                        )
        return records
