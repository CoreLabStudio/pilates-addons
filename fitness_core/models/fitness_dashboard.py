import html as _html
from datetime import datetime, time, timedelta

import pytz

from odoo.exceptions import UserError
from odoo import models, fields, api, _
from odoo.tools import format_date

# The studio is in Spain. Times on this dashboard follow the studio's clock,
# not the server's and not whichever timezone the viewing user is set to.
DEFAULT_TZ = 'Europe/Madrid'


# Rows shown in the dashboard's "Today's Classes" card. Chosen so the card
# reaches the height of Pending Trials + Messages stacked beside it.
PREVIEW_CLASSES_LIMIT = 8


class FitnessAdminDashboard(models.TransientModel):
    _name = 'fitness.admin.dashboard'
    _description = 'Admin Dashboard'

    name = fields.Char(default='Admin Dashboard')

    # Which span the classes card is showing. A stored field on a transient
    # record: the dashboard is created fresh each time Home is opened, so this
    # is per-visit state and needs no cleanup.
    classes_range = fields.Selection(
        [('today', 'Today'), ('week', 'This week')],
        default='today', string='Showing')

    # ── Stat tile counters ────────────────────────────────────────────────────

    today_classes = fields.Integer(string='Classes Today', compute='_compute_stats')
    pending_trials = fields.Integer(string='Pending Trials', compute='_compute_stats')
    pending_swaps = fields.Integer(string='Instructor Swaps', compute='_compute_stats')
    unread_messages = fields.Integer(string='Unread Messages', compute='_compute_stats')
    active_students = fields.Integer(string='Students', compute='_compute_stats')

    # ── Header (greeting + date) ──────────────────────────────────────────────

    header_greeting = fields.Char(compute='_compute_header')
    header_date = fields.Char(compute='_compute_header')

    def _compute_header(self):
        """Greeting and date, in the viewing user's timezone and language."""
        for rec in self:
            now = rec._studio_now()
            hour = now.hour
            if hour < 12:
                rec.header_greeting = _("Good morning")
            elif hour < 19:
                rec.header_greeting = _("Good afternoon")
            else:
                rec.header_greeting = _("Good evening")
            # e.g. "Wednesday, 26 August" - locale aware via babel through Odoo
            try:
                rec.header_date = format_date(
                    rec.env, now.date(), date_format='EEEE, d MMMM'
                )
            except Exception:
                rec.header_date = now.strftime('%A, %d %B')

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

    def _studio_tz(self):
        """The studio's timezone, from the company, falling back to Madrid."""
        return pytz.timezone(self.env.company.partner_id.tz or DEFAULT_TZ)

    def _studio_now(self):
        """Right now, in the studio's timezone."""
        return pytz.utc.localize(fields.Datetime.now()).astimezone(self._studio_tz())

    def _today_bounds(self):
        """Start and end of today in the studio's timezone, as naive UTC.

        Returned naive so the values can go straight into an ORM domain.
        """
        tz = self._studio_tz()
        start_local = tz.localize(datetime.combine(self._studio_now().date(), time.min))
        end_local = start_local + timedelta(days=1)
        to_utc = lambda d: d.astimezone(pytz.utc).replace(tzinfo=None)
        return to_utc(start_local), to_utc(end_local)

    def _range_bounds(self):
        """Start, end and a label for the span the classes card is showing.

        The week runs from today, not from Monday: the card answers "what is
        coming", and half a week of history at the top of it is noise.
        """
        self.ensure_one()
        tz = self._studio_tz()
        today = self._studio_now().date()
        days = 7 if self.classes_range == 'week' else 1
        start_local = tz.localize(datetime.combine(today, time.min))
        end_local = start_local + timedelta(days=days)
        to_utc = lambda d: d.astimezone(pytz.utc).replace(tzinfo=None)
        return to_utc(start_local), to_utc(end_local), days

    def action_show_today(self):
        self.ensure_one()
        self.classes_range = 'today'
        return False

    def action_show_week(self):
        self.ensure_one()
        self.classes_range = 'week'
        return False

    def _compute_stats(self):
        day_start, day_end = self._today_bounds()
        teacher_ids = self._teacher_user_ids()

        for rec in self:
            rec.today_classes = self.env['calendar.event'].search_count([
                ('is_fitness_class', '=', True),
                ('start', '>=', day_start),
                ('start', '<', day_end),
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

    def _range_summary(self, classes, span_days):
        """"14 students booked across 5 classes on 17 Sept".

        Cancelled classes are already out of `classes`: counting them would
        overstate both numbers, and the studio reads this to decide whether a
        day is worth running.
        """
        self.ensure_one()
        students = sum(classes.mapped('booked_seats'))
        when = self._studio_now().date()
        if span_days > 1:
            return _(
                '%(students)s students booked across %(classes)s classes '
                'in the next %(days)s days',
                students=students, classes=len(classes), days=span_days)
        return _(
            '%(students)s students booked across %(classes)s classes on %(day)s',
            students=students, classes=len(classes),
            day=format_date(self.env, when, date_format='d MMM'))

    @staticmethod
    def _record_url(model, res_id):
        """Backend form-view URL for one record."""
        return '/odoo/%s/%s' % (model, res_id)

    # ── Preview panel compute ─────────────────────────────────────────────────

    @api.depends('classes_range')
    def _compute_previews(self):
        studio_tz = self._studio_tz()

        for rec in self:
            day_start, day_end, span_days = rec._range_bounds()
            # ── Today's classes ───────────────────────────────────────────────
            # 5 rows left the card short of the two stacked cards beside it.
            # The height is matched with real classes rather than padding;
            # anything past this is what the "See all" link is for.
            domain = [
                ('is_fitness_class', '=', True),
                ('start', '>=', day_start),
                ('start', '<', day_end),
            ]
            # Counted over the whole span, not over the rows that fit: the
            # summary is the thing that stops anyone adding up a column, so
            # it has to describe everything, not the first eight.
            all_classes = self.env['calendar.event'].sudo().search(domain)
            live = all_classes.filtered(lambda c: c.class_state != 'cancelled')
            total_students = sum(live.mapped('booked_seats'))
            limit = PREVIEW_CLASSES_LIMIT * 2 if span_days > 1 else PREVIEW_CLASSES_LIMIT
            classes = self.env['calendar.event'].search(
                domain, order='start asc', limit=limit)

            if classes:
                # Once the range spans days, the time alone does not say
                # which class is which.
                show_day = span_days > 1
                rows = ''
                for cls in classes:
                    local = pytz.utc.localize(cls.start).astimezone(studio_tz)
                    time_str = local.strftime('%H:%M')
                    day_cell = (f'<td>{_html.escape(local.strftime("%a %d"))}</td>'
                                if show_day else '')
                    teacher = _html.escape(cls.user_id.name or '—')
                    name = _html.escape(cls.name or '—')
                    booked = cls.booked_seats or 0
                    cap = str(cls.capacity) if cls.capacity else '∞'
                    url = rec._record_url('calendar.event', cls.id)
                    rows += (
                        f'<tr>{day_cell}<td>{time_str}</td>'
                        f'<td><a class="cl-rowlink" href="{url}">{name}</a></td>'
                        f'<td>{teacher}</td><td>{booked}/{cap}</td>'
                        f'<td class="cl-go"><a class="cl-rowlink" href="{url}" '
                        f'title="Open this class">→</a></td></tr>'
                    )
                day_head = '<th>Day</th>' if show_day else ''
                more = ''
                if len(all_classes) > len(classes):
                    more = _html.escape(_(
                        '%(shown)s of %(total)s shown - See all for the rest.',
                        shown=len(classes), total=len(all_classes)))
                    more = f'<p class="text-muted small mb-0 mt-1">{more}</p>'
                rec.preview_classes_html = (
                    f'<p class="mb-2"><strong>{_html.escape(rec._range_summary(live, span_days))}</strong></p>'
                    '<table class="table table-sm mb-0">'
                    f'<thead><tr>{day_head}<th>Time</th><th>Class</th>'
                    '<th>Instructor</th><th>Seats</th><th></th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>{more}'
                )
            else:
                empty = _html.escape(
                    _('No classes scheduled this week.') if span_days > 1
                    else _('No classes scheduled for today.'))
                rec.preview_classes_html = f'<p class="text-muted mb-0">{empty}</p>'

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
                    url = rec._record_url('fitness.trial.request', t.id)
                    rows += (
                        f'<tr><td><a class="cl-rowlink" href="{url}">{name}</a></td>'
                        f'<td>{interest}</td>'
                        f'<td class="cl-go"><a class="cl-rowlink" href="{url}" '
                        f'title="Open this trial request">→</a></td></tr>'
                    )
                rec.preview_trials_html = (
                    '<table class="table table-sm mb-0">'
                    '<thead><tr><th>Name</th><th>Interest</th><th></th></tr></thead>'
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
                        pytz.utc.localize(conv.last_activity).astimezone(studio_tz).strftime('%d %b %H:%M')
                        if conv.last_activity else '—'
                    )
                    url = rec._record_url('fitness.studio.conversation', conv.id)
                    rows += (
                        f'<tr><td><a class="cl-rowlink" href="{url}">{student}</a></td>'
                        f'<td>{role}</td><td>{last}</td>'
                        f'<td class="cl-go"><a class="cl-rowlink" href="{url}" '
                        f'title="Open this conversation">→</a></td></tr>'
                    )
                rec.preview_messages_html = (
                    '<table class="table table-sm mb-0">'
                    '<thead><tr><th>Student</th><th>Role</th><th>Last Activity</th><th></th></tr></thead>'
                    f'<tbody>{rows}</tbody></table>'
                )
            else:
                rec.preview_messages_html = (
                    '<p class="text-muted mb-0">No messages awaiting reply.</p>'
                )

    # ── Stat tile click actions ────────────────────────────────────────────────

    def action_open_odoo_dashboard(self):
        """Open Odoo's own Dashboards app.

        Resolved by xmlid rather than hardcoding an id, and it degrades to a
        clear message instead of a traceback if the Dashboards app is not
        installed on a given database.
        """
        self.ensure_one()
        action = self.env.ref(
            'spreadsheet_dashboard.ir_actions_dashboard_action',
            raise_if_not_found=False,
        )
        if not action:
            raise UserError(self.env._(
                "Odoo's Dashboards app is not installed on this database. "
                "Install it from Apps to use this link."
            ))
        return action.read()[0]

    def action_view_today_classes(self):
        # Follows whichever range the card is showing, so See all opens on the
        # thing the card was describing rather than always on today.
        self.ensure_one()
        day_start, day_end, span_days = self._range_bounds()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Classes this week') if span_days > 1 else _("Today's Classes"),
            'res_model': 'calendar.event',
            'view_mode': 'list,form',
            'domain': [
                ('is_fitness_class', '=', True),
                ('start', '>=', day_start),
                ('start', '<', day_end),
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
