import base64
import binascii
import json
import logging
from datetime import timedelta, datetime as _dt_cls, date as _date_cls
from dateutil.relativedelta import relativedelta as _relativedelta
from itertools import groupby as _groupby
from urllib.parse import urlencode

_logger = logging.getLogger(__name__)

import pytz

try:
    from babel.dates import (
        format_date as _babel_format_date,
        format_datetime as _babel_format_datetime,
    )
    _BABEL_OK = True
except Exception:
    _BABEL_OK = False

from odoo import http, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

try:
    from odoo.addons.payment.controllers.portal import PaymentPortal as _OdooPaymentPortal
    _PAYMENT_OK = True
except Exception:
    _OdooPaymentPortal = http.Controller
    _PAYMENT_OK = False

STUDENT_GROUP = 'fitness_core.group_fitness_student'
TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
LOOK_AHEAD_DAYS = 14
# The Available list defaults to a week; 14 stays reachable from the chips.
DEFAULT_LOOK_AHEAD_DAYS = 7
RANGE_CHOICES = (1, 7, 14)
SCHEDULE_LOOK_AHEAD_DAYS = 28

# Mirror of constants in fitness_subscriptions.models.sale_order
_PROMO_WINDOW_START = _date_cls(2026, 9, 1)
_PROMO_WINDOW_END   = _date_cls(2026, 11, 30)

# Placeholder payment details. The studio replaces these from
# Settings → Technical → System Parameters without touching code.
PAYMENT_PARAM_DEFAULTS = {
    'fitness_portal.bizum_phone': '+34 600 000 000',
    'fitness_portal.bank_iban': 'ES00 0000 0000 0000 0000 0000',
    'fitness_portal.bank_holder': 'CoreLab Studio',
}

PAYMENT_METHODS = ('bizum', 'transfer')


