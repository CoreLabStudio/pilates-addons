# -*- coding: utf-8 -*-
"""A membership paid by card: the card form saves the card, as the payment does.

The pay page (/my/packages/pay/<id>) rendered Odoo's payment form without
the order, while the payment itself goes through /my/orders/<id>/transaction,
which passes it. For a membership Odoo then created the payment to save the
card (setup_future_usage off_session) and the card form in the browser was
set up not to (null), and Stripe refused every attempt:

    The provided setup_future_usage (off_session) does not match the
    expected setup_future_usage (null).

Aran Bel Busqueta tried 14 times for S00487 (18-20 Oct 2026) and paid by
Bizum in the end. A payment cannot be completed against Stripe here, so the
test reads what the page hands the card form and compares it with what the
transaction route will ask for. Packs save nothing, before and after.
"""
import html
import json
import re

from odoo.tests import HttpCase, tagged

PW = 'Card-form-2026'


@tagged('post_install', '-at_install')
class TestMembershipCardForm(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('fitness.opening_date', '')
        cls.student = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'CF Student', 'login': 'cf.student@example.invalid',
            'email': 'cf.student@example.invalid', 'password': PW,
            'group_ids': [(6, 0, [env.ref('base.group_portal').id,
                                  env.ref('fitness_core.group_fitness_student').id])]})
        # Production runs Stripe; a gate database is a fresh install of our
        # modules, which do not depend on payment_stripe. There the test
        # checks that the page hands the order to the payment form; where
        # Stripe is installed it reads the card form itself.
        cls.has_stripe = bool(env['ir.module.module'].sudo().search_count(
            [('name', '=', 'payment_stripe'), ('state', '=', 'installed')]))
        if not cls.has_stripe:
            return
        cls.stripe = env['payment.provider'].sudo().search(
            [('code', '=', 'stripe'), ('company_id', '=', env.company.id)], limit=1)
        cls.stripe.write({
            'state': 'test', 'allow_tokenization': True, 'is_published': True,
            'stripe_secret_key': 'sk_test_dummy', 'stripe_publishable_key': 'pk_test_dummy'})
        card = env['payment.method'].sudo().with_context(active_test=False).search([('code', '=', 'card')], limit=1)
        card = card.sudo().with_context(active_test=False)
        card.write({'provider_ids': [(4, cls.stripe.id)]})
        card.write({'active': True})
        cls.card = card

    def _order(self, product, plan=None):
        so = self.env['sale.order'].sudo().create(dict(
            {'partner_id': self.student.partner_id.id, 'fitness_payment_method': 'stripe'},
            **({'plan_id': plan.id} if plan else {})))
        self.env['sale.order.line'].sudo().create({
            'order_id': so.id, 'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1, 'price_unit': 65.0})
        return so

    def _card_forms(self, order):
        self.authenticate(self.student.login, PW)
        page = self.url_open('/my/packages/pay/%d' % order.id).text
        raw = re.findall(r'data-stripe-inline-form-values="([^"]*)"', page)
        self.assertTrue(raw, 'no Stripe card form on the pay page')
        return [json.loads(html.unescape(v)) for v in raw]

    def test_the_pay_page_hands_the_order_to_the_payment_form(self):
        arch = self.env.ref('fitness_portal.portal_packages_pay').arch_db
        call = arch[arch.index('t-call="payment.form"'):]
        call = call[:call.index('</t>', call.index('reference_prefix') + 1) + 200]
        self.assertIn('t-set="sale_order_id"', call,
                      'the payment form is not told which order it pays, so a membership card '
                      'form does not save the card while the payment does')

    def test_a_membership_card_form_saves_the_card_like_the_payment(self):
        if not self.has_stripe:
            return  # covered by test_the_pay_page_hands_the_order_to_the_payment_form
        plan = self.env.ref('sale_subscription.subscription_plan_month')
        product = self.env.ref('fitness_subscriptions.product_barre_clase_fija_1')
        order = self._order(product, plan)
        self.assertTrue(order.is_subscription, 'fixture: not a membership')
        # What /my/orders/<id>/transaction will create for a card.
        payment_saves = bool(self.stripe.allow_tokenization and self.card.support_tokenization
                             and self.stripe._is_tokenization_required(sale_order_id=order.id))
        self.assertTrue(payment_saves, 'fixture: the card payment of a membership does not save the card')
        forms = self._card_forms(order)
        self.assertTrue(any(f.get('is_tokenization_required') for f in forms),
                        'the card form of a membership does not save the card, the payment does: '
                        'Stripe refuses it (setup_future_usage off_session vs null)')

    def test_a_pack_saves_nothing(self):
        if not self.has_stripe:
            return
        pack = self.env['product.template'].sudo().create({
            'name': 'CF Pack', 'type': 'service', 'list_price': 50.0, 'sale_ok': True,
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 90,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        order = self._order(pack)
        self.assertFalse(self.stripe._is_tokenization_required(sale_order_id=order.id))
        self.assertFalse(any(f.get('is_tokenization_required') for f in self._card_forms(order)),
                         'a pack card form saves the card')
