# -*- coding: utf-8 -*-
"""A fixed-class member's weekly hours are placed from now on, never into the past.

Placement bypasses the booking checks - "class has already started"
included - and every caller but the nightly job booked from the FIRST DAY
of the billing period. A member who chose her hours a week after paying
(the card path never sent her to choose them) was booked into the classes
already over, told "your place is reserved" for each, and those filled
her allowance of 4 per weekly hour per month, so the last week of her
period was never booked. Every placed class also told her "No credits
remaining", because that notice only ever counted packs.

The clock is pinned and the language explicit in every test. The
timetable is a real weekly schedule (placement follows recurrence_id).

  PIN = Tue 13 Oct 2026 10:00 Madrid. Her period: Mon 5 Oct - Thu 5 Nov.
  Her hours: Monday 07:00 and Monday 08:00. Mondays in the period:
  5, 12 (over), 19, 26 Oct, 2 Nov.
"""
import re
from datetime import date, datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.addons.fitness_notifications.models import web_push
from odoo.addons.fitness_notifications.models.push_subscription import (
    PARAM_PRIVATE, PARAM_PUBLIC)
from odoo.tests import HttpCase, TransactionCase, common, tagged

PIN = datetime(2026, 10, 13, 8, 0)             # Tue 13 Oct 10:00 Madrid (UTC)
PERIOD_START = date(2026, 10, 5)               # Monday
MANAGER = 'fitness_core.group_fitness_manager'
TEACHER = 'fitness_core.group_fitness_teacher'
STUDENT = 'fitness_core.group_fitness_student'
PW = 'Fixed-future-26'


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi)


class FixedFixture:

    @classmethod
    def _fixture(cls):
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.room = env['fitness.classroom'].sudo().create({
            'name': 'FF Room', 'classroom_type': 'reformer', 'capacity': 6})
        cls.ctype = env['fitness.class.type'].sudo().create({
            'name': 'FF Reformer', 'classroom_type': 'reformer',
            'session_type': 'group', 'level': 'all', 'classroom_id': cls.room.id})
        cls.plan = env['sale.subscription.plan'].sudo().create({
            'name': 'FF Mensual', 'billing_period_value': 1, 'billing_period_unit': 'month'})
        cls.product = env['product.template'].sudo().create({
            'name': 'FF Reformer Fixed 2', 'type': 'service', 'list_price': 130.0,
            'sale_ok': True, 'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_is_clase_fija': True, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group', 'weekly_class_allowance': 2,
            'fitness_subscription_plan_id': cls.plan.id})
        cls.teacher = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'FF Teacher', 'login': 'ff.teacher@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id, env.ref(TEACHER).id])]})

    def _student(self, tag, lang='en_US'):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'FF %s' % tag, 'login': 'ff.%s@example.invalid' % tag,
            'email': 'ff.%s@example.invalid' % tag, 'password': PW, 'lang': lang,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref(STUDENT).id])]})

    def _schedule(self, hour, weekday='mon', start=PERIOD_START, weeks=8):
        s = self.env['fitness.class.schedule'].sudo().create({
            'name': 'FF %s %s' % (weekday, hour), 'class_type_id': self.ctype.id,
            'classroom_id': self.room.id, 'weekday': weekday, 'start_time': float(hour),
            'duration': 1.0, 'date_start': start, 'horizon_weeks': weeks,
            'teacher_user_id': self.teacher.id})
        s.action_generate()
        return self.env['calendar.event'].sudo().search(
            [('recurrence_id', '=', s.recurrence_id.id)], order='start')

    def _membership(self, user, start=PERIOD_START):
        so = self.env['sale.order'].sudo().create({
            'partner_id': user.partner_id.id, 'plan_id': self.plan.id, 'start_date': start})
        self.env['sale.order.line'].sudo().create({
            'order_id': so.id, 'product_id': self.product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 130.0})
        so.action_confirm()
        return so

    def _hours(self, so, *anchors):
        for a in anchors:
            self.env['fitness.clase.fija'].sudo().create(
                {'subscription_id': so.id, 'calendar_event_id': a.id})

    def _booked(self, so):
        return self.env['fitness.booking'].sudo().search(
            [('subscription_id', '=', so.id), ('state', '!=', 'cancelled')],
            order='class_start').mapped('class_start')