class FitnessStudentPortal(http.Controller):

    # ── /my/account redirect ─────────────────────────────────
    # Odoo's standard account-details page is unstyled in our custom
    # portal. Send it to the Profile Hub which handles all account info.
    @http.route('/my/account', type='http', auth='user', website=True, sitemap=False)
    def account_redirect(self, **kw):
        return request.redirect('/my')

    # ══════════════════════════════════════════════════════════
    #  ABOUT CORELAB  (/my/about)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/about', type='http', auth='user', website=True, sitemap=False)
    def portal_about(self, **kw):
        is_teacher = request.env.user.has_group(TEACHER_GROUP)
        return request.render('fitness_portal.portal_about_corelab', {
            'is_teacher': is_teacher,
        })

    # ══════════════════════════════════════════════════════════
    #  HOME  (post-login landing page, bottom-nav tab 1)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/home', type='http', auth='user', website=True, sitemap=False)
    def portal_home(self, **kw):
        if request.env.user.has_group(TEACHER_GROUP):
            return request.redirect('/my/instructor/classes')
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        now = fields.Datetime.now()

        upcoming = request.env['fitness.booking'].search([
            ('student_id', '=', partner.id),
            ('state', '=', 'booked'),
            ('class_start', '>', now),
        ], order='class_start asc')

        has_any_bookings = bool(request.env['fitness.booking'].search_count([
            ('student_id', '=', partner.id),
        ]))

        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        if has_any_bookings:
            welcome = (_('Welcome back, %s') % student_name) if student_name else _('Welcome back')
        else:
            welcome = (_('Welcome, %s') % student_name) if student_name else _('Welcome')

        n = len(upcoming)
        if n == 0:
            schedule_hint = _('Nothing booked yet')
        elif n == 1:
            schedule_hint = _('%d class booked') % n
        else:
            schedule_hint = _('%d classes booked') % n

        news_posts = request.env['fitness.news.post'].search(
            [], order='sequence asc, publish_date desc, id desc', limit=3
        )

        credit_pools = self._credit_pools(partner.id)

        # Prompts for shop categories the student owns nothing in. Independent
        # of Next up, which is about booking with what you already have; this is
        # about not owning anything in the first place. Each tile links to the
        # tab that sells that category.
        missing = partner._fitness_missing_purchases()
        # Owns nothing in any category: the hero's "Book a Class" would drop
        # them into an empty calendar, so it points at the shop instead.
        has_no_purchases = all(missing.values())
        purchase_prompts = [p for p in (
            {'key': 'membership', 'show': missing['membership'],
             'label': _('Membership'), 'status': _('No active membership'),
             'cta': _('View plans'), 'href': '/my/packages?tab=subscriptions'},
            {'key': 'package', 'show': missing['package'],
             'label': _('Class packages'), 'status': _('Discover our packages'),
             'cta': _('Buy'), 'href': '/my/packages?tab=packages'},
            {'key': 'class', 'show': missing['class'],
             'label': _('Classes'), 'status': _('No active class'),
             'cta': _('View classes'), 'href': '/my/packages?tab=classes'},
        ) if p['show']]
        # Membership and packages sit side by side; the class tile spans
        # the row underneath. Split here rather than in QWeb so the
        # template stays free of list comprehensions.
        prompt_pair = [p for p in purchase_prompts if p['key'] != 'class']
        prompt_wide = [p for p in purchase_prompts if p['key'] == 'class']
        return request.render('fitness_portal.portal_student_home', {
            'welcome':          welcome,
            'student_name':     student_name,
            'upcoming_count':   n,
            'next_booking':     upcoming[:1],
            'schedule_hint':    schedule_hint,
            'primary_credit':   credit_pools[0] if credit_pools else None,
            'credit_pools':     credit_pools,
            'purchase_prompts': purchase_prompts,
            'prompt_pair':      prompt_pair,
            'prompt_wide':      prompt_wide,
            'has_any_bookings': has_any_bookings,
            'has_no_purchases': has_no_purchases,
            'lbl_choose_plan':  _('Start by choosing your plan.'),
            'lbl_explore_shop': _('Explore packages, memberships & classes'),
            'news_posts':       news_posts,
            'lbl_lets_book':    _("Let's book your first class."),
        })

    # ══════════════════════════════════════════════════════════
    #  STUDIO  (bottom-nav tab 2 — "Available" | "My Schedule")
    # ══════════════════════════════════════════════════════════

    @http.route('/my/studio', type='http', auth='user', website=True, sitemap=False)
    def studio(self, view=None, booked=None, cancelled=None, credit_returned=None,
               error=None, days=None, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        active_view = 'schedule' if view == 'schedule' else 'available'

        values = {
            'active_view':     active_view,
            'booked':          bool(booked),
            'cancelled':       bool(cancelled),
            'credit_returned': bool(credit_returned),
            'error_msg':       error or None,
            'primary_credit':  self._primary_credit(partner.id),
        }
        full_name = partner.name or ''
        values['student_name'] = full_name.split()[0] if full_name else full_name

        values['timeframe_labels'] = {
            'week':  _('This week'),
            'today': _('Today'),
            'month': _('This month'),
        }

        if active_view == 'schedule':
            values.update(self._schedule_values(partner))
        else:
            values.update(self._available_values(partner, days))

        return request.render('fitness_portal.portal_student_studio', values)

    def _available_values(self, partner, days=None):
        """Day-grouped list of bookable classes (the 'Available' view).

        The window defaults to a week. Loading the full fourteen days put
        every class in the DOM at once, which on a phone meant a page tens
        of thousands of pixels tall before the student saw anything useful.
        """
        _ = request.env._
        lang = request.env.lang or 'en_US'
        now = fields.Datetime.now()

        try:
            sel_days = int(days)
        except (TypeError, ValueError):
            sel_days = DEFAULT_LOOK_AHEAD_DAYS
        if sel_days not in RANGE_CHOICES:
            sel_days = DEFAULT_LOOK_AHEAD_DAYS
        window_end = now + timedelta(days=sel_days)

        eligible_types = self._eligible_class_types(partner.id)

        non_rebookable_ids = set(
            request.env['fitness.booking'].search([
                ('student_id', '=', partner.id),
                ('state', 'in', ('booked', 'no_show')),
                ('class_start', '>', now),
            ]).mapped('calendar_event_id.id')
        )

        all_events = request.env['calendar.event'].sudo().search([
            ('is_fitness_class', '=', True),
            ('class_state', '!=', 'cancelled'),
            ('start', '>', now),
            ('start', '<', window_end),
        ], order='start asc')

        events = all_events.filtered(
            lambda e: (
                e.id not in non_rebookable_ids
                and self._has_seats(e)
                and self._discipline_matches(e, eligible_types)
            )
        )

        user_tz = self._user_tz()
        today_local = pytz.UTC.localize(now).astimezone(user_tz).date()
        tomorrow_local = today_local + timedelta(days=1)

        # Pre-load type and category image flags in one batch read to avoid
        # the QWeb safe_eval restriction that blocks binary field lazy-loads.
        class_types = events.mapped('class_type_id').sudo()
        ct_image_map = {}
        cat_of_ct = {}
        if class_types:
            for row in class_types.read(['id', 'image_1920', 'category_id']):
                ct_image_map[row['id']] = bool(row['image_1920'])
                cat_of_ct[row['id']] = row['category_id'][0] if row['category_id'] else False
        categories = class_types.mapped('category_id').sudo()
        cat_image_map = {}
        if categories:
            for row in categories.read(['id', 'image_1920']):
                cat_image_map[row['id']] = bool(row['image_1920'])

        grouped_events = []
        _current_date = None
        _current_items = []
        for ev in events:
            local_dt = pytz.UTC.localize(ev.start).astimezone(user_tz)
            ev_date = local_dt.date()
            if ev_date != _current_date:
                if _current_items:
                    grouped_events.append((
                        _current_date,
                        _day_label(_current_date, today_local, tomorrow_local, _, lang),
                        _current_items,
                    ))
                _current_date = ev_date
                _current_items = []
            seats_v = (ev.capacity - ev.booked_seats) if ev.capacity else None
            if seats_v is not None and 1 <= seats_v <= 2:
                seats_label = (_('%d spot left') % seats_v) if seats_v == 1 else (_('%d spots left') % seats_v)
            else:
                seats_label = None
            ct_id = ev.class_type_id.id if ev.class_type_id else False
            cat_id = cat_of_ct.get(ct_id, False)
            _current_items.append({
                'event':        ev,
                'local_time':   local_dt.strftime('%H:%M'),
                'seats_v':      seats_v,
                'seats_label':  seats_label,
                'type_has_img': ct_image_map.get(ct_id, False),
                'cat_id':       cat_id,
                'cat_has_img':  cat_image_map.get(cat_id, False),
            })
        if _current_items:
            grouped_events.append((
                _current_date,
                _day_label(_current_date, today_local, tomorrow_local, _, lang),
                _current_items,
            ))

        n = len(events)
        if grouped_events:
            subtitle = (_('%d class available') % n) if n == 1 else (_('%d classes available') % n)
        else:
            subtitle = _('Ready to book a class?')

        # Studio discipline filter chips — only shown when >1 type is present
        ct_types = {(ev.class_type_id.classroom_type or '') for ev in events if ev.class_type_id}
        if len(ct_types) > 1:
            stable = [t for t in ('barre', 'reformer', 'any', '') if t in ct_types]
            studio_chips = [{'key': 'all', 'label': _('All')}] + [
                {'key': t, 'label': self._discipline_label(t)} for t in stable
            ]
        else:
            studio_chips = []

        return {
            'events':          events,
            'grouped_events':  grouped_events,
            'has_sources':     bool(eligible_types),
            'look_ahead_days': sel_days,
            'sel_days':        sel_days,
            'range_chips':     [
                {'days': 1,  'label': _('Today')},
                {'days': 7,  'label': _('This week')},
                {'days': 14, 'label': _('Next 14 days')},
            ],
            'today_local':     today_local,
            'subtitle':        subtitle,
            'empty_state':     _('No classes available in the next %d days for your plan. Check back soon!') % sel_days,
            'no_sources_msg':  _('Time to move! Pick a membership, package, or class and reserve your spot.'),
            'no_sources_cta':  _('See options'),
            'studio_chips':    studio_chips,
        }

    def _schedule_values(self, partner):
        """Day-grouped list of the student's upcoming bookings ('My Schedule')."""
        _ = request.env._
        # Same signal the Classes view uses (see _classes_values), deliberately:
        # _fitness_missing_purchases() answers "owns a category", which stays true
        # for a single class already spent, so My Schedule invited a student with
        # nothing left to book to go and book. _eligible_class_types() answers
        # "can book something right now" - it counts running memberships and only
        # unexpired package lines with credits remaining.
        has_sources = bool(self._eligible_class_types(partner.id))
        lang = request.env.lang or 'en_US'
        now = fields.Datetime.now()

        ICP = request.env['ir.config_parameter'].sudo()
        look_ahead = int(ICP.get_param(
            'fitness_portal.schedule_look_ahead_days', SCHEDULE_LOOK_AHEAD_DAYS
        ))
        window_end = now + timedelta(days=look_ahead)

        bookings = request.env['fitness.booking'].search([
            ('student_id', '=', partner.id),
            ('state', '=', 'booked'),
            ('class_start', '>', now),
            ('class_start', '<', window_end),
        ], order='class_start asc')

        user_tz = self._user_tz()
        today_local = pytz.UTC.localize(now).astimezone(user_tz).date()
        tomorrow_local = today_local + timedelta(days=1)

        grouped = []
        current_date = None
        current_group = []
        for booking in bookings:
            local_dt = pytz.UTC.localize(booking.class_start).astimezone(user_tz)
            local_date = local_dt.date()
            if local_date != current_date:
                if current_date is not None:
                    grouped.append((current_date, _day_label(current_date, today_local, tomorrow_local, _, lang), current_group))
                current_date = local_date
                current_group = []
            current_group.append(booking)
        if current_date is not None:
            grouped.append((current_date, _day_label(current_date, today_local, tomorrow_local, _, lang), current_group))

        # Studio discipline filter chips — only shown when >1 type is present
        bk_types = {(b.class_type_id.classroom_type or '') for b in bookings if b.class_type_id}
        if len(bk_types) > 1:
            stable = [t for t in ('barre', 'reformer', 'any', '') if t in bk_types]
            sched_studio_chips = [{'key': 'all', 'label': _('All')}] + [
                {'key': t, 'label': self._discipline_label(t)} for t in stable
            ]
        else:
            sched_studio_chips = []

        return {
            'grouped_bookings':  grouped,
            'has_sources':       has_sources,
            'no_sources_msg':    _('Time to move! Pick a membership, package, or class and reserve your spot.'),
            'no_sources_cta':    _('See options'),
            'look_ahead_days':   look_ahead,
            'subtitle':          _('Next %d days') % look_ahead,
            'schedule_empty':    _('No upcoming classes in the next %d days.') % look_ahead,
            'studio_chips':      sched_studio_chips,
        }

    # Legacy routes — kept so old bookmarks, emails and browser history
    # continue to land on the right place instead of 404-ing.
    @http.route('/my/classes', type='http', auth='user', website=True, sitemap=False)
    def available_classes(self, **kw):
        qs = urlencode({k: v for k, v in kw.items() if v})
        return request.redirect('/my/studio' + (('?' + qs) if qs else ''))

    @http.route('/my/schedule', type='http', auth='user', website=True, sitemap=False)
    def my_schedule(self, **kw):
        return request.redirect('/my/studio?view=schedule')

    # ══════════════════════════════════════════════════════════
    #  CLASS DETAIL + BOOK / CANCEL
    # ══════════════════════════════════════════════════════════

    @http.route('/my/classes/<int:event_id>', type='http', auth='user',
                website=True, sitemap=False, methods=['GET'])
    def class_detail(self, event_id, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        partner = request.env.user.partner_id
        now = fields.Datetime.now()

        event = request.env['calendar.event'].sudo().browse(event_id)
        if not event.exists() or not event.is_fitness_class:
            return request.redirect('/my/studio')

        # Check if student already has a live booking for this event
        existing = request.env['fitness.booking'].search([
            ('student_id', '=', partner.id),
            ('calendar_event_id', '=', event_id),
            ('state', 'in', ('booked', 'no_show')),
        ], limit=1)

        eligible_types = self._eligible_class_types(partner.id)
        discipline_ok = self._discipline_matches(event, eligible_types)
        seats_left = max(0, event.capacity - event.booked_seats) if event.capacity else None
        can_book = (
            not existing
            and bool(eligible_types)
            and discipline_ok
            and (seats_left is None or seats_left > 0)
            and event.start > now
        )

        user_tz = self._user_tz()
        local_start = pytz.UTC.localize(event.start).astimezone(user_tz)
        local_stop = pytz.UTC.localize(event.stop).astimezone(user_tz)

        _ = request.env._
        lang = request.env.lang or 'en_US'

        if _BABEL_OK:
            try:
                local_date_label = _babel_format_date(
                    local_start.date(), format='EEEE, d MMMM', locale=lang,
                ).capitalize()
            except Exception:
                local_date_label = local_start.strftime('%A, %d %B')
        else:
            local_date_label = local_start.strftime('%A, %d %B')

        if seats_left is None:
            seats_status_label = None
        elif seats_left == 0:
            seats_status_label = _('Class is full')
        elif seats_left == 1:
            seats_status_label = _('Only %d spot left') % seats_left
        elif seats_left <= 2:
            seats_status_label = _('Only %d spots left') % seats_left
        else:
            seats_status_label = _('%d spots available') % seats_left

        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        # Pre-load image flags for the 4-tier fallback (binary fields not accessible via QWeb safe_eval)
        ct = event.class_type_id.sudo()
        type_has_img = False
        cat_id = False
        cat_has_img = False
        if ct:
            ct_row = ct.read(['id', 'image_1920', 'category_id'])[0]
            type_has_img = bool(ct_row.get('image_1920'))
            cat_ref = ct_row.get('category_id')
            if cat_ref:
                cat_id = cat_ref[0]
                cat_row = ct.env['fitness.class.category'].sudo().browse(cat_id).read(['image_1920'])[0]
                cat_has_img = bool(cat_row.get('image_1920'))

        return request.render('fitness_portal.portal_student_class_detail', {
            'event':               event,
            'can_book':            can_book,
            'already_booked':      bool(existing),
            'seats_left':          seats_left,
            'seats_status_label':  seats_status_label,
            'local_start':         local_start,
            'local_stop':          local_stop,
            'local_date_label':    local_date_label,
            'primary_credit':      self._primary_credit(partner.id),
            'student_name':        student_name,
            'booked':              bool(kw.get('booked')),
            'error_msg':           kw.get('error') or None,
            'type_has_img':        type_has_img,
            'cat_id':              cat_id,
            'cat_has_img':         cat_has_img,
        })

    @http.route('/my/classes/<int:event_id>/book', type='http',
                auth='user', website=True, sitemap=False, methods=['POST'])
    def book_class(self, event_id, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        partner = request.env.user.partner_id
        event = request.env['calendar.event'].sudo().browse(event_id)
        if not event.exists() or not event.is_fitness_class:
            qs = urlencode({'error': request.env._('Class not found.')})
            return request.redirect(f'/my/studio?{qs}')
        if event.class_state == 'cancelled':
            qs = urlencode({'error': request.env._(
                'This class has been cancelled and can no longer be booked.')})
            return request.redirect(f'/my/studio?{qs}')

        try:
            request.env['fitness.booking'].create({
                'student_id': partner.id,
                'calendar_event_id': event_id,
            })
        except (UserError, ValidationError) as exc:
            qs = urlencode({'error': str(exc)})
            return request.redirect(f'/my/studio?{qs}')

        return request.redirect('/my/studio?booked=1')

    @http.route('/my/classes/<int:booking_id>/cancel', type='http',
                auth='user', website=True, sitemap=False, methods=['POST'])
    def cancel_booking(self, booking_id, next=None, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        booking = request.env['fitness.booking'].browse(booking_id)

        # Cancel buttons live on both Studio views; come back to the one used.
        base = '/my/studio?view=schedule' if next == 'schedule' else '/my/studio?'
        base = base if base.endswith('?') else base + '&'

        if not booking.exists() or booking.student_id != partner:
            qs = urlencode({'error': _('Booking not found or does not belong to your account.')})
            return request.redirect(f'{base}{qs}')

        try:
            booking.action_cancel()
        except (UserError, ValidationError) as exc:
            msg = str(exc)
            if 'less than 2 hours' in msg or 'within 2 hours' in msg:
                msg = _(
                    "This class starts in less than 2 hours and can no longer "
                    "be cancelled online. Please contact the studio."
                )
            qs = urlencode({'error': msg})
            return request.redirect(f'{base}{qs}')

        if booking.credit_returned:
            return request.redirect(f'{base}cancelled=1&credit_returned=1')
        return request.redirect(f'{base}cancelled=1')

    # ══════════════════════════════════════════════════════════
    #  HISTORY  (sub-page of Profile → My Classes)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/history', type='http', auth='user', website=True, sitemap=False)
    def my_history(self, period=None, **kw):
        import re as _re
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        partner = request.env.user.partner_id
        now = fields.Datetime.now()
        today = fields.Date.context_today(request.env.user)
        lang_code = (request.lang.code if request.lang else None) or 'en_US'

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

        booking_domain = [
            ('student_id', '=', partner.id),
            '|',
            ('class_start', '<', now),
            ('state', 'in', ['no_show', 'cancelled']),
        ]
        if cutoff_start:
            booking_domain.append(('class_start', '>=', cutoff_start))
        if cutoff_end:
            booking_domain.append(('class_start', '<', cutoff_end))

        # Build available months from all bookings (no cutoff) for the picker
        all_month_keys = sorted({
            b.class_start.strftime('%Y-%m')
            for b in request.env['fitness.booking'].search([
                ('student_id', '=', partner.id),
                ('class_start', '!=', False),
            ], order='class_start desc', limit=500)
            if b.class_start
        }, reverse=True)
        available_months = []
        for mk in all_month_keys:
            try:
                dt = _dt_cls.strptime(mk + '-01', '%Y-%m-%d')
                lbl = _babel_format_date(dt, format='MMMM yyyy', locale=lang_code) if _BABEL_OK else mk
            except Exception:
                lbl = mk
            available_months.append({'key': mk, 'label': lbl})

        past_bookings = request.env['fitness.booking'].search(
            booking_domain, order='class_start desc', limit=200)

        orders = request.env['sale.order'].search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'sale'),
            '|',
            ('is_subscription', '=', True),
            ('fitness_is_package', '=', True),
        ], order='date_order desc')

        subscriptions = orders.filtered(lambda o: o.is_subscription)

        packs = []
        for order in orders.filtered(lambda o: o.fitness_is_package):
            pack_line = order.order_line.filtered(
                lambda l: l.fitness_original_class_count > 0
            )[:1]
            if pack_line:
                validity_end = pack_line.fitness_validity_end_date
                is_expired = (
                    (validity_end and validity_end < today)
                    or pack_line.fitness_remaining_classes <= 0
                )
                if is_expired:
                    continue
                packs.append({
                    'order':      order,
                    'line':       pack_line,
                    'is_expired': is_expired,
                })

        _ = request.env._
        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        month_groups = []
        for month_key, items in _groupby(
            past_bookings,
            key=lambda b: b.class_start.strftime('%Y-%m') if b.class_start else 'unknown'
        ):
            entries = list(items)
            try:
                dt = _dt_cls.strptime(month_key + '-01', '%Y-%m-%d')
                label = _babel_format_date(dt, format='MMMM yyyy', locale=lang_code) if _BABEL_OK else month_key
            except Exception:
                label = month_key
            month_groups.append({'key': month_key, 'label': label, 'entries': entries})

        return request.render('fitness_portal.portal_student_history', {
            'month_groups':      month_groups,
            'subscriptions':     subscriptions,
            'packs':             packs,
            'primary_credit':    self._primary_credit(partner.id),
            'student_name':      student_name,
            'filter_period':     period,
            'available_months':  available_months,
            'lbl_enrolled':      _('Enrolled'),
            'lbl_next_billing':  _('Next billing'),
            'lbl_bonus_credits': _('Bonus credits'),
            'lbl_purchased':     _('Purchased'),
            'lbl_remaining':     _('Remaining'),
            'lbl_valid_until':   _('Valid until'),
        })

    # ══════════════════════════════════════════════════════════
    #  CREDIT HISTORY  (ledger — every credit-affecting event)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/credits', type='http', auth='user', website=True, sitemap=False)
    def credit_history(self, period=None, **kw):
        import re as _re
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        lang_code = (request.lang.code if request.lang else None) or 'en_US'
        all_entries = self._credit_ledger(partner)

        # Validate and apply period filter
        if period and _re.match(r'^\d{4}-\d{2}$', period):
            filtered = [e for e in all_entries
                        if e.get('when') and hasattr(e['when'], 'strftime')
                        and e['when'].strftime('%Y-%m') == period]
        else:
            period = 'all'
            filtered = all_entries

        # Build month picker from full (unfiltered) history
        months_seen = {}
        for e in all_entries:
            when = e.get('when')
            if when and hasattr(when, 'strftime'):
                mk = when.strftime('%Y-%m')
                if mk not in months_seen:
                    try:
                        dt = _dt_cls.strptime(mk + '-01', '%Y-%m-%d')
                        lbl = _babel_format_date(dt, format='MMMM yyyy', locale=lang_code) if _BABEL_OK else mk
                    except Exception:
                        lbl = mk
                    months_seen[mk] = lbl
        available_months = [{'key': k, 'label': v}
                            for k, v in sorted(months_seen.items(), reverse=True)]

        # Group filtered entries by month for display
        mg_dict = {}
        for e in filtered:
            when = e.get('when')
            if when and hasattr(when, 'strftime'):
                mk = when.strftime('%Y-%m')
                if mk not in mg_dict:
                    try:
                        dt = _dt_cls.strptime(mk + '-01', '%Y-%m-%d')
                        lbl = _babel_format_date(dt, format='MMMM yyyy', locale=lang_code) if _BABEL_OK else mk
                    except Exception:
                        lbl = mk
                    mg_dict[mk] = {'label': lbl, 'key': mk, 'entries': []}
                mg_dict[mk]['entries'].append(e)
        month_groups = [v for _, v in sorted(mg_dict.items(), reverse=True)]

        # Localise each entry's timestamp into the user's timezone + locale
        user_tz = self._user_tz()
        for e in all_entries:
            raw = e.get('when')
            if raw and hasattr(raw, 'tzinfo'):
                try:
                    if raw.tzinfo is None:
                        aware = pytz.utc.localize(raw)
                    else:
                        aware = raw
                    local_dt = aware.astimezone(user_tz)
                    if _BABEL_OK:
                        e['when_str'] = _babel_format_datetime(
                            local_dt,
                            format='d MMM yyyy · HH:mm',
                            locale=lang_code,
                        )
                    else:
                        e['when_str'] = local_dt.strftime('%d %b %Y · %H:%M')
                except Exception:
                    e['when_str'] = str(raw)
            else:
                e['when_str'] = str(raw) if raw else ''

        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        return request.render('fitness_portal.portal_credit_history', {
            'entries':            filtered,
            'month_groups':       month_groups,
            'available_months':   available_months,
            'filter_period':      period,
            'current_total':      all_entries[0]['balance'] if all_entries else self._credit_total(partner),
            'primary_credit':     self._primary_credit(partner.id),
            'student_name':       student_name,
            'ledger_empty':       _('No credit activity yet. Buy a package to get started.'),
            'label_credits_page': _('Balance'),
            'label_credits_sub':  _('All changes to your credits'),
        })

    def _credit_total(self, partner):
        """Credits the student can book with right now. See res.partner."""
        return partner.sudo()._fitness_credit_total()

    def _credit_ledger(self, partner):
        """Chronological ledger of every event that moved the credit count.

        Sources are the models that already record the movements — no new
        bookkeeping model is introduced:
          * sale.order.line (class packs)  → purchase, expiry
          * sale.order       (subscriptions) → promo floating credits
          * fitness.booking                → spend, refund, no-show

        The running balance is anchored on the live credit total and walked
        backwards, so the newest row always shows the real current balance
        even when a student's records predate this page.
        """
        _ = request.env._
        today = fields.Date.context_today(request.env.user)
        events = []

        # ── Class-pack purchases and expiries ────────────────────────
        pack_lines = request.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_original_class_count', '>', 0),
        ])
        for line in pack_lines:
            order = line.order_id
            when = order.date_order or fields.Datetime.now()
            events.append({
                'when':  when,
                'delta': line.fitness_original_class_count,
                'kind':  'purchase',
                'title': line.product_id.name or _('Class pack'),
                'meta':  _('Package purchased · %s') % (order.name or ''),
            })
            vend = line.fitness_validity_end_date
            if vend and vend < today and line.fitness_remaining_classes > 0:
                events.append({
                    'when':  _dt_cls.combine(vend, _dt_cls.min.time()),
                    'delta': -line.fitness_remaining_classes,
                    'kind':  'expiry',
                    'title': line.product_id.name or _('Class pack'),
                    'meta':  _('Credits expired'),
                })

        # ── Subscription started + promo bonus (separate lines) ──────
        subs = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('fitness_subscription_product_id', '!=', False),
        ])
        for sub in subs:
            product = sub.fitness_subscription_product_id
            bonus = product.fitness_promo_first_cycle_bonus or 0
            sub_date = sub.date_order.date() if sub.date_order else None
            is_cf = bool(getattr(product, 'fitness_is_clase_fija', False))
            is_rm = bool(getattr(product, 'fitness_is_reformer_mensual', False))
            in_promo = sub_date is not None and _PROMO_WINDOW_START <= sub_date <= _PROMO_WINDOW_END
            cf_promo = is_cf and in_promo
            rm_promo = is_rm and in_promo
            effective_bonus = 1 if (cf_promo or rm_promo) else bonus

            # Subscription started (always neutral, no delta)
            events.append({
                'when':  sub.date_order or fields.Datetime.now(),
                'delta': 0,
                'kind':  'neutral',
                'title': product.name or _('Subscription'),
                'meta':  _('Subscription started · %s') % (sub.name or ''),
            })
            # Opening promo bonus — shown as a distinct credit line
            if effective_bonus:
                events.append({
                    'when':  sub.date_order or fields.Datetime.now(),
                    'delta': effective_bonus,
                    'kind':  'purchase',
                    'title': _('Opening promo bonus'),
                    'meta':  _('+%d class') % effective_bonus,
                })

        # ── Bookings, cancellations and no-shows ─────────────────────
        bookings = request.env['fitness.booking'].search([
            ('student_id', '=', partner.id),
        ])
        for booking in bookings:
            name = booking.calendar_event_id.name or _('Class')
            paid_with_credit = bool(
                booking.package_order_line_id or booking.fitness_used_floating_credit
            )
            if booking.state == 'cancelled':
                if booking.credit_returned:
                    events.append({
                        'when':  booking.cancellation_date or booking.booking_date,
                        'delta': 1,
                        'kind':  'refund',
                        'title': name,
                        'meta':  _('Booking cancelled · credit returned'),
                    })
                else:
                    events.append({
                        'when':  booking.cancellation_date or booking.booking_date,
                        'delta': 0,
                        'kind':  'neutral',
                        'title': name,
                        'meta':  _('Booking cancelled · no credit returned'),
                    })
                # The original spend still happened — record it too.
                if paid_with_credit:
                    events.append({
                        'when':  booking.booking_date,
                        'delta': -1,
                        'kind':  'spend',
                        'title': name,
                        'meta':  _('Class booked'),
                    })
            elif booking.state == 'no_show':
                events.append({
                    'when':  booking.class_start or booking.booking_date,
                    'delta': 0,
                    'kind':  'neutral',
                    'title': name,
                    'meta':  _('No-show · credit not returned'),
                })
                if paid_with_credit:
                    events.append({
                        'when':  booking.booking_date,
                        'delta': -1,
                        'kind':  'spend',
                        'title': name,
                        'meta':  _('Class booked'),
                    })
            else:
                events.append({
                    'when':  booking.booking_date,
                    'delta': -1 if paid_with_credit else 0,
                    'kind':  'spend' if paid_with_credit else 'neutral',
                    'title': name,
                    'meta':  _('Class booked') if paid_with_credit
                             else _('Class booked · covered by subscription'),
                })

        events = [e for e in events if e['when']]
        events.sort(key=lambda e: e['when'])

        # Anchor the running balance on the live total so the top row is
        # always the number the rest of the app shows.
        balance = self._credit_total(partner) - sum(e['delta'] for e in events)
        for event in events:
            balance += event['delta']
            event['balance'] = balance

        events.reverse()  # newest first for display
        return events

    # ══════════════════════════════════════════════════════════
    #  PACKAGES & SUBSCRIPTIONS  (bottom-nav tab 3)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/packages', type='http', auth='user', website=True, sitemap=False)
    def packages_list(self, tab=None, discipline=None, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        active_tab = ('subscriptions' if tab == 'subscriptions'
                      else 'classes' if tab == 'classes'
                      else 'packages')
        # Pre-select a discipline chip so a link can land on Reformer only.
        # The chips already filter client-side and corelab.js applies whichever
        # one carries mv-active on load, so marking it server-side is the whole
        # mechanism - nothing new to filter, just a different starting chip.
        active_chip = discipline if discipline in ('barre', 'reformer', 'any') else 'all'

        if active_tab == 'subscriptions':
            domain = [('fitness_is_subscription_plan', '=', True)]
        elif active_tab == 'classes':
            domain = [('fitness_is_package', '=', True), ('fitness_class_count', '<=', 1)]
        else:
            domain = [('fitness_is_package', '=', True), ('fitness_class_count', '>', 1)]

        if active_tab == 'classes':
            # Include sale_ok=False (Privadas/Duo) — they show as contact-only
            products = request.env['product.template'].sudo().search(
                domain + [('active', '=', True)],
                order='fitness_class_type, list_price',
            )
        else:
            products = request.env['product.template'].sudo().search(
                domain + [('active', '=', True), ('sale_ok', '=', True)],
                order='fitness_class_type, list_price',
            )
        products = products.filtered(
            lambda p: 'discontinued' not in (p.name or '').lower()
        )
        contact_only_ids = frozenset(p.id for p in products if not p.sale_ok)

        pkg_meta = {}
        for p in products:
            parts = []
            if active_tab in ('packages', 'classes'):
                if p.fitness_class_count:
                    parts.append((_('%d class') % p.fitness_class_count) if p.fitness_class_count == 1
                                 else (_('%d classes') % p.fitness_class_count))
                if p.fitness_validity_days:
                    parts.append((_('%d day') % p.fitness_validity_days) if p.fitness_validity_days == 1
                                 else (_('%d days') % p.fitness_validity_days))
            else:
                if p.is_unlimited:
                    parts.append(_('Unlimited classes'))
                elif p.weekly_class_allowance:
                    parts.append((_('%d class per week') % p.weekly_class_allowance)
                                 if p.weekly_class_allowance == 1
                                 else (_('%d classes per week') % p.weekly_class_allowance))
                parts.append(_('Monthly plan'))
            pkg_meta[p.id] = ' · '.join(parts)

        # Group by the disciplines that actually exist in the data.
        groups = []
        for disc in self._disciplines_in(products):
            members = products.filtered(
                lambda p, d=disc: (p.fitness_class_type or 'any') == d
            )
            if members:
                groups.append({'key': disc, 'label': self._discipline_label(disc), 'products': members})

        # Chips mirror the disciplines present, so no dead filters appear.
        chips = [{'key': 'all', 'label': _('All')}]
        for disc in self._disciplines_in(products):
            if disc != 'any':
                chips.append({'key': disc, 'label': self._discipline_label(disc)})

        # D6: find which product.templates the student already has active,
        # so the template can show a badge and disable the Buy button.
        active_product_tmpl_ids = set()
        if active_tab == 'subscriptions':
            active_subs = request.env['sale.order'].sudo().search([
                ('partner_id', '=', partner.id),
                ('is_subscription', '=', True),
                ('subscription_state', '=', '3_progress'),
            ])
            for sub in active_subs:
                product = sub.fitness_subscription_product_id
                if product:
                    active_product_tmpl_ids.add(product.product_tmpl_id.id)
        else:
            active_lines = request.env['sale.order.line'].sudo().search([
                ('order_partner_id', '=', partner.id),
                ('product_id.fitness_is_package', '=', True),
                ('fitness_remaining_classes', '>', 0),
            ])
            for line in active_lines:
                if not line.fitness_is_expired:
                    active_product_tmpl_ids.add(line.product_id.product_tmpl_id.id)

        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        credit = self._primary_credit(partner.id)
        credit_line = None
        if credit:
            if credit.get('total'):
                credit_line = _('%(remaining)s / %(total)s credits') % {
                    'remaining': credit['remaining'], 'total': int(credit['total']),
                }
            else:
                credit_line = _('%d credits') % credit['remaining']

        return request.render('fitness_portal.portal_packages', {
            'active_tab':               active_tab,
            'groups':                   groups,
            'chips':                    chips,
            'active_chip':              active_chip,
            'products':                 products,
            'pkg_meta':                 pkg_meta,
            'active_product_tmpl_ids':  active_product_tmpl_ids,
            'contact_only_ids':         contact_only_ids,
            'primary_credit':           credit,
            'credit_line':              credit_line,
            'student_name':             student_name,
            'bought':                   bool(kw.get('bought')),
            'empty_msg':                (_('No subscriptions available right now.') if active_tab == 'subscriptions'
                                         else _('No classes available right now.') if active_tab == 'classes'
                                         else _('No packages available right now.')),
        })

    @http.route('/my/packages/<int:product_id>', type='http', auth='user',
                website=True, sitemap=False)
    def package_detail(self, product_id, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.active or not self._is_buyable(product):
            return request.redirect('/my/packages')

        is_sub = bool(product.fitness_is_subscription_plan)
        partner = request.env.user.partner_id
        _ = request.env._
        parts = []
        if is_sub:
            if product.is_unlimited:
                parts.append(_('Unlimited classes'))
            elif product.weekly_class_allowance:
                parts.append((_('%d class per week') % product.weekly_class_allowance)
                             if product.weekly_class_allowance == 1
                             else (_('%d classes per week') % product.weekly_class_allowance))
            parts.append(_('Monthly plan'))
        else:
            if product.fitness_class_count:
                parts.append((_('%d class') % product.fitness_class_count) if product.fitness_class_count == 1
                             else (_('%d classes') % product.fitness_class_count))
            if product.fitness_validity_days:
                parts.append((_('%d day') % product.fitness_validity_days) if product.fitness_validity_days == 1
                             else (_('%d days') % product.fitness_validity_days))
        meta = ' · '.join(parts)

        # Check if student holds an active instance of this product
        active_info = None
        lang_code = (request.lang.code if request.lang else None) or 'en_US'

        def _fmt_date(d):
            if not d:
                return ''
            if isinstance(d, _dt_cls):
                d = d.date()
            if _BABEL_OK:
                try:
                    return _babel_format_date(d, format='d MMM yyyy', locale=lang_code)
                except Exception:
                    pass
            return d.strftime('%d/%m/%Y')

        if is_sub:
            active_sub = request.env['sale.order'].sudo().search([
                ('partner_id', '=', partner.id),
                ('is_subscription', '=', True),
                ('subscription_state', '=', '3_progress'),
                ('order_line.product_id.product_tmpl_id', '=', product.id),
            ], limit=1)
            if active_sub:
                raw_date = active_sub.start_date or active_sub.date_order
                active_info = {
                    'order':    active_sub,
                    'date_str': _fmt_date(raw_date),
                    'ref':      active_sub.name,
                }
        else:
            active_line = request.env['sale.order.line'].sudo().search([
                ('order_partner_id', '=', partner.id),
                ('product_id.product_tmpl_id', '=', product.id),
                ('fitness_remaining_classes', '>', 0),
            ], order='fitness_validity_end_date asc nulls last', limit=1)
            if active_line:
                active_info = {
                    'order':             active_line.order_id,
                    'date_str':          _fmt_date(active_line.order_id.date_order),
                    'ref':               active_line.order_id.name,
                    'credits_remaining': active_line.fitness_remaining_classes,
                    'credits_total':     active_line.fitness_original_class_count,
                    'validity_end_str':  _fmt_date(active_line.fitness_validity_end_date),
                }

        full_name = partner.name or ''
        return request.render('fitness_portal.portal_package_detail', {
            'product':         product,
            'meta':            meta,
            'is_subscription': is_sub,
            'back_url':        ('/my/packages?tab=subscriptions' if is_sub
                               else '/my/packages?tab=classes' if (
                                   product.fitness_is_package and product.fitness_class_count and product.fitness_class_count <= 1
                               ) else '/my/packages'),
            'ct':              product.fitness_class_type or 'any',
            'student_name':    full_name.split()[0] if full_name else '',
            'primary_credit':  self._primary_credit(partner.id),
            'active_info':     active_info,
            'lbl_status':      _('Status'),
            'lbl_active':      _('Active'),
            'lbl_purchased':   _('Purchased'),
            'lbl_remaining':   _('Remaining'),
            'lbl_classes':     _('classes'),
            'lbl_valid_until': _('Valid until'),
            'lbl_order':       _('Order'),
            'lbl_price':       _('Price'),
        })

    # Legacy POST target — the Buy button is now a link to the payment step.
    @http.route('/my/packages/<int:product_id>/buy', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'])
    def packages_buy(self, product_id, **kw):
        return request.redirect(f'/my/packages/{product_id}/checkout')

    # ══════════════════════════════════════════════════════════
    #  PURCHASE FLOW — step 2 "Payment", step 3 "Sign"
    # ══════════════════════════════════════════════════════════

    @http.route('/my/packages/<int:product_id>/checkout', type='http', auth='user',
                website=True, sitemap=False, methods=['GET', 'POST'])
    def checkout_payment(self, product_id, **kw):
        """Step 2 — Terms acceptance + payment. If an online provider (Stripe)
        is active the student is forwarded to the Stripe payment page instead
        of the old manual bank-transfer/Bizum instructions."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.active or not self._is_buyable(product):
            return request.redirect('/my/packages')
        if not product.sale_ok:
            return request.redirect('/my/packages')

        # Determine whether any enabled/test online payment provider is configured.
        online_providers = request.env['payment.provider'].sudo().search([
            ('state', 'in', ('enabled', 'test')),
            ('company_id', '=', request.env.company.id),
        ])
        use_online = bool(online_providers)

        error_msg = None
        method = kw.get('payment_method')

        if request.httprequest.method == 'POST':
            if use_online:
                # Online (Stripe) path: only terms acceptance needed.
                if not kw.get('terms_accepted'):
                    error_msg = _('Please accept the Terms and Conditions to continue.')
                else:
                    order = self._create_order(partner, product, 'stripe')
                    if not order:
                        return request.redirect('/my/packages')
                    return request.redirect(f'/my/packages/pay/{order.id}')
            else:
                # Manual fallback path: payment method + terms.
                if method not in PAYMENT_METHODS:
                    error_msg = _('Please choose a payment method.')
                elif not kw.get('terms_accepted'):
                    error_msg = _('Please accept the Terms and Conditions to continue.')
                else:
                    order = self._create_order(partner, product, method)
                    if not order:
                        return request.redirect('/my/packages')
                    return request.redirect(f'/my/checkout/{order.id}/sign')

        full_name = partner.name or ''
        return request.render('fitness_portal.portal_checkout_payment', {
            'product':            product,
            'is_subscription':    bool(product.fitness_is_subscription_plan),
            'step':               'payment',
            'selected_method':    method if method in PAYMENT_METHODS else None,
            'payment_details':    self._payment_details(),
            'error_msg':          error_msg,
            'back_url':           f'/my/packages/{product.id}',
            'student_name':       full_name.split()[0] if full_name else '',
            'terms_label':        _('I agree to the'),
            'terms_link_label':   _('Terms and Conditions'),
            'use_online_payment': use_online,
        })

    @http.route('/my/checkout/<int:order_id>/sign', type='http', auth='user',
                website=True, sitemap=False, methods=['GET'])
    def checkout_sign(self, order_id, **kw):
        """Step 3 of 3. Signature capture; confirming completes the purchase."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        order = self._own_draft_order(order_id)
        if not order:
            return request.redirect('/my/packages')

        _ = request.env._
        partner = request.env.user.partner_id
        line = order.order_line[:1]
        product = line.product_id.product_tmpl_id if line else None
        method = order.fitness_payment_method

        method_label = self._payment_method_label(method)
        summary = _('%(product)s · %(price)s · paid by %(method)s') % {
            'product': product.name if product else order.name,
            'price':   self._format_price(order.amount_total, order.currency_id),
            'method':  method_label,
        }

        full_name = partner.name or ''
        return request.render('fitness_portal.portal_checkout_sign', {
            'order':                order,
            'product':              product,
            'step':                 'sign',
            'method_label':         method_label,
            'summary':              summary,
            'sign_default':         partner.name or '',
            'back_url':             f'/my/packages/{product.id}/checkout' if product else '/my/packages',
            'error_msg':            kw.get('error') or None,
            'student_name':         full_name.split()[0] if full_name else '',
            'label_draw_signature': _('Draw your signature'),
            'label_your_full_name': _('Your full name'),
            'label_sign_here':      _('Sign here'),
        })

    @http.route('/my/checkout/<int:order_id>/complete', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'])
    def checkout_complete(self, order_id, signature=None, signed_by=None, **kw):
        """Stores the signature on the existing sale.order signature fields and
        runs the standard confirmation — the same write + action_confirm() the
        stock portal signing route performs. No order logic is duplicated here."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        order = self._own_draft_order(order_id)
        if not order:
            return request.redirect('/my/packages')

        if not signature:
            qs = urlencode({'error': _('Please sign in the box before completing your purchase.')})
            return request.redirect(f'/my/checkout/{order_id}/sign?{qs}')

        try:
            base64.b64decode(signature, validate=True)
        except (binascii.Error, ValueError):
            qs = urlencode({'error': _('The signature could not be read. Please try again.')})
            return request.redirect(f'/my/checkout/{order_id}/sign?{qs}')

        # A signature is not a payment.
        #
        # PAYMENT_METHODS are the two the studio settles by hand (Bizum, bank
        # transfer); for those, signing really is all the portal can ask for and
        # the manager's "needs invoicing" notification is what chases the money.
        # Anything else was routed to Stripe, and confirming it on a signature
        # alone hands out credits for free: this route is reachable directly, so
        # a student who opened the pay page could simply visit the signature step
        # instead. Verified: order S00195 confirmed with 10 credits and zero
        # payment transactions before this check existed.
        if order.fitness_payment_method not in PAYMENT_METHODS:
            paid_tx = order.sudo().transaction_ids.filtered(
                lambda t: t.state == 'done'
            )
            if not paid_tx:
                _logger.warning(
                    "Blocked unpaid confirmation: order %s (method=%s) reached "
                    "the signature step with no successful transaction.",
                    order.name, order.fitness_payment_method or 'unset',
                )
                qs = urlencode({'error': _(
                    'This order has not been paid yet. Please complete the '
                    'payment before confirming your purchase.'
                )})
                return request.redirect(f'/my/packages/pay/{order.id}?{qs}')

        try:
            order.sudo().write({
                'signature': signature,
                'signed_by': signed_by or request.env.user.partner_id.name,
                'signed_on': fields.Datetime.now(),
            })
            order.sudo().action_confirm()
        except (UserError, ValidationError) as exc:
            qs = urlencode({'error': str(exc)})
            return request.redirect(f'/my/checkout/{order_id}/sign?{qs}')

        self._notify_admins_of_purchase(order)
        return request.redirect('/my/packages?bought=1')

    @staticmethod
    def _notify_admins_of_purchase(order):
        """Tell the studio a portal purchase happened.

        Until now this was silent: the order was confirmed and credits were
        granted with nothing prompting anyone to invoice or chase payment.
        """
        managers = request.env['res.users'].sudo().search([
            ('group_ids', 'in', [request.env.ref('fitness_core.group_fitness_manager').id]),
        ])
        if not managers:
            return
        Notif = request.env['fitness.notification'].sudo()
        line = order.order_line[:1]
        product_name = line.product_id.display_name if line else order.name
        for manager in managers:
            translate = request.env(context=dict(request.env.context,
                                                 lang=manager.lang or 'en_US'))._
            # The raw selection label came through in English inside an
            # otherwise-translated message. Translate it in the recipient's
            # language like everything else. "Bizum" is a Spanish payment
            # brand and stays "Bizum" in all three languages — it goes
            # through _() anyway so it is never hard-coded.
            if order.fitness_payment_method == 'transfer':
                method_label = translate('Bank Transfer')
            elif order.fitness_payment_method == 'bizum':
                method_label = translate('Bizum')
            else:
                method_label = translate('Not selected')

            title = translate('New purchase: %(product)s') % {'product': product_name}
            body = translate('%(customer)s bought %(product)s for %(amount)s. Payment method: %(method)s. Order %(order)s needs invoicing.') % {
                'customer': order.partner_id.name,
                'product': product_name,
                'amount': '%.2f %s' % (order.amount_total,
                                       order.currency_id.symbol or ''),
                'method': method_label,
                'order': order.name,
            }
            Notif._create_for_user(manager.id, 'purchase_completed', title, body)

    # ══════════════════════════════════════════════════════════
    #  NEWS DETAIL
    # ══════════════════════════════════════════════════════════

    @http.route('/my/news', type='http', auth='user', website=True, sitemap=False)
    def news_list(self, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')
        posts = request.env['fitness.news.post'].sudo().search(
            [('active', '=', True)],
            order='sequence asc, publish_date desc, id desc',
        )
        return request.render('fitness_portal.portal_news_list', {'posts': posts})

    @http.route('/my/news/<int:post_id>', type='http', auth='user',
                website=True, sitemap=False)
    def news_detail(self, post_id, **kw):
        post = request.env['fitness.news.post'].sudo().search([
            ('id', '=', post_id), ('active', '=', True),
        ], limit=1)
        if not post:
            return request.not_found()
        return request.render('fitness_portal.portal_news_detail', {'post': post})

    # ══════════════════════════════════════════════════════════
    #  TERMS AND CONDITIONS
    # ══════════════════════════════════════════════════════════

    @http.route('/my/terms', type='http', auth='user', website=True, sitemap=False)
    def terms_and_conditions(self, back=None, **kw):
        # `back` lets the payment step send the student straight back to where
        # they were; anything unexpected falls back to the Packages tab.
        back_url = back if (back or '').startswith('/my/') else '/my/packages'
        partner = request.env.user.partner_id
        full_name = partner.name or ''
        return request.render('fitness_portal.portal_terms', {
            'back_url':     back_url,
            'student_name': full_name.split()[0] if full_name else '',
        })

    # ══════════════════════════════════════════════════════════
    #  ACTIVE ORDERS
    # ══════════════════════════════════════════════════════════

    @http.route('/my/orders/active', type='http', auth='user', website=True, sitemap=False)
    def active_orders(self, show=None, **kw):
        """Orders view with two tabs: Active (unsettled) and All.
        ?show=all switches to the All tab which includes fully-invoiced orders."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        show_all = (show == 'all')
        partner = request.env.user.partner_id

        domain = [('partner_id', '=', partner.id), ('state', 'in', ('draft', 'sent', 'sale'))]
        orders = request.env['sale.order'].search(domain, order='date_order desc')

        if not show_all:
            orders = orders.filtered(lambda o: o.invoice_status != 'invoiced')

        rows = []
        for order in orders:
            if order.state in ('draft', 'sent'):
                status = _('Awaiting signature')
                badge = 'pending'
            elif order.invoice_status == 'invoiced':
                status = _('Invoiced')
                badge = 'success'
            else:
                status = _('Awaiting invoice')
                badge = 'sage'
            first_line = order.order_line.filtered(lambda l: l.product_id)[:1]
            plan_name = first_line.product_id.name if first_line else order.name
            rows.append({
                'order':     order,
                'status':    status,
                'badge':     badge,
                'amount':    self._format_price(order.amount_total, order.currency_id),
                'plan_name': plan_name,
            })

        full_name = partner.name or ''
        empty_msg = (_('No orders found.') if show_all
                     else _('You have no active orders. Everything is settled.'))
        return request.render('fitness_portal.portal_active_orders', {
            'rows':         rows,
            'show_all':     show_all,
            'empty_msg':    empty_msg,
            'student_name': full_name.split()[0] if full_name else '',
            'tab_active':   _('Active'),
            'tab_all':      _('All'),
        })

    # ══════════════════════════════════════════════════════════
    #  ORDER DETAIL  (/my/orders/<id>/view)  — mobile override
    # NOTE: Route activates on next service restart after module upgrade.
    #       Until restart, /my/orders/<id> shows the standard Odoo order page.
    # ══════════════════════════════════════════════════════════

    @http.route('/my/orders/<int:order_id>/view', type='http', auth='user',
                website=True, sitemap=False)
    def order_detail(self, order_id, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        partner = request.env.user.partner_id
        order = request.env['sale.order'].sudo().browse(order_id)

        if not order.exists() or order.partner_id.id != partner.id:
            return request.redirect('/my/orders/active')

        _ = request.env._
        full_name = partner.name or ''
        return request.render('fitness_portal.portal_order_detail', {
            'sale_order':      order,
            'student_name':    full_name.split()[0] if full_name else '',
            'lbl_date':        _('Date'),
            'lbl_status':      _('Status'),
            'lbl_order_total': _('Order total'),
        })

    # ══════════════════════════════════════════════════════════
    #  Subscription page (/my/subscription)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/subscription', type='http', auth='user', website=True, sitemap=False)
    def my_subscription(self, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        today = fields.Date.context_today(request.env.user)

        subs = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('is_subscription', '=', True),
            ('subscription_state', '=', '3_progress'),
        ])

        sub_data = []
        for sub in subs:
            product = sub.fitness_subscription_product_id
            if not product:
                continue

            is_unlimited = bool(sub.fitness_is_unlimited)
            weekly_used = sub.fitness_weekly_used_count(today) if not is_unlimited else 0
            eff = sub.fitness_effective_weekly_allowance() if not is_unlimited else 0

            slots = []
            for slot in sub.fitness_clase_fija_ids.filtered('active'):
                ev = slot.calendar_event_id
                if ev and ev.start:
                    slots.append(slot.name)

            period_end_str = ''
            if sub.next_invoice_date:
                next_renewal = sub.next_invoice_date
                today_date = fields.Date.context_today(request.env.user)
                # Advance stale dates forward — manual-payment studios don't
                # trigger the Odoo billing cron so next_invoice_date can lag.
                if next_renewal < today_date and sub.plan_id:
                    unit  = sub.plan_id.billing_period_unit   # 'month', 'week', 'year'
                    value = sub.plan_id.billing_period_value  # e.g. 1
                    delta = _relativedelta(**{unit + 's': value})
                    while next_renewal < today_date:
                        next_renewal = next_renewal + delta
                period_end_str = next_renewal.strftime('%d %b %Y')

            sub_data.append({
                'plan_name':        product.name,
                'is_unlimited':     is_unlimited,
                'weekly_allowance': eff,
                'weekly_used':      weekly_used,
                'floating_credits': sub.fitness_floating_credits,
                'period_end':       period_end_str,
                'is_clase_fija':    bool(sub.fitness_is_clase_fija),
                'slots':            slots,
            })

        full_name = partner.name or ''
        return request.render('fitness_portal.portal_subscription', {
            'sub_data':          sub_data,
            'has_sub':           bool(sub_data),
            'student_name':      full_name.split()[0] if full_name else '',
            'lbl_classes':       _('Classes'),
            'lbl_unlimited':     _('Unlimited'),
            'lbl_this_week':     _('This week'),
            'lbl_bonus_credits': _('Bonus credits'),
            'lbl_next_renewal':  _('Next renewal'),
        })

    # ══════════════════════════════════════════════════════════
    #  Notifications API
    # ══════════════════════════════════════════════════════════

    @http.route('/my/notifications/count', type='http', auth='user',
                website=True, sitemap=False, methods=['GET'])
    def notifications_count(self, **kw):
        count = request.env['fitness.notification'].sudo().search_count([
            ('user_id', '=', request.env.user.id),
            ('is_read', '=', False),
        ])
        return request.make_response(
            json.dumps({'count': count}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/notifications', type='http', auth='user', website=True, sitemap=False)
    def notifications_page(self, **kw):
        """Full archive. Auto-marks all as read on load so state persists
        correctly when the user re-opens. The 'is_new' flag in each entry
        preserves the unread indicator for the current view."""
        _ = request.env._
        notifs = request.env['fitness.notification'].sudo().search(
            [('user_id', '=', request.env.user.id)]
        )
        now = fields.Datetime.now()
        # Capture unread state BEFORE writing so the template can show
        # which notifications are new during this visit.
        entries = [{
            'record':   n,
            'is_new':   not n.is_read,
            'time_ago': _time_ago(now - n.create_date, _),
        } for n in notifs]
        unread_count = sum(1 for e in entries if e['is_new'])

        # Persist read state now — re-opening the archive will show all as read.
        if unread_count:
            notifs.filtered(lambda n: not n.is_read).write({'is_read': True})

        partner = request.env.user.partner_id
        full_name = partner.name or ''
        is_student = request.env.user.has_group(STUDENT_GROUP)
        is_teacher = request.env.user.has_group('fitness_core.group_fitness_teacher')
        return request.render('fitness_portal.portal_notifications', {
            'entries':      entries,
            'unread':       unread_count,
            'is_student':   is_student,
            'is_teacher':   is_teacher,
            'show_shell':   is_student or is_teacher,
            'back_url':     '/my' if (is_student or is_teacher) else '/odoo',
            'empty_msg':    _('No notifications yet.'),
            'student_name': full_name.split()[0] if full_name else '',
        })

    @http.route('/my/notifications/read-all', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'])
    def notifications_read_all(self, **kw):
        request.env['fitness.notification'].sudo().search([
            ('user_id', '=', request.env.user.id), ('is_read', '=', False),
        ]).write({'is_read': True})
        return request.redirect('/my/notifications')

    @http.route('/my/notifications/data', type='http', auth='user',
                website=True, sitemap=False, methods=['GET'])
    def notifications_list(self, **kw):
        _ = request.env._
        notif_model = request.env['fitness.notification'].sudo()
        notifs = notif_model.search(
            [('user_id', '=', request.env.user.id), ('is_read', '=', False)], limit=20
        )
        now = fields.Datetime.now()
        result = []
        for n in notifs:
            time_ago = _time_ago(now - n.create_date, _)
            result.append({
                'id': n.id,
                'title': n.title,
                'body': n.body or '',
                'read': False,
                'time_ago': time_ago,
                'type': n.notification_type,
                'action_url': n.action_url or '',
            })
        return request.make_response(
            json.dumps({'notifications': result}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/notifications/mark_read', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'], csrf=False)
    def notification_mark_read(self, notif_id=None, **kw):
        if notif_id:
            try:
                nid = int(notif_id)
                notif = request.env['fitness.notification'].sudo().search([
                    ('id', '=', nid), ('user_id', '=', request.env.user.id)
                ], limit=1)
                if notif:
                    notif.write({'is_read': True})
            except Exception:
                pass
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    # ══════════════════════════════════════════════════════════
    #  Profile photo upload
    # ══════════════════════════════════════════════════════════

    @http.route('/my/profile/upload-photo', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'])
    def upload_profile_photo(self, photo=None, **kw):
        if photo and hasattr(photo, 'read'):
            data = photo.read()
            if data:
                try:
                    request.env.user.partner_id.sudo().write({
                        'image_1920': base64.b64encode(data).decode(),
                    })
                    return request.redirect('/my?photo_ok=1')
                except Exception:
                    pass
        return request.redirect('/my?photo_err=1')

    # ══════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _user_tz():
        try:
            return pytz.timezone(request.env.user.tz or 'UTC')
        except pytz.UnknownTimeZoneError:
            return pytz.UTC

    @staticmethod
    def _is_buyable(product):
        return bool(product.fitness_is_package or product.fitness_is_subscription_plan)

    @staticmethod
    def _disciplines_in(products):
        """Disciplines actually present in the data, in a stable display order."""
        present = {(p.fitness_class_type or 'any') for p in products}
        return [d for d in ('barre', 'reformer', 'any') if d in present]

    @staticmethod
    def _discipline_label(key):
        _ = request.env._
        return {
            'barre':    _('Barre'),
            'reformer': _('Reformer'),
            'any':      _('All disciplines'),
        }.get(key, key)

    @staticmethod
    def _payment_method_label(method):
        _ = request.env._
        return {
            'bizum':    _('Bizum'),
            'transfer': _('Bank Transfer'),
        }.get(method, _('Not selected'))

    @staticmethod
    def _payment_details():
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            key.rsplit('.', 1)[1]: (ICP.get_param(key) or default)
            for key, default in PAYMENT_PARAM_DEFAULTS.items()
        }

    @staticmethod
    def _format_price(amount, currency):
        symbol = currency.symbol if currency else '€'
        return f'{amount:.2f} {symbol}'

    def _create_order(self, partner, product, method):
        """Return the draft sale order for this purchase, reusing an abandoned
        one where possible.

        A student who taps Next, goes back and taps Next again used to leave a
        new draft behind on every attempt, cluttering Active Orders. We reuse
        an existing *draft* for the same partner and product instead.

        Only 'draft' qualifies. An order that is already sale/sent/done/cancel
        has been signed or acted on and must never be rewritten by a fresh
        checkout attempt.
        """
        variant = product.product_variant_ids[:1]
        if not variant:
            return None

        existing = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'draft'),
        ], order='id desc')
        for candidate in existing:
            lines = candidate.order_line
            # This flow only ever builds single-line orders; anything else was
            # created elsewhere and is not ours to touch.
            if len(lines) == 1 and lines.product_id.id == variant.id:
                candidate.write({
                    'fitness_payment_method': method,
                    'fitness_terms_accepted_on': fields.Datetime.now(),
                })
                _logger.info(
                    '[CHECKOUT] Reusing draft order %s for partner %s / product %s',
                    candidate.name, partner.id, variant.id,
                )
                return candidate

        vals = {
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': variant.id,
                'product_uom_qty': 1,
                'price_unit': product.list_price,
            })],
            'fitness_payment_method': method,
            'fitness_terms_accepted_on': fields.Datetime.now(),
        }

        # Subscription plans need a recurrence plan for Odoo to treat the order
        # as a subscription. Guarded so a database without the subscription app
        # simply creates a normal order.
        if product.fitness_is_subscription_plan and 'plan_id' in request.env['sale.order']._fields:
            plan = request.env['sale.subscription.plan'].sudo().search([], limit=1)
            if plan:
                vals['plan_id'] = plan.id

        return request.env['sale.order'].sudo().create(vals)

    def _own_draft_order(self, order_id):
        """The order must belong to the logged-in student and still be unsigned."""
        order = request.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return None
        if order.partner_id != request.env.user.partner_id:
            return None
        if order.state not in ('draft', 'sent'):
            return None
        return order

    def _credit_pools(self, partner_id):
        """All active credit pools for the stat card, newest-expiring last.

        The arithmetic lives on res.partner so the admin backend shows the
        student exactly the number the student sees. Do not reimplement it
        here: two copies drift the first time a credit rule changes.
        """
        partner = request.env['res.partner'].sudo().browse(partner_id)
        return partner._fitness_credit_pools() if partner.exists() else []

    def _primary_credit(self, partner_id):
        """Return the most relevant credit pool, or None. Used by pages that
        show a single stat (not the paged home card)."""
        pools = self._credit_pools(partner_id)
        return pools[0] if pools else None

    def _eligible_class_types(self, partner_id):
        eligible = set()
        subs = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner_id),
            ('subscription_state', '=', '3_progress'),
            ('fitness_subscription_product_id', '!=', False),
        ])
        for sub in subs:
            self._collect_type(eligible, sub.fitness_subscription_product_id.fitness_class_type)

        lines = request.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner_id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ])
        for line in lines.filtered(lambda l: not l.fitness_is_expired):
            self._collect_type(eligible, line.product_id.fitness_class_type)

        return eligible

    @staticmethod
    def _collect_type(eligible_set, class_type):
        if class_type == 'any':
            eligible_set.update(['barre', 'reformer'])
        elif class_type:
            eligible_set.add(class_type)

    @staticmethod
    def _has_seats(event):
        if not event.capacity:
            return True
        return event.booked_seats < event.capacity

    @staticmethod
    def _discipline_matches(event, eligible_types):
        if not event.class_type_id:
            return False
        return event.class_type_id.classroom_type in eligible_types

    # ══════════════════════════════════════════════════════════
    #  Message the Studio
    # ══════════════════════════════════════════════════════════

    @http.route('/my/messages', type='http', auth='user', website=True, sitemap=False)
    def messages_page(self, sent=None, error=None, prefill=None, **kw):
        user = request.env.user
        is_student = user.has_group(STUDENT_GROUP)
        is_teacher = user.has_group('fitness_core.group_fitness_teacher')
        if not (is_student or is_teacher):
            return request.redirect('/my')

        conversation = request.env['fitness.studio.conversation'].sudo().search([
            ('user_id', '=', user.id),
        ], order='write_date desc', limit=1)

        messages = conversation.message_ids.sorted('create_date') if conversation else []

        return request.render('fitness_portal.portal_messages', {
            'conversation': conversation,
            'messages':     messages,
            'sent':         bool(sent),
            'error':        error,
            'is_teacher':   is_teacher,
            'prefill':      (prefill or '').strip()[:300],
        })

    @http.route('/my/messages/send', type='http', auth='user',
                methods=['POST'], website=True, sitemap=False)
    def messages_send(self, body=None, **kw):
        user = request.env.user
        is_student = user.has_group(STUDENT_GROUP)
        is_teacher = user.has_group('fitness_core.group_fitness_teacher')
        if not (is_student or is_teacher):
            return request.redirect('/my')

        body = (body or '').strip()
        if not body:
            return request.redirect('/my/messages?error=empty')
        if len(body) > 2000:
            return request.redirect('/my/messages?error=toolong')

        role = 'Teacher' if is_teacher else 'Student'

        Conv = request.env['fitness.studio.conversation'].sudo()
        conversation = Conv.search([('user_id', '=', user.id)], order='write_date desc', limit=1)
        if not conversation:
            conversation = Conv.create({
                'user_id':    user.id,
                'partner_id': user.partner_id.id,
                'role':       role,
            })

        request.env['fitness.studio.message'].sudo().create({
            'conversation_id': conversation.id,
            'author_id':       user.id,
            'is_admin':        False,
            'body':            body,
        })
        return request.redirect('/my/messages?sent=1')

    @http.route('/my/message-studio', type='http', auth='user', website=True, sitemap=False)
    def message_studio_page(self, **kw):
        return request.redirect('/my/messages')

    # ══════════════════════════════════════════════════════════
    #  Language
    # ══════════════════════════════════════════════════════════

    @http.route('/my/language', type='http', auth='user', website=True, sitemap=False)
    def language_picker(self, **kw):
        mv_lang = request.httprequest.cookies.get('mv_lang') or request.env.lang or 'es_ES'
        partner = request.env.user.partner_id
        full_name = partner.name or ''
        return request.render('fitness_portal.portal_language_picker', {
            'current_lang':  mv_lang,
            'student_name':  full_name.split()[0] if full_name else '',
        })

    @http.route('/my/set_lang', type='http', auth='user', website=False, sitemap=False, csrf=False)
    def set_lang(self, lang='en_US', redirect='/my', **kw):
        valid_langs = {'en_US', 'es_ES', 'ca_ES'}
        if lang in valid_langs:
            request.env.user.sudo().write({'lang': lang})
            request.session.context = dict(request.session.context or {}, lang=lang)
        response = request.redirect(redirect or '/my')
        if lang in valid_langs:
            response.set_cookie('mv_lang', lang, max_age=365 * 24 * 3600, path='/', samesite='Lax', httponly=False)
            response.set_cookie('frontend_lang', lang, max_age=365 * 24 * 3600, path='/', samesite='Lax', httponly=False)
        return response


