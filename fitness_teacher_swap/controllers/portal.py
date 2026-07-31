from datetime import timedelta, datetime as _dt_cls
from itertools import groupby as _groupby
from urllib.parse import quote

import pytz

try:
    from babel.dates import format_date as _babel_format_date
    _BABEL_OK = True
except Exception:
    _BABEL_OK = False

from odoo import http, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

TEACHER_GROUP = 'fitness_core.group_fitness_teacher'

_DEFAULT_DAYS_BACK    = 7
_DEFAULT_DAYS_FORWARD = 28


def _get_window_days():
    ICP = request.env['ir.config_parameter'].sudo()
    days_back    = int(ICP.get_param('fitness_teacher.roster_days_back',    _DEFAULT_DAYS_BACK))
    days_forward = int(ICP.get_param('fitness_teacher.roster_days_forward', _DEFAULT_DAYS_FORWARD))
    return days_back, days_forward


def _format_local(dt, user_tz):
    if not dt:
        return ''
    return pytz.UTC.localize(dt).astimezone(user_tz).strftime('%d/%m/%Y %H:%M')


class FitnessTeacherSwapPortal(http.Controller):

    @http.route('/my/teacher/classes', type='http', auth='user', website=True, sitemap=False)
    def my_classes(self, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        _ = request.env._
        now = fields.Datetime.now()
        days_back, days_forward = _get_window_days()
        window_start = now - timedelta(days=days_back)
        window_end   = now + timedelta(days=days_forward)

        events = request.env['calendar.event'].search([
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
            ('start', '>=', window_start),
            ('start', '<',  window_end),
        ], order='start asc')

        other_teachers = request.env['res.users'].sudo().search([
            ('id', '!=', request.env.user.id),
            ('group_ids', 'in', [request.env.ref(TEACHER_GROUP).id]),
        ])

        try:
            user_tz = pytz.timezone(request.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC

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

        window_subtitle = (_('Last %d') % days_back) + ' · ' + (_('next %d days') % days_forward)

        return request.render('fitness_teacher_swap.portal_my_classes', {
            'events_ctx':      events_ctx,
            'other_teachers':  other_teachers,
            'days_back':       days_back,
            'days_forward':    days_forward,
            'window_subtitle': window_subtitle,
            'error':           kw.get('error'),
            'success':         kw.get('success'),
        })

    @http.route('/my/teacher/classes/<int:event_id>', type='http', auth='user',
                website=True, sitemap=False)
    def class_roster(self, event_id, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        _ = request.env._
        event = request.env['calendar.event'].browse(event_id)

        if not event.exists() or event.user_id.id != request.env.user.id:
            return request.redirect(
                '/my/teacher/classes?error=' + quote(_('Class not found or not assigned to you.'))
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

    @http.route('/my/teacher/classes/<int:event_id>/mark', type='http', auth='user',
                methods=['POST'], website=True, sitemap=False)
    def mark_attendance(self, event_id, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        _ = request.env._
        roster_url = f'/my/teacher/classes/{event_id}'

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
                '/my/teacher/classes?error=' + quote(_('Class not found or not assigned to you.'))
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

    @http.route('/my/teacher/classes/<int:event_id>/reassign', type='http', auth='user',
                methods=['POST'], website=True, sitemap=False)
    def reassign(self, event_id, new_teacher_id=None, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        try:
            event = request.env['calendar.event'].browse(int(event_id))
            event.fitness_reassign_teacher(int(new_teacher_id))
        except Exception as exc:
            return request.redirect(f'/my/teacher/classes?error={quote(str(exc))}')
        return request.redirect('/my/teacher/classes')

    @http.route('/my/teacher/history', type='http', auth='user', website=True, sitemap=False)
    def my_class_history(self, **kw):
        if not request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        now = fields.Datetime.now()

        try:
            user_tz = pytz.timezone(request.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC

        past_events = request.env['calendar.event'].search([
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
            ('start', '<', now),
        ], order='start desc', limit=200)

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

        lang_code = (request.lang.code if request.lang else None) or 'en_US'
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
            'month_groups': month_groups,
        })
