import base64
import binascii
import json
import logging
from datetime import timedelta, datetime as _dt_cls, date as _date_cls
from dateutil.relativedelta import relativedelta as _relativedelta
from itertools import groupby as _groupby
from urllib.parse import quote, urlencode


# The studio, the site and the portal are Spanish-first, so anything with
# no language set falls back to Spanish rather than to Odoo's English base.
DEFAULT_LANG = 'es_ES'

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
from odoo.tools import float_is_zero
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

# The booking rule itself lives on the model; importing it keeps the
# timetable's "booking opens ..." notice honest if the studio changes it.
from odoo.addons.fitness_bookings.models.fitness_booking import (
    BOOKING_WINDOW_DAYS, fitness_opening_date)
from odoo.addons.fitness_core import class_colors

try:
    from odoo.addons.payment.controllers.portal import PaymentPortal as _OdooPaymentPortal
    _PAYMENT_OK = True
except Exception:
    _OdooPaymentPortal = http.Controller
    _PAYMENT_OK = False

STUDENT_GROUP = 'fitness_core.group_fitness_student'
TEACHER_GROUP = 'fitness_core.group_fitness_teacher'
LOOK_AHEAD_DAYS = 14
# The Available list opens on the month.
#
# It used to default to a week, and a week is often empty: the studio does not
# run classes every day, and around opening there were none at all in the next
# seven. A student landing on a blank page concludes the studio has no classes
# rather than that this particular week is quiet, and nothing on the page
# corrects them. A month is nearly always populated, and Today and This week
# are one tap away for anyone who wants them.
DEFAULT_LOOK_AHEAD_DAYS = 30
# Today / this week / this month. "This month" is a rolling 30 days rather
# than to the end of the calendar month: the window is expressed in days
# everywhere below, and a calendar month would give a student on the 29th a
# two-day "month". A link still holding the old days=14 falls back to the
# default week rather than 404ing.
RANGE_CHOICES = (1, 7, 30)

