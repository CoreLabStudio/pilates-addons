# -*- coding: utf-8 -*-
"""The desk gives the four free classes under Free, and still sells a trial.

Sell at the desk with payment method Free offers the four free single
classes and hides the free-trial pair - giving a trial away would spend
the student's one entitlement without saying so. With cash nothing about
the trial changes: it is in the list and sells exactly as it always has,
spending the entitlement as a paid trial does (owner decision Q6). The
free classes never appear on a cash sale.

The list on screen and what the model accepts are one method
(_product_domain), so both halves are tested through the model as well,
the way a hand-made call to /web/dataset/call_button would arrive.

As a fitness manager with no Sales rights, which is what the studio's
managers are. Clock pinned, language explicit.
"""
from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, common, tagged

PINNED = datetime(2026, 10, 12, 8, 0, 0)     # Monday, 10:00 Madrid
FREE = ('fitness_packages.product_courtesy_barre',
        'fitness_packages.product_courtesy_reformer',
        'fitness_packages.product_courtesy_barre_private',
        'fitness_packages.product_courtesy_reformer_private')
TRIALS = ('fitness_packages.product_barre_trial',
          'fitness_packages.product_reformer_trial')


@tagged('post_install', '-at_install')
class TestDeskFreeClasses(TransactionCase):

    longMessage = False

    def setUp(self):
        super().setUp()
        freezer = common.freeze_time(PINNED)
        freezer.start()
        self.addCleanup(freezer.stop)
        self.manager = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'DF Manager', 'login': 'df.manager@example.invalid',
                'lang': 'en_US', 'tz': 'Europe/Madrid',
                'group_ids': [(6, 0, [
                    self.env.ref('base.group_user').id,
                    self.env.ref('fitness_core.group_fitness_manager').id])],
            })
        self.assertFalse(
            self.env['sale.order'].with_user(self.manager).has_access('read'))
        self.student = self.env['res.partner'].create({
            'name': 'DF Student', 'lang': 'en_US',
            'email': 'df.student@example.invalid'})
        self.TR = self.env['fitness.trial.request']

    def _wizard(self, method, product=None, **extra):
        vals = {'partner_id': self.student.id, 'payment_method': method}
        if product:
            vals['product_id'] = product.id
        vals.update(extra)
        return self.env['fitness.desk.sale.wizard'].with_user(
            self.manager).create(vals)

    def _offered(self, method):
        # In memory, as the open form is: nothing is saved until a product
        # is chosen, and product_id is required.
        wiz = self.env['fitness.desk.sale.wizard'].with_user(
            self.manager).new({'partner_id': self.student.id,
                               'payment_method': method})
        return self.env['product.template'].with_context(
            active_test=False).search(wiz._product_domain())

    def _ref(self, xmlid):
        return self.env.ref(xmlid)

    # -- what each method offers -------------------------------------
    def test_free_offers_the_four_and_hides_the_trials(self):
        offered = self._offered('free')
        for xmlid in FREE:
            self.assertIn(self._ref(xmlid), offered, xmlid)
        for xmlid in TRIALS:
            self.assertNotIn(self._ref(xmlid), offered, xmlid)

    def test_cash_offers_the_trials_and_none_of_the_four(self):
        offered = self._offered('cash')
        for xmlid in TRIALS:
            self.assertIn(self._ref(xmlid), offered, xmlid)
        for xmlid in FREE:
            self.assertNotIn(self._ref(xmlid), offered, xmlid)

    # -- a cash trial, exactly as today -------------------------------
    def test_a_cash_trial_still_sells_and_spends_the_entitlement(self):
        trial = self._ref('fitness_packages.product_reformer_trial')
        self.assertFalse(self.TR._trial_taken(self.student, trial))
        self._wizard('cash', trial, amount_paid=12.0).action_create_sale()
        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)])
        self.assertEqual(len(order), 1)
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.fitness_payment_method, 'cash')
        self.assertEqual(order.order_line.product_id.product_tmpl_id, trial)
        self.assertEqual(order.order_line.fitness_remaining_classes, 1)
        self.assertTrue(self.TR._trial_taken(self.student, trial),
                        'a cash trial no longer spends the entitlement')

    # -- a free class under Free ---------------------------------------
    def test_a_free_class_is_given_with_a_reason_and_leaves_the_trial(self):
        product = self._ref('fitness_packages.product_courtesy_reformer')
        self._wizard('free', product,
                     reason='Came with a friend').action_create_sale()
        order = self.env['sale.order'].sudo().search(
            [('partner_id', '=', self.student.id)])
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.amount_total, 0.0)
        self.assertEqual(order.fitness_payment_method, 'free')
        line = order.order_line
        self.assertEqual(line.fitness_remaining_classes, 1)
        self.assertEqual(line.fitness_validity_end_date, date(2026, 10, 27))
        self.assertIn('Came with a friend',
                      ' '.join(order.message_ids.mapped('body')))
        for xmlid in TRIALS:
            self.assertFalse(self.TR._trial_taken(self.student,
                                                  self._ref(xmlid)), xmlid)

    def test_free_still_needs_a_reason(self):
        product = self._ref('fitness_packages.product_courtesy_barre')
        with self.assertRaises(UserError):
            self._wizard('free', product, reason='  ').action_create_sale()

    # -- the model refuses what the picker would not offer --------------
    def test_a_trial_given_free_is_refused_by_the_model(self):
        trial = self._ref('fitness_packages.product_barre_trial')
        with self.assertRaises(UserError) as caught:
            self._wizard('free', trial, reason='x').action_create_sale()
        self.assertIn('free trial', str(caught.exception))
        self.assertFalse(self.env['sale.order'].sudo().search_count(
            [('partner_id', '=', self.student.id)]))

    def test_a_free_class_sold_for_cash_is_refused_by_the_model(self):
        product = self._ref('fitness_packages.product_courtesy_barre')
        with self.assertRaises(UserError):
            self._wizard('cash', product, amount_paid=5.0).action_create_sale()
        self.assertFalse(self.env['sale.order'].sudo().search_count(
            [('partner_id', '=', self.student.id)]))
