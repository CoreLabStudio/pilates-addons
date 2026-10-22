# -*- coding: utf-8 -*-
"""Cancelling a class that has started says it has started, in her language.

A late cancel is allowed (and forfeits the credit), so the only refusal
left in the app is a class already under way. The page told her it "starts
in less than 6 hours and can no longer be cancelled online" - not what
happened, and in English whatever she reads. It now shows the booking's
own message: the class has already started.
"""
import re
from datetime import timedelta
from urllib.parse import unquote_plus

from odoo import fields
from odoo.tests import HttpCase, tagged

PW = 'Started-msg-2026'
STARTED = {'en_US': 'has already started', 'es_ES': 'ya ha empezado', 'ca_ES': 'ja ha començat'}
WRONG = ('less than', 'menos de', 'menys de')


@tagged('post_install', '-at_install')
class TestClassStartedMessage(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')
        cls.env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.ctype = cls.env['fitness.class.type'].create({
            'name': 'SM Barre', 'classroom_type': 'barre', 'duration': 50,
            'level': 'all', 'session_type': 'group'})
        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'SM pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})

    def _started_booking(self, lang):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'SM %s' % lang, 'login': 'sm.%s@example.invalid' % lang.lower(),
            'email': 'sm.%s@example.invalid' % lang.lower(), 'password': PW, 'lang': lang,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        order = self.env['sale.order'].sudo().create({'partner_id': user.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'barre'})
        order.action_confirm()
        start = fields.Datetime.now() - timedelta(minutes=10)
        event = self.env['calendar.event'].sudo().create({
            'name': 'SM Barre class', 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': self.ctype.id, 'is_fitness_class': True, 'capacity': 6})
        booking = self.env['fitness.booking'].sudo().with_context(
            fitness_record_past_attendance=True).create({
                'student_id': user.partner_id.id, 'calendar_event_id': event.id,
                'package_order_line_id': order.order_line[:1].id})
        return user, booking

    def test_cancelling_a_started_class_says_it_has_started(self):
        for lang, words in STARTED.items():
            with self.subTest(lang=lang):
                user, booking = self._started_booking(lang)
                self.authenticate(user.login, PW)
                self.opener.cookies.set('frontend_lang', lang)
                page = self.url_open('/my/studio').text
                token = re.search(r'csrf_token\W+([0-9a-f]{20,}o?\d*)', page).group(1)
                r = self.url_open('/my/classes/%d/cancel' % booking.id,
                                  data={'csrf_token': token}, allow_redirects=False)
                error = unquote_plus(r.headers.get('Location', ''))
                self.assertIn(words, error, '%s: %s' % (lang, error))
                for wrong in WRONG:
                    self.assertNotIn(wrong, error, '%s still says %r: %s' % (lang, wrong, error))
                self.assertEqual(booking.state, 'booked', 'a started class was cancelled')
