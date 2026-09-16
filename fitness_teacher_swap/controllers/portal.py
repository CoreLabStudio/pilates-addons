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

# How far the calendar looks ahead. Month view needs a whole month whatever the
# chips say, and classes are only generated a few weeks out, so this just has
# to sit comfortably past that horizon rather than be unbounded.
CAL_WINDOW_DAYS = 120

# CoreLab teaches in one room in Madrid, so every screen in this app reads the
# studio's clock. The student portal and the notification emails were pinned to
# it; this module was not, and kept reading the account's own timezone - which
# is blank on most accounts and wrong on several. An instructor opening her
# roster from anywhere but Spain was shown the wrong hour for her own classes.
STUDIO_TZ = 'Europe/Madrid'


def _studio_tz():
    try:
        return pytz.timezone(STUDIO_TZ)
    except pytz.UnknownTimeZoneError:
        return pytz.UTC


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

        user_tz = _studio_tz()

        # Timezone-aware day boundaries for today/week filters
        now_local = pytz.UTC.localize(now).astimezone(user_tz)
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)

        if filter not in ('today', 'week', 'all'):
            filter = 'all'

        base_domain = [
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
            # A cancelled class is not on anybody's timetable. The student
            # views have filtered this out all along; this one never did, so a
            # closure day - the opening event on 16 September, for one - left
            # sixteen cancelled classes sitting on two instructors' screens
            # looking exactly like classes they were due to teach, reassign
            # button and roster included.
            ('class_state', '!=', 'cancelled'),
        ]
        domain = list(base_domain)
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

        # The chips answer "what am I teaching next"; the calendar answers
        # "what does my month look like", and it navigates itself - so it is
        # built from her whole timetable rather than from whichever chip is
        # active, or Month view under Today would show a single square.
        cal_events = request.env['calendar.event'].search(
            base_domain + [
                ('start', '>=', today_start_utc),
                ('start', '<',  today_start_utc + timedelta(days=CAL_WINDOW_DAYS)),
            ], order='start asc')

        # One query for the list and the calendar together. This was a
        # search_count per class, which on the All chip meant a round trip per
        # row; sharing it also means the two views of one class cannot
        # disagree about how many people are coming.
        counts = {}
        for event, count in request.env['fitness.booking']._read_group(
            [('calendar_event_id', 'in', (events | cal_events).ids),
             ('state', 'in', ('booked', 'attended', 'no_show'))],
            groupby=['calendar_event_id'], aggregates=['__count'],
        ):
            counts[event.id] = count

        events_ctx = []
        for ev in events:
            events_ctx.append({
                'event':       ev,
                'local_start': _format_local(ev.start, user_tz),
                'booked':      counts.get(ev.id, 0),
            })

        cal_days, cal_meta = request.env['fitness.calendar.grid'].build(
            cal_events, user_tz, now_local.date(),
            href_pattern='/my/instructor/classes/%d',
            counts=counts)

        return request.render('fitness_teacher_swap.portal_my_classes', {
            'events_ctx':     events_ctx,
            'other_teachers': other_teachers,
            'active_filter':  filter,
            'error':          kw.get('error'),
            'success':        kw.get('success'),
            # The same calendar the students have, given her own classes and
            # pointed at her roster instead of at the booking page.
            'calendar_days':  cal_days,
            'calendar_meta':  cal_meta,
            **request.env['fitness.calendar.grid'].labels(request.env._),
            # Supplied from here rather than written in the template, because
            # <option> and <select> are both on Odoo's inline list: their text
            # is folded into the parent's term instead of becoming a term of
            # its own, so the placeholder option was never extractable and sat
            # in English on a Catalan page. A Python string always extracts.
            'lbl_select_instructor': request.env._('Select instructor…'),
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
        # The list no longer offers cancelled classes, but the roster is a
        # plain URL and survives in history, a bookmark or a notification sent
        # before the cancellation. Marking attendance for a class that did not
        # happen is the thing worth refusing. The student side has guarded its
        # equivalent page all along.
        if event.class_state == 'cancelled':
            return request.redirect(
                '/my/instructor/classes?error=' + quote(_('This class has been cancelled.'))
            )

        # Search without sudo — teacher ir.rule scopes to own classes.
        # Re-browse with sudo so template can read student_id.name.
        booking_ids = request.env['fitness.booking'].search([
            ('calendar_event_id', '=', event_id),
            ('state', 'in', ('booked', 'attended', 'no_show')),
        ], order='student_id asc').ids
        bookings = request.env['fitness.booking'].sudo().browse(booking_ids)

        user_tz = _studio_tz()

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

        user_tz = _studio_tz()

        domain = [
            ('user_id', '=', request.env.user.id),
            ('is_fitness_class', '=', True),
            # "Past classes you have taught" - a cancelled one was not taught.
            ('class_state', '!=', 'cancelled'),
            ('start', '<', now),
        ]
        if cutoff_start:
            domain.append(('start', '>=', cutoff_start))
        if cutoff_end:
            domain.append(('start', '<', cutoff_end))

        # Build available months from all past events (no cutoff)
        all_events_for_months = request.env['calendar.event'].search([
            ('class_state', '!=', 'cancelled'),
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

        # Two counts per class, read in two queries rather than two per row.
        # This was a search_count pair inside the loop: a full 200-class page
        # issued 400 queries to render a number beside each line.
        attended_by_event = {}
        total_by_event = {}
        if past_events:
            Booking = request.env['fitness.booking']
            for event, count in Booking._read_group(
                [('calendar_event_id', 'in', past_events.ids),
                 ('state', '=', 'attended')],
                groupby=['calendar_event_id'], aggregates=['__count'],
            ):
                attended_by_event[event.id] = count
            for event, count in Booking._read_group(
                [('calendar_event_id', 'in', past_events.ids),
                 ('state', 'in', ('booked', 'attended', 'no_show'))],
                groupby=['calendar_event_id'], aggregates=['__count'],
            ):
                total_by_event[event.id] = count

        events_ctx = []
        for ev in past_events:
            events_ctx.append({
                'event':       ev,
                'local_start': _format_local(ev.start, user_tz),
                'attended':    attended_by_event.get(ev.id, 0),
                'total':       total_by_event.get(ev.id, 0),
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

    @http.route('/my/profile/swap-history', type='http', auth='user',
                website=True, sitemap=False)
    def my_swap_history(self, **kw):
        """An instructor's own swap history, reached from Profile.

        Every swap was already recorded - the admin reads them in Cambios de
        Instructor - but an instructor had no way to see their own. That is the
        one person who most needs it: which of their classes somebody else took
        and which they picked up, so a disagreement about who was meant to be
        in the room is settled by a record rather than by memory.

        One list, newest swap first, as asked. The page used to split the rows
        into "handed over" and "taken on", which answers a different question -
        where a class went - and cannot be read as a chronology. The direction
        is now a column instead of a heading, so nothing is lost and the order
        is the order things happened in.

        Note on the columns: a swap record is one class changing hands between
        two instructors. There is no second class, so there is no "swapped-to
        class" to show; the counterpart of the class is the other instructor,
        and that is what the direction column carries.
        """
        user = request.env.user
        if not user.has_group(TEACHER_GROUP):
            return request.redirect('/my')

        user_tz = _studio_tz()

        # sudo: a swap names two instructors, and the other one is the whole
        # point of the record. Read is scoped to rows this user is a party to
        # by the domain itself, so this widens nothing else.
        # Newest first means newest *swap*, not newest class: the column the
        # page is ordered by has to be the one it shows as "Swapped on", or the
        # order looks arbitrary to anyone reading down it.
        swaps = request.env['fitness.teacher.swap'].sudo().search([
            '|',
            ('original_teacher_id', '=', user.id),
            ('new_teacher_id', '=', user.id),
        ], order='create_date desc, id desc', limit=300)

        source_labels = dict(
            request.env['fitness.teacher.swap']._fields['initiated_by'].selection)

        now = fields.Datetime.now()
        _ = request.env._

        def row(sw):
            mine_was_given = sw.original_teacher_id.id == user.id
            other = sw.new_teacher_id if mine_was_given else sw.original_teacher_id
            past = bool(sw.class_start and sw.class_start < now)
            return {
                'id': sw.id,
                'class_name': sw.class_name or (sw.class_type_id.name or ''),
                'when': (_format_local(sw.class_start, user_tz)
                         or _('Date not recorded')),
                'logged': _format_local(sw.create_date, user_tz),
                'other': other.name or _('Unknown'),
                'direction': 'given' if mine_was_given else 'taken',
                'direction_label': _('Handed over to') if mine_was_given
                                   else _('Taken on from'),
                'reason': (sw.reason or '').strip(),
                'source': source_labels.get(sw.initiated_by, sw.initiated_by or ''),
                'event_id': sw.calendar_event_id.id if sw.calendar_event_id else 0,
                # A swap of a class that has already happened is history; one
                # still ahead is something the instructor may need to act on.
                'past': past,
                'status': _('Completed') if past else _('Scheduled'),
            }

        rows = [row(s) for s in swaps]

        return request.render('fitness_teacher_swap.portal_teacher_swaps', {
            'rows': rows,
            'total': len(rows),
        })

    @http.route('/my/instructor/swaps', type='http', auth='user', website=True,
                sitemap=False)
    def _legacy_swaps(self, **kw):
        """The page moved under Profile; this URL is in sent notifications."""
        return request.redirect('/my/profile/swap-history', code=301)

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
