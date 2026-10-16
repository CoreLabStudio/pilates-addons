# -*- coding: utf-8 -*-
"""A private class is booked by the studio, never by the student.

The studio's rule (15 Oct): however she came to hold a private class - a
gift from the studio, a purchase in the app, cash approved at the desk -
the studio arranges the day and time and books her in. On e15a2d7 her
private credit covered any private class open on the timetable, so she
could book one herself, including one arranged for somebody else.

Driven over HTTP as real students, in es, ca and en, on every student
path: the timetable, the class page, the booking route and a direct RPC
call. The studio's Add a student books the same class; group classes are
untouched; a booking that already exists is left alone.
"""
import json
import re
from datetime import timedelta
from urllib.parse import unquote_plus

from odoo import fields
from odoo.tests import HttpCase, tagged

PW = 'Private-only-2026'
MSG = {
    'en_US': 'Private classes are arranged by the studio. The studio will contact you.',
    'es_ES': 'Las clases privadas las organiza el estudio. El estudio se pondrá en contacto contigo.',
    'ca_ES': "Les classes privades les organitza l'estudi. L'estudi es posarà en contacte amb tu.",
}


class PrivateFixture:

    @classmethod
    def _private_fixture(cls):
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        for code in ('es_ES', 'ca_ES'):
            env['res.lang']._activate_and_install_lang(code)
        env['res.lang']._activate_lang('en_US')
        cls.room = env['fitness.classroom'].sudo().create(
            {'name': 'PO Room', 'classroom_type': 'barre', 'capacity': 10})
        cls.t_private = env['fitness.class.type'].sudo().create({
            'name': 'PO Barre Private', 'classroom_type': 'barre', 'session_type': 'private',
            'level': 'all', 'classroom_id': cls.room.id})
        cls.t_group = env['fitness.class.type'].sudo().create({
            'name': 'PO Barre Group', 'classroom_type': 'barre', 'session_type': 'group',
            'level': 'all', 'classroom_id': cls.room.id})
        cls.p_private = env['product.template'].sudo().create({
            'name': 'PO Barre Private Pack', 'type': 'service', 'list_price': 35.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 90,
            'fitness_class_type': 'barre', 'fitness_session_type': 'private'})
        cls.p_group = env['product.template'].sudo().create({
            'name': 'PO Barre Group Pack', 'type': 'service', 'list_price': 50.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 90,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PO Manager', 'login': 'po.manager@example.invalid',
            'group_ids': [(6, 0, [env.ref('base.group_user').id,
                                  env.ref('fitness_core.group_fitness_manager').id,
                                  env.ref('sales_team.group_sale_manager').id,
                                  env.ref('account.group_account_invoice').id])]})
        if not env['account.journal'].sudo().search(
                [('type', '=', 'cash'), ('company_id', '=', env.company.id)]):
            env['account.journal'].sudo().create(
                {'name': 'PO Cash', 'code': 'POC', 'type': 'cash', 'company_id': env.company.id})

    def _event(self, ctype, hours=50):
        start = (fields.Datetime.now() + timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
        return self.env['calendar.event'].sudo().create({
            'name': ctype.name, 'start': start, 'stop': start + timedelta(minutes=55),
            'class_type_id': ctype.id, 'is_fitness_class': True,
            'session_type': ctype.session_type})

    def _student(self, tag, lang):
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PO %s' % tag, 'login': 'po.%s@example.invalid' % tag,
            'email': 'po.%s@example.invalid' % tag, 'password': PW, 'lang': lang,
            'tz': 'Europe/Madrid',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})

    def _order(self, user, product, method, **extra):
        so = self.env['sale.order'].sudo().create(dict(
            {'partner_id': user.partner_id.id, 'fitness_payment_method': method}, **extra))
        self.env['sale.order.line'].sudo().create({
            'order_id': so.id, 'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': product.list_price})
        return so

    def _credit(self, user, source, product=None):
        """A private credit (or `product`) from one of the three sources."""
        product = product or self.p_private
        if source == 'gift':
            self.env['fitness.desk.sale.wizard'].with_user(self.manager).create({
                'partner_id': user.partner_id.id, 'product_id': product.id,
                'payment_method': 'free', 'reason': 'PO gift'}).action_create_sale()
            return self.env['sale.order'].sudo().search(
                [('partner_id', '=', user.partner_id.id)], order='id desc', limit=1)
        if source == 'shop':
            so = self._order(user, product, 'stripe')
            so.action_confirm()
            return so
        if source == 'cash':
            so = self._order(user, product, 'cash',
                             fitness_cash_requested_on=fields.Datetime.now())
            so.with_user(self.manager).action_fitness_approve_cash()
            return so
        raise AssertionError(source)


