# -*- coding: utf-8 -*-
"""What the shop says when she comes back from paying.

Every state a provider can leave her in, and the promise each one makes.

The states matter here more than usual. Production carries S00389: an open
order with TWO draft transactions and Stripe saying the money was taken,
and S00414, which sat with a done transaction against an unconfirmed order
until somebody settled it by hand. So "draft" is not nothing-happened, and
"done" is not necessarily credited - the page has to be careful in both
directions.
"""
from odoo.tests import HttpCase, tagged

ASK = 'id="mv-notif-booked"'


@tagged("post_install", "-at_install")
class TestPaymentReturnStates(HttpCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Pay Student', 'login': 'pay.student',
                'email': 'pay.student@example.invalid',
                'password': 'pay-pass-9134',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('fitness_core.group_fitness_student').id])]})
        # Every payment.method ships archived and every provider ships
        # disabled, so search([]) returns nothing and these tests SKIPPED -
        # which reads as a pass and proves nothing. One is activated here
        # instead. Nothing contacts a provider: the transactions are driven
        # by hand, and state is what is under test.
        self.provider = self.env['payment.provider'].sudo().search(
            [('code', '=', 'none')], limit=1)
        if not self.provider:
            self.provider = self.env['payment.provider'].sudo().search(
                [], limit=1)
        self.method = self.env['payment.method'].sudo().with_context(
            active_test=False).search([], limit=1)
        if not self.provider or not self.method:
            self.skipTest("this database has no payment provider at all")
        # Order matters: Odoo refuses to activate a payment method until an
        # ENABLED provider supports it ("this payment method needs a partner
        # in crime"). So the provider is enabled and linked first.
        self.provider.sudo().write({
            'state': 'test',
            'payment_method_ids': [(4, self.method.id)]})
        self.method.sudo().write({'active': True})
        self.env.registry.clear_cache()

    def _order(self, product):
        return self.env['sale.order'].sudo().create({
            'partner_id': self.student.partner_id.id,
            'order_line': [(0, 0, {
                'product_id': product.product_variant_ids[:1].id,
                'product_uom_qty': 1})]})

    def _tx(self, state, order=None, ref=None):
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': self.provider.id,
            'payment_method_id': self.method.id,
            'reference': ref or ('PAY-%s' % state),
            'amount': 25.0,
            'currency_id': self.env.company.currency_id.id,
            'partner_id': self.student.partner_id.id,
            'sale_order_ids': [(6, 0, order.ids)] if order else False,
        })
        tx.sudo().write({'state': state})
        return tx

    def _page(self, path='/my/packages?from_payment=1'):
        self.authenticate('pay.student', 'pay-pass-9134')
        return self.url_open(path).text

    # ── in progress ──────────────────────────────────────────────────────
    def test_draft_is_in_progress_not_a_failure(self):
        """S00389's shape. Stripe may already hold her money."""
        self._tx('draft')
        body = self._page()
        self.assertIn('not confirmed it yet', body,
                      "a draft transaction was not reported as in progress")
        self.assertNotIn('was not completed', body,
                         "a draft transaction was reported as a failure")
        self.assertIn(ASK, body, "the in-progress state lost the ask")

    def test_pending_is_in_progress(self):
        self._tx('pending')
        body = self._page()
        self.assertIn('not confirmed it yet', body)
        self.assertIn(ASK, body)

    def test_authorized_with_an_unconfirmed_order_is_in_progress(self):
        """Stripe's manual-capture state: reserved, not taken. Nothing is in
        her account until the studio captures it."""
        order = self._order(self._any_package())
        self._tx('authorized', order=order)
        body = self._page()
        self.assertIn('not confirmed it yet', body,
                      "authorized was reported as paid")
        self.assertIn(ASK, body)

    def test_done_against_an_unconfirmed_order_is_in_progress(self):
        """S00414's shape: the money arrived, the order never confirmed, so
        there is no credit. Saying "payment received" here is a promise the
        account cannot keep."""
        order = self._order(self._any_package())
        self.assertEqual(order.state, 'draft')
        self._tx('done', order=order)
        body = self._page()
        self.assertIn('not confirmed it yet', body,
                      "done against a draft order was reported as paid")

    # ── finished ─────────────────────────────────────────────────────────
    def test_done_with_a_confirmed_order_is_paid(self):
        order = self._order(self._any_package())
        order.action_confirm()
        self._tx('done', order=order)
        body = self._page()
        self.assertIn('Payment received', body,
                      "a confirmed purchase was not reported as paid")
        self.assertIn(ASK, body)

    # ── refused ──────────────────────────────────────────────────────────
    def test_cancel_and_error_are_failures(self):
        for state in ('cancel', 'error'):
            self._tx(state, ref='PAY-FAIL-%s' % state)
            body = self._page()
            self.assertIn('was not completed', body,
                          "%s was not reported as a failure" % state)
            self.assertNotIn(ASK, body,
                             "the ask appeared after a %s" % state)

    def test_the_failure_does_not_claim_nothing_was_charged(self):
        """It can be false at the moment she reads it."""
        self._tx('error', ref='PAY-FAIL-COPY')
        body = self._page()
        self.assertNotIn('Nothing has been charged', body)
        self.assertIn('see a charge', body,
                      "she is not told what to do if her bank shows one")

    # ── stale ────────────────────────────────────────────────────────────
    def test_a_transaction_older_than_thirty_minutes_shows_nothing(self):
        from datetime import timedelta
        from odoo import fields
        tx = self._tx('done')
        tx.sudo().write({
            'create_date': fields.Datetime.now() - timedelta(minutes=45)})
        body = self._page()
        for phrase in ('Payment received', 'not confirmed it yet',
                       'was not completed'):
            self.assertNotIn(phrase, body,
                             "an old transaction is still being reported")
        self.assertNotIn(ASK, body)

    # ── helpers ──────────────────────────────────────────────────────────
    def _any_package(self):
        prod = self.env['product.template'].sudo().search(
            [('fitness_is_package', '=', True)], limit=1)
        if not prod:
            self.skipTest("no package product on this database")
        return prod