# Mirror of constants in fitness_subscriptions.models.sale_order

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

        # The hero's trial button points at the news post carrying a call to
        # action - the trial announcement. These posts are created as data and
        # have no xmlid, so there is nothing stable to ref(); "the post with a
        # CTA" is the marker. None found means no button, rather than a button
        # that goes somewhere arbitrary.
        _trial_post = request.env['fitness.news.post'].search(
            [('cta_url', '!=', False)], order='sequence asc, id asc', limit=1
        )
        trial_post_url = (('/my/news/%d?back=/my/home' % _trial_post.id)
                          if _trial_post else False)

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
             'label': _('Class Types'), 'status': _('No active class'),
             'cta': _('View class types'), 'href': '/my/packages?tab=classes'},
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
            'lbl_explore_shop': _('Explore packages, memberships & class types'),
            'news_posts':       news_posts,
            'trial_post_url':   trial_post_url,
            'lbl_book_trial':   _('Book a Free Trial'),
            # Offered only while there is one to take. Once it is spent the
            # prompt would be an invitation to something they cannot have.
            'trial_offer_url':  ('/my/trial'
                                 if not self._trial_entitlement_used(partner)
                                 else False),
            'lbl_trial_offer':  _('Book your free trial class'),
            'lbl_lets_book':    _("Let's book your first class."),
            'lbl_timetable':      _('Weekly Timetable'),
            'lbl_install_title':   _('Install CoreLab'),
            'lbl_install_sub':     _('Add it to your home screen for one-tap booking.'),
            'lbl_install_cta':     _('Install'),
            'lbl_install_dismiss': _('Not now'),
            'lbl_ios_title':       _('Add CoreLab to your Home Screen'),
            'lbl_ios_step1':       _('Tap the Share button at the bottom of Safari.'),
            'lbl_ios_step2':       _('Scroll down and tap "Add to Home Screen".'),
            'lbl_ios_step3':       _('Tap "Add" in the top right corner.'),
            # Not a step list. Only iOS gets numbered instructions, because
            # only iOS has no way to install from the page at all. Any other
            # browser that did not offer a prompt gets one sentence pointing
            # at its own menu - there is no button we could give it that
            # would work.
            'lbl_gen_note':        _('Your browser installs apps from its own menu: '
                                     'look for "Install app" or "Add to Home screen".'),
            'lbl_ios_foot':        _('CoreLab will then open like any other app, without the browser bars.'),
            'lbl_timetable_desc': _('Every class we run, week by week'),
            'lbl_timetable_cta':  _('View timetable'),
        })

    # ══════════════════════════════════════════════════════════
    #  STUDIO  (bottom-nav tab 2 — "Available" | "My Schedule")
    # ══════════════════════════════════════════════════════════

    @http.route('/my/studio', type='http', auth='user', website=True, sitemap=False)
    def studio(self, view=None, booked=None, cancelled=None, credit_returned=None,
               error=None, days=None, discipline=None, trial=None, **kw):
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        active_view = 'schedule' if view == 'schedule' else 'available'

        values = {
            'active_view':     active_view,
            # Which room's tab opens. Set when a student has just taken a
            # trial, so they land on the discipline they chose rather than
            # having to find it among both.
            'active_discipline': (discipline
                                  if discipline in ('barre', 'reformer')
                                  else False),
            # Shown while the credit is unspent, however they got here.
            'just_took_trial':  bool(self._unused_trial_credit(partner)),
            'lbl_trial_next':   request.env._(
                'Your free trial class is waiting - pick any class below and '
                'book it. Booking opens a week before each class.'),
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

    def _calendar_labels(self, _):
        """Strings the shared calendar needs, in one place for all three pages."""
        dow = [d[:3] for d in self._weekday_labels()]
        return {
            'cal_dow': dow,
            # The calendar formats its own period heading in the browser, and
            # <html lang> is empty on these pages - without this it silently
            # formatted every language's dates in Spanish.
            'cal_lang': (request.env.lang or DEFAULT_LANG).replace('_', '-'),
            'lbl_cal_day': _('Day'),
            'lbl_cal_week': _('Week'),
            'lbl_cal_month': _('Month'),
            'lbl_cal_none': _('No classes in this period.'),
            # The date dropdown formats itself in the browser; this is the one
            # string in it that is not a date.
            'lbl_all_dates': _('All dates'),
            'lbl_cal_open': _('Calendar view'),
            'lbl_cal_list': _('List view'),
        }

    @staticmethod
    def _discipline_tabs(types, _):
        """The two-room toggle, or nothing.

        Only Reformer and Barre are rooms a student picks between - 'any' and
        blank are class types that belong to neither, and they stay visible
        under whichever tab is showing rather than being filtered away into
        somewhere with no tab.

        Returned empty unless BOTH rooms are actually present: a toggle whose
        other side is always empty is worse than no toggle, and the studio runs
        weeks where only one room has classes a given student can book.
        """
        rooms = [t for t in ('reformer', 'barre') if t in types]
        if len(rooms) < 2:
            return []
        labels = {'reformer': _('Reformer'), 'barre': _('Barre')}
        return [{'key': t, 'label': labels[t]} for t in rooms]

    def _available_values(self, partner, days=None):
        """Day-grouped list of bookable classes (the 'Available' view).

        The window defaults to a week. Loading the full fourteen days put
        every class in the DOM at once, which on a phone meant a page tens
        of thousands of pixels tall before the student saw anything useful.
        """
        _ = request.env._
        lang = request.env.lang or DEFAULT_LANG
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

        # Classes before the studio opens stay listed. Filtering them out
        # emptied this page: the default window is seven days, and on 9 Sept
        # every class inside it fell before opening, so the student saw a
        # blank page and concluded there were no classes at all. They are
        # shown as not-yet-bookable instead, which is what the page already
        # does for the seven-day booking window.
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

        # The two-room toggle replaces the old All/Reformer/Barre chip row:
        # one control per question, and it matches the toggle the timetable and
        # the shop already use.
        ct_types = {(ev.class_type_id.classroom_type or '') for ev in events if ev.class_type_id}
        discipline_tabs = self._discipline_tabs(ct_types, _)

        cal_days, cal_meta = request.env['fitness.calendar.grid'].build(
            events, user_tz, today_local,
            dow_labels=[d[:3] for d in self._weekday_labels()])

        return {
            'events':          events,
            'grouped_events':  grouped_events,
            'has_sources':     bool(eligible_types),
            'look_ahead_days': sel_days,
            'sel_days':        sel_days,
            'range_chips':     [
                {'days': 1,  'label': _('Today')},
                {'days': 7,  'label': _('This week')},
                {'days': 30, 'label': _('This month')},
            ],
            'today_local':     today_local,
            'subtitle':        subtitle,
            'empty_state':     _('No classes available in the next %d days for your plan. Check back soon!') % sel_days,
            'no_sources_msg':  _('Time to move! Pick a membership, package, or class and reserve your spot.'),
            'no_sources_cta':  _('See options'),
            'discipline_tabs': discipline_tabs,
            # Same grid the timetable and My Schedule use, given this page's
            # own set of classes: what this student may actually book.
            'calendar_days': cal_days,
            'calendar_meta': cal_meta,
            **self._calendar_labels(_),
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
        lang = request.env.lang or DEFAULT_LANG
        now = fields.Datetime.now()

        # No look-ahead cap. This used to stop at 28 days, which meant a class
        # the studio had confirmed could sit outside the student's own view of
        # their schedule - approving a trial into a slot five weeks out left
        # the student with a booking they could not see anywhere. Any number
        # chosen here would have the same failure the first time somebody books
        # further ahead than it, so the window is gone rather than widened:
        # every confirmed future booking is listed.
        bookings = request.env['fitness.booking'].search([
            ('student_id', '=', partner.id),
            ('state', '=', 'booked'),
            ('class_start', '>', now),
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

        bk_types = {(b.class_type_id.classroom_type or '') for b in bookings if b.class_type_id}
        discipline_tabs = self._discipline_tabs(bk_types, _)

        # Only this student's own classes, and every one of them is booked by
        # definition, so the grid marks them all as such.
        own_events = bookings.mapped('calendar_event_id')
        cal_days, cal_meta = request.env['fitness.calendar.grid'].build(
            own_events, user_tz, today_local, booked_event_ids=set(own_events.ids),
            dow_labels=[d[:3] for d in self._weekday_labels()])

        return {
            'grouped_bookings':  grouped,
            'has_sources':       has_sources,
            'no_sources_msg':    _('Time to move! Pick a membership, package, or class and reserve your spot.'),
            'no_sources_cta':    _('See options'),
            'subtitle':          _('Upcoming classes'),
            'schedule_empty':    _('No upcoming classes.'),
            'discipline_tabs':   discipline_tabs,
            'calendar_days':     cal_days,
            'calendar_meta':     cal_meta,
            **self._calendar_labels(_),
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

        # The booking window is decided here rather than left to the booking
        # route. That route can only answer by redirecting to /my/studio with
        # the error in the query string, which threw the student off the page
        # they were reading. Checking first means the page can simply say when
        # booking opens, and never offer a button that cannot work.
        # Seven days before the class, and nothing else. Taking the later of
        # this and the studio's opening date looked sensible and was not: a
        # class on the 17th then advertised "booking opens 17 Sep", the same
        # day it runs. The opening date decides which classes may be booked at
        # all, not when booking opens for the ones that qualify - a class on or
        # after opening follows the ordinary rule, so the 17th opens on the
        # 10th exactly as every other class does.
        opens_at = event.start - timedelta(days=BOOKING_WINDOW_DAYS)
        in_window = opens_at <= now

        can_book = (
            not existing
            and bool(eligible_types)
            and discipline_ok
            and in_window
            and (seats_left is None or seats_left > 0)
            and event.start > now
        )

        # Exactly one state drives the call to action. Ordered by what the
        # student can actually act on: no point saying "booking opens Tuesday"
        # to someone who has nothing to book it with, or offering either to
        # someone looking at a class that is already full.
        if existing:
            book_state = 'booked'
        elif event.start <= now:
            book_state = 'past'
        elif seats_left == 0:
            book_state = 'full'
        elif not (eligible_types and discipline_ok):
            book_state = 'buy'
        elif not in_window:
            book_state = 'not_open'
        else:
            book_state = 'book'

        shop_href = '/my/packages?%s' % urlencode({
            'tab': 'classes',
            'discipline': event.class_type_id.classroom_type or 'reformer',
        })

        user_tz = self._user_tz()
        local_start = pytz.UTC.localize(event.start).astimezone(user_tz)
        local_stop = pytz.UTC.localize(event.stop).astimezone(user_tz)

        _ = request.env._
        lang = request.env.lang or DEFAULT_LANG

        if _BABEL_OK:
            try:
                local_date_label = _babel_format_date(
                    local_start.date(), format='EEEE, d MMMM', locale=lang,
                ).capitalize()
            except Exception:
                local_date_label = local_start.strftime('%A, %d %B')
        else:
            local_date_label = local_start.strftime('%A, %d %B')

        minutes = int(round((event.stop - event.start).total_seconds() / 60)) if event.stop else 0
        if minutes >= 60 and minutes % 60 == 0:
            hours = minutes // 60
            duration_label = _('%d h') % hours
        elif minutes > 60:
            duration_label = _('%(h)d h %(m)d min') % {'h': minutes // 60, 'm': minutes % 60}
        elif minutes:
            duration_label = _('%d min') % minutes
        else:
            duration_label = None

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
            'book_state':          book_state,
            'shop_href':           shop_href,
            'opens_on': (
                self._short_date(pytz.UTC.localize(opens_at).astimezone(user_tz))
                if book_state == 'not_open' else None
            ),
            'already_booked':      bool(existing),
            # The id, not just the boolean: the detail page can now cancel,
            # and /my/classes/<id>/cancel is keyed on the booking.
            'existing_booking':    existing,
            'seats_left':          seats_left,
            'seats_status_label':  seats_status_label,
            'duration_label':      duration_label,
            'lbl_description':     _('Description'),
            'lbl_duration':        _('Duration'),
            'lbl_instructor':      _('Instructor'),
            'lbl_room':            _('Room'),
            'lbl_studio_note':     _('Note from the studio'),
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
        lang_code = (request.lang.code if request.lang else None) or DEFAULT_LANG
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
            # The opening offer is now a discount on the five base plans rather
            # than a free extra class, so there is no window-based bonus to
            # synthesise here any more - only what the product itself grants.
            effective_bonus = bonus

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
        # Classes is the first tab, so it is also what the bare URL shows.
        # 'packages' has to be matched explicitly now that it is no longer the
        # fallback - ?tab=packages was already a live link before this change.
        active_tab = ('subscriptions' if tab == 'subscriptions'
                      else 'packages' if tab == 'packages'
                      else 'classes')
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

        # Which cards get a one-tap Book button, and which have already been
        # used. Worked out here in two passes over the products rather than
        # asked per card in the template, which would be a query a card.
        free_ids = frozenset(p.id for p in products
                             if self._is_free_for(partner, p))
        claimed_ids = frozenset(
            p.id for p in products
            if p.id in free_ids and self._free_already_claimed(partner, p))

        # A spent trial carries no special state of its own any more. It is
        # simply a product this student is not entitled to for free, which
        # _is_free_for has already decided - so it falls through to the same
        # price-and-Buy card as any other class and needs nothing here, and
        # stays on the page afterwards exactly as every other product does.

        # Only the trial is priced per student, and the price tag renders
        # from the product, which cannot know whose trial is spent. Hand it
        # the answer rather than teaching the product about students.
        student_price = {}
        for p in products:
            if self._is_trial_product(p):
                student_price[p.id] = self._student_price(partner, p)

        # The Reformer trial is requested, not booked, so "already claimed"
        # does not describe it while the studio is still deciding: a pending
        # request creates no order, so nothing here suppressed the button and
        # the card invited a second request as though the first had not
        # happened.
        pending_trial_ids = frozenset()
        if self._pending_reformer_request(partner):
            _rt = request.env.ref('fitness_packages.product_reformer_trial',
                                  raise_if_not_found=False)
            if _rt:
                pending_trial_ids = frozenset([_rt.id])

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
            'free_ids':                 free_ids,
            'claimed_free_ids':         claimed_ids,
            'pending_trial_ids':        pending_trial_ids,
            'lbl_trial_pending':        _('Request sent'),
            'student_price':            student_price,
            # Was a literal in the template, so it stayed English in Spanish
            # and Catalan. Harmless while only a bought package showed it;
            # Part D puts it on the trial card, where every student sees it.
            'lbl_active':               _('Active'),
            # A free trial is actually on offer to this student: one of the
            # trial products is priced at zero for them. The note above the
            # cards is about that offer, so it is what the note hangs on.
            'trial_offered':            bool(set(student_price) & free_ids),
            # Said once, above the two trial cards, because a student who takes
            # the wrong one has spent the only one they get.
            'lbl_trial_pick_one':       _('Your first class is free - choose '
                                          'Barre or Reformer. One trial per '
                                          'student, so pick the one you want '
                                          'to try.'),
            'booked':                   bool(kw.get('booked')),
            'error_msg':                kw.get('error') or '',
            'lbl_book_free':            _('Book'),
            'lbl_price_free':           _('Free'),
            'lbl_free_used':            _('Already used'),
            'lbl_free_terms':           _('Free — booking accepts the Terms'),
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
        lang_code = (request.lang.code if request.lang else None) or DEFAULT_LANG

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
                               ) else '/my/packages?tab=packages'),
            'ct':              product.fitness_class_type or 'any',
            # The detail page gets the same one-tap Book button as the card.
            'is_free':         self._is_free_for(partner, product),
            # The price tag renders from the product, which cannot know whose
            # trial is already spent. See _student_price.
            'price_override':  (self._student_price(partner, product)
                                if self._is_trial_product(product) else None),
            # Same rule as the shop grid: while the studio still has an
            # open Reformer request from this student, the product page
            # says so rather than offering to take another one.
            'trial_pending':   bool(self._is_reformer_trial(product)
                                    and self._pending_reformer_request(partner)),
            'lbl_trial_pending': _('Request sent'),
            'free_claimed':    (self._is_free_for(partner, product)
                                and self._free_already_claimed(partner, product)),
            'lbl_book_free':   _('Book'),
            'lbl_price_free':  _('Free'),
            'lbl_free_used':   _('Already used'),
            'lbl_free_terms':  _('Free — booking accepts the Terms'),
            'error_msg':       kw.get('error') or '',
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

    def _is_reformer_trial(self, product):
        """True for the one product that must be reviewed before booking.

        Resolved by xmlid rather than by price or discipline: the rule is about
        this specific product, and it must not lapse if the trial stops being
        free. Falls back to False when the xmlid is missing so a database
        without the seed record simply behaves as before.
        """
        ref = request.env.ref('fitness_packages.product_reformer_trial',
                              raise_if_not_found=False)
        return bool(ref) and product.id == ref.id

    @http.route('/my/trial', type='http', auth='user', website=True,
                sitemap=False)
    def portal_trial_choice(self, **kw):
        """The trial, on a page with nothing else on it.

        The home button used to open the shop with the classes tab selected,
        which showed the two trials among every other class, package and
        membership. One free choice presented as eleven paid ones is how
        students ended up on a checkout page they did not want.
        """
        _ = request.env._
        partner = request.env.user.partner_id
        # Spent entitlement, nothing left to choose. The shop still lists both
        # trials - as ordinary paid classes - so that is where this belongs.
        if self._trial_entitlement_used(partner):
            return request.redirect('/my/packages?tab=classes')

        trials = []
        for xmlid in self.TRIAL_XMLIDS:
            product = request.env.ref(xmlid, raise_if_not_found=False)
            if not product or not product.sudo().active:
                continue
            product = product.sudo()
            bits = []
            if product.fitness_class_count:
                bits.append(_('%d class') % product.fitness_class_count
                            if product.fitness_class_count == 1
                            else _('%d classes') % product.fitness_class_count)
            if product.fitness_validity_days:
                bits.append(_('%d day') % product.fitness_validity_days
                            if product.fitness_validity_days == 1
                            else _('%d days') % product.fitness_validity_days)
            trials.append({
                'id':         product.id,
                'ct':         product.fitness_class_type or 'any',
                'discipline': self._discipline_label(
                    product.fitness_class_type or 'any'),
                'name':       product.name,
                'meta':       ' \u00b7 '.join(bits),
            })

        return request.render('fitness_portal.portal_trial_choice', {
            'trials':      trials,
            'lbl_title':   _('Book your free trial class'),
            'lbl_pick_one': _('Choose only one - Barre or Reformer. Every '
                              'student gets one free trial, so pick the one '
                              'you want to try.'),
            'lbl_book_free': _('Book this trial'),
            'error_msg':   kw.get('error') or '',
        })

    @http.route('/my/packages/<int:product_id>/book-free', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'])
    def packages_book_free(self, product_id, **kw):
        """Book a free item in one tap, with no page in between.

        A checkout page exists to collect a payment method and a signature.
        A free trial has neither to collect, so the page was a screen whose
        only content was a button - the student tapped Buy to reach it and
        tapped again to leave. This is that second tap, moved onto the first.

        Every check the checkout route made still runs here, on the server:
        the price is read from the product rather than taken from the request,
        and the once-per-student rule is applied before anything is created.
        Losing the page must not mean losing the guards.
        """
        _ = request.env._
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        partner = request.env.user.partner_id
        product = request.env['product.template'].sudo().browse(product_id)
        back = kw.get('back') or '/my/packages'
        if not back.startswith('/my/'):
            back = '/my/packages'          # never bounce off-site on our say-so

        def fail(msg):
            return request.redirect('%s%serror=%s' % (
                back, '&' if '?' in back else '?', quote(msg)))

        if not product.exists() or not product.active or not product.sale_ok                 or not self._is_buyable(product):
            return request.redirect('/my/packages')

        # Both trials are self-service now. A logged-in student has an account,
        # so there is nothing for the studio to review before it can book: the
        # old Pending/Contacted/Scheduled round trip existed for people with no
        # account, and it still serves them from the public site.

        # Free is decided here, never by the form. A posted product id for
        # something that costs money goes to the paid flow.
        if not self._is_free_for(partner, product):
            return request.redirect(f'/my/packages/{product.id}/checkout')

        # One free trial per student, whichever discipline they picked. Checked
        # across both products, so taking the Barre trial spends the Reformer
        # one too - they are a single entitlement, not one of each.
        if self._is_trial_product(product):
            if self._trial_entitlement_used(partner):
                return fail(_('You have already used your free trial. '
                              'It is one per student, Barre or Reformer.'))
        elif self._free_already_claimed(partner, product):
            return fail(_('You have already used this free trial. '
                          'It is available once per student.'))

        order = self._create_order(partner, product, 'free')
        if not order:
            return request.redirect('/my/packages')
        if not self._order_is_free(order):
            # the product said free and the order disagrees; trust the order
            _logger.warning(
                '[CHECKOUT] Direct free booking for order %s totals %s; '
                'sending it to the paid flow instead.', order.name, order.amount_total)
            return request.redirect(f'/my/packages/pay/{order.id}')

        order.sudo().write({
            'signed_by': request.env.user.partner_id.name,
            'signed_on': fields.Datetime.now(),
            'fitness_terms_accepted_on': fields.Datetime.now(),
        })
        order.sudo().action_confirm()
        _logger.info('[CHECKOUT] Free order %s booked in one tap for partner %s '
                     '(product %s).', order.name, partner.id, product.id)
        self._notify_admins_of_purchase(order)

        # A trial is only worth having once it is on the timetable, so the
        # student is taken straight to the classes they can now book, in the
        # discipline they just chose, rather than back to the shop to work out
        # what to do next.
        if self._is_trial_product(product):
            disc = product.fitness_class_type or ''
            return request.redirect(
                '/my/studio?trial=1&discipline=%s' % quote(disc))
        return request.redirect('/my/packages?booked=1')

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

        # A free item has no checkout step at all any more, so the page is not
        # merely unlinked - reaching it by URL sends you back to the product,
        # where the Book button is. Leaving it renderable would have left two
        # ways to book the same thing, one of them the screen this removed.
        if self._is_free_for(partner, product):
            return request.redirect('/my/packages/%d' % product.id)

        # The plan the student picked, validated against what was offered. It
        # is read on GET as well as POST so choosing one can re-render the
        # page with that plan's totals before anything is committed.
        selected_plan = self._selected_plan(product, kw.get('plan_id'))

        error_msg = None
        method = kw.get('payment_method')
        if request.httprequest.method == 'POST':
            if use_online:
                # Online (Stripe) path: only terms acceptance needed.
                if not kw.get('terms_accepted'):
                    error_msg = _('Please accept the Terms and Conditions to continue.')
                else:
                    order = self._create_order(partner, product, 'stripe',
                                               plan=selected_plan)
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
                    order = self._create_order(partner, product, method,
                                               plan=selected_plan)
                    if not order:
                        return request.redirect('/my/packages')
                    return request.redirect(f'/my/checkout/{order.id}/sign')

        is_subscription = bool(product.fitness_is_subscription_plan)
        full_name = partner.name or ''
        return request.render('fitness_portal.portal_checkout_payment', {
            'product':            product,
            **self._checkout_totals(product, partner, selected_plan),
            'is_subscription':    is_subscription,
            'plan_options':       self._plan_options(
                product, partner, selected_plan) if is_subscription else [],
            'selected_plan_id':   selected_plan.id if selected_plan else False,
            'lbl_plan_heading':   _('Choose how you pay'),
            'lbl_plan_waiver':    _('Registration fee waived'),
            'lbl_matricula':      _('Registration (one-off)'),
            'step':               'payment',
            'selected_method':    method if method in PAYMENT_METHODS else None,
            'payment_details':    self._payment_details(),
            'error_msg':          error_msg,
            'back_url':           f'/my/packages/{product.id}',
            'student_name':       full_name.split()[0] if full_name else '',
            'terms_label':        _('I agree to the'),
            'terms_link_label':   _('Terms and Conditions'),
            # No free-item values here any more: a zero-price product never
            # reaches this template, it is redirected to its own page where
            # Book completes the booking. Passing them would only invite a
            # second checkout path to grow back.
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
        # An order that costs nothing has nothing to pay, so requiring a
        # successful transaction would make a free trial unconfirmable. The
        # test is the order's own total, computed server-side, not the method
        # recorded on it - a student cannot talk their way past it by asking
        # for method=free on something that costs money.
        #
        # It does have to carry the once-per-student rule too. A draft
        # abandoned before the first free trial was claimed is still reachable
        # at the signature step afterwards, and confirming it there would hand
        # out a second one.
        if self._order_is_free(order):
            line = order.order_line[:1]
            product = line.product_id.product_tmpl_id if line else None
            if product and self._free_already_claimed(order.partner_id, product):
                qs = urlencode({'error': _(
                    'You have already used this free trial. '
                    'It is available once per student.'
                )})
                return request.redirect(f'/my/packages?{qs}')
        elif order.fitness_payment_method not in PAYMENT_METHODS:
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
                                                 lang=manager.lang or DEFAULT_LANG))._
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

    # ══════════════════════════════════════════════════════════
    #  REFORMER TRIAL — the portal's own intake
    # ══════════════════════════════════════════════════════════
    #
    # auth='user'. The public /trial page exists for website visitors who have
    # no account; sending a logged-in student there gave them the login layout
    # and a "log in" link, and dropped them out of the portal entirely on
    # submit, with the confirmation shown on a page that has no way back.

    TRIAL_OPEN_STATES = ('pending', 'contacted')

    def _pending_reformer_request(self, partner):
        """This student's Reformer request that the studio has not closed yet.

        Pending or contacted, not scheduled or declined: those are finished,
        and a student whose trial has been and gone may ask for another.
        """
        if not partner:
            return request.env['fitness.trial.request'].sudo().browse()
        return request.env['fitness.trial.request'].sudo().search([
            ('partner_id', '=', partner.id),
            ('class_interest', '=', 'reformer'),
            ('status', 'in', list(self.TRIAL_OPEN_STATES)),
        ], order='id desc', limit=1)

    @http.route('/my/trial/reformer', type='http', auth='user',
                website=True, sitemap=False)
    def portal_trial_reformer(self, **kw):
        """The two intake questions, asked inside the portal."""
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        pending = self._pending_reformer_request(partner)

        return request.render('fitness_portal.portal_trial_reformer', {
            'partner':       partner,
            'pending':       pending,
            'submitted':     bool(kw.get('submitted')),
            'error_msg':     kw.get('error') or None,
            'back_url':      '/my/packages',
            'page_title':    _('Request a Reformer trial'),
            'lbl_intro':     _('The studio reviews Reformer trials before booking '
                               'them, so they can pick a class that suits your '
                               'experience. Two questions and they will be in touch.'),
            'lbl_first_q':   _('Is this your first time on a Reformer?'),
            'lbl_yes':       _('Yes, my first time'),
            'lbl_no':        _('No, I have used one before'),
            'lbl_years_q':   _('Roughly how long have you been practising?'),
            'lbl_notes_q':   _('Any days or times that suit you best? (optional)'),
            'lbl_submit':    _('Send request'),
            'lbl_pending':   _('Your request is with the studio'),
            'lbl_pending_b': _('They will confirm your class shortly. You will get '
                               'an email and a notification here as soon as it is '
                               'booked.'),
            'lbl_done':      _('Request sent'),
            'lbl_done_body': _('The studio has your request and will be in touch to '
                               'confirm your class.'),
            'lbl_back_shop': _('Back to the shop'),
        })

    @http.route('/my/trial/reformer/submit', type='http', auth='user',
                website=True, sitemap=False, methods=['POST'])
    def portal_trial_reformer_submit(self, **kw):
        """Create the request, then come back to this page with a confirmation.

        Redirect rather than render, so a refresh cannot post it twice.
        """
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id

        # One open request at a time. The button is hidden while one is open,
        # so reaching this means a stale tab or a typed URL.
        if self._pending_reformer_request(partner):
            return request.redirect('/my/trial/reformer')

        first_time = (kw.get('reformer_is_first_time') or '').strip()
        if first_time not in ('yes', 'no'):
            return request.redirect('/my/trial/reformer?error=%s' % quote(
                _('Please tell us whether this is your first time on a Reformer.')))

        vals = {
            'name':  partner.name or request.env.user.name,
            'email': partner.email or request.env.user.login,
            # res.partner carries no 'mobile' in this build; phone only.
            'phone': partner.phone or False,
            'class_interest': 'reformer',
            'partner_id': partner.id,
            'lang': request.env.user.lang or DEFAULT_LANG,
            'reformer_is_first_time': first_time,
            'preferred_time_notes': (kw.get('notes') or '').strip()[:1000] or False,
        }
        years = (kw.get('reformer_years_experience') or '').strip()[:40]
        if years and first_time == 'no':
            vals['reformer_years_experience'] = years

        try:
            req = request.env['fitness.trial.request'].sudo().create(vals)
        except Exception:
            _logger.exception('[TRIAL] Portal Reformer request failed for %s',
                              partner.id)
            return request.redirect('/my/trial/reformer?error=%s' % quote(
                _('Something went wrong. Please try again.')))

        _logger.info('[TRIAL] Portal Reformer request %s created for partner %s',
                     req.id, partner.id)
        return request.redirect('/my/trial/reformer?submitted=1')

    @http.route('/my/news/<int:post_id>', type='http', auth='user',
                website=True, sitemap=False)
    def news_detail(self, post_id, back=None, **kw):
        # A post is reachable from Home and from the News list, so a fixed
        # back link always sent half its readers to the wrong page. The page
        # that linked here says where it linked from; anything unexpected
        # falls back to Home, and never off-site on our say-so.
        post = request.env['fitness.news.post'].sudo().search([
            ('id', '=', post_id), ('active', '=', True),
        ], limit=1)
        if not post:
            return request.not_found()
        back_url = back if (back or '').startswith('/my/') else '/my/home'
        return request.render('fitness_portal.portal_news_detail', {
            'post':     post,
            'back_url': back_url,
        })

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

    def _checkout_totals(self, product, partner, plan=None):
        """The numbers on the order summary, computed once.

        The template used to multiply by 1.21 itself. That was invisible at
        full price - 25.00 x 1.21 is exactly 30.25 - and wrong the moment a
        discount produced a half-cent: the page said 27.22 and Stripe asked
        for 27.23, because Odoo rounds the tax the way the order does and a
        printf in the template does not.

        So the tax comes from the product's own taxes through compute_all,
        which is the same call the sale order line makes. The page and the
        charge are then the same arithmetic rather than two that agree by
        luck.

        The same reasoning now covers the billing period and the registration
        fee: a quarterly membership is three months charged at once, and the
        fee is a second line. Both are folded in here, so the summary and the
        order are built from one calculation instead of the page adding up one
        set of numbers while _create_order writes another.
        """
        def _taxed(prod, price):
            taxes = prod.taxes_id.filtered(
                lambda t: t.company_id == request.env.company)
            if not taxes:
                return price, price
            res = taxes.compute_all(
                price, currency=prod.currency_id, quantity=1.0,
                product=prod.product_variant_ids[:1], partner=partner)
            return res['total_excluded'], res['total_included']

        months = self._plan_months(plan) if plan else 1
        price = self._student_price(partner, product) * months
        subtotal, total = _taxed(product, price)

        matricula = self._matricula_due(partner, product, plan) if plan else \
            request.env['product.template'].browse()
        mat_subtotal = mat_total = 0.0
        if matricula:
            mat_subtotal, mat_total = _taxed(
                matricula, matricula.fitness_effective_price())

        return {
            'co_full':     (product.list_price or 0.0) * months,
            'co_discount': product.fitness_promo_saving * months,
            'co_subtotal': subtotal + mat_subtotal,
            'co_tax':      (total - subtotal) + (mat_total - mat_subtotal),
            'co_total':    total + mat_total,
            'co_currency': product.currency_id.symbol or '€',
            'co_months':   months,
            'co_matricula':       matricula or None,
            # Shown ex-tax, like the membership line above it, so the rows on
            # the summary actually add up to the total underneath them. The
            # tax-inclusive figure is the one the plan selector quotes, which
            # is what the student pays; mixing the two in one column made the
            # column wrong even while the total was right.
            'co_matricula_net':   mat_subtotal,
            'co_matricula_total': mat_total,
        }

    # ── Membership billing plans and the registration fee ────────────────
    #
    # A membership is sold on a billing plan, and the plan decides two things
    # the student needs to see before they commit: what they pay now, and
    # whether the registration fee applies. Both are worked out here so the
    # page, the order and the charge come from one calculation.

    # Yearly is deliberately not offered. It exists in the database, but the
    # studio has never priced a year - 12x the monthly price is an assumption,
    # not a decision, and it would be a real charge. Add it here once there is
    # a price for it.
    MEMBERSHIP_PLAN_XMLIDS = (
        'sale_subscription.subscription_plan_month',
        'fitness_subscriptions.subscription_plan_quarter',
    )
    MATRICULA_WAIVED_FROM_MONTHS = 3

    @staticmethod
    def _plan_months(plan):
        """How many months one billing period covers.

        Weeks and days are rounded down deliberately: they are not commitment
        periods the studio sells, and a plan that does not reach a month must
        not accidentally clear the three-month waiver.
        """
        if not plan:
            return 1
        value = plan.billing_period_value or 1
        unit = plan.billing_period_unit
        if unit == 'year':
            return value * 12
        if unit == 'month':
            return value
        if unit == 'week':
            return (value * 7) // 30
        if unit == 'day':
            return value // 30
        return 1

    # ── The free trial: one per student, either discipline ───────────────
    #
    # The studio gives a student one free trial, not one of each. The old rule
    # was per product, so somebody could take the Barre trial free and then the
    # Reformer trial free as well. These two products are one entitlement.

    TRIAL_XMLIDS = ('fitness_packages.product_barre_trial',
                    'fitness_packages.product_reformer_trial')
    def _trial_products(self):
        out = request.env['product.template'].sudo().browse()
        for xmlid in self.TRIAL_XMLIDS:
            p = request.env.ref(xmlid, raise_if_not_found=False)
            if p:
                out |= p.sudo()
        return out

    def _is_trial_product(self, product):
        return product.id in self._trial_products().ids

    def _trial_entitlement_used(self, partner):
        """Has this student already had their one free trial?

        Read from what happened rather than a flag: any confirmed order of
        either trial product that cost nothing. Drafts do not count - an
        abandoned checkout must not burn the entitlement - which is the same
        rule _free_already_claimed applies, widened from one product to both.
        """
        trials = self._trial_products()
        if not trials or not partner:
            return False
        variants = trials.mapped('product_variant_ids').ids
        if not variants:
            return False
        rounding = request.env.company.currency_id.rounding or 0.01
        lines = request.env['sale.order.line'].sudo().search([
            ('order_id.partner_id', '=', partner.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('product_id', 'in', variants),
        ])
        return any(float_is_zero(l.price_total or 0.0, precision_rounding=rounding)
                   for l in lines)

    def _unused_trial_credit(self, partner):
        """An unspent trial credit, if the student is holding one.

        Read from the credit itself rather than from how the student arrived.
        The prompt used to ride on a ?trial=1 in the URL, so it vanished the
        moment they navigated or reopened the app - which is exactly when
        somebody who has just taken a trial needs telling what to do with it.
        """
        trials = self._trial_products()
        if not trials or not partner:
            return request.env['sale.order.line'].sudo().browse()
        today = fields.Date.context_today(request.env.user)
        lines = request.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('product_id', 'in', trials.mapped('product_variant_ids').ids),
            ('fitness_remaining_classes', '>', 0),
        ])
        return lines.filtered(
            lambda l: not l.fitness_validity_end_date
            or l.fitness_validity_end_date >= today)[:1]

    def _matricula_product(self):
        product = request.env.ref('fitness_subscriptions.product_matricula',
                                  raise_if_not_found=False)
        return product.sudo() if product else product

    @staticmethod
    def _has_paid_membership_before(partner):
        """Has this student ever held a membership?

        Read from what actually happened rather than a flag somebody has to
        remember to set: any confirmed order carrying a subscription plan
        counts, whether it was made in the portal, the back office or an
        import. Drafts do not - the checkout reuses them, so an abandoned
        attempt must not make a first membership look like a second and skip
        the fee. The order being built right now is still draft when this is
        asked, which is what stops it excluding itself.
        """
        lines = request.env['sale.order.line'].sudo().search([
            ('order_id.partner_id', '=', partner.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('product_id.product_tmpl_id.fitness_is_subscription_plan', '=', True),
        ], limit=1)
        return bool(lines)

    def _matricula_due(self, partner, product, plan):
        """The registration fee product when it should be charged, else empty.

        Two conditions, both the studio's: it is a student's first membership,
        and the commitment is shorter than three months. Committing to three
        months or more waives it.
        """
        empty = request.env['product.template'].browse()
        if not product.fitness_is_subscription_plan:
            return empty
        matricula = self._matricula_product()
        if not matricula or not matricula.active:
            return empty
        if self._plan_months(plan) >= self.MATRICULA_WAIVED_FROM_MONTHS:
            return empty
        if self._has_paid_membership_before(partner):
            return empty
        return matricula

    def _membership_plans(self, product):
        """The billing plans a student may choose for this membership.

        The product's own plan is always included even if it is not one of the
        offered set, so a membership configured for something unusual in the
        back office still checks out on the plan it was configured with.

        Read as sudo throughout: sale.subscription.plan is a Sales model that
        portal users have no access to, and the student is being shown the
        studio's price list, not their own records.
        """
        plans = request.env['sale.subscription.plan'].sudo().browse()
        for xmlid in self.MEMBERSHIP_PLAN_XMLIDS:
            plan = request.env.ref(xmlid, raise_if_not_found=False)
            if plan:
                plan = plan.sudo()
                if plan.active:
                    plans |= plan
        own = product.sudo().fitness_subscription_plan_id
        if own and own.sudo().active:
            plans |= own.sudo()
        return plans.sorted(lambda p: (p.sequence, p.id))

    def _plan_options(self, product, partner, selected_plan):
        """What the plan selector renders, priced.

        Each option carries its own total, because the whole point of showing
        the choice is that the student can see what three months up front
        actually costs and what it saves them. The numbers come from the same
        helper the order summary uses, so the option they pick and the total
        they are then charged cannot disagree.
        """
        _ = request.env._
        options = []
        for plan in self._membership_plans(product):
            months = self._plan_months(plan)
            totals = self._checkout_totals(product, partner, plan)
            matricula = self._matricula_due(partner, product, plan)
            waived = (not matricula
                      and months >= self.MATRICULA_WAIVED_FROM_MONTHS
                      and not self._has_paid_membership_before(partner))
            if months == 1:
                cadence = _('Billed monthly')
            elif months % 12 == 0 and months >= 12:
                cadence = _('Billed yearly')
            else:
                cadence = _('Billed every %s months') % months
            options.append({
                'id':        plan.id,
                'name':      plan.name,
                'months':    months,
                'cadence':   cadence,
                'per_month': _('%(price)s per month') % {
                    'price': self._format_price(
                        product.fitness_effective_price(), product.currency_id)},
                'total':     totals['co_total'],
                'total_str': self._format_price(totals['co_total'],
                                                product.currency_id),
                'waives_matricula': waived,
                'selected':  plan.id == selected_plan.id if selected_plan else False,
            })
        return options

    def _selected_plan(self, product, plan_id):
        """The plan this checkout is for, never taken on trust from the form.

        A posted id is only honoured when it is one of the plans actually
        offered for this membership. Anything else - a stale form, a typed id,
        a plan that was withdrawn - falls back to the product's own plan
        rather than billing the student on something nobody offered them.
        """
        if not product.fitness_is_subscription_plan:
            return request.env['sale.subscription.plan'].sudo().browse()
        offered = self._membership_plans(product)
        try:
            wanted = int(plan_id or 0)
        except (TypeError, ValueError):
            wanted = 0
        if wanted:
            match = offered.filtered(lambda p: p.id == wanted)
            if match:
                return match[:1]
            _logger.info('[CHECKOUT] Plan %s is not offered for %s; using the '
                         'product default.', wanted, product.display_name)
        default = product.sudo().fitness_subscription_plan_id
        if default and default.sudo() in offered:
            return default.sudo()
        return offered[:1]

    def _student_price(self, partner, product):
        """What this student pays for this product today.

        Every other price on the shop is a property of the product alone.
        The trial is the exception: it is free once per student and an
        ordinary paid class afterwards, so this one price has to know who is
        asking. Asking the product would answer "free" forever, which is how
        a spent trial kept offering itself.
        """
        if (partner and self._is_trial_product(product)
                and self._trial_entitlement_used(partner)):
            return product.list_price or 0.0
        return product.fitness_effective_price()

    def _is_free_for(self, partner, product):
        """Does this cost this student nothing today?

        Asks the product for its effective price, then lets the student
        override it - a promotion, Free or 100% off, is what decides for
        everyone else. The card, the booking route and the checkout all read
        this one answer, so a spent trial is refused by the route for the
        same reason the card stopped offering it.
        """
        rounding = (product.currency_id.rounding
                    or request.env.company.currency_id.rounding or 0.01)
        return float_is_zero(self._student_price(partner, product),
                             precision_rounding=rounding)

    @staticmethod
    def _order_is_free(order):
        rounding = (order.currency_id.rounding
                    or request.env.company.currency_id.rounding or 0.01)
        return float_is_zero(order.amount_total or 0.0, precision_rounding=rounding)

    @staticmethod
    def _free_already_claimed(partner, product):
        """Has this student already taken this free item once?

        The rule the studio asked for is one free trial per student, and it is
        enforced on what actually happened rather than on a flag somebody has
        to remember to set: any *confirmed* order of this product that cost
        nothing counts, however it was created - portal, back office or import.

        Confirmed, not merely existing. A draft is an abandoned attempt: the
        checkout reuses drafts, so counting them would let one abandoned
        checkout block that student's first free trial for ever. The order
        being confirmed right now is still draft when this is asked, which is
        also what keeps it from refusing itself.

        Scoped to this product, which is how the rule was specified ("a free
        priced booking of that trial type"). If the studio ever runs two free
        trials at once and means one free trial in total, this is the single
        place that changes.
        """
        variant_ids = product.product_variant_ids.ids
        if not variant_ids:
            return False
        rounding = request.env.company.currency_id.rounding or 0.01
        lines = request.env['sale.order.line'].sudo().search([
            ('order_id.partner_id', '=', partner.id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('product_id', 'in', variant_ids),
        ])
        return any(float_is_zero(l.price_total or 0.0, precision_rounding=rounding)
                   for l in lines)

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
            # 'stripe' was missing, so a card order's own summary told the
            # student it was "paid by Not selected" on the signature step.
            'stripe':   _('Card (online)'),
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

    def _order_lines_for(self, partner, product, plan):
        """The lines this purchase should carry, priced.

        One place builds them, and the summary is priced from the same
        helpers, so what the student was shown and what the order charges
        cannot drift apart.
        """
        variant = product.product_variant_ids[:1]
        if not variant:
            return []
        months = self._plan_months(plan) if plan else 1
        lines = [{
            'product_id': variant.id,
            'product_uom_qty': 1,
            # The promotion price, not the list price, times the number of
            # months the period covers - a quarterly membership is three
            # months charged at once. This is the number the student was shown
            # and the number Stripe is asked for; a second calculation here is
            # how those two come apart.
            'price_unit': self._student_price(partner, product) * months,
            'fitness_class_type': product.fitness_class_type,
        }]
        # A combined package is sold at one price but grants two separate
        # pools, so it is written as two lines: the second carries the other
        # discipline and no price. Charging the whole amount on the first line
        # keeps the order total equal to the advertised price, while giving
        # the second pool a line of its own to count credits against - which
        # is what stops one discipline being spent on the other.
        if product.fitness_secondary_class_type:
            lines.append({
                'product_id': variant.id,
                'product_uom_qty': 1,
                # No price is written here at all. This line is flagged as a
                # pool rather than a sale, and sale.order.line computes both
                # price_unit and discount to zero for it - so a later
                # recompute produces the same answer instead of restoring the
                # full price and charging the membership twice.
                'fitness_is_secondary_pool': True,
                'fitness_class_type': product.fitness_secondary_class_type,
            })
        matricula = self._matricula_due(partner, product, plan)
        if matricula:
            mat_variant = matricula.product_variant_ids[:1]
            if mat_variant:
                lines.append({
                    'product_id': mat_variant.id,
                    'product_uom_qty': 1,
                    'price_unit': matricula.fitness_effective_price(),
                })
        return lines

    def _create_order(self, partner, product, method, plan=None):
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

        if product.fitness_is_subscription_plan and plan is None:
            plan = self._selected_plan(product, None)

        line_vals = self._order_lines_for(partner, product, plan)
        if not line_vals:
            return None

        existing = request.env['sale.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'draft'),
        ], order='id desc')
        for candidate in existing:
            lines = candidate.order_line
            # Ours to reuse only if it is for the same membership or pack. The
            # line count is not the test any more: a first membership carries a
            # registration line too, and switching plan can add or remove it,
            # so the draft is rebuilt from line_vals rather than patched.
            if not lines or lines[0].product_id.id != variant.id:
                continue
            if any(l.product_id.product_tmpl_id.id not in (
                    product.id, (self._matricula_product() or product).id)
                    for l in lines):
                continue        # something else was added to it; leave it be
            vals = {
                'fitness_payment_method': method,
                'fitness_terms_accepted_on': fields.Datetime.now(),
                # Rebuilt, not re-priced. A draft can be days old: a promotion
                # can have started or expired, and the student can have come
                # back on a different plan, which changes both the amount and
                # whether the registration fee belongs on it at all.
                'order_line': [(5, 0, 0)] + [(0, 0, v) for v in line_vals],
            }
            if plan and 'plan_id' in request.env['sale.order']._fields:
                vals['plan_id'] = plan.id
            candidate.write(vals)
            _logger.info(
                '[CHECKOUT] Reusing draft order %s for partner %s / product %s '
                '(plan=%s, %d line(s))',
                candidate.name, partner.id, variant.id,
                plan.name if plan else '-', len(line_vals))
            return candidate

        vals = {
            'partner_id': partner.id,
            'order_line': [(0, 0, v) for v in line_vals],
            'fitness_payment_method': method,
            'fitness_terms_accepted_on': fields.Datetime.now(),
        }

        # Subscription plans need a recurrence plan for Odoo to treat the order
        # as a subscription. Guarded so a database without the subscription app
        # simply creates a normal order.
        #
        # The plan is the student's choice, validated against what was actually
        # offered, falling back to the product's own. This used to be
        # search([], limit=1), which is not a choice but an accident of
        # ordering: it always returned Monthly, so Yearly could not be bought
        # from the portal at all and every membership was signed up monthly
        # whatever it had been sold as.
        if product.fitness_is_subscription_plan and 'plan_id' in request.env['sale.order']._fields:
            if not plan:
                # Named explicitly rather than taken off the top of the table,
                # so an unset product keeps today's behaviour instead of
                # changing the moment somebody adds a plan.
                plan = request.env.ref('sale_subscription.subscription_plan_month',
                                       raise_if_not_found=False)
                plan = plan.sudo() if plan else plan
                _logger.info(
                    "[CHECKOUT] %s has no billing plan set; falling back to "
                    "Monthly for order creation.", product.display_name)
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
            product = sub.fitness_subscription_product_id
            self._collect_type(eligible, product.fitness_class_type)
            # A combined membership entitles them to both disciplines, and the
            # second one is only named on the product.
            self._collect_type(eligible, product.fitness_secondary_class_type)

        lines = request.env['sale.order.line'].sudo().search([
            ('order_partner_id', '=', partner_id),
            ('product_id.fitness_is_package', '=', True),
            ('fitness_remaining_classes', '>', 0),
        ])
        for line in lines.filtered(lambda l: not l.fitness_is_expired):
            # The line's own pool discipline: a combo's two lines report one
            # each, so a member whose Barre pool is spent but whose Reformer
            # pool is not is offered Reformer only.
            self._collect_type(
                eligible, line.fitness_class_type or line.product_id.fitness_class_type)

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
    #  FULL WEEKLY TIMETABLE
    # ══════════════════════════════════════════════════════════

    # The studio's own timezone. Used only as a fallback for the timetable:
    # _user_tz() answers UTC when a student has no tz set, and on a page whose
    # entire purpose is "what time is this class" that would silently show
    # every slot two hours out. A physical studio's timetable is far better
    # defaulted to the studio's clock than to UTC.
    STUDIO_TZ = 'Europe/Madrid'

    def _timetable_tz(self):
        student_tz = request.env.user.tz
        try:
            return pytz.timezone(student_tz or self.STUDIO_TZ)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone(self.STUDIO_TZ)

    @http.route('/my/timetable', type='http', auth='user', website=True, sitemap=False)
    def timetable(self, discipline=None, **kw):
        """The studio's full weekly timetable, independent of what a student owns.

        A reference view, deliberately distinct from /my/studio: that page
        answers "what can I book right now" and hides everything a student has
        no credit for. This one answers "what does the studio run, and when",
        which a student needs before deciding what to buy.

        Rows come from fitness.class.schedule - the recurring definitions the
        studio actually edits - so there is no second copy of the timetable to
        drift. Each row is then matched to its next real occurrence through
        recurrence_id, which is what makes a slot tappable and gives the times
        a concrete instant to be converted from (a weekday plus a float hour
        cannot be converted across a DST boundary on its own).

        BOTH disciplines are rendered and the toggle switches them client-side.
        The first version navigated between two URLs, which reloaded the page
        and made the view jump as the browser restored scroll against a
        different layout height. Nothing here is secret, the payload is small,
        and swapping a class on two containers cannot jump.
        """
        if not request.env.user.has_group(STUDENT_GROUP):
            return request.redirect('/my')

        _ = request.env._
        partner = request.env.user.partner_id
        now = fields.Datetime.now()
        tz = self._timetable_tz()

        active = discipline if discipline in ('reformer', 'barre') else 'reformer'
        eligible_types = self._eligible_class_types(partner.id)

        schedules = request.env['fitness.class.schedule'].sudo().search([
            ('active', '=', True),
        ])

        # One batched read of upcoming occurrences for every schedule on the
        # page, then matched back in Python. Asking per row turned this into
        # one search per slot.
        recurrences = schedules.mapped('recurrence_id')
        upcoming = request.env['calendar.event'].sudo().search([
            ('recurrence_id', 'in', recurrences.ids),
            ('is_fitness_class', '=', True),
            ('class_state', '!=', 'cancelled'),
            ('start', '>', now),
        ], order='start asc')
        next_by_recurrence = {}
        for ev in upcoming:
            next_by_recurrence.setdefault(ev.recurrence_id.id, ev)

        booked_event_ids = set(
            request.env['fitness.booking'].search([
                ('student_id', '=', partner.id),
                ('state', 'in', ('booked', 'no_show')),
                ('class_start', '>', now),
            ]).mapped('calendar_event_id.id')
        )

        day_names = self._weekday_labels()
        buckets = {'reformer': {}, 'barre': {}}

        for sched in schedules:
            disc = sched.class_type_id.classroom_type
            if disc not in buckets:
                continue
            ev = next_by_recurrence.get(sched.recurrence_id.id)
            if not ev:
                # Schedule ended, or the horizon cron has not run. There is no
                # class to show and nothing to link to, and a row that cannot
                # be tapped is exactly what this page is meant not to have.
                continue
            local = pytz.UTC.localize(ev.start).astimezone(tz)
            time_label = local.strftime('%H:%M')
            weekday = local.weekday()

            already = ev.id in booked_event_ids
            seats_left = max(0, ev.capacity - ev.booked_seats) if ev.capacity else None

            # Every row is an ordinary link to the class's own page, which is
            # where the three booking states are explained. The grid used to
            # decide them itself and render unbookable classes as dead rows,
            # so a student could see a class and have no way to find out why
            # they could not have it.
            state = 'book'
            if already:
                state = 'booked'
            elif seats_left == 0:
                state = 'full'

            buckets[disc].setdefault(weekday, []).append({
                'time': time_label,
                'name': sched.class_type_id.name,
                # Reformer reads blue and Barre brown, so the two rooms are
                # tellable apart in the list and not only by which tab is
                # selected. One flat colour per discipline, matching the
                # toggle: the per-class-type shading in class_colors is held
                # back for the calendar view. One class sets the background
                # and its measured text colour together.
                'shade': class_colors.solid_class(disc),
                'desc': sched.class_type_id.description or '',
                'teacher': sched.teacher_user_id.name or '',
                'room': sched.classroom_id.name or '',
                'state': state,
                'href': '/my/classes/%d' % ev.id,
                'event_id': ev.id,
            })

        disciplines = {}
        for disc, by_weekday in buckets.items():
            days = []
            for idx in range(7):
                slots = sorted(by_weekday.get(idx, []), key=lambda s: s['time'])
                if slots:
                    days.append({'label': day_names[idx], 'slots': slots})
            disciplines[disc] = days

        # The list on this page is the weekly pattern - one row per schedule,
        # showing its next occurrence. The calendar wants the opposite: every
        # occurrence on the date it actually falls on. 'upcoming' is already
        # that set, batched above, so no second query.
        cal_days, cal_meta = request.env['fitness.calendar.grid'].build(
            upcoming, tz, now.astimezone(tz).date() if now.tzinfo
            else pytz.UTC.localize(now).astimezone(tz).date(),
            booked_event_ids=booked_event_ids,
            dow_labels=[d[:3] for d in self._weekday_labels()])

        return request.render('fitness_portal.portal_timetable', {
            'page_name': 'timetable',
            'calendar_days': cal_days,
            'calendar_meta': cal_meta,
            **self._calendar_labels(request.env._),
            'disciplines': disciplines,
            'active_discipline': active,
            'has_credit': bool(eligible_types),
            'tz_label': str(tz),
            'title': _('Timetable'),
            'subtitle': _('Every class we run, week by week'),
            'lbl_reformer': _('Reformer'),
            'lbl_barre': _('Barre'),
            'lbl_empty': _('No classes scheduled for this discipline yet.'),
            'lbl_booked': _('Booked'),
            'lbl_full': _('Full'),
            'lbl_open': _('Open'),
            'lbl_buy_hint': _('You have no credit for these classes yet — tap any class to see the options.'),
        })

    def _short_date(self, dt):
        """"Mon 8 Sep" in the active language, for the booking-window notice."""
        lang = request.env.lang or DEFAULT_LANG
        if _BABEL_OK:
            try:
                return _babel_format_date(dt.date(), format='EEE d MMM', locale=lang)
            except Exception:
                pass
        return dt.strftime('%d/%m')

    def _weekday_labels(self):
        """Monday-first weekday names in the active language."""
        lang = request.env.lang or DEFAULT_LANG
        if _BABEL_OK:
            try:
                # 2024-01-01 was a Monday, so +idx walks Mon..Sun.
                base = _date_cls(2024, 1, 1)
                return [
                    _babel_format_date(base + timedelta(days=i), format='EEEE',
                                       locale=lang).capitalize()
                    for i in range(7)
                ]
            except Exception:
                pass
        _ = request.env._
        return [_('Monday'), _('Tuesday'), _('Wednesday'), _('Thursday'),
                _('Friday'), _('Saturday'), _('Sunday')]

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

        role = 'Instructor' if is_teacher else 'Student'

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
    def set_lang(self, lang=DEFAULT_LANG, redirect='/my', **kw):
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


def _day_label(d, today, tomorrow, _=lambda s: s, lang=DEFAULT_LANG):
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
