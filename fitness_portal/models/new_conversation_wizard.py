from odoo import models, fields, api


class FitnessStudioNewConversationWizard(models.TransientModel):
    _name = 'fitness.studio.new_conversation.wizard'
    _description = 'Start a new admin-initiated conversation'

    def _recipient_domain(self):
        student_g = self.env.ref('fitness_core.group_fitness_student', raise_if_not_found=False)
        teacher_g = self.env.ref('fitness_core.group_fitness_teacher', raise_if_not_found=False)
        gids = [g.id for g in [student_g, teacher_g] if g]
        if not gids:
            return [('id', '=', False)]
        return [('group_ids', 'in', gids), ('active', '=', True)]

    user_id = fields.Many2one(
        'res.users',
        string='To',
        required=True,
        domain=_recipient_domain,
    )
    body = fields.Text('Message', required=True)

    def action_send(self):
        self.ensure_one()
        Conversation = self.env['fitness.studio.conversation']
        conv = Conversation.search(
            [('user_id', '=', self.user_id.id)],
            limit=1,
            order='write_date desc',
        )
        if not conv:
            teacher_g = self.env.ref('fitness_core.group_fitness_teacher', raise_if_not_found=False)
            role = 'Teacher' if teacher_g and self.user_id in teacher_g.user_ids else 'Student'
            conv = Conversation.create({
                'user_id': self.user_id.id,
                'partner_id': self.user_id.partner_id.id,
                'role': role,
            })
        self.env['fitness.studio.message'].create({
            'conversation_id': conv.id,
            'body': self.body,
            'is_admin': True,
            'author_id': self.env.uid,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fitness.studio.conversation',
            'res_id': conv.id,
            'view_mode': 'form',
            'target': 'current',
        }
