import html as _html

from odoo import models, fields, api

import logging
_logger = logging.getLogger(__name__)


class FitnessStudioConversation(models.Model):
    _name = 'fitness.studio.conversation'
    _description = 'Studio Conversation'
    _order = 'write_date desc'
    _rec_name = 'display_name_computed'

    user_id = fields.Many2one(
        'res.users', 'User', required=True,
        ondelete='cascade', index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', 'Partner', required=True,
        ondelete='cascade',
    )
    role = fields.Char('Role')

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
    thread_html = fields.Html(
        compute='_compute_thread_html',
        sanitize=False,
        string='Thread',
    )

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

    @api.depends(
        'message_ids.body',
        'message_ids.is_admin',
        'message_ids.author_name',
        'message_ids.create_date',
    )
    def _compute_thread_html(self):
        for conv in self:
            msgs = conv.message_ids.sorted('create_date')
            if not msgs:
                conv.thread_html = (
                    '<div style="text-align:center;color:#888;padding:32px 16px;">'
                    'No messages yet.</div>'
                )
                continue

            parts = [
                '<div style="display:flex;flex-direction:column;gap:10px;padding:16px;">'
            ]
            for msg in msgs:
                is_admin = msg.is_admin
                author = _html.escape(
                    msg.author_name or ('Studio' if is_admin else 'Student')
                )
                body = _html.escape(msg.body or '').replace('\n', '<br/>')
                try:
                    local = fields.Datetime.context_timestamp(conv, msg.create_date)
                    time_str = local.strftime('%d %b · %H:%M')
                except Exception:
                    time_str = ''

                if is_admin:
                    wrap_align = 'align-self:flex-end;align-items:flex-end;'
                    bubble_style = (
                        # Heather blue with Paco brown text - the documented
                        # brand pairing (4.71:1, AA). White on Heather is ~1.9:1.
                        'background:#9ABACD;color:#50423D;'
                        'border-radius:16px 4px 16px 16px;'
                    )
                else:
                    wrap_align = 'align-self:flex-start;align-items:flex-start;'
                    bubble_style = (
                        'background:#f0f0f0;color:#212529;'
                        'border-radius:4px 16px 16px 16px;'
                    )

                parts.append(
                    f'<div style="display:flex;flex-direction:column;{wrap_align}'
                    f'max-width:80%;">'
                    f'<div style="font-size:11px;color:#888;margin-bottom:3px;">'
                    f'{author} · {time_str}</div>'
                    f'<div style="padding:10px 14px;{bubble_style}'
                    f'font-size:13px;line-height:1.5;word-break:break-word;">'
                    f'{body}</div></div>'
                )

            parts.append('</div>')
            conv.thread_html = ''.join(parts)

    def name_get(self):
        return [(r.id, r.display_name_computed or f"Conv #{r.id}") for r in self]

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id:
            self.partner_id = self.user_id.partner_id
        else:
            self.partner_id = False

    def _get_role_for_user(self, uid):
        teacher_g = self.env.ref('fitness_core.group_fitness_teacher', raise_if_not_found=False)
        if not teacher_g:
            return 'Student'
        self.env.cr.execute(
            "SELECT 1 FROM res_groups_users_rel WHERE gid = %s AND uid = %s LIMIT 1",
            (teacher_g.id, uid),
        )
        return 'Teacher' if self.env.cr.fetchone() else 'Student'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            uid = vals.get('user_id')
            if uid:
                user = self.env['res.users'].browse(uid)
                if not vals.get('partner_id'):
                    vals['partner_id'] = user.partner_id.id
                if not vals.get('role'):
                    vals['role'] = self._get_role_for_user(uid)
        records = super().create(vals_list)
        for rec in records:
            body = (rec.reply_body or '').strip()
            if body:
                self.env['fitness.studio.message'].create({
                    'conversation_id': rec.id,
                    'author_id': self.env.uid,
                    'author_name': self.env.user.name,
                    'is_admin': True,
                    'body': body,
                })
                rec.reply_body = False
        return records

    def action_create_and_open(self):
        """Called from the create-mode form to save and stay on this conversation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fitness.studio.conversation',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

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
                            # /my/messages/<id> is not a route: the page shows
                            # the user's own single conversation, so the id was
                            # never addressable and the link 404'd.
                            action_url='/my/messages',
                        )
                    except Exception:
                        _logger.exception(
                            "[MESSAGES] Failed to create reply notification for user %s",
                            conv.user_id.id,
                        )
        return records
