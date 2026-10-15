# -*- coding: utf-8 -*-
"""A membership closes the day after its last paid day, and she is told once.

Odoo's weekly expiry job left a lapsed plan "In Progress" for 16 to 22 days,
still paying for classes, and told her nothing. The daily job closes it the
next day (grace fitness.close_grace_days, default 0) and sends one
"expired" message - unless she has already asked to carry on, in which case
the message waits until that request is declined or stays unsettled
fitness.expired_notice_wait_days (default 3).

A closed fixed-class plan comes back through the shop or the desk's
Renew (cash) as a new membership from that day, and both end at "Choose
your weekly class".

Clock pinned on every step (Madrid), languages explicit.
"""
import re
from datetime import date, datetime, timedelta

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, common, tagged

from odoo.addons.fitness_core.models.studio_lang import studio_datetime, studio_lang

from .test_fixed_class_after_payment import FixedFixture, MANAGER, PW

SEP13 = date(2026, 9, 13)                       # first paid month: 13 Sep - 12 Oct
LAST_PAID = date(2026, 10, 12)
NEXT = date(2026, 10, 13)


def at(d, hour=10):
    """10:00 Madrid on `d`, as the naive UTC Odoo stores (CEST, UTC+2)."""
    return datetime(d.year, d.month, d.day, hour - 2, 0)


class CloseFixture(FixedFixture):

    @classmethod
    def _close_fixture(cls):
        cls._fixture()
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'CJ Manager', 'login': 'cj.manager@example.invalid',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref(MANAGER).id,
                                  cls.env.ref('sales_team.group_sale_manager').id,
                                  cls.env.ref('account.group_account_invoice').id])]})
        journal = cls.env['account.journal'].sudo().search(
            [('type', '=', 'cash'), ('company_id', '=', cls.env.company.id)], limit=1)
        if not journal:
            cls.env['account.journal'].sudo().create({
                'name': 'CJ Cash', 'code': 'CJC', 'type': 'cash',
                'company_id': cls.env.company.id})

    def _paid_member(self, tag, lang='en_US'):
        """A member who paid one month from 13 Sep: last paid day 12 Oct."""
        with common.freeze_time(at(SEP13)):
            student = self._student(tag, lang)
            so = self._membership(student, start=SEP13)
            inv = so._create_invoices()
            inv.action_post()
        self.assertEqual(so.next_invoice_date, NEXT)
        return student, so

    def _run(self, d):
        with common.freeze_time(at(d)):
            return self.env['sale.order']._cron_fitness_close_ended_memberships()

    def _told(self, student):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', student.id), ('notification_type', '=', 'membership_expired')])

    def _cash_request(self, student, d):
        with common.freeze_time(at(d)):
            so = self.env['sale.order'].sudo().create({
                'partner_id': student.partner_id.id, 'plan_id': self.plan.id,
                'fitness_payment_method': 'cash',
                'fitness_cash_requested_on': fields.Datetime.now()})
            self.env['sale.order.line'].sudo().create({
                'order_id': so.id, 'product_id': self.product.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 130.0})
        return so


