import base64
import binascii
import json
import logging
from datetime import timedelta, datetime as _dt_cls, date as _date_cls
from itertools import groupby as _groupby
from urllib.parse import urlencode

_logger = logging.getLogger(__name__)

import pytz

try:
    from babel.dates import format_date as _babel_format_date
    _BABEL_OK = True
except Exception:
    _BABEL_OK = False

from odoo import http, fields
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

STUDENT_GROUP = 'fitness_core.group_fitness_student'
LOOK_AHEAD_DAYS = 14
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

    # ══════════════════════════════════════════════════════════
    #  HOME  (post-login landing page, bottom-nav tab 1)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/home', type='http', auth='user', website=True, sitemap=False)
    def portal_home(self, **kw):
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

        return request.render('fitness_portal.portal_student_home', {
            'welcome':          welcome,
            'student_name':     student_name,
            'upcoming_count':   n,
            'next_booking':     upcoming[:1],
            'schedule_hint':    schedule_hint,
            'primary_credit':   self._primary_credit(partner.id),
            'has_any_bookings': has_any_bookings,
        })

    # ══════════════════════════════════════════════════════════
    #  STUDIO  (bottom-nav tab 2 — "Available" | "My Schedule")
    # ══════════════════════════════════════════════════════════

    @http.route('/my/studio', type='http', auth='user', website=True, sitemap=False)
    def studio(self, view=None, booked=None, cancelled=None, credit_returned=None,
               error=None, **kw):
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

        if active_view == 'schedule':
            values.update(self._schedule_values(partner))
        else:
            values.update(self._available_values(partner))

        return request.render('fitness_portal.portal_student_studio', values)

    def _available_values(self, partner):
        """Day-grouped list of bookable classes (the 'Available' view)."""
        _ = request.env._
        lang = request.env.lang or 'en_US'
        now = fields.Datetime.now()
        window_end = now + timedelta(days=LOOK_AHEAD_DAYS)

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
            _current_items.append({'event': ev, 'local_time': local_dt.strftime('%H:%M'),
                                   'seats_v': seats_v, 'seats_label': seats_label})
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

        return {
            'events':          events,
            'grouped_events':  grouped_events,
            'has_sources':     bool(eligible_types),
            'look_ahead_days': LOOK_AHEAD_DAYS,
            'today_local':     today_local,
            'subtitle':        subtitle,
            'empty_state':     _('No classes available in the next %d days for your plan. Check back soon!') % LOOK_AHEAD_DAYS,
            'no_sources_msg':  _("You don't have an active membership or class pack. Please contact the studio to get started."),
        }

    def _schedule_values(self, partner):
        """Day-grouped list of the student's upcoming bookings ('My Schedule')."""
        _ = request.env._
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

        return {
            'grouped_bookings':  grouped,
            'look_ahead_days':   look_ahead,
            'subtitle':          _('Next %d days') % look_ahead,
            'schedule_empty':    _('No upcoming classes in the next %d days.') % look_ahead,
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
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        partner = request.env.user.partner_id
        now = fields.Datetime.now()
        today = fields.Date.today()

        if period == 'week':
            cutoff = now - timedelta(days=7)
        elif period == 'month':
            cutoff = now - timedelta(days=30)
        else:
            period = 'all'
            cutoff = None

        booking_domain = [
            ('student_id', '=', partner.id),
            '|',
            ('class_start', '<', now),
            ('state', 'in', ['no_show', 'cancelled']),
        ]
        if cutoff:
            booking_domain.append(('class_start', '>=', cutoff))

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
                packs.append({
                    'order':      order,
                    'line':       pack_line,
                    'is_expired': is_expired,
                })

        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        lang_code = (request.lang.code if request.lang else None) or 'en_US'
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
            'month_groups':   month_groups,
            'subscriptions':  subscriptions,
            'packs':          packs,
            'primary_credit': self._primary_credit(partner.id),
            'student_name':   student_name,
            'filter_period':  period,
        })

    # ══════════════════════════════════════════════════════════
    #  CREDIT HISTORY  (ledger — every credit-affecting event)
    # ══════════════════════════════════════════════════════════

    @http.route('/my/credits', type='http', auth='user', website=True, sitemap=False)
    def credit_history(self, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        entries = self._credit_ledger(partner)

        full_name = partner.name or ''
        student_name = full_name.split()[0] if full_name else full_name

        return request.render('fitness_portal.portal_credit_history', {
            'entries':           entries,
            'current_total':     entries[0]['balance'] if entries else self._credit_total(partner),
            'primary_credit':    self._primary_credit(partner.id),
            'student_name':      student_name,
            'ledger_empty':      _('No credit activity yet. Buy a package to get started.'),
            'label_credits_page': _('Credit History'),
            'label_credits_sub':  _('All changes to your credits'),
        })

    def _credit_total(self, partner):
        """Credits the student can actually book with right now:
        unexpired class-pack credits + subscription floating credits."""
        today = fields.Date.today()
        total = 0
        lines = request.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ])
        for line in lines:
            vend = line.fitness_validity_end_date
            if vend and vend < today:
                continue
            total += line.fitness_remaining_classes

        subs = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('subscription_state', '=', '3_progress'),
        ])
        total += sum(subs.mapped('fitness_floating_credits'))
        return total

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
        today = fields.Date.today()
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
            cf_promo = (
                is_cf and sub_date is not None
                and _PROMO_WINDOW_START <= sub_date <= _PROMO_WINDOW_END
            )
            effective_bonus = 1 if cf_promo else bonus

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
    def packages_list(self, tab=None, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        active_tab = 'subscriptions' if tab == 'subscriptions' else 'packages'

        if active_tab == 'subscriptions':
            domain = [('fitness_is_subscription_plan', '=', True)]
        else:
            domain = [('fitness_is_package', '=', True)]

        products = request.env['product.template'].sudo().search(
            domain + [('active', '=', True), ('sale_ok', '=', True)],
            order='fitness_class_type, list_price',
        )
        products = products.filtered(
            lambda p: 'discontinued' not in (p.name or '').lower()
        )

        pkg_meta = {}
        for p in products:
            parts = []
            if active_tab == 'packages':
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
            'products':                 products,
            'pkg_meta':                 pkg_meta,
            'active_product_tmpl_ids':  active_product_tmpl_ids,
            'primary_credit':           credit,
            'credit_line':              credit_line,
            'student_name':             student_name,
            'bought':                   bool(kw.get('bought')),
            'empty_msg':                (_('No subscriptions available right now.') if active_tab == 'subscriptions'
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
            'back_url':        '/my/packages?tab=subscriptions' if is_sub else '/my/packages',
            'ct':              product.fitness_class_type or 'any',
            'student_name':    full_name.split()[0] if full_name else '',
            'primary_credit':  self._primary_credit(partner.id),
            'active_info':     active_info,
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
        """Step 2 of 3. Collects a payment method + terms acceptance, then
        creates the sale order and hands over to the signature step."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        product = request.env['product.template'].sudo().browse(product_id)
        if not product.exists() or not product.active or not self._is_buyable(product):
            return request.redirect('/my/packages')
        if not product.sale_ok:
            return request.redirect('/my/packages')

        error_msg = None
        method = kw.get('payment_method')

        if request.httprequest.method == 'POST':
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
            'product':          product,
            'is_subscription':  bool(product.fitness_is_subscription_plan),
            'step':             'payment',
            'selected_method':  method if method in PAYMENT_METHODS else None,
            'payment_details':  self._payment_details(),
            'error_msg':        error_msg,
            'back_url':         f'/my/packages/{product.id}',
            'student_name':     full_name.split()[0] if full_name else '',
            'terms_label':      _('I agree to the'),
            'terms_link_label': _('Terms and Conditions'),
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

        full_name = partner.name or ''
        return request.render('fitness_portal.portal_order_detail', {
            'sale_order':   order,
            'student_name': full_name.split()[0] if full_name else '',
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
        today = fields.Date.today()

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
                period_end_str = sub.next_invoice_date.strftime('%d %b %Y')

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
            'sub_data':     sub_data,
            'has_sub':      bool(sub_data),
            'student_name': full_name.split()[0] if full_name else '',
        })

    # ══════════════════════════════════════════════════════════
    #  Notifications API
    # ══════════════════════════════════════════════════════════

    @http.route('/my/notifications/count', type='http', auth='user',
                website=True, sitemap=False, methods=['GET'])
    def notifications_count(self, **kw):
        count = request.env['fitness.notification'].sudo().search_count([
            ('user_id', '=', request.env.user.id),
            ('read', '=', False),
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
            'is_new':   not n.read,
            'time_ago': _time_ago(now - n.create_date, _),
        } for n in notifs]
        unread_count = sum(1 for e in entries if e['is_new'])

        # Persist read state now — re-opening the archive will show all as read.
        if unread_count:
            notifs.filtered(lambda n: not n.read).write({'read': True})

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
            ('user_id', '=', request.env.user.id), ('read', '=', False),
        ]).write({'read': True})
        return request.redirect('/my/notifications')

    @http.route('/my/notifications/data', type='http', auth='user',
                website=True, sitemap=False, methods=['GET'])
    def notifications_list(self, **kw):
        _ = request.env._
        notif_model = request.env['fitness.notification'].sudo()
        notifs = notif_model.search(
            [('user_id', '=', request.env.user.id)], limit=20
        )
        now = fields.Datetime.now()
        result = []
        for n in notifs:
            time_ago = _time_ago(now - n.create_date, _)
            result.append({
                'id': n.id,
                'title': n.title,
                'body': n.body or '',
                'read': n.read,
                'time_ago': time_ago,
                'type': n.notification_type,
            })
        notifs.filtered(lambda n: not n.read).write({'read': True})
        return request.make_response(
            json.dumps({'notifications': result}),
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

    def _primary_credit(self, partner_id):
        """Return the soonest-expiring active pack's credit info, or None."""
        _ = request.env._
        today = fields.Date.today()
        lines = request.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner_id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ], order='fitness_validity_end_date asc nulls last')
        for line in lines:
            vend = line.fitness_validity_end_date
            if vend and vend < today:
                continue
            ct = getattr(line.product_id, 'fitness_class_type', 'any') or 'any'
            label = {
                'barre': _('barre credits'),
                'reformer': _('reformer credits'),
            }.get(ct, _('class credits'))
            remaining = line.fitness_remaining_classes
            total = line.fitness_original_class_count
            credits_available_text = (_('%d %s available') % (remaining, label))
            return {
                'remaining':              remaining,
                'total':                  total,
                # Pre-rendered so templates never mix a number, a separator and
                # a t-directive inside one node — that produces junk msgids.
                'display':                ('%s / %s' % (remaining, int(total))) if total else str(remaining),
                'label':                  label,
                'credits_available_text': credits_available_text,
            }
        return None

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

    @http.route('/my/message-studio', type='http', auth='user', website=True, sitemap=False)
    def message_studio_page(self, **kw):
        if not (request.env.user.has_group(STUDENT_GROUP) or
                request.env.user.has_group('fitness_core.group_fitness_teacher')):
            return request.redirect('/my')
        return request.render('fitness_portal.portal_message_studio', {
            'sent':  bool(kw.get('sent')),
            'error': kw.get('error'),
        })

    @http.route('/my/message-studio/send', type='http', auth='user',
                methods=['POST'], website=True, sitemap=False)
    def message_studio_send(self, body=None, **kw):
        import html as _html
        if not (request.env.user.has_group(STUDENT_GROUP) or
                request.env.user.has_group('fitness_core.group_fitness_teacher')):
            return request.redirect('/my')

        body = (body or '').strip()
        if not body:
            return request.redirect('/my/message-studio?error=empty')
        if len(body) > 2000:
            return request.redirect('/my/message-studio?error=toolong')

        Channel = request.env['discuss.channel'].sudo()
        channel = Channel.search([('name', '=', 'Studio Messages')], limit=1)
        if not channel:
            channel = Channel.create({
                'name': 'Studio Messages',
                'channel_type': 'channel',
                'description': 'Messages from students and teachers to the studio.',
            })
            try:
                admin_partner = request.env.ref('base.user_admin').sudo().partner_id
                channel.add_members([admin_partner.id])
            except Exception:
                pass

        user = request.env.user
        sender = user.partner_id.name or user.name or 'Portal User'
        role = 'Teacher' if user.has_group('fitness_core.group_fitness_teacher') else 'Student'
        msg_html = (
            f'<strong>[{role}] {_html.escape(sender)}</strong><br/>'
            f'{_html.escape(body).replace(chr(10), "<br/>")}'
        )
        channel.message_post(
            body=msg_html,
            author_id=user.partner_id.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return request.redirect('/my/message-studio?sent=1')

    # ══════════════════════════════════════════════════════════
    #  Language
    # ══════════════════════════════════════════════════════════

    @http.route('/my/language', type='http', auth='user', website=True, sitemap=False)
    def language_picker(self, **kw):
        mv_lang = request.httprequest.cookies.get('mv_lang') or request.env.lang or 'en_US'
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