@tagged('post_install', '-at_install')
class TestPrivateClassesStudioOnly(PrivateFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._private_fixture()

    def _login(self, user, lang):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('frontend_lang', lang)
        self.opener.cookies.set('mv_lang', lang)

    def _bookings(self, user, event):
        return self.env['fitness.booking'].sudo().search(
            [('student_id', '=', user.partner_id.id), ('calendar_event_id', '=', event.id)])

    def _token(self):
        for url in ('/my/studio', '/my/packages/%d/checkout' % self.p_group.id, '/my/message-studio'):
            m = re.search(r'name="csrf_token"\s+value="([^"]+)"', self.url_open(url).text)
            if m:
                return m.group(1)
        raise AssertionError('no csrf token on any page')

    def _post_book(self, event):
        token = self._token()
        return self.url_open('/my/classes/%d/book' % event.id, data={'csrf_token': token})

    def _rpc_create(self, user, event):
        r = self.url_open('/web/dataset/call_kw/fitness.booking/create', data=json.dumps({
            'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {
                'model': 'fitness.booking', 'method': 'create',
                'args': [{'student_id': user.partner_id.id, 'calendar_event_id': event.id}],
                'kwargs': {}}}), headers={'Content-Type': 'application/json'})
        return r.json()

    def test_every_student_path_refuses_whatever_the_source(self):
        cases = [('gift', 'es_ES'), ('shop', 'ca_ES'), ('cash', 'en_US')]
        for source, lang in cases:
            with self.subTest(source=source, lang=lang):
                private = self._event(self.t_private)
                student = self._student('%s%s' % (source, lang[:2]), lang)
                self._credit(student, source)
                self._login(student, lang)

                listing = self.url_open('/my/studio').text
                self.assertNotIn('/my/classes/%d' % private.id, listing,
                                 'the timetable lists a private class')

                detail = self.url_open('/my/classes/%d' % private.id).text
                self.assertNotIn('/my/classes/%d/book' % private.id, detail,
                                 'the class page offers to book a private class')
                self.assertIn(MSG[lang], detail.replace('&#39;', "'"))

                r = self._post_book(private)
                self.assertFalse(self._bookings(student, private),
                                 'the booking route booked a private class (%s)' % source)
                self.assertIn(MSG[lang], unquote_plus(r.url))

                out = self._rpc_create(student, private)
                self.assertIn('error', out, 'RPC create of a private booking was accepted')
                self.assertFalse(self._bookings(student, private),
                                 'a direct RPC call booked a private class (%s)' % source)

                wiz = self.env['fitness.add.student.wizard'].with_user(self.manager).create({
                    'event_id': private.id, 'student_id': student.partner_id.id})
                wiz.action_add()
                booked = self._bookings(student, private)
                self.assertEqual(len(booked), 1, 'the studio could not book her (%s)' % source)
                self.assertEqual(booked.state, 'booked')
                self.assertEqual(booked.package_order_line_id.product_id.product_tmpl_id, self.p_private)

    def test_the_booked_private_class_is_in_her_schedule(self):
        private = self._event(self.t_private)
        student = self._student('sched', 'es_ES')
        self._credit(student, 'gift')
        self.env['fitness.add.student.wizard'].with_user(self.manager).create({
            'event_id': private.id, 'student_id': student.partner_id.id}).action_add()
        self._login(student, 'es_ES')
        mine = self.url_open('/my/studio?view=schedule').text
        self.assertIn('/my/classes/%d' % private.id, mine, 'not in My Schedule')

    def test_only_the_booked_student_sees_her_private_class(self):
        private = self._event(self.t_private)
        booked = self._student('mine', 'es_ES')
        other = self._student('notmine', 'ca_ES')
        self._credit(booked, 'gift')
        self._credit(other, 'gift')
        self.env['fitness.add.student.wizard'].with_user(self.manager).create({
            'event_id': private.id, 'student_id': booked.partner_id.id}).action_add()
        link = '/my/classes/%d' % private.id
        self._login(booked, 'es_ES')
        self.assertIn(link, self.url_open('/my/studio?view=schedule').text,
                      'her private class is missing from My Schedule')
        self._login(other, 'ca_ES')
        self.assertNotIn(link, self.url_open('/my/studio?view=schedule').text,
                         "another student's private class is in her My Schedule")
        self.assertNotIn(link, self.url_open('/my/studio').text,
                         'the timetable lists a private class')

    def test_the_weekly_timetable_shows_no_private_schedule(self):
        teacher = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PO Teacher', 'login': 'po.teacher@example.invalid',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('fitness_core.group_fitness_teacher').id])]})
        for ctype, name in ((self.t_private, 'PO Privada Martes'), (self.t_group, 'PO Grupo Martes')):
            s = self.env['fitness.class.schedule'].sudo().create({
                'name': name, 'class_type_id': ctype.id, 'classroom_id': self.room.id,
                'weekday': 'tue', 'start_time': 12.0, 'duration': 1.0,
                'date_start': fields.Date.today(), 'horizon_weeks': 2,
                'teacher_user_id': teacher.id})
            s.action_generate()
        student = self._student('weekly', 'en_US')
        self._credit(student, 'gift')
        self._credit(student, 'shop', product=self.p_group)
        self._login(student, 'en_US')
        page = self.url_open('/my/timetable?discipline=barre').text
        self.assertIn(self.t_group.name, page, 'fixture: the group schedule is not on the timetable')
        self.assertNotIn(self.t_private.name, page, 'the weekly timetable lists a private class')

    def test_group_classes_as_before(self):
        group = self._event(self.t_group)
        student = self._student('group', 'en_US')
        self._credit(student, 'shop', product=self.p_group)
        self._login(student, 'en_US')
        self.assertIn('/my/classes/%d/book' % group.id, self.url_open('/my/studio').text)
        self._post_book(group)
        self.assertEqual(len(self._bookings(student, group)), 1, 'a group class could not be booked')

    def test_an_existing_self_booking_is_left_alone(self):
        private = self._event(self.t_private)
        student = self._student('before', 'es_ES')
        so = self._credit(student, 'shop')
        # As it was made before the rule: by her, through the portal.
        old = self.env['fitness.booking'].sudo().create({
            'student_id': student.partner_id.id, 'calendar_event_id': private.id,
            'package_order_line_id': so.order_line[:1].id})
        self.env.cr.execute('UPDATE fitness_booking SET create_uid = %s WHERE id = %s',
                            (student.id, old.id))
        self._login(student, 'es_ES')
        self.url_open('/my/studio')
        self.url_open('/my/classes/%d' % private.id)
        old.invalidate_recordset()
        self.assertEqual(old.state, 'booked', 'an existing private booking was touched')
        self.assertIn('/my/classes/%d' % private.id, self.url_open('/my/studio?view=schedule').text)