@tagged('post_install', '-at_install')
class TestCloseEndedMemberships(CloseFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._close_fixture()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    # -- when it closes --------------------------------------------------

    def test_lapsed_plan_closes_the_day_after_its_last_paid_day(self):
        student, so = self._paid_member('lapsed')
        self._run(LAST_PAID)
        self.assertEqual(so.subscription_state, '3_progress', 'closed on her last paid day')
        self.assertFalse(self._told(student))
        self._run(NEXT)
        self.assertEqual(so.subscription_state, '6_churn', 'still running the day after')
        self.assertEqual(so.end_date, LAST_PAID)
        self.assertEqual(so.close_reason_id,
                         self.env.ref('fitness_portal.close_reason_membership_ended'))
        self.assertEqual(len(self._told(student)), 1)

    def test_a_plan_with_an_end_date_closes_the_day_after_it(self):
        student, so = self._paid_member('enddate')
        so.end_date = date(2026, 10, 5)
        self._run(date(2026, 10, 5))
        self.assertEqual(so.subscription_state, '3_progress')
        self._run(date(2026, 10, 6))
        self.assertEqual(so.subscription_state, '6_churn')
        self.assertEqual(so.end_date, date(2026, 10, 5))
        self.assertEqual(len(self._told(student)), 1)

    def test_grace_is_a_parameter_and_defaults_to_none(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.close_grace_days', '2')
        _student, so = self._paid_member('grace')
        self._run(NEXT + timedelta(days=1))
        self.assertEqual(so.subscription_state, '3_progress', 'closed inside the grace days')
        self._run(NEXT + timedelta(days=2))
        self.assertEqual(so.subscription_state, '6_churn')
        self.assertEqual(so.end_date, LAST_PAID, 'the end is her last paid day, not the close')

    def test_never_billed_and_paused_are_left_alone(self):
        with common.freeze_time(at(SEP13)):
            waiting = self._membership(self._student('neverbilled'), start=SEP13)
        _s, paused = self._paid_member('paused')
        paused.subscription_state = '4_paused'
        self._run(date(2026, 10, 20))
        self.assertEqual(waiting.subscription_state, '3_progress',
                         'a purchase waiting for its first payment was closed')
        self.assertEqual(paused.subscription_state, '4_paused')

    def test_twice_then_odoos_job_changes_nothing(self):
        student, so = self._paid_member('twice')
        self._run(NEXT)
        self._run(NEXT)
        self._run(NEXT + timedelta(days=1))
        self.assertEqual(len(self._told(student)), 1, 'told more than once')
        with common.freeze_time(at(NEXT + timedelta(days=7))):
            self.env['sale.order']._cron_subscription_expiration()
        self.assertEqual(so.subscription_state, '6_churn')
        self.assertEqual(so.close_reason_id,
                         self.env.ref('fitness_portal.close_reason_membership_ended'))
        self.assertEqual(so.end_date, LAST_PAID)
        self.assertEqual(len(self._told(student)), 1)

    def test_a_closed_plan_no_longer_pays_for_classes(self):
        student, so = self._paid_member('nopay')
        Booking = self.env['fitness.booking']
        live = lambda: self.env['sale.order'].sudo().search(
            Booking._fitness_live_membership_domain(student.partner_id.id))
        self.assertIn(so, live())
        self._run(NEXT)
        self.assertNotIn(so, live(), 'a closed plan can still pay for a booking')

    def test_the_message_in_her_language(self):
        titles = {'es_ES': 'Tu cuota ha terminado',
                  'ca_ES': "La teva quota s'ha acabat",
                  'en_US': 'Your membership has ended'}
        for lang, title in titles.items():
            with self.subTest(lang=lang):
                student, _so = self._paid_member('lang' + lang[:2], lang)
                self._run(NEXT)
                told = self._told(student)
                self.assertEqual(len(told), 1)
                self.assertEqual(told.title, title)
                self.assertEqual(told.action_url, '/my/packages?tab=subscriptions')

    # -- (1) she has already asked to carry on ---------------------------

    def test_renewed_and_paid_closes_with_no_message(self):
        student, old = self._paid_member('renewed')
        with common.freeze_time(at(date(2026, 10, 11))):
            new = self._membership(student)
            new._create_invoices().action_post()
        self.assertEqual(old.end_date, LAST_PAID, 'the renewal did not set the old end')
        self._run(NEXT)
        self._run(NEXT + timedelta(days=10))
        self.assertEqual(old.subscription_state, '6_churn')
        self.assertEqual(new.subscription_state, '3_progress')
        self.assertFalse(self._told(student), 'told "expired" after renewing')

    def test_cash_request_waiting_holds_the_message_until_declined(self):
        student, old = self._paid_member('cashdecl')
        req = self._cash_request(student, date(2026, 10, 12))
        self._run(NEXT)
        self.assertEqual(old.subscription_state, '6_churn', 'the old plan stayed open')
        self.assertFalse(self._told(student), 'told while her cash was on its way')
        with common.freeze_time(at(NEXT)):
            req.with_user(self.manager).action_fitness_decline_cash()
        self._run(NEXT + timedelta(days=1))
        self.assertEqual(len(self._told(student)), 1, 'not told after the decline')

    def test_cash_request_unpaid_after_the_wait_sends_it(self):
        student, _old = self._paid_member('cashwait')
        self._cash_request(student, date(2026, 10, 12))
        for d in (NEXT, NEXT + timedelta(days=1), NEXT + timedelta(days=2)):
            self._run(d)
            self.assertFalse(self._told(student), 'told on %s, inside the wait' % d)
        self._run(NEXT + timedelta(days=3))
        self.assertEqual(len(self._told(student)), 1)

    def test_cash_request_approved_is_never_told(self):
        student, _old = self._paid_member('cashok')
        req = self._cash_request(student, date(2026, 10, 12))
        self._run(NEXT)
        with common.freeze_time(at(NEXT)):
            req.with_user(self.manager).action_fitness_approve_cash()
        for d in (NEXT + timedelta(days=1), NEXT + timedelta(days=5)):
            self._run(d)
        self.assertFalse(self._told(student))

    def test_transfer_confirmed_and_unpaid(self):
        """Paid later: never told. Still unpaid after the wait: told."""
        paid, old_paid = self._paid_member('trfpaid')
        unpaid, old_unpaid = self._paid_member('trfunpaid')
        orders = {}
        with common.freeze_time(at(date(2026, 10, 11))):
            for student in (paid, unpaid):
                so = self._membership(student)
                so.fitness_payment_method = 'transfer'
                orders[student] = so
        self.assertEqual(old_paid.end_date, LAST_PAID)
        self._run(NEXT)
        self.assertEqual(old_paid.subscription_state, '6_churn')
        self.assertEqual(old_unpaid.subscription_state, '6_churn')
        self.assertFalse(self._told(paid) | self._told(unpaid))
        with common.freeze_time(at(NEXT + timedelta(days=1))):
            orders[paid]._create_invoices().action_post()
        self._run(NEXT + timedelta(days=2))
        self.assertFalse(self._told(unpaid), 'told inside the wait')
        self._run(NEXT + timedelta(days=3))
        self.assertFalse(self._told(paid), 'told after paying the transfer')
        self.assertEqual(len(self._told(unpaid)), 1, 'transfer never paid and never told')

    def test_card_or_bizum_pending_then_declined(self):
        student, _old = self._paid_member('card')
        with common.freeze_time(at(date(2026, 10, 12))):
            so = self.env['sale.order'].sudo().create({
                'partner_id': student.partner_id.id, 'plan_id': self.plan.id})
            self.env['sale.order.line'].sudo().create({
                'order_id': so.id, 'product_id': self.product.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 130.0})
            provider = self.env['payment.provider'].sudo().search([], limit=1)
            method = self.env['payment.method'].sudo().with_context(active_test=False).search([], limit=1)
            tx = self.env['payment.transaction'].sudo().create({
                'provider_id': provider.id, 'payment_method_id': method.id,
                'reference': 'CJ-pending', 'amount': so.amount_total,
                'currency_id': so.currency_id.id, 'partner_id': student.partner_id.id,
                'state': 'pending', 'sale_order_ids': [(6, 0, so.ids)]})
        self._run(NEXT)
        self.assertFalse(self._told(student), 'told while her payment was pending')
        tx.state = 'cancel'
        self._run(NEXT + timedelta(days=1))
        self.assertEqual(len(self._told(student)), 1, 'not told after the payment failed')

    # -- (3) classes already booked after the end ------------------------

    def test_classes_booked_after_the_end_are_left_booked_and_named(self):
        with common.freeze_time(at(date(2026, 10, 6))):
            tuesdays = self._schedule(19, weekday='tue', start=date(2026, 10, 6))
        student, so = self._paid_member('booked')
        self._hours(so, tuesdays[0])
        with common.freeze_time(at(date(2026, 10, 6))):
            so._fitness_place_slots(future_only=True)
        # Placement books inside the paid period only; an end date set
        # before it - a renewal that took over early - leaves the 6 Oct
        # class after the end.
        so.end_date = date(2026, 10, 5)
        after = self.env['fitness.booking'].sudo().search([
            ('subscription_id', '=', so.id), ('state', '!=', 'cancelled'),
            ('class_start', '>=', datetime(2026, 10, 6))])
        self.assertTrue(after, 'fixture: nothing booked after the end')
        self._run(date(2026, 10, 6))
        self.assertEqual(so.subscription_state, '6_churn')
        self.assertTrue(all(b.state != 'cancelled' for b in after), 'a booked class was cancelled')
        lang = studio_lang(self.env)
        first = studio_datetime(self.env, after[0].class_start, 'd MMM y HH:mm', lang)
        note = so.message_ids.filtered(lambda m: first in (m.body or ''))
        self.assertTrue(note, 'the classes after the end were not named in the chatter')


@tagged('post_install', '-at_install')
class TestRenewAfterClose(CloseFixture, HttpCase):
    """(2) A closed fixed-class plan comes back, from the shop or the desk,
    and both end at "Choose your weekly class"."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._close_fixture()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def _login(self, user, lang):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', lang)
        self.opener.cookies.set('frontend_lang', lang)

    def _closed_member(self, tag, lang):
        student, old = self._paid_member(tag, lang)
        self._run(NEXT)
        self.assertEqual(old.subscription_state, '6_churn')
        return student, old

    def test_shop_renew_after_close_ends_at_choose_your_weekly_class(self):
        headings = {'es_ES': 'Elige tu clase semanal', 'ca_ES': 'Tria la teva classe setmanal',
                    'en_US': 'Choose your weekly class'}
        self.env['payment.provider'].sudo().search([]).write({'state': 'disabled'})
        for lang, heading in headings.items():
            with self.subTest(lang=lang):
                student, old = self._closed_member('shop' + lang[:2], lang)
                with common.freeze_time(at(date(2026, 10, 15))):
                    self._schedule(19, weekday='tue', start=date(2026, 10, 20))
                    self._login(student, lang)
                    shop = self.url_open('/my/packages?tab=subscriptions').text
                    self.assertIn('/my/packages/%d/checkout' % self.product.id, shop,
                                  'no Renew on the card of a closed plan')
                    page = self.url_open('/my/packages/%d/checkout' % self.product.id).text
                    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page).group(1)
                    r = self.url_open('/my/packages/%d/checkout' % self.product.id, data={
                        'csrf_token': token, 'plan_id': self.plan.id,
                        'payment_method': 'transfer', 'terms_accepted': '1'})
                    order_id = int(re.search(r'/my/checkout/(\d+)/sign', r.url).group(1))
                    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text).group(1)
                    r = self.url_open('/my/checkout/%d/complete' % order_id, data={
                        'csrf_token': token, 'signed_by': student.name,
                        'signature': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='})
                self.assertIn('/my/fixed-class', r.url, 'landed on %s' % r.url)
                self.assertIn(heading, r.text)
                new = self.env['sale.order'].sudo().browse(order_id)
                self.assertEqual(new.start_date, date(2026, 10, 15), 'did not start that day')
                self.assertEqual(old.subscription_state, '6_churn')

    def test_desk_renew_cash_after_close_ends_at_choose_your_weekly_class(self):
        for lang in ('es_ES', 'ca_ES', 'en_US'):
            with self.subTest(lang=lang):
                student, old = self._closed_member('desk' + lang[:2], lang)
                with common.freeze_time(at(date(2026, 10, 15))):
                    self._schedule(19, weekday='tue', start=date(2026, 10, 20))
                    action = old.with_user(self.manager).action_fitness_renew_cash()
                self.assertEqual(action.get('tag'), 'display_notification')
                new = self.env['sale.order'].sudo().search([
                    ('partner_id', '=', student.partner_id.id), ('id', '!=', old.id),
                    ('is_subscription', '=', True)])
                self.assertEqual(len(new), 1)
                self.assertEqual(new.subscription_state, '3_progress')
                self.assertEqual(new.start_date, date(2026, 10, 15), 'did not start that day')
                self.assertEqual(new.next_invoice_date, date(2026, 11, 15), 'not one month paid')
                self.assertIn(new.invoice_ids.payment_state, ('paid', 'in_payment'))
                self.assertEqual(new.fitness_payment_method, 'cash')
                shop_lines = self.product.fitness_order_line_vals(
                    student.partner_id, plan=self.plan,
                    period_price=self.product.fitness_effective_price())
                self.assertAlmostEqual(
                    new.amount_untaxed,
                    sum(v['price_unit'] * v.get('product_uom_qty', 1) for v in shop_lines),
                    msg='the desk charged a returning student differently from the shop')
                self.assertEqual(old.subscription_state, '6_churn', 'the closed plan reopened')
                bell = self.env['fitness.notification'].sudo().search([
                    ('user_id', '=', student.id),
                    ('notification_type', '=', 'purchase_completed')], order='id desc', limit=1)
                self.assertEqual(bell.action_url, '/my/fixed-class')
                with common.freeze_time(at(date(2026, 10, 15))):
                    self._login(student, lang)
                    r = self.url_open('/my/fixed-class')
                self.assertIn('/my/fixed-class', r.url, 'sent away from her hours: %s' % r.url)
                # Told once at the close on 13 Oct, before she came back; the
                # renewal adds nothing.
                self.assertEqual(len(self._told(student)), 1)
                self._run(date(2026, 10, 20))
                self.assertEqual(len(self._told(student)), 1, 'told again after renewing at the desk')

    def test_desk_renew_refused_when_another_runs(self):
        student, old = self._closed_member('deskrun', 'en_US')
        with common.freeze_time(at(date(2026, 10, 15))):
            other = self._membership(student, start=date(2026, 10, 15))
            other._create_invoices().action_post()
            with self.assertRaises(Exception):
                old.with_user(self.manager).action_fitness_renew_cash()
        self.assertEqual(self.env['sale.order'].sudo().search_count([
            ('partner_id', '=', student.partner_id.id), ('is_subscription', '=', True)]), 2)
