# -*- coding: utf-8 -*-
"""Is this plan renewable now? One rule for the shop, the desk and the reminder.

The studio's rule (14 Oct): renewable from the moment the renewal reminder
goes out - N days before the plan ends, N = fitness.renewal_window_days,
default 3 - and at any time after it has ended. Running with more days
left: Active, and the desk's Renew (cash) says why and does nothing.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRenewalWindow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        G = env.ref
        cls.today = fields.Date.context_today(env['res.users'])
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RW Manager', 'login': 'rw.manager@example.invalid',
            'group_ids': [(6, 0, [G('base.group_user').id, G('fitness_core.group_fitness_manager').id])]})
        cls.month = env.ref('sale_subscription.subscription_plan_month')
        cls.plan = env['product.template'].create({
            'name': 'RW membership', 'list_price': 95.0, 'type': 'service',
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2})
        cls.pack = env['product.template'].create({
            'name': 'RW pack 5', 'list_price': 50.0, 'type': 'service',
            'fitness_is_package': True, 'fitness_class_count': 5, 'fitness_validity_days': 60,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group'})
        cls.seq = 0

    def _student(self):
        type(self).seq += 1
        n = self.seq
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RW Student %d' % n, 'login': 'rw.s%d@example.invalid' % n,
            'email': 'rw.s%d@example.invalid' % n,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]}).partner_id

    def _membership(self, partner, ends_in_days):
        so = self.env['sale.order'].create({
            'partner_id': partner.id, 'plan_id': self.month.id,
            'order_line': [(0, 0, {'product_id': self.plan.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 95.0})]})
        so.with_context(skip_fitness_notification=True).action_confirm()
        so.next_invoice_date = self.today + timedelta(days=ends_in_days)
        return so

    def _pack(self, partner, ends_in_days, left=5):
        so = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {'product_id': self.pack.product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': 50.0})]})
        so.with_context(skip_fitness_notification=True).action_confirm()
        line = so.order_line[:1]
        line.write({'fitness_validity_end_date': self.today + timedelta(days=ends_in_days),
                    'fitness_remaining_classes': left})
        return line

    # -- memberships -------------------------------------------------------

    def test_a_membership_before_the_window_is_active(self):
        p = self._student()
        self._membership(p, 10)
        st = p._fitness_renewal_state(self.plan)
        self.assertEqual(st['state'], 'active')
        self.assertEqual(st['opens_on'], self.today + timedelta(days=7))

    def test_a_membership_inside_the_window_is_renewable_from_its_end(self):
        p = self._student()
        so = self._membership(p, 2)
        st = p._fitness_renewal_state(self.plan)
        self.assertEqual(st['state'], 'renewable')
        self.assertEqual(st['continue_from'], so.next_invoice_date,
                         'a renewal must start on the old end, so she loses no days')

    def test_the_first_window_day_is_renewable(self):
        p = self._student()
        self._membership(p, 3)
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'renewable')

    def test_an_ended_membership_is_renewable(self):
        p = self._student()
        so = self._membership(p, 10)
        so.subscription_state = '6_churn'
        st = p._fitness_renewal_state(self.plan)
        self.assertEqual(st['state'], 'renewable')
        self.assertFalse(st['continue_from'], 'an ended plan restarts today')

    def test_a_paused_membership_is_held(self):
        """Paused is hers: not 'never held', so the shop does not sell it again."""
        p = self._student()
        so = self._membership(p, 10)
        so.subscription_state = '4_paused'
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'active')
        so.next_invoice_date = self.today + timedelta(days=2)
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'renewable')

    def test_never_held_is_an_ordinary_purchase(self):
        self.assertEqual(self._student()._fitness_renewal_state(self.plan)['state'], 'none')

    def test_the_window_is_the_one_parameter(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.renewal_window_days', '7')
        p = self._student()
        self._membership(p, 5)
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'renewable')

    # -- the desk follows the same rule ------------------------------------

    def test_renew_cash_outside_the_window_says_why_and_does_nothing(self):
        p = self._student()
        so = self._membership(p, 10)
        before = so.next_invoice_date
        invoices = so.invoice_ids
        with self.assertRaises(UserError) as caught:
            # English, whatever languages the database has installed: the
            # wording in es/ca is tested on its own below.
            so.with_user(self.manager).with_context(lang='en_US').action_fitness_renew_cash()
        self.assertIn('renewed', str(caught.exception))
        so.invalidate_recordset()
        self.assertEqual(so.next_invoice_date, before, 'the date moved')
        self.assertEqual(so.invoice_ids, invoices, 'an invoice was raised')

    def test_the_refusal_reads_in_the_managers_language(self):
        for code in ('es_ES', 'ca_ES'):
            self.env['res.lang']._activate_and_install_lang(code)
        for lang, words in (('es_ES', 'sigue en curso'), ('ca_ES', 'continua en curs'),
                            ('en_US', 'is still running')):
            with self.subTest(lang=lang):
                self.manager.lang = lang
                so = self._membership(self._student(), 10)
                with self.assertRaises(UserError) as caught:
                    so.with_user(self.manager).with_context(lang=lang).action_fitness_renew_cash()
                self.assertIn(words, str(caught.exception))

    def test_renew_cash_inside_the_window_renews(self):
        p = self._student()
        so = self._membership(p, 2)
        before = so.next_invoice_date
        so.with_user(self.manager).action_fitness_renew_cash()
        so.invalidate_recordset()
        self.assertGreater(so.next_invoice_date, before)

    # -- packs --------------------------------------------------------------

    def test_a_pack_with_time_and_credits_left_is_active(self):
        p = self._student()
        self._pack(p, 10)
        self.assertEqual(p._fitness_renewal_state(self.pack)['state'], 'active')

    def test_a_pack_inside_the_window_is_renewable(self):
        p = self._student()
        self._pack(p, 2)
        self.assertEqual(p._fitness_renewal_state(self.pack)['state'], 'renewable')

    def test_an_expired_pack_is_renewable(self):
        p = self._student()
        self._pack(p, -1)
        self.assertEqual(p._fitness_renewal_state(self.pack)['state'], 'renewable')

    def test_a_used_up_pack_is_renewable(self):
        p = self._student()
        self._pack(p, 30, left=0)
        self.assertEqual(p._fitness_renewal_state(self.pack)['state'], 'renewable')

    # -- the reminder reads the same window --------------------------------

    def test_the_reminder_goes_out_on_the_window_day(self):
        self.env['ir.config_parameter'].sudo().set_param('fitness.renewal_window_days', '5')
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RW Reminded', 'login': 'rw.rem@example.invalid', 'email': 'rw.rem@example.invalid',
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref('fitness_core.group_fitness_student').id])]})
        self._membership(user.partner_id, 5)
        self.env['fitness.booking']._cron_send_billing_reminders()
        self.assertEqual(self.env['fitness.notification'].sudo().search_count([
            ('user_id', '=', user.id), ('notification_type', '=', 'billing_reminder')]), 1,
            'the reminder did not use the renewal window')
