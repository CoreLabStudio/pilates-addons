from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    fitness_is_teacher = fields.Boolean(
        compute='_compute_fitness_is_teacher',
        string='Is Instructor',
    )

    @api.depends('all_group_ids')
    def _compute_fitness_is_teacher(self):
        teacher_group = self.env.ref(
            'fitness_core.group_fitness_teacher', raise_if_not_found=False
        )
        for user in self:
            user.fitness_is_teacher = bool(teacher_group and teacher_group in user.all_group_ids)

    # ── Student actions ───────────────────────────────────────────────────────

    def action_view_student_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Bookings — {self.name}',
            'res_model': 'fitness.booking',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.partner_id.id)],
            'context': {'default_student_id': self.partner_id.id},
        }

    def action_view_student_packages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Packages — {self.name}',
            'res_model': 'sale.order.line',
            'view_mode': 'list',
            'domain': [
                ('order_id.partner_id', '=', self.partner_id.id),
                ('order_id.state', 'in', ('sale', 'done')),
                ('fitness_original_class_count', '>', 0),
            ],
        }

    def action_view_student_subscriptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Memberships — {self.name}',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', '=', self.partner_id.id),
                ('fitness_subscription_product_id', '!=', False),
            ],
        }

    def action_view_student_credits(self):
        """Open the package lines the student's balance is summed from.

        Note this lists package credits only. Subscription floating credits are
        counted in the balance but live on the sale.order, so they are reached
        through the Memberships button instead; one act_window cannot span both
        models.
        """
        self.ensure_one()
        lines = self.partner_id._fitness_active_package_lines()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Credits — {self.name}',
            'res_model': 'sale.order.line',
            'view_mode': 'list',
            'views': [(self.env.ref('fitness_portal.view_fitness_credit_line_list').id, 'list')],
            'domain': [('id', 'in', lines.ids)],
        }

    def action_view_student_messages(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Messages — {self.name}',
            'res_model': 'fitness.studio.conversation',
            'view_mode': 'list,form',
            'domain': [('user_id', '=', self.id)],
        }

    # ── Teacher actions ───────────────────────────────────────────────────────

    def action_view_teacher_classes(self):
        """Classes this teacher is assigned to teach (calendar.event where user_id = self)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Classes — {self.name}',
            'res_model': 'calendar.event',
            'view_mode': 'list,calendar,form',
            'domain': [
                ('user_id', '=', self.id),
                ('is_fitness_class', '=', True),
            ],
            'context': {
                'default_user_id': self.id,
                'default_is_fitness_class': True,
            },
        }
