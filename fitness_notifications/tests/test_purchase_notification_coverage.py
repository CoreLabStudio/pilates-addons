# -*- coding: utf-8 -*-
"""The shop promises "we will tell you when it goes through". Does it?

The pending message on the payment return says we will tell her as soon as
the bank confirms. That promise is only worth making if confirming a
purchase actually produces a notification - so this drives a transaction
from pending to done through the REAL path (_set_done then _post_process,
which is what a provider's webhook calls) and looks for the notification
afterwards.

Driven per product type, because the handler is gated on
fitness_is_package and a type that is not one produces nothing. Which type
that is, is the point of the test rather than a detail.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPurchaseNotificationCoverage(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        portal = self.env.ref('base.group_portal')
        self.student = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'Promise Student', 'login': 'promise.student',
                'email': 'promise.student@example.invalid',
                'group_ids': [(6, 0, [portal.id])]})
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

    def _notifs(self):
        return self.env['fitness.notification'].sudo().search_count([
            ('user_id', '=', self.student.id),
            ('notification_type', '=', 'purchase_completed')])

    def _drive(self, product, ref):
        """pending -> done the way a provider's webhook does it."""
        # A recurring product will not confirm without a plan on the order
        # ("add a recurring plan on the subscription"). The plan is written
        # FIRST and the line after: setting plan_id and order_line in one
        # write discards an explicit price, which has bitten this codebase
        # before.
        plan = product.fitness_subscription_plan_id
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student.partner_id.id,
            **({'plan_id': plan.id} if plan else {})})
        self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.product_variant_ids[:1].id,
            'product_uom_qty': 1,
            # Explicit, so the order total does not depend on whatever
            # promotion the chosen product is running on this database.
            'price_unit': 25.0})
        order.invalidate_recordset()
        tx = self.env['payment.transaction'].sudo().create({
            'provider_id': self.provider.id,
            'payment_method_id': self.method.id,
            'reference': ref,
            # EXACTLY the order total, with no fallback.
            #
            # This was `order.amount_total or 10.0`, which is fine until
            # the product prices to zero - and both trial products do
            # right now, because their promotion runs to 16 October. A
            # 10.00 transaction against a 0.00 order is an amount
            # mismatch, _check_amount_and_confirm_order refuses to
            # confirm on a mismatch, and the order stayed draft. The
            # suite passed locally because the products these searches
            # happen to pick here are priced; on odoo.sh they are not.
            # The price below makes that independent of the database.
            'amount': order.amount_total,
            'currency_id': order.currency_id.id,
            'partner_id': self.student.partner_id.id,
            'sale_order_ids': [(6, 0, order.ids)]})
        tx.sudo().write({'state': 'pending'})
        before = self._notifs()
        tx.sudo()._set_done()
        # _check_amount_and_confirm_order is the sale-side hook that
        # _post_process calls on a done transaction, and confirming the
        # order is what produces the notification. The rest of
        # _post_process posts invoices and creates an account.payment,
        # which needs a journal and a payment-method line that a synthetic
        # provider has not got - so that half is deliberately not driven
        # here. The path under test is the one that tells the student.
        tx.sudo()._check_amount_and_confirm_order()
        order.invalidate_recordset()
        return order, before, self._notifs()

    def _product(self, domain, label):
        prod = self.env['product.template'].sudo().search(domain, limit=1)
        if not prod:
            self.skipTest("no %s product on this database" % label)
        return prod

    def test_a_pack_purchase_tells_her(self):
        prod = self._product(
            [('fitness_is_package', '=', True),
             ('fitness_class_count', '>', 1)], 'multi-class pack')
        order, before, after = self._drive(prod, 'PROMISE-PACK')
        self.assertIn(order.state, ('sale', 'done'),
                      "the order did not confirm, so nothing was credited")
        self.assertEqual(after, before + 1,
                         "a pack purchase produced no notification, so the "
                         "pending promise cannot be kept for packs")

    def test_a_trial_purchase_tells_her(self):
        prod = self.env.ref('fitness_packages.product_barre_trial',
                            raise_if_not_found=False)
        if not prod:
            self.skipTest("no trial product on this database")
        order, before, after = self._drive(prod, 'PROMISE-TRIAL')
        self.assertIn(order.state, ('sale', 'done'))
        self.assertEqual(after, before + 1,
                         "a trial purchase produced no notification")

    def test_a_membership_purchase_tells_her(self):
        """It used to tell her nothing. The handler was gated on
        fitness_is_package and a subscription is not one, so the payment
        return promised "we will tell you as soon as it goes through" and
        for a membership nothing ever came."""
        prod = self.env['product.template'].sudo().search(
            [('fitness_is_subscription_plan', '=', True)], limit=1)
        if not prod:
            self.skipTest("no membership product on this database")
        order, before, after = self._drive(prod, 'PROMISE-MEMBERSHIP')
        self.assertIn(order.state, ('sale', 'done'),
                      "the membership order did not confirm")
        self.assertEqual(after, before + 1,
                         "a membership purchase still produces no "
                         "notification, so the pending promise is unkept")

    def test_a_combined_order_tells_her_once(self):
        """Several lines describing one purchase is one piece of news."""
        pack = self._product(
            [('fitness_is_package', '=', True)], 'package')
        sub = self.env['product.template'].sudo().search(
            [('fitness_is_subscription_plan', '=', True)], limit=1)
        if not sub:
            self.skipTest("no membership product on this database")
        plan = sub.fitness_subscription_plan_id
        order = self.env['sale.order'].sudo().create({
            'partner_id': self.student.partner_id.id,
            **({'plan_id': plan.id} if plan else {})})
        for prod in (pack, sub):
            self.env['sale.order.line'].sudo().create({
                'order_id': order.id,
                'product_id': prod.product_variant_ids[:1].id,
                'product_uom_qty': 1})
        order.invalidate_recordset()
        before = self._notifs()
        order.action_confirm()
        self.assertEqual(self._notifs(), before + 1,
                         "a combined order told her more than once")

