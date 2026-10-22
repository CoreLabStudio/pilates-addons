# -*- coding: utf-8 -*-
"""A student cannot book herself into a class that starts within the limit.

The studio's rule (22 Oct): no booking by the student inside
fitness.booking_cutoff_minutes of the start; 0 (the default) is no limit.
Every way she books meets it - the booking model as her (what a direct RPC
call is), the booking route, the class page and the timetable, which show a
sentence where Book would be. None of the studio's ways is touched: a
manager booking her, anything run as superuser (gift, trial approval) and
the fixed-class placement.

Measured in real time: the night the clocks go back is the same 60 minutes.
"""
import re
from datetime import datetime, timedelta
from urllib.parse import unquote_plus

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, common, tagged

PW = 'Cutoff-2026-pw'
SENTENCE = 'Online booking closes 60 minutes before the class starts.'


@tagged('post_install', '-at_install')
class TestBookingCutoff(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.set_param('fitness.booking_cutoff_minutes', '60')
        cls.types = {s: cls.env['fitness.class.type'].create({
            'name': 'CO %s' % s, 'classroom_type': 'barre', 'duration': 50,
            'level': 'all', 'session_type': s}) for s in ('group', 'private')}
        cls.packs = {s: cls.env['product.template'].sudo().create({
            'name': 'CO pack %s' % s, 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 10,
            'fitness_validity_days': 400, 'fitness_class_type': 'barre',
            'fitness_session_type': s}) for s in ('group', 'private')}
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'CO Manager', 'login': 'co.mgr@example.invalid',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref('fitness_core.group_fitness_manager').id])]})
        cls._seq = 0

    def _student(self, session='group'):
        type(self)._seq += 1
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'CO Student %d' % self._seq, 'login': 'co.%d@example.invalid' % self._seq,
            'email': 'co.%d@example.invalid' % self._seq, 'password': PW, 'lang': 'en_US',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        with common.freeze_time(datetime(2026, 1, 2, 9, 0)):
            order = self.env['sale.order'].sudo().create({'partner_id': user.partner_id.id})
            self.env['sale.order.line'].sudo().create({
                'order_id': order.id, 'product_id': self.packs[session].product_variant_ids[:1].id,
                'product_uom_qty': 1, 'fitness_class_type': 'barre'})
            order.action_confirm()
        return user

    def _class(self, start, session='group'):
        return self.env['calendar.event'].sudo().create({
            'name': 'CO Class %s' % start, 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': self.types[session].id, 'is_fitness_class': True,
            'session_type': session, 'capacity': 8})

    def _book_as(self, user, event, **ctx):
        return self.env['fitness.booking'].with_user(user).with_context(**ctx).create({
            'student_id': (user.partner_id if user.share else self.student_for_manager).id,
            'calendar_event_id': event.id})

    def _in(self, minutes):
        return self._class(fields.Datetime.now() + timedelta(minutes=minutes))

    # -- the model, as she calls it (what an RPC call is) ---------------------

    def test_refused_at_59_minutes_allowed_at_61_and_when_off(self):
        with self.assertRaises(ValidationError) as caught:
            self._book_as(self._student(), self._in(59))
        self.assertIn(SENTENCE, str(caught.exception))
        self.assertEqual(self._book_as(self._student(), self._in(61)).state, 'booked')
        self.env['ir.config_parameter'].sudo().set_param('fitness.booking_cutoff_minutes', '0')
        self.assertEqual(self._book_as(self._student(), self._in(59)).state, 'booked',
                         'refused with the limit switched off')

    def test_measured_in_real_time_in_summer_winter_and_across_the_change(self):
        """59 real minutes is refused and 61 allowed on all three.

        25 Oct 2026, 00:30 UTC is 02:30 on summer time; 01:29 UTC is 02:29 on
        winter time. On the wall clock the class looks a minute *earlier*
        than now - it is still 59 minutes away and still refused.
        """
        for now in (datetime(2026, 7, 15, 16, 0), datetime(2026, 1, 14, 17, 0),
                    datetime(2026, 10, 25, 0, 30)):
            with self.subTest(now=now):
                with common.freeze_time(now):
                    soon = self._class(now + timedelta(minutes=59))
                    later = self._class(now + timedelta(minutes=61))
                    with self.assertRaises(ValidationError):
                        self._book_as(self._student(), soon)
                    self.assertEqual(self._book_as(self._student(), later).state, 'booked')

    # -- the studio's paths are not limited -----------------------------------

    def test_the_studio_still_books_her_inside_the_limit(self):
        type(self).student_for_manager = self._student().partner_id
        self.assertEqual(self._book_as(self.manager, self._in(30)).state, 'booked',
                         'a manager (Add a student, the booking form, a walk-in) was refused')
        gift = self.env['fitness.booking'].sudo().create({
            'student_id': self._student().partner_id.id, 'calendar_event_id': self._in(20).id})
        self.assertEqual(gift.state, 'booked', 'a superuser path (gift, trial approval) was refused')
        placed = self._book_as(self._student(), self._in(10), _fitness_clase_fija_placement=True)
        self.assertEqual(placed.state, 'booked', 'the fixed-class placement lost a week')

    # -- the rules around it behave as before ----------------------------------

    def test_the_private_block_and_the_seven_day_rule_are_unchanged(self):
        user = self._student('private')
        private = self._class(fields.Datetime.now() + timedelta(minutes=30), 'private')
        with self.assertRaises(UserError) as caught:
            self._book_as(user, private)
        self.assertIn('Private classes are arranged by the studio', str(caught.exception))
        with self.assertRaises(ValidationError) as caught:
            self._book_as(self._student(), self._in(8 * 24 * 60))
        self.assertIn('Booking opens 7 days before the class', str(caught.exception))

    # -- what she sees ---------------------------------------------------------

    def _login(self, user):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('frontend_lang', 'en_US')

    def test_the_class_page_and_the_timetable_say_so_instead_of_book(self):
        user = self._student()
        soon, later = self._in(59), self._in(61)
        self._login(user)
        page = self.url_open('/my/classes/%d' % soon.id).text
        self.assertIn(SENTENCE, page)
        self.assertNotIn('/my/classes/%d/book' % soon.id, page)
        self.assertIn('/my/classes/%d/book' % later.id, self.url_open('/my/classes/%d' % later.id).text)
        studio = self.url_open('/my/studio?days=1').text
        self.assertNotIn('/my/classes/%d/book' % soon.id, studio, 'the timetable offers Book at 59 minutes')
        self.assertIn(SENTENCE, studio)
        self.assertIn('/my/classes/%d/book' % later.id, studio)

    def test_the_booking_route_refuses_and_books_nothing(self):
        user = self._student()
        soon = self._in(59)
        self._login(user)
        page = self.url_open('/my/classes/%d' % soon.id).text
        token = re.search(r'csrf_token\W+([0-9a-f]{20,}o?\d*)', page).group(1)
        r = self.url_open('/my/classes/%d/book' % soon.id, data={'csrf_token': token},
                          allow_redirects=False)
        self.assertIn(SENTENCE, unquote_plus(r.headers.get('Location', '')))
        self.assertFalse(self.env['fitness.booking'].sudo().search(
            [('calendar_event_id', '=', soon.id), ('state', '!=', 'cancelled')]))
