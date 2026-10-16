# -*- coding: utf-8 -*-
"""A private class she holds says the studio will contact her - never "ready to book".

Whatever the source - a gift from the studio, a purchase in the app, cash
approved at the desk - the one notification she gets used to say "You have
1 class credit(s) ready to book", the payment page "Your classes are ready
to book" and the class's own page offered "Book a class". A private class
is booked by the studio, so each now says the studio will contact her to
arrange the day and time, in es, ca and en. Group packs keep their words.

The fixture is repeated from test_private_classes_studio_only on purpose:
either commit can be dropped without the other's tests breaking.
"""
import re
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

PW = 'Private-only-2026'
BELL = {
    'en_US': 'Your private class is confirmed. The studio will contact you to arrange the day and time.',
    'es_ES': 'Tu clase privada está confirmada. El estudio se pondrá en contacto contigo para acordar el día y la hora.',
    'ca_ES': "La teva classe privada està confirmada. L'estudi es posarà en contacte amb tu per acordar el dia i l'hora.",
}
BY_STUDIO = {
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
class TestPrivateClassWording(PrivateFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._private_fixture()

    def _bell(self, user):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id), ('notification_type', '=', 'purchase_completed')])

    def test_one_notification_per_source_in_her_language(self):
        for source in ('gift', 'shop', 'cash'):
            for lang in ('es_ES', 'ca_ES', 'en_US'):
                with self.subTest(source=source, lang=lang):
                    student = self._student('w%s%s' % (source, lang[:2]), lang)
                    self._credit(student, source)
                    bell = self._bell(student)
                    self.assertEqual(len(bell), 1, 'not exactly one notification (%s)' % source)
                    self.assertEqual(bell.body, BELL[lang])
                    self.assertEqual(bell.action_url, '/my/packages')

    def test_a_group_pack_keeps_ready_to_book(self):
        student = self._student('wgroup', 'en_US')
        self._credit(student, 'shop', product=self.p_group)
        self.assertIn('ready to book', self._bell(student).body)

    def _login(self, user, lang):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('frontend_lang', lang)
        self.opener.cookies.set('mv_lang', lang)

    def test_back_from_paying_for_a_private_class(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                student = self._student('wpay' + lang[:2], lang)
                so = self._credit(student, 'shop')
                provider = self.env['payment.provider'].sudo().search([], limit=1)
                method = self.env['payment.method'].sudo().with_context(active_test=False).search([], limit=1)
                self.env['payment.transaction'].sudo().create({
                    'provider_id': provider.id, 'payment_method_id': method.id,
                    'reference': 'PO-%s' % lang, 'amount': so.amount_total,
                    'currency_id': so.currency_id.id, 'partner_id': student.partner_id.id,
                    'state': 'done', 'sale_order_ids': [(6, 0, so.ids)]})
                self._login(student, lang)
                page = self.url_open('/my/packages?from_payment=1').text.replace('&#39;', "'")
                self.assertIn(BELL[lang], page)
                self.assertNotIn('Your classes are ready to book', page)

    def test_her_private_class_page_offers_no_booking(self):
        # Like production's single private class and its courtesy private
        # class: not sold in the shop, so its page is the holder's page.
        single = self.env['product.template'].sudo().create({
            'name': 'PO Barre Private Single', 'type': 'service', 'list_price': 35.0,
            'sale_ok': False, 'fitness_is_package': True, 'fitness_class_count': 1,
            'fitness_validity_days': 90, 'fitness_class_type': 'barre',
            'fitness_session_type': 'private'})
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                student = self._student('wpage' + lang[:2], lang)
                self._credit(student, 'gift', product=single)
                self._login(student, lang)
                page = self.url_open('/my/packages/%d' % single.id).text.replace('&#39;', "'")
                self.assertNotIn('mv-book-held', page, 'the page still offers Book a class')
                self.assertIn(BY_STUDIO[lang], page)