@tagged('post_install', '-at_install')
class TestPlacementOnlyFuture(FixedFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()

    def _late_member(self, tag='late', lang='en_US'):
        """Bought 5 Oct, chooses Monday 07:00 and 08:00 at PIN."""
        with common.freeze_time(PIN - timedelta(days=8)):
            mon7 = self._schedule(7)
            mon8 = self._schedule(8)
            user = self._student(tag, lang)
            so = self._membership(user)
        return user, so, mon7, mon8

    def test_a_late_pick_books_only_the_mondays_still_to_come(self):
        user, so, mon7, mon8 = self._late_member()
        with common.freeze_time(PIN):
            self._hours(so, mon7[0], mon8[0])
            so._auto_place_clase_fija()          # what the picker and the button call
            booked = self._booked(so)
        self.assertTrue(booked, 'nothing was placed; fixture wrong')
        self.assertFalse([b for b in booked if b <= PIN],
                         'classes already over were booked: %s' % [b for b in booked if b <= PIN])
        # Monday 07:00 and 08:00 Madrid (CEST, UTC+2 until 25 Oct; CET after).
        self.assertEqual(booked, [
            utc(2026, 10, 19, 5), utc(2026, 10, 19, 6),
            utc(2026, 10, 26, 6), utc(2026, 10, 26, 7),
            utc(2026, 11, 2, 6), utc(2026, 11, 2, 7)])

    def test_her_allowance_is_not_spent_on_past_weeks(self):
        """4 per weekly hour per month: the last Monday of her period is hers."""
        user, so, mon7, mon8 = self._late_member('allow')
        with common.freeze_time(PIN):
            self._hours(so, mon7[0], mon8[0])
            so._auto_place_clase_fija()
            booked = self._booked(so)
        self.assertIn(utc(2026, 11, 2, 6), booked,
                      'Mon 2 Nov 07:00 is inside her paid period and was left unbooked')
        self.assertIn(utc(2026, 11, 2, 7), booked)

    def test_this_weeks_counter_is_right(self):
        user, so, mon7, mon8 = self._late_member('counter')
        with common.freeze_time(PIN):
            self._hours(so, mon7[0], mon8[0])
            so._auto_place_clase_fija()
            self.assertEqual(so.fitness_weekly_used_count(date(2026, 10, 13)), 0,
                             "this week's Monday classes were over before she chose "
                             "them; her week reads as used")
            self.assertEqual(so.fitness_weekly_used_count(date(2026, 10, 20)), 2)

    def test_both_sides_of_a_class_start_to_the_minute(self):
        for minute, expect in ((-1, True), (1, False)):
            with self.subTest(minute=minute):
                with common.freeze_time(PIN - timedelta(days=8)):
                    mon7 = self._schedule(7)
                    so = self._membership(self._student('edge%s' % minute))
                start = utc(2026, 10, 19, 5)        # Mon 19 Oct 07:00 Madrid
                with common.freeze_time(start + timedelta(minutes=minute)):
                    self._hours(so, mon7[0])
                    so._auto_place_clase_fija()
                    booked = self._booked(so)
                self.assertEqual(start in booked, expect,
                                 'class at 07:00, clock at %+d min' % minute)
                self.assertFalse([b for b in booked if b < start])

    def test_sunday_25_october_two_to_three(self):
        """02:00-03:00 happens twice. Started or not is a UTC question."""
        # One class at 02:00 CET (the second 02:00) = 01:00 UTC.
        for clock, expect in ((utc(2026, 10, 25, 0, 30), True),    # 02:30 CEST
                              (utc(2026, 10, 25, 1, 30), False)):  # 02:30 CET
            with self.subTest(clock=clock):
                with common.freeze_time(PIN - timedelta(days=8)):
                    so = self._membership(self._student('dst%s' % clock.hour))
                ev = self.env['calendar.event'].sudo().create({
                    'name': 'FF night', 'start': utc(2026, 10, 25, 1),
                    'stop': utc(2026, 10, 25, 1, 50), 'class_type_id': self.ctype.id,
                    'is_fitness_class': True, 'capacity': 6, 'session_type': 'group'})
                with common.freeze_time(clock):
                    self._hours(so, ev)
                    so._auto_place_clase_fija()
                    booked = self._booked(so)
                self.assertEqual(utc(2026, 10, 25, 1) in booked, expect)

    def test_a_pick_on_day_zero_gets_what_it_always_got(self):
        """Bought Mon 19 Oct at 06:00 Madrid, before the 07:00 class."""
        with common.freeze_time(utc(2026, 10, 19, 4)):
            mon7 = self._schedule(7, start=date(2026, 10, 19))
            so = self._membership(self._student('zero'), start=date(2026, 10, 19))
            self._hours(so, mon7[0])
            so._auto_place_clase_fija()
            booked = self._booked(so)
        # Period 19 Oct - 19 Nov: five Mondays, allowance 4.
        self.assertEqual(booked, [utc(2026, 10, 19, 5), utc(2026, 10, 26, 6),
                                  utc(2026, 11, 2, 6), utc(2026, 11, 9, 6)])

    def test_the_studio_button_and_the_nightly_job_obey_the_same_rule(self):
        user, so, mon7, mon8 = self._late_member('button')
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'FF Manager', 'login': 'ff.manager@example.invalid',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref(MANAGER).id])]})
        with common.freeze_time(PIN):
            self._hours(so, mon7[0], mon8[0])
            so.with_user(manager).action_place_clase_fija()
            after_button = self._booked(so)
            self.env['sale.order']._cron_place_fixed_classes()
            after_job = self._booked(so)
        self.assertFalse([b for b in after_button if b <= PIN], 'the button booked the past')
        self.assertEqual(after_job, after_button, 'the nightly job disagreed with the button')
        self.assertEqual(len(after_button), 6)

    def test_a_month_with_five_of_her_weekday_stays_at_four(self):
        """Bought and chosen Mon 19 Oct; period 19 Oct - 19 Nov holds five
        Mondays (19, 26 Oct, 2, 9, 16 Nov) and she paid for 4. A week in,
        neither the studio's button nor the nightly job adds the fifth: the
        Monday she already had still counts against her 4."""
        with common.freeze_time(utc(2026, 10, 19, 4)):
            mon7 = self._schedule(7, start=date(2026, 10, 19))
            so = self._membership(self._student('five'), start=date(2026, 10, 19))
            self._hours(so, mon7[0])
            so._auto_place_clase_fija()
        four = [utc(2026, 10, 19, 5), utc(2026, 10, 26, 6),
                utc(2026, 11, 2, 6), utc(2026, 11, 9, 6)]
        self.assertEqual(self._booked(so), four, 'fixture: day zero must give 4')
        first = self.env['fitness.booking'].sudo().search(
            [('subscription_id', '=', so.id), ('class_start', '=', four[0])])
        first.state = 'attended'
        # The owner presses it: a manager WITH Sales rights, as on production.
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'FF Five Mgr', 'login': 'ff.five.mgr@example.invalid',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref(MANAGER).id,
                                  self.env.ref('sales_team.group_sale_manager').id])]})
        with common.freeze_time(utc(2026, 10, 27, 9)):
            so.with_user(manager).action_place_clase_fija()
            self.assertEqual(self._booked(so), four,
                             'Place Classes a week in gave her a 5th Monday')
            self.env['sale.order']._cron_place_fixed_classes()
            self.assertEqual(self._booked(so), four,
                             'the nightly job a week in gave her a 5th Monday')

    def test_a_class_the_studio_cancelled_is_never_placed(self):
        """Mon 26 Oct is cancelled. She is not booked into it, not told her
        place is reserved for it, and it does not use one of her 4."""
        user, so, mon7, mon8 = self._late_member('cxl')
        mon7[3].class_state = 'cancelled'          # Mon 26 Oct 07:00
        with common.freeze_time(PIN):
            self._hours(so, mon7[0])
            so._auto_place_clase_fija()
            booked = self._booked(so)
            self.env['sale.order']._cron_place_fixed_classes()
        self.assertEqual(booked, [utc(2026, 10, 19, 5), utc(2026, 11, 2, 6)])
        self.assertFalse(self.env['fitness.booking'].sudo().search_count(
            [('student_id', '=', user.partner_id.id),
             ('calendar_event_id', '=', mon7[3].id)]),
            'a booking exists on the cancelled class')
        told = self.env['fitness.notification'].sudo().search(
            [('user_id', '=', user.id), ('notification_type', '=', 'booking_confirmed')])
        self.assertFalse([b for b in told.mapped('body') if '26' in b],
                         'she was told her place is booked on 26 Oct: %s' % told.mapped('body'))

    def test_a_class_full_only_in_the_past_does_not_refuse_the_hour(self):
        """The cap counts the whole period; fullness that is over does not
        matter to placement, which books only what is to come."""
        user, so, mon7, mon8 = self._late_member('pastfull')
        # Mon 12 Oct, over at PIN, was full: the state both read.
        mon7[1].write({'capacity': 1, 'booked_seats': 1})
        with common.freeze_time(PIN):
            self._hours(so, mon7[0])
            so._auto_place_clase_fija()            # must not raise on 12 Oct
            booked = self._booked(so)
        self.assertEqual(booked, [utc(2026, 10, 19, 5), utc(2026, 10, 26, 6),
                                  utc(2026, 11, 2, 6)])


