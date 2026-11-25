# -*- coding: utf-8 -*-
"""Renewals list, the studio's alerts, and the member's renewal reminder.

The list is a database view and reads "today" from Postgres in Madrid, so
these tests do not freeze the clock: every date is built from the studio's
real today, and every expected date is asked of the Python helper the
registration-fee rule uses - the point being that the list and that rule
cannot disagree.
"""
from datetime import timedelta

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from odoo.addons.fitness_core.models.studio_lang import studio_date, studio_lang
from odoo.addons.fitness_core.models.studio_time import studio_today
from odoo.addons.fitness_subscriptions.models.membership_dates import (
    FEE_WINDOW_DAYS, fitness_fee_free_until, fitness_renewal_pays_fee)

MANAGER = 'fitness_core.group_fitness_manager'
TEACHER = 'fitness_core.group_fitness_teacher'
STUDENT = 'fitness_core.group_fitness_student'


@tagged('post_install', '-at_install')
class TestRenewalsList(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        G = env.ref
        cls.today = studio_today()
        cls.month = env['sale.subscription.plan'].sudo().create({
            'name': 'RL Monthly', 'billing_period_value': 1, 'billing_period_unit': 'month'})
        cls.quarter = env['sale.subscription.plan'].sudo().create({
            'name': 'RL Quarterly', 'billing_period_value': 3, 'billing_period_unit': 'month'})
        cls.plan = env['product.template'].sudo().create({
            'name': 'RL Barre membership', 'list_price': 95.0, 'type': 'service',
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'barre', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2})
        cls.plan2 = env['product.template'].sudo().create({
            'name': 'RL Reformer membership', 'list_price': 120.0, 'type': 'service',
            'fitness_is_subscription_plan': True, 'recurring_invoice': True,
            'fitness_class_type': 'reformer', 'fitness_session_type': 'group',
            'weekly_class_allowance': 2})
        cls.other_sub = env['product.template'].sudo().create({
            'name': 'RL Not a fitness plan', 'list_price': 10.0, 'type': 'service',
            'recurring_invoice': True})
        cls.manager = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RL Manager', 'login': 'rl.manager@example.invalid',
            'email': 'rl.manager@example.invalid',
            'group_ids': [(6, 0, [G('base.group_user').id, G(MANAGER).id])]})
        cls.teacher = env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RL Teacher', 'login': 'rl.teacher@example.invalid',
            'email': 'rl.teacher@example.invalid',
            'group_ids': [(6, 0, [G('base.group_user').id, G(TEACHER).id])]})
        cls.seq = 0

    # -- fixtures ------------------------------------------------------------

    def _student(self, email=True):
        type(self).seq += 1
        n = self.seq
        return self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'RL Student %d' % n, 'login': 'rl.s%d@example.invalid' % n,
            'email': ('rl.s%d@example.invalid' % n) if email else False,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id,
                                  self.env.ref(STUDENT).id])]})

    def _membership(self, partner, start, next_date=None, price=95.0, plan=None,
                    method=None, product=None):
        """Confirmed; next_date given = billed up to the day before it."""
        so = self.env['sale.order'].sudo().create({
            'partner_id': partner.id, 'plan_id': (plan or self.month).id, 'start_date': start,
            'order_line': [(0, 0, {'product_id': (product or self.plan).product_variant_ids[:1].id,
                                   'product_uom_qty': 1, 'price_unit': price})]})
        if method:
            so.fitness_payment_method = method
        so.with_context(skip_fitness_notification=True).action_confirm()
        if next_date:
            so.next_invoice_date = next_date
        return so

    def _paid_to(self, partner, last_paid, **kw):
        """Billed, last paid day `last_paid`, started a month before."""
        return self._membership(partner, last_paid - timedelta(days=29),
                                last_paid + timedelta(days=1), **kw)

    def _row(self, so):
        self.env.flush_all()
        return self.env['fitness.renewal.report'].sudo().browse(so.id).exists()

    def _alerts(self, so, xmlid):
        return self.env['mail.message'].sudo().search([
            ('model', '=', 'sale.order'), ('res_id', '=', so.id),
            ('subtype_id', '=', self.env.ref(xmlid).id)])

    # -- one definition of the dates -------------------------------------------

    def test_the_list_and_the_helper_agree_on_every_shape(self):
        p = self._student().partner_id
        t = self.today
        billed = self._paid_to(p, t + timedelta(days=12))
        capped = self._paid_to(self._student().partner_id, t + timedelta(days=12))
        capped.end_date = t + timedelta(days=4)
        free_m = self._membership(self._student().partner_id, t - timedelta(days=3),
                                  price=0.0, method='free')
        free_q = self._membership(self._student().partner_id, t - timedelta(days=3),
                                  price=0.0, method='free', plan=self.quarter)
        waiting = self._membership(self._student().partner_id, t)
        closed = self._paid_to(self._student().partner_id, t - timedelta(days=20))
        closed.set_close()                      # Odoo's close writes today as the end
        cases = (billed, capped, free_m, free_q, waiting, closed)
        for so in cases:
            row = self._row(so)
            self.assertTrue(row, so.name)
            self.assertEqual(row.paid_up_to or None, so._fitness_paid_up_to(), so.name)
            self.assertEqual(row.fee_free_until or None,
                             fitness_fee_free_until(so._fitness_paid_up_to()), so.name)
        self.assertEqual(billed._fitness_paid_up_to(), t + timedelta(days=12))
        self.assertEqual(capped._fitness_paid_up_to(), t + timedelta(days=4))
        self.assertEqual(free_m._fitness_paid_up_to(),
                         free_m.start_date + self.month.billing_period - timedelta(days=1))
        self.assertEqual(free_q._fitness_paid_up_to(),
                         free_q.start_date + self.quarter.billing_period - timedelta(days=1))
        self.assertIsNone(waiting._fitness_paid_up_to(), 'nothing paid yet is not an end')
        self.assertEqual(closed._fitness_paid_up_to(), t - timedelta(days=20),
                         "Odoo's close day is not her last paid day")

    # -- status ----------------------------------------------------------------

    def test_due_soon_is_five_days_left_or_fewer(self):
        t = self.today
        five = self._paid_to(self._student().partner_id, t + timedelta(days=4))
        six = self._paid_to(self._student().partner_id, t + timedelta(days=5))
        last = self._paid_to(self._student().partner_id, t)
        self.assertEqual((self._row(five).days_left, self._row(five).status), (5, 'due_soon'))
        self.assertEqual((self._row(six).days_left, self._row(six).status), (6, 'running'))
        self.assertEqual((self._row(last).days_left, self._row(last).status), (1, 'due_soon'))

    def test_ended_inside_the_window_dropped_after_it_and_the_fee_agrees(self):
        t = self.today
        for days_ago, status, fee in ((1, 'ended', False),
                                      (FEE_WINDOW_DAYS, 'ended', False),
                                      (FEE_WINDOW_DAYS + 1, 'dropped', True)):
            so = self._paid_to(self._student().partner_id, t - timedelta(days=days_ago))
            row = self._row(so)
            self.assertEqual(row.status, status, days_ago)
            self.assertEqual(fitness_renewal_pays_fee(row.paid_up_to, t), fee, days_ago)

    def test_free_and_running(self):
        t = self.today
        free = self._membership(self._student().partner_id, t, price=0.0, method='free',
                                plan=self.quarter)
        running = self._paid_to(self._student().partner_id, t + timedelta(days=20),
                                method='stripe')
        waiting = self._membership(self._student().partner_id, t, method='transfer')
        self.assertEqual((self._row(free).status, self._row(free).payment_method), ('free', 'free'))
        self.assertTrue(self._row(free).is_free)
        self.assertEqual(self._row(running).status, 'running')
        self.assertEqual(self._row(waiting).status, 'running')
        self.assertFalse(self._row(waiting).paid_up_to)
        free_due = self._membership(self._student().partner_id, t - timedelta(days=27),
                                    price=0.0, method='free')
        row = self._row(free_due)
        if row.days_left <= 5:            # a month is 28 to 31 days
            self.assertEqual(row.status, 'due_soon')
            self.assertTrue(row.is_free)

    def test_a_renewed_membership_gives_way_to_its_renewal(self):
        p = self._student().partner_id
        old = self._paid_to(p, self.today + timedelta(days=2))
        new = self._membership(p, self.today + timedelta(days=3))
        self.assertFalse(self._row(old), 'the renewed membership is still listed')
        self.assertTrue(self._row(new))
        self.assertEqual(old._fitness_renewed_by(), new)

    # -- a move to another plan is not a drop ------------------------------------

    def _fee_due_today(self, partner):
        last = self.env['sale.order']._fitness_last_paid_day_of(partner)
        return fitness_renewal_pays_fee(last, self.today)

    def test_a_plan_switch_is_carried_on_and_no_ended_alert_fires(self):
        t = self.today
        p = self._student().partner_id
        old = self._paid_to(p, t - timedelta(days=10))
        new = self._paid_to(p, t + timedelta(days=25), product=self.plan2)
        self.assertEqual(old._fitness_renewed_by(), new)
        self.assertFalse(self._row(old), 'a member who changed plan is listed under the old one')
        self.assertEqual(self._row(new).status, 'running')
        self.env['fitness.renewal.report']._cron_fitness_renewal_alerts()
        self.assertFalse(self._alerts(old, 'fitness_portal.mt_fitness_membership_ended'),
                         'a plan switch was announced as a membership ended without renewal')
        self.assertFalse(self._alerts(new, 'fitness_portal.mt_fitness_membership_ended'))
        self.assertFalse(self._fee_due_today(p))
        # The shop's Renew button keeps its own rule: the old plan's product
        # is still offered for renewal, as before.
        self.assertEqual(p._fitness_renewal_state(self.plan)['state'], 'renewable')

    def test_a_switch_then_a_drop_is_dropped_and_the_fee_agrees(self):
        t = self.today
        p = self._student().partner_id
        self._paid_to(p, t - timedelta(days=100))
        new = self._paid_to(p, t - timedelta(days=FEE_WINDOW_DAYS + 3), product=self.plan2)
        row = self._row(new)
        self.assertEqual(row.status, 'dropped')
        self.assertTrue(self._fee_due_today(p))

    def test_plans_side_by_side_read_the_member_s_last_paid_day(self):
        t = self.today
        p = self._student().partner_id
        first = self._paid_to(p, t + timedelta(days=20))
        second = self._paid_to(p, t + timedelta(days=2), product=self.plan2)
        self.assertFalse(self._row(first))
        row = self._row(second)
        self.assertEqual(row.paid_up_to, t + timedelta(days=2))
        self.assertEqual(row.member_paid_up_to, t + timedelta(days=20))
        self.assertEqual(row.status, 'running', 'she is paid up for 20 more days')
        self.assertFalse(self._fee_due_today(p))

    def test_every_row_agrees_with_the_fee_rule(self):
        t = self.today
        for days in (-10, 1, FEE_WINDOW_DAYS, FEE_WINDOW_DAYS + 1, 90):
            p = self._student().partner_id
            self._paid_to(p, t - timedelta(days=days))
        p = self._student().partner_id
        self._paid_to(p, t - timedelta(days=60))
        self._paid_to(p, t - timedelta(days=5), product=self.plan2)
        self.env.flush_all()
        rows = self.env['fitness.renewal.report'].sudo().search([('member_id.name', 'like', 'RL Student')])
        self.assertTrue(rows)
        for row in rows:
            last = self.env['sale.order']._fitness_last_paid_day_of(row.member_id)
            self.assertEqual(row.member_paid_up_to or None, last, row.order_ref)
            self.assertEqual(row.status == 'dropped', fitness_renewal_pays_fee(last, t), row.order_ref)

    def test_grouped_by_status(self):
        self._paid_to(self._student().partner_id, self.today + timedelta(days=1))
        self.env.flush_all()
        groups = self.env['fitness.renewal.report'].with_user(self.manager).formatted_read_group(
            [], ['status'], ['__count'])
        self.assertIn('due_soon', [g['status'] for g in groups])

    # -- who sees it -----------------------------------------------------------

    def test_only_managers_read_the_list(self):
        self._paid_to(self._student().partner_id, self.today + timedelta(days=1))
        self.env.flush_all()
        Report = self.env['fitness.renewal.report']
        self.assertTrue(Report.with_user(self.manager).search([]))
        for user in (self.teacher, self._student()):
            with self.assertRaises(AccessError):
                Report.with_user(user).search([])
        menu = self.env.ref('fitness_portal.menu_fitness_renewal_report')
        self.assertEqual(menu.group_ids, self.env.ref(MANAGER))

    # -- alerts ----------------------------------------------------------------

    def test_each_alert_fires_once_to_the_managers_only(self):
        t = self.today
        student = self._student()
        due = self._paid_to(student.partner_id, t + timedelta(days=3))
        ended = self._paid_to(self._student().partner_id, t - timedelta(days=2))
        dropped = self._paid_to(self._student().partner_id, t - timedelta(days=FEE_WINDOW_DAYS + 5))
        far = self._paid_to(self._student().partner_id, t + timedelta(days=20))
        Report = self.env['fitness.renewal.report']
        Report._cron_fitness_renewal_alerts()
        Report._cron_fitness_renewal_alerts()
        due_msg = self._alerts(due, 'fitness_portal.mt_fitness_renewal_due')
        end_msg = self._alerts(ended, 'fitness_portal.mt_fitness_membership_ended')
        self.assertEqual(len(due_msg), 1, 'the due-soon alert repeated or never fired')
        self.assertEqual(len(end_msg), 1, 'the ended alert repeated or never fired')
        self.assertFalse(self._alerts(dropped, 'fitness_portal.mt_fitness_membership_ended'),
                         'a membership dropped long ago was announced as just ended')
        self.assertFalse(self._alerts(far, 'fitness_portal.mt_fitness_renewal_due'))
        self.assertIn(self.manager.partner_id, due_msg.partner_ids)
        self.assertNotIn(self.teacher.partner_id, due_msg.partner_ids)
        self.assertNotIn(student.partner_id, due_msg.partner_ids)
        self.assertTrue(due_msg.subtype_id.internal)
        self.assertIn(studio_date(self.env, t + timedelta(days=3), 'd MMM y', studio_lang(self.env)),
                      str(due_msg.body))
        # The manager reads it in her inbox; the member never sees it on her
        # order, and the instructor cannot read it.
        self.assertTrue(self.env['mail.message'].with_user(self.manager).search(
            [('id', '=', due_msg.id)]))
        self.assertEqual(due_msg.with_user(self.manager).read(['body'])[0]['body'], due_msg.body)
        self.assertFalse(self.env['mail.message'].with_user(student).search([('id', '=', due_msg.id)]))
        self.assertFalse(self.env['mail.message'].with_user(self.teacher).search([('id', '=', due_msg.id)]))

    def test_no_alert_for_a_renewed_membership_and_free_is_labelled(self):
        t = self.today
        p = self._student().partner_id
        old = self._paid_to(p, t + timedelta(days=2))
        self._membership(p, t + timedelta(days=3))
        free = self._membership(self._student().partner_id, t - timedelta(days=40),
                                price=0.0, method='free')
        free.end_date = t - timedelta(days=3)
        self.env['fitness.renewal.report']._cron_fitness_renewal_alerts()
        self.assertFalse(self._alerts(old, 'fitness_portal.mt_fitness_renewal_due'))
        msg = self._alerts(free, 'fitness_portal.mt_fitness_membership_ended')
        self.assertEqual(len(msg), 1)
        lang = studio_lang(self.env)
        marker = self.env(context=dict(self.env.context, lang=lang))._(
            '%(plan)s (free)', plan='@@').replace('@@', '').strip()
        self.assertTrue(marker)
        self.assertIn(marker, str(msg.body))

    # -- the member's reminder ---------------------------------------------------

    def _reminders(self, user):
        return self.env['fitness.notification'].sudo().search([
            ('user_id', '=', user.id), ('notification_type', '=', 'billing_reminder')])

    def _remind(self, user, next_date, product=None):
        so = self._membership(user.partner_id, self.today - timedelta(days=20), next_date,
                              product=product)
        self.env['fitness.booking']._cron_send_billing_reminders()
        return so

    def test_the_reminder_quotes_her_last_paid_day(self):
        window = self.env['sale.order']._fitness_renewal_window_days()
        user = self._student()
        nxt = self.today + timedelta(days=window)
        self._remind(user, nxt)
        sent = self._reminders(user)
        self.assertEqual(len(sent), 1)
        lang = user.lang or 'en_US'
        self.assertIn(studio_date(self.env, nxt - timedelta(days=1), 'd MMM y', lang), sent.body)
        self.assertNotIn(studio_date(self.env, nxt, 'd MMM y', lang), sent.body)

    def test_no_reminder_for_a_subscription_that_is_not_a_membership(self):
        window = self.env['sale.order']._fitness_renewal_window_days()
        user = self._student()
        self._remind(user, self.today + timedelta(days=window), product=self.other_sub)
        self.assertFalse(self._reminders(user))

    def test_no_reminder_once_renewed(self):
        window = self.env['sale.order']._fitness_renewal_window_days()
        user = self._student()
        nxt = self.today + timedelta(days=window)
        old = self._membership(user.partner_id, self.today - timedelta(days=20), nxt)
        self._membership(user.partner_id, nxt)
        old.end_date = nxt - timedelta(days=1)
        self.env['fitness.booking']._cron_send_billing_reminders()
        self.assertFalse(self._reminders(user))


@tagged('post_install', '-at_install')
class TestRenewalsListLanguages(TransactionCase):
    """The screen and the alerts read in the studio's three languages."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for code in ('es_ES', 'ca_ES'):
            cls.env['res.lang']._activate_and_install_lang(code)
        cls.env['res.lang']._activate_lang('en_US')

    def test_labels_and_alerts_in_three_languages(self):
        Report = self.env['fitness.renewal.report']
        expect = {'en_US': ('Due soon', 'Renewals', '%(plan)s (free)'),
                  'es_ES': ('Vence pronto', 'Renovaciones', '%(plan)s (gratis)'),
                  'ca_ES': ('Venç aviat', 'Renovacions', '%(plan)s (gratuïta)')}
        menu = self.env.ref('fitness_portal.menu_fitness_renewal_report')
        for lang, (due, title, free) in expect.items():
            labels = dict(Report.with_context(lang=lang)._fields['status']._description_selection(
                Report.with_context(lang=lang).env))
            self.assertEqual(labels['due_soon'], due, lang)
            self.assertEqual(menu.with_context(lang=lang).name, title, lang)
            tr = self.env(context=dict(self.env.context, lang=lang))._
            self.assertEqual(tr('%(plan)s (free)'), free, lang)
