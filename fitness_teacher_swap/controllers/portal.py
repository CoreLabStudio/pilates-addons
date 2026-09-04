from datetime import timedelta, datetime as _dt_cls
from itertools import groupby as _groupby
from urllib.parse import quote

import pytz


# The studio, the site and the portal are Spanish-first, so anything with
# no language set falls back to Spanish rather than to Odoo's English base.
DEFAULT_LANG = 'es_ES'

try:
    from babel.dates import format_date as _babel_format_date
    _BABEL_OK = True
except Exception:
    _BABEL_OK = False

from odoo import http, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

TEACHER_GROUP = 'fitness_core.group_fitness_teacher'


def _format_local(dt, user_tz):
    if not dt:
        return ''
    return pytz.UTC.localize(dt).astimezone(user_tz).strftime('%d/%m/%Y %H:%M')


class FitnessTeacherSwapPortal(http.Controller):

    @http.route('/my/instructor/classes', type='http', auth='user', website=True, sitemap=False)
    def my_classes(self, filter='all', **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        now = fields.Datetime.now()

        try:
            user_tz = pytz.timezone(request.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC

        # Timezone-aware day boundaries for today/week filters
        now_local = pytz.UTC.localize(now).astimezone(user_tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)

        if filter not in ('today', 'week', 'all'):
            filter = 'all'

        domain = [
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
        ]
        if filter == 'today':
            domain += [
                ('start', '>=', today_start_utc),
                ('start', '<',  today_start_utc + timedelta(days=1)),
            ]
        elif filter == 'week':
            domain += [
                ('start', '>=', today_start_utc),
                ('start', '<',  today_start_utc + timedelta(days=7)),
            ]
        else:
            domain += [('start', '>=', now)]

        events = request.env['calendar.event'].search(domain, order='start asc')

        other_teachers = request.env['res.users'].sudo().search([
            ('id', '!=', request.env.user.id),
            ('group_ids', 'in', [request.env.ref(TEACHER_GROUP).id]),
        ])

        events_ctx = []
        for ev in events:
            booked_count = request.env['fitness.booking'].search_count([
                ('calendar_event_id', '=', ev.id),
                ('state', 'in', ('booked', 'attended', 'no_show')),
            ])
            events_ctx.append({
                'event':       ev,
                'local_start': _format_local(ev.start, user_tz),
                'booked':      booked_count,
            })

        return request.render('fitness_teacher_swap.portal_my_classes', {
            'events_ctx':     events_ctx,
            'other_teachers': other_teachers,
            'active_filter':  filter,
            'error':          kw.get('error'),
            'success':        kw.get('success'),
        })

    @http.route('/my/instructor/classes/<int:event_id>', type='http', auth='user',
                website=True, sitemap=False)
    def class_roster(self, event_id, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        _ = request.env._
        event = request.env['calendar.event'].browse(event_id)

        if not event.exists() or event.user_id.id != request.env.user.id:
            return request.redirect(
                '/my/instructor/classes?error=' + quote(_('Class not found or not assigned to you.'))
            )

        # Search without sudo — teacher ir.rule scopes to own classes.
        # Re-browse with sudo so template can read student_id.name.
        booking_ids = request.env['fitness.booking'].search([
            ('calendar_event_id', '=', event_id),
            ('state', 'in', ('booked', 'attended', 'no_show')),
        ], order='student_id asc').ids
        bookings = request.env['fitness.booking'].sudo().browse(booking_ids)

        try:
            user_tz = pytz.timezone(request.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC

        return request.render('fitness_teacher_swap.portal_teacher_roster', {
            'event':         event,
            'local_start':   _format_local(event.start, user_tz),
            'bookings':      bookings,
            'class_started': fields.Datetime.now() >= event.start,
            'marked':        bool(kw.get('marked')),
            'success':       kw.get('success'),
            'error':         kw.get('error'),
        })

    @http.route('/my/instructor/classes/<int:event_id>/mark', type='http', auth='user',
                methods=['POST'], website=True, sitemap=False)
    def mark_attendance(self, event_id, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        _ = request.env._
        roster_url = f'/my/instructor/classes/{event_id}'

        try:
            booking_id = int(kw.get('booking_id', 0) or 0)
        except (ValueError, TypeError):
            return request.redirect(f'{roster_url}?error=' + quote(_('Invalid request.')))

        action = kw.get('action', '')
        if action not in ('attended', 'no_show'):
            return request.redirect(f'{roster_url}?error=' + quote(_('Invalid request.')))

        event = request.env['calendar.event'].browse(event_id)
        if not event.exists() or event.user_id.id != request.env.user.id:
            return request.redirect(
                '/my/instructor/classes?error=' + quote(_('Class not found or not assigned to you.'))
            )

        # Teacher ir.rule scopes booking search to own classes at DB level.
        booking = request.env['fitness.booking'].browse(booking_id)

        if not booking.exists() or booking.calendar_event_id.id != event_id:
            return request.redirect(f'{roster_url}?error=' + quote(_('Booking not found.')))

        if fields.Datetime.now() < event.start:
            msg = quote(_("This class hasn't started yet — attendance can be marked once it begins."))
            return request.redirect(f'{roster_url}?error={msg}')

        try:
            if action == 'attended':
                booking.action_mark_attended()
            else:
                booking.action_mark_no_show()
        except (UserError, ValidationError) as exc:
            msg = str(exc)
            if "Only a 'Booked' entry" in msg:
                msg = _('This booking has already been marked.')
            return request.redirect(f'{roster_url}?error={quote(msg)}')

        return request.redirect(f'{roster_url}?marked=1')

    @http.route('/my/instructor/classes/<int:event_id>/reassign', type='http', auth='user',
                methods=['POST'], website=True, sitemap=False)
    def reassign(self, event_id, new_teacher_id=None, reason='', **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        try:
            event = request.env['calendar.event'].browse(int(event_id))
            event.fitness_reassign_teacher(
                int(new_teacher_id),
                reason=reason.strip() if reason else '',
            )
        except Exception as exc:
            return request.redirect(f'/my/instructor/classes?error={quote(str(exc))}')
        return request.redirect('/my/instructor/classes')

    @http.route('/my/instructor/history', type='http', auth='user', website=True, sitemap=False)
    def my_class_history(self, period=None, **kw):
        import re as _re
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        now = fields.Datetime.now()
        lang_code = (request.lang.code if request.lang else None) or DEFAULT_LANG

        cutoff_start = cutoff_end = None
        if period and _re.match(r'^\d{4}-\d{2}$', period):
            try:
                yr, mo = int(period[:4]), int(period[5:7])
                cutoff_start = _dt_cls(yr, mo, 1)
                cutoff_end = _dt_cls(yr + (1 if mo == 12 else 0), 1 if mo == 12 else mo + 1, 1)
            except ValueError:
                period = 'all'
        else:
            period = 'all'

        try:
            user_tz = pytz.timezone(request.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC

        domain = [
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
            ('start', '<', now),
        ]
        if cutoff_start:
            domain.append(('start', '>=', cutoff_start))
        if cutoff_end:
            domain.append(('start', '<', cutoff_end))

        # Build available months from all past events (no cutoff)
        all_events_for_months = request.env['calendar.event'].search([
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
            ('start', '<', now),
            ('start', '!=', False),
        ], order='start desc', limit=500)
        all_month_keys = sorted({
            e.start.strftime('%Y-%m') for e in all_events_for_months if e.start
        }, reverse=True)
        available_months = []
        for mk in all_month_keys:
            try:
                dt = _dt_cls.strptime(mk + '-01', '%Y-%m-%d')
                lbl = _babel_format_date(dt, format='MMMM yyyy', locale=lang_code) if _BABEL_OK else mk
            except Exception:
                lbl = mk
            available_months.append({'key': mk, 'label': lbl})

        past_events = request.env['calendar.event'].search(domain, order='start desc', limit=200)

        events_ctx = []
        for ev in past_events:
            attended = request.env['fitness.booking'].search_count([
                ('calendar_event_id', '=', ev.id),
                ('state', '=', 'attended'),
            ])
            total = request.env['fitness.booking'].search_count([
                ('calendar_event_id', '=', ev.id),
                ('state', 'in', ('booked', 'attended', 'no_show')),
            ])
            events_ctx.append({
                'event':       ev,
                'local_start': _format_local(ev.start, user_tz),
                'attended':    attended,
                'total':       total,
            })

        month_groups = []
        for month_key, items in _groupby(
            events_ctx,
            key=lambda ctx: ctx['event'].start.strftime('%Y-%m') if ctx['event'].start else 'unknown'
        ):
            entries = list(items)
            try:
                dt = _dt_cls.strptime(month_key + '-01', '%Y-%m-%d')
                label = _babel_format_date(dt, format='MMMM yyyy', locale=lang_code) if _BABEL_OK else month_key
            except Exception:
                label = month_key
            month_groups.append({'key': month_key, 'label': label, 'entries': entries})

        return request.render('fitness_teacher_swap.portal_teacher_history', {
            'month_groups':    month_groups,
            'filter_period':   period,
            'available_months': available_months,
        })

    @http.route('/my/instructor/swaps', type='http', auth='user', website=True,
                sitemap=False)
    def my_swap_history(self, **kw):
        """An instructor's own swap history.

        Every swap was already recorded - the admin reads them in Cambios de
        Instructor - but an instructor had no way to see their own. That is the
        one person who most needs it: which of their classes somebody else took
        and which they picked up, so a disagreement about who was meant to be
        in the room is settled by a record rather than by memory.

        A swap has two sides and the same record is both, so it is read once
        and split by which side this user is on. "Given away" and "picked up"
        are the two questions actually being asked, and a single merged list
        answers neither at a glance.
        """
        user = request.env.user
        if not user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        try:
            user_tz = pytz.timezone(user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC

        # sudo: a swap names two instructors, and the other one is the whole
        # point of the record. Read is scoped to rows this user is a party to
        # by the domain itself, so this widens nothing else.
        swaps = request.env['fitness.teacher.swap'].sudo().search([
            '|',
            ('original_teacher_id', '=', user.id),
            ('new_teacher_id', '=', user.id),
        ], order='class_start desc, create_date desc', limit=300)

        source_labels = dict(
            request.env['fitness.teacher.swap']._fields['initiated_by'].selection)

        def row(sw):
            mine_was_given = sw.original_teacher_id.id == user.id
            other = sw.new_teacher_id if mine_was_given else sw.original_teacher_id
            return {
                'id': sw.id,
                'class_name': sw.class_name or (sw.class_type_id.name or ''),
                'when': _format_local(sw.class_start, user_tz),
                'logged': _format_local(sw.create_date, user_tz),
                'other': other.name or '',
                'reason': (sw.reason or '').strip(),
                'source': source_labels.get(sw.initiated_by, sw.initiated_by or ''),
                'event_id': sw.calendar_event_id.id if sw.calendar_event_id else 0,
                # A swap of a class that has already happened is history; one
                # still ahead is something the instructor may need to act on.
                'past': bool(sw.class_start and sw.class_start < fields.Datetime.now()),
            }

        given = [row(s) for s in swaps if s.original_teacher_id.id == user.id]
        taken = [row(s) for s in swaps if s.new_teacher_id.id == user.id]

        return request.render('fitness_teacher_swap.portal_teacher_swaps', {
            'given': given,
            'taken': taken,
            'total': len(given) + len(taken),
        })

    # ── Legacy redirects — keep old /my/teacher/ URLs working (notification emails) ──
    @http.route('/my/teacher/classes', type='http', auth='user', website=True, sitemap=False)
    def _legacy_classes(self, **kw):
        qs = request.httprequest.query_string.decode('utf-8')
        return request.redirect('/my/instructor/classes' + ('?' + qs if qs else ''), code=301)

    @http.route('/my/teacher/classes/<int:event_id>', type='http', auth='user', website=True, sitemap=False)
    def _legacy_class_detail(self, event_id, **kw):
        return request.redirect(f'/my/instructor/classes/{event_id}', code=301)

    @http.route('/my/teacher/history', type='http', auth='user', website=True, sitemap=False)
    def _legacy_history(self, **kw):
        qs = request.httprequest.query_string.decode('utf-8')
        return request.redirect('/my/instructor/history' + ('?' + qs if qs else ''), code=301)
