# -*- coding: utf-8 -*-
"""The cancellation policy shows once on the class page, in es, ca and en.

When she was booked the page printed it twice: under "Cancel booking" and
again at the foot of the page. Now it stands once, under Cancel booking;
a class she has not booked still shows it once at the foot. Wording
unchanged - the Terms still say 6 hours.
"""
import html
import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

PW = 'Policy-once-2026'
POLICY = {
    'en_US': 'You must cancel at least 6 hours before the class starts',
    'es_ES': 'Debes cancelar al menos 6 horas antes del inicio de la clase',
    'ca_ES': "Has de cancel·lar almenys 6 hores abans de l",
}


@tagged('post_install', '-at_install')
class TestCancelPolicyShownOnce(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_param('fitness.opening_date', '')
        ICP.set_param('fitness.cancellation_window_hours', '6')
        cls.ctype = cls.env['fitness.class.type'].create({
            'name': 'PO Barre', 'classroom_type': 'barre', 'duration': 50,
            'level': 'all', 'session_type': 'group'})
        cls.pack = cls.env['product.template'].sudo().create({
            'name': 'PO pack', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5,
            'fitness_validity_days': 60, 'fitness_class_type': 'barre',
            'fitness_session_type': 'group'})

    def _student(self, lang):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'PO %s' % lang, 'login': 'po.%s@example.invalid' % lang.lower(),
            'email': 'po.%s@example.invalid' % lang.lower(), 'password': PW, 'lang': lang,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        order = self.env['sale.order'].sudo().create({'partner_id': user.partner_id.id})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id, 'product_id': self.pack.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'fitness_class_type': 'barre'})
        order.action_confirm()
        return user

    def _class(self, days):
        start = fields.Datetime.now() + timedelta(days=days)
        return self.env['calendar.event'].sudo().create({
            'name': 'PO Barre class', 'start': start, 'stop': start + timedelta(minutes=50),
            'class_type_id': self.ctype.id, 'is_fitness_class': True, 'capacity': 6})

    def _page(self, user, lang, event):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)
        return self.url_open('/my/classes/%d' % event.id).text

    @staticmethod
    def _shown(page):
        """The policy paragraphs on the page itself (the confirm sheet is a dialog, not the page)."""
        return [html.unescape(t) for t in re.findall(
            r'class="mv-cancel-policy"[^>]*>(.*?)</p>', page, re.S)]

    def test_booked_it_shows_once_under_cancel_booking(self):
        for lang, words in POLICY.items():
            with self.subTest(lang=lang):
                user = self._student(lang)
                event = self._class(2)
                self.env['fitness.booking'].sudo().create({
                    'student_id': user.partner_id.id, 'calendar_event_id': event.id})
                page = self._page(user, lang, event)
                shown = self._shown(page)
                self.assertEqual(len(shown), 1, '%s: policy shown %d times' % (lang, len(shown)))
                self.assertIn(words, shown[0], '%s: %s' % (lang, shown[0]))
                self.assertLess(page.index('/cancel'), page.index('class="mv-cancel-policy"'),
                                '%s: the policy is not under Cancel booking' % lang)

    def test_not_booked_it_still_shows_once(self):
        for lang, words in POLICY.items():
            with self.subTest(lang=lang):
                user = self._student(lang)
                shown = self._shown(self._page(user, lang, self._class(2)))
                self.assertEqual(len(shown), 1, '%s: policy shown %d times' % (lang, len(shown)))
                self.assertIn(words, shown[0], '%s: %s' % (lang, shown[0]))