@tagged('post_install', '-at_install')
class TestPlacementNotifications(FixedFixture, TransactionCase):
    """Who is told what when a late pick is placed - counted, push included."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def setUp(self):
        super().setUp()
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param(PARAM_PUBLIC, 'pub-for-test')
        Param.set_param(PARAM_PRIVATE, 'priv-for-test')
        Param.set_param('database.is_neutralized', 'False')
        self.env.registry.clear_cache()
        self.addCleanup(self.env.registry.clear_cache)

    def _device(self, user, tag):
        self.env['fitness.push.subscription']._register_device(
            user.id, 'https://push.example.invalid/ff.%s' % tag, 'pub', 'auth')

    def test_she_is_told_only_about_classes_still_to_come(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                with common.freeze_time(PIN - timedelta(days=8)):
                    mon7 = self._schedule(7)
                    mon8 = self._schedule(8)
                    student = self._student('n' + lang[:2], lang)
                    so = self._membership(student)
                manager = self.env['res.users'].with_context(no_reset_password=True).create({
                    'name': 'FF Mgr %s' % lang, 'login': 'ff.mgr.%s@example.invalid' % lang,
                    'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                          self.env.ref(MANAGER).id])]})
                for u, t in ((student, 's' + lang), (self.teacher, 't' + lang), (manager, 'm' + lang)):
                    self._device(u, t)
                N = self.env['fitness.notification'].sudo()
                before = {u.id: N.search_count([('user_id', '=', u.id)])
                          for u in (student, self.teacher, manager)}
                sent = []
                with common.freeze_time(PIN), patch.object(
                        web_push, 'send', lambda *a, **k: sent.append(a) or (200, '')):
                    self._hours(so, mon7[0], mon8[0])
                    so._auto_place_clase_fija()
                    self.env.flush_all()
                new = N.search([('user_id', '=', student.id), ('id', '>', 0)], order='id')
                new = new[before[student.id]:] if before[student.id] else new
                kinds = [n.notification_type for n in new]
                self.assertEqual(kinds.count('booking_confirmed'), 6,
                                 'one "reserved" notice per class still to come: %s' % kinds)
                self.assertEqual(kinds.count('credit_zero'), 0,
                                 '"No credits remaining" while her membership runs')
                bodies = ' '.join(new.mapped('body'))
                for past in ('5 oct', '12 oct', '5 Oct', '12 Oct', "5 d’oct", "12 d’oct"):
                    self.assertNotIn(past, bodies, 'a class already over: %s' % bodies)
                self.assertEqual(N.search_count([('user_id', '=', self.teacher.id)]),
                                 before[self.teacher.id], 'the instructor was told')
                self.assertEqual(N.search_count([('user_id', '=', manager.id)]),
                                 before[manager.id], 'the studio was told')
                self.assertEqual(len(sent), 6, 'pushes sent: %d' % len(sent))

    def test_no_credits_is_still_said_when_it_is_true(self):
        """A pack holder with no membership who spends her last credit."""
        student = self._student('pack', 'en_US')
        pack = self.env['product.template'].sudo().create({
            'name': 'FF pack 1', 'list_price': 10.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 1,
            'fitness_validity_days': 30, 'fitness_class_type': 'reformer',
            'fitness_session_type': 'group'})
        o = self.env['sale.order'].sudo().create({
            'partner_id': student.partner_id.id,
            'order_line': [(0, 0, {'product_id': pack.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 10.0})]})
        o.with_context(skip_fitness_notification=True).action_confirm()
        with common.freeze_time(PIN):
            ev = self.env['calendar.event'].sudo().create({
                'name': 'FF one', 'start': PIN + timedelta(days=1),
                'stop': PIN + timedelta(days=1, hours=1), 'class_type_id': self.ctype.id,
                'is_fitness_class': True, 'capacity': 6, 'session_type': 'group'})
            self.env['fitness.booking'].sudo().create(
                {'student_id': student.partner_id.id, 'calendar_event_id': ev.id})
        self.assertEqual(self.env['fitness.notification'].sudo().search_count(
            [('user_id', '=', student.id), ('notification_type', '=', 'credit_zero')]), 1)


@tagged('post_install', '-at_install')
class TestLatePickThroughThePicker(FixedFixture, HttpCase):
    """The member's own "Choose your weekly class", over HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def _login(self, user, lang):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)

    def test_a_late_pick_through_the_picker_books_only_the_future(self):
        with common.freeze_time(PIN - timedelta(days=8)):
            mon7 = self._schedule(7)
            student = self._student('picker', 'es_ES')
            so = self._membership(student)
        with common.freeze_time(PIN):
            self._login(student, 'es_ES')
            page = self.url_open('/my/fixed-class').text
            sched = self.env['fitness.class.schedule'].sudo().search(
                [('recurrence_id', '=', mon7[0].recurrence_id.id)])
            self.assertIn('value="%d"' % sched.id, page, 'her hour is not offered')
            token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page).group(1)
            r = self.url_open('/my/fixed-class/choose', data={
                'schedule_id': sched.id, 'csrf_token': token}, allow_redirects=False)
            booked = self._booked(so)
        self.assertTrue(booked, 'nothing placed; the post failed: %s' % r.status_code)
        self.assertFalse([b for b in booked if b <= PIN])

    def test_the_picker_offers_an_hour_that_was_full_only_in_the_past(self):
        """Mon 12 Oct 07:00 was full; at PIN it is over. Every Monday to come
        has room, so the hour is hers to choose - in es, with no past date
        given as the reason it is not."""
        with common.freeze_time(PIN - timedelta(days=8)):
            mon7 = self._schedule(7)
            student = self._student('pfpick', 'es_ES')
            so = self._membership(student)
        mon7[1].write({'capacity': 1, 'booked_seats': 1})   # full, and over at PIN
        sched = self.env['fitness.class.schedule'].sudo().search(
            [('recurrence_id', '=', mon7[0].recurrence_id.id)])
        with common.freeze_time(PIN):
            self._login(student, 'es_ES')
            page = self.url_open('/my/fixed-class').text
            self.assertIn('value="%d"' % sched.id, page,
                          'the hour is refused for a class already over')
            self.assertNotIn('12 Oct', page)
            token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page).group(1)
            self.url_open('/my/fixed-class/choose', data={
                'schedule_id': sched.id, 'csrf_token': token}, allow_redirects=False)
            booked = self._booked(so)
        self.assertEqual(booked, [utc(2026, 10, 19, 5), utc(2026, 10, 26, 6),
                                  utc(2026, 11, 2, 6)])
