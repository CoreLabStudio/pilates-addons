# -*- coding: utf-8 -*-
"""While a payment for her plan is waiting, the shop takes no second one.

Berta's case: her plan closed and her Bizum renewal was still with the bank,
and her card offered Renew - a second payment for the same period. While a
card or Bizum payment is pending (or a cash request waits at the desk), the
shop card and the product page say "Waiting for your payment" instead, and
the checkout sends her back to the shop. Once the payment fails, Renew is
offered again; once it goes through, the plan is Active.

A transfer is unchanged: that order is confirmed at checkout and the plan
already shows as Active.
"""
from datetime import date

from odoo.tests import HttpCase, common, tagged

from .test_close_ended_memberships import CloseFixture, at
from .test_fixed_class_after_payment import PW

WAITING = 'Waiting for your payment'
DAY = date(2026, 10, 15)


@tagged('post_install', '-at_install')
class TestNoSecondPaymentWhilePending(CloseFixture, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._close_fixture()
        cls.env['res.lang']._activate_lang('en_US')

    def _login(self, user):
        self.authenticate(user.login, PW)
        self.opener.cookies.set('mv_lang', 'en_US')
        self.opener.cookies.set('frontend_lang', 'en_US')

    def _closed(self, tag):
        student, old = self._paid_member(tag)
        self._run(date(2026, 10, 13))
        self.assertEqual(old.subscription_state, '6_churn')
        return student, old

    def _bizum_pending(self, student, state='pending'):
        with common.freeze_time(at(DAY)):
            order = self.env['sale.order'].sudo().create({
                'partner_id': student.partner_id.id, 'plan_id': self.plan.id,
                'fitness_payment_method': 'bizum'})
            self.env['sale.order.line'].sudo().create({
                'order_id': order.id, 'product_id': self.product.product_variant_ids[:1].id,
                'product_uom_qty': 1, 'price_unit': 130.0})
            PM = self.env['payment.method'].sudo().with_context(active_test=False)
            tx = self.env['payment.transaction'].sudo().create({
                'provider_id': self.env['payment.provider'].sudo().search([], limit=1).id,
                'payment_method_id': (PM.search([('code', '=', 'bizum')], limit=1) or PM.search([], limit=1)).id,
                'reference': 'NSP-%s' % order.id, 'amount': order.amount_total,
                'currency_id': order.currency_id.id, 'partner_id': student.partner_id.id,
                'state': state, 'sale_order_ids': [(6, 0, order.ids)]})
        return order, tx

    def test_a_payment_form_she_opened_and_left_does_not_hide_renew(self):
        """She opened the card form for her renewal and closed it.

        Odoo leaves a draft transaction behind for every payment form that
        was opened, paid or not. Counting it as "waiting for your payment"
        would hide Renew from her for good, with no payment anywhere to wait
        for - so a draft does not count, and Renew stays on the card, on the
        product page and at the checkout.
        """
        student, old = self._closed('nspleft')
        order, tx = self._bizum_pending(student, state='draft')
        checkout, shop, detail, r = self._pages(student)
        self.assertIn(checkout, shop, 'an abandoned payment form hid Renew on the shop card')
        self.assertNotIn(WAITING, shop)
        self.assertIn(checkout, detail, 'an abandoned payment form hid Renew on the product page')
        self.assertNotIn(WAITING, detail)
        self.assertIn(checkout, r.url, 'the checkout refused her after an abandoned form: %s' % r.url)
        self.assertEqual(tx.state, 'draft')

    def _pages(self, student):
        checkout = '/my/packages/%d/checkout' % self.product.id
        with common.freeze_time(at(DAY)):
            self._login(student)
            shop = self.url_open('/my/packages?tab=subscriptions').text
            detail = self.url_open('/my/packages/%d' % self.product.id).text
            r = self.url_open(checkout)
        return checkout, shop, detail, r

    def test_bizum_pending_shows_waiting_not_renew_and_failure_brings_renew_back(self):
        student, old = self._closed('nspfail')
        order, tx = self._bizum_pending(student)
        checkout, shop, detail, r = self._pages(student)
        self.assertNotIn(checkout, shop, 'the shop card still offers a second payment')
        self.assertIn(WAITING, shop)
        self.assertNotIn(checkout, detail, 'the product page still offers a second payment')
        self.assertIn(WAITING, detail)
        self.assertNotIn('/checkout', r.url, 'the checkout opened beside a pending payment: %s' % r.url)
        self.assertIn('/my/packages', r.url)

        tx.state = 'cancel'
        checkout, shop, detail, r = self._pages(student)
        self.assertIn(checkout, shop, 'Renew did not come back after the payment failed')
        self.assertIn(checkout, detail)
        self.assertIn(checkout, r.url, 'the checkout refused after the payment failed')
        self.assertEqual(old.subscription_state, '6_churn')

    def test_bizum_completed_shows_active_and_no_renew(self):
        student, old = self._closed('nspdone')
        order, tx = self._bizum_pending(student)
        with common.freeze_time(at(DAY)):
            tx.state = 'done'
            order.action_confirm()
            order._create_invoices().action_post()
        self.assertEqual(order.subscription_state, '3_progress')
        checkout, shop, detail, r = self._pages(student)
        self.assertNotIn(checkout, shop, 'Renew offered on a plan she has just paid')
        self.assertNotIn(WAITING, shop)
        self.assertNotIn(checkout, detail)

    def test_cash_request_product_page_shows_waiting_not_renew(self):
        student, old = self._closed('nspcash')
        self._cash_request(student, DAY)
        checkout, shop, detail, r = self._pages(student)
        self.assertNotIn(checkout, shop)
        self.assertIn(WAITING, shop)
        self.assertNotIn(checkout, detail, 'the product page offered Renew beside a cash request')
        self.assertIn(WAITING, detail)
        self.assertIn('cash_pending=1', r.url)
