import html as _html
from datetime import timedelta

from odoo import models, fields, api


class FitnessAdminDashboard(models.TransientModel):
    _name = 'fitness.admin.dashboard'
    _description = 'Admin Dashboard'

    name = fields.Char(default='Admin Dashboard')

    # ── Stat tile counters ────────────────────────────────────────────────────

    today_classes = fields.Integer(string='Classes Today', compute='_compute_stats')
    pending_trials = fields.Integer(string='Pending Trials', compute='_compute_stats')
    pending_swaps = fields.Integer(string='Teacher Swaps', compute='_compute_stats')
    unread_messages = fields.Integer(string='Unread Messages', compute='_compute_stats')
    active_students = fields.Integer(string='Students', compute='_compute_stats')

    # ── Preview panels ────────────────────────────────────────────────────────

    preview_classes_html = fields.Html(
        compute='_compute_previews', sanitize=False, string='Classes Preview',
    )
    preview_trials_html = fields.Html(
        compute='_compute_previews', sanitize=False, string='Trials Preview',
    )
    preview_messages_html = fields.Html(
        compute='_compute_previews', sanitize=False, string='Messages Preview',
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _safe_count(self, model_name, domain=None):
        try:
            return self.env[model_name].sudo().search_count(domain or [])
        except Exception:
            return 0

    def _safe_search(self, model_name, domain=None, order=None, limit=5):
        try:
            kw = {}
            if order:
                kw['order'] = order
            if limit:
                kw['limit'] = limit
            return self.env[model_name].sudo().search(domain or [], **kw)
        except Exception:
            return self.env[model_name].sudo().browse()

    # ── Stat tile compute ─────────────────────────────────────────────────────

    def _teacher_user_ids(self):
        """Return list of user IDs in the teacher group, via SQL (groups_id not searchable in Odoo 19)."""
        teacher_g = self.env.ref('fitness_core.group_fitness_teacher', raise_if_not_found=False)
        if not teacher_g:
            return []
        self.env.cr.execute(
            "SELECT uid FROM res_groups_users_rel WHERE gid = %s", [teacher_g.id]
        )
        return [row[0] for row in self.env.cr.fetchall()]

    def _compute_stats(self):
        today = fields.Date.today()
        tomorrow = today + timedelta(days=1)
        teacher_ids = self._teacher_user_ids()

        for rec in self:
            rec.today_classes = self.env['calendar.event'].search_count([
                ('is_fitness_class', '=', True),
                ('start', '>=', fields.Datetime.to_datetime(today)),
                ('start', '<', fields.Datetime.to_datetime(tomorrow)),
            ])
            rec.pending_trials = rec._safe_count(
                'fitness.trial.request', [('status', '=', 'pending')]
            )
            rec.pending_swaps = rec._safe_count('fitness.teacher.swap')
            rec.unread_messages = rec._safe_count(
                'fitness.studio.conversation', [('has_unread', '=', True)]
            )
            domain = [('share', '=', True), ('active', '=', True)]
            if teacher_ids:
                domain.append(('id', 'not in', teacher_ids))
            rec.active_students = self.env['res.users'].sudo().search_count(domain)

    # ── Preview panel compute ─────────────────────────────────────────────────

    def _compute_previews(self):
        today = fields.Date.today()
        tomorrow = today + timedelta(days=1)

        for rec in self:
            # ── Today's classes ───────────────────────────────────────────────
            classes = self.env['calendar.event'].search([
                ('is_fitness_class', '=', True),
                ('start', '>=', fields.Datetime.to_datetime(today)),
                ('start', '<', fields.Datetime.to_datetime(tomorrow)),
            ], order='start asc', limit=5)

            if classes:
                rows = ''
                for cls in classes:
                    local = fields.Datetime.context_timestamp(rec, cls.start)
                    time_str = local.strftime('%H:%M')
                    teacher = _html.escape(cls.user_id.name or '—')
                    name = _html.escape(cls.name or '—')
                    booked = cls.booked_seats or 0
                    cap = str(cls.capacity) if cls.capacity else '∞'
                    rows += (
                        f'<tr><td>{time_str}</td><td>{name}</td>'
                        f'<td>{teacher}</td><td>{booked}/{cap}</td></tr>'
                    )
                rec.preview_classes_html = (
                    '<table class="table table-sm mb-0">'
                    '<thead><tr><th>Time</th><th>Class</th><th>Teacher</th><th>Seats</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )
            else:
                rec.preview_classes_html = (
                    '<p class="text-muted mb-0">No classes scheduled for today.</p>'
                )

            # ── Pending trials ────────────────────────────────────────────────
            trials = rec._safe_search(
                'fitness.trial.request',
                [('status', '=', 'pending')],
                order='create_date asc',
                limit=5,
            )
            if trials:
                rows = ''
                for t in trials:
                    name = _html.escape(t.name or '—')
                    interest = _html.escape(t.class_interest or '—')
                    rows += f'<tr><td>{name}</td><td>{interest}</td></tr>'
                rec.preview_trials_html = (
                    '<table class="table table-sm mb-0">'
                    '<thead><tr><th>Name</th><th>Interest</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )
            else:
                rec.preview_trials_html = (
                    '<p class="text-muted mb-0">No pending trial requests.</p>'
                )

            # ── Unread messages ───────────────────────────────────────────────
            convs = rec._safe_search(
                'fitness.studio.conversation',
                [('has_unread', '=', True)],
                order='write_date desc',
                limit=5,
            )
            if convs:
                rows = ''
                for conv in convs:
                    student = _html.escape(
                        conv.partner_id.name if conv.partner_id else '—'
                    )
                    role = _html.escape(conv.role or '—')
                    last = (
                        fields.Datetime.context_timestamp(rec, conv.last_activity).strftime('%d %b %H:%M')
                        if conv.last_activity else '—'
                    )
                    rows += (
                        f'<tr><td>{student}</td><td>{role}</td><td>{last}</td></tr>'
                    )
                rec.preview_messages_html = (
                    '<table class="table table-sm mb-0">'
                    '<thead><tr><th>Student</th><th>Role</th><th>Last Activity</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )
            else:
                rec.preview_messages_html = (
                    '<p class="text-muted mb-0">No messages awaiting reply.</p>'
                )

    # ── Stat tile click actions ────────────────────────────────────────────────

    def action_view_today_classes(self):
        today = fields.Date.today()
        tomorrow = today + timedelta(days=1)
        return {
            'type': 'ir.actions.act_window',
            'name': "Today's Classes",
            'res_model': 'calendar.event',
            'view_mode': 'list,form',
            'domain': [
                ('is_fitness_class', '=', True),
                ('start', '>=', fields.Datetime.to_datetime(today)),
                ('start', '<', fields.Datetime.to_datetime(tomorrow)),
            ],
        }

    def action_view_pending_trials(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Pending Trial Requests',
            'res_model': 'fitness.trial.request',
            'view_mode': 'list,form',
            'domain': [('status', '=', 'pending')],
        }

    def action_view_pending_swaps(self):
        return self.env.ref(
            'fitness_teacher_swap.action_fitness_teacher_swaps'
        ).read()[0]

    def action_view_unread_messages(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Unread Messages',
            'res_model': 'fitness.studio.conversation',
            'view_mode': 'list,form',
            'domain': [('has_unread', '=', True)],
        }

    def action_view_students(self):
        teacher_ids = self._teacher_user_ids()
        domain = [('share', '=', True), ('active', '=', True)]
        if teacher_ids:
            domain.append(('id', 'not in', teacher_ids))
        base_action = self.env.ref(
            'fitness_portal.action_fitness_student_list', raise_if_not_found=False
        )
        if base_action:
            action = base_action.read()[0]
            action['domain'] = domain
            return action
        # Fallback if fitness_portal not installed
        return {
            'type': 'ir.actions.act_window',
            'name': 'Students',
            'res_model': 'res.users',
            'view_mode': 'list,form',
            'domain': domain,
        }
