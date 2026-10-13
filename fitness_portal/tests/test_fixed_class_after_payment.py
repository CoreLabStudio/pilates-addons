# -*- coding: utf-8 -*-
"""After paying - by card, cash or transfer - a fixed-class member is taken to her hours.

Only the signed checkout (transfer, Bizum: used only when no card provider
is on) sent her to "Choose your weekly class". A card payment lands on the
shop, which never asked, and a cash payment is approved at the desk while
she is not on the page at all. Isabel Silva and Paula Masip Ramon paid by
card for two fixed classes a week and have no hours set.

Clock pinned (Tue 13 Oct 2026 10:00 Madrid), languages explicit.
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
class TestSentToChooseHerHours(FixedFixture, HttpCase):
    """After paying, by card, cash or transfer, she is taken to her hours."""

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

    def test_card_payment_lands_on_choose_your_weekly_class(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                with common.freeze_time(PIN):
                    self._schedule(19, weekday='tue', start=date(2026, 10, 13))
                    student = self._student('card' + lang[:2], lang)
                    so = self._membership(student, start=date(2026, 10, 13))
                    provider = self.env['payment.provider'].sudo().search([], limit=1)
                    method = self.env['payment.method'].sudo().with_context(active_test=False).search([], limit=1)
                    self.env['payment.transaction'].sudo().create({
                        'provider_id': provider.id, 'payment_method_id': method.id,
                        'reference': 'FF-%s' % lang, 'amount': so.amount_total,
                        'currency_id': so.currency_id.id, 'partner_id': student.partner_id.id,
                        'state': 'done', 'sale_order_ids': [(6, 0, so.ids)]})
                    self._login(student, lang)
                    r = self.url_open('/my/packages?from_payment=1')
                self.assertIn('/my/fixed-class', r.url, 'landed on %s' % r.url)

    def test_card_payment_still_pending_is_not_redirected(self):
        with common.freeze_time(PIN):
            student = self._student('cardpend')
            so = self._membership(student, start=date(2026, 10, 13))
            provider = self.env['payment.provider'].sudo().search([], limit=1)
            method = self.env['payment.method'].sudo().with_context(active_test=False).search([], limit=1)
            self.env['payment.transaction'].sudo().create({
                'provider_id': provider.id, 'payment_method_id': method.id,
                'reference': 'FF-pending', 'amount': so.amount_total,
                'currency_id': so.currency_id.id, 'partner_id': student.partner_id.id,
                'state': 'pending', 'sale_order_ids': [(6, 0, so.ids)]})
            self._login(student, 'en_US')
            r = self.url_open('/my/packages?from_payment=1')
        self.assertNotIn('/my/fixed-class', r.url)
        self.assertIn('/my/packages', r.url)

    def test_the_active_bell_takes_her_to_her_hours(self):
        """Cash approved at the desk, a desk sale, a card webhook: every path
        sends this one bell, whether she is on the page or not."""
        texts = {
            'es_ES': 'Elige el día y la hora de tu clase semanal',
            'ca_ES': "Tria el dia i l'hora de la teva classe setmanal",
            'en_US': 'Choose the day and time of your weekly class',
        }
        for lang, text in texts.items():
            with self.subTest(lang=lang):
                with common.freeze_time(PIN):
                    student = self._student('bell' + lang[:2], lang)
                    self._membership(student, start=date(2026, 10, 13))
                bell = self.env['fitness.notification'].sudo().search([
                    ('user_id', '=', student.id),
                    ('notification_type', '=', 'purchase_completed')])
                self.assertEqual(len(bell), 1)
                self.assertEqual(bell.action_url, '/my/fixed-class')
                self.assertIn(text, bell.body)

    def test_cash_approved_at_the_desk_sends_the_bell_to_her_hours(self):
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'FF Cash Mgr', 'login': 'ff.cashmgr@example.invalid',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref(MANAGER).id,
                                  self.env.ref('sales_team.group_sale_manager').id,
                                  self.env.ref('account.group_account_invoice').id])]})
        with common.freeze_time(PIN):
            student = self._student('cash', 'es_ES')
            so = self.env['sale.order'].sudo().create({
                'partner_id': student.partner_id.id, 'plan_id': self.plan.id,
                'fitness_payment_method': 'cash',
                'fitness_cash_requested_on': fields.Datetime.now()})
            self.env['sale.order.line'].sudo().create({
                'order_id': so.id, 'product_id': self.product.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 130.0})
            so.with_user(manager).action_fitness_approve_cash()
        bell = self.env['fitness.notification'].sudo().search([
            ('user_id', '=', student.id), ('notification_type', '=', 'purchase_completed')])
        self.assertEqual(len(bell), 1)
        self.assertEqual(bell.action_url, '/my/fixed-class')

    def test_transfer_signed_checkout_still_goes_to_her_hours(self):
        """The signed path (transfer, no card provider on) already redirected."""
        self.env['payment.provider'].sudo().search([]).write({'state': 'disabled'})
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                with common.freeze_time(PIN):
                    self._schedule(19, weekday='tue', start=date(2026, 10, 13))
                    student = self._student('transfer' + lang[:2], lang)
                    self._login(student, lang)
                    page = self.url_open('/my/packages/%d/checkout' % self.product.id).text
                    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page).group(1)
                    r = self.url_open('/my/packages/%d/checkout' % self.product.id, data={
                        'csrf_token': token, 'plan_id': self.plan.id,
                        'payment_method': 'transfer', 'terms_accepted': '1'})
                    self.assertIn('/sign', r.url, 'not sent to the signature step: %s' % r.url)
                    order_id = int(re.search(r'/my/checkout/(\d+)/sign', r.url).group(1))
                    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text).group(1)
                    r = self.url_open('/my/checkout/%d/complete' % order_id, data={
                        'csrf_token': token, 'signed_by': student.name,
                        'signature': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='})
                self.assertIn('/my/fixed-class', r.url, 'landed on %s' % r.url)