# ── Module-level helper: locale-aware day group label ──────────────────────

def _time_ago(diff, _=lambda s: s):
    """Human 'time since' used by both the bell API and the archive page."""
    total_secs = int(diff.total_seconds())
    if diff.days >= 1:
        return _('%dd ago') % diff.days
    if total_secs >= 3600:
        return _('%dh ago') % (total_secs // 3600)
    if total_secs >= 60:
        return _('%dm ago') % (total_secs // 60)
    return _('Just now')


def _day_label(d, today, tomorrow, _=lambda s: s, lang='en_US'):
    """Return a translated, formatted day label for a given date."""
    if d == today:
        return _('Today')
    if d == tomorrow:
        return _('Tomorrow')
    if _BABEL_OK:
        try:
            label = _babel_format_date(d, format='EEEE d MMM', locale=lang)
            return label.rstrip('.').upper()
        except Exception:
            pass
    return d.strftime('%A') + ' ' + str(d.day) + ' ' + d.strftime('%b')


# ──────────────────────────────────────────────────────────────────────────────
#  Stripe / online payment page for fitness package checkout
# ──────────────────────────────────────────────────────────────────────────────

class FitnessPackagePayment(_OdooPaymentPortal):
    """Renders the Stripe (online) payment page for fitness package orders.

    Inherits PaymentPortal only to get _create_transaction() / _validate_transaction_kwargs().
    The actual transaction JSON route is the sale module's existing
    /my/orders/<id>/transaction — we just render the payment form pointing there.
    """

    @http.route('/my/packages/pay/<int:order_id>', type='http', auth='user',
                website=True, sitemap=False)
    def packages_stripe_pay(self, order_id, **kw):
        """Display the online payment form for a draft fitness package order."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        order_sudo = request.env['sale.order'].sudo().browse(order_id)
        if not order_sudo.exists():
            return request.redirect('/my/packages')
        if order_sudo.partner_id != request.env.user.partner_id:
            return request.redirect('/my/packages')
        if order_sudo.state not in ('draft', 'sent'):
            # Already confirmed (payment succeeded previously).
            return request.redirect('/my/packages?bought=1')

        partner = request.env.user.partner_id
        company = request.env.company
        currency = order_sudo.currency_id or company.currency_id
        amount = order_sudo.amount_total

        availability_report = {}
        providers_sudo = request.env['payment.provider'].sudo()._get_compatible_providers(
            company.id,
            partner.id,
            amount,
            currency_id=currency.id,
            report=availability_report,
        )
        payment_methods_sudo = request.env['payment.method'].sudo()._get_compatible_payment_methods(
            providers_sudo.ids,
            partner.id,
            currency_id=currency.id,
            report=availability_report,
        )
        tokens_sudo = request.env['payment.token'].sudo()._get_available_tokens(
            providers_sudo.ids, partner.id,
        )

        # Ensure the order has an access token — the sale portal's transaction
        # route (/my/orders/<id>/transaction) uses it for public-user auth.
        # For logged-in portal users it acts as a fallback; the ACL check passes
        # first, but sending it avoids a 403 if session ever expires mid-flow.
        access_token = order_sudo._portal_ensure_token()

        # payment.method_form template requires this mapping of provider_id → bool
        # (whether to offer the "Save card" checkbox for each provider).
        if _PAYMENT_OK and hasattr(self, '_compute_show_tokenize_input_mapping'):
            show_tokenize_input_mapping = self._compute_show_tokenize_input_mapping(
                providers_sudo
            )
        else:
            show_tokenize_input_mapping = {
                p.id: bool(p.allow_tokenization) and not request.env.user._is_public()
                for p in providers_sudo
            }

        line = order_sudo.order_line[:1]
        product = line.product_id.product_tmpl_id if line else None
        full_name = partner.name or ''

        return request.render('fitness_portal.portal_packages_pay', {
            'order':                order_sudo,
            'product':              product,
            'amount':               amount,
            'currency':             currency,
            'partner_id':           partner.id,
            'providers_sudo':       providers_sudo,
            'payment_methods_sudo': payment_methods_sudo,
            'tokens_sudo':          tokens_sudo,
            'availability_report':  availability_report,
            'show_tokenize_input_mapping': show_tokenize_input_mapping,
            # Point at the sale portal's existing transaction-creation route so
            # payment.transaction.sale_order_ids is set automatically and
            # _post_process() can call order.action_confirm() on payment success.
            'transaction_route':    f'/my/orders/{order_id}/transaction',
            'landing_route':        '/my/packages',
            'access_token':         access_token,
            'student_name':         full_name.split()[0] if full_name else '',
            'back_url':             (f'/my/packages/{product.id}/checkout'
                                     if product else '/my/packages'),
            # Set when a signature-step confirmation was refused for want of a
            # payment, so the student is told why they landed back here.
            'error_msg':            kw.get('error') or None,
        })
